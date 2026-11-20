import json

import httpx
import pytest

import scrapecore
from scrapecore import AsyncScrapeCore, ScrapeCore


def client(handler, cls=ScrapeCore, **kw):
    http = (httpx.AsyncClient if cls is AsyncScrapeCore else httpx.Client)(transport=httpx.MockTransport(handler))
    return cls("sk_test_" + "x" * 32, base_url="https://api.test", http_client=http, **kw)


def env(status, code, msg, **extra):
    return httpx.Response(status, json={"error": {"code": code, "message": msg, "status": status, "request_id": "rid1",
                                                  "retryable": status in (429, 500, 502, 503), **extra}, "detail": msg})


def test_scrape_sends_key_version_path_and_body():
    seen = {}

    def h(req):
        seen.update(url=str(req.url), key=req.headers["x-api-key"], ua=req.headers["user-agent"], body=json.loads(req.content))
        return httpx.Response(200, json={"success": True, "markdown": "# Hi", "credits_used": 1})
    sc = client(h)
    assert sc.markdown("https://example.com") == "# Hi"
    assert seen["url"] == "https://api.test/api/v1/scrape"
    assert seen["key"].startswith("sk_test_") and seen["ua"].startswith("scrapecore-python/")
    assert seen["body"] == {"url": "https://example.com", "format": "markdown"}     # unset options not sent


def test_missing_key(monkeypatch):
    monkeypatch.delenv("SCRAPECORE_API_KEY", raising=False)
    with pytest.raises(scrapecore.AuthenticationError):
        ScrapeCore()


@pytest.mark.parametrize("status,code,cls", [
    (401, "INVALID_API_KEY", scrapecore.AuthenticationError), (402, "INSUFFICIENT_CREDITS", scrapecore.InsufficientCreditsError),
    (403, "FEATURE_NOT_IN_PLAN", scrapecore.PermissionDeniedError), (422, "VALIDATION_ERROR", scrapecore.InvalidRequestError),
    (404, "NOT_FOUND", scrapecore.NotFoundError)])
def test_errors_map_to_types(status, code, cls):
    sc = client(lambda r: env(status, code, "nope"))
    with pytest.raises(cls) as e:
        sc.scrape("https://example.com")
    assert e.value.code == code and e.value.request_id == "rid1" and e.value.status == status


def test_retries_rate_limit_with_retry_after_then_succeeds(monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr("scrapecore._client.time.sleep", sleeps.append)

    def h(req):
        calls.append(1)
        return env(429, "RATE_LIMITED", "slow down", retry_after_seconds=3) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})
    assert client(h).usage() == {"ok": 1}
    assert len(calls) == 3 and sleeps == [3.0, 3.0]


def test_daily_limit_and_exhausted_retries_raise(monkeypatch):
    monkeypatch.setattr("scrapecore._client.time.sleep", lambda s: None)
    with pytest.raises(scrapecore.RateLimitError):
        client(lambda r: env(429, "DAILY_LIMIT", "daily")).usage()
    calls = []

    def h(r):
        calls.append(1)
        return env(503, "SERVICE_UNAVAILABLE", "down")
    with pytest.raises(scrapecore.APIError):
        client(h, max_retries=2).usage()
    assert len(calls) == 3


def test_network_error_is_retried_then_raised(monkeypatch):
    monkeypatch.setattr("scrapecore._client.time.sleep", lambda s: None)

    def h(r):
        raise httpx.ConnectError("boom")
    with pytest.raises(scrapecore.APIConnectionError):
        client(h).usage()


def test_crawl_wait_and_pages(monkeypatch):
    monkeypatch.setattr("scrapecore._client.time.sleep", lambda s: None)
    polls, idem = [], []
    pages = [{"url": f"https://ex.com/{i}", "markdown": "x"} for i in range(5)]

    def h(req):
        p = req.url.path
        if p == "/api/v1/crawl":
            idem.append(req.headers.get("idempotency-key"))
            return httpx.Response(200, json={"job_id": "J1", "status": "queued"})
        if p == "/api/v1/job/J1":
            polls.append(1)
            return httpx.Response(200, json={"job_id": "J1", "status": "running" if len(polls) < 3 else "success"})
        if p == "/api/v1/crawl/J1/pages":
            o, n = int(req.url.params["offset"]), int(req.url.params["limit"])
            return httpx.Response(200, json={"total": 5, "pages": pages[o:o + n]})
        return httpx.Response(404)
    sc = client(h)
    job = sc.crawl("https://ex.com", max_depth=1, wait=True)
    assert job["status"] == "success" and len(polls) == 3 and idem[0]
    assert [p["url"] for p in sc.crawl_pages("J1", page_size=2)] == [p["url"] for p in pages]


def test_wait_for_job_failure_and_timeout(monkeypatch):
    monkeypatch.setattr("scrapecore._client.time.sleep", lambda s: None)
    sc = client(lambda r: httpx.Response(200, json={"job_id": "J", "status": "failure", "error": "blocked"}))
    with pytest.raises(scrapecore.JobFailedError) as e:
        sc.wait_for_job("J")
    assert e.value.job["error"] == "blocked"
    sc = client(lambda r: httpx.Response(200, json={"job_id": "J", "status": "running"}))
    with pytest.raises(scrapecore.JobTimeoutError):
        sc.wait_for_job("J", timeout=0)


async def test_async_client(monkeypatch):
    async def nosleep(s):
        return None
    monkeypatch.setattr("scrapecore._async_client.asyncio.sleep", nosleep)
    n = []

    def h(req):
        if req.url.path == "/api/v1/map":
            return httpx.Response(200, json={"urls": ["https://ex.com/"], "count": 1})
        if req.url.path == "/api/v1/screenshot":
            return httpx.Response(200, json={"job_id": "S", "status": "queued"})
        n.append(1)
        return httpx.Response(200, json={"job_id": "S", "status": "success" if len(n) > 1 else "running",
                                         "result": {"image_base64": "AAA"}})
    async with client(h, AsyncScrapeCore) as sc:
        assert (await sc.map("https://ex.com"))["count"] == 1
        assert (await sc.screenshot("https://ex.com"))["image_base64"] == "AAA"
        assert await sc.markdown("https://ex.com") == ""


def test_sync_and_async_clients_have_the_same_methods():
    import inspect
    pub = lambda c: {n for n, _ in inspect.getmembers(c, inspect.isfunction) if not n.startswith("_")}
    assert pub(ScrapeCore) == pub(AsyncScrapeCore)
    for n in pub(ScrapeCore):
        assert inspect.signature(getattr(ScrapeCore, n)).parameters.keys() == \
            inspect.signature(getattr(AsyncScrapeCore, n)).parameters.keys(), n
