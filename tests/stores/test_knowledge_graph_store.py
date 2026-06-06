"""Track 5.1c — focused KnowledgeGraphStore integration tests."""
from __future__ import annotations

import sqlite3

import pytest

from core.stores import KnowledgeGraphStore


@pytest.fixture()
def store(tmp_path):
    return KnowledgeGraphStore(str(tmp_path / "friday.db"))


def test_creates_only_its_own_tables(store):
    conn = sqlite3.connect(store.db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    assert names == {"entities", "entity_facts", "entity_relationships"}


# ----------------------------------------------------------------------
# entities
# ----------------------------------------------------------------------

def test_upsert_entity_returns_id_and_is_idempotent(store):
    a = store.upsert_entity("Alice", entity_type="person")
    b = store.upsert_entity("Alice", entity_type="person")
    assert a == b
    # Different type → different entity
    c = store.upsert_entity("Alice", entity_type="concept")
    assert c != a


def test_find_entities_by_fragment(store):
    store.upsert_entity("Alice")
    store.upsert_entity("Aldo")
    store.upsert_entity("Charlie")
    hits = {e["name"] for e in store.find_entities(name_fragment="Al")}
    assert hits == {"Alice", "Aldo"}


def test_find_entities_by_type(store):
    store.upsert_entity("Alice", entity_type="person")
    store.upsert_entity("Bangalore", entity_type="place")
    people = {e["name"] for e in store.find_entities(entity_type="person")}
    places = {e["name"] for e in store.find_entities(entity_type="place")}
    assert people == {"Alice"}
    assert places == {"Bangalore"}


# ----------------------------------------------------------------------
# entity_facts
# ----------------------------------------------------------------------

def test_add_and_query_entity_facts(store):
    eid = store.upsert_entity("Alice", entity_type="person")
    f1 = store.add_entity_fact(eid, "works_at", "Acme", confidence=0.9)
    f2 = store.add_entity_fact(eid, "lives_in", "Bangalore", confidence=0.7)
    facts = store.query_entity_facts(eid)
    assert len(facts) == 2
    # Higher confidence first.
    assert facts[0]["id"] == f1
    assert facts[1]["id"] == f2


# ----------------------------------------------------------------------
# entity_relationships
# ----------------------------------------------------------------------

def test_add_entity_relationship_persists(store):
    a = store.upsert_entity("Alice")
    b = store.upsert_entity("Acme", entity_type="org")
    rid = store.add_entity_relationship(a, b, rel_type="employed_by")
    conn = sqlite3.connect(store.db_path)
    rows = conn.execute(
        "SELECT id, from_id, to_id, rel_type FROM entity_relationships"
    ).fetchall()
    assert rows == [(rid, a, b, "employed_by")]


# ----------------------------------------------------------------------
# ContextStore delegators stay byte-equivalent
# ----------------------------------------------------------------------

def test_context_store_kg_methods_share_store_state(tmp_path):
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    eid = cs.upsert_entity("Alice", entity_type="person", session_id="s1")
    # Read via the direct store sees it.
    direct = cs._knowledge_graph_store.find_entities("Ali")
    assert {e["id"] for e in direct} == {eid}
