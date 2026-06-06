"""FocusModeWorkflow — agentic service for distraction-blocked focus sessions.

Track 5.2e: this is NOT a linear slot-fill workflow. It is a stateful
background manager — module-level mutable state (`_focus_active`,
`_focus_state`), a live `threading.Timer`, and shell-out side effects
(`gsettings` + browser media coordination). Templating it would require
the YAML model to grow into a programming language. It lives under
`core/reasoning/agentic_services/` to make that distinction structural.

When started, the service:
  • mutes desktop notifications (GNOME `gsettings` if available),
  • pauses any active browser-media session via the browser worker,
  • starts a single end-of-session timer (default 25 min, capped at 120),
  • restores notifications and announces when the timer fires.

A second focus utterance while a session is active either reports the
remaining time or, if the user said "stop/end focus", ends it early.

The class name is kept as `FocusModeWorkflow` (and `name = "focus_mode"`)
for state-storage and dispatch compatibility with `WorkflowOrchestrator`.
"""
from __future__ import annotations

import re
import shutil
import platform
import subprocess
import threading
import time

from core.logger import logger


_active_timer: threading.Timer | None = None
_focus_active: bool = False
_focus_state: dict = {
    "started_at": 0.0,
    "ends_at": 0.0,
    "minutes": 0,
    "previous_show_banners": None,
}


class FocusModeWorkflow:
    name = "focus_mode"

    _START_PATTERNS = (
        re.compile(r"\b(?:focus\s+mode|do\s+not\s+disturb|pomodoro|focus\s+for|concentrate)\b", re.IGNORECASE),
        re.compile(r"\bstart\s+(?:a\s+)?focus(?:\s+session)?\b", re.IGNORECASE),
        re.compile(r"\b(?:don'?t\s+disturb|no\s+interruptions?)\b", re.IGNORECASE),
    )
    _STOP_PATTERNS = (
        re.compile(r"\b(?:stop\s+focus|end\s+focus|exit\s+focus|disable\s+focus|focus\s+off|cancel\s+focus)\b", re.IGNORECASE),
        re.compile(r"\b(?:stop|end|cancel)\s+(?:my\s+)?focus\s+session\b", re.IGNORECASE),
    )
    _STATUS_PATTERNS = (
        re.compile(r"\b(?:focus\s+(?:status|left|remaining|time)|how\s+much\s+focus|when\s+does\s+focus\s+end)\b", re.IGNORECASE),
    )
    _DURATION_RE = re.compile(
        r"(\d+)\s*(?:min(?:ute)?s?|m\b|hour(?:s)?|hr(?:s)?|h\b)",
        re.IGNORECASE,
    )

    def __init__(self, app):
        self._app = app

    # ------------------------------------------------------------------
    # Workflow protocol
    # ------------------------------------------------------------------

    def should_start(self, user_text: str, context=None) -> bool:
        return (
            any(p.search(user_text) for p in self._START_PATTERNS)
            or any(p.search(user_text) for p in self._STOP_PATTERNS)
            or any(p.search(user_text) for p in self._STATUS_PATTERNS)
        )

    def can_continue(self, user_text: str, state: dict, context=None) -> bool:
        return any(p.search(user_text) for p in self._STOP_PATTERNS) or any(
            p.search(user_text) for p in self._STATUS_PATTERNS
        )

    def run(self, user_text: str, session_id: str, context=None):
        from core.workflow_orchestrator import WorkflowResult  # noqa: PLC0415

        if any(p.search(user_text) for p in self._STOP_PATTERNS):
            response = self._stop()
            return WorkflowResult(
                workflow_name=self.name,
                handled=True,
                response=response,
                state={"step": "ended"},
            )

        if any(p.search(user_text) for p in self._STATUS_PATTERNS):
            return WorkflowResult(
                workflow_name=self.name,
                handled=True,
                response=self._status(),
                state=dict(_focus_state),
            )

        minutes = self._extract_minutes(user_text)
        return WorkflowResult(
            workflow_name=self.name,
            handled=True,
            response=self._start(minutes, session_id),
            state={"step": "active", "minutes": minutes, "started_at": time.time()},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_minutes(self, user_text: str) -> int:
        match = self._DURATION_RE.search(user_text)
        if not match:
            return 25
        value = int(match.group(1))
        unit = match.group(0).lower()
        if "h" in unit and "m" not in unit.split("h", 1)[0]:
            value *= 60
        return max(1, min(value, 240))

    def _start(self, minutes: int, session_id: str) -> str:
        global _focus_active, _active_timer, _focus_state

        if _focus_active:
            remaining = max(0, int(_focus_state.get("ends_at", 0) - time.time()))
            return (
                f"Focus mode is already active with about {remaining // 60} minute(s) left. "
                "Say 'Friday end focus' to stop it early."
            )

        _focus_active = True
        previous_banners = self._set_notifications(False)
        self._pause_media()

        _focus_state = {
            "started_at": time.time(),
            "ends_at": time.time() + minutes * 60,
            "minutes": minutes,
            "previous_show_banners": previous_banners,
        }

        if _active_timer is not None:
            _active_timer.cancel()
        _active_timer = threading.Timer(minutes * 60, self._end_focus, args=(session_id,))
        _active_timer.daemon = True
        _active_timer.start()

        self._publish("focus_mode_changed", {"active": True, "duration_minutes": minutes})
        # Stay honest about notifications: only claim Do Not Disturb where we
        # can actually toggle it (gsettings on Linux, the toast switch on
        # Windows). The media stop + browser-media block run everywhere.
        if self._notifications_supported():
            state_line = (
                "Do Not Disturb is on and I've stopped all playing media. "
                "Browser media like YouTube is blocked until we're done"
            )
        else:
            state_line = (
                "I've stopped all playing media, and browser media like YouTube "
                "is blocked until we're done"
            )
        return (
            f"Focus mode activated for {minutes} minute(s), sir. "
            f"{state_line}. I'll let you know when time is up."
        )

    def _stop(self) -> str:
        global _focus_active, _active_timer, _focus_state
        if not _focus_active:
            return "Focus mode isn't active right now."
        if _active_timer is not None:
            _active_timer.cancel()
            _active_timer = None
        elapsed = max(0, int(time.time() - _focus_state.get("started_at", time.time())))
        self._restore_notifications()
        _focus_active = False
        _focus_state = {
            "started_at": 0.0,
            "ends_at": 0.0,
            "minutes": 0,
            "previous_show_banners": None,
        }
        self._publish("focus_mode_changed", {"active": False, "elapsed_minutes": elapsed // 60})
        return f"Ended focus mode after {elapsed // 60} minute(s). Notifications are back on."

    def _status(self) -> str:
        if not _focus_active:
            return "Focus mode isn't running."
        remaining = max(0, int(_focus_state.get("ends_at", 0) - time.time()))
        if remaining <= 0:
            return "Focus mode just finished."
        if remaining < 60:
            return f"About {remaining} second(s) left in this focus session."
        return f"About {remaining // 60} minute(s) left in this focus session."

    def _end_focus(self, session_id: str) -> None:
        global _focus_active, _focus_state, _active_timer
        if not _focus_active:
            return
        self._restore_notifications()
        _focus_active = False
        _active_timer = None
        minutes_done = _focus_state.get("minutes", 0)
        _focus_state = {
            "started_at": 0.0,
            "ends_at": 0.0,
            "minutes": 0,
            "previous_show_banners": None,
        }
        self._publish("focus_mode_changed", {"active": False, "elapsed_minutes": minutes_done})
        self._publish(
            "voice_response",
            f"Focus session complete after {minutes_done} minute(s), sir. Time to take a short break.",
        )

    # ------------------------------------------------------------------
    # System hooks
    # ------------------------------------------------------------------

    @staticmethod
    def _notifications_supported() -> bool:
        """True where we can actually toggle desktop notifications: GNOME via
        gsettings (Linux) or the toast registry switch (Windows). macOS has no
        equivalent we drive, so focus there is timer + media-pause only."""
        system = platform.system()
        if system == "Linux":
            return bool(shutil.which("gsettings"))
        if system == "Windows":
            return True
        return False

    def _set_notifications(self, enabled: bool):
        """Toggle desktop notifications off (focus start) / on (focus end).

        Returns an opaque "previous value" stashed in ``_focus_state`` and
        handed back to :meth:`_restore_notifications`. Platform-dispatched:
        GNOME ``gsettings`` on Linux, the ``ToastEnabled`` registry switch
        (Windows' "do not disturb" for toast banners) on Windows.
        """
        if platform.system() == "Windows":
            return self._set_notifications_windows(enabled)
        return self._set_notifications_linux(enabled)

    @staticmethod
    def _set_notifications_windows(enabled: bool):
        """Flip HKCU ``…\\PushNotifications\\ToastEnabled`` — 0 suppresses all
        toast banners (the closest reliable, reversible 'do not disturb'
        without an undocumented Focus-Assist API). Returns the previous value
        ('0'/'1') or None."""
        try:
            import winreg  # noqa: PLC0415 - Windows-only
        except Exception:
            return None
        key_path = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"
        previous = None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as k:
                previous = str(winreg.QueryValueEx(k, "ToastEnabled")[0])
        except Exception:
            previous = None
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "ToastEnabled", 0, winreg.REG_DWORD, 1 if enabled else 0)
        except Exception as exc:
            logger.warning("[focus] could not set Windows ToastEnabled: %s", exc)
        return previous

    def _set_notifications_linux(self, enabled: bool):
        global _focus_state
        if not shutil.which("gsettings"):
            # Expected on Windows/macOS — don't cry wolf every focus turn.
            if platform.system() == "Linux":
                logger.warning("[focus] gsettings not found — notifications NOT muted")
            else:
                logger.debug(
                    "[focus] notification muting not supported on %s; timer + media-pause only",
                    platform.system(),
                )
            return None
        try:
            previous = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
                capture_output=True, text=True, timeout=2, check=False,
                encoding="utf-8", errors="replace",
            ).stdout.strip()
        except Exception:
            previous = None
        try:
            result = subprocess.run(
                [
                    "gsettings", "set", "org.gnome.desktop.notifications",
                    "show-banners", "true" if enabled else "false",
                ],
                capture_output=True, text=True, check=False, timeout=2,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                # Most common cause: the process has no session D-Bus
                # (DBUS_SESSION_BUS_ADDRESS unset) so the write is a silent
                # no-op and notifications keep popping up.
                logger.warning(
                    "[focus] gsettings set show-banners failed (rc=%s): %s",
                    result.returncode, (result.stderr or "").strip(),
                )
        except Exception as exc:
            logger.warning("[focus] gsettings set show-banners raised: %s", exc)
        return previous

    def _restore_notifications(self) -> None:
        global _focus_state
        previous = _focus_state.get("previous_show_banners")
        if platform.system() == "Windows":
            self._restore_notifications_windows(previous)
            return
        if previous is None:
            self._set_notifications(True)
            return
        if not shutil.which("gsettings"):
            return
        try:
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", previous],
                check=False, timeout=2,
            )
        except Exception:
            pass

    @staticmethod
    def _restore_notifications_windows(previous) -> None:
        """Restore the toast switch. With no captured previous value, default
        to enabled (1) — better to over-restore notifications than to leave
        the user silently muted after a focus session."""
        try:
            import winreg  # noqa: PLC0415 - Windows-only
        except Exception:
            return
        try:
            value = int(previous) if previous not in (None, "") else 1
        except (TypeError, ValueError):
            value = 1
        key_path = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "ToastEnabled", 0, winreg.REG_DWORD, value)
        except Exception as exc:
            logger.warning("[focus] could not restore Windows ToastEnabled: %s", exc)

    def _pause_media(self) -> None:
        """Pause everything that could make noise during a focus session.

        Two passes, because ``fast_media_command`` only reaches FRIDAY's own
        Playwright browser — it never sees Spotify, VLC, a normal Firefox tab,
        or any other app. The MPRIS sweep covers those. Media is intentionally
        NOT auto-resumed on focus end: re-blasting audio when a timer fires
        (possibly while the user has stepped away) is worse than leaving it
        paused for a one-tap resume.
        """
        # 1. FRIDAY's own browser (Playwright) — instant in-process pause.
        service = getattr(self._app, "browser_media_service", None)
        fast = getattr(service, "fast_media_command", None) if service else None
        if fast is not None:
            try:
                fast("pause")
            except Exception as exc:
                logger.debug("[focus] browser media pause failed: %s", exc)
        # 2. Every other media player on the session bus.
        self._pause_system_media()

    def _pause_system_media(self) -> int:
        """Pause every media player on the system. Returns how many were asked
        to pause. Linux: each MPRIS player on the session bus via ``gdbus``
        (ships with glib, no ``playerctl`` needed). Windows: every System Media
        Transport Controls session via WinRT (Spotify, Edge/Chrome, the Media
        Player app, …)."""
        if platform.system() == "Windows":
            return self._pause_windows_media()
        if not shutil.which("gdbus"):
            return 0
        paused = 0
        for name in self._mpris_players():
            if self._mpris_pause(name):
                paused += 1
        if paused:
            logger.info("[focus] paused %d MPRIS media player(s)", paused)
        return paused

    @staticmethod
    def _pause_windows_media() -> int:
        """Pause every SMTC session on Windows via WinRT, driven from
        PowerShell. ``TryPauseAsync`` *pauses* (it does not toggle), so it
        won't accidentally resume already-paused media — important because
        FRIDAY's own browser is paused just before this sweep. Returns the
        number of sessions paused (parsed from the script's final line)."""
        if not shutil.which("powershell"):
            return 0
        ps = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null; "
            "$ext=[System.WindowsRuntimeSystemExtensions].GetMethods()|"
            "?{$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and "
            "$_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'}|"
            "Select-Object -First 1; "
            "function Await($op,$t){$m=$ext.MakeGenericMethod($t);"
            "$task=$m.Invoke($null,@($op));$task.Wait(-1)|Out-Null;$task.Result}; "
            "[void][Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,"
            "Windows.Media.Control,ContentType=WindowsRuntime]; "
            "$mgr=Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]"
            "::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]); "
            "$n=0; foreach($s in $mgr.GetSessions()){try{[void](Await ($s.TryPauseAsync()) ([bool]));$n++}catch{}}; "
            "$n"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            logger.debug("[focus] Windows media pause failed: %s", exc)
            return 0
        out = (result.stdout or "").strip()
        try:
            paused = int(out.splitlines()[-1]) if out else 0
        except (ValueError, IndexError):
            paused = 0
        if paused:
            logger.info("[focus] paused %d Windows media session(s)", paused)
        return paused

    @staticmethod
    def _mpris_players() -> list[str]:
        try:
            out = subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                 "--object-path", "/org/freedesktop/DBus",
                 "--method", "org.freedesktop.DBus.ListNames"],
                capture_output=True, text=True, timeout=3, check=False,
                encoding="utf-8", errors="replace",
            ).stdout
        except Exception as exc:
            logger.debug("[focus] gdbus ListNames failed: %s", exc)
            return []
        # Dedupe while preserving order — a player can appear under both its
        # well-known and unique name.
        seen, names = set(), []
        for n in re.findall(r"org\.mpris\.MediaPlayer2\.[A-Za-z0-9_.\-]+", out):
            if n not in seen:
                seen.add(n)
                names.append(n)
        return names

    @staticmethod
    def _mpris_pause(name: str) -> bool:
        try:
            subprocess.run(
                ["gdbus", "call", "--session", "--dest", name,
                 "--object-path", "/org/mpris/MediaPlayer2",
                 "--method", "org.mpris.MediaPlayer2.Player.Pause"],
                capture_output=True, text=True, timeout=3, check=False,
                encoding="utf-8", errors="replace",
            )
            return True
        except Exception as exc:
            logger.debug("[focus] pause %s failed: %s", name, exc)
            return False

    def _publish(self, event: str, data) -> None:
        bus = getattr(self._app, "event_bus", None)
        if bus:
            try:
                bus.publish(event, data)
            except Exception:
                pass

    @staticmethod
    def is_active() -> bool:
        return _focus_active
