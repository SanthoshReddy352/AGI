"""Real OS session lock (modules/system_control/os_lock.py) + the
`lock_screen` capability routing to it.

2026-05-25: "/lock" and "lock the screen" used to only toggle FRIDAY's
internal PIN gate; the user wanted the actual laptop/desktop to lock.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import modules.system_control.os_lock as ol


def test_lock_uses_first_available_linux_locker():
    calls = []

    def fake_which(name):
        return f"/usr/bin/{name}" if name == "loginctl" else None

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return MagicMock(returncode=0, stderr="")

    with patch("platform.system", return_value="Linux"), \
         patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False), \
         patch("shutil.which", side_effect=fake_which), \
         patch("subprocess.run", side_effect=fake_run):
        ok, msg = ol.lock_os_session()

    assert ok and "locked" in msg.lower()
    assert calls and calls[0][0].endswith("loginctl")


def test_lock_reports_failure_when_no_locker():
    with patch("platform.system", return_value="Linux"), \
         patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False), \
         patch("shutil.which", return_value=None):
        ok, msg = ol.lock_os_session()
    assert ok is False and "couldn't lock" in msg.lower()


def test_lock_falls_through_to_second_locker_on_nonzero_exit():
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("loginctl", "xdg-screensaver") else None

    def fake_run(cmd, **kw):
        # loginctl fails (rc=1), xdg-screensaver succeeds.
        rc = 1 if cmd[0].endswith("loginctl") else 0
        return MagicMock(returncode=rc, stderr="busy")

    with patch("platform.system", return_value="Linux"), \
         patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False), \
         patch("shutil.which", side_effect=fake_which), \
         patch("subprocess.run", side_effect=fake_run):
        ok, msg = ol.lock_os_session()
    assert ok is True


def test_capability_handler_calls_os_lock():
    """Phase 3: with the confirmation guard satisfied (_confirmed=True, the
    state the guard re-dispatches with), the handler locks for real."""
    from modules.system_control.plugin import SystemControlPlugin
    plugin = SystemControlPlugin.__new__(SystemControlPlugin)  # skip __init__
    plugin.app = MagicMock()
    plugin.app.confirmation_guard = None  # no guard wired → direct lock
    with patch("modules.system_control.os_lock.lock_os_session",
               return_value=(True, "Screen locked.")) as m:
        out = plugin.handle_lock_screen("lock the screen", {})
    m.assert_called_once()
    assert "locked" in out.lower()


def test_lock_screen_arms_confirmation_first():
    """Phase 3: the first 'lock the screen' arms the confirmation guard
    (preview + prompt) and does NOT lock until confirmed."""
    from modules.system_control.plugin import SystemControlPlugin
    plugin = SystemControlPlugin.__new__(SystemControlPlugin)
    plugin.app = MagicMock()
    plugin.app.confirmation_guard.needs_confirmation.return_value = True
    plugin.app.confirmation_guard.arm.return_value = "I'll lock the screen. Shall I go ahead?"
    with patch("modules.system_control.os_lock.lock_os_session",
               return_value=(True, "Screen locked.")) as m:
        out = plugin.handle_lock_screen("lock the screen", {})
    m.assert_not_called()  # armed, not locked
    plugin.app.confirmation_guard.arm.assert_called_once()
    assert "go ahead" in out.lower()


def test_unlock_handler_explains_system_password():
    from modules.system_control.plugin import SystemControlPlugin
    plugin = SystemControlPlugin.__new__(SystemControlPlugin)
    plugin.app = MagicMock()
    out = plugin.handle_unlock_screen("unlock the screen", {})
    assert "system password" in out.lower()
