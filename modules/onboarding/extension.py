"""First-run user-profile onboarding.

Owns the user-profile capability surface:

  * ``update_user_profile`` — set a single field after onboarding
    (e.g. user later says "call me Cody").
  * ``extract_user_name_or_skip`` — extract a name from "My name is X" /
    "Call me X" / bare-token replies. Returns "" for skip tokens.
  * ``extract_answer_or_skip`` — returns the raw user text, or "" if the
    user said "skip" / "no" / "later". Used by every onboarding question
    after the name.
  * ``complete_onboarding`` — final step of the onboarding workflow:
    writes all five fields to the user_profile namespace, sets the
    onboarding-completed system flag, returns the personalized greeting.

Track 5.2b retired the standalone ``OnboardingWorkflow`` Python class in
favor of the ``user_onboarding`` YAML template; the slot-fill loop is
now driven by the Track 5.2a multi-turn primitive in
``WorkflowTemplateCompiler``. Profile facts are stored in
``ContextStore.facts`` under ``namespace="user_profile"``.
"""
from __future__ import annotations

import re

from core.extensions.protocol import Extension, ExtensionContext
from core.logger import logger


PROFILE_NAMESPACE = "user_profile"
PROFILE_FIELDS = ("name", "role", "location", "preferences", "comm_style")

# Skip-token vocabulary. Matches the Track 5.2a-pre Python workflow's
# `_SKIP_TOKENS` set so the YAML conversion preserves the exact same
# "I'd rather not say" behavior the old workflow had.
_SKIP_TOKENS = frozenset({
    "skip", "later", "no", "nope", "pass", "dunno", "i dunno",
    "i don't know", "idk", "none", "no thanks", "next",
})


def _is_skip(text: str) -> bool:
    normalized = re.sub(r"[^\w\s']", "", (text or "").strip().lower())
    if not normalized:
        return True
    return normalized in _SKIP_TOKENS


def _extract_name(text: str) -> str:
    """Best-effort extract a name from a freeform answer.

    Handles 'My name is X', 'I'm X', 'Call me X', 'X' (bare). Falls back
    to the trimmed input. We don't try to be clever — the user can
    correct via ``update_user_profile`` if needed.
    """
    if not text:
        return ""
    stripped = text.strip().rstrip(".!?")
    m = re.search(
        r"^(?:my name is|i am|i'm|call me|it's|name's|the name's)\s+([A-Za-z][\w\s'\-]*)$",
        stripped,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    if len(stripped.split()) <= 4:
        return stripped
    for word in stripped.split():
        cleaned = word.strip(",.!?'\"")
        if cleaned and cleaned[0].isalpha():
            return cleaned
    return stripped


def read_profile(context_store) -> dict:
    """Return the stored profile as a `{field: value}` dict.

    Missing fields are omitted from the dict so callers can use truthiness
    checks (`if profile.get("name")`). Returns an empty dict on any error.
    """
    if context_store is None:
        return {}
    try:
        rows = context_store.get_facts_by_namespace(PROFILE_NAMESPACE)
    except Exception as exc:
        logger.debug("[onboarding] read_profile failed: %s", exc)
        return {}
    profile = {}
    for row in rows or []:
        key = (row.get("key") or "").strip()
        value = (row.get("value") or "").strip()
        if key and value:
            profile[key] = value
    return profile


def write_profile_field(context_store, field: str, value: str) -> None:
    """Persist a single field. Empty values are stored as empty strings so
    `read_profile` can distinguish "asked and skipped" from "never asked"."""
    if context_store is None or field not in PROFILE_FIELDS:
        return
    try:
        context_store.store_fact(field, value or "", namespace=PROFILE_NAMESPACE)
    except Exception as exc:
        logger.warning("[onboarding] write_profile_field(%s) failed: %s", field, exc)


def mark_completed(context_store) -> None:
    """Set the system-namespace flag that suppresses re-prompting."""
    if context_store is None:
        return
    try:
        context_store.store_fact("onboarding_completed", "true", namespace="system")
    except Exception as exc:
        logger.warning("[onboarding] mark_completed failed: %s", exc)


def is_completed(context_store) -> bool:
    if context_store is None:
        return False
    try:
        facts = {f["key"]: f["value"]
                 for f in context_store.get_facts_by_namespace("system")}
    except Exception:
        return False
    return facts.get("onboarding_completed", "") == "true"


class OnboardingExtension(Extension):
    name = "Onboarding"

    def load(self, ctx: ExtensionContext) -> None:
        self.ctx = ctx
        ctx.register_capability(
            spec={
                "name": "update_user_profile",
                "description": (
                    "Update what FRIDAY remembers about the user. Use when the "
                    "user says things like 'call me X', 'my name is X', "
                    "'I'm a Y', 'I live in Z', 'remember I prefer concise answers'. "
                    "Field must be one of: name, role, location, preferences, comm_style."
                ),
                "parameters": {
                    "field": "string - one of: name, role, location, preferences, comm_style",
                    "value": "string - the new value",
                },
                "aliases": [
                    "call me",
                    "my name is",
                    "remember my name",
                    "i live in",
                    "i'm based in",
                    "remember about me",
                ],
            },
            handler=self._handle_update_profile,
            metadata={
                "side_effect_level": "write",
                "permission_mode": "always_ok",
                "connectivity": "local",
                "latency_class": "interactive",
            },
        )
        # Track 5.2b: slot-fill extractors + completion handler for the
        # user_onboarding YAML template. None of these are user-facing
        # voice triggers — they're invoked by the template compiler.
        ctx.register_capability(
            spec={
                "name": "extract_user_name_or_skip",
                "description": "Internal: parse a name from an onboarding reply.",
                "parameters": {"text": "string - user's reply to the name question"},
            },
            handler=self._handle_extract_name_or_skip,
            metadata={"side_effect_level": "read", "connectivity": "local"},
        )
        ctx.register_capability(
            spec={
                "name": "extract_answer_or_skip",
                "description": (
                    "Internal: pass through onboarding answers verbatim; "
                    "return empty string for skip-tokens ('skip', 'no', 'later')."
                ),
                "parameters": {"text": "string - user's reply"},
            },
            handler=self._handle_extract_answer_or_skip,
            metadata={"side_effect_level": "read", "connectivity": "local"},
        )
        ctx.register_capability(
            spec={
                "name": "complete_onboarding",
                "description": (
                    "Final step of the user_onboarding workflow: write every "
                    "collected profile field, mark onboarding completed, "
                    "return the personalized greeting."
                ),
                "parameters": {
                    "name": "string",
                    "role": "string",
                    "location": "string",
                    "preferences": "string",
                    "comm_style": "string",
                },
            },
            handler=self._handle_complete_onboarding,
            metadata={
                "side_effect_level": "write",
                "permission_mode": "always_ok",
                "connectivity": "local",
            },
        )
        logger.info("OnboardingExtension loaded.")

    def unload(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Capability handler
    # ------------------------------------------------------------------

    def _handle_update_profile(self, raw_text: str, args: dict) -> str:
        field = (args.get("field") or "").strip().lower()
        value = (args.get("value") or "").strip()
        if field not in PROFILE_FIELDS:
            return (
                "I can only remember name, role, location, preferences, or "
                "communication style — which one?"
            )
        if not value:
            return f"What's the new {field.replace('_', ' ')}?"

        context_store = self._context_store()
        write_profile_field(context_store, field, value)

        ack = {
            "name": f"Got it — I'll call you {value}.",
            "role": f"Noted, you work as {value}.",
            "location": f"Noted, you're based in {value}.",
            "preferences": f"Got it, I'll keep that in mind: {value}.",
            "comm_style": f"Understood — I'll keep things {value}.",
        }
        return ack.get(field, f"Noted: {field} is now {value}.")

    # ------------------------------------------------------------------
    # Track 5.2b — onboarding YAML template handlers
    # ------------------------------------------------------------------

    def _handle_extract_name_or_skip(self, raw_text: str, args: dict) -> str:
        text = args.get("text") or raw_text or ""
        if _is_skip(text):
            return ""
        return _extract_name(text)

    def _handle_extract_answer_or_skip(self, raw_text: str, args: dict) -> str:
        text = args.get("text") or raw_text or ""
        if _is_skip(text):
            return ""
        return (text or "").strip()

    def _handle_complete_onboarding(self, raw_text: str, args: dict) -> str:
        store = self._context_store()
        for field in PROFILE_FIELDS:
            value = (args.get(field) or "").strip()
            # Persist every field — empty values record "asked and skipped"
            # so read_profile() can distinguish from "never asked".
            write_profile_field(store, field, value)
        mark_completed(store)
        name = (args.get("name") or "").strip()
        captured = [f for f in PROFILE_FIELDS if (args.get(f) or "").strip()]
        logger.info(
            "[onboarding] Completed via YAML; captured fields: %s",
            ", ".join(captured) or "none",
        )
        if name:
            return f"Got it, {name}. Glad to meet you. How can I help?"
        return "Got it. Glad to meet you. How can I help?"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _context_store(self):
        return self.ctx.get_service("context_store")
