"""Track 6.1 — AppIndexStore.

Persists the application discovery output from `SystemCapabilities` so
the assistant doesn't pay the `.desktop` / Start-Menu / Registry walk
cost on every boot.

Owns one table — `app_index` — keyed on the canonical lowercase name.
The store is the persistence layer; the in-memory cache in
`SystemCapabilities.desktop_apps` remains authoritative during a run.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "app_index.sql")


class AppIndexStore:
    """Persistence for discovered desktop applications.

    Shares the FRIDAY SQLite file with the other domain stores. Owns
    exactly one table (`app_index`) per the Track 5.1 ≤4-tables rule.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._ensure_storage()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_storage(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with open(_migrations_path(), "r", encoding="utf-8") as fh:
            schema_sql = fh.read()
        with self._connect() as conn:
            conn.executescript(schema_sql)
            conn.commit()

    def upsert_app(
        self,
        canonical: str,
        name: str,
        command: str,
        exec_line: str = "",
        desktop_id: str = "",
        source: str = "desktop",
        aliases: Iterable[str] = (),
        categories: Iterable[str] = (),
    ) -> None:
        if not canonical or not command:
            return
        params = (
            canonical,
            name or canonical,
            command,
            exec_line,
            desktop_id,
            source,
            json.dumps(sorted({a for a in aliases if a})),
            json.dumps(sorted({c for c in categories if c})),
            _utc_now(),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO app_index "
                "(canonical, name, command, exec_line, desktop_id, source, aliases_json, categories_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(canonical) DO UPDATE SET "
                "name=excluded.name, command=excluded.command, exec_line=excluded.exec_line, "
                "desktop_id=excluded.desktop_id, source=excluded.source, "
                "aliases_json=excluded.aliases_json, categories_json=excluded.categories_json, "
                "updated_at=excluded.updated_at",
                params,
            )
            conn.commit()

    def bulk_upsert(self, rows: Iterable[dict]) -> int:
        count = 0
        for row in rows:
            self.upsert_app(
                canonical=row.get("canonical", ""),
                name=row.get("name", ""),
                command=row.get("command", ""),
                exec_line=row.get("exec_line", ""),
                desktop_id=row.get("desktop_id", ""),
                source=row.get("source", "desktop"),
                aliases=row.get("aliases", ()),
                categories=row.get("categories", ()),
            )
            count += 1
        return count

    def list_apps(self) -> list[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT canonical, name, command, exec_line, desktop_id, source, "
                "aliases_json, categories_json, updated_at FROM app_index ORDER BY canonical"
            )
            return [self._row_to_dict(row) for row in cur.fetchall()]

    def find_by_alias(self, alias: str) -> dict | None:
        if not alias:
            return None
        needle = alias.strip().lower()
        for entry in self.list_apps():
            if entry["canonical"] == needle or needle in entry["aliases"]:
                return entry
        return None

    def find_by_category(self, category: str) -> list[dict]:
        if not category:
            return []
        needle = category.strip().lower()
        return [e for e in self.list_apps() if needle in {c.lower() for c in e["categories"]}]

    def clear_all(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM app_index")
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM app_index")
            return cur.fetchone()[0]

    def last_refresh_at(self) -> str | None:
        with self._connect() as conn:
            cur = conn.execute("SELECT MAX(updated_at) FROM app_index")
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def is_stale(self, max_age_hours: int = 24) -> bool:
        last = self.last_refresh_at()
        if not last:
            return True
        try:
            stamp = datetime.fromisoformat(last)
        except ValueError:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp < cutoff

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        canonical, name, command, exec_line, desktop_id, source, aliases_json, categories_json, updated_at = row
        return {
            "canonical": canonical,
            "name": name,
            "command": command,
            "exec_line": exec_line,
            "desktop_id": desktop_id,
            "source": source,
            "aliases": json.loads(aliases_json or "[]"),
            "categories": json.loads(categories_json or "[]"),
            "updated_at": updated_at,
        }
