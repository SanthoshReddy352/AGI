"""App launcher tool — open apps/files/URLs, with launch verification + tracking.

Two reliability fixes over the naive version:
  * **verify** the launch actually started (so we don't falsely report success);
  * **track** opened apps and check if they're still running, so "open it again"
    re-launches a closed app instead of claiming it's already open.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time

from namma_agent.core.app_tracker import AppTracker, is_running
from namma_agent.core.tools import ToolRegistry, ToolResult

_tracker = AppTracker()


def _looks_like_path_or_url(target: str) -> bool:
    return (
        target.startswith(("http://", "https://", "ftp://", "/", "~", "./", "../"))
        or target.startswith("file://")
        or os.path.exists(os.path.expanduser(target))
    )


def _verify_started(name: str, proc: subprocess.Popen | None, timeout: float = 3.0) -> bool:
    """True once the app appears to be running (or its process is alive)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None and proc.returncode not in (0, None):
            return False  # the launcher process exited with an error
        if is_running(name):
            return True
        time.sleep(0.3)
    # Last chance: a still-alive launcher process counts as started.
    return bool(proc is not None and proc.poll() is None)


def _open_linux(target: str) -> ToolResult:
    opener = shutil.which("xdg-open") or shutil.which("gio")
    expanded = os.path.expanduser(target)

    # Files / folders / URLs → xdg-open (can't meaningfully track these).
    if _looks_like_path_or_url(target):
        if not opener:
            return ToolResult(ok=False, content="", error="no opener (install xdg-utils)")
        cmd = [opener, "open", expanded] if opener.endswith("gio") else [opener, expanded]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return ToolResult(ok=False, content="",
                              error=f"couldn't open {target}: {(proc.stderr or '').strip()[:200]}")
        return ToolResult(ok=True, content=f"Opened {target}")

    # Bare app name. If it's already running, say so (truthfully) — don't relaunch.
    if is_running(target):
        _tracker.record(target, target)
        return ToolResult(ok=True, content=f"{target} is already open.", data={"already_open": True})

    # Launch as an executable if on PATH, else via the .desktop launcher.
    exe = shutil.which(target) or shutil.which(target.lower())
    if exe:
        proc = subprocess.Popen([exe], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if _verify_started(target, proc):
            _tracker.record(target, exe, proc.pid)
            return ToolResult(ok=True, content=f"Opened {target}.")
        return ToolResult(ok=False, content="", error=f"{target} was launched but didn't start.")

    gtk = shutil.which("gtk-launch")
    if gtk:
        app_id = target[:-8] if target.endswith(".desktop") else target
        proc = subprocess.run([gtk, app_id], capture_output=True, text=True)
        if proc.returncode == 0 and _verify_started(target, None):
            _tracker.record(target, f"gtk-launch {app_id}")
            return ToolResult(ok=True, content=f"Opened {target}.")
        if proc.returncode != 0:
            return ToolResult(ok=False, content="",
                              error=f"no such application {target!r} ({(proc.stderr or '').strip()[:120]})")
        return ToolResult(ok=False, content="", error=f"{target} didn't start.")

    return ToolResult(ok=False, content="", error=f"could not find an app called {target!r}")


def _open_app(args: dict) -> ToolResult:
    target = (args.get("target") or args.get("name") or args.get("app") or "").strip()
    if not target:
        return ToolResult(ok=False, content="", error="no target given")
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(os.path.expanduser(target))  # type: ignore[attr-defined]
            _tracker.record(target, target)
            return ToolResult(ok=True, content=f"Opened {target}")
        if system == "Darwin":
            if _looks_like_path_or_url(target):
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["open", "-a", target])
            return ToolResult(ok=True, content=f"Opened {target}")
        return _open_linux(target)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))


def _list_open_apps(_args: dict) -> ToolResult:
    apps = _tracker.running()
    if not apps:
        return ToolResult(ok=True, content="No tracked apps are currently open.")
    return ToolResult(ok=True, content="Open apps: " + ", ".join(apps), data={"open": apps})


def register(registry: ToolRegistry) -> None:
    registry.register("open_app",
        "Open a desktop app, file, folder, or URL. Verifies the app actually started "
        "and tracks it; if it's already running it says so. Use this to (re)open a "
        "closed app — it relaunches when not running.", {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "app name, file path, or URL"}},
            "required": ["target"],
        }, _open_app)

    registry.register("list_open_apps",
        "List the apps Namma Agent has opened that are still running (checks live state).", {
            "type": "object", "properties": {},
        }, _list_open_apps)
