#!/usr/bin/env python3
"""FRIDAY memory admin CLI.

Usage (run from project root):
  python scripts/memory_admin.py inspect
  python scripts/memory_admin.py list [--namespace NS] [--type facts|memory_items|entities|goals]
  python scripts/memory_admin.py show <id>
  python scripts/memory_admin.py delete <id>
  python scripts/memory_admin.py delete --namespace NS
  python scripts/memory_admin.py wipe --confirm
  python scripts/memory_admin.py export memory_dump.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_DEFAULT_DB = os.path.join(_ROOT, "data", "friday.db")
_DEFAULT_CHROMA = os.path.join(_ROOT, "data", "chroma")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _require_db(db_path: str) -> None:
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_inspect(args: argparse.Namespace) -> None:
    _require_db(args.db)
    tables = [
        "facts", "memory_items", "entities", "entity_facts", "entity_relationships",
        "goals", "goal_progress", "sessions", "turns", "conversation_sessions",
        "personas", "notes", "workflows", "audit_events", "commitments",
    ]
    print(f"\nFRIDAY Memory Inspector — {args.db}")
    print(f"  {'Table':<30} {'Rows':>8}")
    print("  " + "-" * 42)
    with _connect(args.db) as conn:
        for table in tables:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                n = "(missing)"
            print(f"  {table:<30} {str(n):>8}")
    _inspect_chroma(args.chroma)
    print()


def _inspect_chroma(chroma_path: str) -> None:
    try:
        import chromadb  # type: ignore
        client = chromadb.PersistentClient(path=chroma_path)
        try:
            col = client.get_collection("friday_memory")
            print(f"  {'chroma:friday_memory':<30} {col.count():>8} vectors")
        except Exception:
            print(f"  {'chroma:friday_memory':<30} {'(empty)':>8}")
    except ImportError:
        print(f"  {'chromadb':<30} {'(not installed)':>8}")


def cmd_list(args: argparse.Namespace) -> None:
    _require_db(args.db)
    kind = getattr(args, "type", None) or "facts"
    ns = getattr(args, "namespace", None)
    with _connect(args.db) as conn:
        if kind == "facts":
            _list_facts(conn, ns)
        elif kind == "memory_items":
            _list_memory_items(conn)
        elif kind == "entities":
            _list_entities(conn)
        elif kind == "goals":
            _list_goals(conn)
        else:
            print(f"Unknown --type: {kind}. Use: facts, memory_items, entities, goals")
            sys.exit(1)
    print()


def _list_facts(conn: sqlite3.Connection, ns: str | None) -> None:
    q = "SELECT rowid, namespace, key, value, updated_at FROM facts"
    params: list = []
    if ns:
        q += " WHERE namespace = ?"
        params.append(ns)
    q += " ORDER BY namespace, key"
    rows = conn.execute(q, params).fetchall()
    print(f"\n  {'ID':>4}  {'namespace':<20} {'key':<24} {'value':<40} updated")
    print("  " + "-" * 110)
    for r in rows:
        val = str(r["value"] or "")[:40]
        print(f"  {r['rowid']:>4}  {r['namespace']:<20} {r['key']:<24} {val:<40} {r['updated_at']}")


def _list_memory_items(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT rowid, item_id, memory_type, content, updated_at "
        "FROM memory_items ORDER BY updated_at DESC LIMIT 50"
    ).fetchall()
    print(f"\n  {'ID':>4}  {'item_id':<38} {'type':<12} content")
    print("  " + "-" * 100)
    for r in rows:
        content = str(r["content"] or "")[:60]
        print(f"  {r['rowid']:>4}  {r['item_id']:<38} {r['memory_type']:<12} {content}")


def _list_entities(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT rowid, entity_id, name, entity_type FROM entities ORDER BY name"
    ).fetchall()
    print(f"\n  {'ID':>4}  {'entity_id':<38} {'type':<16} name")
    print("  " + "-" * 80)
    for r in rows:
        print(f"  {r['rowid']:>4}  {r['entity_id']:<38} {r['entity_type']:<16} {r['name']}")


def _list_goals(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT rowid, goal_id, title, status, health_score, updated_at "
        "FROM goals ORDER BY updated_at DESC"
    ).fetchall()
    print(f"\n  {'ID':>4}  {'status':<12} {'score':>5}  title")
    print("  " + "-" * 80)
    for r in rows:
        score = r["health_score"] or 0.0
        print(f"  {r['rowid']:>4}  {r['status']:<12} {score:>5.2f}  {r['title']}")


def cmd_show(args: argparse.Namespace) -> None:
    _require_db(args.db)
    id_val = args.id
    with _connect(args.db) as conn:
        for table, id_col in [
            ("facts", "rowid"),
            ("memory_items", "item_id"),
            ("entities", "entity_id"),
            ("goals", "goal_id"),
        ]:
            if _try_show(conn, table, id_col, id_val):
                return
    print(f"No row found with id: {id_val}")


def _try_show(conn: sqlite3.Connection, table: str, id_col: str, id_val: str) -> bool:
    try:
        row = conn.execute(
            f"SELECT rowid, * FROM {table} WHERE {id_col} = ? OR rowid = ?",
            (id_val, id_val),
        ).fetchone()
        if row:
            print(f"\nFound in {table}:")
            for k in row.keys():
                print(f"  {k}: {row[k]}")
            print()
            return True
    except (sqlite3.OperationalError, ValueError):
        pass
    return False


def cmd_delete(args: argparse.Namespace) -> None:
    _require_db(args.db)
    ns = getattr(args, "namespace", None)
    id_val = getattr(args, "id", None)
    if ns:
        _delete_namespace(args.db, ns)
    elif id_val:
        _delete_by_id(args.db, id_val)
    else:
        print("Specify --id <id> or --namespace <ns> to delete.")
        sys.exit(1)


def _delete_namespace(db_path: str, ns: str) -> None:
    with _connect(db_path) as conn:
        n = conn.execute("DELETE FROM facts WHERE namespace = ?", (ns,)).rowcount
        conn.commit()
    print(f"Deleted {n} facts in namespace '{ns}'.")


def _delete_by_id(db_path: str, id_val: str) -> None:
    with _connect(db_path) as conn:
        for table, id_col in [
            ("memory_items", "item_id"), ("entities", "entity_id"), ("goals", "goal_id")
        ]:
            try:
                n = conn.execute(f"DELETE FROM {table} WHERE {id_col} = ?", (id_val,)).rowcount
                if n:
                    conn.commit()
                    print(f"Deleted from {table} (id={id_val}).")
                    return
            except sqlite3.OperationalError:
                continue
        try:
            n = conn.execute("DELETE FROM facts WHERE rowid = ?", (id_val,)).rowcount
            if n:
                conn.commit()
                print(f"Deleted from facts (rowid={id_val}).")
                return
        except (sqlite3.OperationalError, ValueError):
            pass
    print(f"No row found to delete with id: {id_val}")


def wipe_memory(db_path: str, chroma_path: str) -> None:
    """Core wipe logic — called by CLI and the in-FRIDAY confirm handler."""
    now = datetime.utcnow().isoformat()
    with _connect(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO audit_events "
                "(tool_name, ok, args_summary, session_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("MEMORY_WIPE_EXECUTED", 1, "memory_admin wipe --confirm", "", now),
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass

    wipe_tables = [
        "facts", "memory_items",
        "entity_relationships", "entity_facts", "entities",
        "goal_progress", "goals",
        "turns", "conversation_sessions", "sessions",
        "personas", "notes",
    ]
    with _connect(db_path) as conn:
        for table in wipe_tables:
            try:
                n = conn.execute(f"DELETE FROM {table}").rowcount
                print(f"  Cleared {n:>5} rows from {table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    _wipe_chroma(chroma_path)


def _wipe_chroma(chroma_path: str) -> None:
    try:
        import chromadb  # type: ignore
        client = chromadb.PersistentClient(path=chroma_path)
        try:
            client.delete_collection("friday_memory")
            print("  Deleted chroma:friday_memory")
        except Exception:
            pass
        client.create_collection("friday_memory")
        print("  Recreated empty chroma:friday_memory")
    except ImportError:
        print("  chromadb not installed — vector store skipped")
    except Exception as exc:
        print(f"  chroma wipe error: {exc}")


def cmd_wipe(args: argparse.Namespace) -> None:
    if not getattr(args, "confirm", False):
        print("Wipe requires --confirm. This is irreversible.", file=sys.stderr)
        sys.exit(1)
    _require_db(args.db)
    wipe_memory(args.db, args.chroma)
    print("\nMemory wiped. Restart FRIDAY to run onboarding again.")


def export_memory(db_path: str, chroma_path: str, output_path: str) -> int:
    """Dump memory tables to JSON. Returns file size in bytes."""
    dump: dict = {
        "exported_at": datetime.utcnow().isoformat(),
        "db": db_path,
        "tables": {},
    }
    exportable = [
        "facts", "memory_items", "entities", "entity_facts", "entity_relationships",
        "goals", "goal_progress", "personas", "notes",
    ]
    with _connect(db_path) as conn:
        for table in exportable:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                dump["tables"][table] = [dict(r) for r in rows]
            except sqlite3.OperationalError:
                dump["tables"][table] = []
    dump["chroma"] = _export_chroma(chroma_path)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(dump, fh, indent=2, ensure_ascii=False, default=str)
    return os.path.getsize(output_path)


def _export_chroma(chroma_path: str) -> dict:
    try:
        import chromadb  # type: ignore
        client = chromadb.PersistentClient(path=chroma_path)
        col = client.get_collection("friday_memory")
        result = col.get(include=["documents", "metadatas"])
        return {
            "ids": result.get("ids", []),
            "documents": result.get("documents", []),
            "metadatas": result.get("metadatas", []),
        }
    except Exception:
        return {}


def cmd_export(args: argparse.Namespace) -> None:
    _require_db(args.db)
    size = export_memory(args.db, args.chroma, args.file)
    print(f"Exported to {args.file} ({size // 1024} KB)")


# ── Argument parsing ─────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="FRIDAY memory admin CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db", default=_DEFAULT_DB, help="Path to friday.db")
    p.add_argument("--chroma", default=_DEFAULT_CHROMA, help="Path to chroma dir")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("inspect", help="Row counts per table + Chroma size")

    ls = sub.add_parser("list", help="List memory rows")
    ls.add_argument("--namespace", "-n", help="Filter facts by namespace")
    ls.add_argument("--type", "-t", default="facts",
                    choices=["facts", "memory_items", "entities", "goals"])

    sh = sub.add_parser("show", help="Show full content of one row")
    sh.add_argument("id", help="Row ID (rowid or UUID)")

    dl = sub.add_parser("delete", help="Delete a row or namespace")
    dl.add_argument("id", nargs="?", help="Row ID to delete")
    dl.add_argument("--namespace", "-n", help="Delete all facts in this namespace")

    wp = sub.add_parser("wipe", help="Wipe all memory (irreversible)")
    wp.add_argument("--confirm", action="store_true", help="Required to actually wipe")

    ex = sub.add_parser("export", help="Dump all memory to JSON")
    ex.add_argument("file", help="Output JSON file path")

    return p


_COMMANDS = {
    "inspect": cmd_inspect,
    "list": cmd_list,
    "show": cmd_show,
    "delete": cmd_delete,
    "wipe": cmd_wipe,
    "export": cmd_export,
}


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    _COMMANDS[args.command](args)
