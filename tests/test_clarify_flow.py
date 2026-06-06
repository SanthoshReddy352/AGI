"""P3.11 — Clarify primitive."""
import pytest
from unittest.mock import MagicMock

from core.clarify import ask, check_response, has_pending_clarification


def _make_cs(initial_state=None):
    """Minimal context_store mock with get/save session state."""
    state_store = {"_state": initial_state or {}}
    cs = MagicMock()
    cs.get_session_state = lambda sid: dict(state_store["_state"])
    def _save(sid, state):
        state_store["_state"] = dict(state)
    cs.save_session_state = _save
    return cs


SID = "test-session"


def test_ask_returns_question_with_options():
    cs = _make_cs()
    result = ask(SID, "Which subnet?", ["10.0.0.0/8", "192.168.1.0/24"], cs)
    assert "Which subnet?" in result
    assert "10.0.0.0/8" in result


def test_ask_without_options_returns_plain_question():
    cs = _make_cs()
    result = ask(SID, "What format do you want?", [], cs)
    assert result == "What format do you want?"


def test_ask_sets_pending_state():
    cs = _make_cs()
    ask(SID, "Colour?", ["red", "blue"], cs)
    assert has_pending_clarification(SID, cs)


def test_check_response_clears_state():
    cs = _make_cs()
    ask(SID, "Which subnet?", ["10.0.0.0/8"], cs)
    check_response(SID, "10.0.0.0/8 please", cs)
    assert not has_pending_clarification(SID, cs)


def test_check_response_matches_option():
    cs = _make_cs()
    ask(SID, "Which subnet?", ["10.0.0.0/8", "192.168.1.0/24"], cs)
    q, chosen, valid = check_response(SID, "use 192.168.1.0/24", cs)
    assert q == "Which subnet?"
    assert chosen == "192.168.1.0/24"
    assert valid is True


def test_check_response_no_match():
    cs = _make_cs()
    ask(SID, "Choose a colour", ["red", "blue"], cs)
    q, chosen, valid = check_response(SID, "green", cs)
    assert chosen is None
    assert valid is False


def test_check_response_no_pending_returns_none():
    cs = _make_cs()
    q, chosen, valid = check_response(SID, "anything", cs)
    assert q is None
    assert valid is False


def test_has_pending_false_initially():
    cs = _make_cs()
    assert not has_pending_clarification(SID, cs)


def test_freeform_clarification_accepts_any_input():
    cs = _make_cs()
    ask(SID, "What should I name the file?", [], cs)
    q, chosen, valid = check_response(SID, "my_notes.txt", cs)
    assert chosen == "my_notes.txt"
    assert valid is True


def test_case_insensitive_option_matching():
    cs = _make_cs()
    ask(SID, "Format?", ["JSON", "CSV"], cs)
    q, chosen, valid = check_response(SID, "json format please", cs)
    assert chosen == "JSON"
    assert valid is True
