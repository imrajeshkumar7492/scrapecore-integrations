import {
  APIConnectionError, AuthenticationError, JobFailedError, JobTimeoutError, ScrapeCoreError, fromResponse,
} from "./errors.js";
import type {
  AiExtractOptions, AiExtractResult, AiJob, AiJobOptions, CrawlExportFormat, CrawlOptions, CrawlPage, Job, MapOptions, MapResult, Monitor,
  MonitorChange, MonitorOptions, ScrapeOptions, ScrapeResult, ScreenshotOptions, WaitOptions,
} from "./types.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://api.scrapecore.com";
const TERMINAL = new Set(["success", "failure", "cancelled"]);

export interface ClientOptions {
  /** Defaults to process.env.SCRAPECORE_API_KEY. */
  apiKey?: string;
  /** Defaults to process.env.SCRAPECORE_BASE_URL or https://api.scrapecore.com */
  baseUrl?: string;
  /** Milliseconds per request (default 120000). */
  timeout?: number;
  /** Retries for rate limits, 5xx and network errors (default 2). */
  maxRetries?: number;
  userAgent?: string;
  /** A fetch implementation (default: the global fetch, Node 18+). */
  fetch?: typeof fetch;
}

export interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  idempotencyKey?: string;
  /** Resolve to the response body as text (true) or bytes ("bytes") instead of parsed JSON. */
  raw?: boolean | "bytes";
}

const env = (k: string): string | undefined =>
  typeof process !== "undefined" && process.env ? process.env[k] : undefined;

const snake = (k: string) => k.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase());

/** camelCase options -> the API's snake_case fields; undefined values are not sent. */
function body(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) if (v !== undefined) out[snake(k)] = v;
  return out;
}

const sleep = (s: number) => new Promise((r) => setTimeout(r, s * 1000));

function uuid(): string {
  const c: any = (globalThis as any).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    return (ch === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/**
 * ScrapeCore API client.
 *
 * ```ts
 * import { ScrapeCore } from "@scrapecore/sdk";
 * const sc = new ScrapeCore();                 // reads SCRAPECORE_API_KEY
 * const page = await sc.scrape("https://example.com", { format: "markdown" });
 * ```
 * Failed scrapes are not charged. Rate limits and server errors are retried automatically.
 */
export class ScrapeCore {
  readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly ua: string;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: ClientOptions = {}) {
    const key = opts.apiKey ?? env("SCRAPECORE_API_KEY");
    if (!key) {
      throw new AuthenticationError(
        "No API key: pass { apiKey } or set SCRAPECORE_API_KEY (create one at https://scrapecore.com/dashboard/api-keys)",
        { code: "INVALID_API_KEY" });
    }
    this.apiKey = key;
    this.baseUrl = (opts.baseUrl ?? env("SCRAPECORE_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeout = opts.timeout ?? 120_000;
    this.maxRetries = Math.max(0, opts.maxRetries ?? 2);
    this.ua = `${opts.userAgent ? opts.userAgent + " " : ""}scrapecore-node/${VERSION}`;
    const f = opts.fetch ?? (globalThis as any).fetch;
    if (!f) throw new ScrapeCoreError("No fetch available: use Node 18+ or pass { fetch }");
    this.fetchImpl = f;
  }

  /** Any /api/v1 endpoint. Retries what is safe to retry. */
  async request<T = any>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const url = new URL(`${this.baseUrl}/api/v1/${path.replace(/^\/+/, "")}`);
    for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined) url.searchParams.set(k, String(v));
    const headers: Record<string, string> = {
      "X-API-Key": this.apiKey, "User-Agent": this.ua, Accept: "application/json",
    };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
    for (let attempt = 0; ; attempt++) {
      let err: ScrapeCoreError;
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), this.timeout);
      try {
        const res = await this.fetchImpl(url.toString(), {
          method, headers, signal: ctl.signal,
          body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        });
        if (res.ok && opts.raw === "bytes") return new Uint8Array(await res.arrayBuffer()) as unknown as T;
        const text = await res.text();
        if (res.ok && opts.raw) return text as unknown as T;
        let parsed: any = null;
        try { parsed = text ? JSON.parse(text) : null; } catch { parsed = { detail: text.slice(0, 500) }; }
        if (res.ok) return parsed as T;
        err = fromResponse(res.status, parsed, res.headers);
      } catch (e: any) {
        if (e instanceof ScrapeCoreError) throw e;
        const timedOut = e?.name === "AbortError";
        err = new APIConnectionError(timedOut ? `timed out after ${this.timeout} ms` : `could not reach the API: ${e?.message ?? e}`,
          { code: timedOut ? "TIMEOUT" : "CONNECTION_ERROR", retryable: true });
      } finally {
        clearTimeout(timer);
      }
      const retry = attempt < this.maxRetries &&
        (err instanceof APIConnectionError || (err.retryable && err.code !== "DAILY_LIMIT"));
      if (!retry) throw err;
      await sleep(err.retryAfter !== undefined ? Math.min(err.retryAfter, 60)
        : Math.min(0.5 * 2 ** attempt, 8) * (0.75 + Math.random() / 2));
    }
  }

  // ── scraping ──────────────────────────────────────────────────────────────────────────
  /** Scrape one page as html, markdown or text. */
  scrape(url: string, opts: ScrapeOptions = {}): Promise<ScrapeResult> {
    return this.request("POST", "scrape", { body: body({ url, format: "html", ...opts }) });
  }

  /** The page as Markdown (just the text). */
  async markdown(url: string, opts: Omit<ScrapeOptions, "format"> = {}): Promise<string> {
    return (await this.scrape(url, { ...opts, format: "markdown" })).markdown ?? "";
  }

  /** Up to 50 URLs in one call (plan feature "batch"). */
  batch(urls: string[], opts: Omit<ScrapeOptions, "format" | "maxAge"> = {}): Promise<{ results: ScrapeResult[]; [k: string]: unknown }> {
    return this.request("POST", "batch", { body: body({ urls, ...opts }) });
  }

  /** A screenshot: result.image_base64. */
  async screenshot(url: string, opts: ScreenshotOptions = {}): Promise<any> {
    const { wait = true, timeout = 120, ...rest } = opts;
    const job = await this.request("POST", "screenshot",
      { body: body({ url, ...rest, sync: false }), idempotencyKey: uuid() });
    if (!job?.job_id || job.status !== "queued" || !wait) return job;
    return (await this.waitForJob(job.job_id, { timeout })).result;
  }

  /** CSS selectors -> values, e.g. { title: "h1", prices: ".price" }. */
  extract(url: string, selectors: Record<string, string>, opts: { jsRender?: boolean } = {}): Promise<any> {
    return this.request("POST", "extract", { body: body({ url, selectors, ...opts, sync: true }) });
  }

  // ── site discovery and crawling ───────────────────────────────────────────────────────
  /** Every URL of a site (sitemaps + links). */
  map(url: string, opts: MapOptions = {}): Promise<MapResult> {
    return this.request("POST", "map", { body: body({ url, ...opts }) });
  }

  /** Start a crawl job. With { wait: true } resolves when it ends; read pages with crawlPages(). */
  async crawl(url: string, opts: CrawlOptions & { wait?: boolean; timeout?: number } = {}): Promise<Job> {
    const { wait = false, timeout = 1800, ...rest } = opts;
    const job = await this.request<Job>("POST", "crawl", { body: body({ url, ...rest }), idempotencyKey: uuid() });
    return wait ? this.waitForJob(job.job_id, { timeout, throwOnFailure: false }) : job;
  }

  /** Every page of a crawl, fetched page by page: `for await (const p of sc.crawlPages(id)) ...` */
  async *crawlPages(jobId: string, opts: { onlyOk?: boolean; pageSize?: number } = {}): AsyncGenerator<CrawlPage> {
    let offset = 0;
    for (;;) {
      const r = await this.request<{ pages: CrawlPage[]; total: number }>("GET", `crawl/${encodeURIComponent(jobId)}/pages`,
        { query: { offset, limit: opts.pageSize ?? 100, only_ok: opts.onlyOk ?? false } });
      const pages = r?.pages ?? [];
      for (const p of pages) yield p;
      offset += pages.length;
      if (!pages.length || offset >= (r?.total ?? 0)) return;
    }
  }

  // ── jobs ──────────────────────────────────────────────────────────────────────────────
  /** Queue a scrape; resolves to { job_id, status: "queued" }. */
  scrapeAsync(url: string, opts: Omit<ScrapeOptions, "maxAge"> = {}): Promise<Job> {
    return this.request("POST", "async", { body: body({ url, ...opts }), idempotencyKey: uuid() });
  }

  getJob(jobId: string): Promise<Job> {
    return this.request("GET", `job/${encodeURIComponent(jobId)}`);
  }

  /** Poll until success / failure / cancelled. */
  async waitForJob(jobId: string, opts: WaitOptions = {}): Promise<Job> {
    const timeout = opts.timeout ?? 300;
    const deadline = Date.now() + timeout * 1000;
    let delay = opts.pollInterval ?? 1;
    for (;;) {
      const job = await this.getJob(jobId);
      if (TERMINAL.has(job.status)) {
        if ((opts.throwOnFailure ?? true) && job.status !== "success") {
          throw new JobFailedError(`job ${jobId} ended as ${job.status}${job.error ? ": " + job.error : ""}`, job,
            { code: `JOB_${job.status.toUpperCase()}` });
        }
        return job;
      }
      if (Date.now() + delay * 1000 > deadline) {
        throw new JobTimeoutError(`job ${jobId} still ${job.status} after ${timeout}s`, job, { code: "JOB_TIMEOUT" });
      }
      await sleep(delay);
      delay = Math.min(delay * 1.5, 10);
    }
  }

  /** Cancel a queued job, or stop a running crawl after its current page. */
  cancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
    return this.request("POST", `job/${encodeURIComponent(jobId)}/cancel`);
  }

  jobs(opts: { limit?: number; offset?: number; status?: string; type?: string } = {}): Promise<Job[]> {
    return this.request("GET", "jobs", { query: opts });
  }

  // ── AI extraction (your own AI provider key) ───────────────────────
  /** Structured data from ONE page with your own AI provider (any connected one). For many pages use aiJob(). */
  aiExtract(url: string, opts: AiExtractOptions = {}): Promise<AiExtractResult> {
    return this.request("POST", "extract/ai", { body: body({ url, ...opts }) });
  }

  /** A crawl as one AI-ready document: jsonl, markdown, chunks (RAG JSONL), llms (llms.txt) or llms-full. */
  crawlExport(jobId: string, format: CrawlExportFormat = "jsonl", opts: { chunkSize?: number; overlap?: number } = {}): Promise<string> {
    return this.request("GET", `crawl/${encodeURIComponent(jobId)}/export`,
      { raw: true, query: { format, chunk_size: opts.chunkSize, overlap: opts.overlap } });
  }

  // ── AI Extraction jobs (your own AI provider key; many URLs, sitemaps, whole sites) ─────
  /** Your connected AI providers (keys masked) and the default one. */
  aiProviders(): Promise<{ providers: any[]; default: string | null }> {
    return this.request("GET", "ai/providers");
  }

  /** Start an AI extraction job over URLs, a sitemap ({ sitemap }) or a whole site ({ site }). */
  async aiJob(urls: string[] | null, opts: AiJobOptions = {}): Promise<AiJob> {
    const { sitemap, site, wait = false, timeout = 3600, schema, records = "single", options, ...rest } = opts;
    const source = sitemap ? { type: "sitemap", value: sitemap } : site ? { type: "discover", value: site } : { type: "urls" };
    const list = urls ?? [];
    const job = await this.request<AiJob>("POST", "ai/jobs", {
      idempotencyKey: uuid(),
      body: body({ urls: list, source, jsonSchema: schema, records, options: options ? body(options as any) : undefined,
                   mode: list.length > 1 ? "bulk" : site ? "multipage" : "natural", ...rest }),
    });
    return wait ? this.waitForAiJob(job.job_id, { timeout }) : job;
  }

  getAiJob(jobId: string): Promise<AiJob> {
    return this.request("GET", `ai/jobs/${encodeURIComponent(jobId)}`);
  }

  /** Poll until completed / partially_completed / failed / cancelled. */
  async waitForAiJob(jobId: string, opts: { timeout?: number; pollInterval?: number } = {}): Promise<AiJob> {
    const deadline = Date.now() + (opts.timeout ?? 3600) * 1000;
    let delay = opts.pollInterval ?? 2;
    for (;;) {
      const job = await this.getAiJob(jobId);
      if (["completed", "partially_completed", "failed", "cancelled"].includes(job.status)) return job;
      if (Date.now() + delay * 1000 > deadline) {
        throw new JobTimeoutError(`AI job ${jobId} still ${job.status}`, job as any, { code: "JOB_TIMEOUT" });
      }
      await sleep(delay);
      delay = Math.min(delay * 1.3, 10);
    }
  }

  /** Every record of a job (data, valid, errors, url, inferred). */
  async aiJobRecords(jobId: string, opts: { valid?: "valid" | "invalid" | "missing"; pageSize?: number } = {}): Promise<any[]> {
    const out: any[] = [];
    for (let offset = 0; ;) {
      const r = await this.request("GET", `ai/jobs/${encodeURIComponent(jobId)}/records`,
        { query: { offset, limit: opts.pageSize ?? 200, valid: opts.valid } });
      out.push(...(r.records ?? []));
      offset += (r.records ?? []).length;
      if (!(r.records ?? []).length || offset >= (r.total ?? 0)) return out;
    }
  }

  /** The job's records as a file: "json", "csv" or "xlsx" (bytes). */
  aiJobExport(jobId: string, format: "json" | "csv" | "xlsx" = "json"): Promise<Uint8Array> {
    return this.request("GET", `ai/jobs/${encodeURIComponent(jobId)}/export`, { raw: "bytes", query: { format } });
  }

  cancelAiJob(jobId: string): Promise<any> {
    return this.request("POST", `ai/jobs/${encodeURIComponent(jobId)}/cancel`);
  }

  /** Retry only the pages that failed. */
  retryAiJob(jobId: string): Promise<any> {
    return this.request("POST", `ai/jobs/${encodeURIComponent(jobId)}/retry`);
  }

  // ── page-change monitors ─────────────────────────────────────────────────────────────
  monitors(): Promise<{ monitors: Monitor[]; limit: number; intervals: number[]; min_interval_minutes: number }> {
    return this.request("GET", "monitors");
  }

  /** Watch a page (optionally one CSS selector of it) and get alerted when it changes. */
  createMonitor(url: string, opts: MonitorOptions = {}): Promise<Monitor> {
    return this.request("POST", "monitors", { body: body({ url, intervalMinutes: 1440, ...opts }) });
  }

  getMonitor(id: string): Promise<Monitor> {
    return this.request("GET", `monitors/${encodeURIComponent(id)}`);
  }

  /** Change any setting; { status: "paused" | "active" } pauses or resumes. */
  updateMonitor(id: string, changes: MonitorOptions & { status?: "active" | "paused" }): Promise<Monitor> {
    return this.request("PATCH", `monitors/${encodeURIComponent(id)}`, { body: body({ ...changes }) });
  }

  deleteMonitor(id: string): Promise<{ ok: boolean }> {
    return this.request("DELETE", `monitors/${encodeURIComponent(id)}`);
  }

  /** Check now: { changed, summary?, monitor }. */
  checkMonitor(id: string): Promise<{ ok: boolean; changed: boolean; summary?: string; error?: string; baseline?: boolean; monitor: Monitor }> {
    return this.request("POST", `monitors/${encodeURIComponent(id)}/check`);
  }

  /** Detected changes, newest first, each with a unified diff. */
  async monitorChanges(id: string, opts: { limit?: number } = {}): Promise<MonitorChange[]> {
    return (await this.request("GET", `monitors/${encodeURIComponent(id)}/changes`, { query: { limit: opts.limit ?? 20 } })).changes;
  }

  // ── data APIs (v2.0): search engines, e-commerce, YouTube, social media, maps ─────────
  // Top-level options may be camelCase (numResults → num_results); nested objects use the API's
  // snake_case names (e.g. scrapeOptions: { js_render: true }, filters: { min_price: 50 }).
  /** SERP from google | bing | yahoo | duckduckgo | yandex | baidu (searchType: web, news, image, video, shopping, map, ...). */
  search(query: string, opts: Record<string, unknown> & { engine?: string } = {}): Promise<any> {
    const { engine = "google", ...rest } = opts;
    return this.request("POST", `search/${encodeURIComponent(String(engine))}`, { body: body({ query, ...rest }) });
  }

  /** amazon | flipkart | walmart | alibaba | myntra | generic — search, scrape_product, scrape_reviews, compare_products, ... */
  ecommerce(action = "search", opts: Record<string, unknown> & { platform?: string } = {}): Promise<any> {
    const { platform, ...rest } = opts;
    return this.request("POST", platform ? `ecommerce/${encodeURIComponent(String(platform))}` : "ecommerce",
      { body: body({ action, ...rest }) });
  }

  /** search | scrape_video | scrape_channel | download | screenshot */
  youtube(action = "search", opts: Record<string, unknown> = {}): Promise<any> {
    return this.request("POST", "youtube", { body: body({ action, ...opts }) });
  }

  /** twitter, instagram, tiktok, snapchat, sharechat, threads, rss, linkedin, telegram, github, reddit, substack, podcast */
  social(platform: string, target?: string, opts: Record<string, unknown> = {}): Promise<any> {
    return this.request("POST", `social/${encodeURIComponent(platform)}`, { body: body({ target, ...opts }) });
  }

  /** search | nearby | scrape_location | scrape_reviews | directions */
  maps(action = "search", opts: Record<string, unknown> = {}): Promise<any> {
    return this.request("POST", "maps", { body: body({ action, ...opts }) });
  }

  // ── v2.1: ScrapeCore Search, crawl index, agent mode, pipelines ─────────────────────
  /** Meta-search (engines + crawl index), ranked, each page already scraped. */
  webSearch(query: string, opts: Record<string, unknown> = {}): Promise<any> {
    return this.request("POST", "web-search", { body: body({ query, ...opts }) });
  }

  indexSearch(query: string, opts: Record<string, unknown> = {}): Promise<any> {
    return this.request("POST", "index/search", { body: body({ query, ...opts }) });
  }

  /** Browser steps (or instructions planned by your AI provider) in one call. */
  agentRun(opts: Record<string, unknown>): Promise<any> {
    return this.request("POST", "agent/run", { body: body(opts) });
  }

  runAgentRecipe(recipeId: string, opts: Record<string, unknown> = {}): Promise<any> {
    return this.request("POST", `agent/recipes/${encodeURIComponent(recipeId)}/run`, { body: body(opts) });
  }

  createPipeline(opts: Record<string, unknown>): Promise<any> {
    return this.request("POST", "pipelines", { body: body(opts) });
  }

  pipelines(): Promise<any> {
    return this.request("GET", "pipelines");
  }

  runPipeline(pipelineId: string): Promise<any> {
    return this.request("POST", `pipelines/${encodeURIComponent(pipelineId)}/run`);
  }

  // ── account ───────────────────────────────────────────────────────────────────────────
  usage(): Promise<any> {
    return this.request("GET", "usage");
  }

  rateLimit(): Promise<any> {
    return this.request("GET", "rate-limit");
  }
}
