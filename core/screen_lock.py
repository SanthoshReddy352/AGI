"""In-process mirror of the screen-lock state + the capability gate.

The lock state now tracks the **real OS screen lock** (see
``core/lock_monitor.py``, which polls systemd-logind's ``LockedHint`` and
calls :meth:`ScreenLock.set_locked`). When the desktop is locked, the
capability gate refuses tools that need the visible session — browser
automation, app/file launching, screenshots, on-screen vision, dictation —
listed in :data:`BLOCKED_WHEN_LOCKED`. EVERYTHING ELSE (chat, memory,
email, research, web search, weather, news, reminders, …) keeps working.

The legacy PIN gate (``FRIDAY_LOCK_PIN_HASH`` + :meth:`lock` /
:meth:`try_unlock`) is retained for callers/tests that still drive the
state by PIN, but the real OS lock is the primary driver now.
"""
from __future__ import annotations

import hashlib
import os
import threading

from core.logger import logger


ENV_HASH_VAR = "FRIDAY_LOCK_PIN_HASH"


# Denylist: capabilities that CAN'T meaningfully run while the OS screen is
# locked because they drive the visible desktop — browser automation, app
# launching, opening files/URLs, screenshots, on-screen vision, dictation
# into the focused app, window queries. EVERYTHING ELSE stays allowed
# (chat, memory, email, research, web search, weather, news, reminders,
# calendar, file reads, system info, …). New GUI/automation tools should be
# added here.
BLOCKED_WHEN_LOCKED: frozenset[str] = frozenset({
    # Browser automation / media
    "open_browser_url", "open_url", "search_google",
    "play_youtube", "play_youtube_music", "browser_media_control",
    "browser_media_dispatch", "detect_media_command", "web_crawl",
    # App / file launching (needs a visible session)
    "launch_app", "open_file", "open_folder",
    # Screenshots + on-screen vision
    "take_screenshot",
    "analyze_screen", "read_text_from_image", "summarize_screen",
    "analyze_clipboard_image", "debug_code_screenshot", "explain_meme",
    "roast_desktop", "review_design", "compare_screenshots",
    "find_ui_element",
    # Dictation types into the focused app; window introspection
    "start_dictation", "end_dictation", "cancel_dictation",
    "get_active_window",
})

# Substring fallback so obvious future GUI tools are caught even if a
# maintainer forgets to list them above.
_BLOCKED_KEYWORDS: tuple[str, ...] = (
    "screenshot", "browser", "youtube", "launch_app",
)


def is_blocked_when_locked(capability_name: str) -> bool:
    name = (capability_name or "").lower()
    if name in BLOCKED_WHEN_LOCKED:
        return True
    return any(kw in name for kw in _BLOCKED_KEYWORDS)


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8", errors="ignore")).hexdigest()


class ScreenLock:
    """Process-local lock state.

    Thread-safe: a single :class:`threading.Lock` protects ``_locked`` so
    the lock gate in :class:`CapabilityExecutor` and the
    `/lock` / `/unlock` slash handlers can race without seeing a torn
    state. The lock is intentionally NOT persisted across restarts —
    boot always starts unlocked unless the env var rejects the user's
    first try.
    """

    def __init__(self, expected_hash: str = ""):
        self._mu = threading.Lock()
        self._locked = False
        self._expected_hash = (expected_hash or os.environ.get(ENV_HASH_VAR, "")).strip().lower()

    def is_configured(self) -> bool:
        return bool(self._expected_hash)

    def is_locked(self) -> bool:
        with self._mu:
            return self._locked

    def set_locked(self, value: bool) -> bool:
        """Set the lock state directly (driven by the real OS lock state).

        Returns True if the state actually changed. This is the path used
        once locking means the *OS session* lock rather than a PIN gate —
        the LockStateMonitor calls it on every detected transition.
        """
        value = bool(value)
        with self._mu:
            changed = value != self._locked
            self._locked = value
        if changed:
            logger.info("[screen_lock] state -> %s", "locked" if value else "unlocked")
        return changed

    def lock(self) -> str:
        if not self.is_configured():
            return (
                "Screen lock is not configured. Set the FRIDAY_LOCK_PIN_HASH "
                "environment variable to a sha256 hex digest of your PIN."
            )
        with self._mu:
            self._locked = True
        logger.info("[screen_lock] locked")
        return "Screen locked. Tools require /unlock <pin> to run."

    def try_unlock(self, pin: str) -> tuple[bool, str]:
        if not self.is_configured():
            return False, (
                "Screen lock is not configured. Set FRIDAY_LOCK_PIN_HASH "
                "to a sha256 hex digest of your PIN to enable locking."
            )
        pin = (pin or "").strip()
        if not pin:
            return False, "Provide a PIN: /unlock <pin>"
        if _hash_pin(pin) == self._expected_hash:
            with self._mu:
                self._locked = False
            logger.info("[screen_lock] unlocked")
            return True, "Screen unlocked."
        logger.warning("[screen_lock] unlock attempt with wrong PIN")
        return False, "Wrong PIN. Screen stays locked."

    def is_allowed(self, capability_name: str) -> bool:
        """True when *capability_name* may run given the current lock state.

        When unlocked, everything is allowed. When locked, everything is
        allowed EXCEPT the screen-dependent tools in BLOCKED_WHEN_LOCKED
        (browser automation, app/file launching, screenshots, vision, …).
        """
        if not self.is_locked():
            return True
        return not is_blocked_when_locked(capability_name)
