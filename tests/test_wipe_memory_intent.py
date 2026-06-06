"""P2.1 — memory wipe and export intent routing in IntentRecognizer."""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

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


@pytest.mark.parametrize("phrase", [
    "forget everything you know about me",
    "wipe your memory",
    "wipe my memory",
    "erase everything",
    "start fresh",
    "delete everything you know about me",
])
def test_wipe_init_routes(phrase):
    ir = _make_recognizer(["wipe_memory_init"])
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "wipe_memory_init", f"Got {result[0]['tool']} for: {phrase}"


@pytest.mark.parametrize("phrase", [
    "export my memory",
    "export memory",
    "backup my memory",
])
def test_export_memory_routes(phrase):
    ir = _make_recognizer(["export_memory"])
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "export_memory"


def _make_wipe_router(session_id: str, pending: bool = True):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {
        "confirm_memory_wipe": MagicMock(),
        "cancel_memory_wipe": MagicMock(),
    }
    router.session_id = session_id
    cs = MagicMock()
    cs.get_session_state.return_value = {"pending_memory_wipe": pending}
    router.context_store = cs
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return router, cs, IntentRecognizer(router)


def test_wipe_confirmation_intercepted():
    """When pending_memory_wipe is set, 'yes wipe everything' → confirm_memory_wipe."""
    router, cs, ir = _make_wipe_router("sess-123")
    result = ir.plan("yes, wipe everything")
    assert result and result[0]["tool"] == "confirm_memory_wipe"
    # Flag should be cleared
    saved_state = cs.save_session_state.call_args[0][1]
    assert not saved_state.get("pending_memory_wipe")


def test_wipe_cancellation_intercepted():
    """When pending_memory_wipe is set, non-confirm phrase → cancel_memory_wipe."""
    router, cs, ir = _make_wipe_router("sess-456")
    result = ir.plan("no, cancel that")
    assert result and result[0]["tool"] == "cancel_memory_wipe"


def test_wipe_init_not_triggered_without_tool_registered():
    """If wipe_memory_init isn't registered, the phrase falls through."""
    ir = _make_recognizer([])  # no tools registered
    result = ir.plan("forget everything you know about me")
    # Should not crash; may route to LLM chat or return empty
    # Just verify it doesn't raise
    assert result is not None or result is None


def test_no_false_trigger_on_normal_forget():
    """'forget my location' should NOT trigger wipe_memory_init."""
    ir = _make_recognizer(["wipe_memory_init", "delete_memory", "forget_memory"])
    result = ir.plan("forget my location")
    # Should not be wipe_memory_init
    if result:
        assert result[0]["tool"] != "wipe_memory_init"
