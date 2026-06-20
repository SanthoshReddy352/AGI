"""Secure sudo askpass flow — prompt the UI once, retry with `sudo -S`, leak nothing."""
from __future__ import annotations

import subprocess

import namma_agent.tools.shell as shell
from namma_agent.core.interactive import set_askpass
from namma_agent.core.tools import ToolRegistry


def _cp(rc, out="", err=""):
    return subprocess.CompletedProcess(args="x", returncode=rc, stdout=out, stderr=err)


def test_sudo_rewrites_to_noninteractive():
    assert shell._noninteractive_sudo("sudo apt update") == "sudo -n apt update"
    assert shell._noninteractive_sudo("echo a && sudo b") == "echo a && sudo -n b"
    assert shell._noninteractive_sudo("sudo -n x") == "sudo -n x"  # untouched


def test_askpass_retry_with_password(monkeypatch):
    calls = []

    def fake_run(cmd, timeout, password=None):
        calls.append((cmd, password))
        if password is None:
            return _cp(1, err="sudo: a password is required")   # first try fails
        return _cp(0, out="Reading package lists... Done")        # retry with -S works

    monkeypatch.setattr(shell, "_run", fake_run)
    set_askpass(lambda prompt: "hunter2")
    try:
        reg = ToolRegistry()
        shell.register(reg)
        out = reg.execute("run_shell", {"command": "sudo apt update"})
    finally:
        set_askpass(None)

    assert out.ok and "Done" in out.content
    assert calls[0] == ("sudo -n apt update", None)              # first: non-interactive
    assert calls[1][0] == "sudo -S -p '' apt update"            # retry uses -S
    assert calls[1][1] == "hunter2"                              # password fed to sudo only
    # The password must never appear in what the model/user sees.
    assert "hunter2" not in out.content and "hunter2" not in (out.error or "")


def test_no_askpass_fails_fast(monkeypatch):
    monkeypatch.setattr(shell, "_run", lambda cmd, timeout, password=None: _cp(1, err="sudo: a password is required"))
    set_askpass(None)  # no UI connected → no prompt, just a clear failure
    reg = ToolRegistry()
    shell.register(reg)
    out = reg.execute("run_shell", {"command": "sudo apt update"})
    assert not out.ok and "passwordless sudo" in out.content
