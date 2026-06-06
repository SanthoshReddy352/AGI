"""Clean-text article extraction via `trafilatura`.

Replaces the in-repo `_html_to_text` + BeautifulSoup hack that kept
nav/footer/cookie-banner garbage in the extracted text. trafilatura is
the Python tool the HuggingFace data team uses for the same job — it
detects boilerplate and emits only the main article body.

Already installed in this venv (see Step 5a's `pip check`).
"""
from __future__ import annotations

import requests

from core.logger import logger

_HEADERS = {
    "User-Agent": "FRIDAY-research-agent/1.0 (extracting article text)",
    "Accept": "text/html,application/xhtml+xml",
}
_TIMEOUT_S = 12


def _import_trafilatura():
    try:
        import trafilatura  # noqa: PLC0415
        return trafilatura
    except ImportError as exc:
        logger.warning("[newspaper] trafilatura unavailable: %s", exc)
        return None


def extract(url: str) -> dict | None:
    """Return {title, text, url, length} or None on failure.

    `text` is the cleaned article body — boilerplate (nav, ads, footer,
    comments) is stripped. Empty string when the page had no main body
    or extraction failed.
    """
    if not url:
        return None
    trafilatura = _import_trafilatura()
    if trafilatura is None:
        return None
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("[newspaper] fetch failed for %s: %s", url, exc)
        return None

    try:
        # include_comments=False drops HN/Reddit-style comment blobs.
        # favor_recall=True grabs more text — research wants context.
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            url=url,
        ) or ""
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = ""
        if meta is not None:
            title = getattr(meta, "title", None) or ""
    except Exception as exc:
        logger.warning("[newspaper] trafilatura extract failed for %s: %s", url, exc)
        text = ""
        title = ""

    text = text.strip()
    return {
        "url": url,
        "title": title.strip() if title else "",
        "text": text,
        "length": len(text),
    }


def extract_many(urls: list[str], *, max_workers: int = 5) -> list[dict]:
    """Parallel fetch of multiple URLs (uses a thread pool).

    Returns extractions in the same order as the input URLs; failed
    fetches become None entries.
    """
    if not urls:
        return []
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    results: list[dict | None] = [None] * len(urls)
    workers = max(1, min(max_workers, len(urls)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="newspaper-extract") as ex:
        futures = {ex.submit(extract, u): i for i, u in enumerate(urls)}
        for fut in futures:
            i = futures[fut]
            try:
                results[i] = fut.result(timeout=_TIMEOUT_S + 5)
            except Exception as exc:
                logger.warning("[newspaper] worker %d failed: %s", i, exc)
                results[i] = None
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Capability handler
# ---------------------------------------------------------------------------


def handle_newspaper_extract(raw_text: str, args: dict) -> str:
    """Capability: fetch a URL and return the clean article text only."""
    url = (args.get("url") or "").strip()
    if not url:
        # Try to pull a URL out of the raw text.
        import re as _re  # noqa: PLC0415
        m = _re.search(r"https?://\S+", raw_text or "")
        if m:
            url = m.group(0).rstrip(".,;:!?)")
    if not url:
        return "Please provide a URL to extract."
    extraction = extract(url)
    if extraction is None or not extraction.get("text"):
        return f"Couldn't extract readable text from {url}."
    title = extraction.get("title") or url
    body = extraction["text"]
    if len(body) > 6000:
        body = body[:6000] + "…"
    return f"**{title}** ({url})\n\n{body}"
