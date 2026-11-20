"""Asynchronous client (asyncio). Same methods as ScrapeCore, awaitable."""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Sequence

import httpx

from . import _base, _errors


class AsyncScrapeCore:
    """Async ScrapeCore client: `async with AsyncScrapeCore() as sc: page = await sc.scrape(url)`."""

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 120.0,
                 max_retries: int = 2, user_agent: str | None = None, http_client: httpx.AsyncClient | None = None):
        self._s = _base.Settings(api_key, base_url, timeout, max_retries, user_agent)
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._own = http_client is None

    # ── plumbing ──────────────────────────────────────────────────────────────────────────
    async def close(self) -> None:
        if self._own:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncScrapeCore":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                idempotent_key: str | None = None, raw: bool = False) -> Any:
        """Any /api/v1 endpoint. Retries what is safe to retry. raw=True returns the body as text."""
        headers = dict(self._s.headers)
        if idempotent_key:
            headers["Idempotency-Key"] = idempotent_key
        attempt = 0
        while True:
            try:
                r = await self._http.request(method, self._s.url(path), json=json, params=params, headers=headers,
                                       timeout=self._s.timeout)
                if raw and r.status_code < 400:
                    return r.text
                return _base.parse(r.status_code, r.headers, r.content)
            except _errors.ScrapeCoreError as e:
                err = e
            except httpx.TimeoutException as e:
                err = _errors.APIConnectionError(f"timed out: {e}", code="TIMEOUT", retryable=True)
            except httpx.HTTPError as e:
                err = _errors.APIConnectionError(f"could not reach the API: {e}", code="CONNECTION_ERROR",
                                                 retryable=True)
            if not _base.should_retry(err, attempt, self._s.max_retries):
                raise err
            await asyncio.sleep(_base.backoff(attempt, err))
            attempt += 1

    # ── scraping ──────────────────────────────────────────────────────────────────────────
    async def scrape(self, url: str, *, format: str = "html", js_render: bool | None = None, use_proxy: bool | None = None,
               waf: bool | None = None, max_age: int | None = None) -> dict:
        """Scrape one page. format: "html", "markdown" or "text". max_age (seconds): a stored
        result at most this old is fine (faster)."""
        return await self.request("POST", "scrape", json=_base.scrape_body(url, format, js_render, use_proxy, waf, max_age))

    async def markdown(self, url: str, **kw) -> str:
        """The page as Markdown (just the text)."""
        return (await self.scrape(url, format="markdown", **kw)).get("markdown") or ""

    async def batch(self, urls: Sequence[str], *, js_render: bool | None = None, use_proxy: bool | None = None,
              waf: bool | None = None) -> dict:
        """Up to 50 URLs in one call (plan feature "batch")."""
        return await self.request("POST", "batch", json=_base._clean({"urls": list(urls), "js_render": js_render,
                                                                 "use_proxy": use_proxy, "waf": waf}))

    async def screenshot(self, url: str, *, full_page: bool = False, wait: bool = True, timeout: float = 120, **options) -> dict:
        """A screenshot (base64 image in result["image_base64"]). Options: device, width, height,
        format ("png"/"jpeg"), selector, wait_for, dark_mode, block_ads, hide_cookie_banners, ..."""
        body = {"url": url, "full_page": full_page, "sync": False, **options}
        job = await self.request("POST", "screenshot", json=body, idempotent_key=_base.idempotency_key())
        if "job_id" not in job or job.get("status") != "queued":
            return job                                         # ran directly
        return (await self.wait_for_job(job["job_id"], timeout=timeout))["result"] if wait else job

    async def extract(self, url: str, selectors: dict, *, js_render: bool | None = None) -> dict:
        """CSS selectors -> values, e.g. {"title": "h1", "prices": ".price"}."""
        return await self.request("POST", "extract", json=_base._clean({"url": url, "selectors": selectors,
                                                                   "js_render": js_render, "sync": True}))

    # ── site discovery and crawling ───────────────────────────────────────────────────────
    async def map(self, url: str, *, limit: int | None = None, search: str | None = None,
            include_subdomains: bool | None = None, respect_robots: bool | None = None) -> dict:
        """Every URL of a site (sitemaps + links). Returns {"urls": [...], "count": n, ...}."""
        return await self.request("POST", "map", json=_base.map_body(url, limit, search, include_subdomains, respect_robots))

    async def crawl(self, url: str, *, max_depth: int | None = None, limit: int | None = None,
              include_paths: Sequence[str] | None = None, exclude_paths: Sequence[str] | None = None,
              include_subdomains: bool | None = None, respect_robots: bool | None = None,
              js_render: bool | None = None, use_proxy: bool | None = None,
              wait: bool = False, timeout: float = 1800) -> dict:
        """Start a crawl job (returns {"job_id", ...}). wait=True: block until it ends and return
        the finished job; read the pages with crawl_pages(job_id)."""
        body = _base.crawl_body(url, max_depth, limit, list(include_paths) if include_paths else None,
                                list(exclude_paths) if exclude_paths else None, include_subdomains,
                                respect_robots, js_render, use_proxy)
        job = await self.request("POST", "crawl", json=body, idempotent_key=_base.idempotency_key())
        return await self.wait_for_job(job["job_id"], timeout=timeout, raise_on_failure=False) if wait else job

    async def crawl_pages(self, job_id: str, *, only_ok: bool = False, page_size: int = 100) -> AsyncIterator[dict]:
        """Every page of a crawl (url, title, markdown, status_code, ...), fetched page by page."""
        offset = 0
        while True:
            r = await self.request("GET", f"crawl/{job_id}/pages",
                             params={"offset": offset, "limit": page_size, "only_ok": str(only_ok).lower()})
            pages = r.get("pages") or []
            for p in pages:
                yield p
            offset += len(pages)
            if not pages or offset >= int(r.get("total") or 0):
                return

    # ── jobs ──────────────────────────────────────────────────────────────────────────────
    async def scrape_async(self, url: str, **kw) -> dict:
        """Queue a scrape; returns {"job_id", "status": "queued", ...}. See wait_for_job()."""
        body = _base.scrape_body(url, kw.pop("format", None), kw.pop("js_render", None), kw.pop("use_proxy", None),
                                 kw.pop("waf", None), None)
        return await self.request("POST", "async", json=body, idempotent_key=_base.idempotency_key())

    async def get_job(self, job_id: str) -> dict:
        return await self.request("GET", f"job/{job_id}")

    async def wait_for_job(self, job_id: str, *, timeout: float = 300, poll_interval: float = 1.0,
                     raise_on_failure: bool = True) -> dict:
        """Poll until the job is success / failure / cancelled. Raises JobFailedError (failure,
        cancelled) unless raise_on_failure=False, and JobTimeoutError after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        delay = poll_interval
        while True:
            job = await self.get_job(job_id)
            if job.get("status") in _base.TERMINAL:
                if raise_on_failure and job["status"] != "success":
                    raise _base.job_failed(job)
                return job
            if time.monotonic() + delay > deadline:
                raise _errors.JobTimeoutError(f"job {job_id} still {job.get('status')} after {timeout}s", job,
                                              code="JOB_TIMEOUT")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 10.0)

    async def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued job, or stop a running crawl after its current page."""
        return await self.request("POST", f"job/{job_id}/cancel")

    async def jobs(self, *, limit: int = 50, offset: int = 0, status: str | None = None, type: str | None = None) -> list:
        return await self.request("GET", "jobs", params=_base._clean({"limit": limit, "offset": offset,
                                                                  "status": status, "type": type}))

    # ── AI extraction and web search (bring your own provider key) ───────────────────────
    async def ai_extract(self, url: str, *, prompt: str | None = None, schema: dict | None = None, model: str | None = None,
                   js_render: bool | None = None, use_proxy: bool | None = None) -> dict:
        """Structured data from a page with Claude, using the Anthropic key saved in your dashboard
        (Integrations → AI extraction). Give a prompt, a JSON schema, or both. Returns {"data", ...}."""
        return await self.request("POST", "extract/ai", json=_base._clean({"url": url, "prompt": prompt, "schema": schema,
                                                                      "model": model, "js_render": js_render,
                                                                      "use_proxy": use_proxy}))

    async def search(self, query: str, *, limit: int | None = None, scrape: bool | None = None, format: str | None = None,
               provider: str | None = None, max_chars: int | None = None) -> dict:
        """Web search (your Brave / Serper key) and, by default, scrape each result as Markdown."""
        return await self.request("POST", "search", json=_base._clean({"query": query, "limit": limit, "scrape": scrape,
                                                                  "format": format, "provider": provider,
                                                                  "max_chars": max_chars}))

    async def crawl_export(self, job_id: str, format: str = "jsonl", *, chunk_size: int | None = None,
                     overlap: int | None = None) -> str:
        """A crawl as one AI-ready document: "jsonl", "markdown", "chunks" (RAG-sized JSONL),
        "llms" (llms.txt) or "llms-full" (llms-full.txt)."""
        return await self.request("GET", f"crawl/{job_id}/export", raw=True,
                                params=_base._clean({"format": format, "chunk_size": chunk_size, "overlap": overlap}))

    # ── page-change monitors ─────────────────────────────────────────────────────────────
    async def monitors(self) -> dict:
        """{"monitors": [...], "limit": n, "intervals": [...]}"""
        return await self.request("GET", "monitors")

    async def create_monitor(self, url: str, *, interval_minutes: int = 1440, name: str | None = None,
                       selector: str | None = None, ignore_patterns: Sequence[str] | None = None,
                       min_change_chars: int | None = None, notify_email: bool | None = None,
                       js_render: bool | None = None, use_proxy: bool | None = None) -> dict:
        """Watch a page (optionally one CSS selector of it) and get alerted when it changes."""
        return await self.request("POST", "monitors", json=_base._clean({
            "url": url, "interval_minutes": interval_minutes, "name": name, "selector": selector,
            "ignore_patterns": list(ignore_patterns) if ignore_patterns else None, "min_change_chars": min_change_chars,
            "notify_email": notify_email, "js_render": js_render, "use_proxy": use_proxy}))

    async def get_monitor(self, monitor_id: str) -> dict:
        return await self.request("GET", f"monitors/{monitor_id}")

    async def update_monitor(self, monitor_id: str, **changes) -> dict:
        """Change any setting; status="paused" / "active" pauses or resumes."""
        return await self.request("PATCH", f"monitors/{monitor_id}", json=_base._clean(changes))

    async def delete_monitor(self, monitor_id: str) -> dict:
        return await self.request("DELETE", f"monitors/{monitor_id}")

    async def check_monitor(self, monitor_id: str) -> dict:
        """Check now. Returns {"changed": bool, "summary"?, "monitor": {...}}."""
        return await self.request("POST", f"monitors/{monitor_id}/check")

    async def monitor_changes(self, monitor_id: str, *, limit: int = 20) -> list:
        """Detected changes, newest first, each with a unified "diff"."""
        return (await self.request("GET", f"monitors/{monitor_id}/changes", params={"limit": limit}))["changes"]

    # ── account ───────────────────────────────────────────────────────────────────────────
    async def usage(self) -> dict:
        return await self.request("GET", "usage")

    async def rate_limit(self) -> dict:
        return await self.request("GET", "rate-limit")
