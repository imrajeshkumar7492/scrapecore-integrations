"""0.2: AI extraction, crawl exports, monitors, and the `scrapecore` CLI."""
import base64
import json

import httpx
import pytest

from scrapecore import AsyncScrapeCore, ScrapeCore, _cli

KEY = "sk_test_" + "x" * 32


def mk(handler, cls=ScrapeCore):
    http = (httpx.AsyncClient if cls is AsyncScrapeCore else httpx.Client)(transport=httpx.MockTransport(handler))
    return cls(KEY, base_url="https://api.test", http_client=http)


def test_ai_extract_export_monitors_paths():
    seen = []

    def h(req):
        seen.append((req.method, req.url.path, req.url.query.decode(), json.loads(req.content) if req.content else None))
        if req.url.path.endswith("/export"):
            return httpx.Response(200, text="# Site\n\n> summary\n", headers={"content-type": "text/plain"})
        if req.url.path.endswith("/changes"):
            return httpx.Response(200, json={"changes": [{"diff": "-a\n+b"}]})
        return httpx.Response(200, json={"ok": True})
    sc = mk(h)
    sc.ai_extract("https://x.example", prompt="price", schema={"type": "object"})
    assert sc.crawl_export("j1", "llms") == "# Site\n\n> summary\n"
    sc.create_monitor("https://x.example", interval_minutes=60, selector="#p")
    sc.update_monitor("m1", status="paused")
    assert sc.monitor_changes("m1", limit=2) == [{"diff": "-a\n+b"}]
    assert seen[0][:2] == ("POST", "/api/v1/extract/ai") and seen[0][3] == {"url": "https://x.example", "prompt": "price",
                                                                             "schema": {"type": "object"}}
    assert seen[1][:3] == ("GET", "/api/v1/crawl/j1/export", "format=llms")
    assert seen[2][3] == {"url": "https://x.example", "interval_minutes": 60, "selector": "#p"}
    assert seen[3][:2] == ("PATCH", "/api/v1/monitors/m1") and seen[3][3] == {"status": "paused"}
    assert seen[4][2] == "limit=2"


async def test_async_parity():
    async def h(req):
        return httpx.Response(200, text="a\nb\n") if req.url.path.endswith("/export") else httpx.Response(200, json={"monitors": []})
    sc = mk(h, AsyncScrapeCore)
    assert await sc.crawl_export("j", "chunks", chunk_size=500) == "a\nb\n"
    assert await sc.monitors() == {"monitors": []}


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(_cli, "CONFIG", tmp_path / "cfg" / "config.json")
    monkeypatch.delenv("SCRAPECORE_API_KEY", raising=False)
    calls = []
    routes = {}

    def handler(req):
        calls.append((req.method, req.url.path, req.headers.get("x-api-key"), req.headers.get("user-agent")))
        for (m, suffix), resp in routes.items():
            if req.method == m and req.url.path.endswith(suffix):
                return resp(req) if callable(resp) else resp
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "no route", "status": 404}})
    real = ScrapeCore.__init__

    def init(self, api_key=None, **kw):
        kw["http_client"] = httpx.Client(transport=httpx.MockTransport(handler))
        kw["base_url"] = "https://api.test"
        real(self, api_key, **kw)
    monkeypatch.setattr(ScrapeCore, "__init__", init)
    return calls, routes


def test_login_saves_key_privately_and_is_used(cli, monkeypatch, capsys):
    calls, routes = cli
    routes[("GET", "/usage")] = httpx.Response(200, json={"credits_used": 10, "credits_limit": 1000})
    routes[("POST", "/scrape")] = httpx.Response(200, json={"markdown": "# Example"})
    monkeypatch.setattr(_cli.getpass, "getpass", lambda prompt: KEY)
    assert _cli.main(["login"]) == 0
    cfg = _cli.CONFIG
    assert json.loads(cfg.read_text())["api_key"] == KEY and (cfg.stat().st_mode & 0o777) == 0o600
    assert "990 credits left" in capsys.readouterr().err
    assert _cli.main(["scrape", "https://example.com"]) == 0
    assert capsys.readouterr().out.strip() == "# Example"
    assert calls[-1][2] == KEY and calls[-1][3].startswith("scrapecore-cli/")
    assert _cli.main(["logout"]) == 0 and "api_key" not in json.loads(cfg.read_text())


def test_no_key_is_a_clear_error(cli, capsys):
    with pytest.raises(SystemExit) as e:
        _cli.main(["scrape", "https://example.com"])
    assert e.value.code == 1 and "scrapecore login" in capsys.readouterr().err


def test_api_error_exit_code(cli, monkeypatch, capsys):
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    routes[("POST", "/scrape")] = httpx.Response(402, json={"error": {"code": "INSUFFICIENT_CREDITS",
                                                                      "message": "Out of credits", "status": 402}})
    with pytest.raises(SystemExit) as e:
        _cli.main(["scrape", "https://example.com"])
    assert e.value.code == 1 and "Out of credits" in capsys.readouterr().err


def test_crawl_waits_and_exports(cli, monkeypatch, capsys, tmp_path):
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    monkeypatch.setattr("scrapecore._client.time.sleep", lambda s: None)
    routes[("POST", "/crawl")] = httpx.Response(200, json={"job_id": "j9", "status": "queued", "max_credits": 50})
    routes[("GET", "/job/j9")] = httpx.Response(200, json={"status": "success", "result": {"pages_ok": 3, "pages_failed": 0,
                                                                                         "credits_used": 3}})
    routes[("GET", "/crawl/j9/export")] = httpx.Response(200, text="# llms\n")
    out = tmp_path / "llms.txt"
    assert _cli.main(["crawl", "https://docs.example", "--limit", "5", "--export", "llms", "-o", str(out)]) == 0
    assert out.read_text() == "# llms\n" and "3 page(s) ok" in capsys.readouterr().err


def test_screenshot_writes_png(cli, monkeypatch, tmp_path):
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    png = b"\x89PNG\r\n\x1a\nfake"
    routes[("POST", "/screenshot")] = httpx.Response(200, json={"image_base64": base64.b64encode(png).decode()})
    dest = tmp_path / "s.png"
    assert _cli.main(["screenshot", "https://example.com", "-o", str(dest)]) == 0
    assert dest.read_bytes() == png


def test_monitor_list_table_and_json(cli, monkeypatch, capsys):
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    data = {"monitors": [{"id": "m1", "status": "active", "interval_minutes": 60, "changes": 2, "last_changed_at": None,
                          "url": "https://x.example"}], "limit": 10}
    routes[("GET", "/monitors")] = httpx.Response(200, json=data)
    assert _cli.main(["monitor", "list"]) == 0
    text = capsys.readouterr().out
    assert "m1" in text and "1 / 10 monitors" in text
    assert _cli.main(["monitor", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == data


def test_extract_needs_prompt_schema_or_selectors(cli, monkeypatch):
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    with pytest.raises(SystemExit) as e:
        _cli.main(["extract", "https://x.example"])
    assert e.value.code == 2


def test_ai_job_methods_and_cli(cli, monkeypatch, capsys, tmp_path):
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    seen = {}

    def create(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"job_id": "aij_1", "status": "queued", "provider": "openai", "model": "gpt-4.1"})
    routes[("POST", "/ai/jobs")] = create
    routes[("GET", "/ai/jobs/aij_1")] = httpx.Response(200, json={"job_id": "aij_1", "status": "completed",
                                                                  "totals": {"ok": 2, "failed": 0, "urls": 2, "records": 3}})
    routes[("GET", "/ai/jobs/aij_1/export")] = httpx.Response(200, content=b"name,price\nMug,12\n")
    dest = tmp_path / "out.csv"
    assert _cli.main(["ai", "https://a.example/1", "https://a.example/2", "-p", "products", "--many", "-f", "csv",
                      "--provider", "openai", "-o", str(dest)]) == 0
    assert dest.read_bytes() == b"name,price\nMug,12\n"
    b = seen["body"]
    assert b["urls"] == ["https://a.example/1", "https://a.example/2"] and b["records"] == "list" and b["mode"] == "bulk"
    assert b["provider"] == "openai" and b["instructions"] == "products"
    assert "completed: 2/2 pages, 3 records" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        _cli.main(["ai", "-p", "x"])
    assert e.value.code == 2
