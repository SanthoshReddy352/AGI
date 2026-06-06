"""Follow-up fixes from live session 2026-05-23 21:35–21:51.

Covers:
  • PTY controlling terminal (sudo isatty check).
  • search_conversations intent.
  • show_memories "more" flag (no verbatim repeat).
  • Slash command /research uses research_topic (not research_agent).
  • Slash command /fetch and /crawl exist.
  • modules/web exposes setup().
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# --- intent ----------------------------------------------------------------

def _make_recognizer(tools: list[str]):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in tools}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase,expected_query", [
    ("Search my conversations for programming", "programming"),
    ("search my chats for python tips", "python tips"),
    ("find in conversation history about deadlines", "deadlines"),
    ("what did we talk about last week", "last week"),
    ("what have we discussed about the deploy", "the deploy"),
])
def test_search_conversations_routes(phrase, expected_query):
    ir = _make_recognizer(["search_conversations", "search_indexed_files"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "search_conversations"
    assert result[0]["args"]["query"] == expected_query


@pytest.mark.parametrize("phrase,expects_more", [
    ("What do you know about me?", False),
    ("what have you learned about me", False),
    ("show my memories", False),
    ("What else do you know about me?", True),
    ("tell me more about me", True),
    ("anything else you remember", True),
    ("tell me everything you know about me", True),
])
def test_show_memories_more_flag(phrase, expects_more):
    ir = _make_recognizer(["show_memories"])
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == "show_memories"
    assert bool(result[0]["args"].get("more")) is expects_more


# --- slash commands --------------------------------------------------------


def test_research_slash_probes_research_topic():
    """The 2026-05-23 21:44 bug: /research said 'Capability research_agent
    is not registered' because it probed the wrong name. After fix it
    probes research_topic first.
    """
    from core import slash_commands as slash
    seen = []

    def fake_executor_execute(name, raw, args):
        seen.append(name)
        return SimpleNamespace(ok=True, output="ok", error="")

    app = SimpleNamespace(
        capability_registry=MagicMock(),
        capability_executor=SimpleNamespace(execute=fake_executor_execute),
    )
    app.capability_registry.get_handler.side_effect = (
        lambda n: object() if n == "research_topic" else None
    )

    out = slash.dispatch(app, "/research GPT history")
    assert out == "ok"
    assert seen == ["research_topic"]


def test_fetch_slash_registered():
    from core import slash_commands as slash
    names = [n for n, _, _ in slash.REGISTRY]
    assert "fetch" in names
    assert "crawl" in names


def test_fetch_slash_calls_web_extract():
    from core import slash_commands as slash
    seen = []

    def fake_executor_execute(name, raw, args):
        seen.append((name, args))
        return SimpleNamespace(ok=True, output="page text", error="")

    app = SimpleNamespace(
        capability_registry=MagicMock(),
        capability_executor=SimpleNamespace(execute=fake_executor_execute),
    )
    app.capability_registry.get_handler.side_effect = (
        lambda n: object() if n == "web_extract" else None
    )

    out = slash.dispatch(app, "/fetch https://example.com")
    assert out == "page text"
    assert seen == [("web_extract", {"url": "https://example.com"})]


# --- modules/web ----------------------------------------------------------


def test_web_module_exposes_setup():
    """Loader requires module-level setup(app); the empty __init__.py
    silently skipped registration of web_search / web_extract / web_crawl
    (the 21:50 'I cannot access external URLs' bug)."""
    import importlib
    mod = importlib.import_module("modules.web")
    assert hasattr(mod, "setup"), "modules/web must expose setup() for the loader"
    assert callable(mod.setup)


# --- PTY shell controlling TTY -------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
def test_pty_child_has_controlling_tty():
    """sudo says 'a terminal is required' when its stdin isn't a controlling
    TTY. We force TIOCSCTTY in preexec_fn — verify by running `tty` and
    confirming it returns a /dev/pts/ path (NOT 'not a tty').
    """
    import core.shell_prefix as sp
    sp.cancel_active_session(reason="test setup")
    try:
        out = sp.run_shell("!tty")
    finally:
        sp.cancel_active_session(reason="test teardown")
    assert "/dev/pts/" in out, f"child did not see a TTY: {out!r}"


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
def test_pty_sudo_no_terminal_error_is_gone():
    """`sudo -n true` should now reject with 'a password is required'
    (the EXPECTED non-interactive sudo error) rather than the OLD
    'a terminal is required to read the password' that meant the PTY
    wasn't acquired.
    """
    import core.shell_prefix as sp
    sp.cancel_active_session(reason="test setup")
    try:
        out = sp.run_shell("!sudo -n true 2>&1; echo exit=$?")
    finally:
        sp.cancel_active_session(reason="test teardown")
    # The OLD error string MUST be absent — that's the regression we fixed.
    assert "a terminal is required" not in out, f"sudo still complains about no TTY: {out!r}"
