"""Cross-document bleed fix (2026-05-29).

A document was loaded, asked about, then a *different* document was loaded —
but the chat model answered about the FIRST document because its Q&A still
lived in the recent-turn window. ``AssistantContext.prune_document_turns()``
removes prior document interactions (and the assistant reply that followed
each) when a new document is loaded, while preserving ordinary chat history.
"""
from __future__ import annotations

from core.assistant_context import AssistantContext


def _texts(ac):
    return [h["text"] for h in ac.history]


def test_prune_drops_prior_document_qa():
    ac = AssistantContext()
    ac.record_message("user", "[Load file: Advanced_System_Documents.md]")
    ac.record_message("assistant", "Loaded Advanced_System_Documents.md — 20 chunks.")
    ac.record_message("user", "[Re: Advanced_System_Documents.md] what did you understand?")
    ac.record_message("assistant", "It is about tenant_id, plan_type and quota_config.")

    ac.prune_document_turns()

    # Nothing about the old document survives to anchor the next answer.
    assert not any("Advanced_System_Documents" in t for t in _texts(ac))
    assert not any("tenant_id" in t for t in _texts(ac))
    assert list(ac.history) == []


def test_prune_preserves_ordinary_chat():
    ac = AssistantContext()
    ac.record_message("user", "what's the weather like")
    ac.record_message("assistant", "It's sunny.")
    ac.record_message("user", "[Re: PRD.md] summarize this")
    ac.record_message("assistant", "The PRD describes the product scope.")

    ac.prune_document_turns()

    texts = _texts(ac)
    assert "what's the weather like" in texts
    assert "It's sunny." in texts
    # The document interaction (and its reply) are gone.
    assert not any("PRD" in t for t in texts)
    assert not any("product scope" in t for t in texts)


def test_prune_keeps_assistant_reply_not_following_a_doc_turn():
    ac = AssistantContext()
    ac.record_message("user", "tell me a joke")
    ac.record_message("assistant", "Why did the chicken cross the road?")
    ac.prune_document_turns()
    assert _texts(ac) == ["tell me a joke", "Why did the chicken cross the road?"]
