"""Session-scoped in-memory RAG with hybrid (keyword + semantic) retrieval.

Converts a document via MarkItDown, splits into heading-aware chunks, and
retrieves at query time by fusing two signals:

* **BM25** keyword scoring — exact term matches, zero extra inference.
* **Dense semantic** scoring — cosine over the process-wide sentence-
  transformer embedder (the same `all-MiniLM-L6-v2` already resident for
  memory recall, so no extra model is loaded). Catches paraphrases that
  share no literal terms with the document — the common case for "what did
  you understand about this?" style questions.

The two rankings are fused with Reciprocal Rank Fusion (RRF), which is
scale-free and needs no score normalization. When sentence-transformers is
unavailable (offline / hash-embedder fallback), retrieval degrades cleanly
to BM25-only — so the system keeps working on a minimal install.

Cleared when the session ends or the user loads a new file.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in (text or ""))
    return [t for t in cleaned.split() if len(t) > 1]


# Broad/overview questions whose terms rarely appear verbatim in the document.
# When the query reads like one of these we ground the answer in the document's
# leading section plus the strongest semantic hits, rather than relying on
# keyword overlap that will not exist.
_OVERVIEW_RE = re.compile(
    r"\b(summar|overview|gist|main points?|key points?|understand|understood|"
    r"what(?:'s| is| are| does)|tell me about|explain|describe|contain|about (?:it|this|the )|"
    r"what'?s in|content|outline|brief)\b",
    re.IGNORECASE,
)


def _dot(a: list[float], b: list[float]) -> float:
    """Cosine for L2-normalized vectors (the embedder normalizes its output)."""
    return sum(x * y for x, y in zip(a, b))


@dataclass
class _Chunk:
    text: str
    heading: str
    index: int
    tf: Counter = field(default_factory=Counter)

    def __post_init__(self):
        self.tf = Counter(_tokenize(self.text))

    @property
    def embed_text(self) -> str:
        """Heading + body — the heading carries section context the body omits."""
        return f"{self.heading}\n{self.text}".strip() if self.heading else self.text


def _split_chunks(markdown: str, max_chars: int = 600) -> list[_Chunk]:
    chunks: list[_Chunk] = []
    current_heading = ""
    index = 0

    # Split on markdown headings so each section stays together
    sections = re.split(r"(?m)^(#{1,3} .+)$", markdown)
    for part in sections:
        if re.match(r"^#{1,3} ", part):
            current_heading = part.strip()
            continue
        if not part.strip():
            continue
        paragraphs = re.split(r"\n{2,}", part)
        buffer = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(buffer) + len(para) > max_chars and buffer:
                chunks.append(_Chunk(text=buffer.strip(), heading=current_heading, index=index))
                index += 1
                buffer = para
            else:
                buffer = (buffer + "\n\n" + para).strip() if buffer else para
        if buffer.strip():
            chunks.append(_Chunk(text=buffer.strip(), heading=current_heading, index=index))
            index += 1

    # Safety net: if splitting produced nothing (e.g. flat CSV, no headings),
    # treat the entire document as one chunk — no truncation.
    return chunks or [_Chunk(text=markdown, heading="", index=0)]


class SessionRAG:
    """In-memory hybrid retriever for a single session document.

    No dedicated model load: BM25 is pure arithmetic and the dense pass reuses
    the resident shared embedder. Retrieval is a few milliseconds.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: list[_Chunk] = []
        self._df: Counter = Counter()
        self._source_name: str = ""
        self._total_chars: int = 0
        # generation counter — bumped on every load, lets other subsystems
        # (e.g. AssistantContext) detect that a *different* document is active.
        self._generation: int = 0
        self._embedder = None  # resolved lazily on first load
        self._chunk_vecs: dict[int, list[float]] = {}

    @property
    def is_active(self) -> bool:
        return bool(self._chunks)

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def generation(self) -> int:
        return self._generation

    # Formats readable without MarkItDown
    _PLAIN_SUFFIXES = {".txt", ".md", ".csv", ".html"}

    def load_file(self, path: str | Path) -> str:
        """Convert *path* to markdown, chunk it, and build the hybrid index.

        Returns a human-readable status message. Replaces any previously
        loaded document — only one file is active per session.
        """
        path = Path(path)
        markdown = self._convert(path)
        chunks = _split_chunks(markdown)

        df: Counter = Counter()
        for chunk in chunks:
            for term in set(chunk.tf.keys()):
                df[term] += 1

        chunk_vecs = self._embed_chunks(chunks)

        with self._lock:
            self._chunks = chunks
            self._df = df
            self._source_name = path.name
            self._total_chars = sum(len(c.text) for c in chunks)
            self._chunk_vecs = chunk_vecs
            self._generation += 1

        mode = "hybrid" if chunk_vecs else "keyword"
        return f"Loaded '{path.name}' — {len(chunks)} chunks indexed ({mode})."

    # ── retrieval ──────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 4) -> list[str]:
        """Return the top-k most relevant chunk texts for *query*.

        Fuses BM25 and dense-semantic rankings via RRF. For overview-style
        questions (or queries with no keyword/semantic signal) the document's
        leading section is included first so the answer is always grounded in
        the actual document, never an empty or off-topic context block.
        """
        if not self._chunks:
            return []
        with self._lock:
            chunks = self._ordered_chunks(query, top_k)
        return [c.text for c in chunks]

    def _ordered_chunks(self, query: str, top_k: int) -> list[_Chunk]:
        query_terms = list(Counter(_tokenize(query)).keys())
        leading = self._chunks[: min(2, len(self._chunks))]

        if not query_terms:
            return self._chunks[:top_k]

        bm25 = self._bm25_rank(query_terms)
        dense = self._dense_rank(query)
        fused = self._rrf(bm25, dense)

        if not fused:
            # No keyword or semantic signal at all — pure document grounding.
            return self._chunks[:top_k]

        is_overview = bool(_OVERVIEW_RE.search(query)) or not bm25
        if is_overview:
            # Lead with the document's opening section for grounding, then add
            # the strongest relevant chunks not already covered.
            ordered = list(leading)
            seen = {c.index for c in ordered}
            for chunk in fused:
                if chunk.index not in seen:
                    ordered.append(chunk)
                    seen.add(chunk.index)
            return ordered[:top_k]
        return fused[:top_k]

    def _bm25_rank(self, query_terms: list[str]) -> list[_Chunk]:
        n = len(self._chunks)
        k1, b = 1.5, 0.75
        avgdl = (sum(sum(c.tf.values()) for c in self._chunks) / n) or 1.0
        scored: list[tuple[float, _Chunk]] = []
        for chunk in self._chunks:
            dl = sum(chunk.tf.values()) or 1
            score = 0.0
            for term in query_terms:
                tf = chunk.tf.get(term, 0)
                if tf == 0:
                    continue
                df = self._df.get(term, 1)
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored]

    def _dense_rank(self, query: str) -> list[_Chunk]:
        if not self._chunk_vecs or self._embedder is None:
            return []
        try:
            qvec = self._embedder.embed([query])[0]
        except Exception:
            return []
        sims: list[tuple[float, _Chunk]] = []
        for chunk in self._chunks:
            vec = self._chunk_vecs.get(chunk.index)
            if vec is None:
                continue
            sims.append((_dot(qvec, vec), chunk))
        # Drop weakly-related chunks so the dense ranking does not dilute RRF
        # with noise on a focused query (kept generous; overview queries still
        # get leading-chunk grounding regardless).
        sims = [(s, c) for s, c in sims if s > 0.15]
        sims.sort(key=lambda x: -x[0])
        return [c for _, c in sims]

    @staticmethod
    def _rrf(*rankings: list[_Chunk], k: int = 60) -> list[_Chunk]:
        """Reciprocal Rank Fusion — scale-free combination of rankings."""
        scores: dict[int, float] = defaultdict(float)
        by_index: dict[int, _Chunk] = {}
        for ranking in rankings:
            for rank, chunk in enumerate(ranking):
                scores[chunk.index] += 1.0 / (k + rank + 1)
                by_index[chunk.index] = chunk
        return sorted(by_index.values(), key=lambda c: -scores[c.index])

    def get_context_block(self, query: str, top_k: int | None = None) -> str:
        """Return a formatted context string ready to inject into the LLM prompt."""
        if top_k is None:
            # Overview questions need broader coverage; focused questions stay tight.
            top_k = 6 if _OVERVIEW_RE.search(query or "") else 4
        chunks = self.retrieve(query, top_k=top_k)
        if not chunks:
            return ""
        joined = "\n\n---\n\n".join(chunks)
        name = self._source_name
        # Strong, directive framing (2026-05-29 fix). Two failure modes this
        # block must defeat, both seen in the wild with the 0.8B chat model:
        #   1. The model refused doc questions ("I don't have a tool for this
        #      document, so I can't generate it") because the global identity
        #      guard says "never claim an action you don't have a tool for".
        #      We explicitly grant the capability here — reading the excerpts
        #      IS the tool, so it must never decline.
        #   2. The model conflated a newly attached file with a previously
        #      discussed one (the Dubai doc bleeding into a resume answer)
        #      because the old turn still lived in conversation history. We
        #      pin the answer to the current document and tell it to ignore
        #      anything discussed earlier. (AssistantContext also prunes prior
        #      document turns from history on a new load — belt and braces.)
        return (
            f"[DOCUMENT Q&A] The user has attached the document '{name}' and is "
            f"asking about it. You CAN read and answer using ONLY the excerpts "
            f"below — no tool, plugin, or special capability is needed, so never "
            f"say you can't do this. Answer about '{name}' ONLY; if a different "
            f"document was discussed earlier in this conversation, ignore it — it "
            f"is no longer loaded.\n"
            f"{joined}\n"
            f"[End of '{name}' excerpts]"
        )

    def clear(self):
        with self._lock:
            self._chunks = []
            self._df = Counter()
            self._source_name = ""
            self._total_chars = 0
            self._chunk_vecs = {}

    # ── internals ──────────────────────────────────────────────────────

    def _embed_chunks(self, chunks: list[_Chunk]) -> dict[int, list[float]]:
        """Embed every chunk once at load. Returns {} when no real embedder is
        available (offline / hash fallback), which disables the dense pass."""
        embedder = self._resolve_embedder()
        if embedder is None:
            return {}
        try:
            vecs = embedder.embed([c.embed_text for c in chunks])
        except Exception:
            return {}
        if not vecs or len(vecs) != len(chunks):
            return {}
        return {chunk.index: vecs[i] for i, chunk in enumerate(chunks)}

    def _resolve_embedder(self):
        """Lazily resolve the process-wide embedder. Returns None when only the
        keyword-grade HashEmbedder is available so the dense pass stays off."""
        if self._embedder is not None:
            return self._embedder
        try:
            from core.memory.embeddings import get_shared_embedder  # noqa: PLC0415
            embedder = get_shared_embedder()
        except Exception:
            return None
        # HashEmbedder is a deterministic offline stand-in with keyword-grade
        # recall — fusing it with BM25 adds noise, not signal, so skip it.
        if type(embedder).__name__ == "HashEmbedder":
            return None
        self._embedder = embedder
        return embedder

    def _convert(self, path: Path) -> str:
        """Convert *path* to a markdown string.

        Uses MarkItDown when available. Falls back to direct UTF-8 read for
        plain-text formats so .txt / .md / .csv / .html work without MarkItDown.
        Raises a helpful ImportError for binary formats that require it.
        """
        try:
            from modules.document_intel.converter import convert_to_markdown
            return convert_to_markdown(path)
        except (ImportError, ModuleNotFoundError):
            suffix = path.suffix.lower()
            if suffix in self._PLAIN_SUFFIXES:
                text = path.read_text(encoding="utf-8", errors="replace")
                if not text.strip():
                    raise ValueError(f"File is empty: {path.name}")
                return text
            raise ImportError(
                f"MarkItDown is required to load {suffix} files. "
                f"Install it with: pip install markitdown"
            )
