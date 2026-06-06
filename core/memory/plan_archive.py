"""Procedural plan archive — user-approved successful workflows.

When a workflow finishes successfully under user approval, we persist a
compact record (request → chosen workflow + slot pattern → outcome) plus
a vector embedding of the original user request. Future turns can then
retrieve similar prior runs and inject them as few-shot exemplars into
the Qwen planner prompts, dramatically improving small-model consistency.

Storage: a single ``plan_archive`` table inside the existing
``data/friday.db`` SQLite file. The table is created lazily on first
``save()`` so the archive is opt-in — turning it off costs nothing on
disk beyond the empty table itself.

Embedding: reuses :func:`core.memory.embeddings.get_best_embedder` so the
archive shares whichever model the semantic store is using (BGE small if
sentence-transformers is installed, hash fallback otherwise). All
embeddings are unit-normalized so cosine similarity == dot product.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from typing import Any

from core.logger import logger
from core.memory.embeddings import EmbedderProtocol, get_best_embedder


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _floats_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_floats(blob: bytes) -> list[float]:
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(v * v for v in vec))
    if n == 0:
        return list(vec)
    return [v / n for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two normalized vectors == dot product."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class PlanRecord:
    """Public-facing record of an archived plan run."""
    id: int = 0
    created_at: str = ""
    user_id: str = ""
    session_id: str = ""
    user_text: str = ""
    workflow_name: str = ""
    slot_values: dict = field(default_factory=dict)
    plan_shape: list[str] = field(default_factory=list)
    outcome: str = ""
    user_approved: bool = False
    score: float = 0.0          # similarity score (set by retrieve_similar)

    def to_exemplar(self) -> dict[str, Any]:
        """Compact dict for prompt injection."""
        return {
            "task": self.user_text[:200],
            "workflow": self.workflow_name,
            "filled_slots": dict(self.slot_values),
            "plan_shape": list(self.plan_shape),
            "outcome": self.outcome,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plan_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    user_text TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    slot_values_json TEXT NOT NULL DEFAULT '{}',
    plan_shape_json TEXT NOT NULL DEFAULT '[]',
    outcome TEXT NOT NULL,
    user_approved INTEGER NOT NULL DEFAULT 0,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_plan_archive_workflow_outcome
    ON plan_archive (workflow_name, outcome, user_approved);
"""


# ---------------------------------------------------------------------------
# PlanArchive
# ---------------------------------------------------------------------------


class PlanArchive:
    """Append-only, retrieve-by-similarity store for approved plans.

    Thread-safe (SQLite + a per-instance lock for the embedder).
    """

    def __init__(
        self,
        db_path: str,
        *,
        embedder: EmbedderProtocol | None = None,
    ):
        self.db_path = db_path
        self._embedder = embedder
        self._embedder_lock = threading.Lock()
        self._schema_ready = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        *,
        user_text: str,
        workflow_name: str,
        slot_values: dict | None = None,
        plan_shape: list[str] | None = None,
        outcome: str = "success",
        user_approved: bool = True,
        user_id: str = "",
        session_id: str = "",
    ) -> int:
        """Insert a plan record. Returns the row id.

        Records with ``outcome != "success"`` or ``user_approved=False`` are
        still stored but won't be returned by :meth:`retrieve_similar` —
        only validated, user-blessed runs become few-shot fodder.
        """
        text = (user_text or "").strip()
        if not text or not workflow_name:
            return 0

        self._ensure_schema()
        embedding = self._embed(text)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO plan_archive (
                    created_at, user_id, session_id, user_text,
                    workflow_name, slot_values_json, plan_shape_json,
                    outcome, user_approved, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now(),
                    str(user_id or ""),
                    str(session_id or ""),
                    text,
                    str(workflow_name),
                    json.dumps(slot_values or {}, ensure_ascii=False),
                    json.dumps(plan_shape or [], ensure_ascii=False),
                    str(outcome or "success"),
                    1 if user_approved else 0,
                    _floats_to_blob(embedding) if embedding else None,
                ),
            )
            return int(cursor.lastrowid or 0)

    def retrieve_similar(
        self,
        user_text: str,
        *,
        top_k: int = 3,
        workflow_name: str | None = None,
        only_successful: bool = True,
        only_approved: bool = True,
    ) -> list[PlanRecord]:
        """Return up to *top_k* records most similar to *user_text*.

        Filters by ``outcome == 'success'`` and ``user_approved=True`` by
        default. The similarity score is cosine distance over the
        request embedding; records with a missing/dimension-mismatched
        embedding are still returned but at the bottom (score 0.0).
        """
        text = (user_text or "").strip()
        if not text:
            return []
        if not os.path.exists(self.db_path):
            return []

        self._ensure_schema()
        query_vec = self._embed(text)

        clauses: list[str] = []
        params: list[Any] = []
        if only_successful:
            clauses.append("outcome = 'success'")
        if only_approved:
            clauses.append("user_approved = 1")
        if workflow_name:
            clauses.append("workflow_name = ?")
            params.append(workflow_name)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        rows: list[PlanRecord] = []
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                SELECT id, created_at, user_id, session_id, user_text,
                       workflow_name, slot_values_json, plan_shape_json,
                       outcome, user_approved, embedding
                FROM plan_archive {where}
                """,
                tuple(params),
            )
            for r in cur.fetchall():
                emb = _blob_to_floats(r[10] or b"")
                score = _cosine(query_vec, emb) if query_vec and emb else 0.0
                rows.append(PlanRecord(
                    id=int(r[0]),
                    created_at=str(r[1] or ""),
                    user_id=str(r[2] or ""),
                    session_id=str(r[3] or ""),
                    user_text=str(r[4] or ""),
                    workflow_name=str(r[5] or ""),
                    slot_values=json.loads(r[6] or "{}"),
                    plan_shape=json.loads(r[7] or "[]"),
                    outcome=str(r[8] or ""),
                    user_approved=bool(r[9]),
                    score=float(score),
                ))

        rows.sort(key=lambda r: (-r.score, -r.id))
        return rows[:max(0, int(top_k))]

    def all(self) -> list[PlanRecord]:
        """Return every stored record (for diagnostics / tests). Includes
        non-approved and non-successful runs."""
        if not os.path.exists(self.db_path):
            return []
        self._ensure_schema()
        out: list[PlanRecord] = []
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, created_at, user_id, session_id, user_text,
                       workflow_name, slot_values_json, plan_shape_json,
                       outcome, user_approved
                FROM plan_archive ORDER BY id DESC
                """
            )
            for r in cur.fetchall():
                out.append(PlanRecord(
                    id=int(r[0]),
                    created_at=str(r[1] or ""),
                    user_id=str(r[2] or ""),
                    session_id=str(r[3] or ""),
                    user_text=str(r[4] or ""),
                    workflow_name=str(r[5] or ""),
                    slot_values=json.loads(r[6] or "{}"),
                    plan_shape=json.loads(r[7] or "[]"),
                    outcome=str(r[8] or ""),
                    user_approved=bool(r[9]),
                ))
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
        self._schema_ready = True

    def _embed(self, text: str) -> list[float]:
        with self._embedder_lock:
            if self._embedder is None:
                try:
                    self._embedder = get_best_embedder()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("[plan_archive] embedder unavailable: %s", exc)
                    return []
            try:
                vectors = self._embedder.embed([text])
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("[plan_archive] embed failed: %s", exc)
                return []
        if not vectors:
            return []
        return _normalize(list(vectors[0]))
