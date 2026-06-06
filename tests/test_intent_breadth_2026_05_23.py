"""Step 3 — broadened intent patterns for existing parsers.

Each parametrised test enumerates spoken variants the user actually
uses (per CLAUDE.md "humans interact differently with different tools").
Anti-poach cases ensure broadened regexes don't grab unrelated phrases.
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


# ── brightness ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_percent", [
    ("set brightness to 60", 60),
    ("brightness 50%", 50),
    ("brightness to 75", 75),
    ("dim the screen to 30", 30),
    ("brighten to 80", 80),
    ("make my screen brighter", 80),     # relative → bump up
    ("make it darker", 30),               # relative → bump down
    ("turn down the screen brightness", 30),
    ("turn up the screen brightness", 80),
    ("raise screen brightness", 80),
    ("lower the screen brightness", 30),
    ("max brightness", 100),
    ("full brightness", 100),
    ("minimum brightness", 0),
    ("lowest brightness", 0),
    ("brightness to max", 100),
    ("brightness to min", 0),
    ("set brightness to fifty", 50),
    ("set brightness to seventy five", 75),
    ("set brightness to a hundred", 100),
    ("dim the screen all the way", 0),
])
def test_brightness_variants(phrase, expected_percent):
    ir = _make_recognizer(["set_brightness"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "set_brightness"
    assert result[0]["args"]["percent"] == expected_percent, (
        f"{phrase!r}: got {result[0]['args']['percent']}, expected {expected_percent}"
    )


@pytest.mark.parametrize("phrase", [
    # These must NOT route to set_brightness.
    "open my screen recorder",
    "I deleted my brightness folder",  # contains 'brightness' but no action verb
    "what's the weather like",
    "lower the volume",                 # belongs to volume
])
def test_brightness_anti_poach(phrase):
    ir = _make_recognizer(["set_brightness", "set_volume", "launch_app"])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] != "set_brightness", (
            f"set_brightness wrongly captured {phrase!r}"
        )


# ── volume ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expects", [
    ("volume up", {"direction": "up"}),
    ("turn up the volume", {"direction": "up"}),
    ("volume down", {"direction": "down"}),
    ("turn down the volume", {"direction": "down"}),
    ("louder", {"direction": "up"}),
    ("quieter", {"direction": "down"}),
    ("softer", {"direction": "down"}),
    ("too quiet", {"direction": "up"}),
    ("too loud", {"direction": "down"}),
    ("crank it", {"direction": "up"}),
    ("pump it up", {"direction": "up"}),
    ("tone it down", {"direction": "down"}),
    ("mute", {"direction": "mute"}),
    ("unmute", {"direction": "unmute"}),
    ("set volume to 50", {"percent": 50}),
    ("volume to 80", {"percent": 80}),
    ("volume 30%", {"percent": 30}),
    ("set volume to fifty", {"percent": 50}),
    ("volume to seventy five", {"percent": 75}),
    ("put the volume on full", {"percent": 100}),
])
def test_volume_variants(phrase, expects):
    ir = _make_recognizer(["set_volume"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "set_volume"
    for key, expected in expects.items():
        assert result[0]["args"].get(key) == expected, (
            f"{phrase!r}: args[{key!r}] = {result[0]['args'].get(key)!r}, expected {expected!r}"
        )


@pytest.mark.parametrize("phrase", [
    "raise the question",
    "lower the screen brightness",
    "lower the screen",
    "I want to mute the alarm tomorrow",
    "turn up the heat",
])
def test_volume_anti_poach(phrase):
    ir = _make_recognizer(["set_volume", "set_brightness"])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] != "set_volume", (
            f"set_volume wrongly captured {phrase!r}"
        )


# ── screenshot ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "take a screenshot",
    "Take a screenshot please",
    "grab a screenshot",
    "snap a screenshot",
    "capture my screen",
    "grab the screen",
    "snap a picture of my screen",
    "take a snapshot",
    "snapshot",
    "screenshot",
    "screenshot please",
    "print screen",
    "do a screenshot",
    "get me a screenshot",
])
def test_screenshot_variants(phrase):
    ir = _make_recognizer(["take_screenshot"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "take_screenshot"


@pytest.mark.parametrize("phrase", [
    "I deleted my screenshot folder",
    "where's my screenshot from yesterday",
    "show me the screenshot",
])
def test_screenshot_anti_poach(phrase):
    ir = _make_recognizer(["take_screenshot", "search_file", "search_indexed_files"])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] != "take_screenshot", (
            f"take_screenshot wrongly captured {phrase!r}"
        )


# ── time / date ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool", [
    ("what time is it", "get_time"),
    ("what's the time", "get_time"),
    ("tell me the time", "get_time"),
    ("current time", "get_time"),
    ("got the time", "get_time"),
    ("do you have the time", "get_time"),
    ("time please", "get_time"),
    ("time now", "get_time"),
    ("the time", "get_time"),
    ("what's the date", "get_date"),
    ("what day is it", "get_date"),
    ("what day is today", "get_date"),
    ("what's today", "get_date"),
    ("today's date", "get_date"),
    ("current date", "get_date"),
    ("tell me the date", "get_date"),
    ("date please", "get_date"),
    ("date today", "get_date"),
    ("the date", "get_date"),
])
def test_time_date_variants(phrase, expected_tool):
    ir = _make_recognizer(["get_time", "get_date"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool, (
        f"{phrase!r}: got {result[0]['tool']!r}, expected {expected_tool!r}"
    )


@pytest.mark.parametrize("phrase", [
    "the time of useful consciousness is 30s",     # concept name
    "I have time for one more",                    # idiom
])
def test_time_date_anti_poach(phrase):
    ir = _make_recognizer(["get_time", "get_date", "llm_chat"])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] not in ("get_time", "get_date"), (
            f"time/date wrongly captured {phrase!r}"
        )


# ── screen lock ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "lock screen",
    "lock the screen",
    "lock my screen",
    "lock yourself",
    "lock friday",
    "lock the assistant",
    "lock the console",
    "lock the computer",
    "lock my laptop",
    "lock my pc",
    "lock the machine",
    "lock my workstation",
    "lock my desktop",
    "lock my session",
    "lock me out",
    "lock me down",
    "enable screen lock",
    "engage lock",
    "activate lock",
    "turn on lock",
    "secure the computer",
    "secure my laptop",
    "step away mode",
    "going afk",
    "i'm afk",
    "im going afk",
])
def test_screen_lock_variants(phrase):
    ir = _make_recognizer(["lock_screen", "unlock_screen"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "lock_screen", (
        f"{phrase!r}: got {result[0]['tool']!r}"
    )


@pytest.mark.parametrize("phrase,expected_pin", [
    ("unlock", ""),
    ("unlock screen", ""),
    ("unlock with 1234", "1234"),
    ("unlock 9876", "9876"),
    ("unlock screen pin 1234", "1234"),
    ("i'm back", ""),
])
def test_unlock_variants(phrase, expected_pin):
    ir = _make_recognizer(["lock_screen", "unlock_screen"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "unlock_screen"
    assert result[0]["args"]["pin"] == expected_pin


@pytest.mark.parametrize("phrase", [
    "lock me a meeting on tuesday",          # calendar phrasing
    "block me from notifications for 30 min",  # focus session — must NOT be lock
])
def test_screen_lock_anti_poach(phrase):
    ir = _make_recognizer([
        "lock_screen", "unlock_screen",
        "start_focus_session", "create_calendar_event",
    ])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] != "lock_screen", (
            f"lock_screen wrongly captured {phrase!r}"
        )


# ── focus session ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "start a focus session",
    "begin focus mode",
    "kick off pomodoro for 25 minutes",
    "enter focus mode",
    "do not disturb for an hour",
    "do not disturb for 30 minutes",
    "dnd mode",
    "deep work mode",
    "deep work for 50 minutes",
    "go into quiet mode",
    "silence my notifications for an hour",
    "mute my notifications for 30 minutes",
    "block me from notifications for a while",
    "turn on focus",
    "turn on do not disturb",
    "focus for 25",
    "pomodoro for 25",
])
def test_start_focus_variants(phrase):
    ir = _make_recognizer(["start_focus_session", "end_focus_session", "focus_session_status"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "start_focus_session", (
        f"{phrase!r}: got {result[0]['tool']!r}"
    )


@pytest.mark.parametrize("phrase,expected_tool", [
    ("stop focus session", "end_focus_session"),
    ("end pomodoro", "end_focus_session"),
    ("cancel focus mode", "end_focus_session"),
    ("exit deep work mode", "end_focus_session"),
    ("leave dnd", "end_focus_session"),
    ("disable do not disturb", "end_focus_session"),
    ("focus status", "focus_session_status"),
    ("how much focus is left", "focus_session_status"),
    ("how much time is remaining", "focus_session_status"),
    ("am I still in focus mode", "focus_session_status"),
])
def test_focus_end_status_variants(phrase, expected_tool):
    ir = _make_recognizer(["start_focus_session", "end_focus_session", "focus_session_status"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool, (
        f"{phrase!r}: got {result[0]['tool']!r}, expected {expected_tool!r}"
    )
