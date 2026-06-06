"""Identity intent routing — 'who are you?' must hit identify_self, not the LLM."""
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
    ds.pending_memory_wipe = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase", [
    "Who are you?",
    "who are you",
    "Who are you, Friday?",
    "What are you?",
    "what's your name",
    "What is your name?",
    "tell me about yourself",
    "tell me about you",
    "introduce yourself",
    "describe yourself",
    "Are you an AI?",
    "are you a bot",
    "are you human",
    "are you real",
    "state your name",
    "state your identity",
    "identify yourself",
])
def test_identity_routes_to_identify_self(phrase):
    ir = _make_recognizer(["identify_self"])
    result = ir.plan(phrase)
    assert result, f"No plan produced for: {phrase!r}"
    assert result[0]["tool"] == "identify_self", (
        f"Got {result[0]['tool']!r} for {phrase!r}, expected identify_self"
    )


@pytest.mark.parametrize("phrase", [
    # 'who am I' must keep routing to personal-fact recall, not identity
    "who am i",
    "what's my name",
    # Bare hellos route to greet, not identity
    "hi",
    "hello friday",
    # Generic chatter must NOT poach the identity intent
    "open firefox",
    "what time is it",
    "set brightness to 60%",
])
def test_identity_does_not_poach(phrase):
    ir = _make_recognizer([
        "identify_self", "greet", "recall_personal_fact",
        "launch_app", "get_time", "set_brightness",
    ])
    result = ir.plan(phrase)
    # Either no plan, or the chosen tool is not identify_self.
    if result:
        assert result[0]["tool"] != "identify_self", (
            f"identify_self wrongly captured: {phrase!r}"
        )


def test_identity_skipped_when_capability_absent():
    """If identify_self isn't registered, parser should be a no-op (not crash)."""
    ir = _make_recognizer(["greet"])  # no identify_self
    result = ir.plan("who are you?")
    # Should fall through — either no plan or some other tool (not identify_self).
    if result:
        assert result[0]["tool"] != "identify_self"
