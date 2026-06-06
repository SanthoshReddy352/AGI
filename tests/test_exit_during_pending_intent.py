"""Regression: a goodbye/exit while a file slot-fill is pending must shut down.

Pins the 2026-05-29 bug from the session log: FRIDAY asked "Which file would
you like me to open?" (set ``pending_file_name_request``), the user said "bye",
and ``_parse_pending_selection`` swallowed "bye" as the *filename* — searching
for it and matching the *goodbye* test files instead of shutting down.

A standalone exit phrase must escape ANY pending slot-fill and fall through to
``_parse_exit`` → shutdown_assistant.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.dialog_state import DialogState


ALL_TOOLS = [
    "open_file",
    "read_file",
    "summarize_file",
    "search_file",
    "shutdown_assistant",
    "select_file_candidate",
]


def _make_recognizer(tools=None):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in (tools if tools is not None else ALL_TOOLS)}
    router.context_store = None
    router.session_id = None
    router.dialog_state = DialogState()
    return IntentRecognizer(router), router.dialog_state


@pytest.mark.parametrize("phrase", ["bye", "goodbye", "bye friday", "exit", "quit", "Goodbye."])
@pytest.mark.parametrize("pending_action", ["open", "read", "summarize", "find"])
def test_exit_escapes_pending_file_name_request(phrase, pending_action):
    ir, ds = _make_recognizer()
    ds.pending_file_name_request = pending_action

    result = ir.plan(phrase)

    assert result, f"No plan for: {phrase!r}"
    assert result[0]["tool"] == "shutdown_assistant", (
        f"{phrase!r} with pending '{pending_action}' routed to "
        f"{result[0]['tool']} instead of shutdown_assistant"
    )
    # The pending slot must be cleared so the next turn starts fresh.
    assert ds.pending_file_name_request is None


def test_exit_escapes_pending_candidate_list():
    ir, ds = _make_recognizer()
    ds.set_pending_file_request(
        candidates=["/x/test_goodbye_a.md", "/x/test_goodbye_b.md"],
        requested_actions=["open"],
    )

    result = ir.plan("bye")

    assert result and result[0]["tool"] == "shutdown_assistant"
    assert ds.pending_file_request is None


def test_real_filename_still_fills_pending_slot():
    """An actual filename must NOT be mistaken for an exit phrase."""
    ir, ds = _make_recognizer()
    ds.pending_file_name_request = "open"

    result = ir.plan("exit_plan.txt")

    assert result and result[0]["tool"] == "open_file"
    assert result[0]["args"]["filename"] == "exit_plan.txt"
