"""Phase 2 tests — the agent loop (tool calling, persistence, events)."""
from __future__ import annotations

from friday.core.agent import Agent
from friday.core.builtins import register_memory_tools
from friday.core.memory import Database
from friday.core.persona import load_persona
from friday.core.providers.base import LLMResponse, Provider, ToolCall
from friday.core.tools import ToolRegistry, ToolResult


class ScriptedProvider(Provider):
    """Returns a queued list of responses, one per generate() call."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)
        self.seen_messages = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None):
        self.seen_messages.append(list(messages))
        resp = self._responses.pop(0)
        if stream and on_token and resp.content:
            on_token(resp.content)
        return resp


def _agent(responses, registry=None):
    db = Database(":memory:")
    reg = registry or ToolRegistry()
    events = []
    agent = Agent(ScriptedProvider(responses), reg, db, load_persona(),
                  emit=lambda e, p: events.append((e, p)))
    return agent, db, events


def test_plain_chat_turn_persists():
    agent, db, events = _agent([LLMResponse(content="Hello!")])
    result = agent.process_turn("hi")
    assert result.content == "Hello!"
    turns = db.recent_turns(result.session_id)
    assert turns == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    assert ("turn_completed", events[-1][1]) == ("turn_completed", events[-1][1])
    assert events[-1][0] == "turn_completed"


def test_tool_call_executes_and_feeds_back():
    reg = ToolRegistry()
    calls = {}

    def echo(args):
        calls["args"] = args
        return f"echoed:{args.get('x')}"

    reg.register("echo", "echo a value", {
        "type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"],
    }, echo)

    responses = [
        LLMResponse(content="On it.", tool_calls=[ToolCall(id="t1", name="echo", args={"x": "hi"})]),
        LLMResponse(content="Done — got hi."),
    ]
    agent, db, events = _agent(responses, registry=reg)
    result = agent.process_turn("echo hi")

    assert calls["args"] == {"x": "hi"}
    assert result.content == "Done — got hi."
    assert result.tools_used == ["echo"]
    # preamble + tool_started + tool_finished emitted
    kinds = [e for e, _ in events]
    assert "preamble" in kinds and "tool_started" in kinds and "tool_finished" in kinds
    # the second generate() call saw the tool result in its messages
    second_call = agent.provider.seen_messages[1]
    assert any(m.get("role") == "tool" and m.get("content") == "echoed:hi" for m in second_call)


def test_unknown_tool_returns_error_to_model():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="nope", args={})]),
        LLMResponse(content="Recovered."),
    ]
    agent, db, events = _agent(responses)
    result = agent.process_turn("do nope")
    assert result.content == "Recovered."
    second_call = agent.provider.seen_messages[1]
    tool_msg = [m for m in second_call if m.get("role") == "tool"][0]
    assert "ERROR: Unknown tool" in tool_msg["content"]


def test_loop_limit_guard():
    # Always returns a tool call -> must terminate at the limit, not hang.
    looping = [
        LLMResponse(tool_calls=[ToolCall(id=f"t{i}", name="echo", args={})])
        for i in range(20)
    ]
    reg = ToolRegistry()
    reg.register("echo", "e", {"type": "object", "properties": {}}, lambda a: "ok")
    agent, db, events = _agent(looping, registry=reg)
    agent.tool_loop_limit = 3
    result = agent.process_turn("loop forever")
    assert result.content  # produced a fallback message
    assert result.tools_used.count("echo") == 3


def test_memory_tools_via_agent():
    reg = ToolRegistry()
    db = Database(":memory:")
    register_memory_tools(reg, db)
    responses = [
        LLMResponse(content="Saving.", tool_calls=[
            ToolCall(id="t1", name="remember_fact", args={"key": "editor", "value": "vim"})]),
        LLMResponse(content="Saved your editor as vim."),
    ]
    agent = Agent(ScriptedProvider(responses), reg, db, load_persona())
    agent.process_turn("remember my editor is vim")
    assert db.get_fact("editor") == "vim"


def test_facts_injected_into_system_prompt():
    db = Database(":memory:")
    db.save_fact("name", "Tricky")
    reg = ToolRegistry()
    agent = Agent(ScriptedProvider([LLMResponse(content="hi Tricky")]), reg, db, load_persona())
    agent.process_turn("who am i")
    system = agent.provider.seen_messages[0][0]
    assert system["role"] == "system"
    assert "Tricky" in system["content"]
    assert "USER_FACTS" in system["content"]
