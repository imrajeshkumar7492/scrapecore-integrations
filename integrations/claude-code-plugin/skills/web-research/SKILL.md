---
name: web-research
description: Read, map or crawl public web pages with the ScrapeCore MCP tools. Use when the user asks to read a URL, summarise a website, find a page on a site, collect several pages (docs, blog), extract values from a page or screenshot it.
---

# Web research with ScrapeCore

Pick the cheapest tool that answers the question. Every successful fetch costs credits.

1. **One known URL**: `scrape_url` (Markdown). If the result says `[cut: ...]` and you need more, call it again with the `offset` it gives.
2. **Find the right page on a site**: `map_site` with `search` (e.g. `search="pricing"`), then `scrape_url` on the best match.
3. **Several pages** (a docs section): `crawl_site` with a small `limit` (10 to 30) and `include_paths` (e.g. `["^/docs"]`). If it is still running, poll `get_job_status`.
4. **Specific values** (prices, titles): `extract_structured` with CSS selectors.
5. **Visual check**: `screenshot`.

Rules:
- If a page fails to load, retry once with `js_render: true`. Only then try `use_proxy: true`.
- On `RATE_LIMITED`, wait the seconds it gives. On `INSUFFICIENT_CREDITS` or `DAILY_LIMIT`, stop and tell the user.
- Run `check_usage` before a big crawl.
- Respect robots.txt and site terms. Do not collect personal data at scale.
- Cite the URLs you used.
