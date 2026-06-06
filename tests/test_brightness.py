"""Track 6.4 — set_brightness honest-failure tests.

The capability must NEVER claim success when no backend actually
applied the change. This is the failure mode that let the LLM fabricate
"Brightness set to 60." in the user's session log.
"""
from __future__ import annotations

import pytest

from modules.system_control.brightness import _coerce_percent, set_brightness


def test_coerce_percent_accepts_int_and_string():
    assert _coerce_percent(50) == 50
    assert _coerce_percent("60") == 60
    assert _coerce_percent("60%") == 60
    assert _coerce_percent("set brightness to 75") == 75


def test_coerce_percent_rejects_out_of_range():
    assert _coerce_percent(-1) is None
    assert _coerce_percent(150) is None
    assert _coerce_percent(101) is None


def test_coerce_percent_rejects_garbage():
    assert _coerce_percent("not a number") is None
    assert _coerce_percent(None) is None
    assert _coerce_percent([]) is None


def test_set_brightness_invalid_percent_returns_help():
    msg = set_brightness("banana")
    assert "between 0 and 100" in msg


def test_set_brightness_does_not_lie_on_failure(monkeypatch):
    """If every backend fails, the reply must say so — not 'Brightness set'."""
    # Force `shutil.which` to report neither brightnessctl nor light.
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    # Force the sysfs path to a non-existent location.
    import glob as _glob
    monkeypatch.setattr(_glob, "glob", lambda pattern: [])
    msg = set_brightness(60)
    assert "couldn't change the brightness" in msg.lower()
    assert "brightness set to" not in msg.lower()


def test_set_brightness_success_when_brightnessctl_exists(monkeypatch):
    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/brightnessctl" if name == "brightnessctl" else None)

    class _OK:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _OK())
    msg = set_brightness(40)
    assert msg == "Brightness set to 40%."


# ---------------------------------------------------------------------------
# Desktop-environment refresh (Step 2 of 2026-05-23 plan)
# ---------------------------------------------------------------------------

def test_notify_desktop_environment_is_called_on_success(monkeypatch):
    """After a successful brightness change we must nudge the desktop's
    panel widget so the slider repaints. The hardware change itself is
    instant; the indicator was stale because no DE got told."""
    import shutil
    import subprocess
    from modules.system_control import brightness as br

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/brightnessctl" if name == "brightnessctl" else None)

    class _OK:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _OK())

    notify_calls = []
    monkeypatch.setattr(br, "_notify_desktop_environment", lambda t: notify_calls.append(t))

    msg = br.set_brightness(40)
    assert msg == "Brightness set to 40%."
    assert notify_calls == [40], "DE-refresh helper must fire after successful set"


def test_notify_desktop_environment_skipped_on_failure(monkeypatch):
    """If every backend fails we must NOT notify (the slider should keep
    showing the old value because the hardware didn't change either)."""
    import shutil
    import glob as _glob
    from modules.system_control import brightness as br

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(_glob, "glob", lambda pattern: [])

    notify_calls = []
    monkeypatch.setattr(br, "_notify_desktop_environment", lambda t: notify_calls.append(t))

    msg = br.set_brightness(60)
    assert "couldn't change" in msg.lower()
    assert notify_calls == [], "must NOT fake a DE refresh when nothing changed"


def test_notify_helpers_swallow_missing_tools(monkeypatch):
    """If gdbus/qdbus/xfconf-query are absent, each helper returns False
    without raising; the chain caller never crashes."""
    import shutil
    from modules.system_control import brightness as br

    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert br._notify_gnome(50) is False
    assert br._notify_kde(50) is False
    assert br._notify_xfce(50) is False
    # And the chain doesn't raise.
    br._notify_desktop_environment(50)


def test_windows_uses_wmi_backend(monkeypatch):
    """On Windows, set_brightness drives the panel via WMI/PowerShell and
    reports success — it must NOT depend on brightnessctl/light/sysfs."""
    import shutil
    import subprocess
    from modules.system_control import brightness as br

    monkeypatch.setattr(br.platform, "system", lambda: "Windows")
    monkeypatch.setattr(shutil, "which", lambda name: "powershell.exe" if name == "powershell" else None)

    captured = {}

    def _capture_run(args, **kwargs):
        captured["args"] = list(args)

        class _OK:
            returncode = 0
            stdout = "OK"
            stderr = ""

        return _OK()

    monkeypatch.setattr(subprocess, "run", _capture_run)
    msg = br.set_brightness(55)
    assert msg == "Brightness set to 55%."
    assert captured["args"][0] == "powershell"
    assert "WmiSetBrightness" in captured["args"][-1]
    assert "Brightness=55" in captured["args"][-1]


def test_windows_failure_is_honest(monkeypatch):
    """If WMI fails on Windows (e.g. a desktop with no internal panel), the
    reply must say so with a Windows-appropriate hint — never fake success."""
    import shutil
    import subprocess
    import glob as _glob
    from modules.system_control import brightness as br

    monkeypatch.setattr(br.platform, "system", lambda: "Windows")
    monkeypatch.setattr(shutil, "which", lambda name: "powershell.exe" if name == "powershell" else None)
    monkeypatch.setattr(_glob, "glob", lambda pattern: [])

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "no WmiMonitorBrightnessMethods instance"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Fail())
    msg = br.set_brightness(60)
    assert "couldn't change the brightness" in msg.lower()
    assert "brightness set to" not in msg.lower()
    assert "external monitor" in msg.lower()


def test_notify_gnome_invokes_gdbus(monkeypatch):
    """Verify the exact dbus payload — wrong path/interface/property names
    fail silently on the running system and we'd never know.
    """
    import shutil
    import subprocess
    from modules.system_control import brightness as br

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/gdbus" if name == "gdbus" else None)

    captured = {}

    def _capture_run(args, **kwargs):
        captured["args"] = list(args)

        class _OK:
            returncode = 0
            stdout = ""
            stderr = ""

        return _OK()

    monkeypatch.setattr(subprocess, "run", _capture_run)
    assert br._notify_gnome(80) is True
    args = captured["args"]
    assert args[0] == "gdbus"
    assert "--dest" in args and "org.gnome.SettingsDaemon.Power" in args
    assert "Brightness" in args
    assert "<int32 80>" in args
