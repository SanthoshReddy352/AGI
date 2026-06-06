"""Track 5.1c — GoalStore.

Extracted from `core.context_store.ContextStore`. Owns two tables —
`goals` and `goal_progress` (the append-only score-change log).

Every method here is ≤30 lines (Direction §5.1 rule).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "goal.sql")


def _health_for_score(score: float) -> str:
    if score >= 0.7:
        return "on_track"
    if score >= 0.4:
        return "at_risk"
    return "behind"


class GoalStore:
    """Goal + goal_progress persistence."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_storage()

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
    # goals
    # ------------------------------------------------------------------

    def create_goal(self, title: str, description: str = "",
                    level: str = "task", parent_id: str = "",
                    time_horizon: str = "weekly",
                    tags: list | None = None,
                    session_id: str = "") -> str:
        goal_id = str(uuid.uuid4())
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO goals
                   (id, session_id, title, description, level, parent_id,
                    score, status, health, time_horizon, escalation_stage,
                    tags_json, estimated_hours, actual_hours, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0.0, 'active', 'on_track', ?, 'none', ?, 0.0, 0.0, ?, ?)""",
                (goal_id, session_id, title, description, level, parent_id,
                 time_horizon, json.dumps(tags or []), now, now),
            )
            conn.commit()
        return goal_id

    def update_goal_score(self, goal_id: str, score: float,
                          note: str = "") -> bool:
        now = _utc_now()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT score FROM goals WHERE id=?", (goal_id,)
            ).fetchone()
            if not row:
                return False
            old_score = row["score"]
            conn.execute(
                "UPDATE goals SET score=?, health=?, updated_at=? WHERE id=?",
                (score, _health_for_score(score), now, goal_id),
            )
            conn.execute(
                """INSERT INTO goal_progress (goal_id, score_before, score_after, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (goal_id, old_score, score, note, now),
            )
            conn.commit()
            return True

    def update_goal_status(self, goal_id: str, status: str) -> bool:
        now = _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE goals SET status=?, updated_at=? WHERE id=?",
                (status, now, goal_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_goals(self, session_id: str = "",
                   status: str = "active") -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            clauses, params = ["status=?"], [status]
            if session_id:
                clauses.append("session_id=?")
                params.append(session_id)
            where = "WHERE " + " AND ".join(clauses)
            rows = conn.execute(
                f"SELECT * FROM goals {where} ORDER BY level, created_at",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_goal(self, goal_id: str) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM goals WHERE id=?", (goal_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_goal(self, goal_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM goal_progress WHERE goal_id=?", (goal_id,))
            cur = conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
            conn.commit()
            return cur.rowcount > 0
