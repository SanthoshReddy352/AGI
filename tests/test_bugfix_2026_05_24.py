"""Regression tests for the four bugs surfaced in the live session
2026-05-24 07:05-07:30.

  1. show_memories returned stale name from the legacy `user_profile`
     namespace even when the facade had been updated with a newer name.
  2. /new and /clear didn't expire the outgoing session's workflow
     rows, so a pending research_planner step (`awaiting_readout`)
     could intercept the first message of the next conversation —
     turning "Bye" into a 1-paragraph readout instead of letting
     `shutdown_assistant` fire.
  3. `/web` returns empty results when DDG rate-limits / changes
     layout; now falls back to Wikipedia.
  4. `awaiting_readout` step now treats shutdown / bail-out phrasings
     ("bye", "exit", "never mind", "/new") as workflow-not-handled so
     the outer router can dispatch the real intent.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── Bug 1: show_memories prefers facade over stale user_profile ──────────


def test_show_memories_prefers_facade_over_stale_user_profile():
    """Repro of the 2026-05-24 07:25 bug: user_profile namespace has an
    outdated name='Tricky', but the facade has name='Santhosh'. The
    facade must win — the user typed "My name is Santhosh" and the
    very next "What do you know about me?" must reflect that.
    """
    from modules.memory_manager.plugin import MemoryManagerPlugin

    # Stub context_store: returns stale "Tricky" from user_profile.
    cs = MagicMock()
    cs.get_facts_by_namespace.return_value = [
        {"key": "name", "value": "Tricky"},
        {"key": "role", "value": "Student"},
        {"key": "location", "value": "Nellore"},
    ]

    # Stub facade: returns fresh "Santhosh" for `name` via `recall`.
    facade = MagicMock()

    def fake_recall(session_id, key=None, limit=20, persona_id=""):
        from core.memory.facade import Fact
        canonical = {
            "name": "Santhosh",       # facade wins over stale Tricky
            "role": "Student",
            "location": "Nellore",
        }
        if key:
            v = canonical.get(key)
            return [Fact(key=key, value=v)] if v else []
        return [Fact(key=k, value=v) for k, v in canonical.items()]

    facade.recall.side_effect = fake_recall
    facade.list_all.return_value = []

    plugin = MemoryManagerPlugin.__new__(MemoryManagerPlugin)
    plugin.app = SimpleNamespace(
        context_store=cs,
        session_id="sess-1",
        memory_broker=SimpleNamespace(facts=facade),
    )
    plugin._facade = lambda: facade
    plugin._session_id = lambda: "sess-1"

    response = plugin._handle_show_memories("What do you know about me?", {})
    assert "Santhosh" in response, f"expected fresh name to win; got: {response!r}"
    assert "Tricky" not in response, "stale user_profile name leaked"


# ── Bug 2 / Bug 4a: /new expires all workflow rows ──────────────────────


def test_new_session_expires_all_active_workflows():
    """A dangling research_planner row from the prior session must NOT
    survive `/new` and intercept the next conversation's first message."""
    from core.slash_commands import dispatch

    expired_sessions: list[str] = []

    class _FakeStore:
        sessions = {"old-session-1": {}}

        def start_session(self, meta):
            new_id = "new-session-2"
            self.sessions[new_id] = {}
            return new_id

        def get_session_state(self, sid):
            return dict(self.sessions.get(sid, {}))

        def save_session_state(self, sid, state):
            self.sessions[sid] = dict(state)

        def expire_all_workflows(self, session_id):
            expired_sessions.append(session_id)
            return 1

    class _FakeBrowser:
        def reset_session(self):
            pass

    app = SimpleNamespace(
        session_id="old-session-1",
        context_store=_FakeStore(),
        browser_media_service=_FakeBrowser(),
        assistant_context=SimpleNamespace(history=[], bind_context_store=lambda *a: None),
        dialog_state=SimpleNamespace(reset_pending=lambda *a: None),
        routing_state=SimpleNamespace(reset_for_turn=lambda: None),
    )

    response = dispatch(app, "/new")
    assert "new conversation" in response.lower()
    assert expired_sessions == ["old-session-1"], (
        "outgoing session's workflow rows must be expired"
    )


def test_new_session_survives_missing_expire_method():
    """If the context_store stand-in doesn't expose
    `expire_all_workflows`, /new must not crash."""
    from core.slash_commands import dispatch
    cs = MagicMock(spec=["start_session", "get_session_state", "save_session_state"])
    cs.start_session.return_value = "new-1"
    cs.get_session_state.return_value = {}
    app = SimpleNamespace(
        session_id="old-1",
        context_store=cs,
        assistant_context=SimpleNamespace(history=[], bind_context_store=lambda *a: None),
        dialog_state=SimpleNamespace(reset_pending=lambda *a: None),
    )
    response = dispatch(app, "/new")
    assert "new conversation" in response.lower()


# ── Bug 4b: research_planner awaiting_readout bails on shutdown words ────


@pytest.mark.parametrize("phrase", [
    "bye",
    "goodbye",
    "see you",
    "exit",
    "quit",
    "/new",
    "/clear",
    "never mind",
    "leave it",
])
def test_research_planner_awaiting_readout_bails_on_shutdown(phrase):
    """The user says "Bye" while a research briefing is waiting to be
    read aloud. The workflow must end gracefully (`handled=False`) so
    the router can route the message through `_parse_exit` instead of
    reading the briefing at the user.
    """
    from core.reasoning.agentic_services.research_planner import (
        ResearchPlannerWorkflow,
    )

    wf = ResearchPlannerWorkflow.__new__(ResearchPlannerWorkflow)
    wf.app = MagicMock()
    wf.name = "research_planner"

    saved_state = {}

    class _StoreStub:
        def save_workflow_state(self, sid, name, state):
            saved_state.update(state)

        def get_active_workflow(self, sid, workflow_name=None):
            return {
                "step": "awaiting_readout",
                "topic": "GPT history",
                "folder": "/path/to/friday-research/x",
                "summary_path": "/path/to/x/00-summary.md",
            }

    wf._memory = lambda: _StoreStub()
    wf._save = lambda sid, ws: saved_state.update(ws)

    state = {"user_text": phrase, "session_id": "s1"}
    result_state = wf._handle(state)

    # Workflow should have marked itself done...
    assert saved_state.get("step") == "done", (
        f"workflow didn't end after bail-out phrase {phrase!r}"
    )
    # ...and returned handled=False so the router picks up the real intent.
    from core.workflow_orchestrator import WorkflowResult  # local import
    wr = result_state.get("result")
    assert isinstance(wr, WorkflowResult)
    assert wr.handled is False, (
        f"workflow should NOT have handled bail-out phrase {phrase!r} "
        "(must yield to the outer router)"
    )


def test_research_planner_awaiting_readout_still_reads_on_yes():
    """The bail-out fix must not regress the happy path."""
    from core.reasoning.agentic_services.research_planner import (
        ResearchPlannerWorkflow,
    )

    wf = ResearchPlannerWorkflow.__new__(ResearchPlannerWorkflow)
    wf.app = MagicMock()
    wf.name = "research_planner"

    class _StoreStub:
        def get_active_workflow(self, sid, workflow_name=None):
            return {
                "step": "awaiting_readout",
                "topic": "GPT history",
                "folder": "/x",
                "summary_path": "/x/00-summary.md",
            }

    wf._memory = lambda: _StoreStub()
    wf._save = lambda sid, ws: None
    wf._summary_for_speech = lambda path: "Here's the briefing on GPT history."

    state = {"user_text": "yes please", "session_id": "s1"}
    result = wf._handle(state)
    from core.workflow_orchestrator import WorkflowResult as _WR
    wr = result.get("result")
    assert isinstance(wr, _WR)
    assert wr.handled is True
    assert "GPT history" in wr.response


# ── Bug 3: /web falls back to Wikipedia when DDG returns empty ──────────


def test_web_search_falls_back_to_wikipedia_on_empty_ddg():
    """The 2026-05-24 07:29 bug: DDG returned 0 results for the same
    query that returned 5 hits 22 minutes earlier. Wikipedia fallback
    must surface a usable answer."""
    from modules.web import plugin as web_plugin

    captured: dict = {}

    def fake_summary_for_query(q):
        captured["q"] = q
        return {
            "title": "Attack on Titan",
            "extract": "Attack on Titan is a Japanese manga series…",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Attack_on_Titan"}},
        }

    with patch.object(web_plugin, "_ddg_search", return_value=[]), \
         patch("modules.sources.wikipedia.summary_for_query", side_effect=fake_summary_for_query):
        plugin = web_plugin.WebPlugin.__new__(web_plugin.WebPlugin)
        plugin.app = MagicMock()
        out = plugin._handle_search("anything", {"query": "Attack on Titan"})

    assert "Attack on Titan" in out
    assert "Wikipedia" in out
    assert "en.wikipedia.org" in out
    assert captured["q"] == "Attack on Titan"


def test_web_search_returns_ddg_results_when_present():
    """The Wikipedia fallback must NOT fire when DDG actually returned hits."""
    from modules.web import plugin as web_plugin

    wiki_called = {"count": 0}

    def _track(q):
        wiki_called["count"] += 1
        return None

    with patch.object(web_plugin, "_ddg_search", return_value=[
        {"title": "Result 1", "url": "https://r1", "snippet": "first"},
        {"title": "Result 2", "url": "https://r2", "snippet": "second"},
    ]), patch("modules.sources.wikipedia.summary_for_query", side_effect=_track):
        plugin = web_plugin.WebPlugin.__new__(web_plugin.WebPlugin)
        plugin.app = MagicMock()
        out = plugin._handle_search("anything", {"query": "x"})

    assert "Result 1" in out and "Result 2" in out
    assert "Wikipedia" not in out
    assert wiki_called["count"] == 0


def test_web_search_handles_wiki_fallback_failure_gracefully():
    """If both DDG and Wikipedia return nothing, surface a clean
    "no results" line — not a stacktrace."""
    from modules.web import plugin as web_plugin
    with patch.object(web_plugin, "_ddg_search", return_value=[]), \
         patch("modules.sources.wikipedia.summary_for_query", return_value=None):
        plugin = web_plugin.WebPlugin.__new__(web_plugin.WebPlugin)
        plugin.app = MagicMock()
        out = plugin._handle_search("anything", {"query": "obscure_xyz_query"})
    assert "no results" in out.lower() or "no result" in out.lower()
