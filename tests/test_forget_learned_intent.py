"""Adaptive Intent Recognition Phase 5 — forget_learned_intents routing.

`_parse_forget_learned` must catch "forget how I talk" style phrasings and
route them to the routing-learning reset — without poaching the memory-fact
wipe ("forget everything you know about me" → wipe_memory_init).
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


@pytest.mark.parametrize("phrase", [
    "forget how I talk",
    "forget how I speak",
    "reset what you learned about how I talk",
    "unlearn my phrasings",
    "stop learning how I talk",
    "forget how I word things",
    "reset your intent learning",
    "clear the way I phrase things",
])
def test_forget_learned_routes(phrase):
    ir = _make_recognizer(["forget_learned_intents"])
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "forget_learned_intents", \
        f"Got {result[0]['tool']} for: {phrase}"


@pytest.mark.parametrize("phrase", [
    # Memory-fact wipe must NOT be poached by the learning reset.
    "forget everything you know about me",
    "wipe your memory",
    # Unrelated.
    "what's the weather like",
    "forget about the meeting tomorrow",
])
def test_forget_learned_does_not_poach(phrase):
    ir = _make_recognizer(["forget_learned_intents", "wipe_memory_init"])
    result = ir.plan(phrase)
    tool = result[0]["tool"] if result else None
    assert tool != "forget_learned_intents", f"Wrongly poached: {phrase} → {tool}"


def test_inert_when_capability_absent():
    # Tool not registered → parser must return nothing (test apps / optional).
    ir = _make_recognizer(["wipe_memory_init"])
    assert not any(
        a.get("tool") == "forget_learned_intents" for a in (ir.plan("forget how I talk") or [])
    )
