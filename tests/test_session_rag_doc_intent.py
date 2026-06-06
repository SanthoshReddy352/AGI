"""IntentRecognizer routing for questions about a loaded session document.

Pins the 2026-05-29 bug: a PDF was loaded into the session RAG, but
"[Re: Resume.pdf] What is there in the document?" routed to `read_file`
("Which file would you like me to read?") because (a) the phrasing matches
_KNOWLEDGE_Q_RE so plan() bailed to [] before any doc-aware parser ran, and
(b) nothing routed SessionRAG docs anywhere. The fix routes such questions to
`llm_chat` (chat injects the excerpts) when a session document is active.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


ALL_TOOLS = ["llm_chat", "read_file", "open_file", "query_document",
             "get_time", "launch_app", "summarize_file"]


class _FakeRag:
    def __init__(self, active):
        self.is_active = active


def _make_recognizer(doc_active, tools=None):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in (tools if tools is not None else ALL_TOOLS)}
    router.context_store = None
    router.session_id = "s1"
    ac = MagicMock()
    ac.session_rag = _FakeRag(doc_active)
    router.assistant_context = ac
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    ds.pending_goal_selection = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase", [
    "[Re: Resume.pdf] What is there in the document ?",
    "what is there in the document",
    "what does it say",
    "summarize this",
    "what's in the file",
    "tell me about it",
    "explain this",
    "what does the pdf contain",
])
def test_doc_question_routes_to_chat_when_doc_active(phrase):
    ir = _make_recognizer(doc_active=True)
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase!r}"
    assert result[0]["tool"] == "llm_chat", f"{phrase!r} → {result[0]['tool']}"


def test_re_prefix_is_stripped_from_query():
    ir = _make_recognizer(doc_active=True)
    result = ir.plan("[Re: Resume.pdf] What is there in the document ?")
    assert result[0]["tool"] == "llm_chat"
    assert "[Re:" not in result[0]["args"]["query"]
    assert "what is there in the document" in result[0]["args"]["query"].lower()


@pytest.mark.parametrize("phrase,expected", [
    ("what time is it", "get_time"),
    ("open calculator", "launch_app"),
])
def test_non_doc_questions_not_poached_even_with_doc_active(phrase, expected):
    ir = _make_recognizer(doc_active=True)
    result = ir.plan(phrase)
    assert result and result[0]["tool"] == expected


def test_doc_question_falls_through_when_no_doc_loaded():
    # Without an active session document, "what is there in the document?" must
    # NOT be force-routed to chat — it stays a knowledge-question bail ([]),
    # letting the normal routing pipeline handle it.
    ir = _make_recognizer(doc_active=False)
    result = ir.plan("what is there in the document")
    assert not result or result[0]["tool"] != "llm_chat"


def test_no_chat_capability_means_no_doc_route():
    ir = _make_recognizer(doc_active=True, tools=["read_file", "open_file"])
    result = ir.plan("what is there in the document")
    assert not result or result[0]["tool"] != "llm_chat"
