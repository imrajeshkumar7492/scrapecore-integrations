"""0.3: data APIs (search, e-commerce, YouTube, social, maps) in both clients and the CLI."""
import json

import httpx
import pytest

from scrapecore import AsyncScrapeCore, ScrapeCore, _cli, _cli_data
from test_v02 import KEY, cli, mk  # noqa: F401  (fixture)

SERP = {"success": True, "engine": "bing", "credits_used": 10,
        "organic_results": [{"rank": 1, "title": "R1", "url": "https://r1.example"}, {"rank": 2, "title": "R2", "url": "https://r2.example"}]}


def test_client_paths_and_bodies():
    seen = []

    def h(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json={"ok": True})
    sc = mk(h)
    sc.search("laptops", engine="bing", search_type="news", num_results=5, country=None)
    sc.ecommerce("scrape_product", platform="amazon", url="https://www.amazon.com/dp/B0")
    sc.ecommerce("search", query="mug")
    sc.youtube("scrape_video", url="https://youtu.be/x", include_comments=False)
    sc.social("reddit", "r/python", action="scrape_subreddit", limit=5)
    sc.maps("directions", origin="A", destination="B")
    assert seen[0] == ("POST", "/api/v1/search/bing", {"query": "laptops", "search_type": "news", "num_results": 5})
    assert seen[1][1] == "/api/v1/ecommerce/amazon" and seen[1][2]["action"] == "scrape_product"
    assert seen[2][1] == "/api/v1/ecommerce" and seen[3][2] == {"action": "scrape_video", "url": "https://youtu.be/x", "include_comments": False}
    assert seen[4] == ("POST", "/api/v1/social/reddit", {"target": "r/python", "action": "scrape_subreddit", "limit": 5})
    assert seen[5][1] == "/api/v1/maps" and seen[5][2]["origin"] == "A"


async def test_async_parity():
    async def h(req):
        return httpx.Response(200, json={"path": req.url.path})
    sc = mk(h, AsyncScrapeCore)
    assert (await sc.search("x", engine="yandex"))["path"] == "/api/v1/search/yandex"
    assert (await sc.maps("search", query="cafe"))["path"] == "/api/v1/maps"


def test_cli_search_json_yaml_table_and_errors(cli, monkeypatch, capsys):  # noqa: F811
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    routes[("POST", "/search/bing")] = lambda req: httpx.Response(200, json={**SERP, "_sent": json.loads(req.content)})
    assert _cli.main(["search", "best", "laptops", "-e", "bing", "-n", "2", "--country", "IN", "--as", "json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["_sent"] == {"query": "best laptops", "search_type": "web", "num_results": 2, "country": "IN"}
    assert _cli.main(["search", "x", "-e", "bing", "--as", "yaml"]) == 0
    y = capsys.readouterr().out
    assert "organic_results:" in y and "- rank: 1" in y and "url: https://r1.example" in y.replace('"', "")
    assert _cli.main(["search", "x", "-e", "bing", "--as", "text"]) == 0
    assert "1. R1\n   https://r1.example" in capsys.readouterr().out
    routes[("POST", "/search/google")] = httpx.Response(403, json={"error": {"code": "FEATURE_NOT_IN_PLAN", "message": "needs Growth", "status": 403}})
    with pytest.raises(SystemExit) as e:
        _cli.main(["search", "x", "-t", "shopping"])
    assert e.value.code == 1 and "needs Growth" in capsys.readouterr().err


def test_cli_verticals_and_batch(cli, monkeypatch, capsys, tmp_path):  # noqa: F811
    calls, routes = cli
    monkeypatch.setenv("SCRAPECORE_API_KEY", KEY)
    sent = []

    def echo(req):
        sent.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"success": True, "credits_used": 5, "results": []})
    for path in ("/youtube", "/social/github", "/ecommerce/amazon", "/maps", "/scrape"):
        routes[("POST", path)] = echo
    assert _cli.main(["youtube", "search", "ml", "tutorial", "--uploaded", "week", "--as", "json"]) == 0
    assert _cli.main(["social", "github", "facebook/react", "--as", "json"]) == 0
    assert _cli.main(["ecommerce", "product", "https://www.amazon.com/dp/B0", "-p", "amazon", "--zip", "10001", "--as", "json"]) == 0
    assert _cli.main(["maps", "directions", "Mumbai to Pune", "--mode", "walking", "--as", "json"]) == 0
    assert _cli.main(["maps", "search", "cafes", "--location", "Delhi, India", "--as", "json"]) == 0
    capsys.readouterr()
    assert sent[0] == ("/api/v1/youtube", {"action": "search", "query": "ml tutorial", "num_results": 20, "filters": {"upload_date": "week"}})
    assert sent[1][1]["target"] == "facebook/react"
    assert sent[2][1] == {"action": "scrape_product", "url": "https://www.amazon.com/dp/B0", "zip_code": "10001"}
    assert sent[3][1] == {"action": "directions", "origin": "Mumbai", "destination": "Pune", "mode": "walking"}
    assert sent[4][1]["location"] == {"city": "Delhi", "country": "India"} and sent[4][1]["result_range"] == "top10"
    f = tmp_path / "urls.txt"
    f.write_text("https://a.example\n# comment\nhttps://b.example\n")
    routes[("POST", "/scrape")] = lambda req: httpx.Response(200, json={"success": True, "credits_used": 10, "markdown": "x"})
    out = tmp_path / "out"
    assert _cli.main(["batch", "scrape", str(f), "--out-dir", str(out), "--concurrency", "2"]) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["ok"] == 2 and summary["credits"] == 20 and len(list(out.glob("*.json"))) == 2


def test_config_completion_man_and_yaml(cli, monkeypatch, capsys):  # noqa: F811
    assert _cli.main(["config", "set-key", KEY]) == 0
    assert _cli.main(["config", "show", "--as", "json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["api_key"].startswith("sk_test_") and "…" in shown["api_key"] and KEY not in json.dumps(shown)
    assert _cli.main(["completion", "bash"]) == 0
    assert "search" in capsys.readouterr().out
    assert _cli.main(["man"]) == 0
    assert ".TH SCRAPECORE 1" in capsys.readouterr().out
    assert _cli_data.to_yaml({"a": [1, {"b": "x: y"}], "c": None, "d": "yes"}) == 'a:\n  - 1\n  - b: "x: y"\nc: null\nd: "yes"'


def test_v21_methods_paths():
    seen = []

    def h(req):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json={"recipes": [], "pipelines": [], "runs": []})
    sc = mk(h)
    sc.web_search("rrf", engines=["bing"], num_results=3)
    sc.index_search("espresso")
    sc.agent_run([{"action": "goto", "url": "https://a.example"}], secrets={"pw": "x"})
    sc.create_pipeline("p", "search", {"query": "x"}, interval_minutes=60)
    sc.run_pipeline("abc")
    assert seen[0] == ("POST", "/api/v1/web-search", {"query": "rrf", "engines": ["bing"], "num_results": 3, "content": "markdown"})
    assert seen[1][1] == "/api/v1/index/search" and seen[2][2]["secrets"] == {"pw": "x"}
    assert seen[3][2]["kind"] == "search" and seen[4][:2] == ("POST", "/api/v1/pipelines/abc/run")
