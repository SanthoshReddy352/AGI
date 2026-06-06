"""Real OS session lock — locks the actual desktop/laptop screen.

This is distinct from `core/screen_lock.py`, which is a FRIDAY-internal PIN
gate that only blocks tool execution. Users who say "lock the screen" /
"lock my laptop" mean *lock the computer*, so the `lock_screen` capability
and the `/lock` slash command route here.

Cross-platform, best-effort: we try a series of known locker commands and
use the first one that exists and exits cleanly. The OS is unlocked by the
user's normal password at the system lock screen — there is no programmatic
unlock (by design), so `unlock_*` only reports that.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

from core.logger import logger

# Linux lockers in preference order. `loginctl lock-session` (systemd-logind)
# is the most universal across GNOME/KDE/Xfce; the rest cover desktops or
# Wayland compositors where logind locking isn't wired up.
_LINUX_LOCKERS: list[list[str]] = [
    ["loginctl", "lock-session"],
    ["xdg-screensaver", "lock"],
    ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"],
    ["gnome-screensaver-command", "-l"],
    ["xflock4"],                       # Xfce (common on Kali)
    ["light-locker-command", "-l"],
    ["dm-tool", "lock"],               # LightDM
    ["swaylock"],                      # Wayland (sway)
    ["i3lock"],                        # i3
    ["xset", "s", "activate"],         # last resort
]


def _run(cmd: list[str], timeout: int = 8) -> bool:
    exe = shutil.which(cmd[0])
    if exe is None:
        return False
    try:
        result = subprocess.run(
            [exe, *cmd[1:]],
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("[os_lock] %s failed: %s", cmd[0], exc)
        return False
    if result.returncode == 0:
        logger.info("[os_lock] locked via %s", cmd[0])
        return True
    logger.debug("[os_lock] %s exited %s: %s", cmd[0], result.returncode, result.stderr.strip())
    return False


def lock_os_session() -> tuple[bool, str]:
    """Lock the real desktop/laptop session. Returns (ok, user_message)."""
    system = platform.system()

    if system == "Windows":
        try:
            import ctypes  # noqa: PLC0415
            if ctypes.windll.user32.LockWorkStation():
                return True, "Screen locked."
        except Exception as exc:  # pragma: no cover - platform-specific
            logger.debug("[os_lock] LockWorkStation failed: %s", exc)
        return False, "I couldn't lock the screen on this Windows session."

    if system == "Darwin":
        if _run(["pmset", "displaysleepnow"]):
            return True, "Screen locked."
        return False, "I couldn't lock the screen on this Mac."

    # Linux / other POSIX
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        # Headless or no GUI session — locking has no meaning.
        logger.warning("[os_lock] no DISPLAY/WAYLAND_DISPLAY — cannot lock")
    for cmd in _LINUX_LOCKERS:
        if _run(cmd):
            return True, "Screen locked."
    return (
        False,
        "I couldn't lock the screen — no supported locker was found. "
        "Install one of: a desktop screensaver, `loginctl` (systemd), "
        "or `xdg-screensaver`/`xflock4`.",
    )
