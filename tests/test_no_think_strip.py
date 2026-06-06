"""P0.2 — /no_think and /think artifacts are stripped from model output."""
import pytest
from core.model_output import strip_model_artifacts


@pytest.mark.parametrize("raw, expected", [
    # Original line-anchored cases (must still work)
    ("/no_think", ""),
    ("/think", ""),
    # Inline / embedded cases (the regression that was failing)
    ("Sure! /no_think Here you go.", "Sure! Here you go."),
    ("Oh, you're asking me to do a '/no_think' scan?", "Oh, you're asking me to do a '' scan?"),
    ("Let me /think about this carefully.", "Let me about this carefully."),
    # Mixed with think blocks
    ("<think>internal thoughts</think>Result: /no_think done", "Result: done"),
    # No false positives
    ("I think this is right.", "I think this is right."),
    ("Re-think the approach.", "Re-think the approach."),
])
def test_strip_model_artifacts(raw, expected):
    assert strip_model_artifacts(raw) == expected


# ----------------------------------------------------------------------
# P0.2 final piece — read-side strip in build_chat_messages.
# Persisted /no_think tokens from older builds must not leak back into
# the LLM context when history is replayed.
# ----------------------------------------------------------------------

def test_build_chat_messages_strips_no_think_from_history():
    from core.assistant_context import AssistantContext
    ctx = AssistantContext()
    ctx.record_message("user", "tell me about cars /no_think")
    ctx.record_message("assistant", "Cars are fast.")
    msgs = ctx.build_chat_messages("and trucks?")
    history_blob = " ".join(m["content"] for m in msgs if m["role"] != "system")
    assert "/no_think" not in history_blob
    assert "/think" not in history_blob


def test_build_chat_messages_keeps_normal_words():
    from core.assistant_context import AssistantContext
    ctx = AssistantContext()
    ctx.record_message("user", "I think this is right.")
    ctx.record_message("assistant", "Agreed.")
    msgs = ctx.build_chat_messages("ok")
    blob = " ".join(m["content"] for m in msgs if m["role"] != "system")
    assert "I think this is right" in blob  # bare "think" must survive
