"""Data API commands for the `scrapecore` / `scraper` CLI (v2.0): search, ecommerce, youtube,
social, maps, batch, config, auth, health, status, history, completion, man.

Display: --as json|yaml|table|text (default: a table/summary in a terminal, JSON when piped).
Colours, tables and spinners come from `rich` when it is installed (pip install "scrapecore-sdk[cli]");
without it the output is plain text. Long output goes through a pager in an interactive terminal.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
from pathlib import Path
from typing import Any

try:                                  # optional pretty output
    from rich.console import Console
    from rich.table import Table
    _RICH = True
except ImportError:                   # pragma: no cover - exercised when rich is missing
    _RICH = False

LIST_KEYS = ("organic_results", "results", "image_results", "news_results", "shopping_results", "video_results",
             "short_video_results", "map_results", "book_results", "forum_results", "products", "reviews", "entries",
             "episodes", "messages", "posts", "videos", "recent_posts", "recent_videos", "jobs", "comments", "routes",
             "repos", "reels")
TITLE = ("title", "product_title", "name", "business_name", "thread_title", "question", "author")
URL = ("url", "product_url", "video_url", "short_url", "link", "permalink", "maps_url", "website")
EXTRA = ("price", "current_price", "rating", "average_rating", "views", "score", "likes", "duration", "date",
         "published", "source_name", "domain", "address", "review_count", "channel")


def _console(stderr: bool = False):
    return Console(stderr=stderr, highlight=False) if _RICH else None


def _pick(o: dict, keys) -> Any:
    for k in keys:
        if isinstance(o, dict) and o.get(k) not in (None, ""):
            return o[k]
    return None


def to_yaml(v: Any, indent: int = 0) -> str:
    """Small YAML emitter (no dependency) for dict/list/scalar JSON data."""
    pad = "  " * indent
    if isinstance(v, dict):
        if not v:
            return "{}"
        lines = []
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                lines.append(f"{pad}{k}:\n{to_yaml(x, indent + 1)}")
            else:
                lines.append(f"{pad}{k}: {to_yaml(x, 0)}")
        return "\n".join(lines)
    if isinstance(v, list):
        if not v:
            return "[]"
        out = []
        for x in v:
            if isinstance(x, (dict, list)) and x:
                body = to_yaml(x, indent + 1).lstrip()
                out.append(f"{pad}- {body}")
            else:
                out.append(f"{pad}- {to_yaml(x, 0)}")
        return "\n".join(out)
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or any(c in s for c in ":#{}[],&*!|>'\"%@`\n") or s.strip() != s or s.lower() in ("yes", "no", "true", "false", "null"):
        return json.dumps(s, ensure_ascii=False)
    return s


def main_list(data: dict) -> tuple[str | None, list]:
    for k in LIST_KEYS:
        if isinstance(data.get(k), list) and data[k]:
            return k, data[k]
    return None, []


def summary_lines(data: dict) -> list[str]:
    head = []
    for k in ("engine", "search_type", "platform", "action", "query_used", "query", "render_tier", "credits_used",
              "credits_remaining", "cached"):
        if data.get(k) not in (None, "", [], {}):
            head.append(f"{k.replace('_', ' ')}: {data[k]}")
    return head


def render(args, data: Any) -> None:
    """Print a result in the chosen display mode (or write it with -o FILE)."""
    mode = getattr(args, "as_", None) or ("json" if getattr(args, "json", False) else None)
    if mode is None:
        mode = "table" if sys.stdout.isatty() else "json"
    dest = getattr(args, "output", None)
    if mode == "json" or dest and mode == "table":
        text = json.dumps(data, indent=2, ensure_ascii=False)
    elif mode == "yaml":
        text = to_yaml(data)
    elif mode == "text":
        key, rows = main_list(data) if isinstance(data, dict) else (None, [])
        lines = summary_lines(data) if isinstance(data, dict) else []
        for r in rows:
            lines.append(f"{r.get('rank', '')}. {_pick(r, TITLE) or ''}\n   {_pick(r, URL) or ''}")
        text = "\n".join(lines) or json.dumps(data, indent=2, ensure_ascii=False)
    else:
        if _RICH and isinstance(data, dict):
            return _rich_table(data)
        key, rows = main_list(data) if isinstance(data, dict) else (None, [])
        from ._cli import table
        text = "\n".join(summary_lines(data)) + ("\n\n" if rows else "") + (table(
            [[r.get("rank", i + 1), str(_pick(r, TITLE) or "")[:70], str(_pick(r, URL) or "")[:60],
              str(_pick(r, EXTRA) or "")[:20]] for i, r in enumerate(rows)], ["#", "title", "url", "info"]) if rows else
            json.dumps({k: v for k, v in data.items() if not isinstance(v, (list, dict))}, indent=2, ensure_ascii=False))
    if dest:
        Path(dest).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        print(f"saved {dest}", file=sys.stderr)
        return
    _page(text)


def _page(text: str) -> None:
    import shutil
    rows = shutil.get_terminal_size((80, 24)).lines
    if sys.stdout.isatty() and text.count("\n") > rows and not os.environ.get("SCRAPECORE_NO_PAGER"):
        import pydoc
        pydoc.pager(text)
    else:
        print(text)


def _rich_table(data: dict) -> None:
    con = _console()
    head = summary_lines(data)
    if head:
        con.print("[bold green]✓[/] " + "  ·  ".join(head))
    for k in ("featured_snippet", "knowledge_panel"):
        v = data.get(k) or {}
        if v.get("present"):
            con.print(f"[bold]{k.replace('_', ' ').title()}:[/] {v.get('title') or ''} — {str(v.get('snippet') or v.get('description') or '')[:300]}")
    key, rows = main_list(data)
    if rows:
        t = Table(title=key.replace("_", " "), show_lines=False, header_style="bold cyan", expand=True)
        t.add_column("#", justify="right", style="dim", no_wrap=True)
        t.add_column("title", overflow="fold", ratio=4)
        t.add_column("url", overflow="fold", style="blue", ratio=3)
        t.add_column("info", overflow="fold", ratio=1)
        for i, r in enumerate(rows):
            t.add_row(str(r.get("rank", i + 1)), str(_pick(r, TITLE) or ""), str(_pick(r, URL) or ""), str(_pick(r, EXTRA) or ""))
        with con.pager(styles=True) if len(rows) > 40 and sys.stdout.isatty() else _null():
            con.print(t)
    else:
        flat = {k: v for k, v in data.items() if not isinstance(v, (list, dict)) and k not in ("success",)}
        t = Table(show_header=False, box=None)
        for k, v in flat.items():
            t.add_row(f"[dim]{k.replace('_', ' ')}[/]", str(v))
        con.print(t)
        for k, v in data.items():
            if isinstance(v, dict) and v and k not in ("_billing", "parser", "tier_attempts"):
                con.print(f"[bold]{k.replace('_', ' ')}[/]: " + ", ".join(f"{kk}={vv}" for kk, vv in list(v.items())[:12]
                                                                      if not isinstance(vv, (dict, list))))
    if data.get("warnings"):
        for w in data["warnings"]:
            con.print(f"[yellow]! {w}[/]")


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def spin(label: str):
    """Spinner while a request runs (stderr), when rich is available and stderr is a terminal."""
    if _RICH and sys.stderr.isatty():
        return _console(stderr=True).status(f"[cyan]{label}…", spinner="dots")
    return _null()


def _json_arg(v):
    if v is None:
        return None
    p = Path(v)
    try:
        return json.loads(p.read_text()) if p.exists() else json.loads(v)
    except ValueError:
        from ._cli import die
        die(f"not valid JSON: {v[:80]}", 2)


# ── commands ──────────────────────────────────────────────────────────────────
def cmd_search(args):
    from ._cli import client
    params = {"num_results": args.results, "result_range": args.range, "page": args.page, "country": args.country,
              "language": args.language, "device": args.device, "time_filter": args.time, "safe_search": args.safe or None,
              "include_ads": args.ads or None, "exact_match": args.exact or None, "no_cache": args.fresh or None}
    if args.depth:
        params["scrape_depth"] = 1
        params["scrape_options"] = {"js_render": args.js, "use_proxy": args.proxy, "output_format": args.page_format}
    if args.as_ in ("markdown",):
        params["output_format"] = "markdown"
    with client(args) as sc, spin(f"searching {args.engine}"):
        r = sc.search(" ".join(args.query), engine=args.engine, search_type=args.type,
                      **{k: v for k, v in params.items() if v is not None})
    if args.as_ == "markdown":
        print(r.get("markdown") or "")
        return
    render(args, r)


def cmd_web_search(args):
    from ._cli import client
    with client(args) as sc, spin("ScrapeCore Search"):
        r = sc.web_search(" ".join(args.query), engines=args.engines.split(",") if args.engines else None,
                          num_results=args.results, content=args.content, country=args.country)
    render(args, r)


def cmd_youtube(args):
    from ._cli import client
    a = {"search": "search", "video": "scrape_video", "channel": "scrape_channel", "download": "download",
         "screenshot": "screenshot"}[args.action]
    p: dict = {}
    if a == "search":
        p = {"query": " ".join(args.target), "num_results": args.limit,
             "filters": {k: v for k, v in {"upload_date": args.uploaded, "duration": args.duration, "sort_by": args.sort,
                                           "type": args.kind}.items() if v} or None}
    else:
        p = {"url": " ".join(args.target)}
    if a == "scrape_video":
        p.update(include_transcript=not args.no_transcript, include_comments=not args.no_comments, max_comments=args.limit)
    if a == "scrape_channel":
        p["num_results"] = args.limit
    if a == "download":
        p.update(quality=args.quality, format=args.format)
    with client(args) as sc, spin(f"youtube {args.action}"):
        r = sc.youtube(a, **{k: v for k, v in p.items() if v is not None})
    render(args, r)


def cmd_social(args):
    from ._cli import client
    with client(args) as sc, spin(f"{args.platform}"):
        r = sc.social(args.platform, " ".join(args.target) if args.target else None, action=args.action,
                      limit=args.limit, sort=args.sort, query=args.query)
    render(args, r)


def cmd_ecommerce(args):
    from ._cli import client
    a = {"search": "search", "product": "scrape_product", "reviews": "scrape_reviews", "category": "scrape_category",
         "compare": "compare_products", "seller": "scrape_seller"}[args.action]
    p = {"country": args.country, "domain": args.domain, "zip_code": args.zip, "currency": args.currency,
         "sort_by": args.sort, "num_pages": args.pages, "num_results": args.limit,
         "include_screenshot": args.screenshot or None}
    tgt = " ".join(args.target)
    if a == "search":
        p["query"] = tgt
    elif a == "compare_products":
        p["urls"] = args.target
    elif a == "scrape_seller" and not tgt.startswith("http"):
        p["merchant_id"] = tgt
    else:
        p["url"] = tgt
    with client(args) as sc, spin(f"{args.platform or 'shop'} {args.action}"):
        r = sc.ecommerce(a, platform=args.platform, **{k: v for k, v in p.items() if v is not None})
    render(args, r)


def cmd_maps(args):
    from ._cli import client
    a = {"search": "search", "nearby": "nearby", "place": "scrape_location", "reviews": "scrape_reviews",
         "directions": "directions"}[args.action]
    p: dict = {"result_range": args.results if a in ("search", "nearby") else None}
    tgt = " ".join(args.target)
    if a == "search":
        p["query"] = tgt
        if args.location:
            parts = [x.strip() for x in args.location.split(",")]
            p["location"] = {"city": parts[0], **({"country": parts[-1]} if len(parts) > 1 else {})}
    elif a == "nearby":
        lat, lng = (float(x) for x in tgt.replace(" ", "").split(","))
        p.update(query=args.query, location={"lat": lat, "lng": lng, "radius_km": args.radius})
    elif a in ("scrape_location", "scrape_reviews"):
        p.update(url=tgt if tgt.startswith("http") else None, place_id=None if tgt.startswith("http") else tgt,
                 max_reviews=args.limit)
    else:
        if " to " not in tgt:
            from ._cli import die
            die('directions: use "ORIGIN to DESTINATION"', 2)
        o, d = tgt.split(" to ", 1)
        p.update(origin=o.strip(), destination=d.strip(), mode=args.mode)
    if args.depth and a in ("search", "nearby"):
        p["scrape_depth"] = 1
    with client(args) as sc, spin(f"maps {args.action}"):
        r = sc.maps(a, **{k: v for k, v in p.items() if v is not None})
    render(args, r)


def cmd_batch(args):
    """Run many scrapes or searches concurrently; one JSON file per item in --out-dir."""
    from ._cli import client, die
    lines = [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        die("the file has no lines", 2)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"ok": 0, "failed": 0, "credits": 0}

    def one(i_item):
        i, item = i_item
        with client(args) as sc:
            try:
                r = (sc.scrape(item, format=args.format) if args.kind == "scrape" else
                     sc.search(item, engine=args.engine, num_results=args.results))
                (out_dir / f"{i:05d}.json").write_text(json.dumps({"input": item, **r}, ensure_ascii=False, indent=2), encoding="utf-8")
                return True, r.get("credits_used") or 0, item
            except Exception as e:  # noqa: BLE001 — one failure must not stop the batch
                (out_dir / f"{i:05d}.error.json").write_text(json.dumps({"input": item, "error": str(e)}), encoding="utf-8")
                return False, 0, item
    if _RICH and sys.stderr.isatty():
        from rich.progress import Progress
        with Progress(console=_console(stderr=True)) as prog:
            task = prog.add_task(f"{args.kind} ×{len(lines)}", total=len(lines))
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                for ok, cr, _ in ex.map(one, enumerate(lines, 1)):
                    results["ok" if ok else "failed"] += 1
                    results["credits"] += cr
                    prog.advance(task)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            for n, (ok, cr, item) in enumerate(ex.map(one, enumerate(lines, 1)), 1):
                results["ok" if ok else "failed"] += 1
                results["credits"] += cr
                print(f"[{n}/{len(lines)}] {'ok ' if ok else 'ERR'} {item}", file=sys.stderr)
    print(json.dumps({**results, "out_dir": str(out_dir)}))


def cmd_config(args):
    from ._cli import CONFIG, load_config, save_config
    cfg = load_config()
    if args.action == "set-key":
        cfg["api_key"] = args.value
        save_config(cfg)
        print(f"API key saved to {CONFIG}", file=sys.stderr)
    elif args.action == "set-url":
        cfg["base_url"] = args.value
        save_config(cfg)
        print(f"base URL saved: {args.value}", file=sys.stderr)
    elif args.action == "set":
        k, _, v = (args.value or "").partition("=")
        if not k or not v:
            from ._cli import die
            die("use: scrapecore config set key=value", 2)
        cfg.setdefault("defaults", {})[k] = v
        save_config(cfg)
    else:
        shown = dict(cfg)
        if shown.get("api_key"):
            shown["api_key"] = shown["api_key"][:8] + "…" + shown["api_key"][-4:]
        shown["config_file"] = str(CONFIG)
        render(args, shown)


def cmd_auth_status(args):
    from ._cli import client
    with client(args) as sc:
        u = sc.usage()
    render(args, {"authenticated": True, **{k: v for k, v in u.items() if not isinstance(v, (dict, list))}})


def cmd_health(args):
    from ._cli import client
    with client(args) as sc:
        render(args, sc.health())


def cmd_history(args):
    from ._cli import client
    with client(args) as sc:
        h = sc.history(args.limit)
    render(args, {"results": h if isinstance(h, list) else [h]})


def cmd_completion(args):
    """Shell completion script (bash/zsh/fish) generated from the parser."""
    from ._cli import parser
    p = parser()
    cmds = sorted(a for action in p._subparsers._group_actions for a in action.choices)  # noqa: SLF001
    words = " ".join(cmds)
    prog = args.prog
    if args.shell == "bash":
        print(f'_{prog}_complete() {{ COMPREPLY=($(compgen -W "{words}" -- "${{COMP_WORDS[COMP_CWORD]}}")); }}\n'
              f"complete -F _{prog}_complete {prog}")
    elif args.shell == "zsh":
        print(f"#compdef {prog}\n_arguments '1:command:({words})' '*::arg:->args'")
    else:
        for c in cmds:
            print(f"complete -c {prog} -n '__fish_use_subcommand' -a {c}")


def cmd_man(args):
    """A man page (roff) built from the parser's help."""
    from ._cli import parser
    from ._version import __version__
    p = parser()
    out = [f'.TH SCRAPECORE 1 "" "scrapecore {__version__}" "User Commands"', ".SH NAME",
           "scrapecore, scraper \\- ScrapeCore web scraping and data APIs from the command line", ".SH SYNOPSIS",
           ".B scrapecore\n\\fICOMMAND\\fR [\\fIoptions\\fR]", ".SH COMMANDS"]
    for action in p._subparsers._group_actions:  # noqa: SLF001
        for name, sp in action.choices.items():
            out += [f".TP\n.B {name}", (sp.description or "").replace("-", "\\-")]
    out += [".SH ENVIRONMENT", ".TP\n.B SCRAPECORE_API_KEY\nAPI key (or run scrapecore login)",
            ".SH FILES", "~/.config/scrapecore/config.json", ".SH SEE ALSO", "https://scrapecore.com/docs/cli"]
    print("\n".join(out))


def register(add, sub_common) -> None:
    """Add the data API commands to the main parser (`add(name, fn, help)` returns a subparser)."""
    def disp(sp):
        sp.add_argument("--as", dest="as_", choices=["json", "yaml", "table", "text", "markdown"],
                        help="display: json, yaml, table (default in a terminal), text")
        return sp
    s = disp(add("search", cmd_search, "search engines: Google, Bing, Yahoo, DuckDuckGo, Yandex, Baidu"))
    s.add_argument("query", nargs="+")
    s.add_argument("-e", "--engine", choices=["google", "bing", "yahoo", "duckduckgo", "yandex", "baidu"], default="google")
    s.add_argument("-t", "--type", default="web", help="web, news, image, video, shopping, map, forum, book, short_video, ai")
    s.add_argument("-n", "--results", type=int, help="number of results")
    s.add_argument("--range", choices=["top3", "top10", "11-20", "21-30", "31-40", "all"])
    s.add_argument("--page", type=int)
    s.add_argument("--country")
    s.add_argument("--language")
    s.add_argument("--device", choices=["desktop", "mobile"])
    s.add_argument("--time", choices=["past_hour", "past_day", "past_week", "past_month", "past_year"])
    s.add_argument("--safe", action="store_true")
    s.add_argument("--ads", action="store_true", help="include ads")
    s.add_argument("--exact", action="store_true", help="exact phrase")
    s.add_argument("--depth", type=int, choices=[0, 1], default=0, help="1 = also scrape each result page")
    s.add_argument("--js", action="store_true", help="(depth 1) render result pages")
    s.add_argument("--proxy", action="store_true", help="(depth 1) use a proxy")
    s.add_argument("--page-format", default="markdown", help="(depth 1) markdown, plain_text, json, ai_query, html")
    s.add_argument("--fresh", action="store_true", help="skip the cache")
    s = disp(add("web-search", cmd_web_search, "ScrapeCore Search: engines + crawl index, ranked, pages already scraped"))
    s.add_argument("query", nargs="+")
    s.add_argument("--engines", help="comma list, default google,bing,duckduckgo")
    s.add_argument("-n", "--results", type=int, default=5)
    s.add_argument("--content", default="markdown", help="markdown, ai_query, plain_text, json, metadata, html, none")
    s.add_argument("--country")
    s = disp(add("youtube", cmd_youtube, "YouTube: search | video URL | channel URL | download URL | screenshot URL"))
    s.add_argument("action", choices=["search", "video", "channel", "download", "screenshot"])
    s.add_argument("target", nargs="+", help="query or URL")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--uploaded", choices=["hour", "today", "week", "month", "year"])
    s.add_argument("--duration", choices=["short", "medium", "long"])
    s.add_argument("--sort", choices=["relevance", "upload_date", "view_count", "rating"])
    s.add_argument("--kind", choices=["video", "channel", "playlist", "movie"])
    s.add_argument("--no-transcript", action="store_true")
    s.add_argument("--no-comments", action="store_true")
    s.add_argument("--quality", default="best", help="best, 1080p, 720p, 480p, 360p, audio_only")
    s.add_argument("--format", default="mp4", help="mp4, webm, m4a, mp3")
    s = disp(add("social", cmd_social, "social media: twitter, instagram, tiktok, reddit, github, linkedin, telegram, rss, podcast, ..."))
    s.add_argument("platform", choices=["twitter", "x", "instagram", "tiktok", "snapchat", "sharechat", "threads", "rss", "linkedin",
                                        "telegram", "github", "reddit", "substack", "podcast"])
    s.add_argument("target", nargs="*", help="URL, @handle, owner/repo, r/subreddit or query")
    s.add_argument("-a", "--action", help="platform action (default: the platform's main one)")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--sort")
    s.add_argument("--query", help="(podcast) search inside episodes")
    s = disp(add("ecommerce", cmd_ecommerce, "e-commerce: search | product URL | reviews URL | category URL | compare URL… | seller"))
    s.add_argument("action", choices=["search", "product", "reviews", "category", "compare", "seller"])
    s.add_argument("target", nargs="+", help="query, URL(s) or merchant id")
    s.add_argument("-p", "--platform", choices=["amazon", "flipkart", "walmart", "alibaba", "myntra", "generic"])
    s.add_argument("--country")
    s.add_argument("--domain", help="e.g. .co.uk")
    s.add_argument("--zip")
    s.add_argument("--currency")
    s.add_argument("--sort", choices=["best_sellers", "most_recent", "price_low_to_high", "price_high_to_low", "featured", "average_review"])
    s.add_argument("--pages", type=int)
    s.add_argument("--limit", type=int)
    s.add_argument("--screenshot", action="store_true")
    s = disp(add("maps", cmd_maps, 'maps: search "QUERY" | nearby LAT,LNG | place URL | reviews URL | directions "A to B"'))
    s.add_argument("action", choices=["search", "nearby", "place", "reviews", "directions"])
    s.add_argument("target", nargs="+")
    s.add_argument("--location", help='"City, Country" for search')
    s.add_argument("--results", choices=["top3", "top10", "11-20"], default="top10")
    s.add_argument("--radius", type=float, help="km (nearby)")
    s.add_argument("--query", help="place type (nearby)")
    s.add_argument("--limit", type=int, default=20, help="max reviews")
    s.add_argument("--mode", choices=["driving", "walking", "bicycling", "transit"], default="driving")
    s.add_argument("--depth", type=int, choices=[0, 1], default=0, help="1 = reviews + website of each place")
    s = add("batch", cmd_batch, "run many scrapes or searches from a file (one per line)")
    s.add_argument("kind", choices=["scrape", "search"])
    s.add_argument("file")
    s.add_argument("--out-dir", default="results")
    s.add_argument("--concurrency", type=int, default=5)
    s.add_argument("--engine", default="google")
    s.add_argument("--results", type=int, default=10)
    s.add_argument("-f", "--format", default="markdown")
    s = disp(add("config", cmd_config, "config: show | set-key KEY | set-url URL | set key=value"))
    s.add_argument("action", choices=["show", "set-key", "set-url", "set"], nargs="?", default="show")
    s.add_argument("value", nargs="?")
    s = disp(add("status", cmd_auth_status, "who you are logged in as, plan and credits"))
    s = disp(add("health", cmd_health, "API health"))
    s = disp(add("history", cmd_history, "recent requests"))
    s.add_argument("--limit", type=int, default=20)
    s = add("completion", cmd_completion, "print a shell completion script: completion bash|zsh|fish")
    s.add_argument("shell", choices=["bash", "zsh", "fish"])
    s.add_argument("--prog", default="scrapecore")
    add("man", cmd_man, "print the man page (roff): scrapecore man | man -l -")
