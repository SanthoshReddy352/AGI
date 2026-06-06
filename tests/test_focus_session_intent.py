"""Intent-recognizer coverage for the focus-session capabilities.

Pins the "proper implementation" pass (2026-05-26):
  • start / end / status route deterministically to the three
    ``*_focus_session`` capabilities instead of falling into LLM chat;
  • the spoken duration lands in ``args["minutes"]`` (the declared
    parameter) rather than being silently dropped;
  • the ubiquitous phrase "focus on <X>" no longer hijacks ordinary
    speech into a focus session — the regression this suite exists to
    prevent.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


FOCUS_TOOLS = [
    "start_focus_session",
    "end_focus_session",
    "focus_session_status",
]


def _make_recognizer(tools=None):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in (tools if tools is not None else FOCUS_TOOLS)}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


# ---------------------------------------------------------------------------
# start_focus_session — verb / object / phrasing breadth
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "start a focus session",
    "start focus",
    "begin a pomodoro",
    "enter focus mode",
    "go into deep work mode",
    "kick off a pomodoro",
    "enable do not disturb",
    "activate focus mode",
    "put me in do not disturb",
    "deep work mode",
    "focus mode",
    "focus session",
    "turn on focus",
    "turn on do not disturb",
    "dnd for 25",
    "focus for 50 minutes",
    "pomodoro for 45 minutes",
    "do not disturb for 30 minutes",
    "silence my notifications for an hour",
    "block me from notifications",
    "give me 25 minutes of focus",
])
def test_start_focus_routes(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "start_focus_session", f"Got {result[0]['tool']} for: {phrase}"


@pytest.mark.parametrize("phrase,minutes", [
    ("focus for 50 minutes", 50),
    ("pomodoro for 45 minutes", 45),
    ("dnd for 25", 25),
    ("do not disturb for 30 minutes", 30),
    ("focus for 2 hours", 120),
    ("silence my notifications for an hour", 60),
    ("focus for half an hour", 30),
    ("focus for fifty minutes", 50),
    ("give me 25 minutes of focus", 25),
    ("focus for 999 minutes", 240),   # capped at the 240-minute ceiling
])
def test_start_focus_extracts_minutes(phrase, minutes):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == "start_focus_session", f"No start plan for: {phrase}"
    assert result[0]["args"].get("minutes") == minutes, (
        f"Expected minutes={minutes} for {phrase!r}, got {result[0]['args']}"
    )


def test_start_focus_without_duration_omits_minutes():
    """No spoken duration → no minutes arg (handler defaults to 25)."""
    ir = _make_recognizer()
    result = ir.plan("start a focus session")
    assert result and result[0]["tool"] == "start_focus_session"
    assert "minutes" not in result[0]["args"]


# ---------------------------------------------------------------------------
# end_focus_session
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "end focus",
    "stop focus session",
    "exit focus mode",
    "cancel focus",
    "disable do not disturb",
    "turn off focus",
    "turn off do not disturb",
    "quit deep work mode",
])
def test_end_focus_routes(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "end_focus_session", f"Got {result[0]['tool']} for: {phrase}"


# ---------------------------------------------------------------------------
# focus_session_status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "focus status",
    "how much focus is left",
    "how much time is left",
    "am i still in focus mode",
    "am i in focus",
    "focus remaining",
    "dnd status",
])
def test_focus_status_routes(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase}"
    assert result[0]["tool"] == "focus_session_status", f"Got {result[0]['tool']} for: {phrase}"


# ---------------------------------------------------------------------------
# Negative cases — must NOT route to any focus capability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "focus on my homework",
    "i need to focus on the report",
    "let's focus on the bug",
    "can you focus on accuracy",
    "what is do not disturb mode",
    "the pomodoro technique is popular",
])
def test_focus_negatives_do_not_route(phrase):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    tool = result[0]["tool"] if result else None
    assert tool not in FOCUS_TOOLS, f"{phrase!r} wrongly routed to {tool}"


def test_parser_inert_without_capability():
    """When the focus capabilities aren't loaded the parser stays silent."""
    ir = _make_recognizer(tools=[])
    assert ir.plan("start a focus session") == []
