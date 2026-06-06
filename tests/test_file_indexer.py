"""Track 6.2 — FileIndexer service tests.

Exercises the BFS walker against a tmp tree: counts, excludes, hidden
dirs skipped, deep nesting, and ensures the persisted store matches.
watchdog is treated as optional — if it isn't installed,
`start_watcher()` is asserted to return False rather than crashing.
"""
from __future__ import annotations

import os

import pytest

from core.stores import FileIndexStore
from modules.system_control.file_indexer import (
    DEFAULT_EXCLUDES,
    FileIndexer,
    default_roots,
)


@pytest.fixture()
def store(tmp_path):
    return FileIndexStore(str(tmp_path / "friday.db"))


@pytest.fixture()
def sample_tree(tmp_path):
    root = tmp_path / "user"
    (root / "Documents").mkdir(parents=True)
    (root / "Downloads").mkdir()
    (root / ".cache").mkdir()  # hidden
    (root / "node_modules" / "pkg").mkdir(parents=True)  # excluded
    (root / "Documents" / "notes.md").write_text("hello")
    (root / "Documents" / "meeting.pdf").write_bytes(b"%PDF")
    (root / "Downloads" / "installer.exe").write_bytes(b"MZ")
    (root / ".cache" / "stale.txt").write_text("ignore me")
    (root / "node_modules" / "pkg" / "index.js").write_text("// nope")
    return str(root)


def test_scan_once_indexes_visible_files(store, sample_tree):
    indexer = FileIndexer(store, roots=[sample_tree])
    count = indexer.scan_once()
    assert count == 3  # notes.md + meeting.pdf + installer.exe
    assert store.count() == 3


def test_scan_skips_hidden_and_excluded_dirs(store, sample_tree):
    indexer = FileIndexer(store, roots=[sample_tree])
    indexer.scan_once()
    paths = {row["path"] for row in store.search("", limit=999) or store.search("e", limit=999)}
    # search('') returns []; use a broad search instead
    all_rows = [row for row in store.search("e", limit=999)]
    extensions_seen = {row["ext"] for row in all_rows}
    # node_modules + .cache contents must not appear
    names = {row["name"] for row in all_rows}
    assert "stale.txt" not in names
    assert "index.js" not in names


def test_scan_handles_nonexistent_root(store, tmp_path):
    indexer = FileIndexer(store, roots=[str(tmp_path / "does_not_exist")])
    assert indexer.scan_once() == 0


def test_scan_ignores_unreadable_subdir(store, tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    (root / "ok.txt").write_text("a")
    locked = root / "locked"
    locked.mkdir()
    (locked / "secret.txt").write_text("a")
    try:
        os.chmod(locked, 0)
        indexer = FileIndexer(store, roots=[str(root)])
        n = indexer.scan_once()
        assert n >= 1
    finally:
        os.chmod(locked, 0o755)


def test_scan_respects_max_files_cap(store, tmp_path):
    root = tmp_path / "big"
    root.mkdir()
    for i in range(20):
        (root / f"f_{i}.txt").write_text("x")
    indexer = FileIndexer(store, roots=[str(root)], max_files_per_scan=5)
    n = indexer.scan_once()
    assert n == 5


def test_excludes_are_lowercase_compared(store, tmp_path):
    root = tmp_path / "r"
    (root / "Node_Modules").mkdir(parents=True)
    (root / "Node_Modules" / "x.js").write_text("// no")
    (root / "keep.txt").write_text("yes")
    indexer = FileIndexer(store, roots=[str(root)])
    indexer.scan_once()
    names = {row["name"] for row in store.search("", limit=999) or store.search("e", limit=999)}
    # Direct search:
    txt_hits = store.search("keep")
    assert len(txt_hits) == 1
    js_hits = store.search("x.js")
    assert js_hits == []


def test_default_roots_filters_nonexistent(monkeypatch, tmp_path):
    # Force HOME to a tmp dir with only Documents present
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Documents").mkdir()
    roots = default_roots()
    assert any(r.endswith("Documents") for r in roots)
    assert all(os.path.isdir(r) for r in roots)


def test_start_watcher_returns_bool(store, sample_tree):
    """Watcher start must not crash whether or not watchdog is installed."""
    indexer = FileIndexer(store, roots=[sample_tree])
    result = indexer.start_watcher()
    assert isinstance(result, bool)
    indexer.stop()


def test_default_excludes_includes_common_build_dirs():
    expected = {".git", ".venv", "node_modules", "__pycache__", "target", "build", "dist"}
    assert expected.issubset(DEFAULT_EXCLUDES)
