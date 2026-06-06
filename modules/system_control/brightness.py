"""Brightness control with honest failure modes.

The previous build had no `set_brightness` capability registered. When
the user said "set brightness to 60", LLMChat caught the request and
fabricated "Brightness set to 60." — confidently announcing success
without actually doing anything. That's the worst kind of hallucination
because it's indistinguishable from a working tool.

This module implements a real capability that:

1. Tries `brightnessctl set N%` (preferred — userspace, no sudo).
2. Falls back to writing `/sys/class/backlight/<panel>/brightness`.
3. If everything fails, returns a precise error message so the LLM no
   longer has plausible-deniability cover to hallucinate.
"""
from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import subprocess

from core.logger import logger


_VALID_RANGE = range(0, 101)
_PERCENT_PATTERN = re.compile(r"(\d{1,3})\s*%?")


def set_brightness(percent: object) -> str:
    """Set screen brightness to *percent*. Returns a user-facing message."""
    target = _coerce_percent(percent)
    if target is None:
        return (
            "I need a brightness percentage between 0 and 100. "
            "Try 'set brightness to 60' or 'brightness 60%'."
        )

    err_chain: list[str] = []

    # Windows: the built-in laptop panel is driven through WMI
    # (WmiMonitorBrightnessMethods) via PowerShell — there is no
    # brightnessctl / /sys backlight there. Gated on `which("powershell")`
    # so the existing Linux backend tests (which monkeypatch `which` to
    # return None) are unaffected on either OS. Windows repaints its own
    # brightness slider, so no DE-refresh nudge is needed.
    if platform.system() == "Windows" and shutil.which("powershell"):
        ok, err = _via_windows_wmi(target)
        if ok:
            logger.info("[brightness] set to %d%% via WMI", target)
            return f"Brightness set to {target}%."
        err_chain.append(f"wmi: {err}")

    if shutil.which("brightnessctl"):
        ok, err = _via_brightnessctl(target)
        if ok:
            logger.info("[brightness] set to %d%% via brightnessctl", target)
            _notify_desktop_environment(target)
            return f"Brightness set to {target}%."
        err_chain.append(f"brightnessctl: {err}")

    if shutil.which("light"):
        ok, err = _via_light(target)
        if ok:
            logger.info("[brightness] set to %d%% via light", target)
            _notify_desktop_environment(target)
            return f"Brightness set to {target}%."
        err_chain.append(f"light: {err}")

    ok, err = _via_sysfs(target)
    if ok:
        logger.info("[brightness] set to %d%% via /sys", target)
        _notify_desktop_environment(target)
        return f"Brightness set to {target}%."
    err_chain.append(f"/sys: {err}")

    details = "; ".join(e for e in err_chain if e) or "no backend available"
    logger.warning("[brightness] failed: %s", details)
    if platform.system() == "Windows":
        return (
            f"I couldn't change the brightness ({details}). On Windows I can "
            "only adjust a built-in laptop display via WMI — external monitors "
            "need their own controls (or a DDC/CI tool)."
        )
    return (
        f"I couldn't change the brightness ({details}). "
        "Install brightnessctl (`sudo apt install brightnessctl`) "
        "and add your user to the `video` group, then try again."
    )


# ---------------------------------------------------------------------------
# Desktop-environment refresh helpers (2026-05-23 — Step 2 of plan)
# ---------------------------------------------------------------------------
#
# `brightnessctl` writes /sys/class/backlight/*/brightness directly, which
# changes the actual hardware backlight — but most desktop panel-slider
# widgets (GNOME Quick Settings, KDE Plasma applet, XFCE indicator) cache
# their value and only refresh on their own DBus / xfconf signals. Result:
# the screen really IS dimmer, but the slider in the panel keeps showing
# the old number until you wiggle it.
#
# Fix: after a successful brightness change, emit the corresponding signal
# / property set so each DE's daemon re-reads /sys and repaints. We try
# every known backend in parallel best-effort and swallow failures — only
# one needs to succeed for the slider to refresh, and an unknown DE just
# means no refresh (harmless — the brightness itself already changed).

def _notify_desktop_environment(target: int) -> None:
    """Best-effort: tell the running desktop environment to refresh its
    brightness widget. Never raises — failures are logged at debug level
    only because they're expected on non-matching DEs (e.g. GNOME calls
    fail on a KDE system).
    """
    for name, fn in (
        ("gnome", _notify_gnome),
        ("kde", _notify_kde),
        ("xfce", _notify_xfce),
    ):
        try:
            fired = fn(target)
            if fired:
                logger.debug("[brightness] notified %s desktop (brightness=%d%%)", name, target)
        except Exception as exc:
            logger.debug("[brightness] %s notify failed: %s", name, exc)


def _notify_gnome(target: int) -> bool:
    """Tell `org.gnome.SettingsDaemon.Power` the brightness changed.

    Setting the `Brightness` property both updates the value GNOME
    Quick Settings reads AND causes gsd-power to repaint the indicator.
    Works on GNOME 40+ (Wayland and X11).
    """
    if not shutil.which("gdbus"):
        return False
    args = [
        "gdbus", "call",
        "--session",
        "--dest", "org.gnome.SettingsDaemon.Power",
        "--object-path", "/org/gnome/SettingsDaemon/Power",
        "--method", "org.freedesktop.DBus.Properties.Set",
        "org.gnome.SettingsDaemon.Power.Screen",
        "Brightness",
        f"<int32 {target}>",
    ]
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=2,
        encoding="utf-8", errors="replace",
    )
    return result.returncode == 0


def _notify_kde(target: int) -> bool:
    """Tell KDE Plasma's PowerManagement service the brightness changed.

    qdbus is the simplest interface; falls back to gdbus if qdbus
    isn't installed but gdbus is.
    """
    if shutil.which("qdbus"):
        result = subprocess.run(
            [
                "qdbus",
                "org.kde.Solid.PowerManagement",
                "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                "org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness",
                str(target),
            ],
            capture_output=True, text=True, timeout=2,
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    if shutil.which("gdbus"):
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.kde.Solid.PowerManagement",
                "--object-path", "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                "--method", "org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness",
                str(target),
            ],
            capture_output=True, text=True, timeout=2,
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    return False


def _notify_xfce(target: int) -> bool:
    """XFCE caches brightness in xfconf — `xfconf-query` nudges the
    power-manager applet to re-read. Silent no-op if xfconf-query isn't
    installed.
    """
    if not shutil.which("xfconf-query"):
        return False
    result = subprocess.run(
        [
            "xfconf-query", "-c", "xfce4-power-manager",
            "-p", "/xfce4-power-manager/brightness-level",
            "-s", str(target),
            "--create", "-t", "int",
        ],
        capture_output=True, text=True, timeout=2,
        encoding="utf-8", errors="replace",
    )
    return result.returncode == 0


def _coerce_percent(value: object) -> int | None:
    if isinstance(value, (int, float)):
        target = int(value)
    elif isinstance(value, str):
        match = _PERCENT_PATTERN.search(value)
        if not match:
            return None
        target = int(match.group(1))
    else:
        return None
    return target if target in _VALID_RANGE else None


def _via_windows_wmi(target: int) -> tuple[bool, str]:
    """Set the built-in display brightness on Windows via WMI.

    `WmiMonitorBrightnessMethods.WmiSetBrightness(timeout, level)` drives the
    integrated laptop panel (the same channel the OS brightness slider uses).
    Desktops / external monitors usually expose no instance — that surfaces as
    an honest failure rather than a fabricated success. `Invoke-CimMethod`
    works on both Windows PowerShell 5.1 and PowerShell 7+.
    """
    ps = (
        "$ErrorActionPreference='Stop'; "
        "try { "
        "$m=@(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods); "
        "if(-not $m){throw 'no WmiMonitorBrightnessMethods instance "
        "(no internal display / brightness not WMI-controllable)'}; "
        f"Invoke-CimMethod -InputObject $m[0] -MethodName WmiSetBrightness "
        f"-Arguments @{{Timeout=1;Brightness={target}}} | Out-Null; 'OK' "
        "} catch { Write-Error $_.Exception.Message; exit 1 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "non-zero exit").strip()[:200]


def _via_brightnessctl(target: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["brightnessctl", "set", f"{target}%"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "non-zero exit").strip()[:200]


def _via_light(target: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["light", "-S", str(target)],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "non-zero exit").strip()[:200]


def _via_sysfs(target: int) -> tuple[bool, str]:
    panels = glob.glob("/sys/class/backlight/*/brightness")
    if not panels:
        return False, "no backlight panel found"
    panel = panels[0]
    max_path = os.path.join(os.path.dirname(panel), "max_brightness")
    try:
        with open(max_path, "r") as f:
            max_raw = int(f.read().strip())
    except OSError as exc:
        return False, f"cannot read {max_path}: {exc}"
    raw_target = max(0, min(max_raw, round(max_raw * target / 100)))
    try:
        with open(panel, "w") as f:
            f.write(str(raw_target))
    except PermissionError:
        return False, "permission denied — needs brightnessctl or video group"
    except OSError as exc:
        return False, f"write failed: {exc}"
    return True, ""
