"""arXiv search via the public export.arxiv.org Atom API.

No API key required. Endpoint:
  http://export.arxiv.org/api/query?search_query=<...>&start=0&max_results=N

Returns Atom XML — we parse with stdlib `xml.etree.ElementTree`.

The API doesn't rate-limit individual queries but recommends 1req/3s for
heavy crawls; our single-query usage is well inside that.
"""
from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET

import requests

from core.logger import logger

_HEADERS = {
    "User-Agent": "FRIDAY-research-agent/1.0",
}
_TIMEOUT_S = 15
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# Most queries use the all-fields default; users with academic-paper
# intent often want title+abstract specifically.
_DEFAULT_SEARCH_FIELDS = "all"


def search(query: str, *, max_results: int = 5) -> list[dict]:
    """Return list of {title, authors, summary, published, pdf_url, abs_url, id}.

    Empty list on failure (network error or malformed response).
    """
    if not query or not query.strip():
        return []
    params = {
        "search_query": f"{_DEFAULT_SEARCH_FIELDS}:{query.strip()}",
        "start": 0,
        "max_results": max(1, min(max_results, 20)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("[arxiv] search failed for %r: %s", query, exc)
        return []

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        logger.warning("[arxiv] parse failed: %s", exc)
        return []

    out: list[dict] = []
    for entry in root.iterfind(f"{_ATOM_NS}entry"):
        eid = (entry.findtext(f"{_ATOM_NS}id") or "").strip()
        title = (entry.findtext(f"{_ATOM_NS}title") or "").strip().replace("\n", " ")
        summary = (entry.findtext(f"{_ATOM_NS}summary") or "").strip()
        published = (entry.findtext(f"{_ATOM_NS}published") or "").strip()
        authors = [
            (a.findtext(f"{_ATOM_NS}name") or "").strip()
            for a in entry.iterfind(f"{_ATOM_NS}author")
        ]
        pdf_url = ""
        abs_url = eid
        for link in entry.iterfind(f"{_ATOM_NS}link"):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
            elif link.get("rel") == "alternate":
                abs_url = link.get("href") or abs_url
        # Compact whitespace in summary.
        summary = " ".join(summary.split())
        out.append({
            "id": eid,
            "title": title,
            "authors": [a for a in authors if a],
            "summary": summary,
            "published": published[:10],  # YYYY-MM-DD
            "pdf_url": pdf_url,
            "abs_url": abs_url,
        })
    return out


def fetch_by_id(arxiv_id: str) -> dict | None:
    """Fetch a single paper by arXiv ID (e.g. '2401.04088')."""
    if not arxiv_id:
        return None
    # The ID endpoint accepts the id_list param.
    params = {"id_list": arxiv_id.strip()}
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as exc:
        logger.warning("[arxiv] fetch_by_id %r failed: %s", arxiv_id, exc)
        return None
    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        return None
    title = (entry.findtext(f"{_ATOM_NS}title") or "").strip().replace("\n", " ")
    summary = " ".join((entry.findtext(f"{_ATOM_NS}summary") or "").strip().split())
    authors = [
        (a.findtext(f"{_ATOM_NS}name") or "").strip()
        for a in entry.iterfind(f"{_ATOM_NS}author")
    ]
    pdf_url = ""
    for link in entry.iterfind(f"{_ATOM_NS}link"):
        if link.get("type") == "application/pdf":
            pdf_url = link.get("href") or ""
    return {
        "id": arxiv_id,
        "title": title,
        "authors": [a for a in authors if a],
        "summary": summary,
        "published": (entry.findtext(f"{_ATOM_NS}published") or "")[:10],
        "pdf_url": pdf_url,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id.strip()}",
    }


# ---------------------------------------------------------------------------
# Capability handler
# ---------------------------------------------------------------------------


def handle_arxiv_search(raw_text: str, args: dict) -> str:
    query = (args.get("query") or args.get("topic") or raw_text or "").strip()
    if not query:
        return "What should I search arXiv for?"
    try:
        max_results = int(args.get("max_results", 5) or 5)
    except (TypeError, ValueError):
        max_results = 5
    papers = search(query, max_results=max_results)
    if not papers:
        return f"arXiv returned no papers for '{query}'."
    lines = [f"**arXiv results for '{query}'** ({len(papers)} papers):\n"]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors += f" et al."
        lines.append(f"{i}. **{p['title']}** ({p['published']})")
        lines.append(f"   {authors}")
        lines.append(f"   {p['abs_url']}")
        snippet = p["summary"][:280]
        if snippet:
            lines.append(f"   {snippet}…" if len(p["summary"]) > 280 else f"   {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip()
