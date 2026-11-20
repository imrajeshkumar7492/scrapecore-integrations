"""What the sync and async clients share: settings, request building, retry policy, parsing."""
from __future__ import annotations

import os
import random
import uuid
from typing import Any

from . import _errors
from ._version import __version__

DEFAULT_BASE_URL = "https://api.scrapecore.com"
TERMINAL = ("success", "failure", "cancelled")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


class Settings:
    def __init__(self, api_key: str | None, base_url: str | None, timeout: float, max_retries: int,
                 user_agent: str | None):
        self.api_key = api_key or os.environ.get("SCRAPECORE_API_KEY")
        if not self.api_key:
            raise _errors.AuthenticationError(
                "No API key: pass api_key=... or set SCRAPECORE_API_KEY (create one at "
                "https://scrapecore.com/dashboard/api-keys)", code="INVALID_API_KEY")
        self.base_url = (base_url or os.environ.get("SCRAPECORE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        ua = f"scrapecore-python/{__version__}"
        self.headers = {"X-API-Key": self.api_key, "User-Agent": f"{user_agent} {ua}" if user_agent else ua,
                        "Accept": "application/json"}

    def url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/{path.lstrip('/')}"


def backoff(attempt: int, err: _errors.ScrapeCoreError | None) -> float:
    if err is not None and err.retry_after is not None:
        return min(float(err.retry_after), 60.0)
    return min(0.5 * (2 ** attempt), 8.0) * (0.75 + random.random() / 2)


def should_retry(err: _errors.ScrapeCoreError, attempt: int, max_retries: int) -> bool:
    if attempt >= max_retries:
        return False
    if isinstance(err, _errors.APIConnectionError):
        return True
    # concurrency / per-minute / queue limits clear quickly; a daily limit does not
    return err.retryable and err.code != "DAILY_LIMIT"


def parse(status: int, headers, content: bytes) -> Any:
    import json
    try:
        body = json.loads(content) if content else None
    except ValueError:
        body = {"detail": content[:500].decode("utf-8", "replace")}
    if status >= 400:
        raise _errors.from_response(status, body, headers)
    return body


def idempotency_key() -> str:
    return str(uuid.uuid4())


# ── request bodies (one place, so both clients send the same thing) ─────────────────────────
def scrape_body(url, format, js_render, use_proxy, waf, max_age):
    return _clean({"url": url, "format": format, "js_render": js_render, "use_proxy": use_proxy,
                   "waf": waf, "max_age": max_age})


def map_body(url, limit, search, include_subdomains, respect_robots):
    return _clean({"url": url, "limit": limit, "search": search, "include_subdomains": include_subdomains,
                   "respect_robots": respect_robots})


def crawl_body(url, max_depth, limit, include_paths, exclude_paths, include_subdomains, respect_robots,
               js_render, use_proxy):
    return _clean({"url": url, "max_depth": max_depth, "limit": limit, "include_paths": include_paths,
                   "exclude_paths": exclude_paths, "include_subdomains": include_subdomains,
                   "respect_robots": respect_robots, "js_render": js_render, "use_proxy": use_proxy})


def job_failed(job: dict) -> _errors.JobFailedError:
    return _errors.JobFailedError(f"job {job.get('job_id')} ended as {job.get('status')}: {job.get('error') or ''}".strip(),
                                  job, code="JOB_" + str(job.get("status", "failed")).upper())
