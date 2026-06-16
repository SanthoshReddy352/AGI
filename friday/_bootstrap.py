"""Launch-time guard: make `python -m friday` work no matter which interpreter
was typed.

If the app is started with a Python that lacks the project's runtime deps — most
commonly the system `/usr/bin/python` instead of the project virtualenv — the
provider SDK (`openai`) isn't importable, every provider reports "unavailable",
and turns fail with the opaque "All providers failed. Last error: None".

`ensure_venv()` detects that case and re-execs into the project's `.venv`
interpreter so the right packages are present. It's a no-op when the current
interpreter already has the deps, when there's no `.venv`, or when explicitly
disabled with FRIDAY_NO_REEXEC=1.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _has_provider_sdk() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_venv() -> None:
    if os.environ.get("FRIDAY_NO_REEXEC") or _has_provider_sdk():
        return

    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / ".venv" / "bin" / "python",        # POSIX
        repo_root / ".venv" / "Scripts" / "python.exe",  # Windows
    ]
    # NB: compare *literal* paths, not realpath — a venv's python is typically a
    # symlink to the base interpreter; what makes it a venv (its site-packages) is
    # the invocation path, so resolving it would wrongly look identical to system
    # python and skip the switch.
    here = os.path.abspath(sys.executable)
    for py in candidates:
        if py.exists() and os.path.abspath(str(py)) != here:
            # Guard against a re-exec loop if the venv is somehow also missing deps.
            os.environ["FRIDAY_NO_REEXEC"] = "1"
            print(f"[friday] switching to project venv: {py}", file=sys.stderr)
            os.execv(str(py), [str(py), "-m", "friday", *sys.argv[1:]])
    # No usable venv found — proceed; the provider layer will surface a clear error.
