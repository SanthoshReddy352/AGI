"""RAG overhaul (2026-05-25) — MemoryStore semantic-recall behaviours.

Covers the pieces added in the RAG production-hardening tracks:
  * Track 1 — real semantic recall (paraphrase with zero shared tokens)
  * Track 2 — vector-store resilience (cooldown, not permanent disable)
  * Track 3 — lazy re-index on embedder-signature change
  * Track 4 — RRF fusion of dense + sparse candidates
  * Track 5 — MMR diversity
  * Track 6 — recency / type weighting
  * Track 7 — embedding cache

Model-dependent cases skip automatically when sentence-transformers is
unavailable (offline hash fallback), so the suite still runs on a bare box.
"""
from __future__ import annotations

import time

import pytest

from core.memory.embeddings import SentenceTransformerEmbedder, get_shared_embedder
from core.stores import MemoryStore
from core.stores.memory_store import HashEmbeddingFunction, SemanticEmbeddingFunction


def _has_real_embedder() -> bool:
    return isinstance(get_shared_embedder(), SentenceTransformerEmbedder)


requires_model = pytest.mark.skipif(
    not _has_real_embedder(),
    reason="sentence-transformers unavailable; semantic assertions need a real model",
)


@pytest.fixture()
def store(tmp_path):
    return MemoryStore(str(tmp_path / "friday.db"), str(tmp_path / "chroma"))


# ----------------------------------------------------------------------
# Track 1 — real semantic recall
# ----------------------------------------------------------------------

@requires_model
def test_paraphrase_recall_with_no_shared_tokens(store):
    """The headline fix: 'sibling' must recall 'sister' even though the
    query and the stored memory share no literal tokens — impossible with
    the old hash-bucket embedder."""
    store.store_memory_item("s1", "My sister's name is Asha", memory_type="semantic")
    store.store_memory_item("s1", "The weather is sunny today", memory_type="episodic")
    hits = store.semantic_recall("what is my sibling called", "s1", limit=1)
    assert hits and "sister" in hits[0].lower()


@requires_model
def test_recall_ranks_relevant_over_irrelevant(store):
    store.store_memory_item("s1", "I work as a backend engineer", memory_type="semantic")
    store.store_memory_item("s1", "I had pasta for dinner", memory_type="episodic")
    hits = store.semantic_recall("where am I employed", "s1", limit=1)
    assert hits and "engineer" in hits[0].lower()


# ----------------------------------------------------------------------
# Track 2 — resilience
# ----------------------------------------------------------------------

def test_vector_failure_uses_cooldown_not_permanent_disable(store):
    """A burst of failures pauses the vector store for a cooldown window,
    after which _vector_ready() re-initialises it — the old code latched
    _vector_available=False forever."""
    store._VECTOR_COOLDOWN_SEC = 0.2
    for _ in range(store._VECTOR_FAIL_THRESHOLD):
        store._note_vector_failure(RuntimeError("boom"))
    assert store._vector_available is False
    assert store._vector_ready() is False  # still in cooldown
    time.sleep(0.25)
    # cooldown elapsed -> re-init attempted; with Chroma present it recovers
    assert store._vector_ready() is True


# ----------------------------------------------------------------------
# Track 3 — lazy re-index on embedder change
# ----------------------------------------------------------------------

@requires_model
def test_embedder_signature_change_rebuilds_collection(tmp_path):
    """Open the collection once with the real embedder, then force a stale
    hash signature and re-open: the mismatch must drop & recreate so a
    64-dim → 384-dim swap can't corrupt queries."""
    db, vec = str(tmp_path / "f.db"), str(tmp_path / "chroma")
    s1 = MemoryStore(db, vec)
    s1.store_memory_item("s1", "indexed under the real embedder")
    real_sig = s1._embedder_signature
    assert real_sig.startswith("friday-st-v1")

    import chromadb
    client = chromadb.PersistentClient(path=vec)
    # Simulate a prior hash-built collection by stamping a stale signature.
    MemoryStore._maybe_rebuild_collection(client, "friday-hash-v1:64")
    names = {c.name for c in client.list_collections()}
    assert "friday_memory" not in names  # stale collection dropped


# ----------------------------------------------------------------------
# Track 4 — RRF fusion
# ----------------------------------------------------------------------

def test_rrf_fuse_rewards_agreement_between_retrievers():
    dense = [{"text": "A", "rank": 1, "source": "dense", "kind": "semantic",
              "persona_id": "", "created_at": ""},
             {"text": "B", "rank": 0, "source": "dense", "kind": "", "persona_id": "",
              "created_at": ""}]
    sparse = [{"text": "A", "rank": 0, "source": "sparse", "kind": "episodic",
               "persona_id": "", "created_at": ""}]
    fused = MemoryStore._rrf_fuse(dense, sparse)
    # 'A' found by BOTH retrievers must outrank 'B' found by one.
    assert fused[0]["text"] == "A"
    assert fused[0]["kind"] == "semantic"  # dense metadata wins the merge


# ----------------------------------------------------------------------
# Track 5 — MMR diversity
# ----------------------------------------------------------------------

@requires_model
def test_mmr_prefers_diverse_results(store):
    # Two near-duplicates plus one distinct relevant memory.
    store.store_memory_item("s1", "I love hiking in the mountains")
    store.store_memory_item("s1", "I enjoy mountain hiking trips")
    store.store_memory_item("s1", "I also play the violin")
    hits = store.semantic_recall("tell me about my hobbies", "s1", limit=2)
    joined = " ".join(hits).lower()
    # MMR should not return two paraphrases of the same hiking memory.
    assert "violin" in joined


# ----------------------------------------------------------------------
# Track 6 — recency weighting
# ----------------------------------------------------------------------

def test_recency_factor_decays_with_age(store):
    from datetime import datetime, timezone, timedelta
    fresh = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    assert store._recency_factor(fresh) > store._recency_factor(old)
    assert store._recency_factor("") == 1.0          # missing → neutral
    assert store._recency_factor("not-a-date") == 1.0  # unparseable → neutral


# ----------------------------------------------------------------------
# Track 7 — embedding cache
# ----------------------------------------------------------------------

@requires_model
def test_embedder_caches_repeated_text():
    emb = SentenceTransformerEmbedder(cache_size=16)
    v1 = emb.embed(["repeat me"])[0]
    v2 = emb.embed(["repeat me"])[0]
    assert v1 == v2
    # Cache holds exactly one entry for the single unique string.
    assert len(emb._cache) == 1
