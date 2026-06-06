"""Tests for core/planning/references.py — Track 1.3b."""
from __future__ import annotations

import pytest

from core.stores import ContextStore
from core.planning.references import TurnReferences, attach


@pytest.fixture
def store(tmp_path):
    s = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = s.start_session({"source": "ref-tests"})
    return s, session_id


# ---------------------------------------------------------------------------
# Construction + attach factory
# ---------------------------------------------------------------------------


def test_attach_returns_bound_turn_references(store):
    s, session_id = store
    refs = attach(s, session_id)
    assert isinstance(refs, TurnReferences)
    assert refs._store is s
    assert refs._session_id == session_id


def test_default_constructor_yields_empty():
    refs = TurnReferences()
    assert refs.items() == []
    assert refs.kind() == ""
    assert refs.resolve("first") == ""


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_register_stores_items_in_memory(store):
    s, session_id = store
    refs = attach(s, session_id)
    refs.register(["a.pdf", "b.txt", "c.md"], kind="files")
    assert refs.items() == ["a.pdf", "b.txt", "c.md"]
    assert refs.kind() == "files"


def test_register_writes_ordinals_to_store(store):
    s, session_id = store
    refs = attach(s, session_id)
    refs.register(["a.pdf", "b.txt", "c.md"], kind="files")
    assert s.get_reference(session_id, "first") == "a.pdf"
    assert s.get_reference(session_id, "second") == "b.txt"
    assert s.get_reference(session_id, "third") == "c.md"


def test_register_writes_last_list_to_store(store):
    s, session_id = store
    refs = attach(s, session_id)
    refs.register(["a", "b", "c"], kind="files")
    assert s.get_reference(session_id, "last_list") == "a\nb\nc"
    assert s.get_reference(session_id, "last_list_kind") == "files"


def test_register_caps_at_ten_ordinals(store):
    s, session_id = store
    refs = attach(s, session_id)
    refs.register([f"item{i}" for i in range(15)], kind="files")
    assert refs.items() == [f"item{i}" for i in range(10)]
    assert s.get_reference(session_id, "tenth") == "item9"


def test_register_strips_whitespace_and_drops_empty(store):
    s, session_id = store
    refs = attach(s, session_id)
    refs.register(["  alpha  ", "", "beta", "   "], kind="files")
    assert refs.items() == ["alpha", "beta"]


def test_register_default_kind_is_items():
    refs = TurnReferences()
    refs.register(["a", "b"])
    assert refs.kind() == "items"


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


def test_resolve_word_ordinal(store):
    _s, session_id = store
    refs = attach(store[0], session_id)
    refs.register(["one", "two", "three"], kind="files")
    assert refs.resolve("first") == "one"
    assert refs.resolve("second") == "two"
    assert refs.resolve("third") == "three"


def test_resolve_digit_ordinal(store):
    _s, session_id = store
    refs = attach(store[0], session_id)
    refs.register(["one", "two", "three"], kind="files")
    assert refs.resolve("1st") == "one"
    assert refs.resolve("2nd") == "two"
    assert refs.resolve("3rd") == "three"


def test_resolve_last(store):
    _s, session_id = store
    refs = attach(store[0], session_id)
    refs.register(["one", "two", "three"], kind="files")
    assert refs.resolve("last") == "three"


def test_resolve_missing_ordinal_returns_empty(store):
    _s, session_id = store
    refs = attach(store[0], session_id)
    refs.register(["one"], kind="files")
    assert refs.resolve("seventh") == ""


def test_resolve_handles_blank_input(store):
    _s, session_id = store
    refs = attach(store[0], session_id)
    refs.register(["one"], kind="files")
    assert refs.resolve("") == ""
    assert refs.resolve("   ") == ""


def test_resolve_falls_back_to_store_when_no_inmemory_items(store):
    """A fresh TurnReferences (e.g. start of next turn) can still
    resolve ordinals that the PREVIOUS turn registered, because the
    store mirror retained them. Confirms cross-turn persistence."""
    s, session_id = store
    refs_prev = attach(s, session_id)
    refs_prev.register(["alpha", "beta", "gamma"], kind="files")

    # New TurnReferences for the next turn — no in-memory items.
    refs_next = attach(s, session_id)
    assert refs_next.items() == []
    # Resolution falls back to the store mirror.
    assert refs_next.resolve("second") == "beta"
    assert refs_next.resolve("last") == "gamma"


# ---------------------------------------------------------------------------
# Defensive: store / session_id missing
# ---------------------------------------------------------------------------


def test_register_without_store_does_not_raise():
    refs = TurnReferences()
    refs.register(["a", "b"], kind="files")
    assert refs.items() == ["a", "b"]


def test_resolve_without_store_returns_inmemory_only():
    refs = TurnReferences()
    refs.register(["a", "b"], kind="files")
    assert refs.resolve("first") == "a"
    assert refs.resolve("third") == ""


def test_resolve_with_flaky_store_returns_empty():
    """A store that raises on get_reference must not crash resolution."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    store = MagicMock()
    store.save_reference.side_effect = RuntimeError("write down")
    store.get_reference.side_effect = RuntimeError("read down")
    refs = attach(store, "sess-1")
    # register swallows the write exception
    refs.register(["a", "b"], kind="files")
    # resolve from in-memory still works
    assert refs.resolve("first") == "a"
    # resolve from store (fresh registry) swallows the read exception
    refs_fresh = attach(store, "sess-1")
    assert refs_fresh.resolve("first") == ""
