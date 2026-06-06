"""P3.17 — Tool guardrails."""
import pytest
from core.safety.tool_guardrails import ToolGuardrails


def test_safe_file_path_passes():
    g = ToolGuardrails()
    import os
    ok, reason = g.check("open_file", {"filename": os.path.expanduser("~/notes.txt")})
    assert ok, reason


def test_traversal_path_blocked():
    g = ToolGuardrails()
    ok, reason = g.check("open_file", {"filename": "/tmp/../etc/passwd"})
    assert not ok
    assert "path" in reason.lower() or "traversal" in reason.lower() or "unsafe" in reason.lower()


def test_safe_url_passes():
    g = ToolGuardrails()
    ok, reason = g.check("open_browser_url", {"url": "https://en.wikipedia.org/"})
    assert ok, reason


def test_private_url_blocked():
    g = ToolGuardrails()
    ok, reason = g.check("open_browser_url", {"url": "http://192.168.1.1/admin"})
    assert not ok


def test_non_file_tool_no_path_check():
    g = ToolGuardrails()
    ok, _ = g.check("llm_chat", {"query": "hello"})
    assert ok


def test_custom_validator_registered():
    g = ToolGuardrails()
    called = []

    def my_validator(tool_name, args):
        called.append(tool_name)
        return True, ""

    g.register("my_tool", my_validator)
    ok, _ = g.check("my_tool", {})
    assert ok
    assert "my_tool" in called


def test_custom_validator_can_block():
    g = ToolGuardrails()
    g.register("risky_tool", lambda name, args: (False, "blocked by policy"))
    ok, reason = g.check("risky_tool", {})
    assert not ok
    assert "policy" in reason
