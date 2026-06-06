"""Reusable disambiguation / pick guard (Phase 3, checkpoint 4).

The sibling of :class:`core.workflows.confirmation.ConfirmationGuard`. Where the
confirmation guard asks "shall I go ahead?" before a *destructive* action, this
guard asks "which one did you mean?" when a capability resolves a request to
**more than one** candidate (several matching files, an ambiguous app name, a
choice of documents) and needs the user to pick before it can act.

Flow (handler-arming model, identical shape to the confirmation guard):

  1. A capability handler, at the moment it discovers it has >1 candidate,
     calls ``guard.arm(action=<capability to run once a pick is made>,
     arg_name=<arg that the picked value fills>, candidates=[...],
     base_args=<other args to carry through>)`` — UNLESS ``args["_picked"]`` is
     already set. ``arm`` stores the pending pick in session state and returns
     a numbered list prompt to speak.
  2. :class:`core.intent_recognizer.IntentRecognizer`'s ``_parse_pending_pick``
     interceptor sees the armed pick on the next turn and, when the utterance
     looks like a selection ("2", "the second one", a candidate's name), routes
     to ``pick_pending_candidate`` (a clear "cancel"/"never mind" →
     ``cancel_pending_pick``).
  3. ``pick_pending_candidate`` calls :meth:`pick`, which resolves the selection
     to one candidate, fills ``base_args[arg_name]`` with that candidate's value
     plus ``_picked=True``, and re-dispatches the stored ``action`` through the
     :class:`CapabilityExecutor` — so the chosen file is opened, the chosen app
     launched, the chosen document queried.

The guard is deliberately tiny and dependency-light: it talks to the
``context_store`` for session state and ``capability_executor`` for dispatch,
both resolved from the app lazily so partial test apps degrade gracefully (a
handler whose app has no guard simply acts on its first/own candidate).
"""
from __future__ import annotations

import re
from typing import Any

from core.logger import logger


# Session-state key holding the armed pick. Distinct from the confirmation
# guard's `pending_destructive_action` so the two never collide.
PENDING_KEY = "pending_pick"

# Word → ordinal index (0-based) for spoken selections.
_ORDINALS = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
    "sixth": 5, "seventh": 6, "eighth": 7, "ninth": 8, "tenth": 9,
    "1st": 0, "2nd": 1, "3rd": 2, "4th": 3, "5th": 4, "6th": 5,
    "7th": 6, "8th": 7, "9th": 8, "10th": 9,
}

# Cancel-shaped replies that abandon a pending pick.
CANCEL_RE = re.compile(
    r"\b(?:cancel|never\s*mind|nevermind|forget\s+it|none(?:\s+of\s+(?:them|those))?|"
    r"stop|nothing|no\s+thanks?)\b",
    re.IGNORECASE,
)


def parse_selection(text: str, labels: list[str]) -> int | None:
    """Resolve a selection utterance to a 0-based index into *labels*.

    Recognizes: a bare/embedded number ("2", "option 2", "number 3"), spoken
    and digit ordinals ("first", "the second one", "3rd"), "last", and a
    case-insensitive substring match against a candidate's label (≥3 chars, and
    only when it matches exactly one candidate). Returns ``None`` when nothing
    resolves — the caller then leaves the turn for normal routing.
    """
    n = len(labels)
    if n == 0:
        return None
    norm = (text or "").strip().lower().strip(" .!?")
    if not norm:
        return None

    # "last" / "the last one"
    if re.fullmatch(r"(?:the\s+)?last(?:\s+(?:one|option|item|result))?", norm):
        return n - 1

    # Numeric: "2", "option 2", "number 2", "#2", "the 2nd"
    num_match = re.search(r"(?:option|number|item|result|#)?\s*(\d{1,2})\b", norm)
    if num_match and re.fullmatch(
        r"(?:the\s+)?(?:option|number|item|result|#)?\s*\d{1,2}(?:\s*(?:one|option|item|result))?",
        norm,
    ):
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < n:
            return idx

    # Spoken / digit ordinals: "first", "the second one", "3rd"
    ord_match = re.fullmatch(
        r"(?:the\s+)?(\w+)(?:\s+(?:one|option|item|result))?", norm
    )
    if ord_match and ord_match.group(1) in _ORDINALS:
        idx = _ORDINALS[ord_match.group(1)]
        if 0 <= idx < n:
            return idx

    # Label substring — only if it uniquely identifies a candidate.
    if len(norm) >= 3:
        hits = [
            i for i, label in enumerate(labels)
            if norm in (label or "").lower()
        ]
        if len(hits) == 1:
            return hits[0]

    return None


def looks_like_selection(text: str, labels: list[str]) -> bool:
    """True when *text* is plausibly a pick (number/ordinal/known label)."""
    return parse_selection(text, labels) is not None


class DisambiguationGuard:
    """Two-step "which one did you mean?" guard shared by ambiguous capabilities."""

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------
    # Wiring helpers
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Config gate ``routing.disambiguate`` (default True)."""
        cfg = getattr(self.app, "config", None)
        if cfg is None or not hasattr(cfg, "get"):
            return True
        value = cfg.get("routing.disambiguate")
        return True if value is None else bool(value)

    def _store(self):
        return getattr(self.app, "context_store", None)

    def _session(self, session_id: str | None) -> str:
        return session_id or getattr(self.app, "session_id", "") or ""

    @staticmethod
    def _normalize(candidates: list) -> list[dict]:
        """Coerce candidates into ``[{"label", "value"}]``.

        Accepts a list of plain strings (label == value), ``(label, value)``
        pairs, or ``{"label", "value"}`` dicts.
        """
        out: list[dict] = []
        for c in candidates or []:
            if isinstance(c, dict):
                label = str(c.get("label", c.get("value", "")))
                value = c.get("value", label)
            elif isinstance(c, (tuple, list)) and len(c) == 2:
                label, value = str(c[0]), c[1]
            else:
                label = value = c if isinstance(c, str) else str(c)
            out.append({"label": label, "value": value})
        return out

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def render(candidates: list[dict], intro: str | None = None) -> str:
        intro = (intro or "Which one did you mean?").strip()
        lines = [intro]
        for i, c in enumerate(candidates, start=1):
            lines.append(f"{i}. {c['label']}")
        lines.append("Say a number (or its name), or 'cancel'.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def arm(
        self,
        *,
        action: str,
        arg_name: str,
        candidates: list,
        base_args: dict[str, Any] | None = None,
        intro: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Stash a pending pick and return the numbered prompt to ask."""
        norm = self._normalize(candidates)
        store = self._store()
        session_id = self._session(session_id)
        if store is not None and session_id:
            try:
                state = store.get_session_state(session_id) or {}
                state[PENDING_KEY] = {
                    "action": action,
                    "arg_name": arg_name,
                    "base_args": dict(base_args or {}),
                    "candidates": norm,
                    "intro": intro or "",
                }
                store.save_session_state(session_id, state)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("[pick] arm failed to persist: %s", exc)
        return self.render(norm, intro)

    def peek(self, session_id: str | None = None) -> dict | None:
        store = self._store()
        session_id = self._session(session_id)
        if store is None or not session_id:
            return None
        try:
            state = store.get_session_state(session_id) or {}
        except Exception:
            return None
        pending = state.get(PENDING_KEY)
        return dict(pending) if isinstance(pending, dict) else None

    def clear(self, session_id: str | None = None) -> dict | None:
        """Pop and return the armed pick (or None)."""
        store = self._store()
        session_id = self._session(session_id)
        if store is None or not session_id:
            return None
        try:
            state = store.get_session_state(session_id) or {}
        except Exception:
            return None
        pending = state.pop(PENDING_KEY, None)
        try:
            store.save_session_state(session_id, state)
        except Exception:  # pragma: no cover - defensive
            pass
        return dict(pending) if isinstance(pending, dict) else None

    def pick(self, raw_text: str = "", session_id: str | None = None) -> str:
        """Resolve the selection and re-dispatch the armed action.

        If the utterance doesn't resolve to a candidate, the list is re-asked
        (the pending pick is kept). On success the pending pick is cleared and
        the wrapped capability runs with the chosen value + ``_picked=True``.
        """
        pending = self.peek(session_id)
        if not pending:
            return "There's nothing waiting to be picked."
        candidates = pending.get("candidates") or []
        labels = [c.get("label", "") for c in candidates]
        idx = parse_selection(raw_text, labels)
        if idx is None:
            # Couldn't tell — keep the pick armed and re-ask.
            return self.render(candidates, pending.get("intro") or None)

        self.clear(session_id)
        chosen = candidates[idx]
        action = pending.get("action") or ""
        arg_name = pending.get("arg_name") or ""
        args = dict(pending.get("base_args") or {})
        if arg_name:
            args[arg_name] = chosen.get("value")
        args["_picked"] = True
        executor = getattr(self.app, "capability_executor", None)
        if executor is None or not action:
            return f"You picked {chosen.get('label')}, but I can't act on it right now."
        try:
            result = executor.execute(action, raw_text, args)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[pick] dispatch of %r failed: %s", action, exc)
            return "Something went wrong with that choice."
        output = getattr(result, "output", None)
        if output is None and not getattr(result, "ok", True):
            return getattr(result, "error", "") or "That didn't complete."
        return str(output if output is not None else result or "")

    def cancel(self, session_id: str | None = None) -> str:
        self.clear(session_id)
        return "Okay, never mind — I won't pick one."

    # ------------------------------------------------------------------
    # Handler convenience
    # ------------------------------------------------------------------

    def needs_disambiguation(self, args: dict | None, candidates: list) -> bool:
        """True when a handler should arm a pick rather than act.

        Keeps a handler's guard line a one-liner::

            if guard and guard.needs_disambiguation(args, cands):
                return guard.arm(action="open_file", arg_name="filename",
                                 candidates=cands, intro="Which file?")
        """
        if not self.enabled:
            return False
        if (args or {}).get("_picked"):
            return False
        return len(candidates or []) > 1
