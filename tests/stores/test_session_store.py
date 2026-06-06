"""Track 5.1d — focused SessionStore integration tests.

Exercises the final domain store: session/turn lifecycle, the
working_artifact scope-precedence rule, the reference registry, and
the persona-row primitive. Real SQLite, no mocks.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from core.stores import (
    ARTIFACT_SCOPE_RANK,
    SessionStore,
    WorkingArtifact,
    artifact_scope_rank,
)


@pytest.fixture()
def store(tmp_path):
    return SessionStore(str(tmp_path / "friday.db"))


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

def test_session_store_creates_only_its_own_tables(store):
    conn = sqlite3.connect(store.db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    # P3.2 added the `turns_fts` virtual table for FTS5 keyword search;
    # SQLite materialises four shadow tables (turns_fts_data /
    # _idx / _docsize / _config) alongside it. They're all owned by
    # SessionStore via the FTS5 declaration in session.sql.
    owned = {"sessions", "turns", "conversation_sessions", "personas",
             "turns_fts", "turns_fts_data", "turns_fts_idx",
             "turns_fts_docsize", "turns_fts_config"}
    assert names == owned


# ----------------------------------------------------------------------
# sessions + turns + summarize + prune
# ----------------------------------------------------------------------

def test_start_session_returns_id_and_persists_row(store):
    sid = store.start_session({"entrypoint": "test"})
    assert sid
    conn = sqlite3.connect(store.db_path)
    rows = conn.execute("SELECT id, metadata_json FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == sid
    assert '"entrypoint"' in rows[0][1]


def test_append_turn_row_persists_and_bumps_session(store):
    sid = store.start_session()
    before = sqlite3.connect(store.db_path).execute(
        "SELECT updated_at FROM sessions WHERE id = ?", (sid,)
    ).fetchone()[0]

    store.append_turn_row(sid, "user", "hello", source="text")
    store.append_turn_row(sid, "assistant", "hi", source="assistant")

    rows = sqlite3.connect(store.db_path).execute(
        "SELECT role, text, source FROM turns WHERE session_id = ? ORDER BY id",
        (sid,),
    ).fetchall()
    assert rows == [("user", "hello", "text"), ("assistant", "hi", "assistant")]

    after = sqlite3.connect(store.db_path).execute(
        "SELECT updated_at FROM sessions WHERE id = ?", (sid,)
    ).fetchone()[0]
    assert after >= before


def test_append_turn_row_empty_session_id_is_noop(store):
    assert store.append_turn_row("", "user", "x") == ""


def test_summarize_session_orders_oldest_first(store):
    sid = store.start_session()
    store.append_turn_row(sid, "user", "first")
    store.append_turn_row(sid, "assistant", "second")
    store.append_turn_row(sid, "user", "third")
    summary = store.summarize_session(sid, limit=10)
    assert summary == "user: first\nassistant: second\nuser: third"


def test_summarize_empty_session(store):
    sid = store.start_session()
    assert store.summarize_session(sid) == ""


def test_prune_old_turns_drops_only_aged_rows(store):
    sid = store.start_session()
    store.append_turn_row(sid, "user", "recent")
    # Backdate one row.
    stale = (datetime.utcnow() - timedelta(days=60)).isoformat()
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "INSERT INTO turns (session_id, role, text, source, created_at) "
        "VALUES (?, 'user', 'aged', 'text', ?)",
        (sid, stale),
    )
    conn.commit()
    deleted = store.prune_old_turns(sid, older_than_days=30)
    assert deleted == 1
    remaining = sqlite3.connect(store.db_path).execute(
        "SELECT text FROM turns WHERE session_id = ?", (sid,)
    ).fetchall()
    assert remaining == [("recent",)]


# ----------------------------------------------------------------------
# conversation_sessions (session-state JSON)
# ----------------------------------------------------------------------

def test_save_and_get_session_state_round_trip(store):
    sid = store.start_session()
    store.save_session_state(sid, {
        "active_persona_id": "alfred",
        "pending_online": {"tool_name": "web_fetch"},
        "custom_key": {"nested": [1, 2, 3]},
    })
    state = store.get_session_state(sid)
    assert state["active_persona_id"] == "alfred"
    assert state["pending_online"] == {"tool_name": "web_fetch"}
    assert state["custom_key"] == {"nested": [1, 2, 3]}


def test_get_session_state_returns_empty_dict_for_unknown(store):
    assert store.get_session_state("nope") == {}
    assert store.get_session_state("") == {}


def test_active_persona_helpers(store):
    sid = store.start_session()
    store.set_active_persona(sid, "alfred")
    assert store.get_active_persona_id(sid) == "alfred"
    store.set_active_persona(sid, "")
    assert store.get_active_persona_id(sid) == ""


def test_pending_online_helpers(store):
    sid = store.start_session()
    store.set_pending_online(sid, {"tool_name": "web_fetch", "reason": "ask"})
    assert store.get_session_state(sid)["pending_online"]["tool_name"] == "web_fetch"
    store.clear_pending_online(sid)
    assert store.get_session_state(sid)["pending_online"] == {}


def test_clear_pending_online_on_unknown_session_is_noop(store):
    store.clear_pending_online("nope")  # no exception


# ----------------------------------------------------------------------
# Working artifact + scope-precedence rule (Track 1.2 invariant)
# ----------------------------------------------------------------------

def test_artifact_scope_rank_known_and_unknown():
    assert artifact_scope_rank("inferred") == 1
    assert artifact_scope_rank("auto") == 2
    assert artifact_scope_rank("explicit") == 3
    assert artifact_scope_rank("last_write") == 4
    assert artifact_scope_rank("session") == 5
    # Unknown defaults to auto.
    assert artifact_scope_rank("nonsense") == ARTIFACT_SCOPE_RANK["auto"]
    assert artifact_scope_rank("") == ARTIFACT_SCOPE_RANK["auto"]


def test_save_artifact_round_trip(store):
    sid = store.start_session()
    store.save_artifact(sid, WorkingArtifact(
        content="hello",
        source_path="/tmp/x.txt",
        capability_name="read_file",
        scope="explicit",
    ))
    art = store.get_artifact(sid)
    assert art is not None
    assert art.content == "hello"
    assert art.source_path == "/tmp/x.txt"
    assert art.capability_name == "read_file"
    assert art.scope == "explicit"


def test_get_artifact_when_unset_is_none(store):
    sid = store.start_session()
    assert store.get_artifact(sid) is None


def test_higher_scope_wins_over_lower(store):
    """`explicit` (rank 3) wins over `auto` (rank 2)."""
    sid = store.start_session()
    store.save_artifact(sid, WorkingArtifact(content="auto-set", scope="auto"))
    store.save_artifact(sid, WorkingArtifact(content="explicit-set", scope="explicit"))
    assert store.get_artifact(sid).content == "explicit-set"


def test_lower_scope_cannot_displace_higher(store):
    """`inferred` (rank 1) cannot displace `explicit` (rank 3)."""
    sid = store.start_session()
    store.save_artifact(sid, WorkingArtifact(content="explicit-set", scope="explicit"))
    store.save_artifact(sid, WorkingArtifact(content="inferred-ignored", scope="inferred"))
    assert store.get_artifact(sid).content == "explicit-set"


def test_last_write_wins_over_explicit(store):
    """The Track 1.2 invariant: a fresh file write supersedes any stale
    explicit pronoun anchor."""
    sid = store.start_session()
    store.save_artifact(sid, WorkingArtifact(content="explicit-set", scope="explicit"))
    store.save_artifact(sid, WorkingArtifact(content="last-write-wins", scope="last_write"))
    assert store.get_artifact(sid).content == "last-write-wins"


def test_equal_scope_later_overwrites_earlier(store):
    sid = store.start_session()
    store.save_artifact(sid, WorkingArtifact(content="first", scope="explicit"))
    store.save_artifact(sid, WorkingArtifact(content="second", scope="explicit"))
    assert store.get_artifact(sid).content == "second"


def test_clear_artifact(store):
    sid = store.start_session()
    store.save_artifact(sid, WorkingArtifact(content="x", scope="explicit"))
    assert store.get_artifact(sid) is not None
    store.clear_artifact(sid)
    assert store.get_artifact(sid) is None


# ----------------------------------------------------------------------
# Reference registry
# ----------------------------------------------------------------------

def test_save_get_all_references(store):
    sid = store.start_session()
    store.save_reference(sid, "active_document", "/tmp/x.txt")
    store.save_reference(sid, "last_file", "/tmp/y.txt")
    assert store.get_reference(sid, "active_document") == "/tmp/x.txt"
    assert store.get_reference(sid, "missing") is None
    assert store.get_all_references(sid) == {
        "active_document": "/tmp/x.txt",
        "last_file": "/tmp/y.txt",
    }


# ----------------------------------------------------------------------
# personas (upsert_persona_row + get + list)
# ----------------------------------------------------------------------

def test_upsert_persona_row_inserts_and_updates(store):
    pid = store.upsert_persona_row({
        "persona_id": "alfred",
        "display_name": "Alfred",
        "system_identity": "butler",
        "example_dialogues": "Sir, your tea.",
    })
    assert pid == "alfred"
    fetched = store.get_persona("alfred")
    assert fetched["display_name"] == "Alfred"
    assert fetched["system_identity"] == "butler"

    # Update — display name changes; row stays unique.
    store.upsert_persona_row({"persona_id": "alfred", "display_name": "Alfie"})
    rows = sqlite3.connect(store.db_path).execute(
        "SELECT persona_id, display_name FROM personas"
    ).fetchall()
    assert rows == [("alfred", "Alfie")]


def test_upsert_persona_row_empty_id_is_noop(store):
    assert store.upsert_persona_row({}) == ""
    assert store.upsert_persona_row({"persona_id": ""}) == ""
    assert store.list_personas() == []


def test_list_personas_sorted_by_display_name(store):
    store.upsert_persona_row({"persona_id": "z", "display_name": "Zebra"})
    store.upsert_persona_row({"persona_id": "a", "display_name": "Alfred"})
    store.upsert_persona_row({"persona_id": "m", "display_name": "Mike"})
    names = [p["display_name"] for p in store.list_personas()]
    assert names == ["Alfred", "Mike", "Zebra"]


# ----------------------------------------------------------------------
# ContextStore delegators stay byte-equivalent
# ----------------------------------------------------------------------

def test_context_store_session_methods_share_session_store_state(tmp_path):
    """Writing through ContextStore must be readable via SessionStore
    directly, and vice versa."""
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    sid = cs.start_session({"entrypoint": "test"})
    cs.append_turn(sid, "user", "hello via facade")
    # Direct store sees the turn.
    rows = sqlite3.connect(cs.db_path).execute(
        "SELECT text FROM turns WHERE session_id = ?", (sid,)
    ).fetchall()
    assert ("hello via facade",) in rows

    # WorkingArtifact through facade is reachable via session_store.
    cs.save_artifact(sid, WorkingArtifact(content="via facade", scope="explicit"))
    direct = cs._session_store.get_artifact(sid)
    assert direct is not None and direct.content == "via facade"


def test_context_store_save_persona_indexes_examples(tmp_path):
    """`ContextStore.save_persona` orchestrates: SessionStore writes the
    row, MemoryStore indexes example_dialogues."""
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    cs.save_persona({
        "persona_id": "alfred",
        "display_name": "Alfred",
        "example_dialogues": "Sir, your tea is ready.",
    })
    assert cs._session_store.get_persona("alfred") is not None
    # No exception is the success criterion for the vector indexing —
    # Chroma is best-effort.


def test_context_store_append_turn_indexes_turn_text(tmp_path):
    """`ContextStore.append_turn` orchestrates: SessionStore writes the
    row + bumps sessions.updated_at; MemoryStore indexes the text."""
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    sid = cs.start_session()
    cs.append_turn(sid, "user", "I went to Tokyo for cherry blossoms")
    # The text should be reachable via semantic_recall (vector OR fallback).
    hits = cs._memory_store.semantic_recall("Tokyo", sid, limit=3)
    assert any("Tokyo" in h for h in hits)


def test_working_artifact_re_exported_from_context_store():
    """Back-compat: existing callers do
    `from core.stores import WorkingArtifact` — must still work."""
    from core.stores import (
        ARTIFACT_SCOPE_RANK as RANK,
        WorkingArtifact as CSArtifact,
        artifact_scope_rank as cs_rank,
    )
    assert RANK == ARTIFACT_SCOPE_RANK
    assert CSArtifact is WorkingArtifact
    assert cs_rank("explicit") == 3
