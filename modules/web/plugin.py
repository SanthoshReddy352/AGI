"""P3.10 — Web search, extract, and crawl capabilities.

Three capabilities:
  web_search  — multi-backend search (duckduckgo-search primary, DDG HTML fallback)
  web_extract — fetch a URL and return clean Markdown text
  web_crawl   — follow links from a seed URL, LLM-guided extraction

All outbound URLs are checked by core.safety.url_safety before fetching.
"""
from __future__ import annotations

import html
import html.parser
import re
import urllib.request
import urllib.parse
from typing import Optional

from core.plugin_manager import FridayPlugin
from core.logger import logger


# ── HTML → plain text ────────────────────────────────────────────────────────

class _TextExtractor(html.parser.HTMLParser):
    _SKIP = {"script", "style", "noscript", "head", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self._links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith("http"):
                self._links.append(href)

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)

    def get_links(self) -> list[str]:
        return self._links


def _html_to_text(raw_html: str) -> tuple[str, list[str]]:
    """Extract plain text and links from HTML. Returns (text, links)."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html.unescape(raw_html))
    except Exception:
        pass
    text = re.sub(r"\s{3,}", "  ", extractor.get_text())
    return text, extractor.get_links()


def _fetch_url(url: str, timeout: int = 10) -> str:
    """Fetch URL and return raw HTML/text body. Raises on error."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(512 * 1024)  # cap at 512 KB
        charset = "utf-8"
        ct = resp.headers.get("Content-Type", "")
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip()
        return raw.decode(charset, errors="replace")


_DDG_REDIRECT_RE = re.compile(
    r"^https?://(?:www\.)?duckduckgo\.com/l/?\?", re.IGNORECASE
)


def _unwrap_ddg_redirect(url: str) -> str:
    """DuckDuckGo HTML wraps every result link in a tracking redirect:
    `https://duckduckgo.com/l/?uddg=<URL-encoded real URL>&rut=…`.

    These wrappers don't open cleanly in browsers (they 400 a lot) and
    trafilatura can't follow them, so we hand back the decoded `uddg`
    parameter wherever possible. Live session 2026-05-24 17:58 lost
    every web hit in both research modes because every URL was a 400-ing
    wrapper.
    """
    if not url or not _DDG_REDIRECT_RE.match(url):
        return url
    try:
        # html.unescape first because the wrapper itself often contains
        # &amp; in the DDG HTML; otherwise parse_qs sees `&amp;rut=` and
        # mis-reads the param boundary.
        clean = html.unescape(url)
        parsed = urllib.parse.urlparse(clean)
        params = urllib.parse.parse_qs(parsed.query)
        real = params.get("uddg", [""])[0]
        if real:
            return urllib.parse.unquote(real)
    except Exception as exc:
        logger.debug("[web_search] DDG unwrap failed for %s: %s", url[:80], exc)
    return url


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo search via duckduckgo-search library (preferred) or HTTP fallback.

    Every URL is run through `_unwrap_ddg_redirect` so callers get the
    real destination, not the `duckduckgo.com/l/?uddg=…` wrapper.
    """
    try:
        from duckduckgo_search import DDGS  # noqa: PLC0415
        results = list(DDGS().text(query, max_results=max_results))
        return [{
            "title": r.get("title", ""),
            "url": _unwrap_ddg_redirect(r.get("href", "")),
            "snippet": r.get("body", ""),
        } for r in results]
    except ImportError:
        pass
    # HTTP fallback using DDG HTML (no API key required)
    try:
        q = urllib.parse.quote_plus(query)
        raw = _fetch_url(f"https://html.duckduckgo.com/html/?q={q}", timeout=8)
        # Extract result titles and links from DDG HTML
        results = []
        for m in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)', raw
        ):
            url, title = m.group(1), html.unescape(m.group(2)).strip()
            if url.startswith("//"):
                url = "https:" + url
            url = _unwrap_ddg_redirect(url)
            if url.startswith("http") and len(results) < max_results:
                results.append({"title": title, "url": url, "snippet": ""})
        return results
    except Exception as exc:
        logger.error("[web_search] DDG fallback failed: %s", exc)
        return []


def _searchflox_links(query: str, max_results: int) -> list[dict]:
    """SearchFlox sources → the same {title,url,snippet} shape as DDG.

    Returns [] on any failure so callers fall through to DDG/Wikipedia.
    """
    try:
        from modules.web import searchflox_client  # noqa: PLC0415
        # Links only need the sources list — use a tight timeout so we fail
        # over to DDG quickly instead of making the user wait the full window.
        res = searchflox_client.search(query, timeout=10)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[web_search] searchflox unavailable: %s", exc)
        return []
    if res is None or not res.sources:
        return []
    return [
        {"title": s.get("title") or s["url"], "url": s["url"], "snippet": ""}
        for s in res.sources[:max_results]
    ]


def _check_url_safety(url: str) -> tuple[bool, str]:
    try:
        from core.safety.url_safety import UrlSafety  # noqa: PLC0415
        return UrlSafety().is_safe(url)
    except Exception:
        return True, ""


# ── Plugin ────────────────────────────────────────────────────────────────────

class WebPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "Web"
        self.on_load()

    def on_load(self):
        self.app.register_capability(
            {
                "name": "web_search",
                "description": (
                    "Search the web for current information, news, or facts. "
                    "Returns titles, URLs, and snippets for the top results."
                ),
                "parameters": {"query": "string — the search query", "limit": "int — max results (default 5)"},
                "aliases": [
                    "search the web for", "look up online", "google", "search online",
                    "find online", "what's the latest on", "look this up",
                    "search for", "web search", "find on the web",
                ],
                "patterns": [
                    r"\bsearch(?:\s+the\s+web)?\s+for\b",
                    r"\blook\s+up\b.{0,20}\bonline\b",
                    r"\bwhat(?:'s|\s+is)\s+the\s+latest\s+(?:on|about)\b",
                    r"\bfind\b.{0,20}\bonline\b",
                    r"\bweb\s+search\b",
                ],
                "context_terms": ["search online", "web", "internet", "google", "look up"],
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            self._handle_search,
        )
        self.app.register_capability(
            {
                "name": "quick_answer",
                "description": (
                    "Answer a question directly in the chat using a fast web "
                    "lookup (SearchFlox). Returns a short synthesised answer "
                    "with a couple of source links. Nothing is saved to disk — "
                    "use this for 'quick answer', 'just tell me', or a one-off "
                    "factual question that needs current information."
                ),
                "parameters": {"query": "string — the question to answer"},
                "aliases": [
                    "quick answer", "quick search", "just tell me",
                    "give me a quick answer", "quickly look up",
                ],
                "context_terms": ["quick answer", "quick search", "fast answer"],
                "connectivity": "online",
                "permission_mode": "online_permission",
                "latency_class": "slow",
                "side_effect_level": "read",
            },
            self._handle_quick_answer,
        )
        self.app.register_capability(
            {
                "name": "web_extract",
                "description": "Fetch a URL and return its content as clean readable text.",
                "parameters": {"url": "string — the URL to fetch"},
                "aliases": [
                    "fetch", "read this url", "open this link", "extract from url",
                    "get content from", "read the page", "fetch this page",
                ],
                "patterns": [
                    r"\bfetch\s+https?://",
                    r"\bread\s+(?:this\s+|the\s+)?(?:url|page|link)\b",
                    r"\bextract\s+(?:from|content)\b.{0,20}https?://",
                ],
                "context_terms": ["fetch url", "read page", "extract content", "open link"],
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            self._handle_extract,
        )
        self.app.register_capability(
            {
                "name": "web_crawl",
                "description": (
                    "Follow links from a seed URL and extract relevant content. "
                    "Use for multi-page research tasks."
                ),
                "parameters": {
                    "url": "string — seed URL",
                    "instructions": "string — what to look for while crawling",
                    "depth": "int — link depth (1=seed only, 2=follow one level, default 1)",
                },
                "aliases": [
                    "crawl", "crawl this website", "explore this site", "scrape this site",
                    "research this website", "gather from this site",
                ],
                "patterns": [
                    r"\bcrawl\s+https?://",
                    r"\b(?:scrape|crawl|explore)\s+(?:this\s+)?(?:site|website|page)\b",
                ],
                "context_terms": ["crawl", "scrape site", "research website"],
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            self._handle_crawl,
        )
        logger.info("[web] WebPlugin loaded — web_search, quick_answer, web_extract, web_crawl registered.")

    # ------------------------------------------------------------------

    def _handle_search(self, raw_text: str, args: dict) -> str:
        query = args.get("query") or raw_text.strip()
        limit = min(int(args.get("limit", 5)), 10)
        if not query:
            return "What would you like me to search for?"
        logger.info("[web_search] query=%r limit=%d", query, limit)

        # Primary: SearchFlox returns ranked sources (title + url) with no
        # API key. Fall back to DDG (and then Wikipedia) when it's throttled
        # or returns nothing, so /web never goes dark.
        results = _searchflox_links(query, limit)
        if not results:
            try:
                results = _ddg_search(query, limit)
            except Exception as exc:
                logger.error("[web_search] error: %s", exc)
                results = []

        # DDG HTML scraping is brittle — they sometimes return empty
        # results (rate limit / different layout). 2026-05-24 07:29-07:30
        # session: the same "/web Attack on Titan" query that returned
        # 5 hits at 07:07 returned 0 hits at 07:29. Fall back to the
        # Wikipedia source tool — same query, no rate-limited HTML
        # scraping, almost-always-non-empty for named entities.
        if not results:
            wiki_fallback = self._try_wikipedia_fallback(query)
            if wiki_fallback:
                return wiki_fallback
            return f"No results found for: {query}"

        lines = [f"Search results for **{query}**:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**\n   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:200]}")
        return "\n".join(lines)

    def _handle_quick_answer(self, raw_text: str, args: dict) -> str:
        """Instant chat answer via SearchFlox; never writes to disk.

        Falls back to a DDG-snippet digest, then Wikipedia, so the user
        always gets *something* even when SearchFlox is rate-limited.
        """
        query = (args.get("query") or raw_text or "").strip()
        if not query:
            return "What would you like a quick answer to?"
        logger.info("[quick_answer] query=%r", query)

        try:
            from modules.web import searchflox_client  # noqa: PLC0415
            res = searchflox_client.search(query)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[quick_answer] searchflox unavailable: %s", exc)
            res = None

        if res is not None and res.text:
            answer = res.text.strip()
            cites = [s["url"] for s in res.sources[:3] if s.get("url")]
            if cites:
                answer += "\n\nSources:\n" + "\n".join(f"• {u}" for u in cites)
            return answer

        # Fallback 1: DDG snippets stitched into a short answer.
        try:
            results = _ddg_search(query, 3)
        except Exception:
            results = []
        if results:
            lines = [r["snippet"] for r in results if r.get("snippet")]
            if lines:
                body = " ".join(lines)[:600]
                cites = [r["url"] for r in results[:3] if r.get("url")]
                return body + ("\n\nSources:\n" + "\n".join(f"• {u}" for u in cites) if cites else "")

        # Fallback 2: Wikipedia.
        wiki = self._try_wikipedia_fallback(query)
        if wiki:
            return wiki
        return f"I couldn't find a quick answer for: {query}"

    def _try_wikipedia_fallback(self, query: str) -> str:
        """When DDG returns empty, try Wikipedia. Lazy-import so the web
        plugin doesn't hard-depend on `modules.sources`.
        """
        try:
            from modules.sources import wikipedia as _wiki  # noqa: PLC0415
        except Exception as exc:
            logger.debug("[web_search] wikipedia fallback unavailable: %s", exc)
            return ""
        try:
            summary = _wiki.summary_for_query(query)
        except Exception as exc:
            logger.warning("[web_search] wikipedia fallback failed: %s", exc)
            return ""
        if not summary:
            return ""
        title = summary.get("title") or query
        extract = (summary.get("extract") or "").strip()
        if not extract:
            return ""
        url = (
            (summary.get("content_urls") or {}).get("desktop", {}).get("page")
            or ""
        )
        logger.info("[web_search] DDG empty for %r — used Wikipedia fallback", query)
        prefix = (
            f"_(Web search returned nothing; pulled this from Wikipedia instead.)_\n\n"
            f"**{title}**"
        )
        if url:
            prefix += f"\n{url}\n"
        return f"{prefix}\n{extract}"

    def _handle_extract(self, raw_text: str, args: dict) -> str:
        url = args.get("url") or _extract_url(raw_text)
        if not url:
            return "Please provide a URL to fetch."
        ok, reason = _check_url_safety(url)
        if not ok:
            return f"I can't fetch that URL: {reason}"
        logger.info("[web_extract] url=%s", url)
        try:
            raw = _fetch_url(url)
            text, _ = _html_to_text(raw)
            if len(text) > 4000:
                text = text[:4000] + "…"
            return text or "The page loaded but contained no readable text."
        except Exception as exc:
            logger.error("[web_extract] error: %s", exc)
            return f"Couldn't fetch that page: {exc}"

    def _handle_crawl(self, raw_text: str, args: dict) -> str:
        url = args.get("url") or _extract_url(raw_text)
        instructions = args.get("instructions", "")
        depth = max(1, min(int(args.get("depth", 1)), 2))
        if not url:
            return "Please provide a seed URL to crawl."
        ok, reason = _check_url_safety(url)
        if not ok:
            return f"I can't crawl that URL: {reason}"
        logger.info("[web_crawl] url=%s depth=%d instructions=%r", url, depth, instructions)
        visited: set[str] = set()
        collected: list[str] = []
        self._crawl_page(url, depth, visited, collected)
        if not collected:
            return "Couldn't extract content from that site."
        combined = "\n\n---\n\n".join(collected[:3])
        if len(combined) > 5000:
            combined = combined[:5000] + "…"
        return combined

    def _crawl_page(self, url: str, depth: int, visited: set, collected: list) -> None:
        if url in visited or len(collected) >= 3:
            return
        visited.add(url)
        try:
            raw = _fetch_url(url, timeout=8)
            text, links = _html_to_text(raw)
            if text:
                collected.append(f"[{url}]\n{text[:2000]}")
            if depth > 1:
                for link in links[:5]:
                    ok, _ = _check_url_safety(link)
                    if ok and link not in visited:
                        self._crawl_page(link, depth - 1, visited, collected)
        except Exception as exc:
            logger.warning("[web_crawl] failed to fetch %s: %s", url, exc)


def _extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text)
    return m.group(0).rstrip(".,;)") if m else None
