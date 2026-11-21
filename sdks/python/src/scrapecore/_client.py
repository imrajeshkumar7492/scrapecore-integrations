"""Synchronous client."""
from __future__ import annotations

import time
from typing import Any, Iterator, Sequence

import httpx

from . import _base, _errors


class ScrapeCore:
    """ScrapeCore API client.

        from scrapecore import ScrapeCore
        sc = ScrapeCore()                         # reads SCRAPECORE_API_KEY
        page = sc.scrape("https://example.com", format="markdown")
        print(page["markdown"])

    Failed scrapes are not charged. Rate-limit and server errors are retried automatically
    (max_retries, honouring Retry-After); every other error raises a ScrapeCoreError subclass.
    """

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 120.0,
                 max_retries: int = 2, user_agent: str | None = None, http_client: httpx.Client | None = None):
        self._s = _base.Settings(api_key, base_url, timeout, max_retries, user_agent)
        self._http = http_client or httpx.Client(timeout=timeout)
        self._own = http_client is None

    # ── plumbing ──────────────────────────────────────────────────────────────────────────
    def close(self) -> None:
        if self._own:
            self._http.close()

    def __enter__(self) -> "ScrapeCore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                idempotent_key: str | None = None, raw: bool | str = False) -> Any:
        """Any /api/v1 endpoint. Retries what is safe to retry. raw=True returns the body as text."""
        headers = dict(self._s.headers)
        if idempotent_key:
            headers["Idempotency-Key"] = idempotent_key
        attempt = 0
        while True:
            try:
                r = self._http.request(method, self._s.url(path), json=json, params=params, headers=headers,
                                       timeout=self._s.timeout)
                if raw and r.status_code < 400:
                    return r.content if raw == "bytes" else r.text
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
            time.sleep(_base.backoff(attempt, err))
            attempt += 1

    # ── scraping ──────────────────────────────────────────────────────────────────────────
    def scrape(self, url: str, *, format: str = "html", js_render: bool | None = None, use_proxy: bool | None = None,
               waf: bool | None = None, max_age: int | None = None) -> dict:
        """Scrape one page. format: "html", "markdown" or "text". max_age (seconds): a stored
        result at most this old is fine (faster)."""
        return self.request("POST", "scrape", json=_base.scrape_body(url, format, js_render, use_proxy, waf, max_age))

    def markdown(self, url: str, **kw) -> str:
        """The page as Markdown (just the text)."""
        return self.scrape(url, format="markdown", **kw).get("markdown") or ""

    def batch(self, urls: Sequence[str], *, js_render: bool | None = None, use_proxy: bool | None = None,
              waf: bool | None = None) -> dict:
        """Up to 50 URLs in one call (plan feature "batch")."""
        return self.request("POST", "batch", json=_base._clean({"urls": list(urls), "js_render": js_render,
                                                                 "use_proxy": use_proxy, "waf": waf}))

    def screenshot(self, url: str, *, full_page: bool = False, wait: bool = True, timeout: float = 120, **options) -> dict:
        """A screenshot (base64 image in result["image_base64"]). Options: device, width, height,
        format ("png"/"jpeg"), selector, wait_for, dark_mode, block_ads, hide_cookie_banners, ..."""
        body = {"url": url, "full_page": full_page, "sync": False, **options}
        job = self.request("POST", "screenshot", json=body, idempotent_key=_base.idempotency_key())
        if "job_id" not in job or job.get("status") != "queued":
            return job                                         # ran directly
        return self.wait_for_job(job["job_id"], timeout=timeout)["result"] if wait else job

    def extract(self, url: str, selectors: dict, *, js_render: bool | None = None) -> dict:
        """CSS selectors -> values, e.g. {"title": "h1", "prices": ".price"}."""
        return self.request("POST", "extract", json=_base._clean({"url": url, "selectors": selectors,
                                                                   "js_render": js_render, "sync": True}))

    # ── site discovery and crawling ───────────────────────────────────────────────────────
    def map(self, url: str, *, limit: int | None = None, search: str | None = None,
            include_subdomains: bool | None = None, respect_robots: bool | None = None) -> dict:
        """Every URL of a site (sitemaps + links). Returns {"urls": [...], "count": n, ...}."""
        return self.request("POST", "map", json=_base.map_body(url, limit, search, include_subdomains, respect_robots))

    def crawl(self, url: str, *, max_depth: int | None = None, limit: int | None = None,
              include_paths: Sequence[str] | None = None, exclude_paths: Sequence[str] | None = None,
              include_subdomains: bool | None = None, respect_robots: bool | None = None,
              js_render: bool | None = None, use_proxy: bool | None = None,
              wait: bool = False, timeout: float = 1800) -> dict:
        """Start a crawl job (returns {"job_id", ...}). wait=True: block until it ends and return
        the finished job; read the pages with crawl_pages(job_id)."""
        body = _base.crawl_body(url, max_depth, limit, list(include_paths) if include_paths else None,
                                list(exclude_paths) if exclude_paths else None, include_subdomains,
                                respect_robots, js_render, use_proxy)
        job = self.request("POST", "crawl", json=body, idempotent_key=_base.idempotency_key())
        return self.wait_for_job(job["job_id"], timeout=timeout, raise_on_failure=False) if wait else job

    def crawl_pages(self, job_id: str, *, only_ok: bool = False, page_size: int = 100) -> Iterator[dict]:
        """Every page of a crawl (url, title, markdown, status_code, ...), fetched page by page."""
        offset = 0
        while True:
            r = self.request("GET", f"crawl/{job_id}/pages",
                             params={"offset": offset, "limit": page_size, "only_ok": str(only_ok).lower()})
            pages = r.get("pages") or []
            yield from pages
            offset += len(pages)
            if not pages or offset >= int(r.get("total") or 0):
                return

    # ── jobs ──────────────────────────────────────────────────────────────────────────────
    def scrape_async(self, url: str, **kw) -> dict:
        """Queue a scrape; returns {"job_id", "status": "queued", ...}. See wait_for_job()."""
        body = _base.scrape_body(url, kw.pop("format", None), kw.pop("js_render", None), kw.pop("use_proxy", None),
                                 kw.pop("waf", None), None)
        return self.request("POST", "async", json=body, idempotent_key=_base.idempotency_key())

    def get_job(self, job_id: str) -> dict:
        return self.request("GET", f"job/{job_id}")

    def wait_for_job(self, job_id: str, *, timeout: float = 300, poll_interval: float = 1.0,
                     raise_on_failure: bool = True) -> dict:
        """Poll until the job is success / failure / cancelled. Raises JobFailedError (failure,
        cancelled) unless raise_on_failure=False, and JobTimeoutError after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        delay = poll_interval
        while True:
            job = self.get_job(job_id)
            if job.get("status") in _base.TERMINAL:
                if raise_on_failure and job["status"] != "success":
                    raise _base.job_failed(job)
                return job
            if time.monotonic() + delay > deadline:
                raise _errors.JobTimeoutError(f"job {job_id} still {job.get('status')} after {timeout}s", job,
                                              code="JOB_TIMEOUT")
            time.sleep(delay)
            delay = min(delay * 1.5, 10.0)

    def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued job, or stop a running crawl after its current page."""
        return self.request("POST", f"job/{job_id}/cancel")

    def jobs(self, *, limit: int = 50, offset: int = 0, status: str | None = None, type: str | None = None) -> list:
        return self.request("GET", "jobs", params=_base._clean({"limit": limit, "offset": offset,
                                                                  "status": status, "type": type}))

    # ── AI extraction (your own AI provider key) ───────────────────────
    def ai_extract(self, url: str, *, prompt: str | None = None, schema: dict | None = None, model: str | None = None,
                   provider: str | None = None, records: str | None = None,
                   js_render: bool | None = None, use_proxy: bool | None = None) -> dict:
        """Structured data from ONE page with your own AI provider key (any provider connected in
        Dashboard → AI Extraction: OpenAI, Anthropic, Gemini, Mistral, ...; default = your default one).
        Give a prompt, a JSON schema, or both. records="list" returns every item. Returns {"data", ...}.
        For many pages, sitemaps or whole sites use ai_job()."""
        return self.request("POST", "extract/ai", json=_base._clean({"url": url, "prompt": prompt, "schema": schema,
                                                                      "model": model, "provider": provider, "records": records, "js_render": js_render,
                                                                      "use_proxy": use_proxy}))

    def crawl_export(self, job_id: str, format: str = "jsonl", *, chunk_size: int | None = None,
                     overlap: int | None = None) -> str:
        """A crawl as one AI-ready document: "jsonl", "markdown", "chunks" (RAG-sized JSONL),
        "llms" (llms.txt) or "llms-full" (llms-full.txt)."""
        return self.request("GET", f"crawl/{job_id}/export", raw=True,
                                params=_base._clean({"format": format, "chunk_size": chunk_size, "overlap": overlap}))

    # ── page-change monitors ─────────────────────────────────────────────────────────────
    def monitors(self) -> dict:
        """{"monitors": [...], "limit": n, "intervals": [...]}"""
        return self.request("GET", "monitors")

    def create_monitor(self, url: str, *, interval_minutes: int = 1440, name: str | None = None,
                       selector: str | None = None, ignore_patterns: Sequence[str] | None = None,
                       min_change_chars: int | None = None, notify_email: bool | None = None,
                       js_render: bool | None = None, use_proxy: bool | None = None) -> dict:
        """Watch a page (optionally one CSS selector of it) and get alerted when it changes."""
        return self.request("POST", "monitors", json=_base._clean({
            "url": url, "interval_minutes": interval_minutes, "name": name, "selector": selector,
            "ignore_patterns": list(ignore_patterns) if ignore_patterns else None, "min_change_chars": min_change_chars,
            "notify_email": notify_email, "js_render": js_render, "use_proxy": use_proxy}))

    def get_monitor(self, monitor_id: str) -> dict:
        return self.request("GET", f"monitors/{monitor_id}")

    def update_monitor(self, monitor_id: str, **changes) -> dict:
        """Change any setting; status="paused" / "active" pauses or resumes."""
        return self.request("PATCH", f"monitors/{monitor_id}", json=_base._clean(changes))

    def delete_monitor(self, monitor_id: str) -> dict:
        return self.request("DELETE", f"monitors/{monitor_id}")

    def check_monitor(self, monitor_id: str) -> dict:
        """Check now. Returns {"changed": bool, "summary"?, "monitor": {...}}."""
        return self.request("POST", f"monitors/{monitor_id}/check")

    def monitor_changes(self, monitor_id: str, *, limit: int = 20) -> list:
        """Detected changes, newest first, each with a unified "diff"."""
        return (self.request("GET", f"monitors/{monitor_id}/changes", params={"limit": limit}))["changes"]

    # ── AI Extraction jobs (your own AI provider key; many URLs, sitemaps, whole sites) ─────
    def ai_providers(self) -> dict:
        """Your connected AI providers (keys masked) and the default one."""
        return self.request("GET", "ai/providers")

    def ai_job(self, urls: Sequence[str] | None = None, *, instructions: str = "", schema: dict | None = None,
               fields: list | None = None, schema_id: str | None = None, records: str = "single",
               provider: str | None = None, model: str | None = None, sitemap: str | None = None,
               site: str | None = None, name: str | None = None, project: str | None = None,
               wait: bool = False, timeout: float = 3600, **options) -> dict:
        """Start an AI extraction job. Give urls, or sitemap=..., or site=... (discover its pages).
        records="list" extracts every item on each page. options: temperature, max_tokens,
        missing_value, dedupe_on, js_render, use_proxy. wait=True blocks until the job ends."""
        if sitemap or site:
            source = {"type": "sitemap" if sitemap else "discover", "value": sitemap or site}
        else:
            source = {"type": "urls"}
        body = _base._clean({"urls": list(urls or []), "source": source, "instructions": instructions,
                             "json_schema": schema, "fields": fields, "schema_id": schema_id, "records": records,
                             "provider": provider, "model": model, "name": name, "project": project,
                             "mode": "bulk" if urls and len(urls) > 1 else ("multipage" if site else "natural"),
                             "options": _base._clean(options) or None})
        job = self.request("POST", "ai/jobs", json=body, idempotent_key=_base.idempotency_key())
        return (self.wait_for_ai_job(job["job_id"], timeout=timeout)) if wait else job

    def get_ai_job(self, job_id: str) -> dict:
        return self.request("GET", f"ai/jobs/{job_id}")

    def wait_for_ai_job(self, job_id: str, *, timeout: float = 3600, poll_interval: float = 2.0) -> dict:
        """Poll until completed / partially_completed / failed / cancelled (never raises on failure)."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_ai_job(job_id)
            if job.get("status") in ("completed", "partially_completed", "failed", "cancelled"):
                return job
            if time.monotonic() + poll_interval > deadline:
                raise _errors.JobTimeoutError(f"AI job {job_id} still {job.get('status')} after {timeout}s", job,
                                              code="JOB_TIMEOUT")
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.3, 10.0)

    def ai_job_records(self, job_id: str, *, valid: str | None = None, page_size: int = 200) -> list:
        """Every record of a job (each: data, valid, errors, url, inferred). valid: "valid" | "invalid" | "missing"."""
        out, offset = [], 0
        while True:
            r = self.request("GET", f"ai/jobs/{job_id}/records",
                                params=_base._clean({"offset": offset, "limit": page_size, "valid": valid}))
            out += r.get("records") or []
            offset += len(r.get("records") or [])
            if not r.get("records") or offset >= int(r.get("total") or 0):
                return out

    def ai_job_export(self, job_id: str, format: str = "json") -> bytes:
        """The job's records as a file: "json", "csv" or "xlsx" (bytes)."""
        return self.request("GET", f"ai/jobs/{job_id}/export", params={"format": format}, raw="bytes")

    def cancel_ai_job(self, job_id: str) -> dict:
        return self.request("POST", f"ai/jobs/{job_id}/cancel")

    def retry_ai_job(self, job_id: str) -> dict:
        """Retry only the pages that failed."""
        return self.request("POST", f"ai/jobs/{job_id}/retry")

    # ── data APIs (v2.0): search engines, e-commerce, YouTube, social media, maps ─────────
    def search(self, query: str, *, engine: str = "google", search_type: str = "web", **params) -> dict:
        """SERP from google | bing | yahoo | duckduckgo | yandex | baidu. search_type: web, news, image, video,
        shopping, map, forum, book, short_video, ai, default. Other params as in the API (num_results, page,
        result_range, country, language, device, time_filter, scrape_depth, scrape_options, ...)."""
        return self.request("POST", f"search/{engine}", json=_base._clean({"query": query, "search_type": search_type, **params}))

    def ecommerce(self, action: str = "search", *, platform: str | None = None, **params) -> dict:
        """amazon | flipkart | walmart | alibaba | myntra | generic. action: search, scrape_product, scrape_category,
        scrape_reviews, compare_products, scrape_seller, search_by_category_id, search_by_merchant_id."""
        path = f"ecommerce/{platform}" if platform else "ecommerce"
        return self.request("POST", path, json=_base._clean({"action": action, **params}))

    def youtube(self, action: str = "search", **params) -> dict:
        """action: search (query, filters), scrape_video (url, include_transcript, include_comments),
        scrape_channel (url), download (url, quality, format), screenshot (url)."""
        return self.request("POST", "youtube", json=_base._clean({"action": action, **params}))

    def social(self, platform: str, target: str | None = None, *, action: str | None = None, **params) -> dict:
        """twitter, instagram, tiktok, snapchat, sharechat, threads, rss, linkedin, telegram, github, reddit,
        substack, podcast. target: URL, @handle, owner/repo, r/subreddit or a query."""
        return self.request("POST", f"social/{platform}", json=_base._clean({"target": target, "action": action, **params}))

    def maps(self, action: str = "search", **params) -> dict:
        """action: search (query, location), nearby (location.lat/lng), scrape_location / scrape_reviews
        (url or place_id), directions (origin, destination, mode)."""
        return self.request("POST", "maps", json=_base._clean({"action": action, **params}))

    def health(self) -> dict:
        return self.request("GET", "health")

    def history(self, limit: int = 20) -> list:
        r = self.request("GET", "scrape/history", params={"limit": limit})
        return r.get("history", r) if isinstance(r, dict) else r

    # ── v2.1: ScrapeCore Search, crawl index, agent mode, pipelines ─────────────────────
    def web_search(self, query: str, *, engines: list | None = None, num_results: int = 5, content: str = "markdown",
                   **params) -> dict:
        """Meta-search (engines + ScrapeCore's crawl index), ranked, with each page already scraped."""
        return self.request("POST", "web-search", json=_base._clean({"query": query, "engines": engines,
                                                                   "num_results": num_results, "content": content, **params}))

    def index_search(self, query: str, *, limit: int = 10, domain: str | None = None) -> dict:
        """Full-text search over pages ScrapeCore already fetched."""
        return self.request("POST", "index/search", json=_base._clean({"query": query, "limit": limit, "domain": domain}))

    def agent_run(self, steps: list | None = None, *, instructions: str | None = None, start_url: str | None = None,
                  inputs: dict | None = None, secrets: dict | None = None, save_as: str | None = None, **params) -> dict:
        """Run browser steps (or plain-word instructions planned by your AI provider) in one call."""
        return self.request("POST", "agent/run", json=_base._clean({"steps": steps, "instructions": instructions,
                                                                   "start_url": start_url, "inputs": inputs, "secrets": secrets,
                                                                   "save_as": save_as, **params}))

    def agent_recipes(self) -> list:
        return (self.request("GET", "agent/recipes")).get("recipes", [])

    def run_agent_recipe(self, recipe_id: str, *, inputs: dict | None = None, secrets: dict | None = None) -> dict:
        return self.request("POST", f"agent/recipes/{recipe_id}/run", json=_base._clean({"inputs": inputs, "secrets": secrets}))

    def pipelines(self) -> list:
        return (self.request("GET", "pipelines")).get("pipelines", [])

    def create_pipeline(self, name: str, kind: str, params: dict, *, interval_minutes: int = 1440,
                        destinations: list | None = None) -> dict:
        """kind: scrape, search, web_search, ecommerce, social, youtube, maps. destinations: list of
        {"type": "webhook" | "s3" | "gsheets" | "bigquery", "config": {...}}."""
        return self.request("POST", "pipelines", json={"name": name, "kind": kind, "params": params,
                                                        "interval_minutes": interval_minutes, "destinations": destinations or []})

    def run_pipeline(self, pipeline_id: str) -> dict:
        return self.request("POST", f"pipelines/{pipeline_id}/run")

    def pipeline_runs(self, pipeline_id: str, limit: int = 20) -> list:
        return (self.request("GET", f"pipelines/{pipeline_id}/runs", params={"limit": limit})).get("runs", [])

    def delete_pipeline(self, pipeline_id: str) -> dict:
        return self.request("DELETE", f"pipelines/{pipeline_id}")

    # ── account ───────────────────────────────────────────────────────────────────────────
    def usage(self) -> dict:
        return self.request("GET", "usage")

    def rate_limit(self) -> dict:
        return self.request("GET", "rate-limit")
