"""Wikipedia search + summary via the public REST API.

No API key required. Two endpoints we use:

  - https://en.wikipedia.org/api/rest_v1/page/summary/<title>
      Returns a structured JSON {title, extract, description, content_urls, …}.
  - https://en.wikipedia.org/w/api.php?action=opensearch&search=<q>
      Free-text search → list of candidate titles. We pick the top hit.

Network failures degrade to a clear error string — callers should NEVER
crash because Wikipedia was unreachable.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Optional

import requests

from core.logger import logger

_HEADERS = {
    "User-Agent": "FRIDAY-research-agent/1.0 (https://github.com/local)",
    "Accept": "application/json",
}
_TIMEOUT_S = 10


def search_titles(query: str, limit: int = 5) -> list[str]:
    """Return up to *limit* Wikipedia article titles matching *query*."""
    if not query or not query.strip():
        return []
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=opensearch&search={urllib.parse.quote(query.strip())}"
        f"&limit={limit}&namespace=0&format=json"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        # opensearch returns [query, titles, descriptions, urls]
        data = resp.json()
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [str(t) for t in data[1][:limit]]
    except Exception as exc:
        logger.warning("[wikipedia] search failed for %r: %s", query, exc)
    return []


def fetch_summary(title: str) -> Optional[dict]:
    """Return the article's REST summary dict, or None on failure.

    Keys returned by the REST API include: title, displaytitle, extract,
    description, content_urls.desktop.page, thumbnail (optional).
    """
    if not title:
        return None
    safe = urllib.parse.quote(title.strip().replace(" ", "_"), safe="")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[wikipedia] summary fetch failed for %r: %s", title, exc)
        return None


def summary_for_query(query: str) -> Optional[dict]:
    """Convenience: open-search → top hit → REST summary. None if nothing."""
    titles = search_titles(query, limit=1)
    if not titles:
        return None
    return fetch_summary(titles[0])


# ---------------------------------------------------------------------------
# Capability handlers
# ---------------------------------------------------------------------------


def handle_wikipedia_summary(raw_text: str, args: dict) -> str:
    """Top-1 Wikipedia summary for the topic."""
    query = (args.get("query") or args.get("topic") or raw_text or "").strip()
    if not query:
        return "What topic would you like a Wikipedia summary for?"
    summary = summary_for_query(query)
    if summary is None:
        return f"Wikipedia has no article matching '{query}'."
    title = summary.get("title") or query
    extract = (summary.get("extract") or "").strip()
    if not extract:
        return f"Wikipedia found '{title}' but the article has no summary text."
    url = (
        (summary.get("content_urls") or {}).get("desktop", {}).get("page")
        or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    )
    return f"**{title}** ({url})\n\n{extract}"


def handle_wikipedia_search(raw_text: str, args: dict) -> str:
    """List the top N Wikipedia article titles for the query."""
    query = (args.get("query") or args.get("topic") or raw_text or "").strip()
    if not query:
        return "What should I search Wikipedia for?"
    try:
        limit = int(args.get("limit", 5) or 5)
    except (TypeError, ValueError):
        limit = 5
    titles = search_titles(query, limit=max(1, min(limit, 10)))
    if not titles:
        return f"Wikipedia returned no titles for '{query}'."
    lines = [f"Wikipedia articles matching '{query}':"]
    for i, t in enumerate(titles, 1):
        lines.append(f"  {i}. {t}")
    return "\n".join(lines)
