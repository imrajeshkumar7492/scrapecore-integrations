# ScrapeCore Node.js / TypeScript SDK

The official client for the [ScrapeCore](https://scrapecore.com) API (v1). It needs Node 18+ (it uses
the built-in fetch), supports both ESM and CommonJS, and ships with full TypeScript types.

```bash
npm install @scrapecore/sdk
```

```ts
import { ScrapeCore } from "@scrapecore/sdk";

const sc = new ScrapeCore();          // reads SCRAPECORE_API_KEY (or { apiKey: "sk_live_..." })

const page = await sc.scrape("https://example.com", { format: "markdown" });
console.log(page.markdown, page.credits_used);

const { urls } = await sc.map("https://example.com", { limit: 500 });

const job = await sc.crawl("https://example.com/docs", { maxDepth: 2, limit: 100, includePaths: ["^/docs"], wait: true });
for await (const p of sc.crawlPages(job.job_id, { onlyOk: true })) console.log(p.url, p.title);

const shot = await sc.screenshot("https://example.com", { fullPage: true, device: "mobile" }); // shot.image_base64
const data = await sc.extract("https://example.com", { title: "h1" });
```

CommonJS: `const { ScrapeCore } = require("@scrapecore/sdk");`

## Errors and retries

Every API error is thrown as a subclass of `ScrapeCoreError`, with `code` (stable, e.g.
`RATE_LIMITED`), `status`, `message`, `requestId`, `retryable` and `retryAfter`. The subclasses are
`AuthenticationError`, `InsufficientCreditsError`, `PermissionDeniedError`, `InvalidRequestError`,
`NotFoundError`, `RateLimitError`, `APIError`, `APIConnectionError`, `JobFailedError` and
`JobTimeoutError`.

The SDK automatically retries rate limits (except the daily limit), 5xx errors and network errors
(`maxRetries: 2`, honouring `Retry-After`). Job-creating calls send an `Idempotency-Key`, so a retry
never creates a second job. Failed scrapes are never charged.

## Responsible use

Use ScrapeCore only for content you are allowed to access. Crawls and maps respect `robots.txt` by
default. See the [acceptable use policy](https://scrapecore.com/acceptable-use).
