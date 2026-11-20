"""`scrapecore` command line: scrape, map, crawl, screenshot, AI extract, search, monitors, usage.

    scrapecore login                         save an API key (~/.config/scrapecore/config.json, mode 600)
    scrapecore scrape https://example.com    the page as Markdown
    scrapecore crawl https://docs.example.com --limit 50 --export llms -o llms.txt

The API key comes from --api-key, then SCRAPECORE_API_KEY, then the saved config.
Exit codes: 0 ok, 1 API or usage error, 2 bad arguments, 130 interrupted.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from ._errors import ScrapeCoreError
from ._version import __version__

CONFIG = Path(os.environ.get("SCRAPECORE_CONFIG") or
              Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "scrapecore" / "config.json")


# ── config ──────────────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)


def client(args):
    from ._client import ScrapeCore
    cfg = load_config()
    key = args.api_key or os.environ.get("SCRAPECORE_API_KEY") or cfg.get("api_key")
    if not key:
        die("No API key. Run `scrapecore login`, set SCRAPECORE_API_KEY, or pass --api-key.")
    return ScrapeCore(key, base_url=args.base_url or os.environ.get("SCRAPECORE_BASE_URL") or cfg.get("base_url"),
                      user_agent=f"scrapecore-cli/{__version__}")


# ── output ──────────────────────────────────────────────────────────────────────────────
def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(msg, file=sys.stderr)


def out(args, data: Any, text: str | None = None):
    """--json prints the API response; otherwise `text` (or pretty JSON). -o writes to a file."""
    body = json.dumps(data, indent=2, ensure_ascii=False) if (args.json or text is None) else text
    dest = getattr(args, "output", None)
    if dest:
        Path(dest).write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        info(f"saved {dest}")
    else:
        print(body)


def table(rows: list[list], headers: list[str]) -> str:
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = lambda r: "  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip()  # noqa: E731
    return "\n".join([line(headers), line(["-" * x for x in w]), *map(line, rows)])


# ── commands ────────────────────────────────────────────────────────────────────────────
def cmd_login(args):
    key = args.api_key or os.environ.get("SCRAPECORE_API_KEY")
    if not key:
        info("Create a key at https://scrapecore.com/dashboard/api-keys")
        key = getpass.getpass("API key: ").strip()
    if not key:
        die("no key entered", 2)
    from ._client import ScrapeCore
    base = args.base_url or os.environ.get("SCRAPECORE_BASE_URL")
    with ScrapeCore(key, base_url=base, user_agent=f"scrapecore-cli/{__version__}") as sc:
        u = sc.usage()                                  # proves the key works
    cfg = load_config()
    cfg["api_key"] = key
    if base:
        cfg["base_url"] = base
    save_config(cfg)
    left = (u.get("credits_limit") or 0) - (u.get("credits_used") or 0) if "credits_limit" in u else None
    info(f"Logged in. Key saved to {CONFIG}" + (f" · {left:,} credits left" if isinstance(left, int) else ""))


def cmd_logout(args):
    cfg = load_config()
    if cfg.pop("api_key", None):
        save_config(cfg)
        info("Logged out (saved key removed).")
    else:
        info("No saved key.")


def cmd_scrape(args):
    with client(args) as sc:
        r = sc.scrape(args.url, format=args.format, js_render=args.js or None, use_proxy=args.proxy or None,
                      max_age=args.max_age)
    out(args, r, r.get(args.format) or r.get("html") or r.get("text") or "")


def cmd_map(args):
    with client(args) as sc:
        r = sc.map(args.url, limit=args.limit, search=args.search, include_subdomains=args.subdomains or None)
    out(args, r, "\n".join(r.get("urls") or []))
    info(f"{r.get('count', len(r.get('urls') or []))} URL(s)")


def cmd_crawl(args):
    with client(args) as sc:
        job = sc.crawl(args.url, max_depth=args.depth, limit=args.limit, include_paths=args.include,
                       exclude_paths=args.exclude, js_render=args.js or None, use_proxy=args.proxy or None)
        jid = job["job_id"]
        info(f"crawl {jid} queued (up to {job.get('max_credits', '?')} credits)")
        if args.no_wait:
            return out(args, job, jid)
        done = sc.wait_for_job(jid, timeout=args.timeout, raise_on_failure=False)
        r = done.get("result") or {}
        info(f"{done['status']}: {r.get('pages_ok', 0)} page(s) ok, {r.get('pages_failed', 0)} failed, "
             f"{r.get('credits_used', 0)} credits")
        if done["status"] != "success" and not r.get("pages_ok"):
            die(done.get("error") or r.get("error") or "crawl failed")
        out(args, None, sc.crawl_export(jid, args.export, chunk_size=args.chunk_size)) if not args.json \
            else out(args, done)


def cmd_export(args):
    with client(args) as sc:
        out(args, None, sc.crawl_export(args.job_id, args.format, chunk_size=args.chunk_size, overlap=args.overlap))


def cmd_screenshot(args):
    opts = {k: v for k, v in {"device": args.device, "format": args.image_format}.items() if v}
    with client(args) as sc:
        r = sc.screenshot(args.url, full_page=args.full_page, **opts)
    if args.json:
        return out(args, r)
    img = r.get("image_base64")
    if not img:
        die(r.get("error") or "no image returned")
    dest = args.output or f"screenshot.{args.image_format or 'png'}"
    Path(dest).write_bytes(base64.b64decode(img))
    info(f"saved {dest}")


def cmd_extract(args):
    with client(args) as sc:
        if args.selectors:
            try:
                sel = json.loads(args.selectors)
            except ValueError:
                die('--selectors must be JSON, e.g. \'{"title": "h1"}\'', 2)
            r = sc.extract(args.url, sel, js_render=args.js or None)
            return out(args, r, json.dumps(r.get("data", r), indent=2, ensure_ascii=False))
        schema = None
        if args.schema:
            try:
                schema = json.loads(Path(args.schema).read_text() if os.path.exists(args.schema) else args.schema)
            except ValueError:
                die("--schema must be a JSON file or a JSON string", 2)
        if not (args.prompt or schema):
            die("give --prompt and/or --schema (AI extraction), or --selectors (CSS)", 2)
        r = sc.ai_extract(args.url, prompt=args.prompt, schema=schema, model=args.model, js_render=args.js or None)
    out(args, r, json.dumps(r.get("data"), indent=2, ensure_ascii=False))
    if r.get("usage") and not args.json:
        info(f"{r.get('model')} · {r['usage'].get('input_tokens', 0)} in / {r['usage'].get('output_tokens', 0)} out "
             f"tokens (your Anthropic key) · {r.get('credits_used', 0)} credits")


def cmd_search(args):
    with client(args) as sc:
        r = sc.search(args.query, limit=args.limit, scrape=False if args.no_scrape else None)
    if args.json:
        return out(args, r)
    parts = []
    for i, x in enumerate(r.get("results") or [], 1):
        parts.append(f"{i}. {x.get('title')}\n   {x.get('url')}")
        if x.get("markdown"):
            parts.append("   " + x["markdown"][:500].replace("\n", "\n   ") + ("…" if len(x["markdown"]) > 500 else ""))
    out(args, r, "\n".join(parts) or "no results")


def cmd_monitor(args):
    with client(args) as sc:
        a = args.action
        if a == "list":
            r = sc.monitors()
            rows = [[m["id"], m["status"], m["interval_minutes"], m["changes"], m.get("last_changed_at") or "", m["url"]]
                    for m in r["monitors"]]
            return out(args, r, table(rows, ["ID", "STATUS", "EVERY(MIN)", "CHANGES", "LAST CHANGE", "URL"])
                       + f"\n{len(rows)} / {r['limit']} monitors")
        if a == "add":
            if not args.target:
                die("usage: scrapecore monitor add URL", 2)
            m = sc.create_monitor(args.target, interval_minutes=args.every, selector=args.selector, name=args.name)
            return out(args, m, f"monitor {m['id']} created: first check sets the baseline")
        if not args.target:
            die(f"usage: scrapecore monitor {a} MONITOR_ID", 2)
        if a == "check":
            r = sc.check_monitor(args.target)
            msg = (f"changed: {r.get('summary')}" if r.get("changed") else "baseline saved" if r.get("baseline")
                   else "no change" if r.get("ok") else f"check failed: {r.get('error')}")
            return out(args, r, msg)
        if a == "changes":
            ch = sc.monitor_changes(args.target, limit=args.limit or 5)
            return out(args, ch, "\n\n".join(f"# {c['created_at']}  {c['summary']}\n{c['diff']}" for c in ch) or "no changes yet")
        if a in ("pause", "resume"):
            m = sc.update_monitor(args.target, status="paused" if a == "pause" else "active")
            return out(args, m, f"monitor {m['id']} {m['status']}")
        if a == "rm":
            sc.delete_monitor(args.target)
            return out(args, {"ok": True}, f"monitor {args.target} deleted")


def cmd_jobs(args):
    with client(args) as sc:
        if args.job_id:
            j = sc.get_job(args.job_id)
            return out(args, j)
        r = sc.jobs(limit=args.limit or 20, status=args.status, type=args.type)
    rows = r if isinstance(r, list) else r.get("jobs", [])
    out(args, r, table([[j.get("job_id"), j.get("type"), j.get("status"), j.get("created_at"), j.get("url")] for j in rows],
                       ["JOB", "TYPE", "STATUS", "CREATED", "URL"]))


def cmd_usage(args):
    with client(args) as sc:
        u = sc.usage()
    lines = [f"{k.replace('_', ' ')}: {v:,}" if isinstance(v, int) else f"{k.replace('_', ' ')}: {v}"
             for k, v in u.items() if not isinstance(v, (dict, list))]
    out(args, u, "\n".join(lines))


# ── parser ──────────────────────────────────────────────────────────────────────────────
def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-key", help="API key (default: SCRAPECORE_API_KEY or `scrapecore login`)")
    common.add_argument("--base-url", help=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", help="print the raw API response as JSON")
    common.add_argument("-o", "--output", help="write the result to a file")

    p = argparse.ArgumentParser(prog="scrapecore", description="ScrapeCore from the command line.",
                                epilog="Docs: https://scrapecore.com/docs/cli")
    p.add_argument("-V", "--version", action="version", version=f"scrapecore {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name, fn, help_):
        sp = sub.add_parser(name, parents=[common], help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("login", cmd_login, "save an API key for later commands")
    add("logout", cmd_logout, "remove the saved API key")
    s = add("scrape", cmd_scrape, "scrape one page")
    s.add_argument("url")
    s.add_argument("-f", "--format", choices=["markdown", "html", "text"], default="markdown")
    s.add_argument("--js", action="store_true", help="render JavaScript")
    s.add_argument("--proxy", action="store_true", help="use a proxy")
    s.add_argument("--max-age", type=int, help="accept a stored result up to this many seconds old")
    s = add("map", cmd_map, "list every URL of a site")
    s.add_argument("url")
    s.add_argument("--limit", type=int)
    s.add_argument("--search", help="only URLs containing this text")
    s.add_argument("--subdomains", action="store_true")
    s = add("crawl", cmd_crawl, "crawl a site and print it as an AI-ready export")
    s.add_argument("url")
    s.add_argument("--depth", type=int, help="link depth (default 2)")
    s.add_argument("--limit", type=int, help="max pages (default 50)")
    s.add_argument("--include", action="append", help="path pattern to include (repeatable)")
    s.add_argument("--exclude", action="append", help="path pattern to exclude (repeatable)")
    s.add_argument("--js", action="store_true")
    s.add_argument("--proxy", action="store_true")
    s.add_argument("--export", choices=["jsonl", "markdown", "chunks", "llms", "llms-full"], default="markdown")
    s.add_argument("--chunk-size", type=int)
    s.add_argument("--timeout", type=float, default=1800)
    s.add_argument("--no-wait", action="store_true", help="print the job id and exit")
    s = add("export", cmd_export, "export a finished crawl")
    s.add_argument("job_id")
    s.add_argument("-f", "--format", choices=["jsonl", "markdown", "chunks", "llms", "llms-full"], default="jsonl")
    s.add_argument("--chunk-size", type=int)
    s.add_argument("--overlap", type=int)
    s = add("screenshot", cmd_screenshot, "save a screenshot")
    s.add_argument("url")
    s.add_argument("--full-page", action="store_true")
    s.add_argument("--device", help="desktop, desktop_hd, laptop, tablet or mobile")
    s.add_argument("--image-format", choices=["png", "jpeg"])
    s = add("extract", cmd_extract, "structured data: AI (--prompt/--schema, your Anthropic key) or CSS (--selectors)")
    s.add_argument("url")
    s.add_argument("-p", "--prompt")
    s.add_argument("--schema", help="JSON schema (file path or JSON string)")
    s.add_argument("--model")
    s.add_argument("--selectors", help='CSS selectors as JSON, e.g. \'{"title": "h1"}\'')
    s.add_argument("--js", action="store_true")
    s = add("search", cmd_search, "web search + scrape the results (your Brave / Serper key)")
    s.add_argument("query")
    s.add_argument("--limit", type=int)
    s.add_argument("--no-scrape", action="store_true", help="results only, don't fetch the pages")
    s = add("monitor", cmd_monitor, "page-change monitors: list | add URL | check ID | changes ID | pause ID | resume ID | rm ID")
    s.add_argument("action", choices=["list", "add", "check", "changes", "pause", "resume", "rm"])
    s.add_argument("target", nargs="?", help="URL (add) or monitor id")
    s.add_argument("--every", type=int, default=1440, help="minutes between checks (15, 60, 360, 1440, 10080)")
    s.add_argument("--selector", help="only watch this CSS selector")
    s.add_argument("--name")
    s.add_argument("--limit", type=int)
    s = add("jobs", cmd_jobs, "list async jobs, or show one")
    s.add_argument("job_id", nargs="?")
    s.add_argument("--limit", type=int)
    s.add_argument("--status")
    s.add_argument("--type")
    add("usage", cmd_usage, "credits and limits")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    try:
        args.fn(args)
    except ScrapeCoreError as e:
        code = getattr(e, "code", None)
        die(f"{e}" + (f" [{code}]" if code and code not in str(e) else ""))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
