"""forget_memory intent routing — 'forget my love for coding' was the
2026-05-23 16:12 session bug (routed to chat, model fabricated a reply).
"""
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
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase,expected_key", [
    ("Forget my love for coding", "loves"),
    ("forget my love for python", "loves"),
    ("forget that I love coding", "loves"),
    ("forget that I like jazz", "likes"),
    ("forget that I hate broccoli", "dislikes"),
    ("forget my name", "name"),
    ("forget my location", "location"),
    ("forget my hometown", "location"),
    ("forget my city", "location"),
    ("forget my role", "role"),
    ("forget my job", "role"),
    ("forget where I live", "location"),
    ("forget that I'm a student", "role"),
    ("forget my email", "email"),
])
def test_forget_memory_extracts_key(phrase, expected_key):
    ir = _make_recognizer(["forget_memory"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "forget_memory"
    assert result[0]["args"]["key"] == expected_key


@pytest.mark.parametrize("phrase", [
    "forget everything you know about me",  # → wipe_memory_init
    "forget it",                            # → cancellation
    "forget about it",                      # → cancellation
    "forget all of that",                   # → wipe_memory_init
])
def test_forget_memory_does_not_poach_global_forget(phrase):
    ir = _make_recognizer(["forget_memory", "wipe_memory_init"])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] != "forget_memory", (
            f"forget_memory wrongly captured {phrase!r}"
        )


def test_forget_memory_skipped_when_tool_absent():
    ir = _make_recognizer(["wipe_memory_init"])  # no forget_memory
    result = ir.plan("forget my name")
    if result:
        assert result[0]["tool"] != "forget_memory"
