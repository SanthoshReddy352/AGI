"""Hacker News via the official Firebase API.

No API key required. Endpoints:
  https://hacker-news.firebaseio.com/v0/topstories.json   → list[int] of IDs
  https://hacker-news.firebaseio.com/v0/newstories.json   → list[int] of IDs
  https://hacker-news.firebaseio.com/v0/item/<id>.json    → {title, url, by, score, descendants, time, …}
  https://hn.algolia.com/api/v1/search?query=<q>          → search

We use Algolia's HN API for keyword search (the Firebase API has no
search endpoint) and the Firebase API for top stories / individual item
fetches.
"""
from __future__ import annotations

import urllib.parse

import requests

from core.logger import logger

_HEADERS = {"User-Agent": "FRIDAY-research-agent/1.0"}
_TIMEOUT_S = 10


def top_stories(limit: int = 10) -> list[dict]:
    """Return top *limit* stories' minimal fields ({title, url, score, hn_url})."""
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            headers=_HEADERS, timeout=_TIMEOUT_S,
        ).json() or []
    except Exception as exc:
        logger.warning("[hackernews] topstories failed: %s", exc)
        return []
    out: list[dict] = []
    for story_id in ids[:max(1, min(limit, 30))]:
        item = fetch_item(int(story_id))
        if item is None:
            continue
        if item.get("type") != "story":
            continue
        out.append(_compact_item(item))
        if len(out) >= limit:
            break
    return out


def fetch_item(item_id: int) -> dict | None:
    try:
        resp = requests.get(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            headers=_HEADERS, timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[hackernews] item %s failed: %s", item_id, exc)
        return None


def search(query: str, limit: int = 10) -> list[dict]:
    """Keyword search via Algolia HN API."""
    if not query or not query.strip():
        return []
    url = (
        "https://hn.algolia.com/api/v1/search"
        f"?query={urllib.parse.quote(query.strip())}&hitsPerPage={max(1, min(limit, 30))}"
        "&tags=story"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        hits = (resp.json() or {}).get("hits", []) or []
    except Exception as exc:
        logger.warning("[hackernews] search failed for %r: %s", query, exc)
        return []
    out = []
    for h in hits:
        out.append({
            "title": h.get("title") or h.get("story_title") or "",
            "url": h.get("url") or "",
            "score": int(h.get("points") or 0),
            "comments": int(h.get("num_comments") or 0),
            "by": h.get("author") or "",
            "hn_url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        })
    return out


def _compact_item(item: dict) -> dict:
    item_id = item.get("id")
    return {
        "title": item.get("title") or "",
        "url": item.get("url") or "",
        "score": int(item.get("score") or 0),
        "comments": int(item.get("descendants") or 0),
        "by": item.get("by") or "",
        "hn_url": f"https://news.ycombinator.com/item?id={item_id}" if item_id else "",
    }


# ---------------------------------------------------------------------------
# Capability handlers
# ---------------------------------------------------------------------------


def handle_hackernews_top(raw_text: str, args: dict) -> str:
    try:
        limit = int(args.get("limit", 10) or 10)
    except (TypeError, ValueError):
        limit = 10
    stories = top_stories(limit=max(1, min(limit, 20)))
    if not stories:
        return "Hacker News is unreachable right now."
    lines = [f"**Top {len(stories)} on Hacker News:**\n"]
    for i, s in enumerate(stories, 1):
        title = s["title"]
        link = s["url"] or s["hn_url"]
        lines.append(f"{i}. [{s['score']}] {title}")
        if s["url"]:
            lines.append(f"   {s['url']}")
        lines.append(f"   {s['comments']} comments — {s['hn_url']}")
    return "\n".join(lines)


def handle_hackernews_search(raw_text: str, args: dict) -> str:
    query = (args.get("query") or args.get("topic") or raw_text or "").strip()
    if not query:
        return "What should I search Hacker News for?"
    try:
        limit = int(args.get("limit", 8) or 8)
    except (TypeError, ValueError):
        limit = 8
    hits = search(query, limit=max(1, min(limit, 20)))
    if not hits:
        return f"Hacker News returned no stories for '{query}'."
    lines = [f"**Hacker News search '{query}'** ({len(hits)} stories):\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. [{h['score']}] {h['title']}")
        if h["url"]:
            lines.append(f"   {h['url']}")
        lines.append(f"   {h['comments']} comments — {h['hn_url']}")
    return "\n".join(lines)
