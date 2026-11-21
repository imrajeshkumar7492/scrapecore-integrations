#!/usr/bin/env node
/**
 * `scrapecore` command line (Node): the same commands as the Python CLI.
 *
 *   npx @scrapecore/sdk login
 *   npx @scrapecore/sdk scrape https://example.com
 *   npx @scrapecore/sdk crawl https://docs.example.com --limit 50 --export llms -o llms.txt
 *
 * API key: --api-key, then SCRAPECORE_API_KEY, then the saved config
 * (~/.config/scrapecore/config.json, mode 600, shared with the Python CLI).
 * Exit codes: 0 ok, 1 API error, 2 bad arguments.
 */
import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { ScrapeCore } from "./client.js";
import { ScrapeCoreError } from "./errors.js";
import { VERSION } from "./version.js";

type Flags = Record<string, string | boolean | string[]>;

export const CONFIG_PATH = (): string =>
  process.env.SCRAPECORE_CONFIG ||
  join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "scrapecore", "config.json");

class UsageError extends Error {}

const BOOL = new Set(["json", "js", "proxy", "subdomains", "no-wait", "full-page", "no-scrape", "help", "version", "many"]);
const MULTI = new Set(["include", "exclude"]);
const ALIAS: Record<string, string> = { o: "output", f: "format", p: "prompt", h: "help", V: "version" };

export function parseArgs(argv: string[]): { pos: string[]; flags: Flags } {
  const pos: string[] = [];
  const flags: Flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--") { pos.push(...argv.slice(i + 1)); break; }
    if (!a.startsWith("-") || a === "-") { pos.push(a); continue; }
    let name = a.replace(/^--?/, "");
    let val: string | undefined;
    const eq = name.indexOf("=");
    if (eq >= 0) { val = name.slice(eq + 1); name = name.slice(0, eq); }
    name = ALIAS[name] ?? name;
    if (BOOL.has(name)) { flags[name] = true; continue; }
    if (val === undefined) {
      val = argv[++i];
      if (val === undefined) throw new UsageError(`--${name} needs a value`);
    }
    if (MULTI.has(name)) flags[name] = [...((flags[name] as string[]) || []), val];
    else flags[name] = val;
  }
  return { pos, flags };
}

const str = (f: Flags, k: string): string | undefined => (typeof f[k] === "string" ? (f[k] as string) : undefined);
const num = (f: Flags, k: string): number | undefined => {
  const v = str(f, k);
  if (v === undefined) return undefined;
  const n = Number(v);
  if (!Number.isFinite(n)) throw new UsageError(`--${k} must be a number`);
  return n;
};

function loadConfig(): any {
  try { return JSON.parse(readFileSync(CONFIG_PATH(), "utf8")); } catch { return {}; }
}

function saveConfig(cfg: any): void {
  const p = CONFIG_PATH();
  mkdirSync(dirname(p), { recursive: true });
  const tmp = p + ".tmp";
  writeFileSync(tmp, JSON.stringify(cfg, null, 2), { mode: 0o600 });
  chmodSync(tmp, 0o600);
  renameSync(tmp, p);
}

const info = (m: string) => process.stderr.write(m + "\n");

function client(f: Flags): ScrapeCore {
  const cfg = loadConfig();
  const apiKey = str(f, "api-key") || process.env.SCRAPECORE_API_KEY || cfg.api_key;
  if (!apiKey) throw new ScrapeCoreError("No API key. Run `scrapecore login`, set SCRAPECORE_API_KEY, or pass --api-key.");
  return new ScrapeCore({ apiKey, baseUrl: str(f, "base-url") || process.env.SCRAPECORE_BASE_URL || cfg.base_url,
                          userAgent: `scrapecore-cli/${VERSION}` });
}

function out(f: Flags, data: unknown, text?: string): void {
  const s = f.json || text === undefined ? JSON.stringify(data, null, 2) : text;
  const dest = str(f, "output");
  if (dest) { writeFileSync(dest, s.endsWith("\n") ? s : s + "\n"); info(`saved ${dest}`); }
  else process.stdout.write(s.endsWith("\n") ? s : s + "\n");
}

function table(rows: unknown[][], headers: string[]): string {
  const r = rows.map((x) => x.map((c) => (c == null ? "" : String(c))));
  const w = headers.map((h, i) => Math.max(h.length, ...r.map((x) => x[i].length)));
  const line = (x: string[]) => x.map((c, i) => c.padEnd(w[i])).join("  ").trimEnd();
  return [line(headers), line(w.map((n) => "-".repeat(n))), ...r.map(line)].join("\n");
}

function askHidden(q: string): Promise<string> {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, output: process.stderr, terminal: true });
    const w = (rl as any)._writeToOutput;
    (rl as any)._writeToOutput = (s: string) => { if (s.startsWith(q)) w.call(rl, s); };
    rl.question(q, (a) => { rl.close(); process.stderr.write("\n"); resolve(a.trim()); });
  });
}

const need = (v: string | undefined, usage: string): string => {
  if (!v) throw new UsageError(`usage: scrapecore ${usage}`);
  return v;
};

const EXPORTS = ["jsonl", "markdown", "chunks", "llms", "llms-full"];

const COMMANDS: Record<string, { help: string; run: (pos: string[], f: Flags) => Promise<void> }> = {
  login: {
    help: "save an API key for later commands",
    async run(_p, f) {
      let key = str(f, "api-key") || process.env.SCRAPECORE_API_KEY;
      if (!key) { info("Create a key at https://scrapecore.com/dashboard/api-keys"); key = await askHidden("API key: "); }
      if (!key) throw new UsageError("no key entered");
      const base = str(f, "base-url") || process.env.SCRAPECORE_BASE_URL;
      const u = await new ScrapeCore({ apiKey: key, baseUrl: base, userAgent: `scrapecore-cli/${VERSION}` }).usage();
      const cfg = loadConfig();
      cfg.api_key = key;
      if (base) cfg.base_url = base;
      saveConfig(cfg);
      const left = typeof u?.credits_limit === "number" ? u.credits_limit - (u.credits_used || 0) : undefined;
      info(`Logged in. Key saved to ${CONFIG_PATH()}` + (left !== undefined ? ` · ${left.toLocaleString("en-US")} credits left` : ""));
    },
  },
  logout: {
    help: "remove the saved API key",
    async run() {
      const cfg = loadConfig();
      if (cfg.api_key) { delete cfg.api_key; saveConfig(cfg); info("Logged out (saved key removed)."); } else info("No saved key.");
    },
  },
  scrape: {
    help: "scrape one page (--format markdown|html|text, --js, --proxy)",
    async run(p, f) {
      const format = (str(f, "format") || "markdown") as any;
      const r: any = await client(f).scrape(need(p[0], "scrape URL"), { format, jsRender: f.js ? true : undefined,
        useProxy: f.proxy ? true : undefined, maxAge: num(f, "max-age") });
      out(f, r, r[format] ?? r.html ?? r.text ?? "");
    },
  },
  map: {
    help: "list every URL of a site (--limit, --search)",
    async run(p, f) {
      const r: any = await client(f).map(need(p[0], "map URL"), { limit: num(f, "limit"), search: str(f, "search"),
        includeSubdomains: f.subdomains ? true : undefined });
      out(f, r, (r.urls || []).join("\n"));
    },
  },
  crawl: {
    help: "crawl a site and print it as an AI-ready export (--limit, --depth, --export llms|markdown|...)",
    async run(p, f) {
      const sc = client(f);
      const fmt = str(f, "export") || "markdown";
      if (!EXPORTS.includes(fmt)) throw new UsageError(`--export must be one of ${EXPORTS.join(", ")}`);
      const job: any = await sc.crawl(need(p[0], "crawl URL"), { maxDepth: num(f, "depth"), limit: num(f, "limit"),
        includePaths: f.include as string[] | undefined, excludePaths: f.exclude as string[] | undefined,
        jsRender: f.js ? true : undefined, useProxy: f.proxy ? true : undefined });
      info(`crawl ${job.job_id} queued (up to ${job.max_credits ?? "?"} credits)`);
      if (f["no-wait"]) return out(f, job, job.job_id);
      const done: any = await sc.waitForJob(job.job_id, { timeout: num(f, "timeout") ?? 1800, throwOnFailure: false });
      const r = done.result || {};
      info(`${done.status}: ${r.pages_ok ?? 0} page(s) ok, ${r.pages_failed ?? 0} failed, ${r.credits_used ?? 0} credits`);
      if (done.status !== "success" && !r.pages_ok) throw new ScrapeCoreError(done.error || r.error || "crawl failed");
      if (f.json) return out(f, done);
      out(f, null, await sc.crawlExport(job.job_id, fmt as any, { chunkSize: num(f, "chunk-size") }));
    },
  },
  export: {
    help: "export a finished crawl (--format jsonl|markdown|chunks|llms|llms-full)",
    async run(p, f) {
      const fmt = str(f, "format") || "jsonl";
      if (!EXPORTS.includes(fmt)) throw new UsageError(`--format must be one of ${EXPORTS.join(", ")}`);
      out(f, null, await client(f).crawlExport(need(p[0], "export JOB_ID"), fmt as any,
        { chunkSize: num(f, "chunk-size"), overlap: num(f, "overlap") }));
    },
  },
  screenshot: {
    help: "save a screenshot (-o file.png, --full-page, --device)",
    async run(p, f) {
      const r: any = await client(f).screenshot(need(p[0], "screenshot URL"), {
        fullPage: f["full-page"] ? true : undefined, device: str(f, "device") as any, format: str(f, "image-format") as any });
      if (f.json) return out(f, r);
      if (!r?.image_base64) throw new ScrapeCoreError(r?.error || "no image returned");
      const dest = str(f, "output") || `screenshot.${str(f, "image-format") || "png"}`;
      writeFileSync(dest, Buffer.from(r.image_base64, "base64"));
      info(`saved ${dest}`);
    },
  },
  extract: {
    help: "structured data: AI (--prompt / --schema, your Anthropic key) or CSS (--selectors JSON)",
    async run(p, f) {
      const url = need(p[0], "extract URL --prompt ...");
      const sc = client(f);
      const selectors = str(f, "selectors");
      if (selectors) {
        let sel: any;
        try { sel = JSON.parse(selectors); } catch { throw new UsageError(`--selectors must be JSON, e.g. '{"title": "h1"}'`); }
        const r: any = await sc.extract(url, sel, { jsRender: f.js ? true : undefined });
        return out(f, r, JSON.stringify(r.data ?? r, null, 2));
      }
      let schema: any;
      const s = str(f, "schema");
      if (s) {
        try { schema = JSON.parse(existsSync(s) ? readFileSync(s, "utf8") : s); }
        catch { throw new UsageError("--schema must be a JSON file or a JSON string"); }
      }
      if (!str(f, "prompt") && !schema) throw new UsageError("give --prompt and/or --schema (AI extraction), or --selectors (CSS)");
      const r = await sc.aiExtract(url, { prompt: str(f, "prompt"), schema, model: str(f, "model"), jsRender: f.js ? true : undefined });
      out(f, r, JSON.stringify(r.data, null, 2));
      if (r.usage && !f.json) info(`${r.model} · ${r.usage.input_tokens} in / ${r.usage.output_tokens} out tokens (your Anthropic key)`);
    },
  },
  ai: {
    help: "AI extraction job over many pages with your own AI key (URLs | --file | --sitemap | --site; -p, --schema, --many)",
    async run(p, f) {
      const sc = client(f);
      let urls = [...p];
      const file = str(f, "file");
      if (file) urls = urls.concat(readFileSync(file, "utf8").match(/https?:\/\/[^\s,;"'<>]+/g) || []);
      let schema: any;
      const s = str(f, "schema");
      if (s) {
        try { schema = JSON.parse(existsSync(s) ? readFileSync(s, "utf8") : s); }
        catch { throw new UsageError("--schema must be a JSON file or a JSON string"); }
      }
      if (!urls.length && !str(f, "sitemap") && !str(f, "site")) throw new UsageError("give URLs, --file, --sitemap or --site");
      if (!str(f, "prompt") && !schema) throw new UsageError("give --prompt and/or --schema");
      const job = await sc.aiJob(urls.length ? urls : null, { instructions: str(f, "prompt") || "", schema, sitemap: str(f, "sitemap"),
        site: str(f, "site"), records: f.many ? "list" : "single", provider: str(f, "provider"), model: str(f, "model"),
        name: str(f, "name"), project: str(f, "project") });
      info(`AI job ${job.job_id} queued: ${job.provider} / ${job.model}`);
      if (f["no-wait"]) return out(f, job, job.job_id);
      let last = "";
      let j: any;
      for (;;) {
        j = await sc.getAiJob(job.job_id);
        const t = j.totals || {};
        const line = `${j.status}: ${(t.ok || 0) + (t.failed || 0)}/${t.urls || 0} pages, ${t.records || 0} records`;
        if (line !== last) { info(line); last = line; }
        if (["completed", "partially_completed", "failed", "cancelled"].includes(j.status)) break;
        await new Promise((r) => setTimeout(r, Number(process.env.SCRAPECORE_POLL_MS || 3000)));
      }
      if (j.status === "failed" && !(j.totals || {}).records) throw new ScrapeCoreError(j.error || "the job failed");
      if (f.json) return out(f, await sc.aiJobRecords(job.job_id));
      const fmt = (str(f, "format") || "json") as any;
      const data = await sc.aiJobExport(job.job_id, fmt);
      const dest = str(f, "output") || (fmt === "xlsx" ? `${job.job_id}.xlsx` : undefined);
      if (dest) { writeFileSync(dest, data); info(`saved ${dest}`); }
      else process.stdout.write(Buffer.from(data).toString("utf8").replace(/^\uFEFF/, ""));
    },
  },
  monitor: {
    help: "page-change monitors: list | add URL | check ID | changes ID | pause ID | resume ID | rm ID",
    async run(p, f) {
      const sc = client(f);
      const [action, target] = p;
      if (action === "list" || !action) {
        const r = await sc.monitors();
        const rows = r.monitors.map((m) => [m.id, m.status, m.interval_minutes, m.changes, m.last_changed_at ?? "", m.url]);
        return out(f, r, table(rows, ["ID", "STATUS", "EVERY(MIN)", "CHANGES", "LAST CHANGE", "URL"]) + `\n${rows.length} / ${r.limit} monitors`);
      }
      const id = need(target, `monitor ${action} ${action === "add" ? "URL" : "MONITOR_ID"}`);
      if (action === "add") {
        const m = await sc.createMonitor(id, { intervalMinutes: num(f, "every") ?? 1440, selector: str(f, "selector"), name: str(f, "name") });
        return out(f, m, `monitor ${m.id} created: first check sets the baseline`);
      }
      if (action === "check") {
        const r = await sc.checkMonitor(id);
        return out(f, r, r.changed ? `changed: ${r.summary}` : r.baseline ? "baseline saved" : r.ok ? "no change" : `check failed: ${r.error}`);
      }
      if (action === "changes") {
        const ch = await sc.monitorChanges(id, { limit: num(f, "limit") ?? 5 });
        return out(f, ch, ch.map((c) => `# ${c.created_at}  ${c.summary}\n${c.diff}`).join("\n\n") || "no changes yet");
      }
      if (action === "pause" || action === "resume") {
        const m = await sc.updateMonitor(id, { status: action === "pause" ? "paused" : "active" });
        return out(f, m, `monitor ${m.id} ${m.status}`);
      }
      if (action === "rm") { await sc.deleteMonitor(id); return out(f, { ok: true }, `monitor ${id} deleted`); }
      throw new UsageError("usage: scrapecore monitor list|add|check|changes|pause|resume|rm");
    },
  },
  jobs: {
    help: "list async jobs, or show one (JOB_ID)",
    async run(p, f) {
      const sc = client(f);
      if (p[0]) return out(f, await sc.getJob(p[0]));
      const r: any = await sc.jobs({ limit: num(f, "limit") ?? 20, status: str(f, "status"), type: str(f, "type") });
      const rows = Array.isArray(r) ? r : r.jobs || [];
      out(f, r, table(rows.map((j: any) => [j.job_id, j.type, j.status, j.created_at, j.url]), ["JOB", "TYPE", "STATUS", "CREATED", "URL"]));
    },
  },
  search: {
    help: "search engines (-e google|bing|yahoo|duckduckgo|yandex|baidu, -t web|news|image|video|shopping|map|..., --results, --country)",
    async run(p, f) {
      const r: any = await client(f).search(need(p.join(" "), "search QUERY"), { engine: str(f, "engine") || str(f, "e") || "google",
        searchType: str(f, "type") || str(f, "t") || "web", numResults: num(f, "results"), country: str(f, "country"),
        language: str(f, "language"), resultRange: str(f, "range") });
      const rows = (r.organic_results || []) as any[];
      out(f, r, rows.map((x) => `${x.rank}. ${x.title}\n   ${x.url}`).join("\n") || JSON.stringify(r, null, 2));
    },
  },
  youtube: {
    help: "YouTube: youtube search QUERY | video URL | channel URL | download URL",
    async run(p, f) {
      const [action, ...rest] = p;
      const map: Record<string, string> = { search: "search", video: "scrape_video", channel: "scrape_channel", download: "download" };
      const a = map[need(action, "youtube ACTION")] || action;
      const target = need(rest.join(" "), "youtube ACTION TARGET");
      out(f, await client(f).youtube(a, a === "search" ? { query: target } : { url: target }));
    },
  },
  social: {
    help: "social media: social PLATFORM TARGET [--action A] (twitter, instagram, tiktok, reddit, github, linkedin, rss, ...)",
    async run(p, f) {
      const [platform, ...rest] = p;
      out(f, await client(f).social(need(platform, "social PLATFORM"), rest.join(" ") || undefined,
        { action: str(f, "action"), limit: num(f, "limit") }));
    },
  },
  ecommerce: {
    help: "e-commerce: ecommerce search QUERY | product URL | reviews URL [--platform amazon|flipkart|walmart|...]",
    async run(p, f) {
      const [action, ...rest] = p;
      const map: Record<string, string> = { search: "search", product: "scrape_product", reviews: "scrape_reviews", category: "scrape_category" };
      const a = map[need(action, "ecommerce ACTION")] || action;
      const target = need(rest.join(" "), "ecommerce ACTION TARGET");
      out(f, await client(f).ecommerce(a, { platform: str(f, "platform"), ...(a === "search" ? { query: target } : { url: target }),
        country: str(f, "country"), numPages: num(f, "pages") }));
    },
  },
  maps: {
    help: 'maps: maps search "QUERY" [--location City] | place URL | reviews URL | directions "A to B"',
    async run(p, f) {
      const [action, ...rest] = p;
      const map: Record<string, string> = { search: "search", place: "scrape_location", reviews: "scrape_reviews", directions: "directions" };
      const a = map[need(action, "maps ACTION")] || action;
      const target = need(rest.join(" "), "maps ACTION TARGET");
      let opts: Record<string, unknown> = {};
      if (a === "search") opts = { query: target, location: str(f, "location") ? { city: str(f, "location") } : undefined };
      else if (a === "directions") {
        const [o, d] = target.split(" to ");
        opts = { origin: need(o, 'directions "A to B"'), destination: need(d, 'directions "A to B"'), mode: str(f, "mode") };
      } else opts = { url: target };
      out(f, await client(f).maps(a, opts));
    },
  },
  usage: {
    help: "credits and limits",
    async run(_p, f) {
      const u = await client(f).usage();
      out(f, u, Object.entries(u).filter(([, v]) => typeof v !== "object").map(([k, v]) =>
        `${k.replace(/_/g, " ")}: ${typeof v === "number" ? v.toLocaleString("en-US") : v}`).join("\n"));
    },
  },
};

function help(): string {
  const w = Math.max(...Object.keys(COMMANDS).map((k) => k.length));
  return [`scrapecore ${VERSION}: ScrapeCore from the command line`, "", "usage: scrapecore COMMAND [options]", "",
    ...Object.entries(COMMANDS).map(([k, c]) => `  ${k.padEnd(w)}  ${c.help}`), "",
    "options: --api-key KEY  --json  -o/--output FILE", "docs: https://scrapecore.com/docs/cli"].join("\n");
}

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  try {
    const { pos, flags } = parseArgs(argv);
    if (flags.version) { process.stdout.write(`scrapecore ${VERSION}\n`); return 0; }
    const [cmd, ...rest] = pos;
    if (!cmd || flags.help || !COMMANDS[cmd]) {
      process.stdout.write(help() + "\n");
      return cmd && !COMMANDS[cmd] ? 2 : 0;
    }
    await COMMANDS[cmd].run(rest, flags);
    return 0;
  } catch (e: any) {
    if (e instanceof UsageError) { info(`error: ${e.message}`); return 2; }
    if (e instanceof ScrapeCoreError) {
      const code = (e as any).code;
      info(`error: ${e.message}${code && !e.message.includes(code) ? ` [${code}]` : ""}`);
      return 1;
    }
    throw e;
  }
}

// run when executed directly (not when imported by tests)
const self = (process.argv[1] || "").replace(/\\/g, "/");
if (/\/(cli\.js|scrapecore)$/.test(self) || self.endsWith("/.bin/scrapecore")) {
  main().then((code) => process.exit(code));
}
