"""P3.6 — approval primitive."""
from unittest.mock import MagicMock

import pytest
from core.approval import check_approval, has_pending_approval, request_approval


def _make_cs(state: dict | None = None):
    cs = MagicMock()
    _state = dict(state or {})
    cs.get_session_state.return_value = _state
    cs.save_session_state.side_effect = lambda sid, s: _state.update(s)
    return cs, _state


def test_request_sets_pending():
    cs, state = _make_cs()
    msg = request_approval("sess1", "memory_wipe", "Confirm?", "yes wipe", cs)
    assert msg == "Confirm?"
    assert "pending_approval" in state
    assert state["pending_approval"]["action_key"] == "memory_wipe"


def test_check_approval_confirmed():
    cs, _ = _make_cs({"pending_approval": {"action_key": "memory_wipe", "confirm_phrase": "yes wipe everything"}})
    key, confirmed = check_approval("sess1", "yes wipe everything", cs)
    assert key == "memory_wipe"
    assert confirmed is True


def test_check_approval_cancelled():
    cs, _ = _make_cs({"pending_approval": {"action_key": "memory_wipe", "confirm_phrase": "yes wipe everything"}})
    key, confirmed = check_approval("sess1", "no, cancel", cs)
    assert key == "memory_wipe"
    assert confirmed is False


def test_check_approval_clears_state():
    cs, state = _make_cs({"pending_approval": {"action_key": "op", "confirm_phrase": "confirm"}})
    check_approval("sess1", "confirm", cs)
    assert "pending_approval" not in state


def test_check_approval_no_pending():
    cs, _ = _make_cs()
    key, confirmed = check_approval("sess1", "yes", cs)
    assert key is None
    assert confirmed is False


def test_has_pending_yes():
    cs, _ = _make_cs({"pending_approval": {"action_key": "x", "confirm_phrase": "y"}})
    assert has_pending_approval("sess1", cs) is True


def test_has_pending_no():
    cs, _ = _make_cs()
    assert has_pending_approval("sess1", cs) is False


def test_confirm_case_insensitive():
    cs, _ = _make_cs({"pending_approval": {"action_key": "op", "confirm_phrase": "yes delete"}})
    _, confirmed = check_approval("sess1", "YES DELETE", cs)
    assert confirmed is True
