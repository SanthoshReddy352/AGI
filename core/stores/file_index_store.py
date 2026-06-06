"""Track 6.2 — FileIndexStore.

One-table persistence for the background filesystem indexer
(`modules/system_control/file_indexer.py`). Holds (path, name,
parent_dir, ext, size, mtime, indexed_at) for every file the indexer
has seen, scoped to the user's roots (Documents, Downloads, Desktop,
external mounts) — not the full filesystem.

Search is `LIKE`-based for the first cut; FTS5 is a follow-up if name
hits prove too coarse. The store is the only place that writes the
table.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "file_index.sql")


class FileIndexStore:
    """Path index used by the background FileIndexer."""

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

    def upsert_file(
        self,
        path: str,
        name: str = "",
        parent_dir: str = "",
        ext: str = "",
        size: int = 0,
        mtime: float = 0.0,
    ) -> None:
        if not path:
            return
        name = name or os.path.basename(path)
        parent_dir = parent_dir or os.path.dirname(path)
        if not ext:
            _, raw_ext = os.path.splitext(name)
            ext = raw_ext.lstrip(".").lower()
        params = (path, name, parent_dir, ext, int(size or 0), float(mtime or 0.0), _utc_now())
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO file_index (path, name, parent_dir, ext, size, mtime, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "name=excluded.name, parent_dir=excluded.parent_dir, ext=excluded.ext, "
                "size=excluded.size, mtime=excluded.mtime, indexed_at=excluded.indexed_at",
                params,
            )
            conn.commit()

    # Commit the bulk index in batches of this size rather than one giant
    # transaction. The indexer shares friday.db with the turn/audit stores, so
    # a single 200k-row commit holds the SQLite write lock for seconds and
    # stalls every turn's DB write behind it (the 2026-05-29 inter-message
    # latency). Chunking releases the lock between batches so interactive
    # writes interleave.
    _UPSERT_BATCH = 2000

    _UPSERT_SQL = (
        "INSERT INTO file_index (path, name, parent_dir, ext, size, mtime, indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "name=excluded.name, parent_dir=excluded.parent_dir, ext=excluded.ext, "
        "size=excluded.size, mtime=excluded.mtime, indexed_at=excluded.indexed_at"
    )

    def bulk_upsert(self, rows: Iterable[dict]) -> int:
        stamp = _utc_now()
        count = 0
        batch: list[tuple] = []
        for row in rows:
            path = row.get("path", "")
            if not path:
                continue
            name = row.get("name") or os.path.basename(path)
            parent_dir = row.get("parent_dir") or os.path.dirname(path)
            ext = row.get("ext")
            if not ext:
                _, raw_ext = os.path.splitext(name)
                ext = raw_ext.lstrip(".").lower()
            batch.append((
                path, name, parent_dir, ext,
                int(row.get("size") or 0),
                float(row.get("mtime") or 0.0),
                stamp,
            ))
            count += 1
            if len(batch) >= self._UPSERT_BATCH:
                self._flush_batch(batch)
                batch = []
        if batch:
            self._flush_batch(batch)
        return count

    def _flush_batch(self, payload: list[tuple]) -> None:
        """Commit one batch in its own short transaction, then release the
        write lock so other writers (turn/audit stores on the same DB) run."""
        if not payload:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(self._UPSERT_SQL, payload)
            conn.commit()

    def delete_path(self, path: str) -> None:
        if not path:
            return
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM file_index WHERE path = ?", (path,))
            conn.commit()

    def delete_under(self, parent_dir: str) -> int:
        """Remove every row whose path starts with *parent_dir*.

        Used by the indexer when a directory disappears so the index
        doesn't accumulate ghost entries for deleted trees.
        """
        if not parent_dir:
            return 0
        prefix = parent_dir.rstrip(os.sep) + os.sep
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM file_index WHERE path = ? OR path LIKE ?",
                (parent_dir, prefix + "%"),
            )
            conn.commit()
            return cur.rowcount or 0

    def search(self, query: str, limit: int = 20, ext: str = "") -> list[dict]:
        if not query:
            return []
        needle = f"%{query.strip().lower()}%"
        sql = (
            "SELECT path, name, parent_dir, ext, size, mtime, indexed_at "
            "FROM file_index WHERE lower(name) LIKE ?"
        )
        params: list = [needle]
        if ext:
            sql += " AND ext = ?"
            params.append(ext.lstrip(".").lower())
        sql += " ORDER BY mtime DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            cur = conn.execute(sql, tuple(params))
            return [self._row_to_dict(row) for row in cur.fetchall()]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM file_index").fetchone()[0]

    def last_indexed_at(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(indexed_at) FROM file_index").fetchone()
            return row[0] if row and row[0] else None

    def clear_all(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM file_index")
            conn.commit()

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        path, name, parent_dir, ext, size, mtime, indexed_at = row
        return {
            "path": path,
            "name": name,
            "parent_dir": parent_dir,
            "ext": ext,
            "size": size,
            "mtime": mtime,
            "indexed_at": indexed_at,
        }
