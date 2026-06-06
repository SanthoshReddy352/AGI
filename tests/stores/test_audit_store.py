"""Track 5.1a — focused AuditStore integration tests.

Each test uses a tmp_path SQLite file so there's no shared state and no
mocking — this is the "focused integration test" that Direction §5.1
asks for. Together they exercise every public method on AuditStore and
prove that ContextStore's delegators stay byte-equivalent to going
through AuditStore directly.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from core.stores import AuditStore


@pytest.fixture()
def store(tmp_path):
    return AuditStore(str(tmp_path / "friday.db"))


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

def test_audit_store_creates_only_its_own_tables(store):
    """AuditStore must create exactly the 4 audit-domain tables — not the
    12 other tables ContextStore owns. Track 5.1 enforces ≤4 tables per
    store; this guards against a regression that re-couples schemas.
    """
    conn = sqlite3.connect(store.db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    assert names == {
        "audit_events",
        "online_permission_events",
        "agent_messages",
        "commitments",
    }


# ----------------------------------------------------------------------
# audit_events
# ----------------------------------------------------------------------

def test_log_and_query_audit_event(store):
    store.log_audit_event(
        "open_file", True,
        args_summary="path=x.py",
        output_summary="opened",
        exec_ms=42,
        session_id="s1",
        authority_decision="allowed",
    )
    rows = store.query_audit_events(session_id="s1")
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "open_file"
    assert rows[0]["ok"] == 1
    assert rows[0]["exec_ms"] == 42
    assert rows[0]["authority_decision"] == "allowed"


def test_query_audit_events_filters_by_tool(store):
    store.log_audit_event("open_file", True, session_id="s1")
    store.log_audit_event("save_note", True, session_id="s1")
    open_rows = store.query_audit_events(tool_name="open_file")
    assert {r["tool_name"] for r in open_rows} == {"open_file"}


# ----------------------------------------------------------------------
# online_permission_events
# ----------------------------------------------------------------------

def test_log_online_permission_persists(store):
    store.log_online_permission("s1", "web_fetch", "allow", reason="user said ok")
    conn = sqlite3.connect(store.db_path)
    rows = conn.execute(
        "SELECT session_id, tool_name, decision, reason FROM online_permission_events"
    ).fetchall()
    assert rows == [("s1", "web_fetch", "allow", "user said ok")]


# ----------------------------------------------------------------------
# agent_messages
# ----------------------------------------------------------------------

def test_post_list_and_ack_agent_message(store):
    msg_id = store.post_agent_message(
        from_agent="friday",
        to_agent="user",
        msg_type="task",
        content="please confirm",
        priority="high",
        requires_response=True,
    )
    pending = store.list_agent_messages(to_agent="user")
    assert [m["id"] for m in pending] == [msg_id]
    assert pending[0]["status"] == "pending"
    assert pending[0]["requires_response"] == 1
    assert store.ack_agent_message(msg_id) is True
    assert store.list_agent_messages(to_agent="user", status="pending") == []
    acked = store.list_agent_messages(to_agent="user", status="acknowledged")
    assert [m["id"] for m in acked] == [msg_id]


def test_ack_unknown_message_returns_false(store):
    assert store.ack_agent_message("not-a-real-id") is False


# ----------------------------------------------------------------------
# commitments — full state machine
# ----------------------------------------------------------------------

def test_commitment_lifecycle(store):
    cid = store.record_commitment(
        "email mom", session_id="s1", priority="high", when_due="2026-05-20"
    )
    pending = store.list_pending_commitments(session_id="s1")
    assert [c["id"] for c in pending] == [cid]
    assert pending[0]["priority"] == "high"

    assert store.complete_commitment(cid, result="sent") is True
    assert store.get_commitment(cid)["status"] == "completed"
    assert store.get_commitment(cid)["result"] == "sent"
    assert store.list_pending_commitments(session_id="s1") == []


def test_fail_and_cancel_commitments(store):
    failed = store.record_commitment("call dentist", session_id="s1")
    cancelled = store.record_commitment("reschedule gym", session_id="s1")
    store.fail_commitment(failed, result="line busy")
    store.cancel_commitment(cancelled)
    statuses = {c["id"]: c["status"] for c in store.list_all_commitments(session_id="s1")}
    assert statuses[failed] == "failed"
    assert statuses[cancelled] == "cancelled"


def test_complete_unknown_commitment_returns_false(store):
    assert store.complete_commitment("not-a-real-id") is False


def test_list_pending_commitments_scopes_by_session(store):
    cid_s1 = store.record_commitment("a", session_id="s1")
    store.record_commitment("b", session_id="s2")
    s1_ids = {c["id"] for c in store.list_pending_commitments(session_id="s1")}
    assert s1_ids == {cid_s1}


# ----------------------------------------------------------------------
# ContextStore delegators stay byte-equivalent
# ----------------------------------------------------------------------

def test_context_store_audit_methods_share_audit_store_state(tmp_path):
    """Writing through ContextStore delegators must be readable through
    AuditStore directly (and vice versa) — they share the SQLite file
    plus the same AuditStore instance.
    """
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    cs.log_audit_event("ping", True, session_id="s1")
    direct = cs._audit_store.query_audit_events(session_id="s1")
    assert len(direct) == 1
    assert direct[0]["tool_name"] == "ping"

    cid = cs._audit_store.record_commitment("via-store", session_id="s1")
    assert cs.get_commitment(cid)["what"] == "via-store"
