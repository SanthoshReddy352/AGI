"""Track 1.4 — ContextResolver keystone (minimum-viable, phased rollout).

Sits between intent classification + plan construction and tool dispatch.
Reads the per-turn context (working artifact, references, recent turns)
and either:

  * Rewrites the planned action when a pronoun-bearing utterance was
    classified as chat but actually refers to an artifact in scope
    ("what's in it?" after `read my.txt` → `read_file(filename="my.txt")`).
  * Returns a no-op when the plan already has fully-resolved slots.

Initial scope is intentionally narrow: only the chat→file rescue path,
which addresses the persistent UX bug where artifact pronouns in
short questions fell through to llm_chat and the model hallucinated.
Future PRs migrate the scattered per-handler resolution (in
`intent_recognizer._resolve_references`, `file_workspace`'s
pending-file-request handling, `_extract_manage_content`, etc.) into
this single contract. The Direction calls this layer "the keystone";
landing it small but functional gives every later migration a place
to slot into.

Naming: the resolver does NOT replace the planner. It just edits the
plan's destination AFTER the planner has run, when the original plan
clearly missed a contextual signal the resolver can see.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.capability_broker import ToolPlan, ToolStep


# Patterns that signal the user is asking about an artifact in scope.
# Kept narrow to avoid false-positive rewrites of legitimate chat turns:
# the verb AND the pronoun must both appear, and the verb must be one
# that obviously wants to read a file.
_READ_VERB_RE = re.compile(
    r"\b(?:read|show|preview|open|display|"
    r"what(?:'s|s|\s+is)\s+(?:in|inside)|"
    r"contents?\s+of)\b",
    re.IGNORECASE,
)
_ARTIFACT_PRONOUN_RE = re.compile(
    r"\b(?:it|that|this|the\s+file|same\s+file)\b",
    re.IGNORECASE,
)

# Ordinal pattern covering both word ("first"/"second"/…/"tenth"/"last") and
# digit ("1st"/"2nd"/"3rd"/"[4-9]th"/"10th") forms. Optional leading "the"
# and optional trailing "one"/"item"/"option"/"file"/"result". The capture
# group is always the bare ordinal token, normalized below to a word-form
# key the reference registry stores under.
_ORDINAL_RE = re.compile(
    r"\b(?:the\s+)?"
    r"(1st|2nd|3rd|[4-9]th|10th"
    r"|first|second|third|fourth|fifth"
    r"|sixth|seventh|eighth|ninth|tenth|last)"
    r"(?:\s+(?:one|item|option|file|result))?\b",
    re.IGNORECASE,
)

_ORDINAL_DIGIT_TO_WORD = {
    "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth",
    "5th": "fifth", "6th": "sixth", "7th": "seventh", "8th": "eighth",
    "9th": "ninth", "10th": "tenth",
}


@dataclass
class ResolverDecision:
    """What the resolver decided to do with the plan."""

    rewrite: ToolPlan | None = None  # if set, replace the original plan
    reason: str = ""                  # short log line

    @property
    def applied(self) -> bool:
        return self.rewrite is not None


class ContextResolver:
    """Per-turn pronoun + slot resolver. Owns a single `try_rescue` entry
    point so the turn orchestrator stays trivially callable from tests."""

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    def try_rescue(self, text: str, plan: ToolPlan | None, session_id: str) -> ResolverDecision:
        """Inspect the planned action; if it's a chat fallback for a
        pronoun-bearing read request, rewrite it as a file action against
        the current working artifact.

        Returns an empty decision (resolver.applied is False) for any
        plan that doesn't match the rescue pattern. Callers should treat
        an empty decision as "use the original plan."
        """
        if plan is None:
            return ResolverDecision()
        mode = (getattr(plan, "mode", "") or "").lower()
        # Only intervene when the planner decided this was conversational
        # text OR fell back to a generic clarify. Tool / planner / workflow
        # / refuse modes already have explicit handling and must not be
        # overridden. `clarify` is included because the broker's fallback
        # "I need a bit more detail" is exactly the case the resolver
        # exists to repair when an artifact is in scope.
        if mode not in {"chat", "clarify", ""}:
            return ResolverDecision()
        # A clarify plan that proposes online consent (`requires_confirmation`)
        # is a deliberate yes/no prompt — leave it alone.
        if mode == "clarify" and getattr(plan, "requires_confirmation", False):
            return ResolverDecision()
        cleaned = (text or "").strip()
        if not cleaned:
            return ResolverDecision()

        # Paths 1 + 2 require a read-verb AND a registered `read_file`
        # capability since they always rewrite to `read_file`. Path 3
        # (pending-candidate rescue) has its own preconditions because
        # selection replies like "the pdf one" lack a verb.
        has_read_verb = bool(_READ_VERB_RE.search(cleaned))
        can_read_file = self._read_file_capability_available()

        # Path 1 — pronoun rescue against the working artifact.
        if has_read_verb and can_read_file and _ARTIFACT_PRONOUN_RE.search(cleaned):
            target_path = self._artifact_source_path(session_id)
            if target_path:
                return self._build_decision(
                    plan, cleaned, "read_file", {"filename": target_path},
                    reason=f"chat→read_file rescue via artifact {target_path}",
                )

        # Path 2 — ordinal rescue against the reference registry.
        if has_read_verb and can_read_file:
            ordinal_target = self._ordinal_target(cleaned, session_id)
            if ordinal_target:
                return self._build_decision(
                    plan, cleaned, "read_file", {"filename": ordinal_target},
                    reason=f"chat→read_file rescue via ordinal {ordinal_target}",
                )

        # Path 3 — pending-file-candidate rescue. When an earlier turn left
        # a pending_file_request (`Tell me the number, exact filename, or
        # extension to choose one.`) and the user's reply matches a
        # selection shape that `_parse_pending_selection` didn't catch
        # (extension-only without "one", partial name, etc.), route to
        # `select_file_candidate` here as a defensive backup. No verb
        # required — selection replies are typically nouns.
        pending_rescue = self._pending_selection_rescue(cleaned, plan)
        if pending_rescue is not None:
            return pending_rescue

        return ResolverDecision()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_decision(
        self,
        plan: ToolPlan,
        text: str,
        capability_name: str,
        args: dict,
        *,
        reason: str,
        side_effect_level: str = "read",
        connectivity: str = "local",
    ) -> ResolverDecision:
        rewrite = ToolPlan(
            turn_id=getattr(plan, "turn_id", ""),
            mode="tool",
            steps=[
                ToolStep(
                    capability_name=capability_name,
                    args=dict(args),
                    raw_text=text,
                    side_effect_level=side_effect_level,
                    connectivity=connectivity,
                )
            ],
            final_style=getattr(plan, "final_style", ""),
        )
        return ResolverDecision(rewrite=rewrite, reason=reason)

    def _pending_selection_rescue(self, text: str, plan: ToolPlan) -> ResolverDecision | None:
        """Defensive backup for `_parse_pending_selection` misses. Fires
        only when an active `pending_file_request` is set on the app's
        dialog_state AND `choose_candidate_from_text` would resolve the
        utterance to one of the candidates. Returns None on no-match so
        the resolver falls through to its no-op decision.
        """
        dialog_state = getattr(self.app, "dialog_state", None)
        pending = getattr(dialog_state, "pending_file_request", None) if dialog_state else None
        candidates = getattr(pending, "candidates", None) if pending else None
        if not candidates:
            return None
        if not self._select_file_candidate_available():
            return None
        try:
            from modules.system_control.file_search import (  # noqa: PLC0415
                choose_candidate_from_text,
            )
        except Exception:
            return None
        try:
            chosen, _err = choose_candidate_from_text(text, candidates)
        except Exception:
            return None
        if not chosen:
            return None
        return self._build_decision(
            plan, text, "select_file_candidate", {},
            reason=f"chat→select_file_candidate rescue via pending list ({chosen})",
        )

    def _select_file_candidate_available(self) -> bool:
        registry = getattr(self.app, "capability_registry", None)
        if registry is not None and hasattr(registry, "has_capability"):
            try:
                if registry.has_capability("select_file_candidate"):
                    return True
            except Exception:
                pass
        router = getattr(self.app, "router", None)
        if router is not None:
            tools = getattr(router, "_tools_by_name", {}) or {}
            return "select_file_candidate" in tools
        return False

    def _ordinal_target(self, text: str, session_id: str) -> str:
        """Return the registered reference for the first ordinal in `text`,
        or "" when no match / no registry entry."""
        if not session_id:
            return ""
        match = _ORDINAL_RE.search(text)
        if match is None:
            return ""
        ordinal = match.group(1).lower()
        ordinal_word = _ORDINAL_DIGIT_TO_WORD.get(ordinal, ordinal)
        store = getattr(self.app, "context_store", None)
        if store is None:
            return ""
        try:
            value = store.get_reference(session_id, ordinal_word)
        except Exception:
            return ""
        return (value or "").strip()

    def _artifact_source_path(self, session_id: str) -> str:
        store = getattr(self.app, "context_store", None)
        if store is None or not session_id:
            return ""
        try:
            artifact = store.get_artifact(session_id)
        except Exception:
            return ""
        if artifact is None:
            return ""
        return getattr(artifact, "source_path", "") or ""

    def _read_file_capability_available(self) -> bool:
        registry = getattr(self.app, "capability_registry", None)
        if registry is not None and hasattr(registry, "has_capability"):
            try:
                if registry.has_capability("read_file"):
                    return True
            except Exception:
                pass
        # Fallback for test apps that wire only `app.router`.
        router = getattr(self.app, "router", None)
        if router is not None:
            tools = getattr(router, "_tools_by_name", {}) or {}
            return "read_file" in tools
        return False
