"""P3.4 — ContextCompressor tests."""
import pytest
from unittest.mock import MagicMock
from core.context_compressor import ContextCompressor, make_compressor, _messages_tokens


def _msg(role, content):
    return {"role": role, "content": content}


def _short():
    return [_msg("system", "sys"), _msg("user", "hi"), _msg("assistant", "hello")]


def test_within_budget_returns_unchanged():
    msgs = _short()
    c = ContextCompressor(max_tokens=4096)
    result = c.compress(msgs)
    assert result == msgs


def test_empty_returns_empty():
    c = ContextCompressor(max_tokens=512)
    assert c.compress([]) == []


def test_system_message_preserved():
    system = _msg("system", "You are a helpful assistant.")
    turns = [_msg("user", "x" * 1000), _msg("assistant", "y" * 1000)] * 10
    c = ContextCompressor(max_tokens=128)
    result = c.compress([system] + turns)
    assert any(m["role"] == "system" for m in result)
    assert result[0]["content"] == system["content"]


def test_oldest_turns_dropped_first():
    system = _msg("system", "sys")
    old = _msg("user", "old message " * 50)
    recent = _msg("user", "recent message")
    c = ContextCompressor(max_tokens=64)
    result = c.compress([system, old, recent])
    texts = [m["content"] for m in result]
    assert any("recent" in t for t in texts)


def test_result_fits_within_budget():
    msgs = [_msg("user", "word " * 200)] * 10
    c = ContextCompressor(max_tokens=128)
    result = c.compress(msgs)
    assert _messages_tokens(result) <= 128


def test_llm_summary_injected_when_turns_dropped(tmp_path):
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "Earlier we discussed A and B."}}]
    }
    system = _msg("system", "sys")
    old = _msg("user", "looong old turn " * 100)
    recent = _msg("user", "current question")
    c = ContextCompressor(max_tokens=64, llm=mock_llm)
    result = c.compress([system, old, recent])
    contents = " ".join(m.get("content", "") for m in result)
    assert "summary" in contents.lower() or "earlier" in contents.lower() or "discussed" in contents.lower()


def test_llm_failure_does_not_raise():
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.side_effect = RuntimeError("boom")
    msgs = [_msg("system", "s")] + [_msg("user", "x" * 300)] * 5
    c = ContextCompressor(max_tokens=64, llm=mock_llm)
    result = c.compress(msgs)
    assert isinstance(result, list)


def test_no_llm_still_trims():
    msgs = [_msg("system", "s")] + [_msg("user", "x" * 300)] * 5
    c = ContextCompressor(max_tokens=64)
    result = c.compress(msgs)
    assert _messages_tokens(result) <= 64 + 20  # small slack for system


def test_make_compressor_factory():
    c = make_compressor(max_tokens=1024)
    assert isinstance(c, ContextCompressor)
    assert c._max_tokens == 1024


def test_multiple_system_messages_all_preserved():
    msgs = [
        _msg("system", "base persona"),
        _msg("system", "extra rule"),
        _msg("user", "x" * 400),
    ]
    c = ContextCompressor(max_tokens=48)
    result = c.compress(msgs)
    sys_msgs = [m for m in result if m["role"] == "system"]
    assert len(sys_msgs) == 2


def test_synthetic_60_turn_transcript_stays_under_8k_tokens():
    """Plan P3.4 verify clause: 60-turn synthetic transcript stays under 8K tokens."""
    msgs = [_msg("system", "You are FRIDAY.")]
    for i in range(30):
        msgs.append(_msg("user", f"turn {i}: tell me about subject {i} in detail. " * 20))
        msgs.append(_msg("assistant", f"response {i}: subject {i} is interesting because… " * 20))
    c = ContextCompressor(max_tokens=8000)
    result = c.compress(msgs)
    assert _messages_tokens(result) <= 8000


def test_compressor_wired_into_assistant_context():
    from core.assistant_context import AssistantContext
    ctx = AssistantContext()
    assert ctx.context_compressor is None
    # 2026-05-23: the persona system prompt grew slightly to add the
    # "never speak as the user" + "never claim a tool you don't have"
    # guards. With 256 tokens the compressor was dropping the user turn
    # to fit the system message; bump to 2048 since this test is about
    # wiring, not the squeeze budget.
    c = make_compressor(max_tokens=2048)
    ctx.context_compressor = c
    msgs = ctx.build_chat_messages("hello")
    # Should still build messages without error; compressor is pass-through here.
    assert any(m["role"] == "user" for m in msgs)
