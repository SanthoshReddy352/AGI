"""Track 6 / 6.3 — intent-recognizer coverage for the newly-added tools.

These pin the "rescan my apps fell into chat mode" bug from the
2026-05-23 15:35 session log. Every Track 6 / 6.3 capability now needs
deterministic routing through IntentRecognizer; falling into LLM-chat
let the small model fabricate junk like
'The user wants to rescan their apps. This is a standard command...'
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


ALL_TOOLS = [
    "refresh_app_index",
    "refresh_file_index",
    "search_indexed_files",
    "set_brightness",
    "lock_screen",
    "unlock_screen",
]


def _make_recognizer(tools=None):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in (tools if tools is not None else ALL_TOOLS)}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


# ---------------------------------------------------------------------------
# refresh_app_index
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "rescan my apps",
    "rescan apps",
    "refresh applications",
    "reindex my apps",
    "rebuild the app index",
    "update the application index",
    "apps rescan",
    "Friday rescan my apps",
])
def test_refresh_app_index_routes(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "refresh_app_index", f"Got {result[0]['tool']} for: {phrase}"


# ---------------------------------------------------------------------------
# refresh_file_index
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "reindex my files",
    "rescan filesystem",
    "rebuild the file index",
    "refresh file index",
    "scan my filesystem",
    "rebuild index",
])
def test_refresh_file_index_routes(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "refresh_file_index", f"Got {result[0]['tool']} for: {phrase}"


# ---------------------------------------------------------------------------
# search_indexed_files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_query", [
    # "called <name>" — explicit signal, works without an extension.
    ("where is the file called notes", "notes"),
    ("find the file called meeting", "meeting"),
    ("locate file called budget", "budget"),
    # Filename with extension — implicit signal.
    ("where is notes.md", "notes.md"),
    ("find file budget.xlsx", "budget.xlsx"),
    ("locate file invoice.pdf", "invoice.pdf"),
    ("search for file report.docx", "report.docx"),
])
def test_search_indexed_files_routes(phrase, expected_query):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "search_indexed_files"
    assert expected_query in result[0]["args"]["query"]


def test_search_indexed_files_yields_to_file_action_for_natural_phrasing():
    """'find the file design build final report' (no extension, no
    'called') must NOT match search_indexed_files — it has to fall
    through to the broader file-search router. Regression for
    test_workflow_orchestration.py::test_confirm_yes_replays_pending_clarification_action.
    """
    ir = _make_recognizer()
    result = ir.plan("find the file design build final report")
    if result:
        assert result[0]["tool"] != "search_indexed_files"


# ---------------------------------------------------------------------------
# set_brightness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_percent", [
    ("set brightness to 60", 60),
    ("set brightness to 60%", 60),
    ("brightness 80%", 80),
    ("set brightness to 50%", 50),
    ("dim to 30", 30),
    ("set brightness to fifty", 50),
    ("set brightness to seventy", 70),
    ("max brightness", 100),
    ("minimum brightness", 0),
])
def test_set_brightness_routes(phrase, expected_percent):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "set_brightness", f"Got {result[0]['tool']} for: {phrase}"
    assert result[0]["args"]["percent"] == expected_percent


def test_set_brightness_rejects_unrelated_numbers():
    """'Set timer to 60' must not trigger set_brightness."""
    ir = _make_recognizer()
    result = ir.plan("set timer to 60 minutes")
    if result:
        assert result[0]["tool"] != "set_brightness"


# ---------------------------------------------------------------------------
# lock_screen / unlock_screen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "lock screen",
    "lock the screen",
    "lock friday",
    "lock yourself",
    "lock the assistant",
    "enable screen lock",
    "engage screen lock",
])
def test_lock_screen_routes(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "lock_screen", f"Got {result[0]['tool']} for: {phrase}"


@pytest.mark.parametrize("phrase,expected_pin", [
    ("unlock screen 1234", "1234"),
    ("unlock 4321", "4321"),
    ("unlock the screen with 1234", "1234"),
    ("unlock with pin 9999", "9999"),
    ("unlock screen", ""),
    ("unlock me", ""),
])
def test_unlock_screen_routes(phrase, expected_pin):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "unlock_screen", f"Got {result[0]['tool']} for: {phrase}"
    assert result[0]["args"]["pin"] == expected_pin


# ---------------------------------------------------------------------------
# Negative cases — these phrases must NOT match the new parsers.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "what is the time",
    "tell me a joke",
    "take a screenshot",
    "set volume to 50",
])
def test_unrelated_phrases_do_not_match_new_parsers(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    matched = result[0]["tool"] if result else None
    assert matched not in {
        "refresh_app_index", "refresh_file_index", "search_indexed_files",
        "set_brightness", "lock_screen", "unlock_screen",
    }, f"{phrase} mis-routed to {matched}"
