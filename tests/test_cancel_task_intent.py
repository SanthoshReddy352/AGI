"""Intent recognizer coverage for the cancel_active_task tool.

The phrasal patterns here must route to cancel_active_task. Bare "cancel"
and "stop" are intentionally left to _parse_confirmation → confirm_no so
that pending yes/no dialogs still work.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


ALL_TOOLS = [
    "cancel_active_task",
    "cancel_memory_wipe",
    "confirm_yes",
    "confirm_no",
    "shutdown_assistant",
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
    ds.pending_clarification = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase", [
    "cancel that",
    "cancel this",
    "cancel it",
    "stop that",
    "stop this",
    "abort that",
    "never mind",
    "cancel the research",
    "stop the research",
    "abort the research",
    "cancel the task",
    "stop the task",
    "cancel what you're doing",
    "cancel what you are doing",
    "stop what you're doing",
    "stop what you are doing",
    "cancel all you are doing",
    "stop working on that",
    "cancel the search",
    "stop the process",
])
def test_cancel_task_routes_to_cancel_active_task(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "cancel_active_task", f"Got {result[0]['tool']} for: {phrase}"


@pytest.mark.parametrize("phrase", [
    # Bare "cancel" / "stop" must remain confirm_no so pending dialogs work
    "cancel",
    "stop",
    "no",
    "nope",
    "cancel something else",
    "stop the car",
    "stop the music",
    # Domain-specific cancels must not be poached
    "cancel the dictation",
    "cancel my memo",
    "cancel the calendar event",
    "cancel my meeting",
    "cancel memory wipe",
    # Shutdown phrases must not be poached
    "shut down",
    "shutdown",
])
def test_negative_cases_do_not_match(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] != "cancel_active_task", f"Should not match cancel_active_task for: {phrase}"
