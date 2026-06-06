"""Approval / confirmation primitive (P3.6).

request_approval() saves a pending confirmation in session state and
returns the prompt string. check_approval() reads the session state
to determine whether the user's input satisfies the required phrase.

Both functions are pure-logic: they manage session state only and never
call the LLM or render UI.

Usage pattern:
  1. On the triggering turn:
       msg = request_approval(session_id, "memory_wipe",
                              "Say 'yes, wipe everything' to confirm.",
                              "yes, wipe everything", context_store)
       return msg   # FRIDAY speaks this
  2. On the next turn (intercepted by _parse_pending_approval or similar):
       action_key, confirmed = check_approval(session_id, user_input, context_store)
       if action_key == "memory_wipe" and confirmed:
           ...execute...
"""
from __future__ import annotations

import re
from typing import Optional

_PENDING_KEY = "pending_approval"


def request_approval(
    session_id: str,
    action_key: str,
    prompt: str,
    confirm_phrase: str,
    context_store,
) -> str:
    """Persist the pending approval in session state and return the prompt."""
    try:
        state = context_store.get_session_state(session_id) or {}
        state[_PENDING_KEY] = {"action_key": action_key, "confirm_phrase": confirm_phrase}
        context_store.save_session_state(session_id, state)
    except Exception:
        pass
    return prompt


def check_approval(
    session_id: str,
    user_input: str,
    context_store,
) -> tuple[Optional[str], bool]:
    """Check user_input against the pending approval.

    Returns (action_key, confirmed): action_key is None if nothing was pending.
    Clears the pending state in either branch (approve or cancel).
    """
    try:
        state = context_store.get_session_state(session_id) or {}
    except Exception:
        return None, False
    pending = state.pop(_PENDING_KEY, None)
    if pending is None:
        return None, False
    try:
        context_store.save_session_state(session_id, state)
    except Exception:
        pass
    pattern = re.compile(re.escape(pending["confirm_phrase"]), re.IGNORECASE)
    return pending["action_key"], bool(pattern.search(user_input))


def has_pending_approval(session_id: str, context_store) -> bool:
    """Return True if any approval is awaiting confirmation."""
    try:
        state = context_store.get_session_state(session_id) or {}
        return _PENDING_KEY in state
    except Exception:
        return False
