"""P0.3 — Bare 'remember X' free-form write intent routing."""
import types
import pytest
from core.intent_recognizer import IntentRecognizer


def _make_router_with_tools(*tool_names):
    router = types.SimpleNamespace(
        _tools_by_name={name: True for name in tool_names},
        dialog_state=None,
    )
    return router


@pytest.fixture
def recognizer():
    router = _make_router_with_tools(
        "record_personal_fact", "save_note", "show_memories",
    )
    return IntentRecognizer(router)


def _parse(recognizer, text):
    return recognizer._parse_free_remember(text, text.lower(), {})


def test_remember_love_routes_to_record_personal_fact(recognizer):
    result = _parse(recognizer, "remember I love cars")
    assert result is not None
    assert result["tool"] == "record_personal_fact"
    assert result["args"]["key"] == "loves"
    assert result["args"]["value"] == "cars"


def test_remember_like_routes_to_record_personal_fact(recognizer):
    result = _parse(recognizer, "remember I like jazz")
    assert result is not None
    assert result["tool"] == "record_personal_fact"
    assert result["args"]["key"] == "likes"
    assert result["args"]["value"] == "jazz"


def test_remember_that_i_love(recognizer):
    result = _parse(recognizer, "remember that I love hiking")
    assert result is not None
    assert result["tool"] == "record_personal_fact"
    assert result["args"]["value"] == "hiking"


def test_remember_this_ignored(recognizer):
    # "remember this" is demonstrative — _parse_notes handles it, not us
    result = _parse(recognizer, "remember this")
    assert result is None


def test_remember_that_ignored(recognizer):
    result = _parse(recognizer, "remember that")
    assert result is None


def test_generic_remember_routes_to_save_note(recognizer):
    result = _parse(recognizer, "remember to call mom tomorrow")
    assert result is not None
    assert result["tool"] == "save_note"


def test_remember_parser_in_clause_pipeline(recognizer):
    # Verify _parse_free_remember fires inside the full _parse_clause pipeline
    result = recognizer._parse_clause("remember I love cars", {})
    assert result is not None
    assert result["tool"] == "record_personal_fact"
