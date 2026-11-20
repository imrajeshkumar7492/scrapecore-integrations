import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, statSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ScrapeCore } from "../dist/esm/index.js";
import { main, parseArgs } from "../dist/esm/cli.js";

const KEY = "sk_test_" + "x".repeat(32);
const json = (status, obj) => new Response(JSON.stringify(obj), { status });

test("aiExtract / search / crawlExport / monitors: paths and bodies", async () => {
  const seen = [];
  const sc = new ScrapeCore({ apiKey: KEY, baseUrl: "https://api.test", fetch: async (url, init) => {
    const u = new URL(url);
    seen.push({ m: init.method, p: u.pathname, q: u.search, b: init.body ? JSON.parse(init.body) : null });
    if (u.pathname.endsWith("/export")) return new Response("# llms\n", { status: 200 });
    if (u.pathname.endsWith("/changes")) return json(200, { changes: [{ diff: "-a\n+b" }] });
    return json(200, { ok: true });
  } });
  await sc.aiExtract("https://x.example", { prompt: "price", jsRender: true });
  await sc.search("espresso", { limit: 3, maxChars: 500 });
  assert.equal(await sc.crawlExport("j1", "llms", { chunkSize: 500 }), "# llms\n");
  await sc.createMonitor("https://x.example", { selector: "#p", ignorePatterns: ["\\d+"] });
  await sc.updateMonitor("m1", { status: "paused" });
  assert.deepEqual(await sc.monitorChanges("m1", { limit: 2 }), [{ diff: "-a\n+b" }]);
  assert.deepEqual(seen[0], { m: "POST", p: "/api/v1/extract/ai", q: "", b: { url: "https://x.example", prompt: "price", js_render: true } });
  assert.deepEqual(seen[1].b, { query: "espresso", limit: 3, max_chars: 500 });
  assert.equal(seen[2].q, "?format=llms&chunk_size=500");
  assert.deepEqual(seen[3].b, { url: "https://x.example", interval_minutes: 1440, selector: "#p", ignore_patterns: ["\\d+"] });
  assert.deepEqual([seen[4].m, seen[4].p, seen[4].b], ["PATCH", "/api/v1/monitors/m1", { status: "paused" }]);
  assert.equal(seen[5].q, "?limit=2");
});

test("parseArgs: flags, aliases, repeatables", () => {
  const { pos, flags } = parseArgs(["crawl", "https://a.example", "--limit", "5", "--include", "/docs", "--include=/api", "-o", "x.txt", "--json"]);
  assert.deepEqual(pos, ["crawl", "https://a.example"]);
  assert.deepEqual(flags, { limit: "5", include: ["/docs", "/api"], output: "x.txt", json: true });
});

function withCli(routes) {
  const dir = mkdtempSync(join(tmpdir(), "sc-cli-"));
  process.env.SCRAPECORE_CONFIG = join(dir, "cfg", "config.json");
  process.env.SCRAPECORE_BASE_URL = "https://api.test";
  delete process.env.SCRAPECORE_API_KEY;
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const u = new URL(url);
    calls.push({ m: init.method, p: u.pathname, key: init.headers["X-API-Key"], ua: init.headers["User-Agent"] });
    for (const [k, v] of Object.entries(routes)) {
      const [m, suffix] = k.split(" ");
      if (m === init.method && u.pathname.endsWith(suffix)) return typeof v === "function" ? v() : v.clone();
    }
    return json(404, { error: { code: "NOT_FOUND", message: "no route", status: 404 } });
  };
  const out = [];
  const realWrite = process.stdout.write.bind(process.stdout);
  process.stdout.write = (s) => { out.push(String(s)); return true; };
  const errs = [];
  const realErr = process.stderr.write.bind(process.stderr);
  process.stderr.write = (s) => { errs.push(String(s)); return true; };
  return { dir, calls, out, errs, restore() { globalThis.fetch = realFetch; process.stdout.write = realWrite; process.stderr.write = realErr; } };
}

test("cli: login saves key with mode 600, scrape uses it, logout removes it", async () => {
  const t = withCli({ "GET /usage": () => json(200, { credits_used: 10, credits_limit: 1000 }),
                      "POST /scrape": () => json(200, { markdown: "# Example" }) });
  try {
    assert.equal(await main(["login", "--api-key", KEY]), 0);
    const cfg = process.env.SCRAPECORE_CONFIG;
    assert.equal(JSON.parse(readFileSync(cfg, "utf8")).api_key, KEY);
    if (process.platform !== "win32") assert.equal(statSync(cfg).mode & 0o777, 0o600);
    assert.match(t.errs.join(""), /990 credits left/);
    assert.equal(await main(["scrape", "https://example.com"]), 0);
    assert.equal(t.out.join("").trim(), "# Example");
    assert.equal(t.calls.at(-1).key, KEY);
    assert.match(t.calls.at(-1).ua, /^scrapecore-cli\//);
    assert.equal(await main(["logout"]), 0);
    assert.equal(JSON.parse(readFileSync(cfg, "utf8")).api_key, undefined);
  } finally { t.restore(); }
});

test("cli: no key -> exit 1, API error -> exit 1 with message, bad usage -> 2", async () => {
  const t = withCli({ "POST /scrape": () => json(402, { error: { code: "INSUFFICIENT_CREDITS", message: "Out of credits", status: 402 } }) });
  try {
    assert.equal(await main(["scrape", "https://example.com"]), 1);
    assert.match(t.errs.join(""), /scrapecore login/);
    process.env.SCRAPECORE_API_KEY = KEY;
    assert.equal(await main(["scrape", "https://example.com"]), 1);
    assert.match(t.errs.join(""), /Out of credits/);
    assert.equal(await main(["extract", "https://x.example"]), 2);
    assert.equal(await main(["nope"]), 2);
  } finally { t.restore(); delete process.env.SCRAPECORE_API_KEY; }
});

test("cli: crawl waits then writes the export; screenshot writes the image", async () => {
  const png = Buffer.from("\x89PNG fake", "latin1");
  const t = withCli({
    "POST /crawl": () => json(200, { job_id: "j9", status: "queued", max_credits: 5 }),
    "GET /job/j9": () => json(200, { status: "success", result: { pages_ok: 3, pages_failed: 0, credits_used: 3 } }),
    "GET /crawl/j9/export": () => new Response("# llms\n", { status: 200 }),
    "POST /screenshot": () => json(200, { image_base64: png.toString("base64") }),
  });
  process.env.SCRAPECORE_API_KEY = KEY;
  try {
    const dest = join(t.dir, "llms.txt");
    assert.equal(await main(["crawl", "https://docs.example", "--limit", "5", "--export", "llms", "-o", dest]), 0);
    assert.equal(readFileSync(dest, "utf8"), "# llms\n");
    assert.match(t.errs.join(""), /3 page\(s\) ok/);
    const img = join(t.dir, "s.png");
    assert.equal(await main(["screenshot", "https://example.com", "-o", img]), 0);
    assert.ok(existsSync(img) && readFileSync(img).equals(png));
  } finally { t.restore(); delete process.env.SCRAPECORE_API_KEY; }
});
