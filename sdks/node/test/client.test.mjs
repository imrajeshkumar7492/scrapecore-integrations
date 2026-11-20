import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { ScrapeCore, RateLimitError, AuthenticationError, InsufficientCreditsError, APIError,
  APIConnectionError, JobFailedError, JobTimeoutError } from "../dist/esm/index.js";

const KEY = "sk_test_" + "x".repeat(32);
const json = (status, obj, headers = {}) => new Response(JSON.stringify(obj), { status, headers });
const envl = (status, code, extra = {}) => json(status, { error: { code, message: code.toLowerCase(), status,
  request_id: "rid1", retryable: [429, 500, 502, 503].includes(status), ...extra }, detail: code });
const mk = (handler, o = {}) => new ScrapeCore({ apiKey: KEY, baseUrl: "https://api.test", fetch: handler, ...o });

test("scrape: key, path, snake_case body, unset options not sent", async () => {
  let seen;
  const sc = mk(async (url, init) => { seen = { url, init }; return json(200, { success: true, markdown: "# Hi" }); });
  assert.equal(await sc.markdown("https://example.com", { jsRender: true }), "# Hi");
  assert.equal(seen.url, "https://api.test/api/v1/scrape");
  assert.equal(seen.init.headers["X-API-Key"], KEY);
  assert.match(seen.init.headers["User-Agent"], /^scrapecore-node\//);
  assert.deepEqual(JSON.parse(seen.init.body), { url: "https://example.com", format: "markdown", js_render: true });
});

test("missing key", () => {
  const prev = process.env.SCRAPECORE_API_KEY; delete process.env.SCRAPECORE_API_KEY;
  assert.throws(() => new ScrapeCore({ fetch: async () => json(200, {}) }), AuthenticationError);
  if (prev) process.env.SCRAPECORE_API_KEY = prev;
});

test("errors map to types with envelope fields", async () => {
  await assert.rejects(mk(async () => envl(402, "INSUFFICIENT_CREDITS")).usage(),
    (e) => e instanceof InsufficientCreditsError && e.code === "INSUFFICIENT_CREDITS" && e.requestId === "rid1" && e.status === 402);
  await assert.rejects(mk(async () => envl(401, "INVALID_API_KEY")).usage(), AuthenticationError);
});

test("retries 429 honouring Retry-After, not the daily limit", async () => {
  let n = 0;
  const sc = mk(async () => (++n < 2 ? envl(429, "RATE_LIMITED", { retry_after_seconds: 0 }) : json(200, { ok: 1 })));
  assert.deepEqual(await sc.usage(), { ok: 1 });
  assert.equal(n, 2);
  n = 0;
  await assert.rejects(mk(async () => { n++; return envl(429, "DAILY_LIMIT"); }).usage(), RateLimitError);
  assert.equal(n, 1);
});

test("5xx and network errors: retried, then thrown", async () => {
  let n = 0;
  await assert.rejects(mk(async () => { n++; return envl(503, "SERVICE_UNAVAILABLE", { retry_after_seconds: 0 }); }).usage(), APIError);
  assert.equal(n, 3);
  await assert.rejects(mk(async () => { throw new TypeError("fetch failed"); }, { maxRetries: 0 }).usage(), APIConnectionError);
});

test("crawl wait + crawlPages pagination + idempotency key", async () => {
  let polls = 0; let idem;
  const pages = Array.from({ length: 5 }, (_, i) => ({ url: `https://ex.com/${i}` }));
  const sc = mk(async (u, init) => {
    const url = new URL(u);
    if (url.pathname === "/api/v1/crawl") { idem = init.headers["Idempotency-Key"]; return json(200, { job_id: "J1", status: "queued" }); }
    if (url.pathname === "/api/v1/job/J1") return json(200, { job_id: "J1", status: ++polls < 2 ? "running" : "success" });
    if (url.pathname === "/api/v1/crawl/J1/pages") {
      const o = +url.searchParams.get("offset"), l = +url.searchParams.get("limit");
      return json(200, { total: 5, pages: pages.slice(o, o + l) });
    }
    return json(404, {});
  });
  const job = await sc.crawl("https://ex.com", { maxDepth: 1, wait: true, timeout: 30 });
  assert.equal(job.status, "success"); assert.ok(idem);
  const got = []; for await (const p of sc.crawlPages("J1", { pageSize: 2 })) got.push(p.url);
  assert.deepEqual(got, pages.map((p) => p.url));
});

test("waitForJob failure and timeout", async () => {
  await assert.rejects(mk(async () => json(200, { job_id: "J", status: "failure", error: "blocked" })).waitForJob("J"),
    (e) => e instanceof JobFailedError && e.job.error === "blocked");
  await assert.rejects(mk(async () => json(200, { job_id: "J", status: "running" })).waitForJob("J", { timeout: 0 }), JobTimeoutError);
});

test("CommonJS build works", () => {
  const require = createRequire(import.meta.url);
  const cjs = require("../dist/cjs/index.js");
  assert.equal(typeof cjs.ScrapeCore, "function");
  assert.ok(new cjs.RateLimitError("x") instanceof cjs.ScrapeCoreError);
});
