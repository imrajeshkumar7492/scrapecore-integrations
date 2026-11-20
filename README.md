# ScrapeCore integrations

Official, open-source integrations for [ScrapeCore](https://scrapecore.com), the web scraping API: read web
pages as Markdown, map and crawl sites, extract data with CSS selectors, take screenshots.

| | Install | Source |
|---|---|---|
| **Python SDK** | `pip install scrapecore-sdk` | [sdks/python](sdks/python) |
| **Node.js / TypeScript SDK** | `npm install @scrapecore/sdk` | [sdks/node](sdks/node) |
| **MCP server** (Claude, ChatGPT, Cursor, VS Code…) | `https://mcp.scrapecore.com/mcp` | [docs](https://scrapecore.com/docs/mcp) |
| **Claude Code plugin** (MCP server + web-research skill) | `/plugin install scrapecore --marketplace imrajeshkumar7492/scrapecore-integrations` | [integrations/claude-code-plugin](integrations/claude-code-plugin) |
| **MCP Registry entry** | `com.scrapecore/scrapecore` | [integrations/mcp-registry/server.json](integrations/mcp-registry/server.json) |

## Quick start

```python
from scrapecore import ScrapeCore
sc = ScrapeCore()  # SCRAPECORE_API_KEY
print(sc.scrape("https://example.com", format="markdown")["markdown"])
```

```ts
import { ScrapeCore } from "@scrapecore/sdk";
const sc = new ScrapeCore(); // SCRAPECORE_API_KEY
console.log((await sc.scrape("https://example.com", { format: "markdown" })).markdown);
```

Get an API key at [scrapecore.com](https://scrapecore.com/dashboard/api-keys). The free plan includes credits. Failed requests are never charged.

## Responsible use

Use ScrapeCore only for content you are allowed to access. Maps and crawls respect `robots.txt` by default.
See the [acceptable use policy](https://scrapecore.com/acceptable-use).

## About this repository

This repository is published automatically from ScrapeCore's main codebase; changes made directly here are
overwritten on the next sync. Please open issues here. Security reports go to security@scrapecore.com.
