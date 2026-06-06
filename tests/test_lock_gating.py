"""Lock gating (denylist) + OS-lock state monitor + Telegram notifications.

2026-05-25: when the OS screen is locked, screen-dependent tools (browser
automation, app/file launching, screenshots, vision) must be refused while
everything else (chat, memory, email, research, web search, …) still works;
lock/unlock transitions are logged to Telegram.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.screen_lock import ScreenLock, is_blocked_when_locked, BLOCKED_WHEN_LOCKED
from core.lock_monitor import LockStateMonitor


# ── denylist semantics ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "open_browser_url", "search_google", "play_youtube_music",
    "browser_media_control", "launch_app", "open_file", "open_folder",
    "take_screenshot", "analyze_screen", "summarize_screen", "find_ui_element",
    "start_dictation", "get_active_window", "web_crawl",
])
def test_screen_dependent_tools_blocked_when_locked(name):
    lock = ScreenLock()
    lock.set_locked(True)
    assert lock.is_allowed(name) is False, f"{name} should be blocked while locked"


@pytest.mark.parametrize("name", [
    "llm_chat", "check_unread_emails", "summarize_inbox", "research_topic",
    "web_search", "quick_answer", "get_weather", "recall_personal_fact",
    "save_note", "list_reminders", "read_file", "get_cpu_ram", "set_brightness",
])
def test_non_screen_tools_allowed_when_locked(name):
    lock = ScreenLock()
    lock.set_locked(True)
    assert lock.is_allowed(name) is True, f"{name} should stay allowed while locked"


def test_everything_allowed_when_unlocked():
    lock = ScreenLock()
    assert lock.is_locked() is False
    for name in BLOCKED_WHEN_LOCKED:
        assert lock.is_allowed(name) is True


def test_keyword_fallback_catches_unlisted_gui_tools():
    assert is_blocked_when_locked("take_fancy_screenshot_v2") is True
    assert is_blocked_when_locked("new_browser_thing") is True
    assert is_blocked_when_locked("send_email") is False


def test_set_locked_reports_change():
    lock = ScreenLock()
    assert lock.set_locked(True) is True   # changed
    assert lock.set_locked(True) is False  # no change
    assert lock.set_locked(False) is True


# ── executor gate uses the denylist ───────────────────────────────────────

def test_executor_refuses_blocked_tool_while_locked():
    from core.capability_registry import CapabilityRegistry, CapabilityExecutor
    reg = CapabilityRegistry()
    reg.register_tool({"name": "launch_app", "description": "x", "parameters": {}},
                      lambda r, a: "launched", {})
    ex = CapabilityExecutor(reg)
    lock = ScreenLock()
    lock.set_locked(True)
    ex.screen_lock = lock
    res = ex.execute("launch_app", "open firefox", {})
    assert res.ok is True
    assert "locked" in res.output.lower()
    assert "launched" not in res.output.lower()


def test_executor_allows_chat_while_locked():
    from core.capability_registry import CapabilityRegistry, CapabilityExecutor
    reg = CapabilityRegistry()
    reg.register_tool({"name": "llm_chat", "description": "x", "parameters": {}},
                      lambda r, a: "hello there", {})
    ex = CapabilityExecutor(reg)
    lock = ScreenLock()
    lock.set_locked(True)
    ex.screen_lock = lock
    res = ex.execute("llm_chat", "hi", {})
    assert res.output == "hello there"


# ── monitor: state mirroring + Telegram notifications ──────────────────────

def _app_with_telegram():
    app = MagicMock()
    app.comms.telegram.available = True
    sent = []
    app.comms.telegram.send.side_effect = lambda msg, *a, **k: sent.append(msg)
    return app, sent


def test_note_locked_sets_state_and_notifies_once():
    app, sent = _app_with_telegram()
    lock = ScreenLock()
    mon = LockStateMonitor(app, lock)
    mon.note_locked()
    assert lock.is_locked() is True
    assert len(sent) == 1 and "lock" in sent[0].lower()
    # Idempotent — re-locking doesn't double-notify.
    mon.note_locked()
    assert len(sent) == 1


def test_monitor_notifies_on_unlock_transition():
    app, sent = _app_with_telegram()
    lock = ScreenLock()
    mon = LockStateMonitor(app, lock)
    mon._set_state(True, source="os")
    mon._set_state(False, source="os")
    assert lock.is_locked() is False
    assert len(sent) == 2
    assert "unlock" in sent[1].lower()


def test_monitor_no_notify_without_telegram():
    app = MagicMock()
    app.comms.telegram.available = False
    lock = ScreenLock()
    mon = LockStateMonitor(app, lock)
    mon.note_locked()  # must not raise
    assert lock.is_locked() is True


def test_linux_locked_hint_parsing():
    app, _ = _app_with_telegram()
    mon = LockStateMonitor(app, ScreenLock())
    fake = MagicMock(stdout="LockedHint=yes\n")
    with patch("shutil.which", return_value="/usr/bin/loginctl"), \
         patch.dict("os.environ", {"XDG_SESSION_ID": "2"}, clear=False), \
         patch("subprocess.run", return_value=fake):
        assert mon._linux_locked_hint() is True
    fake.stdout = "LockedHint=no\n"
    with patch("shutil.which", return_value="/usr/bin/loginctl"), \
         patch.dict("os.environ", {"XDG_SESSION_ID": "2"}, clear=False), \
         patch("subprocess.run", return_value=fake):
        assert mon._linux_locked_hint() is False
