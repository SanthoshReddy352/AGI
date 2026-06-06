"""Hermes-ported web tool intent routing (2026-05-23).

The bug repro from the live 2026-05-23 16:42 session:
  "crawl https://news.ycombinator.com and find ML stories" was routing
  to `search_indexed_files` via the planner because no intent regex
  existed for `web_crawl` / `web_extract`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_recognizer(tools: list[str]):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in tools}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase,expected_url,expected_instr_substr", [
    ("crawl https://news.ycombinator.com and find ML stories",
     "https://news.ycombinator.com",
     "ml stories"),
    ("crawl https://example.com",
     "https://example.com",
     ""),
    ("scrape this site: https://example.com",
     "https://example.com",
     ""),
])
def test_web_crawl_routes_with_url(phrase, expected_url, expected_instr_substr):
    ir = _make_recognizer(["web_crawl", "web_extract", "search_indexed_files"])
    result = ir.plan(phrase)
    assert result, f"no plan for: {phrase!r}"
    assert result[0]["tool"] == "web_crawl"
    assert result[0]["args"]["url"].startswith(expected_url)
    if expected_instr_substr:
        assert expected_instr_substr in result[0]["args"]["instructions"].lower()


@pytest.mark.parametrize("phrase", [
    "fetch https://docs.python.org/3/library/subprocess.html",
    "Friday, fetch https://docs.python.org/3/library/subprocess.htm",
    "read this url https://example.com/article",
    "extract content from https://example.com",
    "open https://en.wikipedia.org/wiki/Linux",
    "download https://example.com/file.txt",
])
def test_web_extract_routes_with_url(phrase):
    ir = _make_recognizer(["web_extract", "web_crawl"])
    result = ir.plan(phrase)
    assert result, f"no plan for: {phrase!r}"
    assert result[0]["tool"] == "web_extract"
    assert result[0]["args"]["url"].startswith("https://")


def test_bare_url_routes_to_extract():
    ir = _make_recognizer(["web_extract"])
    result = ir.plan("https://example.com")
    assert result and result[0]["tool"] == "web_extract"


@pytest.mark.parametrize("phrase", [
    # No URL → must not poach; should fall through.
    "crawl my files",
    "scrape my memory",
    "fetch the report",
    "find ML stories",
    "look for new articles",
])
def test_web_parser_skips_when_no_url(phrase):
    ir = _make_recognizer([
        "web_crawl", "web_extract",
        "search_indexed_files", "search_file",
    ])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] not in ("web_crawl", "web_extract"), (
            f"web tool wrongly captured no-URL phrase: {phrase!r} -> {result[0]['tool']}"
        )


def test_web_parser_skipped_when_tool_absent():
    """If neither web tool is loaded, parser is inert."""
    ir = _make_recognizer(["search_indexed_files"])
    result = ir.plan("crawl https://example.com")
    if result:
        assert result[0]["tool"] not in ("web_crawl", "web_extract")


def test_google_search_still_wins_for_search_phrasing():
    """search_google is the right tool for 'search the web for X' (browser-driven)."""
    ir = _make_recognizer(["search_google", "web_search", "web_crawl"])
    result = ir.plan("search the web for claude opus 4.7 release notes")
    assert result and result[0]["tool"] == "search_google"
    assert "claude" in result[0]["args"]["query"].lower()


def test_crawl_with_url_beats_search_indexed_files():
    """Regression: 'crawl <URL> and find X' must NOT go to search_indexed_files."""
    ir = _make_recognizer(["web_crawl", "search_indexed_files"])
    result = ir.plan("crawl https://news.ycombinator.com and find ML stories")
    assert result and result[0]["tool"] == "web_crawl"
