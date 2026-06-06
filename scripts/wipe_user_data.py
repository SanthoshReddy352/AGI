#!/usr/bin/env python3
"""Wipe all user-generated data while preserving app and file indexes.

Clears:
  - Sessions, turns, personas, conversation state
  - Memory items, facts, vector index (friday_memory)
  - Knowledge graph entities and relationships
  - Goals and goal progress
  - Audit events, agent messages, commitments
  - Workflow state
  - Routing observations and learned intent patterns

Keeps:
  - App index (app_index table)
  - File index (file_index table)
  - Document intelligence index (indexed_documents + friday_documents)

Usage:
  python scripts/wipe_user_data.py          # dry-run (shows what would be wiped)
  python scripts/wipe_user_data.py --force   # execute the wipe
"""

import argparse
import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "friday.db")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "data", "chroma")

WIPE_TABLES = [
    "memory_items",
    "facts",
    "entities",
    "entity_facts",
    "entity_relationships",
    "goals",
    "goal_progress",
    "sessions",
    "turns",
    "conversation_sessions",
    "personas",
    "audit_events",
    "online_permission_events",
    "agent_messages",
    "commitments",
    "workflows",
    "routing_observations",
    "learned_phrases",
    "intent_profile",
]

KEEP_TABLES = [
    "app_index",
    "file_index",
    "indexed_documents",
]

FTS_TABLES = {
    "turns_fts": "turns",
}


def wipe_sqlite(conn: sqlite3.Connection, dry_run: bool) -> list[str]:
    actions = []
    for table in WIPE_TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM \"{table}\"").fetchone()[0]
        if count == 0:
            continue
        if not dry_run:
            conn.execute(f"DELETE FROM \"{table}\"")
        actions.append(f"  {table:<30s}  {count:>6d} rows")
    for fts_table, source_table in FTS_TABLES.items():
        count = conn.execute(f"SELECT COUNT(*) FROM \"{source_table}\"").fetchone()[0]
        if count > 0 and not dry_run:
            conn.execute(f"DELETE FROM \"{fts_table}\"")
        # FTS count mirrors source table — no separate row reporting
    conn.commit()
    return actions


def verify_kept_tables(conn: sqlite3.Connection) -> list[str]:
    """Sanity-check that KEEP tables exist and are still populated."""
    kept = []
    for table in KEEP_TABLES:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM \"{table}\"").fetchone()[0]
            kept.append(f"  {table:<30s}  {count:>6d} rows (preserved)")
        except sqlite3.OperationalError:
            kept.append(f"  {table:<30s}  table not found (no index built yet)")
    return kept


def wipe_chroma(dry_run: bool) -> list[str]:
    """Delete and recreate the friday_memory collection; leave friday_documents."""
    actions = []
    chroma_dir = CHROMA_PATH
    if not os.path.isdir(chroma_dir):
        actions.append("  chroma/  directory not found — skipping")
        return actions
    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_dir)
        existing = {c.name for c in client.list_collections()}
        if "friday_memory" in existing:
            if not dry_run:
                client.delete_collection("friday_memory")
                client.create_collection("friday_memory")
            actions.append("  friday_memory  chroma collection wiped and recreated")
        else:
            actions.append("  friday_memory  chroma collection not found")
        if "friday_documents" in existing:
            actions.append("  friday_documents  chroma collection preserved")
    except Exception as exc:
        actions.append(f"  chroma error: {exc}")
    return actions


def main():
    parser = argparse.ArgumentParser(description="Wipe user data, preserve indexes")
    parser.add_argument("--force", action="store_true", help="Execute the wipe (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.force
    label = "DRY RUN" if dry_run else "WIPE"
    print(f"[{label}] User data wipe — preserving app_index, file_index, indexed_documents")
    print()

    if not os.path.isfile(DB_PATH):
        print(f"  Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    print("  SQL tables to wipe:")
    sql_actions = wipe_sqlite(conn, dry_run)
    if sql_actions:
        for a in sql_actions:
            print(a)
    else:
        print("  (all tables already empty)")

    print()
    print("  Tables preserved:")
    kept = verify_kept_tables(conn)
    for k in kept:
        print(k)

    print()
    print("  Chroma vector store:")
    chroma_actions = wipe_chroma(dry_run)
    for a in chroma_actions:
        print(a)

    conn.close()

    print()
    if dry_run:
        print("  ── Dry-run complete. No data changed. ──")
        print('  Run with --force to execute.')
    else:
        print("  ── Wipe complete. ──")


if __name__ == "__main__":
    main()
