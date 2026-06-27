"""The four Cognee memory-lifecycle ops behind the Memory tab — focus on the
**improve** op (session buffer → consolidate → cognify), which the cognee-mcp image
has no direct tool for. Offline: the cognee MCP client is faked.
"""
from __future__ import annotations

import pytest

from namma_agent.service import NammaAgentService


class FakeCogneeClient:
    def __init__(self):
        self.calls = []        # (tool, args)

    def call_tool(self, tool, args, timeout=None):
        self.calls.append((tool, dict(args or {})))
        return f"{tool}: ok"

    def list_tools(self):
        return [{"name": n} for n in ("remember", "recall", "forget")]


@pytest.fixture
def svc(monkeypatch):
    s = NammaAgentService.__new__(NammaAgentService)   # skip heavy __init__
    client = FakeCogneeClient()
    s._cognee_client = lambda: client
    s._fake = client
    return s


def test_session_remember_buffers_for_consolidation(svc):
    r = svc.cognee_remember("I love Python", permanent=False)
    assert r["ok"] and r["pending_consolidation"] == 1
    # stored to the session cache (fast, no graph build)
    tool, args = svc._fake.calls[-1]
    assert tool == "remember" and args.get("session_id") == "namma_ui"
    assert svc.cognee_pending() == 1


def test_permanent_remember_does_not_buffer(svc):
    r = svc.cognee_remember("I am building Namma Agent", permanent=True)
    assert r["ok"] and svc.cognee_pending() == 0
    tool, args = svc._fake.calls[-1]
    assert tool == "remember" and "session_id" not in args   # straight to cognify


def test_consolidate_promotes_buffer_to_graph_then_clears(svc):
    svc.cognee_remember("fact one", permanent=False)
    svc.cognee_remember("fact two", permanent=False)
    assert svc.cognee_pending() == 2

    out = svc.cognee_consolidate()
    assert out["ok"] and out["consolidated"] == 2 and out["pending_consolidation"] == 0
    # each buffered note was cognified permanently (no session_id this time)
    permanent_calls = [a for (t, a) in svc._fake.calls if t == "remember" and "session_id" not in a]
    assert {c["data"] for c in permanent_calls} == {"fact one", "fact two"}
    assert svc.cognee_pending() == 0   # buffer cleared


def test_consolidate_with_nothing_pending_is_friendly(svc):
    out = svc.cognee_consolidate()
    assert out["ok"] and out["consolidated"] == 0
    assert "Nothing pending" in out["content"]


def test_remember_rejects_empty(svc):
    out = svc.cognee_remember("   ", permanent=False)
    assert out["ok"] is False and svc.cognee_pending() == 0


def test_consolidate_offline_errors_cleanly():
    s = NammaAgentService.__new__(NammaAgentService)
    s._cognee_client = lambda: None
    out = s.cognee_consolidate()
    assert out["ok"] is False and "not connected" in out["error"]


class FakeDB:
    def __init__(self, facts=None, turns=None):
        self._facts, self._turns = facts or [], turns or []

    def search_facts(self, query, limit=10):
        return self._facts

    def search_turns(self, query, limit=10):
        return self._turns


def test_memory_compare_keyword_miss_cognee_hit(svc):
    # keyword search finds nothing; Cognee answers → the money shot
    svc.db = FakeDB(facts=[], turns=[])
    out = svc.memory_compare("which database engine do I favour?")
    assert out["ok"]
    assert out["fts"]["count"] == 0
    assert out["cognee"]["connected"] is True
    assert "recall:" in out["cognee"]["answer"]   # from FakeCogneeClient


def test_memory_compare_includes_keyword_hits(svc):
    svc.db = FakeDB(facts=[{"key": "language", "value": "Python"}],
                    turns=[{"role": "user", "content": "I love Python"}])
    out = svc.memory_compare("python")
    assert out["ok"] and out["fts"]["count"] == 2
    kinds = {h["kind"] for h in out["fts"]["hits"]}
    assert "fact" in kinds and "user" in kinds


def test_memory_compare_rejects_empty(svc):
    svc.db = FakeDB()
    out = svc.memory_compare("  ")
    assert out["ok"] is False
