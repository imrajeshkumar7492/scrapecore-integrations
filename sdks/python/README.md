# ScrapeCore Python SDK

The official Python client for the [ScrapeCore](https://scrapecore.com) API (v1). You can scrape
pages to HTML, Markdown or text, map a site, crawl it, take screenshots, and extract data with CSS
selectors or with AI. You can also watch pages for changes. It includes a
`scrapecore` command-line tool.

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

## AI extraction, crawl exports, monitors

AI extraction uses your own AI provider key: OpenAI, Anthropic, Gemini, Mistral, Groq, DeepSeek, xAI,
Cohere, Azure OpenAI, OpenRouter or any OpenAI-compatible endpoint. Connect it in Dashboard → AI Extraction.
Your provider bills you for tokens; ScrapeCore does not.

```python
product = sc.ai_extract("https://shop.example/item", prompt="name, price and rating",
                        schema={"type": "object", "properties": {"name": {"type": "string"},
                                                                 "price": {"type": "number"}}})["data"]

# many pages (or sitemap=..., site=...) as a background job, any connected provider
job = sc.ai_job(["https://shop.example/c/1", "https://shop.example/c/2"], instructions="every product with price",
                schema={"name": "string", "price": "number"}, records="list", provider="openai", wait=True)
rows = sc.ai_job_records(job["job_id"])
open("products.xlsx", "wb").write(sc.ai_job_export(job["job_id"], "xlsx"))

llms_txt = sc.crawl_export(job["job_id"], "llms")            # also "jsonl", "markdown", "chunks", "llms-full"

m = sc.create_monitor("https://competitor.example/pricing", interval_minutes=60, selector="#plans")
for change in sc.monitor_changes(m["id"]):
    print(change["created_at"], change["summary"], change["diff"])
```

## Command line

```bash
scrapecore login                                   # saves the key in ~/.config/scrapecore/config.json (mode 600)
scrapecore scrape https://example.com              # Markdown to stdout
scrapecore map https://example.com --limit 200
scrapecore crawl https://docs.example.com --limit 50 --export llms -o llms.txt
scrapecore screenshot https://example.com --full-page -o page.png
scrapecore extract https://shop.example/item -p "name and price"
scrapecore ai https://shop.example/c/1 https://shop.example/c/2 -p "every product with price" --many -f xlsx -o out.xlsx
scrapecore monitor add https://competitor.example/pricing --every 60 --selector "#plans"
scrapecore monitor list
scrapecore usage
```

Add `--json` to print the raw API response, or `-o FILE` to write the result to a file. The key
comes from `--api-key`, then `SCRAPECORE_API_KEY`, then the key saved by `scrapecore login`.
`python -m scrapecore` works too.

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
