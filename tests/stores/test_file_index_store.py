"""Track 6.2 — focused FileIndexStore integration tests.

Exercises the single-table file path index: upsert, bulk_upsert,
search (LIKE-based with optional ext filter), delete_path,
delete_under, count, and clear_all. Real SQLite, no mocks.
"""
from __future__ import annotations

import os

import pytest

from core.stores import FileIndexStore


@pytest.fixture()
def store(tmp_path):
    return FileIndexStore(str(tmp_path / "friday.db"))


def test_upsert_and_search_round_trip(store):
    store.upsert_file(
        path="/home/u/Documents/notes.md",
        name="notes.md",
        parent_dir="/home/u/Documents",
        ext="md",
        size=128,
        mtime=1_700_000_000.0,
    )
    hits = store.search("notes")
    assert len(hits) == 1
    assert hits[0]["path"] == "/home/u/Documents/notes.md"
    assert hits[0]["ext"] == "md"


def test_upsert_overwrites_same_path(store):
    store.upsert_file(path="/home/u/a.txt", size=10, mtime=100.0)
    store.upsert_file(path="/home/u/a.txt", size=20, mtime=200.0)
    rows = store.search("a")
    assert len(rows) == 1
    assert rows[0]["size"] == 20
    assert rows[0]["mtime"] == 200.0


def test_bulk_upsert_counts_and_skips_blank_paths(store):
    n = store.bulk_upsert([
        {"path": "/x/1.txt"},
        {"path": ""},
        {"path": "/x/2.txt"},
        {"path": "/x/3.txt"},
    ])
    assert n == 3
    assert store.count() == 3


def test_bulk_upsert_commits_across_batch_boundaries(store):
    # 2026-05-29: bulk_upsert now commits in chunks (_UPSERT_BATCH) to release
    # the SQLite write lock between batches. Every row must still land, and
    # re-upserting must not duplicate, even when the input spans several
    # batches.
    total = store._UPSERT_BATCH * 2 + 37
    rows = [{"path": f"/x/f{i}.txt", "name": f"f{i}.txt"} for i in range(total)]
    assert store.bulk_upsert(rows) == total
    assert store.count() == total
    # Re-upsert a slice that straddles a batch edge — conflict path, no dupes.
    edge = store._UPSERT_BATCH
    assert store.bulk_upsert(rows[edge - 5:edge + 5]) == 10
    assert store.count() == total


def test_search_returns_empty_for_no_match(store):
    store.upsert_file(path="/x/foo.txt")
    assert store.search("zzz") == []


def test_search_filters_by_ext(store):
    store.upsert_file(path="/x/a.md", name="a.md")
    store.upsert_file(path="/x/a.txt", name="a.txt")
    md_hits = store.search("a", ext="md")
    assert len(md_hits) == 1
    assert md_hits[0]["ext"] == "md"


def test_search_orders_by_mtime_desc(store):
    store.upsert_file(path="/x/old.txt", name="old.txt", mtime=100.0)
    store.upsert_file(path="/x/new.txt", name="new.txt", mtime=200.0)
    hits = store.search("txt")
    assert hits[0]["name"] == "new.txt"
    assert hits[1]["name"] == "old.txt"


def test_search_honors_limit(store):
    for i in range(15):
        store.upsert_file(path=f"/x/file_{i}.txt", name=f"file_{i}.txt", mtime=float(i))
    assert len(store.search("file", limit=5)) == 5


def test_delete_path_removes_single_row(store):
    store.upsert_file(path="/x/a.txt")
    store.upsert_file(path="/x/b.txt")
    store.delete_path("/x/a.txt")
    assert store.count() == 1
    assert store.search("a") == []


def test_delete_under_removes_subtree(store):
    store.upsert_file(path="/root/keep/a.txt", name="a.txt")
    store.upsert_file(path="/root/drop/b.txt", name="b.txt")
    store.upsert_file(path="/root/drop/sub/c.txt", name="c.txt")
    removed = store.delete_under("/root/drop")
    assert removed == 2
    assert store.count() == 1
    assert store.search("a")[0]["path"] == "/root/keep/a.txt"


def test_clear_all_resets_table(store):
    store.upsert_file(path="/x/1")
    store.upsert_file(path="/x/2")
    store.clear_all()
    assert store.count() == 0


def test_last_indexed_at_returns_max(store):
    assert store.last_indexed_at() is None
    store.upsert_file(path="/x/1")
    assert store.last_indexed_at() is not None


def test_ext_defaults_to_lowercase_no_dot(store):
    store.upsert_file(path="/x/Doc.PDF")
    hits = store.search("doc")
    assert hits[0]["ext"] == "pdf"
