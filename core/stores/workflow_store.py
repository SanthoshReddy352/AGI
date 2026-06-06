"""Track 5.1b — WorkflowStore.

Extracted from `core.context_store.ContextStore`. Owns one table — the
multi-turn workflow state machine (`workflows`) that drives
calendar_event / file / dictation continuations across turn boundaries
and FRIDAY restarts.

Every method here is ≤30 lines (Direction §5.1 rule). The session
table's `updated_at` bump and the memory-item upsert that
`ContextStore.save_workflow_state` also performed remain in ContextStore
as the orchestrating caller — they cross store boundaries (session +
memory), so WorkflowStore stays single-responsibility.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from core.logger import logger


# Workflow rows older than this auto-expire. Prevents stale calendar /
# file workflows from surviving a FRIDAY restart and resurrecting
# half-finished multi-turn flows.
WORKFLOW_TTL_HOURS = 24


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _is_workflow_expired(updated_at, ttl_hours=WORKFLOW_TTL_HOURS) -> bool:
    parsed = _parse_iso_utc(updated_at)
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed
    return age.total_seconds() > ttl_hours * 3600


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "workflow.sql")


class WorkflowStore:
    """Workflow row CRUD + auto-expiry.

    Shares the FRIDAY SQLite file with the other domain stores; the
    `workflows` table is owned exclusively here (see
    `migrations/workflow.sql`).
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_storage()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_storage(self) -> None:
        _db_dir = os.path.dirname(self.db_path)
        if _db_dir:
            os.makedirs(_db_dir, exist_ok=True)
        with open(_migrations_path(), "r", encoding="utf-8") as fh:
            schema_sql = fh.read()
        with self._connect() as conn:
            conn.executescript(schema_sql)
            conn.commit()

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    def get_active(self, session_id: str, workflow_name: str | None = None):
        if not session_id:
            return None
        row = self._fetch_active_row(session_id, workflow_name)
        if not row:
            return None
        # Auto-expire stale rows: treat as no active workflow and mark
        # the row completed in-place so it stops shadowing future queries.
        if _is_workflow_expired(row[7]):
            try:
                self.mark_expired(session_id, row[0])
            except Exception as e:
                logger.warning("[workflow_store] mark_expired failed: %s", e)
            return None
        return self._row_to_workflow(row)

    def _fetch_active_row(self, session_id: str, workflow_name: str | None):
        query = (
            "SELECT workflow_name, status, pending_slots_json, last_action, "
            "target_json, result_summary, state_json, updated_at "
            "FROM workflows WHERE session_id = ? AND status IN ('active', 'pending')"
        )
        params: list = [session_id]
        if workflow_name:
            query += " AND workflow_name = ?"
            params.append(workflow_name)
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self._connect() as conn:
            return conn.execute(query, tuple(params)).fetchone()

    def get_summary(self, session_id: str) -> str:
        active = self.get_active(session_id)
        if not active:
            return ""
        pending = ", ".join(active.get("pending_slots") or [])
        summary = active.get("result_summary") or ""
        if pending:
            summary = f"{summary} Pending: {pending}.".strip()
        return f"{active['workflow_name']}: {summary}".strip()

    @staticmethod
    def _row_to_workflow(row) -> dict:
        (workflow_name, status, pending_slots_json, last_action,
         target_json, result_summary, state_json, updated_at) = row
        state = json.loads(state_json or "{}")
        state.setdefault("workflow_name", workflow_name)
        state.setdefault("status", status)
        state.setdefault("pending_slots", json.loads(pending_slots_json or "[]"))
        state.setdefault("last_action", last_action or "")
        state.setdefault("target", json.loads(target_json or "{}"))
        state.setdefault("result_summary", result_summary or "")
        state.setdefault("updated_at", updated_at)
        return state

    # ------------------------------------------------------------------
    # Write paths
    # ------------------------------------------------------------------

    def upsert(self, session_id: str, workflow_name: str, state: dict) -> str:
        """Insert or update a workflow row. Returns the ISO timestamp written.

        Callers (ContextStore.save_workflow_state) are responsible for
        the cross-domain side effects: bumping `sessions.updated_at` and
        upserting the memory-item summary.
        """
        if not session_id or not workflow_name:
            return ""
        state = dict(state or {})
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows (
                    session_id, workflow_name, status, pending_slots_json,
                    last_action, target_json, result_summary, state_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, workflow_name)
                DO UPDATE SET
                    status = excluded.status,
                    pending_slots_json = excluded.pending_slots_json,
                    last_action = excluded.last_action,
                    target_json = excluded.target_json,
                    result_summary = excluded.result_summary,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    workflow_name,
                    str(state.get("status") or "active"),
                    json.dumps(list(state.get("pending_slots") or []), ensure_ascii=True),
                    str(state.get("last_action") or ""),
                    json.dumps(state.get("target") or {}, ensure_ascii=True),
                    str(state.get("result_summary") or ""),
                    json.dumps(state, ensure_ascii=True),
                    now,
                ),
            )
            conn.commit()
        return now

    def mark_expired(self, session_id: str, workflow_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE workflows SET status = 'expired', updated_at = ? "
                "WHERE session_id = ? AND workflow_name = ?",
                (_utc_now(), session_id, workflow_name),
            )
            conn.commit()

    def expire_all_for_session(self, session_id: str) -> int:
        """Expire EVERY active workflow row for *session_id*. Returns the
        number of rows affected.

        Used by `/new` and `/clear` so a pending workflow (research
        planner waiting on a readout reply, browser-media flow waiting
        on a query, …) from the outgoing session can't intercept the
        first message of the new conversation. The 2026-05-24 07:30 bug
        was the canonical example: a `research_planner` row stuck at
        `awaiting_readout` made "Bye" trigger a 1-paragraph readout
        instead of `shutdown_assistant`.
        """
        if not session_id:
            return 0
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE workflows SET status = 'expired', updated_at = ? "
                "WHERE session_id = ? AND status = 'active'",
                (_utc_now(), session_id),
            )
            conn.commit()
            return cur.rowcount or 0
