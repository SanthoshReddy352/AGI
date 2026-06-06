"""`!`-prefix shell executor with interactive (PTY-backed) input support.

Shell choice (2026-05-24): we explicitly use `/bin/bash` (with
`/bin/sh` fallback) instead of letting `subprocess(shell=True)` pick.
On Debian / Ubuntu / Kali, `shell=True` resolves to `/bin/sh` which is
dash — and dash doesn't have `source`, `[[ ]]`, arrays, process
substitution, or any of the things users instinctively type.

Venv awareness (2026-05-24): if the project root has a `.venv/` (or
`venv/`) directory, every `!cmd` runs with that venv "activated" —
i.e. PATH is prepended with `<venv>/bin` and `VIRTUAL_ENV` is set.
This means `!python script.py` uses the project's python without the
user needing `source .venv/bin/activate` (which wouldn't help anyway
because each `!cmd` spawns a fresh shell — its env vanishes when the
shell exits).

When the user's input starts with `!`, the rest of the line is executed
as a shell command under a pseudo-terminal so commands that need a TTY
(sudo password prompts, `read`, `ssh`, `passwd`, …) actually work.

Follow-up input is fed via the `>` prefix:

    !sudo apt install brightnessctl
    > <your password>            # piped to stdin of the running command
    > y                          # piped to the apt confirmation prompt

A non-`>` reply while a shell session is active **cancels** the running
command — it does NOT fall through to chat mode, so a stray "yes" can't
end up being interpreted by the LLM while sudo is waiting on a
password. (See `is_shell_followup` + `app._maybe_handle_input_prefix`.)

Security notes:

* Gated by :class:`core.screen_lock.ScreenLock`. While the screen is
  locked, `!` is blocked just like any other tool.
* `shell=True` is used by design.
* Wall-clock cap (default 5 minutes) on a single command; output cap
  prevents runaway buffering.
* Windows fallback: PTYs are POSIX-only. On Windows we degrade to the
  previous non-interactive `subprocess.run()` behaviour and reject `>`
  follow-ups with a clear message.
"""
from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from core.logger import logger


SHELL_PREFIX = "!"
FOLLOWUP_PREFIX = ">"
DEFAULT_HARD_TIMEOUT = 300        # 5 min wall-clock cap on a single command
INITIAL_QUIET_WINDOW = 1.5        # how long to wait for fresh output before
                                  # declaring the command "waiting on input"
FOLLOWUP_QUIET_WINDOW = 1.5
MAX_OUTPUT_CHARS = 8000
READ_CHUNK = 4096

_PROMPT_HINTS = (
    re.compile(rb"[Pp]assword[^:\n]*:\s*$"),
    re.compile(rb"\[sudo\] password[^:\n]*:\s*$"),
    re.compile(rb"\[[Yy]/[Nn]\]\s*$"),
    re.compile(rb"\([Yy]/[Nn]\)\s*$"),
    re.compile(rb"[Cc]ontinue\?\s*$"),
    re.compile(rb"\?\s*$"),
    re.compile(rb">\s*$"),
)


def _supports_pty() -> bool:
    return os.name == "posix"


def _preferred_shell() -> str:
    """Return absolute path to the shell we want `!cmd` to run under.

    Prefers bash so user-friendly idioms (`source`, `[[ ]]`, arrays,
    `<(…)` process substitution) work. Falls back to /bin/sh if bash
    isn't installed (extremely rare on a desktop Linux box).

    On Windows this helper is never used as a real `executable=` (the PTY
    path is POSIX-only and the sync paths pass `None` on `os.name == "nt"`),
    but return COMSPEC defensively so a stray call can't hand subprocess a
    non-existent `/bin/sh`.
    """
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    for candidate in ("/bin/bash", "/usr/bin/bash"):
        if os.path.exists(candidate):
            return candidate
    return "/bin/sh"


# Project root = directory containing this file's grandparent (core/ → repo)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _venv_path() -> str | None:
    """Return absolute path to the project venv (if one exists)."""
    for name in (".venv", "venv", ".env"):
        candidate = os.path.join(_PROJECT_ROOT, name)
        if os.path.isfile(os.path.join(candidate, "bin", "python")) or \
           os.path.isfile(os.path.join(candidate, "Scripts", "python.exe")):
            return candidate
    return None


def _shell_env() -> dict[str, str]:
    """Build the env dict for `!cmd` subprocesses.

    Inherits the current process env, then — if a venv exists in the
    project root — prepends `<venv>/bin` to PATH and sets `VIRTUAL_ENV`.
    Net effect: `!python script.py` uses the venv's interpreter without
    the user needing `source .venv/bin/activate`.
    """
    env = dict(os.environ)
    venv = _venv_path()
    if venv is None:
        return env
    bin_dir = os.path.join(venv, "bin")
    if not os.path.isdir(bin_dir):
        bin_dir = os.path.join(venv, "Scripts")  # Windows fallback
    if os.path.isdir(bin_dir):
        existing_path = env.get("PATH", "")
        # Avoid duplicating if FRIDAY itself is already running in this venv.
        if not existing_path.startswith(bin_dir + os.pathsep):
            env["PATH"] = bin_dir + os.pathsep + existing_path
        env["VIRTUAL_ENV"] = venv
        # PYTHONHOME interferes with venv resolution if it's set.
        env.pop("PYTHONHOME", None)
    return env


def is_shell_command(text: str) -> bool:
    stripped = (text or "").lstrip()
    if not stripped.startswith(SHELL_PREFIX):
        return False
    body = stripped[1:].lstrip()
    if not body or body[0] in ("!", "?", "."):
        return False
    return True


def is_shell_followup(text: str) -> bool:
    """Return True for `>`-prefixed follow-up input.

    Only meaningful while a shell session is alive — `app` calls this
    first, then consults :func:`has_active_session`.
    """
    stripped = (text or "").lstrip()
    return stripped.startswith(FOLLOWUP_PREFIX) and not stripped.startswith(">>")


# ---------------------------------------------------------------------------
# Interactive session state
# ---------------------------------------------------------------------------


@dataclass
class _ShellSession:
    cmd: str
    proc: subprocess.Popen
    master_fd: int
    started_at: float
    output: bytearray = field(default_factory=bytearray)
    lock: threading.Lock = field(default_factory=threading.Lock)
    closed: bool = False

    def drain(self, quiet_window: float) -> bytes:
        """Read available output until *quiet_window* seconds elapse with
        no new bytes, the wall-clock cap is hit, or the process exits.
        """
        new_bytes = bytearray()
        last_read = time.monotonic()
        while True:
            if time.monotonic() - self.started_at > DEFAULT_HARD_TIMEOUT:
                self.kill("timeout")
                break
            timeout = max(0.0, quiet_window - (time.monotonic() - last_read))
            try:
                r, _, _ = select.select([self.master_fd], [], [], timeout)
            except (OSError, ValueError):
                break
            if r:
                try:
                    chunk = os.read(self.master_fd, READ_CHUNK)
                except OSError:
                    chunk = b""
                if not chunk:
                    # EOF — process has finished writing.
                    break
                new_bytes.extend(chunk)
                self.output.extend(chunk)
                last_read = time.monotonic()
                if len(self.output) > MAX_OUTPUT_CHARS * 4:
                    # Truncate stored buffer; keep last MAX_OUTPUT_CHARS*2 bytes.
                    keep = bytes(self.output[-MAX_OUTPUT_CHARS * 2:])
                    self.output.clear()
                    self.output.extend(keep)
                continue
            # No data ready within quiet_window.
            if self.proc.poll() is not None:
                # Process finished; drain any final bytes non-blocking.
                self._final_drain(new_bytes)
                break
            break  # quiet window with process still alive
        return bytes(new_bytes)

    def _final_drain(self, new_bytes: bytearray) -> None:
        # Non-blocking final read until EOF/EAGAIN.
        import fcntl  # noqa: PLC0415 - POSIX only path
        try:
            fl = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        except OSError:
            return
        while True:
            try:
                chunk = os.read(self.master_fd, READ_CHUNK)
            except (BlockingIOError, OSError):
                break
            if not chunk:
                break
            new_bytes.extend(chunk)
            self.output.extend(chunk)

    def write(self, data: str) -> None:
        if self.closed:
            return
        payload = (data + "\n").encode("utf-8", errors="replace")
        try:
            os.write(self.master_fd, payload)
        except OSError as exc:
            logger.warning("[shell] write to PTY failed: %s", exc)

    def is_alive(self) -> bool:
        return (not self.closed) and self.proc.poll() is None

    def kill(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.proc.poll() is None:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                # Give it a half-second to clean up, then SIGKILL.
                try:
                    self.proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.proc.wait(timeout=0.5)
        except (ProcessLookupError, OSError):
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        logger.info("[shell] session killed (%s): %s", reason, self.cmd[:120])


_state_lock = threading.Lock()
_active: Optional[_ShellSession] = None


def has_active_session() -> bool:
    with _state_lock:
        return _active is not None and _active.is_alive()


def cancel_active_session(reason: str = "user") -> Optional[str]:
    """Force-terminate the active session (if any). Returns the final
    formatted output, or None if there was no session.
    """
    global _active
    with _state_lock:
        sess = _active
        _active = None
    if sess is None:
        return None
    sess.kill(reason)
    return _format_final(sess, note=f"(cancelled: {reason})")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_shell(command: str, timeout: Optional[int] = None) -> str:
    """Start `command` under a PTY.

    If ``timeout`` is provided, run synchronously like the old API:
    block up to that many seconds, kill on overshoot, return a final
    formatted result with no interactive session left behind. (Tests
    rely on this — and a few internal call sites that want a one-shot
    invocation.)

    Otherwise: PTY-backed interactive mode. If the command finishes
    inside :data:`INITIAL_QUIET_WINDOW`, return the final output. If
    it's still alive, leave it alive and return a streaming snapshot
    with an "awaiting input" hint; the next user message that begins
    with ``>`` will be piped to its stdin.
    """
    global _active
    cmd = (command or "").lstrip().lstrip(SHELL_PREFIX).strip()
    if not cmd:
        return "Empty shell command."

    # Force-clear any stale session before starting a new one.
    cancel_active_session(reason="superseded")

    if timeout is not None:
        return _run_shell_sync(cmd, timeout)

    if not _supports_pty():
        return _run_shell_no_pty(cmd)

    logger.info("[shell] running (pty): %s", cmd[:120])
    import pty  # noqa: PLC0415 - POSIX only
    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as exc:
        logger.warning("[shell] pty.openpty failed (%s); falling back to non-PTY", exc)
        return _run_shell_no_pty(cmd)

    # Critical for sudo: the slave fd must be the child's CONTROLLING
    # terminal, not just plumbed as stdin. Without TIOCSCTTY, `sudo`
    # checks `isatty()` and refuses with "a terminal is required to
    # read the password". The previous shape (`start_new_session=True`,
    # PTY slave on stdin/out/err) gave us a TTY-shaped fd but no
    # controlling terminal — sudo saw a session leader with no TTY and
    # bailed. We fork a session with setsid(), then issue TIOCSCTTY on
    # fd 0 inside the child via `preexec_fn`.
    import fcntl  # noqa: PLC0415 - POSIX only
    import termios  # noqa: PLC0415 - POSIX only

    def _preexec_acquire_tty():
        # Already in a new session because start_new_session=True ran
        # setsid() for us; reissuing setsid here would fail. Just claim
        # the controlling terminal.
        try:
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        except OSError:
            # Some kernels (or already-controlling TTYs) reject this;
            # not fatal — non-sudo commands work either way.
            pass

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            executable=_preferred_shell(),
            env=_shell_env(),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
            preexec_fn=_preexec_acquire_tty,
        )
    except Exception as exc:
        os.close(master_fd)
        os.close(slave_fd)
        return f"Shell execution failed: {exc}"
    os.close(slave_fd)  # child holds the only ref now

    sess = _ShellSession(cmd=cmd, proc=proc, master_fd=master_fd, started_at=time.monotonic())
    sess.drain(INITIAL_QUIET_WINDOW)

    if proc.poll() is not None:
        # Finished before we even got to "waiting" — synthesize a one-shot result.
        return _format_final(sess)

    with _state_lock:
        _active = sess
    return _format_waiting(sess)


def feed_followup(text: str) -> str:
    """Pipe a `>` follow-up to the active shell session's stdin."""
    global _active
    with _state_lock:
        sess = _active
    if sess is None or not sess.is_alive():
        with _state_lock:
            _active = None
        return "No active shell command. Start one with `!<cmd>`."

    payload = text.lstrip()
    if payload.startswith(FOLLOWUP_PREFIX):
        payload = payload[len(FOLLOWUP_PREFIX):]
    payload = payload.lstrip()

    sess.write(payload)
    sess.drain(FOLLOWUP_QUIET_WINDOW)

    if not sess.is_alive():
        with _state_lock:
            _active = None
        return _format_final(sess)
    return _format_waiting(sess)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _strip_ansi(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    # Strip the common CSI / OSC escape sequences so the rendered output
    # in the chat bubble doesn't look like binary garbage.
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"\x1b\][^\x07]*\x07", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _last_visible_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _looks_like_prompt(buf: bytes) -> bool:
    tail = bytes(buf[-200:]) if len(buf) > 200 else bytes(buf)
    tail_stripped = tail.rstrip(b" \t")
    return any(p.search(tail_stripped) for p in _PROMPT_HINTS)


def _format_body(sess: _ShellSession) -> str:
    body = _strip_ansi(bytes(sess.output)).rstrip()
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[-MAX_OUTPUT_CHARS:]
        body = "... [truncated]\n" + body
    return body or "(no output yet)"


def _format_waiting(sess: _ShellSession) -> str:
    body = _format_body(sess)
    last = _last_visible_line(body)
    if _looks_like_prompt(sess.output):
        if re.search(r"password", last, re.IGNORECASE):
            hint = "Awaiting password — reply with `> <password>` (input will not be echoed)."
        else:
            hint = f"Awaiting input — reply with `> <your answer>`. Prompt: {last!r}"
    else:
        hint = "Still running — reply with `> <input>` to send to stdin, or any other message to cancel."
    return f"```\n$ {sess.cmd}\n{body}\n```\n_{hint}_"


def _format_final(sess: _ShellSession, note: str = "") -> str:
    body = _format_body(sess)
    rc = sess.proc.returncode
    if sess.proc.poll() is None:
        rc_line = ""
    elif rc != 0:
        rc_line = f"\n[exit {rc}]"
    else:
        rc_line = ""
    suffix = f"\n_{note}_" if note else ""
    return f"```\n$ {sess.cmd}{rc_line}\n{body}\n```{suffix}"


# ---------------------------------------------------------------------------
# Non-PTY fallback (Windows)
# ---------------------------------------------------------------------------


def _run_shell_sync(cmd: str, timeout: int) -> str:
    """Synchronous one-shot mode: block, kill on overshoot, format as
    the legacy `run_shell` did. Does NOT create a persistent session.
    """
    logger.info("[shell] running (sync, timeout=%ss): %s", timeout, cmd[:120])
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            executable=_preferred_shell() if os.name == "posix" else None,
            env=_shell_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s: `{cmd}`"
    except Exception as exc:
        return f"Shell execution failed: {exc}"
    body = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).rstrip()
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[-MAX_OUTPUT_CHARS:]
        body = "... [truncated]\n" + body
    body = body or "(no output)"
    rc_line = f"\n[exit {proc.returncode}]" if proc.returncode != 0 else ""
    return f"```\n$ {cmd}{rc_line}\n{body}\n```"


def _run_shell_no_pty(cmd: str) -> str:
    logger.info("[shell] running (no-pty): %s", cmd[:120])
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            executable=_preferred_shell() if os.name == "posix" else None,
            env=_shell_env(),
            capture_output=True,
            text=True,
            timeout=DEFAULT_HARD_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {DEFAULT_HARD_TIMEOUT}s: `{cmd}`"
    except Exception as exc:
        return f"Shell execution failed: {exc}"
    body = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).rstrip()
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[-MAX_OUTPUT_CHARS:]
        body = "... [truncated]\n" + body
    body = body or "(no output)"
    rc_line = f"\n[exit {proc.returncode}]" if proc.returncode != 0 else ""
    return f"```\n$ {cmd}{rc_line}\n{body}\n```"
