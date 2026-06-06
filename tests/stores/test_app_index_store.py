"""Track 6.1 — focused AppIndexStore integration tests.

Exercises the one-table persistence layer for discovered desktop apps:
upsert (insert + update path), bulk_upsert, alias lookup, category
filter, clear_all, and the staleness predicate. Real SQLite, no mocks.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.stores import AppIndexStore


@pytest.fixture()
def store(tmp_path):
    return AppIndexStore(str(tmp_path / "friday.db"))


def test_upsert_and_list_round_trip(store):
    store.upsert_app(
        canonical="firefox",
        name="Firefox",
        command="/usr/bin/firefox",
        aliases=["firefox", "mozilla firefox"],
        categories=["Network", "WebBrowser"],
        source="desktop",
    )
    rows = store.list_apps()
    assert len(rows) == 1
    row = rows[0]
    assert row["canonical"] == "firefox"
    assert row["command"] == "/usr/bin/firefox"
    assert row["aliases"] == ["firefox", "mozilla firefox"]
    assert row["categories"] == ["Network", "WebBrowser"]
    assert row["source"] == "desktop"


def test_upsert_overwrites_same_canonical(store):
    store.upsert_app(canonical="chrome", name="Chrome", command="/old/path/chrome")
    store.upsert_app(canonical="chrome", name="Google Chrome", command="/new/path/google-chrome")
    rows = store.list_apps()
    assert len(rows) == 1
    assert rows[0]["name"] == "Google Chrome"
    assert rows[0]["command"] == "/new/path/google-chrome"


def test_bulk_upsert_counts_rows(store):
    n = store.bulk_upsert([
        {"canonical": "a", "name": "A", "command": "/a"},
        {"canonical": "b", "name": "B", "command": "/b"},
        {"canonical": "c", "name": "C", "command": "/c"},
    ])
    assert n == 3
    assert store.count() == 3


def test_bulk_upsert_skips_rows_without_canonical_or_command(store):
    store.bulk_upsert([
        {"canonical": "a", "name": "A", "command": "/a"},
        {"canonical": "", "name": "Empty canonical", "command": "/x"},
        {"canonical": "b", "name": "B", "command": ""},
    ])
    assert store.count() == 1
    assert store.list_apps()[0]["canonical"] == "a"


def test_find_by_alias_matches_canonical_or_alias(store):
    store.upsert_app(
        canonical="terminal",
        name="GNOME Terminal",
        command="gnome-terminal",
        aliases=["gnome terminal", "qterminal"],
    )
    assert store.find_by_alias("terminal")["canonical"] == "terminal"
    assert store.find_by_alias("gnome terminal")["canonical"] == "terminal"
    assert store.find_by_alias("qterminal")["canonical"] == "terminal"
    assert store.find_by_alias("kitty") is None


def test_find_by_category_returns_all_matching(store):
    store.upsert_app(canonical="firefox", name="Firefox", command="/usr/bin/firefox",
                     categories=["Network", "WebBrowser"])
    store.upsert_app(canonical="chrome", name="Chrome", command="/usr/bin/chrome",
                     categories=["Network", "WebBrowser"])
    store.upsert_app(canonical="vlc", name="VLC", command="/usr/bin/vlc",
                     categories=["AudioVideo"])
    results = store.find_by_category("WebBrowser")
    canonicals = {r["canonical"] for r in results}
    assert canonicals == {"firefox", "chrome"}


def test_clear_all_resets_table(store):
    store.upsert_app(canonical="x", name="X", command="/x")
    store.upsert_app(canonical="y", name="Y", command="/y")
    assert store.count() == 2
    store.clear_all()
    assert store.count() == 0
    assert store.list_apps() == []


def test_last_refresh_at_returns_max_timestamp(store):
    assert store.last_refresh_at() is None
    store.upsert_app(canonical="x", name="X", command="/x")
    last = store.last_refresh_at()
    assert last is not None
    # The timestamp must parse as ISO 8601
    parsed = datetime.fromisoformat(last)
    assert parsed.tzinfo is not None


def test_is_stale_true_when_empty(store):
    assert store.is_stale(max_age_hours=24) is True


def test_is_stale_false_after_recent_upsert(store):
    store.upsert_app(canonical="x", name="X", command="/x")
    assert store.is_stale(max_age_hours=24) is False


def test_aliases_dedupe_and_sort(store):
    store.upsert_app(
        canonical="zed",
        name="Zed",
        command="/usr/bin/zed",
        aliases=["zed", "Zed", "code editor", "zed"],
    )
    aliases = store.list_apps()[0]["aliases"]
    assert aliases == sorted(set(aliases))
