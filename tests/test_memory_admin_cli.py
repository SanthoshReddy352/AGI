"""P2.1 — memory_admin CLI: inspect, list, show, delete, wipe, export."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import types

import pytest

# Ensure project root is importable
_ROOT = os.path.dirname(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture()
def tmp_db(tmp_path):
    """Minimal in-memory DB with the facts and memory_items tables."""
    db_path = str(tmp_path / "test_friday.db")
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT DEFAULT 'general',
                key TEXT NOT NULL,
                value TEXT,
                session_id TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                session_id TEXT DEFAULT '',
                persona_id TEXT DEFAULT '',
                memory_type TEXT DEFAULT 'episodic',
                sensitivity TEXT DEFAULT 'safe_auto',
                content TEXT,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS entities (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                name TEXT,
                entity_type TEXT DEFAULT 'concept'
            );
            CREATE TABLE IF NOT EXISTS entity_facts (entity_id TEXT, predicate TEXT, object TEXT);
            CREATE TABLE IF NOT EXISTS entity_relationships (from_id TEXT, to_id TEXT, rel_type TEXT);
            CREATE TABLE IF NOT EXISTS goals (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id TEXT NOT NULL,
                title TEXT,
                status TEXT DEFAULT 'active',
                health_score REAL DEFAULT 0.0,
                updated_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS goal_progress (goal_id TEXT, score REAL);
            CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS turns (turn_id TEXT, session_id TEXT, role TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS conversation_sessions (id TEXT);
            CREATE TABLE IF NOT EXISTS personas (persona_id TEXT);
            CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, content TEXT);
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT,
                ok INTEGER,
                args_summary TEXT,
                session_id TEXT,
                created_at TEXT
            );
        """)
        conn.executemany(
            "INSERT INTO facts (namespace, key, value, updated_at) VALUES (?, ?, ?, ?)",
            [
                ("user_profile", "name", "Santhosh", "2026-05-22T10:00:00"),
                ("general", "loves", "cars", "2026-05-22T10:01:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO memory_items (item_id, content, memory_type, updated_at) VALUES (?, ?, ?, ?)",
            [("item-001", "User mentioned cars", "episodic", "2026-05-22T10:01:00")],
        )
        conn.commit()
    return db_path


@pytest.fixture()
def no_chroma_path(tmp_path):
    return str(tmp_path / "chroma")


def _ns(db, chroma):
    """Build a minimal argparse-like namespace for the CLI."""
    return types.SimpleNamespace(db=db, chroma=chroma)


def test_inspect_runs(tmp_db, no_chroma_path, capsys):
    from scripts.memory_admin import cmd_inspect
    args = _ns(tmp_db, no_chroma_path)
    cmd_inspect(args)
    out = capsys.readouterr().out
    assert "facts" in out
    assert "memory_items" in out


def test_list_facts(tmp_db, no_chroma_path, capsys):
    from scripts.memory_admin import cmd_list
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, namespace=None, type="facts")
    cmd_list(args)
    out = capsys.readouterr().out
    assert "Santhosh" in out
    assert "user_profile" in out


def test_list_facts_namespace_filter(tmp_db, no_chroma_path, capsys):
    from scripts.memory_admin import cmd_list
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, namespace="user_profile", type="facts")
    cmd_list(args)
    out = capsys.readouterr().out
    assert "Santhosh" in out
    assert "cars" not in out  # 'cars' is in 'general' namespace


def test_show_by_rowid(tmp_db, no_chroma_path, capsys):
    from scripts.memory_admin import cmd_show
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, id="1")
    cmd_show(args)
    out = capsys.readouterr().out
    assert "facts" in out or "name" in out


def test_delete_by_namespace(tmp_db, no_chroma_path):
    from scripts.memory_admin import cmd_delete
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, namespace="general", id=None)
    cmd_delete(args)
    with sqlite3.connect(tmp_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM facts WHERE namespace='general'").fetchone()[0]
    assert n == 0


def test_wipe_requires_confirm(tmp_db, no_chroma_path):
    from scripts.memory_admin import cmd_wipe
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, confirm=False)
    with pytest.raises(SystemExit):
        cmd_wipe(args)


def test_wipe_clears_facts(tmp_db, no_chroma_path):
    from scripts.memory_admin import cmd_wipe
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, confirm=True)
    cmd_wipe(args)
    with sqlite3.connect(tmp_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert n == 0


def test_wipe_clears_memory_items(tmp_db, no_chroma_path):
    from scripts.memory_admin import cmd_wipe
    import types
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, confirm=True)
    cmd_wipe(args)
    with sqlite3.connect(tmp_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
    assert n == 0


def test_export_creates_valid_json(tmp_db, no_chroma_path, tmp_path):
    from scripts.memory_admin import cmd_export
    import types
    out_file = str(tmp_path / "export.json")
    args = types.SimpleNamespace(db=tmp_db, chroma=no_chroma_path, file=out_file)
    cmd_export(args)
    assert os.path.exists(out_file)
    with open(out_file, encoding="utf-8") as fh:
        data = json.load(fh)
    assert "tables" in data
    assert "facts" in data["tables"]
    rows = data["tables"]["facts"]
    assert any(r.get("key") == "name" for r in rows)


def test_export_memory_function_directly(tmp_db, no_chroma_path, tmp_path):
    from scripts.memory_admin import export_memory
    out_file = str(tmp_path / "direct_export.json")
    size = export_memory(tmp_db, no_chroma_path, out_file)
    assert size > 0
    assert os.path.exists(out_file)
