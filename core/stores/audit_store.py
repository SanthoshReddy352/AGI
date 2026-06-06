"""Track 5.1a — AuditStore.

Extracted from `core.context_store.ContextStore`. Owns the four
"things that happened or are pending" tables (see `migrations/audit.sql`):

    audit_events, online_permission_events, agent_messages, commitments

Every method here is intentionally ≤30 lines (Direction §5.1 rule).

ContextStore now delegates its audit-domain methods into an instance
of this store, sharing the same SQLite file. That keeps the ~22
existing callers working without a sweep while we extract the other
three stores; a future track will remove ContextStore entirely.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "audit.sql")


class AuditStore:
    """Audit, permission, agent-message, and commitment persistence.

    Shares the FRIDAY SQLite file with the other domain stores so
    cross-domain transactions remain possible, but the four tables
    listed in `migrations/audit.sql` are owned exclusively here.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
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
    # audit_events
    # ------------------------------------------------------------------

    def log_audit_event(
        self,
        tool_name: str,
        ok: bool,
        args_summary: str = "",
        output_summary: str = "",
        exec_ms: int = 0,
        session_id: str = "",
        agent_id: str = "friday",
        authority_decision: str = "allowed",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO audit_events
                   (tool_name, ok, args_summary, output_summary, exec_ms,
                    session_id, agent_id, authority_decision, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tool_name, int(ok), str(args_summary)[:500],
                 str(output_summary)[:500], int(exec_ms),
                 session_id, agent_id, authority_decision, _utc_now()),
            )
            conn.commit()

    def query_audit_events(
        self, tool_name: str = "", limit: int = 50, session_id: str = ""
    ) -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            clauses, params = [], []
            if tool_name:
                clauses.append("tool_name=?")
                params.append(tool_name)
            if session_id:
                clauses.append("session_id=?")
                params.append(session_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM audit_events {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # online_permission_events
    # ------------------------------------------------------------------

    def log_online_permission(
        self, session_id: str, tool_name: str, decision: str, reason: str = ""
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO online_permission_events
                   (session_id, tool_name, decision, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id or "", tool_name or "",
                 decision or "", reason or "", _utc_now()),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # agent_messages
    # ------------------------------------------------------------------

    def post_agent_message(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: str,
        content: str,
        priority: str = "normal",
        requires_response: bool = False,
        deadline: str = "",
    ) -> str:
        msg_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO agent_messages
                   (id, from_agent, to_agent, msg_type, content, priority,
                    requires_response, deadline, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (msg_id, from_agent, to_agent, msg_type, content, priority,
                 int(requires_response), deadline, _utc_now()),
            )
            conn.commit()
        return msg_id

    def list_agent_messages(self, to_agent: str = "", status: str = "pending") -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            clauses, params = ["status=?"], [status]
            if to_agent:
                clauses.append("to_agent=?")
                params.append(to_agent)
            where = "WHERE " + " AND ".join(clauses)
            rows = conn.execute(
                f"SELECT * FROM agent_messages {where} ORDER BY priority DESC, created_at ASC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def ack_agent_message(self, msg_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE agent_messages SET status='acknowledged' WHERE id=?",
                (msg_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # commitments
    # ------------------------------------------------------------------

    def record_commitment(
        self,
        what: str,
        session_id: str = "",
        when_due: str = "",
        priority: str = "medium",
        retry_policy: str = "none",
        assigned_to: str = "friday",
    ) -> str:
        commitment_id = str(uuid.uuid4())
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO commitments
                   (id, session_id, what, when_due, priority, status,
                    retry_policy, assigned_to, result, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, '', ?, ?)""",
                (commitment_id, session_id, what, when_due, priority,
                 retry_policy, assigned_to, now, now),
            )
            conn.commit()
        return commitment_id

    def complete_commitment(self, commitment_id: str, result: str = "") -> bool:
        return self._update_commitment_status(commitment_id, "completed", result)

    def fail_commitment(self, commitment_id: str, result: str = "") -> bool:
        return self._update_commitment_status(commitment_id, "failed", result)

    def cancel_commitment(self, commitment_id: str) -> bool:
        return self._update_commitment_status(commitment_id, "cancelled")

    def _update_commitment_status(
        self, cid: str, status: str, result: str = ""
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE commitments SET status=?, result=?, updated_at=? WHERE id=?",
                (status, result, _utc_now(), cid),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_pending_commitments(self, session_id: str = "", limit: int = 20) -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if session_id:
                rows = conn.execute(
                    """SELECT * FROM commitments WHERE status='pending' AND session_id=?
                       ORDER BY priority DESC, created_at ASC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM commitments WHERE status='pending'
                       ORDER BY priority DESC, created_at ASC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def list_all_commitments(self, session_id: str = "", limit: int = 50) -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM commitments WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM commitments ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_commitment(self, commitment_id: str) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM commitments WHERE id=?", (commitment_id,)
            ).fetchone()
            return dict(row) if row else None
