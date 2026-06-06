"""Step 4 — long-tail intent parsers for previously unwired tools.

One block per parser; each parametrises positives + anti-poaches.
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
    ds.pending_goal_selection = None
    router.dialog_state = ds
    return IntentRecognizer(router)


# ── weather ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_loc", [
    ("what's the weather", ""),
    ("how's the weather", ""),
    ("weather forecast", ""),
    ("what's the temperature", ""),
    ("is it raining", ""),
    ("is it sunny outside", ""),
    ("will it rain", ""),
    ("how hot is it outside", ""),
    ("how cold is it", ""),
    ("how's it outside", ""),
    ("what's the weather in Nellore", "Nellore"),
    ("weather in Mumbai", "Mumbai"),
    ("weather forecast for New York", "New York"),
    ("what's the temperature in Bengaluru", "Bengaluru"),
    ("is it raining in London", "London"),
])
def test_weather_routes(phrase, expected_loc):
    ir = _make_recognizer(["get_weather"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "get_weather"
    assert result[0]["args"].get("location", "") == expected_loc


@pytest.mark.parametrize("phrase", [
    "open the weather app",   # launch_app
    "weather is great here",  # statement
])
def test_weather_anti_poach(phrase):
    ir = _make_recognizer(["get_weather", "launch_app"])
    result = ir.plan(phrase)
    if result:
        # "open the weather app" should not poach; "weather is great" is fine to skip
        assert result[0]["tool"] != "get_weather" or "open" not in phrase.lower()


# ── goals ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool", [
    ("list my goals", "list_goals"),
    ("show my goals", "list_goals"),
    ("show all goals", "list_goals"),
    ("what are my goals", "list_goals"),
    ("what am I working on", "list_goals"),
    ("goals status", "list_goals"),
    ("pause my goal", "pause_goal"),
    ("put my goal on hold", "pause_goal"),
    ("tell me about my goal", "get_goal_detail"),
])
def test_goals_route(phrase, expected_tool):
    ir = _make_recognizer([
        "list_goals", "create_goal", "complete_goal", "pause_goal", "get_goal_detail",
    ])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool, (
        f"{phrase!r}: got {result[0]['tool']!r}, expected {expected_tool!r}"
    )


@pytest.mark.parametrize("phrase,expected_title", [
    ("I have a new goal: ship the research agent", "ship the research agent"),
    ("add a new goal: read 12 books", "read 12 books"),
    ("create goal: lose 5kg", "lose 5kg"),
    ("new goal: learn rust", "learn rust"),
    ("my goal is to ship by friday", "ship by friday"),
    ("I want to achieve financial independence", "financial independence"),
])
def test_create_goal_extracts_title(phrase, expected_title):
    ir = _make_recognizer(["create_goal"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "create_goal"
    assert expected_title.lower() in result[0]["args"]["title"].lower()


# ── triggers ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool", [
    ("list my triggers", "list_triggers"),
    ("show all triggers", "list_triggers"),
    ("active triggers", "list_triggers"),
    ("watch my clipboard", "add_clipboard_trigger"),
    ("tell me when I copy", "add_clipboard_trigger"),
    ("tell me when my clipboard changes", "add_clipboard_trigger"),
    ("add a clipboard trigger", "add_clipboard_trigger"),
    ("watch ~/Downloads", "add_file_watch_trigger"),
    ("notify me when a new file appears", "add_file_watch_trigger"),
    ("add a file watcher", "add_file_watch_trigger"),
    ("every monday remind me to commit", "add_cron_trigger"),
    ("every 30 minutes run the cleanup", "add_cron_trigger"),
    ("add a scheduled job", "add_cron_trigger"),
    ("remove trigger #3", "remove_trigger"),
    ("delete trigger 5", "remove_trigger"),
    ("cancel my trigger", "remove_trigger"),
])
def test_trigger_routes(phrase, expected_tool):
    ir = _make_recognizer([
        "list_triggers", "remove_trigger",
        "add_clipboard_trigger", "add_cron_trigger", "add_file_watch_trigger",
    ])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool


# ── clipboard ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool", [
    ("what's in my clipboard", "get_clipboard"),
    ("show my clipboard", "get_clipboard"),
    ("read the clipboard", "get_clipboard"),
    ("get clipboard contents", "get_clipboard"),
    ("paste my clipboard", "get_clipboard"),
])
def test_clipboard_get(phrase, expected_tool):
    ir = _make_recognizer(["get_clipboard", "set_clipboard"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool


@pytest.mark.parametrize("phrase,expected_text", [
    ('copy "hello world" to clipboard', "hello world"),
    ("copy to clipboard: my secret token", "my secret token"),
    ("put this to the clipboard: 12345", "12345"),
])
def test_clipboard_set(phrase, expected_text):
    ir = _make_recognizer(["set_clipboard"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "set_clipboard"
    assert result[0]["args"]["text"] == expected_text


def test_clipboard_image_analysis():
    ir = _make_recognizer(["analyze_clipboard_image"])
    result = ir.plan("analyze my clipboard image")
    assert result and result[0]["tool"] == "analyze_clipboard_image"


# ── Home Assistant ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool,expected_entity", [
    ("turn on the kitchen light", "ha_turn_on", "kitchen light"),
    ("turn on the heater", "ha_turn_on", "heater"),
    ("switch on the bedroom lamp", "ha_turn_on", "bedroom lamp"),
    ("activate the porch light", "ha_turn_on", "porch light"),
    ("turn off the kitchen light", "ha_turn_off", "kitchen light"),
    ("switch off the tv", "ha_turn_off", "tv"),
    ("shut off the fan", "ha_turn_off", "fan"),
    ("deactivate the alarm", "ha_turn_off", "alarm"),
])
def test_ha_turn_on_off(phrase, expected_tool, expected_entity):
    ir = _make_recognizer(["ha_turn_on", "ha_turn_off", "ha_set_temperature", "ha_get_state"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool
    assert expected_entity in result[0]["args"].get("entity", "")


@pytest.mark.parametrize("phrase,expected_temp", [
    ("set the AC to 22 degrees", 22),
    ("set the thermostat to 70", 70),
    ("set temperature to 18", 18),
    ("set the heater to 25 degrees", 25),
])
def test_ha_set_temperature(phrase, expected_temp):
    ir = _make_recognizer(["ha_set_temperature"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "ha_set_temperature"
    assert result[0]["args"]["temperature"] == expected_temp


@pytest.mark.parametrize("phrase", [
    "is the front door locked",
    "is the bedroom light on",
    "is the heater running",
    "is the garage open",
])
def test_ha_get_state(phrase):
    ir = _make_recognizer(["ha_get_state"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "ha_get_state"


@pytest.mark.parametrize("phrase", [
    # These are owned by OTHER parsers — must NOT go to HA.
    "turn off voice",
    "turn on focus",
    "turn on do not disturb",
    "lower the volume",
    "turn down the brightness",
])
def test_ha_anti_poach(phrase):
    ir = _make_recognizer([
        "ha_turn_on", "ha_turn_off",
        "set_volume", "set_brightness",
        "start_focus_session", "disable_voice", "enable_voice",
    ])
    result = ir.plan(phrase)
    if result:
        assert result[0]["tool"] not in ("ha_turn_on", "ha_turn_off"), (
            f"HA wrongly captured {phrase!r}"
        )


# ── awareness ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool", [
    ("awareness status", "awareness_status"),
    ("is awareness on", "awareness_status"),
    ("is awareness mode enabled", "awareness_status"),
    ("are you watching my screen", "awareness_status"),
    ("enable awareness mode", "enable_awareness_mode"),
    ("turn on screen awareness", "enable_awareness_mode"),
    ("watch my screen", "enable_awareness_mode"),
    ("start observing my screen", "enable_awareness_mode"),
    ("disable awareness mode", "disable_awareness_mode"),
    ("turn off awareness", "disable_awareness_mode"),
    ("stop watching my screen", "disable_awareness_mode"),
])
def test_awareness_routes(phrase, expected_tool):
    ir = _make_recognizer([
        "awareness_status", "enable_awareness_mode", "disable_awareness_mode",
    ])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool


# ── code eval ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_code_substr", [
    ("evaluate: 2 + 2", "2 + 2"),
    ("run this: print('hello')", "print('hello')"),
    ("execute python: x = 5; print(x)", "x = 5; print(x)"),
    ("eval: sum(range(10))", "sum(range(10))"),
])
def test_code_eval_extracts_code(phrase, expected_code_substr):
    ir = _make_recognizer(["evaluate_code"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "evaluate_code"
    assert expected_code_substr in result[0]["args"]["code"]


# ── notifications ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_text", [
    ("send a notification: standup in 5 minutes", "standup in 5 minutes"),
    ("send me a desktop notification saying coffee break", "coffee break"),
    ("show notification: build done", "build done"),
    ("post notification with text: low battery", "low battery"),
    ("notify me: tests passed", "tests passed"),
    ("ping me: deploy finished", "deploy finished"),
])
def test_send_notification(phrase, expected_text):
    ir = _make_recognizer(["send_notification"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "send_notification"
    assert expected_text in result[0]["args"]["text"]


# ── window query ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "what's my active window",
    "what is the current window",
    "which window is focused",
    "what app am I using",
    "what application is open",
    "what program is focused",
    "currently focused window",
])
def test_active_window(phrase):
    ir = _make_recognizer(["get_active_window"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "get_active_window"


# ── extended security ─────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool,expected_arg", [
    ("dns enum example.com", "dns_enum_owned_domain", ("domain", "example.com")),
    ("dns enumeration for mybox.local.lab", "dns_enum_owned_domain", ("domain", "mybox.local.lab")),
    ("subdomain scan of example.lab.local", "dns_enum_owned_domain", ("domain", "example.lab.local")),
    ("fuzz https://target.lab", "web_directory_enum", ("target", "https://target.lab")),
    ("gobuster on target.local.lab", "web_directory_enum", ("target", "target.local.lab")),
    ("directory scan on target.lab.local", "web_directory_enum", ("target", "target.lab.local")),
])
def test_security_extras(phrase, expected_tool, expected_arg):
    ir = _make_recognizer([
        "host_service_scan", "ping_sweep",
        "dns_enum_owned_domain", "web_directory_enum",
        "compare_scan_results", "security_report_generate",
    ])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool
    arg_key, arg_val = expected_arg
    assert result[0]["args"][arg_key] == arg_val


@pytest.mark.parametrize("phrase,expected_tool", [
    ("compare the last two scans", "compare_scan_results"),
    ("compare scan results", "compare_scan_results"),
    ("diff between scans", "compare_scan_results"),
    ("what changed since the last scan", "compare_scan_results"),
    ("generate a security report", "security_report_generate"),
    ("create a pentest report", "security_report_generate"),
    ("write up the recon findings", "security_report_generate"),
])
def test_security_meta(phrase, expected_tool):
    ir = _make_recognizer(["compare_scan_results", "security_report_generate"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool


# ── extended vision ──────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_tool", [
    ("where is the submit button", "find_ui_element"),
    ("find the close icon", "find_ui_element"),
    ("compare these two screenshots", "compare_screenshots"),
    ("diff my screenshots", "compare_screenshots"),
    ("debug my code", "debug_code_screenshot"),
    ("what's wrong with this error", "debug_code_screenshot"),
    ("what have I been doing", "recent_screen_activity"),
    ("recent screen activity", "recent_screen_activity"),
    ("roast my desktop", "roast_desktop"),
    ("roast my wallpaper", "roast_desktop"),
    ("review my design", "review_design"),
    ("critique my mockup", "review_design"),
    ("explain this meme", "explain_meme"),
    ("I don't get the meme", "explain_meme"),
    ("describe this picture", "describe_image"),
    ("what's in this image", "describe_image"),
])
def test_vision_extras(phrase, expected_tool):
    ir = _make_recognizer([
        "find_ui_element", "compare_screenshots", "debug_code_screenshot",
        "recent_screen_activity", "roast_desktop", "review_design",
        "explain_meme", "describe_image",
        "summarize_screen", "analyze_screen", "read_text_from_image",
    ])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool


# ── world monitor ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "show world monitor",
    "world monitor news",
    "global watch news",
])
def test_world_monitor(phrase):
    ir = _make_recognizer(["get_world_monitor_news"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "get_world_monitor_news"


# ── all parsers are inert when their tool is absent ───────────────────────


@pytest.mark.parametrize("tool_to_omit,probe_phrase", [
    ("get_weather", "what's the weather"),
    ("list_goals", "list my goals"),
    ("list_triggers", "list my triggers"),
    ("get_clipboard", "what's in my clipboard"),
    ("ha_turn_on", "turn on the kitchen light"),
    ("awareness_status", "is awareness on"),
    ("evaluate_code", "evaluate: 2 + 2"),
    ("send_notification", "send a notification: hi"),
    ("get_active_window", "what's my active window"),
])
def test_parsers_inert_when_tool_absent(tool_to_omit, probe_phrase):
    """Each new parser must be a no-op when its capability isn't loaded."""
    ir = _make_recognizer([])  # NO tools at all
    result = ir.plan(probe_phrase)
    if result:
        # Either no plan or no plan with the absent tool.
        assert result[0]["tool"] != tool_to_omit
