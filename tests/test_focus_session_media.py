"""Focus-session side-effect coverage (2026-05-26).

Pins the "focus session was allowing media" fix: pausing must reach EVERY
MPRIS player on the session bus (Spotify, VLC, browsers, native players),
not just FRIDAY's own Playwright browser. These tests mock the subprocess /
shutil layer so they run with no real D-Bus or desktop present.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.reasoning.agentic_services.focus_mode import FocusModeWorkflow


LIST_NAMES_STDOUT = (
    "([':1.0', 'org.freedesktop.DBus', "
    "'org.mpris.MediaPlayer2.spotify', "
    "'org.mpris.MediaPlayer2.vlc', "
    "'org.mpris.MediaPlayer2.chromium.instance123', "
    "'org.mpris.MediaPlayer2.chromium.instance123', "  # duplicate → deduped
    "':1.42'],)"
)


def _wf(browser=None):
    app = MagicMock()
    app.browser_media_service = browser
    app.event_bus = None
    return FocusModeWorkflow(app)


def _fake_run_factory(record):
    """Returns a subprocess.run stand-in that records argv and answers
    ListNames with our fixture, everything else with rc=0."""
    def _fake_run(argv, **kwargs):
        record.append(argv)
        if "ListNames" in argv[-1]:
            return SimpleNamespace(returncode=0, stdout=LIST_NAMES_STDOUT, stderr="")
        return SimpleNamespace(returncode=0, stdout="(@mb true,)", stderr="")
    return _fake_run


def test_mpris_players_parses_and_dedupes():
    calls = []
    with patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="/usr/bin/gdbus"), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run", _fake_run_factory(calls)):
        players = _wf()._mpris_players()
    assert players == [
        "org.mpris.MediaPlayer2.spotify",
        "org.mpris.MediaPlayer2.vlc",
        "org.mpris.MediaPlayer2.chromium.instance123",
    ]


def test_pause_system_media_pauses_every_player():
    calls = []
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="/usr/bin/gdbus"), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run", _fake_run_factory(calls)):
        count = _wf()._pause_system_media()
    assert count == 3
    pause_targets = [
        argv[argv.index("--dest") + 1]
        for argv in calls
        if "org.mpris.MediaPlayer2.Player.Pause" in argv
    ]
    assert pause_targets == [
        "org.mpris.MediaPlayer2.spotify",
        "org.mpris.MediaPlayer2.vlc",
        "org.mpris.MediaPlayer2.chromium.instance123",
    ]


def test_pause_media_hits_browser_and_system():
    """_pause_media must drive BOTH the in-process browser and the bus sweep."""
    browser = MagicMock()
    calls = []
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="/usr/bin/gdbus"), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run", _fake_run_factory(calls)):
        _wf(browser=browser)._pause_media()
    browser.fast_media_command.assert_called_once_with("pause")
    assert any("ListNames" in argv[-1] for argv in calls), "MPRIS sweep was not attempted"


def test_pause_system_media_noop_without_gdbus():
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value=None), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run") as run:
        assert _wf()._pause_system_media() == 0
    run.assert_not_called()


def test_pause_system_media_uses_smtc_on_windows():
    """Windows now pauses every SMTC session via WinRT/PowerShell — it must
    invoke powershell and report the count the script printed."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="2\n", stderr="")

    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Windows"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run", _fake_run):
        count = _wf()._pause_system_media()
    assert count == 2
    assert calls and calls[0][0] == "powershell"
    assert "TryPauseAsync" in calls[0][-1]


def test_pause_system_media_noop_on_windows_without_powershell():
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Windows"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value=None), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run") as run:
        assert _wf()._pause_system_media() == 0
    run.assert_not_called()


def test_notifications_supported_per_platform():
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Windows"):
        assert FocusModeWorkflow._notifications_supported() is True
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="/usr/bin/gsettings"):
        assert FocusModeWorkflow._notifications_supported() is True
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value=None):
        assert FocusModeWorkflow._notifications_supported() is False
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Darwin"):
        assert FocusModeWorkflow._notifications_supported() is False


def test_set_notifications_dispatches_to_windows(monkeypatch):
    """On Windows, _set_notifications routes to the registry path, not gsettings."""
    wf = _wf()
    captured = {}
    monkeypatch.setattr(
        "core.reasoning.agentic_services.focus_mode.platform.system",
        lambda: "Windows",
    )
    monkeypatch.setattr(
        FocusModeWorkflow, "_set_notifications_windows",
        staticmethod(lambda enabled: captured.setdefault("enabled", enabled) or "1"),
    )
    assert wf._set_notifications(False) == "1"
    assert captured["enabled"] is False


def test_pause_media_survives_browser_failure():
    browser = MagicMock()
    browser.fast_media_command.side_effect = RuntimeError("browser down")
    calls = []
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="/usr/bin/gdbus"), \
         patch("core.reasoning.agentic_services.focus_mode.subprocess.run", _fake_run_factory(calls)):
        _wf(browser=browser)._pause_media()  # must not raise
    assert any("ListNames" in argv[-1] for argv in calls), "sweep skipped after browser error"
