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
    # The visible answer keeps the whole turn: the "On it." preamble that came with
    # the tool call (otherwise lost) plus the closing answer.
    assert result.content == "On it.\n\nDone — got hi."
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


def test_media_tool_output_surfaced_in_answer():
    """Diagrams/images a tool generates must appear in the visible answer even
    when the model doesn't re-paste the markdown (regression: learning chats
    showed only the closing line, no diagram)."""
    reg = ToolRegistry()
    md = "![Gear ratio](/api/media/diagrams/abc.png)\n\n*Gear ratio* · [⬇ Download](/api/media/diagrams/abc.png)"
    reg.register("render_diagram", "draw", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=md, data={"url": "/api/media/diagrams/abc.png", "kind": "diagram"}))
    responses = [
        LLMResponse(content="Here's how gears trade speed for force.",
                    tool_calls=[ToolCall(id="d1", name="render_diagram", args={})]),
        LLMResponse(content="What would you pick?"),
    ]
    agent, db, _ = _agent(responses, registry=reg)
    result = agent.process_turn("teach me")
    # explanation + the diagram markdown + closing line all present, in order
    assert "Here's how gears trade speed for force." in result.content
    assert "/api/media/diagrams/abc.png" in result.content
    assert result.content.strip().endswith("What would you pick?")
    # and it persisted (reload-safe)
    assert "/api/media/diagrams/abc.png" in db.recent_turns(result.session_id)[-1]["content"]


def test_stream_interleaves_media_and_mirrors_final_answer():
    """The live token stream must contain the SAME assembly as the final answer:
    preamble text, then generated media markdown in place, then the closing
    answer — so images render inline while streaming instead of popping in when
    the turn ends (and the turn_result replace causes no reflow)."""
    reg = ToolRegistry()
    media_md = "![Water cycle](/api/media/diagrams/x.png)\n\n*Water cycle* · [⬇ Download](/api/media/diagrams/x.png)"

    reg.register("draw", "draw a diagram", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=media_md, data={"url": "/api/media/diagrams/x.png"}))

    responses = [
        LLMResponse(content="Here's the picture:",
                    tool_calls=[ToolCall(id="t1", name="draw", args={})]),
        LLMResponse(content="And that's the cycle."),
    ]
    agent, db, _events = _agent(responses, registry=reg)
    chunks = []
    result = agent.process_turn("show me", on_token=chunks.append)

    streamed = "".join(chunks)
    expected = f"Here's the picture:\n\n{media_md}\n\nAnd that's the cycle."
    assert streamed == expected
    assert result.content == expected  # canonical answer == streamed answer


def test_stream_does_not_duplicate_repeated_media():
    """A tool returning the same media URL twice is shown once — in the stream
    AND in the final answer alike."""
    reg = ToolRegistry()
    media_md = "![d](/api/media/diagrams/same.png)"
    reg.register("draw", "draw", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=media_md, data={"url": "/api/media/diagrams/same.png"}))
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="draw", args={}),
                                ToolCall(id="t2", name="draw", args={})]),
        LLMResponse(content="Done."),
    ]
    agent, db, _events = _agent(responses, registry=reg)
    chunks = []
    result = agent.process_turn("draw twice", on_token=chunks.append)
    assert "".join(chunks).count("same.png") == 1
    assert result.content.count("same.png") == 1
