"""Phase 3 — IntentRecognizer interceptor for armed destructive actions.

The `_parse_pending_destructive` parser must fire FIRST while a destructive
action is armed, routing an affirmation to `confirm_pending_action` and
anything else to `cancel_pending_action`. When nothing is armed it must not
interfere with normal routing.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_router(*, armed: bool, tools=None, session_id="sess-1"):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {
        t: MagicMock()
        for t in (tools or ["confirm_pending_action", "cancel_pending_action"])
    }
    router.session_id = session_id
    cs = MagicMock()
    state = {"pending_destructive_action": {"action": "lock_screen", "args": {}}} if armed else {}
    cs.get_session_state.return_value = state
    router.context_store = cs
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return router, IntentRecognizer(router)


@pytest.mark.parametrize("phrase", [
    "yes",
    "yes please",
    "yeah go ahead",
    "do it",
    "confirm",
    "sure, proceed",
])
def test_affirmation_routes_to_confirm(phrase):
    _router, ir = _make_router(armed=True)
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == "confirm_pending_action", phrase


@pytest.mark.parametrize("phrase", [
    "no",
    "no thanks",
    "cancel that",
    "never mind",
    "actually don't",
])
def test_non_affirmation_routes_to_cancel(phrase):
    _router, ir = _make_router(armed=True)
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == "cancel_pending_action", phrase


def test_no_pending_action_does_not_intercept():
    # Nothing armed → the interceptor returns None and a bare "yes" falls
    # through (no confirm/cancel tool fires).
    _router, ir = _make_router(armed=False)
    result = ir.plan("yes")
    if result:
        assert result[0]["tool"] not in {"confirm_pending_action", "cancel_pending_action"}


def test_interceptor_inert_without_context_store():
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {"confirm_pending_action": MagicMock()}
    router.context_store = None
    router.session_id = None
    ir = IntentRecognizer(router)
    # No crash, no interception.
    assert ir._parse_pending_destructive("yes", "yes", {}) is None


def test_confirm_tool_unregistered_falls_to_cancel():
    # If only cancel is registered, an affirmation still resolves the pending
    # state via cancel rather than dispatching an unregistered confirm.
    _router, ir = _make_router(armed=True, tools=["cancel_pending_action"])
    result = ir.plan("yes")
    assert result and result[0]["tool"] == "cancel_pending_action"
