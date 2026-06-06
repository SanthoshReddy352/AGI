"""P3.7 — Code execution sandbox."""
import pytest
from unittest.mock import MagicMock

from modules.code_execution.plugin import (
    CodeExecutionPlugin, run_python, run_bash, _extract_code,
)


# ── run_python ────────────────────────────────────────────────────────────────

def test_run_python_simple_expression():
    stdout, stderr, rc = run_python("print(2 + 2)")
    assert stdout.strip() == "4"
    assert rc == 0


def test_run_python_syntax_error():
    stdout, stderr, rc = run_python("def broken(")
    assert rc != 0
    assert "SyntaxError" in stderr or stderr


def test_run_python_timeout():
    stdout, stderr, rc = run_python("import time; time.sleep(10)", timeout=1)
    assert rc == 124
    assert "Timed out" in stderr


def test_run_python_no_output():
    stdout, stderr, rc = run_python("x = 1 + 1")
    assert stdout.strip() == ""
    assert rc == 0


# ── run_bash ─────────────────────────────────────────────────────────────────

def test_run_bash_simple_command():
    stdout, stderr, rc = run_bash("echo hello")
    assert "hello" in stdout
    assert rc == 0


def test_run_bash_error():
    stdout, stderr, rc = run_bash("exit 1")
    assert rc != 0


# ── _extract_code ─────────────────────────────────────────────────────────────

def test_extract_code_compute_prefix():
    code = _extract_code("compute 47 * 3.14")
    assert "47" in code and "3.14" in code
    assert "print(" in code  # wrapped for output


def test_extract_code_raw_expression():
    code = _extract_code("what is 2 + 2")
    assert "2" in code


# ── Plugin capability ─────────────────────────────────────────────────────────

def _make_plugin(enabled=True):
    app = MagicMock()
    app.register_capability = MagicMock()
    plugin = CodeExecutionPlugin.__new__(CodeExecutionPlugin)
    plugin.app = app
    plugin.name = "CodeExecution"
    plugin._is_enabled = lambda: enabled
    plugin._timeout = lambda: 5
    plugin.on_load = CodeExecutionPlugin.on_load.__get__(plugin, CodeExecutionPlugin)
    plugin.on_load()
    return plugin


def test_plugin_disabled_returns_message():
    plugin = _make_plugin(enabled=False)
    plugin._is_enabled = lambda: False
    plugin._handle_evaluate = CodeExecutionPlugin._handle_evaluate.__get__(
        plugin, CodeExecutionPlugin
    )
    result = plugin._handle_evaluate("compute 2 + 2", {"code": "print(2+2)"})
    assert "disabled" in result.lower()


def test_plugin_no_code_returns_prompt():
    plugin = _make_plugin(enabled=True)
    plugin._is_enabled = lambda: True
    plugin._handle_evaluate = CodeExecutionPlugin._handle_evaluate.__get__(
        plugin, CodeExecutionPlugin
    )
    result = plugin._handle_evaluate("", {"code": ""})
    assert "provide" in result.lower() or "code" in result.lower()


def test_plugin_runs_python_and_returns_output():
    plugin = _make_plugin(enabled=True)
    plugin._is_enabled = lambda: True
    plugin._handle_evaluate = CodeExecutionPlugin._handle_evaluate.__get__(
        plugin, CodeExecutionPlugin
    )
    result = plugin._handle_evaluate("run python", {"code": "print(42)", "language": "python"})
    assert "42" in result
