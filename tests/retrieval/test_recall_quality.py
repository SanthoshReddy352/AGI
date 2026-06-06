"""Retrieval-quality eval harness (RAG overhaul Track 8).

A labelled query→memory set with recall@k and MRR metrics, plus a pytest
gate so future changes to the embedder, fusion, or ranking can't silently
regress recall quality. Run standalone for a metrics dump:

    .venv/bin/python3 tests/retrieval/test_recall_quality.py

The thresholds are deliberately conservative — they assert the system is
doing *semantic* retrieval (paraphrases land), not a specific model's exact
numbers, so a model swap that stays good still passes.
"""
from __future__ import annotations

import pytest

from core.memory.embeddings import SentenceTransformerEmbedder, get_shared_embedder
from core.stores import MemoryStore


# (memory_id, stored_text)
MEMORIES = [
    ("sister", "My sister's name is Asha and she lives in Pune"),
    ("job", "I work as a backend engineer at a fintech startup"),
    ("food", "My favourite cuisine is Thai, especially green curry"),
    ("allergy", "I'm allergic to peanuts and shellfish"),
    ("car", "I drive a blue Honda Civic"),
    ("pet", "My dog Rocky is a golden retriever"),
    ("city", "I grew up in Nellore before moving away"),
    ("music", "I play the violin most evenings to unwind"),
]

# (query, expected_memory_id) — paraphrases that share few/no literal tokens
QUERIES = [
    ("what is my sibling called", "sister"),
    ("where am I employed", "job"),
    ("what kind of food do I enjoy", "food"),
    ("do I have any food allergies", "allergy"),
    ("which vehicle do I own", "car"),
    ("tell me about my pet animal", "pet"),
    ("what instrument do I play", "music"),
]

RECALL_AT_K = 3
MIN_RECALL_AT_3 = 0.85
MIN_MRR = 0.70


def _has_real_embedder() -> bool:
    return isinstance(get_shared_embedder(), SentenceTransformerEmbedder)


def _build_store(tmp_path) -> MemoryStore:
    store = MemoryStore(str(tmp_path / "friday.db"), str(tmp_path / "chroma"))
    for mid, text in MEMORIES:
        store.store_memory_item("eval", text, memory_type="semantic",
                                metadata={"item_id": mid})
    return store


def _text_to_id() -> dict:
    return {text: mid for mid, text in MEMORIES}


def evaluate(store: MemoryStore) -> dict:
    """Return recall@k and MRR over the labelled query set."""
    lookup = _text_to_id()
    hits_at_k = 0
    reciprocal_ranks = []
    for query, expected in QUERIES:
        results = store.semantic_recall(query, "eval", limit=len(MEMORIES))
        ranked_ids = [lookup.get(t) for t in results]
        if expected in ranked_ids[:RECALL_AT_K]:
            hits_at_k += 1
        rank = ranked_ids.index(expected) + 1 if expected in ranked_ids else 0
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    n = len(QUERIES)
    return {
        f"recall@{RECALL_AT_K}": hits_at_k / n,
        "mrr": sum(reciprocal_ranks) / n,
        "n_queries": n,
    }


@pytest.mark.skipif(not _has_real_embedder(),
                    reason="semantic retrieval quality needs a real embedder")
def test_recall_quality_meets_threshold(tmp_path):
    store = _build_store(tmp_path)
    metrics = evaluate(store)
    assert metrics[f"recall@{RECALL_AT_K}"] >= MIN_RECALL_AT_3, metrics
    assert metrics["mrr"] >= MIN_MRR, metrics


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    if not _has_real_embedder():
        print("sentence-transformers unavailable — cannot run quality eval.")
        raise SystemExit(1)
    with tempfile.TemporaryDirectory() as d:
        store = _build_store(Path(d))
        metrics = evaluate(store)
    print("Retrieval quality:")
    for k, v in metrics.items():
        print(f"  {k:12s} {v}")
