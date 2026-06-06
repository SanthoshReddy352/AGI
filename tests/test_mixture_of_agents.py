"""P3.13 — Mixture of Agents (MoA)."""
import threading
import pytest
from unittest.mock import MagicMock, patch

from core.mixture_of_agents import MixtureOfAgents, make_moa, _call_llm


def _fake_llm(text_response="mock answer"):
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": text_response}}]
    }
    return llm


def _make_router(chat_llm=None, tool_llm=None):
    router = MagicMock()
    router.get_llm.return_value = chat_llm
    router.get_tool_llm.return_value = tool_llm
    # Provide a simple non-blocking lock
    router.chat_inference_lock = threading.Lock()
    model_mgr = MagicMock()
    model_mgr.inference_lock.return_value = threading.Lock()
    router.model_manager = model_mgr
    return router


def test_no_llm_returns_unavailable_message():
    router = _make_router(chat_llm=None, tool_llm=None)
    moa = MixtureOfAgents(router)
    result = moa.run("test query")
    assert "available" in result.lower() or "model" in result.lower()


def test_single_model_fallback_when_tool_llm_none():
    llm = _fake_llm("single answer")
    router = _make_router(chat_llm=llm, tool_llm=None)
    moa = MixtureOfAgents(router)
    result = moa.run("question?")
    assert result == "single answer"


def test_single_model_fallback_when_same_object():
    llm = _fake_llm("same model answer")
    router = _make_router(chat_llm=llm, tool_llm=llm)
    moa = MixtureOfAgents(router)
    # same object — should use two-temperature path
    result = moa.run("question?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_two_model_parallel_pass():
    chat = _fake_llm("chat answer")
    tool = _fake_llm("tool answer")
    router = _make_router(chat_llm=chat, tool_llm=tool)
    moa = MixtureOfAgents(router)
    result = moa.run("hard question")
    # synthesis runs; result should be non-empty
    assert isinstance(result, str)
    assert len(result) > 0


def test_identical_answers_skip_synthesis():
    chat = _fake_llm("same answer")
    tool = _fake_llm("same answer")
    router = _make_router(chat_llm=chat, tool_llm=tool)
    moa = MixtureOfAgents(router)
    result = moa.run("q")
    assert result == "same answer"
    # synthesis LLM should not be called — chat.create_chat_completion called <= 2 times
    assert chat.create_chat_completion.call_count <= 2


def test_make_moa_factory():
    router = _make_router(chat_llm=_fake_llm())
    moa = make_moa(router)
    assert isinstance(moa, MixtureOfAgents)


def test_run_with_custom_messages():
    llm = _fake_llm("custom")
    router = _make_router(chat_llm=llm, tool_llm=None)
    moa = MixtureOfAgents(router)
    msgs = [{"role": "user", "content": "custom input"}]
    result = moa.run("q", messages=msgs)
    assert isinstance(result, str)


def test_call_llm_on_exception_returns_empty():
    bad_llm = MagicMock()
    bad_llm.create_chat_completion.side_effect = RuntimeError("crash")
    result = _call_llm(bad_llm, [{"role": "user", "content": "q"}], 128, 0.7)
    assert result == ""


def test_both_models_empty_returns_fallback_message():
    chat = MagicMock()
    chat.create_chat_completion.side_effect = RuntimeError("fail")
    tool = MagicMock()
    tool.create_chat_completion.side_effect = RuntimeError("fail")
    router = _make_router(chat_llm=chat, tool_llm=tool)
    moa = MixtureOfAgents(router)
    result = moa.run("q")
    assert "couldn't" in result.lower() or "response" in result.lower()
