"""Local PDF text search via lazy-imported `pypdf`.

Complements `search_indexed_files` (which matches filenames) by
searching the *contents* of PDFs in the user's workspace. Used by the
research agent's deep mode to pull citations out of papers the user has
on disk.

Lazy-imports `pypdf` so a missing dep doesn't break boot — returns a
clear install hint instead.
"""
from __future__ import annotations

import glob
import os
import re

from core.logger import logger


def _import_pypdf():
    try:
        import pypdf  # noqa: PLC0415
        return pypdf
    except ImportError:
        return None


def _candidate_roots() -> list[str]:
    """Folders to scan when no explicit folder is provided."""
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents", "FRIDAY"),
    ]
    return [r for r in roots if os.path.isdir(r)]


def list_pdfs(root: str, max_files: int = 50) -> list[str]:
    """Return absolute paths to PDFs under *root* (non-recursive limit)."""
    if not os.path.isdir(root):
        return []
    paths = glob.glob(os.path.join(root, "**", "*.pdf"), recursive=True)
    return paths[:max_files]


def extract_text(pdf_path: str, *, max_pages: int | None = None) -> str:
    """Return the extracted text of *pdf_path*. Empty on failure."""
    pypdf = _import_pypdf()
    if pypdf is None:
        return ""
    if not os.path.isfile(pdf_path):
        return ""
    try:
        reader = pypdf.PdfReader(pdf_path)
    except Exception as exc:
        logger.warning("[pdf] %s open failed: %s", pdf_path, exc)
        return ""
    chunks: list[str] = []
    pages = reader.pages
    if max_pages is not None:
        pages = pages[:max_pages]
    for i, page in enumerate(pages):
        try:
            chunks.append(page.extract_text() or "")
        except Exception as exc:
            logger.debug("[pdf] %s page %d failed: %s", pdf_path, i, exc)
            continue
    return "\n".join(chunks).strip()


def search(query: str, *, folder: str | None = None, max_results: int = 5) -> list[dict]:
    """Search PDF contents for *query*.

    Returns up to *max_results* hits: {path, filename, snippet, score}.
    Score is the number of distinct query-token hits in the document
    (case-insensitive); snippet is the first matching paragraph trimmed
    to ~280 chars.
    """
    if not query or not query.strip():
        return []
    pypdf = _import_pypdf()
    if pypdf is None:
        return []

    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) >= 3]
    if not tokens:
        return []

    roots = [folder] if folder and os.path.isdir(folder) else _candidate_roots()
    if not roots:
        return []

    candidates: list[str] = []
    for r in roots:
        candidates.extend(list_pdfs(r))
    if not candidates:
        return []

    hits: list[dict] = []
    for path in candidates:
        text = extract_text(path, max_pages=30)
        if not text:
            continue
        low = text.lower()
        score = sum(1 for t in tokens if t in low)
        if score == 0:
            continue
        snippet = _first_match_snippet(text, tokens)
        hits.append({
            "path": path,
            "filename": os.path.basename(path),
            "snippet": snippet,
            "score": score,
        })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:max_results]


def _first_match_snippet(text: str, tokens: list[str], width: int = 280) -> str:
    low = text.lower()
    idx = -1
    for t in tokens:
        i = low.find(t)
        if i != -1 and (idx == -1 or i < idx):
            idx = i
    if idx == -1:
        return text[:width].strip()
    start = max(0, idx - width // 2)
    end = min(len(text), start + width)
    snippet = text[start:end].strip()
    snippet = " ".join(snippet.split())  # collapse whitespace
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


# ---------------------------------------------------------------------------
# Capability handler
# ---------------------------------------------------------------------------


def handle_pdf_text_search(raw_text: str, args: dict) -> str:
    if _import_pypdf() is None:
        return (
            "The `pypdf` package isn't installed. "
            "Run `pip install pypdf` in the FRIDAY venv to enable PDF content search."
        )
    query = (args.get("query") or args.get("topic") or raw_text or "").strip()
    if not query:
        return "What text should I search for inside your PDFs?"
    folder = (args.get("folder") or "").strip() or None
    if folder:
        folder = os.path.expanduser(folder)
    try:
        max_results = int(args.get("max_results", 5) or 5)
    except (TypeError, ValueError):
        max_results = 5
    hits = search(query, folder=folder, max_results=max_results)
    if not hits:
        return f"No PDFs containing '{query}' found in {folder or 'your usual folders'}."
    lines = [f"**PDFs matching '{query}'** ({len(hits)} hits):\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. **{h['filename']}**  (score: {h['score']})")
        lines.append(f"   {h['path']}")
        if h["snippet"]:
            lines.append(f"   {h['snippet']}")
        lines.append("")
    return "\n".join(lines).rstrip()
