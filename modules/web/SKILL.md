---
name: web
description: "Web search, page extraction, and site crawling. Gives FRIDAY internet access for current information."
plugin_module: modules/web
capabilities:
  - name: web_search
    description: "Search the web using DuckDuckGo. Returns titles, URLs, and snippets."
    aliases:
      - "search the web for"
      - "look up online"
      - "google"
      - "what's the latest on"
      - "find online"
      - "web search"
  - name: web_extract
    description: "Fetch a URL and return its readable text content."
    aliases:
      - "fetch this url"
      - "read this page"
      - "extract content from"
      - "open this link"
  - name: web_crawl
    description: "Follow links from a seed URL and gather content across multiple pages."
    aliases:
      - "crawl this website"
      - "scrape this site"
      - "research this website"
---

# Web Module

Gives FRIDAY internet access via DuckDuckGo search (no API key required).

## Setup

Install the optional fast backend:
```
pip install duckduckgo-search
```

Without it, FRIDAY falls back to the DDG HTML interface (slightly slower).

## Examples

```
Friday, search the web for "Claude opus 4.7 release"
Friday, look up the latest Python packaging changes online
Friday, fetch https://docs.python.org/3/library/subprocess.html
Friday, crawl https://news.ycombinator.com and find ML stories
```

## Permissions

All capabilities require `online_permission` mode. URLs are pre-screened by
`core.safety.url_safety` — private IP ranges and blocked domains are rejected.

## Config

`config/web_search.yaml` — set preferred backend and optional API keys for
Brave Search, Tavily, or SearXNG.
