"""Phase 3 checkpoint 4 — IntentRecognizer interceptor for armed picks.

While a disambiguation pick is armed, `_parse_pending_pick` must route a
selection-shaped utterance to `pick_pending_candidate` and a clear cancel to
`cancel_pending_pick`. Unrelated utterances fall through to normal routing, and
nothing fires when no pick is armed.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_ir(*, armed: bool, candidates=None, tools=None, session_id="sess-1"):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {
        t: MagicMock()
        for t in (tools or ["pick_pending_candidate", "cancel_pending_pick"])
    }
    router.session_id = session_id
    cs = MagicMock()
    cands = candidates if candidates is not None else [
        {"label": "chrome", "value": "chrome"},
        {"label": "chromium", "value": "chromium"},
        {"label": "edge", "value": "edge"},
    ]
    state = {
        "pending_pick": {
            "action": "launch_app", "arg_name": "app_names",
            "base_args": {}, "candidates": cands, "intro": "",
        }
    } if armed else {}
    cs.get_session_state.return_value = state
    router.context_store = cs
    # Neutralize the file/goal pending-selection parser.
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    ds.pending_goal_selection = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase", [
    "1", "2", "option 2", "number 3", "the second one", "first", "last", "3rd",
    "chromium",  # unique label
])
def test_selection_routes_to_pick(phrase):
    ir = _make_ir(armed=True)
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == "pick_pending_candidate", phrase


@pytest.mark.parametrize("phrase", [
    "cancel", "never mind", "none of them", "forget it", "nothing",
])
def test_cancel_routes_to_cancel_pick(phrase):
    ir = _make_ir(armed=True)
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == "cancel_pending_pick", phrase


@pytest.mark.parametrize("phrase", [
    "what's the weather",
    "play some music",
    "what time is it",
])
def test_unrelated_utterance_falls_through(phrase):
    # Not a selection and not a cancel → the interceptor returns None and the
    # turn routes normally (never to the pick tools).
    ir = _make_ir(armed=True)
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] not in {"pick_pending_candidate", "cancel_pending_pick"}, phrase


def test_no_pick_armed_does_not_intercept():
    ir = _make_ir(armed=False)
    result = ir.plan("2")
    if result:
        assert result[0]["tool"] not in {"pick_pending_candidate", "cancel_pending_pick"}


def test_interceptor_inert_without_context_store():
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {"pick_pending_candidate": MagicMock()}
    router.context_store = None
    router.session_id = None
    ir = IntentRecognizer(router)
    assert ir._parse_pending_pick("2", "2", {}) is None


def test_label_substring_for_unique_candidate():
    ir = _make_ir(armed=True, candidates=[
        {"label": "design_notes.md", "value": "/d/design_notes.md"},
        {"label": "budget.xlsx", "value": "/d/budget.xlsx"},
    ])
    result = ir.plan("budget")
    assert result and result[0]["tool"] == "pick_pending_candidate"
