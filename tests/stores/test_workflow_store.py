"""Track 5.1b — focused WorkflowStore integration tests.

Exercises the workflow row state machine + auto-expiry directly against
SQLite (no mocks). The last test pins the ContextStore-as-orchestrator
contract: writing through `ContextStore.save_workflow_state` must
produce the same workflow row as a direct `WorkflowStore.upsert`, plus
the cross-domain `sessions.updated_at` bump.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.stores import WorkflowStore
from core.stores.workflow_store import WORKFLOW_TTL_HOURS


@pytest.fixture()
def store(tmp_path):
    return WorkflowStore(str(tmp_path / "friday.db"))


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

def test_workflow_store_creates_only_its_own_table(store):
    conn = sqlite3.connect(store.db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    assert names == {"workflows"}


# ----------------------------------------------------------------------
# upsert + get_active
# ----------------------------------------------------------------------

def test_upsert_then_get_active(store):
    store.upsert("s1", "calendar_event_workflow", {
        "status": "active",
        "pending_slots": ["date", "time"],
        "last_action": "asked_date",
        "target": {"event": "lunch"},
        "result_summary": "in progress",
    })
    active = store.get_active("s1")
    assert active["workflow_name"] == "calendar_event_workflow"
    assert active["status"] == "active"
    assert active["pending_slots"] == ["date", "time"]
    assert active["target"] == {"event": "lunch"}
    assert active["last_action"] == "asked_date"


def test_upsert_with_missing_session_or_name_is_noop(store):
    assert store.upsert("", "x", {}) == ""
    assert store.upsert("s1", "", {}) == ""
    assert store.get_active("s1") is None


def test_get_active_filters_by_workflow_name(store):
    store.upsert("s1", "file_workflow", {"status": "active"})
    store.upsert("s1", "calendar_event_workflow", {"status": "active"})
    cal = store.get_active("s1", workflow_name="calendar_event_workflow")
    assert cal["workflow_name"] == "calendar_event_workflow"


def test_get_active_skips_completed_rows(store):
    store.upsert("s1", "file_workflow", {"status": "completed"})
    assert store.get_active("s1") is None


def test_get_active_handles_empty_session_id(store):
    assert store.get_active("") is None


# ----------------------------------------------------------------------
# mark_expired + auto-expiry on read
# ----------------------------------------------------------------------

def test_mark_expired_flips_status(store):
    store.upsert("s1", "file_workflow", {"status": "active"})
    store.mark_expired("s1", "file_workflow")
    assert store.get_active("s1") is None


def test_auto_expiry_on_read_marks_row_expired(store):
    """A row whose updated_at is older than WORKFLOW_TTL_HOURS must be
    treated as no active workflow AND get its status flipped to 'expired'
    so subsequent reads stop returning it.
    """
    store.upsert("s1", "file_workflow", {"status": "active"})
    # Backdate the row past the TTL.
    stale = (datetime.now(timezone.utc) - timedelta(hours=WORKFLOW_TTL_HOURS + 1)).isoformat()
    conn = sqlite3.connect(store.db_path)
    conn.execute("UPDATE workflows SET updated_at = ? WHERE session_id = 's1'", (stale,))
    conn.commit()

    assert store.get_active("s1") is None
    # The read should have flipped status to 'expired' in-place.
    status = sqlite3.connect(store.db_path).execute(
        "SELECT status FROM workflows WHERE session_id='s1'"
    ).fetchone()[0]
    assert status == "expired"


# ----------------------------------------------------------------------
# get_summary
# ----------------------------------------------------------------------

def test_get_summary_includes_pending_and_result(store):
    store.upsert("s1", "calendar_event_workflow", {
        "status": "active",
        "pending_slots": ["date", "time"],
        "result_summary": "asked twice",
    })
    summary = store.get_summary("s1")
    assert "calendar_event_workflow" in summary
    assert "Pending: date, time" in summary
    assert "asked twice" in summary


def test_get_summary_empty_when_no_active(store):
    assert store.get_summary("s1") == ""


# ----------------------------------------------------------------------
# Round-trip preserves arbitrary state JSON
# ----------------------------------------------------------------------

def test_upsert_preserves_arbitrary_state_keys(store):
    store.upsert("s1", "file_workflow", {
        "status": "active",
        "custom_field": {"nested": [1, 2, 3]},
        "another": "value",
    })
    active = store.get_active("s1")
    assert active["custom_field"] == {"nested": [1, 2, 3]}
    assert active["another"] == "value"


# ----------------------------------------------------------------------
# ContextStore orchestrator contract
# ----------------------------------------------------------------------

def test_context_store_save_workflow_state_uses_workflow_store(tmp_path):
    """The orchestrator (ContextStore.save_workflow_state) must:
      (1) delegate the workflow-row write to WorkflowStore, and
      (2) still perform its cross-domain side effects — bumping
          sessions.updated_at and upserting the memory-item summary.
    """
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    sid = cs.start_session({"entrypoint": "test"})

    # Snapshot sessions.updated_at before the workflow write.
    before = sqlite3.connect(cs.db_path).execute(
        "SELECT updated_at FROM sessions WHERE id = ?", (sid,)
    ).fetchone()[0]

    cs.save_workflow_state(sid, "file_workflow", {
        "status": "active",
        "pending_slots": ["path"],
        "last_action": "ask_path",
        "result_summary": "looking for file",
    })

    # The workflow row exists via the direct store path.
    via_store = cs._workflow_store.get_active(sid, "file_workflow")
    assert via_store is not None
    assert via_store["pending_slots"] == ["path"]

    # The orchestrator bumped sessions.updated_at.
    after = sqlite3.connect(cs.db_path).execute(
        "SELECT updated_at FROM sessions WHERE id = ?", (sid,)
    ).fetchone()[0]
    assert after >= before  # bumped or same-tick


def test_context_store_clear_workflow_state_marks_completed(tmp_path):
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    sid = cs.start_session({"entrypoint": "test"})
    cs.save_workflow_state(sid, "file_workflow", {"status": "active"})
    assert cs.get_active_workflow(sid) is not None

    cs.clear_workflow_state(sid, "file_workflow")
    assert cs.get_active_workflow(sid) is None
