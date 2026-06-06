"""SessionRAG retrieval behaviour, incl. the 2026-05-29 no-match fallback."""
from __future__ import annotations

from core.session_rag import SessionRAG


_DOC = """# John Doe
Software Engineer based in Nellore.

## Experience
Built the FRIDAY local assistant end to end.

## Skills
Python, system design, distributed systems.
"""


def _loaded(tmp_path):
    p = tmp_path / "resume.md"
    p.write_text(_DOC, encoding="utf-8")
    rag = SessionRAG()
    rag.load_file(p)
    return rag


def test_keyword_match_returns_relevant_chunk(tmp_path):
    rag = _loaded(tmp_path)
    chunks = rag.retrieve("python skills", top_k=3)
    assert any("Python" in c for c in chunks)


def test_no_match_falls_back_to_leading_chunks(tmp_path):
    # "document" never appears in the resume → BM25 scores nothing. The
    # fallback must still return leading chunks (not an empty list) so the
    # chat path has document grounding for "what is there in the document?".
    rag = _loaded(tmp_path)
    chunks = rag.retrieve("what is there in the document", top_k=3)
    assert chunks, "no-match retrieval returned an empty context block"
    # Leading chunk(s) of the resume, in document order.
    assert "Software Engineer" in chunks[0]


def test_empty_query_returns_leading_chunks(tmp_path):
    rag = _loaded(tmp_path)
    assert rag.retrieve("", top_k=2)


def test_context_block_non_empty_for_generic_question(tmp_path):
    rag = _loaded(tmp_path)
    block = rag.get_context_block("what is there in the document", top_k=3)
    assert block and "resume.md" in block


def test_context_block_grants_capability_and_pins_current_doc(tmp_path):
    # 2026-05-29: the model refused doc questions ("I don't have a tool")
    # and conflated a new doc with an earlier one. The block must explicitly
    # grant the read capability and pin the answer to the current document.
    rag = _loaded(tmp_path)
    block = rag.get_context_block("summarize this").lower()
    assert "no tool" in block and "never say you can't" in block
    assert "ignore it" in block  # disregard any earlier document


def test_inactive_rag_returns_nothing():
    rag = SessionRAG()
    assert rag.retrieve("anything") == []
    assert rag.get_context_block("anything") == ""


# ── hybrid (keyword + semantic) retrieval ──────────────────────────────


class _FakeEmbedder:
    """Tiny deterministic 3-topic embedder so the dense path is testable
    without sentence-transformers installed: [build/create, skills/python,
    identity/engineer]."""

    model_name = "fake-test-embedder"

    def embed(self, texts):
        out = []
        for t in texts:
            tl = t.lower()
            v = [
                1.0 if any(w in tl for w in ("experience", "built", "build", "create")) else 0.0,
                1.0 if any(w in tl for w in ("skill", "python")) else 0.0,
                1.0 if any(w in tl for w in ("engineer", "based")) else 0.0,
            ]
            norm = (sum(x * x for x in v) ** 0.5) or 1.0
            out.append([x / norm for x in v])
        return out


def test_load_reports_hybrid_mode_when_embedder_present(tmp_path):
    rag = SessionRAG()
    rag._embedder = _FakeEmbedder()
    msg = rag.load_file(_make_doc(tmp_path))
    assert "hybrid" in msg


def test_dense_rank_finds_paraphrase_with_no_keyword_overlap(tmp_path):
    # "what did they create" shares no literal term with the document, so BM25
    # alone scores nothing. The dense pass must still surface the Experience
    # chunk ("Built the FRIDAY ...") — the whole point of going hybrid.
    rag = SessionRAG()
    rag._embedder = _FakeEmbedder()
    rag.load_file(_make_doc(tmp_path))
    ranked = rag._dense_rank("what did they create")
    assert ranked and "Built the FRIDAY" in ranked[0].text


def _make_doc(tmp_path):
    p = tmp_path / "resume.md"
    p.write_text(_DOC, encoding="utf-8")
    return p
