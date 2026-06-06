"""P3.11 — Clarify primitive: ask the user a structured follow-up question.

Works the same way as core.approval: stores a pending clarification in
session state so the next user turn can be checked against it.

Typical flow:
    # Tool decides it needs more info:
    return clarify.ask(session_id, "Which subnet?", ["192.168.1.0/24", "10.0.0.0/8"], cs)

    # Next turn arrives; check before normal routing:
    q, chosen, valid = clarify.check_response(session_id, user_input, cs)
    if q is not None:
        # Was a pending clarification — handle chosen option (may be None if no match)
"""
from __future__ import annotations

from typing import Optional

_PENDING_KEY = "pending_clarification"


def ask(
    session_id: str,
    question: str,
    options: list[str],
    context_store,
    timeout_sec: float = 30.0,
) -> str:
    """Record a pending clarification and return the prompt to surface to the user.

    If options is non-empty, appends them to the question string so the user
    knows what answers are expected.
    """
    state = context_store.get_session_state(session_id) or {}
    state[_PENDING_KEY] = {
        "question": question,
        "options": options,
        "timeout_sec": timeout_sec,
    }
    context_store.save_session_state(session_id, state)
    if options:
        opts = ", ".join(f'"{o}"' for o in options)
        return f"{question} Options: {opts}"
    return question


def check_response(
    session_id: str,
    user_input: str,
    context_store,
) -> tuple[Optional[str], Optional[str], bool]:
    """Check if user_input answers a pending clarification.

    Returns:
        (question, chosen_option, is_valid)
        - question: the original question string, or None if no pending clarification
        - chosen_option: matched option (or raw input if options=[]), or None if no match
        - is_valid: True if the response resolved the clarification

    Always clears the pending state regardless of whether the input matched.
    """
    state = context_store.get_session_state(session_id) or {}
    pending = state.pop(_PENDING_KEY, None)
    if pending is None:
        return None, None, False
    context_store.save_session_state(session_id, state)

    question = pending["question"]
    options = pending.get("options", [])

    if not options:
        return question, user_input.strip(), True

    user_lower = user_input.strip().lower()
    for opt in options:
        if opt.lower() in user_lower or user_lower in opt.lower():
            return question, opt, True
    return question, None, False


def has_pending_clarification(session_id: str, context_store) -> bool:
    """Return True if a clarification is waiting for this session."""
    state = context_store.get_session_state(session_id) or {}
    return _PENDING_KEY in state
