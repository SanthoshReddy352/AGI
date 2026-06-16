"""Shell tool — run a command (destructive; approval-gated)."""
from __future__ import annotations

import re
import subprocess

from friday.core.tools import ToolRegistry, ToolResult

_TIMEOUT = 180

# Force every `sudo` into non-interactive mode so it never grabs the server's
# terminal to prompt for a password (it reads from /dev/tty, not stdin). With
# passwordless sudo it just works; otherwise it fails fast with a clear message.
_SUDO_RE = re.compile(r"(^|[;&|]\s*)sudo\s+(?!-n\b|-S\b|-A\b|-K\b|-k\b)")


def _noninteractive_sudo(cmd: str) -> str:
    return _SUDO_RE.sub(lambda m: m.group(1) + "sudo -n ", cmd)


def _needs_password(returncode: int, out: str) -> bool:
    low = out.lower()
    return returncode != 0 and ("a password is required" in low
                                or "a terminal is required" in low
                                or "no askpass" in low)


def _run(cmd: str, timeout: int, password: str | None = None) -> subprocess.CompletedProcess:
    """Run detached from any controlling terminal. With a password, feed it on
    stdin for `sudo -S` (and nowhere else); otherwise close stdin."""
    kwargs = dict(shell=True, capture_output=True, text=True, encoding="utf-8",
                  errors="replace", timeout=timeout, start_new_session=True)
    if password is None:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, **kwargs)
    return subprocess.run(cmd, input=password + "\n", **kwargs)


def _run_shell(args: dict) -> ToolResult:
    raw = args.get("command", "").strip()
    if not raw:
        return ToolResult(ok=False, content="", error="empty command")
    cmd = _noninteractive_sudo(raw)
    timeout = max(1, min(int(args.get("timeout", _TIMEOUT) or _TIMEOUT), 1800))
    try:
        proc = _run(cmd, timeout)
        # If a sudo password is required, ask the UI once and retry with `sudo -S`.
        # The secret goes ONLY to sudo's stdin — never logged, stored, or returned.
        if _needs_password(proc.returncode, (proc.stdout or "") + (proc.stderr or "")) and "sudo -n " in cmd:
            from friday.core.interactive import get_askpass

            askpass = get_askpass()
            if askpass is not None:
                pwd = askpass("Enter your sudo password")
                if pwd:
                    proc = _run(cmd.replace("sudo -n ", "sudo -S -p '' "), timeout, password=pwd)
                    del pwd
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, content="", error=f"timed out after {timeout}s")
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip()[:20_000] or "(no output)"
    if _needs_password(proc.returncode, out):
        out += ("\n\n(No sudo password was provided. Configure passwordless sudo, "
                "or run it yourself with `! sudo …` in your terminal.)")
    return ToolResult(ok=proc.returncode == 0, content=out,
                      error="" if proc.returncode == 0 else f"exit {proc.returncode}: {out[:300]}")


def register(registry: ToolRegistry) -> None:
    registry.register("run_shell",
        "Run a NON-INTERACTIVE shell command and return stdout/stderr. Cannot answer "
        "prompts (use `sudo -n` / `apt -y` / `DEBIAN_FRONTEND=noninteractive`).", {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "the shell command to run"},
                "timeout": {"type": "integer", "description": "seconds (default 180, max 1800)"},
            },
            "required": ["command"],
        }, _run_shell, destructive=True)
