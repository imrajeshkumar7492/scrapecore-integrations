# ScrapeCore Python SDK

The official Python client for the [ScrapeCore](https://scrapecore.com) API (v1). You can scrape
pages to HTML, Markdown or text, map a site, crawl it, take screenshots, and extract data with CSS
selectors.

```bash
pip install scrapecore-sdk
```

```python
from scrapecore import ScrapeCore

sc = ScrapeCore()            # reads SCRAPECORE_API_KEY (or pass api_key="sk_live_...")

page = sc.scrape("https://example.com", format="markdown")
print(page["markdown"], page["credits_used"], page["credits_remaining"])

urls = sc.map("https://example.com", limit=500)["urls"]

job = sc.crawl("https://example.com/docs", max_depth=2, limit=100, include_paths=["^/docs"], wait=True)
for p in sc.crawl_pages(job["job_id"], only_ok=True):
    print(p["url"], p["title"], len(p["markdown"]))

shot = sc.screenshot("https://example.com", full_page=True, device="mobile")   # shot["image_base64"]
data = sc.extract("https://example.com", {"title": "h1", "links": "a"})
```

Async:

```python
from scrapecore import AsyncScrapeCore

async with AsyncScrapeCore() as sc:
    page = await sc.scrape("https://example.com", format="markdown")
```

## Errors and retries

Every API error raises a subclass of `ScrapeCoreError`. Each error has these attributes: `code`
(stable, e.g. `RATE_LIMITED`), `status`, `message`, `request_id` (quote it to support),
`retryable` and `retry_after`.

| Exception | When |
|---|---|
| `AuthenticationError` | missing / wrong / revoked key (401) |
| `InsufficientCreditsError` | monthly credits used up (402) |
| `PermissionDeniedError` | feature not in your plan (403) |
| `InvalidRequestError` | bad URL or parameter (400/422) |
| `RateLimitError` | per-minute / daily / concurrency limit (429) |
| `APIError` | server or target-site failure (5xx) |
| `APIConnectionError` | network error or timeout |

The SDK automatically retries rate limits (except the daily limit), 5xx errors and network errors
(`max_retries=2`, honouring `Retry-After`). Job-creating calls send an `Idempotency-Key`, so a retry
never creates a second job. Failed scrapes are never charged.

## Responsible use

Use ScrapeCore only for content you are allowed to access. Crawls and maps respect `robots.txt` by
default. See the [acceptable use policy](https://scrapecore.com/acceptable-use).
