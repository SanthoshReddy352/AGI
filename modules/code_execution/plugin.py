"""P3.7 — Sandboxed code execution.

Runs Python or Bash snippets in a subprocess with:
  - 5-second wall-clock timeout (configurable)
  - Isolated temp working directory (/tmp/friday-sandbox/<turn_id>)
  - Stripped environment (no AWS/cloud credentials, minimal PATH)
  - Output capped at 2000 characters

Default-off: requires `code_execution.enabled: true` in config.yaml.

Examples:
  Friday, compute 47 times 3.14
  Friday, run: import math; print(math.sqrt(2))
  Friday, what is 2 to the power of 32?
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid

from core.plugin_manager import FridayPlugin
from core.logger import logger

# Use the platform temp dir so the sandbox works on Windows (%TEMP%) and
# macOS as well as Linux (/tmp); a bare "/tmp" path is not portable.
_SANDBOX_ROOT = os.path.join(tempfile.gettempdir(), "friday-sandbox")
_DEFAULT_TIMEOUT = 5  # seconds
_MAX_OUTPUT = 2000    # characters


def _safe_env() -> dict:
    """Return a stripped environment for subprocess execution."""
    keep = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE"}
    return {k: v for k, v in os.environ.items() if k in keep}


def run_python(code: str, timeout: int = _DEFAULT_TIMEOUT) -> tuple[str, str, int]:
    """Execute Python code in isolation. Returns (stdout, stderr, returncode)."""
    work_dir = os.path.join(_SANDBOX_ROOT, uuid.uuid4().hex[:8])
    os.makedirs(work_dir, exist_ok=True)
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=work_dir,
            env=_safe_env(),
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Timed out after {timeout}s", 124
    except Exception as exc:
        return "", str(exc), 1
    finally:
        _cleanup(work_dir)


def run_bash(code: str, timeout: int = _DEFAULT_TIMEOUT) -> tuple[str, str, int]:
    """Execute a Bash snippet in isolation. Returns (stdout, stderr, returncode)."""
    work_dir = os.path.join(_SANDBOX_ROOT, uuid.uuid4().hex[:8])
    os.makedirs(work_dir, exist_ok=True)
    script = os.path.join(work_dir, "run.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/bash\nset -euo pipefail\n")
        fh.write(code)
    os.chmod(script, 0o700)
    try:
        restricted_env = {**_safe_env(), "PATH": "/usr/bin:/bin"}
        result = subprocess.run(
            ["/bin/bash", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=work_dir,
            env=restricted_env,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Timed out after {timeout}s", 124
    except Exception as exc:
        return "", str(exc), 1
    finally:
        _cleanup(work_dir)


def _cleanup(path: str) -> None:
    try:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


class CodeExecutionPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "CodeExecution"
        self.on_load()

    def _is_enabled(self) -> bool:
        cfg = getattr(self.app, "config", None)
        if cfg and hasattr(cfg, "get"):
            return str(cfg.get("code_execution.enabled", "false")).lower() == "true"
        return False

    def _timeout(self) -> int:
        cfg = getattr(self.app, "config", None)
        if cfg and hasattr(cfg, "get"):
            return int(cfg.get("code_execution.timeout_sec", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT)
        return _DEFAULT_TIMEOUT

    def on_load(self):
        self.app.register_capability(
            {
                "name": "evaluate_code",
                "description": (
                    "Run a Python or Bash snippet and return the output. "
                    "Use for calculations, data transformations, or quick scripts."
                ),
                "parameters": {
                    "code": "string — the code to run",
                    "language": "string — 'python' or 'bash' (default: python)",
                },
                "aliases": [
                    "compute", "calculate", "evaluate", "run this code",
                    "execute", "run python", "run bash", "what is",
                    "eval", "python", "bash",
                ],
                "patterns": [
                    r"\b(?:compute|calculate|eval(?:uate)?)\b",
                    r"\brun\s+(?:this\s+)?(?:code|script|python|bash)\b",
                    r"\bwhat\s+is\s+\d+\s*[\+\-\*\/\^]\s*\d+",
                    r"\bexecute\s+(?:this\s+)?(?:code|script)\b",
                ],
                "context_terms": [
                    "compute", "calculate", "run code", "python script",
                    "bash script", "evaluate", "what is the result",
                ],
                "permission_mode": "always_ok",
            },
            self._handle_evaluate,
        )
        logger.info("[code_execution] CodeExecutionPlugin loaded.")

    def _handle_evaluate(self, raw_text: str, args: dict) -> str:
        if not self._is_enabled():
            return (
                "Code execution is disabled. "
                "Set `code_execution.enabled: true` in config.yaml to enable it."
            )
        code = args.get("code") or _extract_code(raw_text)
        lang = (args.get("language") or "python").lower().strip()
        if not code:
            return "Please provide the code or expression to evaluate."

        timeout = self._timeout()
        if lang == "bash":
            stdout, stderr, rc = run_bash(code, timeout=timeout)
        else:
            stdout, stderr, rc = run_python(code, timeout=timeout)

        output = stdout.strip()
        err = stderr.strip()

        if not output and not err:
            return "The code ran successfully but produced no output."
        if rc == 124:
            return f"Code timed out after {timeout}s."
        if output:
            trimmed = output[:_MAX_OUTPUT]
            if len(output) > _MAX_OUTPUT:
                trimmed += "… [output truncated]"
            return trimmed
        if err:
            return f"Error:\n{err[:_MAX_OUTPUT]}"
        return f"Exited with code {rc}."


import re as _re


def _extract_code(text: str) -> str:
    """Extract code from a natural-language request."""
    # Match: "compute X", "calculate X", "what is X" where X looks like math
    m = _re.search(
        r"(?:compute|calculate|eval(?:uate)?|what\s+is|run)\s+:?\s*(.+)$",
        text, _re.IGNORECASE
    )
    if m:
        snippet = m.group(1).strip()
        # Wrap pure expressions as print() for output
        if not snippet.startswith(("print", "import", "def ", "class ", "for ", "if ", "#")):
            snippet = f"print({snippet})"
        return snippet
    return text.strip()
