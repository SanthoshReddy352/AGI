"""Track 5.1c — focused MemoryStore integration tests.

Exercises facts + memory_items + the Chroma-backed semantic_recall
(falling back to token-overlap when Chroma is unavailable). Real
SQLite + real Chroma — no mocks.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.stores import MemoryStore


@pytest.fixture()
def store(tmp_path):
    return MemoryStore(
        str(tmp_path / "friday.db"),
        str(tmp_path / "chroma"),
    )


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

def test_memory_store_creates_only_its_own_tables(store):
    """MemoryStore owns exactly `facts` + `memory_items` — no other
    tables ContextStore historically created."""
    conn = sqlite3.connect(store.db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    assert names == {"facts", "memory_items"}


# ----------------------------------------------------------------------
# facts
# ----------------------------------------------------------------------

def test_store_fact_and_get_by_namespace(store):
    store.store_fact("weather", "sunny", session_id="s1")
    store.store_fact("location", "Bangalore", session_id="s1")
    facts = store.get_facts_by_namespace("general")
    keys = {f["key"] for f in facts}
    assert keys == {"weather", "location"}


def test_store_fact_upsert_on_same_key(store):
    store.store_fact("mood", "happy", session_id="s1")
    store.store_fact("mood", "tired", session_id="s1")
    facts = store.get_facts_by_namespace("general")
    assert len(facts) == 1
    assert facts[0]["value"] == "tired"


def test_store_fact_empty_key_is_noop(store):
    store.store_fact("", "x")
    assert store.get_facts_by_namespace("general") == []


def test_store_fact_respects_namespace(store):
    store.store_fact("k", "v1", namespace="profile")
    store.store_fact("k", "v2", namespace="settings")
    profile = store.get_facts_by_namespace("profile")
    settings = store.get_facts_by_namespace("settings")
    assert profile == [{"key": "k", "value": "v1"}]
    assert settings == [{"key": "k", "value": "v2"}]


# ----------------------------------------------------------------------
# memory_items
# ----------------------------------------------------------------------

def test_store_memory_item_round_trip(store):
    store.store_memory_item("s1", "I went to Paris last summer",
                            metadata={"tag": "travel"})
    items = store.recent_memory_items("s1")
    assert len(items) == 1
    assert items[0]["content"] == "I went to Paris last summer"
    assert items[0]["metadata"] == {"tag": "travel"}


def test_recent_memory_items_persona_filter(store):
    store.store_memory_item("s1", "shared item")
    store.store_memory_item("s1", "alice item", persona_id="alice")
    store.store_memory_item("s1", "bob item", persona_id="bob")
    alice_items = store.recent_memory_items("s1", persona_id="alice")
    contents = {i["content"] for i in alice_items}
    # alice's persona AND blank-persona items both visible
    assert contents == {"shared item", "alice item"}


def test_delete_memory_item(store):
    store.store_memory_item("s1", "ephemeral",
                            metadata={"item_id": "abc-123"})
    assert any(i["item_id"] == "abc-123" for i in store.recent_memory_items("s1"))
    store.delete_memory_item("abc-123")
    assert not any(i["item_id"] == "abc-123" for i in store.recent_memory_items("s1"))


def test_prune_low_confidence_memories(store):
    store.store_memory_item("s1", "high conf",
                            memory_type="semantic",
                            metadata={"item_id": "hi", "confidence": 0.9})
    store.store_memory_item("s1", "low conf",
                            memory_type="semantic",
                            metadata={"item_id": "lo", "confidence": 0.2})
    store.store_memory_item("s1", "episodic always kept",
                            metadata={"item_id": "ep"})
    removed = store.prune_low_confidence_memories("s1", min_confidence=0.5)
    assert removed == 1
    remaining = {i["item_id"] for i in store.recent_memory_items("s1")}
    assert remaining == {"hi", "ep"}


# ----------------------------------------------------------------------
# semantic_recall (vector + fallback)
# ----------------------------------------------------------------------

def test_semantic_recall_returns_relevant_documents(store):
    store.store_memory_item("s1", "I visited Tokyo for cherry blossoms")
    store.store_memory_item("s1", "weekend hike in the Pyrenees")
    store.store_memory_item("s1", "coffee shop near Tokyo Tower")
    hits = store.semantic_recall("Tokyo", "s1", limit=2)
    # Both vector and fallback should pull Tokyo-mentioning docs first.
    assert any("Tokyo" in h for h in hits)


def test_semantic_recall_empty_query_returns_empty(store):
    store.store_memory_item("s1", "any content")
    assert store.semantic_recall("", "s1") == []


def test_fallback_semantic_recall_uses_facts_and_turns(store):
    # Drop a fact and a synthetic turn — the fallback reads both tables.
    store.store_fact("favorite_city", "Tokyo", session_id="s1")
    conn = sqlite3.connect(store.db_path)
    # The fallback reads from `turns` (cross-store READ is fine).
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS turns ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id TEXT NOT NULL,"
        " role TEXT NOT NULL,"
        " text TEXT NOT NULL,"
        " source TEXT NOT NULL,"
        " created_at TEXT NOT NULL"
        ");"
    )
    conn.execute(
        "INSERT INTO turns (session_id, role, text, source, created_at) "
        "VALUES ('s1', 'user', 'I love Tokyo ramen', 'text', '2026-05-19')"
    )
    conn.commit()
    hits = store._fallback_semantic_recall("Tokyo", "s1", limit=5)
    assert any("Tokyo" in h for h in hits)
    assert any("favorite_city" in h for h in hits)


# ----------------------------------------------------------------------
# upsert_vector — cross-domain helper
# ----------------------------------------------------------------------

def test_upsert_vector_indexes_text(store):
    """The cross-domain helper used by workflow summary + persona example
    writers. Empty text is a no-op; valid text gets indexed when Chroma
    is available."""
    store.upsert_vector("", "anything", {"k": "v"})  # empty id no-op
    store.upsert_vector("workflow:s1:test", "summary text",
                        {"session_id": "s1", "kind": "workflow"})
    # No exception is the success criterion — Chroma may not be available
    # in all test environments; the function is best-effort.


# ----------------------------------------------------------------------
# ContextStore delegators stay byte-equivalent
# ----------------------------------------------------------------------

def test_context_store_memory_methods_share_memory_store_state(tmp_path):
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    cs.store_fact("city", "Bangalore", session_id="s1")
    # Read via the direct store should see the same row.
    direct = cs._memory_store.get_facts_by_namespace("general")
    assert direct == [{"key": "city", "value": "Bangalore"}]

    cs._memory_store.store_memory_item("s1", "wrote a test")
    cs_view = cs.recent_memory_items("s1")
    assert any("wrote a test" == i["content"] for i in cs_view)
