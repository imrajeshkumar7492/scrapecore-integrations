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

## AI extraction, crawl exports, monitors

AI extraction uses your own AI provider key (OpenAI, Anthropic, Gemini, Mistral, Groq, DeepSeek, xAI, Cohere,
Azure OpenAI, OpenRouter or any OpenAI-compatible endpoint), connected in Dashboard → AI Extraction.
Your provider bills you for tokens; ScrapeCore does not.

```ts
const { data } = await sc.aiExtract("https://shop.example/item", { prompt: "name, price and rating" });
const job = await sc.aiJob(null, { sitemap: "https://shop.example/sitemap.xml", instructions: "name and price",
  schema: { name: "string", price: "number" }, provider: "gemini", wait: true });
const records = await sc.aiJobRecords(job.job_id);
const llmsTxt = await sc.crawlExport(job.job_id, "llms");     // "jsonl" | "markdown" | "chunks" | "llms" | "llms-full"

const m = await sc.createMonitor("https://competitor.example/pricing", { intervalMinutes: 60, selector: "#plans" });
for (const c of await sc.monitorChanges(m.id)) console.log(c.created_at, c.summary, c.diff);
```

## Command line

```bash
npx @scrapecore/sdk login            # or install globally: npm i -g @scrapecore/sdk, then `scrapecore ...`
npx @scrapecore/sdk scrape https://example.com
npx @scrapecore/sdk crawl https://docs.example.com --limit 50 --export llms -o llms.txt
npx @scrapecore/sdk monitor add https://competitor.example/pricing --every 60 --selector "#plans"
```

These are the same commands and the same saved key (`~/.config/scrapecore/config.json`) as the Python CLI.
Run `scrapecore --help` to list them all.

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
