"""PubMed search via NCBI Entrez E-utilities.

No API key required for low-volume usage (rate limit: 3 req/sec without
a key; we make at most 2 requests per call).

Two-step protocol:
  1. esearch.fcgi → list of PMIDs matching the query.
  2. esummary.fcgi → metadata for those PMIDs (title, authors, source, pubdate).

For abstract text we'd add a third efetch.fcgi call returning XML; that's
heavier and we don't need it for the current research-agent use case
(titles + journals + dates are enough for the writer to cite).
"""
from __future__ import annotations

import urllib.parse

import requests

from core.logger import logger

_HEADERS = {"User-Agent": "FRIDAY-research-agent/1.0"}
_TIMEOUT_S = 12
_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def search(query: str, *, max_results: int = 5) -> list[dict]:
    """Return list of {pmid, title, journal, pubdate, authors, url}."""
    if not query or not query.strip():
        return []
    max_results = max(1, min(max_results, 20))

    # Step 1: esearch — get PMIDs.
    esearch_params = {
        "db": "pubmed",
        "term": query.strip(),
        "retmode": "json",
        "retmax": max_results,
        "sort": "relevance",
    }
    try:
        resp = requests.get(
            f"{_BASE}/esearch.fcgi?" + urllib.parse.urlencode(esearch_params),
            headers=_HEADERS, timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        idlist = (resp.json() or {}).get("esearchresult", {}).get("idlist", []) or []
    except Exception as exc:
        logger.warning("[pubmed] esearch failed for %r: %s", query, exc)
        return []
    if not idlist:
        return []

    # Step 2: esummary — get metadata for those PMIDs.
    esummary_params = {
        "db": "pubmed",
        "id": ",".join(idlist),
        "retmode": "json",
    }
    try:
        resp = requests.get(
            f"{_BASE}/esummary.fcgi?" + urllib.parse.urlencode(esummary_params),
            headers=_HEADERS, timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        result = (resp.json() or {}).get("result", {}) or {}
    except Exception as exc:
        logger.warning("[pubmed] esummary failed: %s", exc)
        return []

    out: list[dict] = []
    for pmid in idlist:
        item = result.get(pmid) or {}
        if not item:
            continue
        authors_field = item.get("authors") or []
        authors = [
            a.get("name", "") for a in authors_field
            if isinstance(a, dict) and a.get("name")
        ]
        out.append({
            "pmid": pmid,
            "title": (item.get("title") or "").strip(),
            "journal": item.get("source") or item.get("fulljournalname") or "",
            "pubdate": item.get("pubdate") or "",
            "authors": authors,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return out


# ---------------------------------------------------------------------------
# Capability handler
# ---------------------------------------------------------------------------


def handle_pubmed_search(raw_text: str, args: dict) -> str:
    query = (args.get("query") or args.get("topic") or raw_text or "").strip()
    if not query:
        return "What should I search PubMed for?"
    try:
        max_results = int(args.get("max_results", 5) or 5)
    except (TypeError, ValueError):
        max_results = 5
    papers = search(query, max_results=max_results)
    if not papers:
        return f"PubMed returned no results for '{query}'."
    lines = [f"**PubMed results for '{query}'** ({len(papers)} papers):\n"]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors += " et al."
        lines.append(f"{i}. **{p['title']}**")
        if authors:
            lines.append(f"   {authors}")
        meta_bits = [b for b in (p["journal"], p["pubdate"]) if b]
        if meta_bits:
            lines.append(f"   {' · '.join(meta_bits)}")
        lines.append(f"   {p['url']}")
        lines.append("")
    return "\n".join(lines).rstrip()
