"""Cognee in real conversation: the steering block + the opt-in proactive
recall-context injection (the "Namma remembers you in a fresh chat" safety net)."""
from __future__ import annotations

from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry, ToolResult


class DummyProvider(Provider):
    name = "dummy"

    def __init__(self):
        super().__init__(model="dummy")

    def is_available(self):
        return True

    def generate(self, *a, **k):
        return LLMResponse(content="")


def _reg_with_recall(answer="Santhosh loves Python and is building Namma Agent.", calls=None):
    reg = ToolRegistry()

    def handler(args):
        if calls is not None:
            calls.append(args)
        return ToolResult(ok=True, content=answer)

    reg.register("mcp_cognee_recall", "[cognee] recall",
                 {"type": "object", "properties": {"query": {"type": "string"}}}, handler)
    return reg


def _agent(reg, recall_context=False):
    db = Database(":memory:")
    a = Agent(DummyProvider(), reg, db, load_persona(), cognee_recall_context=recall_context)
    return a, db.create_session()


def test_steering_present_when_cognee_recall_registered():
    a, sid = _agent(_reg_with_recall())
    system = a._build_messages("hello", sid)[0]["content"]
    assert "COGNEE MEMORY" in system
    assert "mcp_cognee_recall" in system
    assert "before answering any question about the user" in system.lower()


def test_no_steering_without_cognee():
    db = Database(":memory:")
    a = Agent(DummyProvider(), ToolRegistry(), db, load_persona())
    system = a._build_messages("hello", db.create_session())[0]["content"]
    assert "COGNEE MEMORY" not in system


def test_recall_context_off_by_default_no_injection():
    calls = []
    a, sid = _agent(_reg_with_recall(calls=calls), recall_context=False)
    system = a._build_messages("what do you know about me?", sid)[0]["content"]
    assert "RELEVANT MEMORY" not in system
    assert calls == []                     # recall NOT proactively called → stays visible


def test_recall_context_injects_on_recall_question():
    calls = []
    a, sid = _agent(_reg_with_recall(calls=calls), recall_context=True)
    system = a._build_messages("what do you know about me?", sid)[0]["content"]
    assert "RELEVANT MEMORY" in system
    assert "loves Python" in system
    assert calls and calls[0]["query"] == "what do you know about me?"


def test_recall_context_skips_non_recall_message():
    calls = []
    a, sid = _agent(_reg_with_recall(calls=calls), recall_context=True)
    system = a._build_messages("write a poem about the sea", sid)[0]["content"]
    assert "RELEVANT MEMORY" not in system
    assert calls == []                     # not a recall-style question → no proactive call


def test_recall_context_skips_empty_recall_result():
    calls = []
    a, sid = _agent(_reg_with_recall(answer="(no result)", calls=calls), recall_context=True)
    system = a._build_messages("remind me what I told you", sid)[0]["content"]
    assert "RELEVANT MEMORY" not in system  # nothing useful to inject
