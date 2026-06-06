"""P1.2 — file workflow LLM content generation."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from modules.system_control.file_workflow_helpers import _llm_generate_about


def _app_with_llm(response: str):
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": response}}]
    }
    router = SimpleNamespace(get_llm=lambda: llm)
    return SimpleNamespace(router=router), llm


def _app_without_llm():
    router = SimpleNamespace(get_llm=lambda: None)
    return SimpleNamespace(router=router)


def test_generates_body_for_text_extension():
    app, llm = _app_with_llm("A short note about kids' favourite activities.")
    body = _llm_generate_about(app, "activities that kids love", "kids.txt")
    assert "favourite" in body or "activities" in body
    assert llm.create_chat_completion.called


def test_generation_picks_up_extension_in_prompt():
    app, llm = _app_with_llm("body text")
    _llm_generate_about(app, "Python tips", "notes.md")
    sent = llm.create_chat_completion.call_args.kwargs["messages"][-1]["content"]
    assert "md" in sent.lower()
    assert "Python tips" in sent


def test_generation_handles_no_extension():
    app, llm = _app_with_llm("plain body")
    body = _llm_generate_about(app, "topic", "noext")
    assert body == "plain body"
    sent = llm.create_chat_completion.call_args.kwargs["messages"][-1]["content"]
    assert "text document" in sent


def test_returns_empty_when_no_llm():
    app = _app_without_llm()
    assert _llm_generate_about(app, "anything", "x.txt") == ""


def test_llm_exception_returns_empty():
    app, llm = _app_with_llm("ignored")
    llm.create_chat_completion.side_effect = RuntimeError("boom")
    assert _llm_generate_about(app, "topic", "x.txt") == ""


def test_strips_whitespace():
    app, llm = _app_with_llm("   padded body   \n")
    assert _llm_generate_about(app, "t", "x.txt") == "padded body"


def test_non_dict_llm_response_returns_empty():
    app, llm = _app_with_llm("ignored")
    llm.create_chat_completion.return_value = None
    assert _llm_generate_about(app, "t", "x.txt") == ""
