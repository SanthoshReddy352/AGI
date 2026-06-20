"""Document tool — extract readable text from a document file.

The v1 ``document_intel`` module was a full Chroma-backed RAG stack. The v2 port
keeps the useful, model-facing primitive: pull a document's text into the
conversation so the agent can read/summarise/answer over it. The model does the
"intelligence"; this tool just converts a file to text.

  read_document(path) — .txt/.md/.csv/.log directly; .pdf (pypdf); .docx (python-docx)

Plain-text formats need no dependency; PDF/DOCX use optional libraries and return
a clear error if they're missing. All paths go through PathSecurity.
"""
from __future__ import annotations

from pathlib import Path

from namma_agent.core.safety import check_path
from namma_agent.core.tools import ToolRegistry, ToolResult

_MAX_CHARS = 100_000
_PLAINTEXT = {".txt", ".md", ".markdown", ".csv", ".log", ".rst", ".json", ".yaml", ".yml"}


def _read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("reading PDF needs the 'pypdf' package") from exc
    reader = PdfReader(str(p))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(p: Path) -> str:
    try:
        import docx  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("reading DOCX needs the 'python-docx' package") from exc
    return "\n".join(para.text for para in docx.Document(str(p)).paragraphs)


def _read_markitdown(p: Path) -> str:
    """MarkItDown converts many formats (pdf/docx/pptx/xlsx/html/epub/…) to clean
    markdown — the same engine the v1 RAG used. Optional dependency."""
    from markitdown import MarkItDown  # noqa: PLC0415

    result = MarkItDown().convert(str(p))
    return result.text_content or ""


def extract_text(p: Path) -> str:
    """Best available extraction: MarkItDown first (richest), then plaintext/pypdf/docx."""
    suffix = p.suffix.lower()
    if suffix in _PLAINTEXT:
        return p.read_text(encoding="utf-8", errors="replace")
    try:
        text = _read_markitdown(p)
        if text.strip():
            return text
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — fall back to the format-specific readers
        pass
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix == ".docx":
        return _read_docx(p)
    # Final fallback: many files are just text under an unfamiliar extension. If the
    # bytes look textual (decode as UTF-8 with no NUL bytes), read them as text rather
    # than refusing. Genuine binaries (with NULs) stay "unsupported".
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"cannot read {p.name}: {exc}") from exc
    if raw and b"\x00" not in raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")
    raise RuntimeError(f"unsupported document type: {suffix or '(none)'}")


def _read_document(args: dict) -> ToolResult:
    path = (args.get("path") or "").strip()
    ok, reason = check_path(path)
    if not ok:
        return ToolResult(ok=False, content="", error=reason)
    p = Path(path).expanduser()
    if not p.is_file():
        return ToolResult(ok=False, content="", error=f"not a file: {path}")

    try:
        text = extract_text(p)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))

    text = (text or "").strip()
    if not text:
        return ToolResult(ok=True, content="(document contained no extractable text)")
    truncated = len(text) > _MAX_CHARS
    return ToolResult(ok=True, content=text[:_MAX_CHARS] + ("\n…[truncated]" if truncated else ""),
                      data={"chars": len(text), "truncated": truncated})


def register(registry: ToolRegistry) -> None:
    registry.register("read_document",
        "Extract text from a document (pdf/docx/pptx/xlsx/html/epub/txt/md/csv via "
        "MarkItDown) for reading or summarising.", {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "path to the document file"}},
            "required": ["path"],
        }, _read_document)
