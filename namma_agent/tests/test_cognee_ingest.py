"""CogneeIngestor — the opt-in background bridge that grows the Cognee graph.

These tests are offline: the cognee MCP client is faked, so they verify the
gating + queueing logic (not real cognify). Covers per-turn auto-ingest and the
Learning-Room recap path, including their independent enable switches and the
silent no-op when Cognee isn't connected.
"""
from __future__ import annotations

import threading

from namma_agent.core.cognee_ingest import CogneeIngestor


class FakeClient:
    """Records remember() calls and signals when one lands."""
    def __init__(self):
        self.calls = []
        self.got = threading.Event()

    def call_tool(self, name, args, timeout=None):
        self.calls.append((name, args))
        self.got.set()
        return {"ok": True}


def test_ingest_learning_gated_off():
    client = FakeClient()
    ing = CogneeIngestor(lambda: client, learning_enabled=False)
    ing.ingest_learning("A solid recap of a completed module about neurons.")
    assert not client.got.wait(0.5)
    assert client.calls == []


def test_ingest_learning_pushes_when_enabled():
    client = FakeClient()
    ing = CogneeIngestor(lambda: client, enabled=False, learning_enabled=True)
    # learning path is independent of the per-turn `enabled` switch.
    ing.ingest_learning("A solid recap of a completed module about neurons.")
    assert client.got.wait(2.0), "an enabled learning recap should reach Cognee"
    name, args = client.calls[0]
    assert name == "remember"
    assert "neurons" in args["data"]


def test_ingest_learning_noop_when_disconnected():
    ing = CogneeIngestor(lambda: None, learning_enabled=True)
    # No client connected → drops silently, no exception.
    ing.ingest_learning("A solid recap of a completed module about neurons.")
    # Nothing to assert beyond "did not raise"; give the worker a moment.
    if ing._worker:
        ing._worker.join(0.3)


def test_ingest_learning_skips_short_text():
    client = FakeClient()
    ing = CogneeIngestor(lambda: client, learning_enabled=True, min_chars=24)
    ing.ingest_learning("too short")
    assert not client.got.wait(0.4)
    assert client.calls == []


def test_auto_ingest_turn_gated_off():
    client = FakeClient()
    ing = CogneeIngestor(lambda: client, enabled=False)
    ing.ingest_async("A long enough user message about the data layer design.")
    assert not client.got.wait(0.4)
    assert client.calls == []
