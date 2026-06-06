"""SearchFlox API client — free, no-auth web search backend.

SearchFlox (https://searchfloxai.vercel.app/docs) answers a natural-language
query with a synthesised ``text`` answer plus a list of ``sources``
(title + url). We use it as the PRIMARY backend for the lightweight research
tiers (``/web`` links, ``/quick`` instant answer) because it returns both an
answer and citations in a single round-trip with no API key.

It's an unauthenticated demo on Vercel with documented rate-limiting (HTTP
429) and no SLA, so every call here is defensive: short timeout, single
retry on 429, and a clean ``None`` return on any failure so callers can fall
back to the existing DuckDuckGo / SearxNG / Wikipedia chain. This keeps
FRIDAY working even when SearchFlox is throttled or down.

Cross-platform: pure ``urllib`` + ``json`` from the stdlib, no extra deps.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from core.logger import logger

_BASE_URL = "https://searchfloxai.vercel.app"
_SEARCH_PATH = "/api/search"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass
class SearchFloxResult:
    """Normalised SearchFlox response. ``sources`` items are {title, url}."""

    query: str
    text: str = ""
    sources: list = field(default_factory=list)


def search(query: str, *, timeout: int = 20, retries: int = 1) -> "SearchFloxResult | None":
    """Run a SearchFlox query. Returns ``None`` on any failure so the caller
    can fall back to another backend.

    Retries once on HTTP 429 with a short backoff (the docs recommend
    backoff-with-jitter; one retry is enough for an interactive turn — we'd
    rather fall back fast than make the user wait).
    """
    query = (query or "").strip()
    if not query:
        return None

    payload = json.dumps({"query": query}).encode("utf-8")
    url = _BASE_URL + _SEARCH_PATH

    attempt = 0
    while True:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(512 * 1024)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            return _normalise(query, data)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue
            logger.warning("[searchflox] HTTP %s for %r", exc.code, query[:80])
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("[searchflox] request failed for %r: %s", query[:80], exc)
            return None


def _normalise(query: str, data) -> "SearchFloxResult | None":
    if not isinstance(data, dict):
        return None
    text = (data.get("text") or data.get("answer") or "").strip()
    sources = []
    for item in data.get("sources") or []:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or item.get("link") or "").strip()
        if not url:
            continue
        sources.append({"title": (item.get("title") or "").strip(), "url": url})
    if not text and not sources:
        return None
    return SearchFloxResult(query=query, text=text, sources=sources)
