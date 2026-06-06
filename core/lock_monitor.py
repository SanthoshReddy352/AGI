"""LockStateMonitor — track the real OS screen-lock state and react.

Responsibilities:
  • Poll the OS session lock state (systemd-logind ``LockedHint`` on Linux)
    and mirror it into ``app.screen_lock`` so the capability gate blocks
    screen-dependent tools while the desktop is locked.
  • Notify the user over Telegram on every lock ↔ unlock transition, so they
    get a log line whether the lock came from FRIDAY (`/lock`) or from the
    desktop directly (Super+L).

A single ``_set_state`` chokepoint updates the lock state and sends the
Telegram message only on an actual change, so a FRIDAY-initiated lock
(``note_locked``) and the poller seeing the same state don't double-notify.

Best-effort and side-effect free when locking can't be observed (headless,
no logind): the thread just no-ops.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time

from core.logger import logger


class LockStateMonitor:
    # After FRIDAY itself locks, ignore an "unlocked" OS reading for this long.
    # LockWorkStation returns before the secure desktop fully engages, so an
    # immediate poll can still see the Default desktop and wrongly clear the
    # lock we just set.
    _LOCK_GRACE_SECONDS = 6.0

    def __init__(self, app, screen_lock, poll_interval: float = 2.0):
        self._app = app
        self._lock = screen_lock
        self._interval = max(0.5, float(poll_interval))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._mu = threading.Lock()
        self._locked_at = 0.0  # monotonic time of the last FRIDAY-initiated lock

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._poll_loop, name="LockStateMonitor", daemon=True
        )
        self._thread.start()
        logger.info("[lock_monitor] started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Public hooks
    # ------------------------------------------------------------------

    def note_locked(self) -> None:
        """Called immediately after FRIDAY itself locks the screen, so the
        gate + Telegram notice fire without waiting for the next poll."""
        self._locked_at = time.monotonic()
        self._set_state(True, source="friday")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _set_state(self, locked: bool, *, source: str) -> None:
        with self._mu:
            changed = self._lock.set_locked(locked)
        if not changed:
            return
        logger.info("[lock_monitor] screen %s (via %s)",
                    "locked" if locked else "unlocked", source)
        self._notify(locked)

    def _notify(self, locked: bool) -> None:
        comms = getattr(self._app, "comms", None)
        telegram = getattr(comms, "telegram", None) if comms else None
        if telegram is None or not getattr(telegram, "available", False):
            return
        msg = (
            "🔒 Screen locked — screen-dependent tools (browser, apps, "
            "screenshots) are paused. Chat, memory, email and research still work."
            if locked else
            "🔓 Screen unlocked — all tools available again."
        )
        try:
            telegram.send(msg)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[lock_monitor] telegram notify failed: %s", exc)

    def _poll_loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                state = self._query_os_locked()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("[lock_monitor] poll error: %s", exc)
                continue
            if state is None:
                continue
            # Don't let an early "unlocked" reading undo a lock we just issued
            # (LockWorkStation returns before the secure desktop engages).
            if not state and (time.monotonic() - self._locked_at) < self._LOCK_GRACE_SECONDS:
                continue
            self._set_state(state, source="os")

    # ------------------------------------------------------------------
    # OS probes
    # ------------------------------------------------------------------

    def _query_os_locked(self) -> "bool | None":
        system = platform.system()
        if system == "Linux":
            return self._linux_locked_hint()
        if system == "Windows":
            return self._windows_locked()
        # macOS has no cheap poll-friendly probe here; rely on note_locked()
        # for FRIDAY-initiated locks.
        return None

    def _windows_locked(self) -> "bool | None":
        """Detect the Windows lock screen by inspecting the input desktop.

        When the workstation is locked, the secure desktop is active and a
        normal process can't open the input desktop (OpenInputDesktop returns
        NULL with ERROR_ACCESS_DENIED); when unlocked it returns the "Default"
        desktop. This lets us notice a manual unlock after a FRIDAY-initiated
        LockWorkStation, which previously left the lock state stuck (the
        2026-05-29 "I already unlocked but it says locked" bug).
        """
        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415
        except Exception:
            return None
        try:
            user32 = ctypes.windll.User32
            DESKTOP_READOBJECTS = 0x0001
            UOI_NAME = 2
            open_input = user32.OpenInputDesktop
            open_input.restype = ctypes.c_void_p
            open_input.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            close_desktop = user32.CloseDesktop
            close_desktop.argtypes = [ctypes.c_void_p]
            get_info = user32.GetUserObjectInformationW
            get_info.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            ]
            get_info.restype = wintypes.BOOL

            hdesk = open_input(0, False, DESKTOP_READOBJECTS)
            if not hdesk:
                return True  # can't open the input desktop → locked
            try:
                buf = ctypes.create_unicode_buffer(256)
                needed = wintypes.DWORD(0)
                ok = get_info(hdesk, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed))
                if not ok:
                    return None
                # "Default" = interactive desktop (unlocked); "Winlogon"/other
                # = secure desktop (locked).
                return buf.value.strip().lower() != "default"
            finally:
                close_desktop(hdesk)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[lock_monitor] windows lock probe failed: %s", exc)
            return None

    def _linux_locked_hint(self) -> "bool | None":
        loginctl = shutil.which("loginctl")
        if loginctl is None:
            return None
        session = self._linux_session_id(loginctl)
        if not session:
            return None
        try:
            out = subprocess.run(
                [loginctl, "show-session", session, "-p", "LockedHint"],
                capture_output=True, text=True, timeout=4,
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        line = (out.stdout or "").strip()
        if "LockedHint=" not in line:
            return None
        return line.split("LockedHint=", 1)[1].strip().lower() == "yes"

    def _linux_session_id(self, loginctl: str) -> str:
        sid = os.environ.get("XDG_SESSION_ID")
        if sid:
            return sid
        try:
            out = subprocess.run(
                [loginctl, "list-sessions", "--no-legend"],
                capture_output=True, text=True, timeout=4,
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, OSError):
            return ""
        for row in (out.stdout or "").splitlines():
            parts = row.split()
            if parts:
                return parts[0]
        return ""
