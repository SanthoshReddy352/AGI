"""Reusable confirm-before-destructive-action guard (Phase 3).

Generalizes the proven two-step memory-wipe pattern
(:mod:`modules.memory_manager.plugin`) into one shared mechanism so any
destructive capability gets a confirmation turn without re-implementing its
own pending-state machine.

Flow (handler-arming model):

  1. A destructive handler, at the moment it knows *exactly* what it would
     do, calls ``guard.arm(action=<own capability name>, args=<resolved
     args>, preview=<human description>)`` — UNLESS ``args["_confirmed"]`` is
     already set. ``arm`` stores the pending action in session state and
     returns the prompt to speak.
  2. The :class:`core.intent_recognizer.IntentRecognizer`'s
     ``_parse_pending_destructive`` interceptor sees the armed action on the
     next turn and routes an affirmation to ``confirm_pending_action``
     (anything else → ``cancel_pending_action``).
  3. ``confirm_pending_action`` calls :meth:`confirm`, which re-dispatches the
     stored capability through the :class:`CapabilityExecutor` with
     ``_confirmed=True`` — so the SAME handler runs its real side effect.

Because arming happens only once the handler has resolved its target (e.g.
*which* goal, *which* calendar event), the preview is always specific and
the guard composes cleanly with any prior disambiguation step.

The guard is deliberately tiny and dependency-light: it talks to the
``context_store`` for session state and the ``capability_executor`` for
dispatch, both resolved from the app lazily so partial test apps degrade
gracefully (a handler whose app has no guard simply runs unguarded).
"""
from __future__ import annotations

from typing import Any

from core.logger import logger


# Session-state key holding the armed action. Distinct from the
# memory-wipe flow's `pending_memory_wipe` so the two never collide.
PENDING_KEY = "pending_destructive_action"


class ConfirmationGuard:
    """Two-step confirm-before-act guard shared by destructive capabilities."""

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------
    # Wiring helpers
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Config gate ``routing.confirm_destructive`` (default True).

        Lets a power user opt out of the extra confirmation turn entirely
        without code changes; defaults to safe-by-default.
        """
        cfg = getattr(self.app, "config", None)
        if cfg is None or not hasattr(cfg, "get"):
            return True
        value = cfg.get("routing.confirm_destructive")
        return True if value is None else bool(value)

    def _store(self):
        return getattr(self.app, "context_store", None)

    def _session(self, session_id: str | None) -> str:
        return session_id or getattr(self.app, "session_id", "") or ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def arm(
        self,
        *,
        action: str,
        args: dict[str, Any] | None = None,
        preview: str,
        session_id: str | None = None,
    ) -> str:
        """Stash a pending destructive *action* and return the prompt to ask.

        ``preview`` is a specific human description of what will happen
        ("I'll delete the goal 'Run a 5k'"). Returns a confirmation prompt;
        the caller returns this string to the user verbatim.
        """
        store = self._store()
        session_id = self._session(session_id)
        if store is not None and session_id:
            try:
                state = store.get_session_state(session_id) or {}
                state[PENDING_KEY] = {
                    "action": action,
                    "args": dict(args or {}),
                    "preview": preview,
                }
                store.save_session_state(session_id, state)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("[confirm] arm failed to persist: %s", exc)
        return self.prompt_for(preview)

    @staticmethod
    def prompt_for(preview: str) -> str:
        preview = (preview or "").strip()
        lead = f"{preview} " if preview else ""
        return f"{lead}Shall I go ahead? Say yes to confirm, or anything else to cancel."

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
        """Pop and return the armed action (or None)."""
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

    def confirm(self, raw_text: str = "", session_id: str | None = None) -> str:
        """Execute the armed action by re-dispatching it with ``_confirmed=True``.

        Returns the wrapped capability's user-facing output, or a graceful
        message when nothing was armed / dispatch is unavailable.
        """
        pending = self.clear(session_id)
        if not pending:
            return "There's nothing waiting for confirmation."
        action = pending.get("action") or ""
        args = dict(pending.get("args") or {})
        args["_confirmed"] = True
        executor = getattr(self.app, "capability_executor", None)
        if executor is None or not action:
            return "I can't complete that right now."
        try:
            result = executor.execute(action, raw_text, args)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[confirm] dispatch of %r failed: %s", action, exc)
            return "Something went wrong completing that."
        output = getattr(result, "output", None)
        if output is None and not getattr(result, "ok", True):
            return getattr(result, "error", "") or "That didn't complete."
        return str(output or "")

    def cancel(self, session_id: str | None = None) -> str:
        self.clear(session_id)
        return "Okay, cancelled — I won't do that."

    # ------------------------------------------------------------------
    # Handler convenience
    # ------------------------------------------------------------------

    def needs_confirmation(self, args: dict | None) -> bool:
        """True when a handler should arm rather than act.

        Centralizes the ``enabled`` + ``_confirmed`` check so a destructive
        handler's guard line stays a one-liner:

            if guard and guard.needs_confirmation(args):
                return guard.arm(action="lock_screen", preview="I'll lock the screen.")
        """
        if not self.enabled:
            return False
        return not bool((args or {}).get("_confirmed"))
