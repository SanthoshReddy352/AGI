"""Track 6.3 — `!`-prefix shell executor tests."""
from __future__ import annotations

import pytest

from core.shell_prefix import is_shell_command, run_shell


def test_is_shell_command_positive():
    assert is_shell_command("!ls") is True
    assert is_shell_command("  !echo hi") is True
    assert is_shell_command("!whoami | head -1") is True


def test_is_shell_command_rejects_chat_emphasis():
    assert is_shell_command("!") is False
    assert is_shell_command("!!") is False
    assert is_shell_command("!?") is False
    assert is_shell_command("!.") is False
    assert is_shell_command("hello!") is False
    assert is_shell_command("") is False


def test_run_shell_captures_stdout():
    out = run_shell("!echo HELLO_FRIDAY")
    assert "HELLO_FRIDAY" in out
    assert out.startswith("```")
    assert out.endswith("```")


def test_run_shell_includes_exit_code_when_nonzero():
    out = run_shell("!bash -c 'exit 7'")
    assert "[exit 7]" in out


def test_run_shell_timeout():
    out = run_shell("!sleep 30", timeout=1)
    assert "timed out" in out.lower()
    assert "30" in out or "sleep" in out


def test_run_shell_empty_after_prefix():
    out = run_shell("!")
    assert "empty" in out.lower()


def test_run_shell_merges_stderr():
    out = run_shell("!bash -c 'echo out; echo err >&2'")
    assert "out" in out
    assert "err" in out


# ---------------------------------------------------------------------------
# Interactive PTY-backed mode (2026-05-23)
# ---------------------------------------------------------------------------

import os
import sys
import time

import core.shell_prefix as _sp


@pytest.fixture(autouse=True)
def _clear_active():
    _sp.cancel_active_session(reason="test setup")
    yield
    _sp.cancel_active_session(reason="test teardown")


def test_is_shell_followup_recognises_gt_prefix():
    assert _sp.is_shell_followup("> password123") is True
    assert _sp.is_shell_followup(">y") is True
    assert _sp.is_shell_followup("  > continue") is True
    # `>>` is shell append, not a follow-up
    assert _sp.is_shell_followup(">> foo") is False
    # Plain text
    assert _sp.is_shell_followup("yes") is False
    assert _sp.is_shell_followup("") is False


@pytest.mark.skipif(os.name != "posix", reason="PTY only on POSIX")
def test_interactive_session_captures_stdin_via_followup():
    """A python child that reads stdin should see the `>` follow-up content."""
    py = sys.executable
    out = _sp.run_shell(
        f"!{py} -u -c \"x=input('prompt> '); print('GOT:', x)\""
    )
    # Initial run should leave a session alive, waiting on input.
    assert _sp.has_active_session(), f"session not alive: {out!r}"
    assert "awaiting" in out.lower() or "still running" in out.lower()

    # Feed the line the child is waiting on.
    final = _sp.feed_followup("> sahiba")
    assert "GOT: sahiba" in final, f"stdin not piped through: {final!r}"
    assert not _sp.has_active_session()


@pytest.mark.skipif(os.name != "posix", reason="PTY only on POSIX")
def test_cancel_active_session_kills_long_running():
    out = _sp.run_shell("!sleep 30")
    assert _sp.has_active_session(), f"sleep did not become an active session: {out!r}"
    final = _sp.cancel_active_session(reason="test")
    assert final is not None
    assert not _sp.has_active_session()


@pytest.mark.skipif(os.name != "posix", reason="PTY only on POSIX")
def test_feed_followup_without_active_session_is_safe():
    assert not _sp.has_active_session()
    out = _sp.feed_followup("> hello")
    assert "no active" in out.lower()


@pytest.mark.skipif(os.name != "posix", reason="PTY only on POSIX")
def test_new_run_supersedes_old_session():
    """Starting a new `!cmd` while one is active must kill the old one."""
    _sp.run_shell("!sleep 30")
    assert _sp.has_active_session()
    # New short-lived command supersedes.
    out = _sp.run_shell("!echo NEW_CMD")
    assert "NEW_CMD" in out
    # New command was short-lived; no session should be alive now.
    assert not _sp.has_active_session()


# ---------------------------------------------------------------------------
# bash + venv injection (2026-05-24)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
def test_preferred_shell_is_bash_when_available():
    """`source` is a bash builtin — dash doesn't have it. We must pick
    /bin/bash so user-friendly idioms work."""
    import core.shell_prefix as sp
    shell = sp._preferred_shell()
    # On any modern Linux desktop /bin/bash exists; if it didn't, we'd
    # fall back to /bin/sh but the test environment should have bash.
    assert shell in ("/bin/bash", "/usr/bin/bash", "/bin/sh")
    if os.path.exists("/bin/bash"):
        assert shell == "/bin/bash", "must prefer bash when present"


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="bash required")
def test_bash_builtin_source_works():
    """The 2026-05-24 06:37 bug: `!source .venv/bin/activate` failed with
    `/bin/sh: 1: source: not found` because shell=True picked dash. With
    /bin/bash explicit, source works."""
    import core.shell_prefix as sp
    sp.cancel_active_session(reason="test setup")
    out = sp.run_shell("!source /dev/null && echo SOURCE_WORKED", timeout=5)
    assert "SOURCE_WORKED" in out
    assert "not found" not in out.lower()


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
@pytest.mark.skipif(not os.path.exists("/bin/bash"), reason="bash required")
def test_bash_double_bracket_works():
    """[[ ]] is a bash-only test command; dash has no equivalent."""
    import core.shell_prefix as sp
    sp.cancel_active_session(reason="test setup")
    out = sp.run_shell("!if [[ 1 -eq 1 ]]; then echo BASH_TEST_OK; fi", timeout=5)
    assert "BASH_TEST_OK" in out


def test_venv_is_detected_when_present():
    """`.venv/` at the repo root should be auto-detected so `!python`
    transparently uses the project interpreter."""
    import core.shell_prefix as sp
    venv = sp._venv_path()
    if not venv:
        pytest.skip("no .venv in project root — test only meaningful when one exists")
    assert venv.endswith(".venv") or venv.endswith("venv") or venv.endswith(".env")
    assert os.path.isdir(venv)


def test_shell_env_prepends_venv_bin_to_path():
    """`_shell_env()` must put `<venv>/bin` at the front of PATH and set
    VIRTUAL_ENV — otherwise `!python script.py` runs the system python."""
    import core.shell_prefix as sp
    venv = sp._venv_path()
    if not venv:
        pytest.skip("no .venv in project root")
    env = sp._shell_env()
    bin_dir = os.path.join(venv, "bin")
    assert env.get("PATH", "").startswith(bin_dir + os.pathsep), (
        f"PATH should start with {bin_dir}; got {env.get('PATH', '')[:120]}"
    )
    assert env.get("VIRTUAL_ENV") == venv
    # PYTHONHOME messes with venv resolution if set.
    assert "PYTHONHOME" not in env


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
def test_which_python_returns_venv_binary_without_activate():
    """End-to-end: `!which python` must return the venv binary even
    though the user never typed `source .venv/bin/activate`."""
    import core.shell_prefix as sp
    venv = sp._venv_path()
    if not venv:
        pytest.skip("no .venv in project root")
    sp.cancel_active_session(reason="test setup")
    out = sp.run_shell("!which python", timeout=5)
    assert os.path.join(venv, "bin", "python") in out, (
        f"venv python not on PATH; got:\n{out}"
    )
