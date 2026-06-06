"""Track 5.1c — KnowledgeGraphStore.

Extracted from `core.context_store.ContextStore`. Owns three tables —
the typed entity graph (`entities`, `entity_facts`, `entity_relationships`).
Used by `core.memory.graph.EntityExtractor` and the knowledge-graph
querying APIs.

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
    return os.path.join(os.path.dirname(__file__), "migrations", "knowledge_graph.sql")


class KnowledgeGraphStore:
    """Entity nodes + predicate triples + edges."""

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
    # entities
    # ------------------------------------------------------------------

    def upsert_entity(self, name: str, entity_type: str = "concept",
                      properties: dict | None = None,
                      session_id: str = "") -> str:
        existing = self._find_entity_by_name(name, entity_type)
        if existing:
            return existing
        entity_id = str(uuid.uuid4())
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO entities
                   (id, entity_type, name, properties_json, session_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (entity_id, entity_type, name,
                 json.dumps(properties or {}), session_id, now, now),
            )
            conn.commit()
        return entity_id

    def _find_entity_by_name(self, name: str, entity_type: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM entities WHERE name=? AND entity_type=? LIMIT 1",
                (name, entity_type),
            ).fetchone()
            return row[0] if row else None

    def find_entities(self, name_fragment: str = "",
                      entity_type: str = "") -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            clauses, params = [], []
            if name_fragment:
                clauses.append("name LIKE ?")
                params.append(f"%{name_fragment}%")
            if entity_type:
                clauses.append("entity_type=?")
                params.append(entity_type)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM entities {where} ORDER BY name LIMIT 50",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # entity_facts (triples)
    # ------------------------------------------------------------------

    def add_entity_fact(self, subject_id: str, predicate: str, obj: str,
                        confidence: float = 0.7, source: str = "") -> str:
        fact_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO entity_facts
                   (id, subject_id, predicate, object, confidence, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (fact_id, subject_id, predicate, obj,
                 confidence, source, _utc_now()),
            )
            conn.commit()
        return fact_id

    def query_entity_facts(self, subject_id: str) -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM entity_facts WHERE subject_id=? ORDER BY confidence DESC",
                (subject_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # entity_relationships (edges)
    # ------------------------------------------------------------------

    def add_entity_relationship(self, from_id: str, to_id: str,
                                rel_type: str = "related_to",
                                properties: dict | None = None) -> str:
        rel_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO entity_relationships
                   (id, from_id, to_id, rel_type, properties_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (rel_id, from_id, to_id, rel_type,
                 json.dumps(properties or {}), _utc_now()),
            )
            conn.commit()
        return rel_id
