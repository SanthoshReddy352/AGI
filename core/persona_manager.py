from __future__ import annotations

import os
from dataclasses import dataclass, asdict

from core.logger import logger


@dataclass
class PersonaProfile:
    persona_id: str
    display_name: str
    system_identity: str
    tone_traits: str = "warm, calm, capable"
    conversation_style: str = "natural and concise"
    speech_style: str = "clear and confident"
    humor_level: str = "light"
    verbosity_preference: str = "adaptive"
    formality_level: str = "balanced"
    empathy_style: str = "supportive"
    tool_ack_style: str = "brief and reassuring"
    memory_scope: str = "shared"
    retrieval_filters: str = ""
    example_dialogues: str = ""
    enabled_skills: str = "*"
    disallowed_behaviors: str = "sound robotic, over-explain every simple action"


def _default_persona_yaml_path() -> str:
    # repo_root/config/personas/default.yaml
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "personas", "default.yaml",
    )


def _load_persona_yaml(path: str | None) -> dict:
    """Best-effort YAML load. Returns {} on any failure (file missing,
    YAML not installed, malformed)."""
    path = path or _default_persona_yaml_path()
    if not os.path.isfile(path):
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        logger.warning("[persona] PyYAML missing; using hardcoded defaults")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("[persona] failed to load %s: %s", path, exc)
        return {}


def _bullets(prefix: str, items) -> str:
    if not items:
        return ""
    if isinstance(items, str):
        return f"{prefix} {items.strip()}"
    lines = [f"  - {str(b).strip()}" for b in items if str(b).strip()]
    if not lines:
        return ""
    return f"{prefix}\n" + "\n".join(lines)


def render_identity_prompt(data: dict) -> str:
    """Build the system-prompt identity text from a persona dict.

    Sections appended in order: identity, tone, dos, donts. Empty
    sections are skipped so the prompt stays tight.
    """
    parts: list[str] = []
    identity = (data.get("identity") or data.get("system_identity") or "").strip()
    if identity:
        parts.append(identity)
    tone = (data.get("tone") or data.get("tone_traits") or "").strip()
    if tone:
        parts.append(f"Tone: {tone}.")
    dos_block = _bullets("Do:", data.get("dos"))
    if dos_block:
        parts.append(dos_block)
    donts_block = _bullets("Don't:", data.get("donts"))
    if donts_block:
        parts.append(donts_block)
    return "\n\n".join(parts).strip()


class PersonaManager:
    DEFAULT_PERSONA_ID = "friday_core"

    # P2.5: YAML-defined persona overrides the hardcoded defaults. Held
    # on the class so prompt_builder.friday_prompt() can read it without
    # an instance handle (the chat plugin's fallback path is module-level).
    _yaml_cache: dict | None = None

    def __init__(self, context_store, yaml_path: str | None = None):
        self.context_store = context_store
        self._yaml_path = yaml_path
        self._reload_yaml()
        self.ensure_default_persona()

    def _reload_yaml(self) -> dict:
        data = _load_persona_yaml(self._yaml_path)
        PersonaManager._yaml_cache = data
        return data

    @classmethod
    def get_yaml_persona(cls) -> dict:
        """Returns the cached YAML persona dict (may be empty)."""
        if cls._yaml_cache is None:
            cls._yaml_cache = _load_persona_yaml(None)
        return cls._yaml_cache or {}

    @classmethod
    def identity_prompt(cls) -> str:
        """Return the rendered system-prompt identity (YAML-driven when present)."""
        return render_identity_prompt(cls.get_yaml_persona())

    @classmethod
    def assistant_name(cls) -> str:
        """Return the assistant's display name (YAML-driven, falls back to FRIDAY).

        Single source of truth for "who the assistant is" — used by the
        impersonation guard / scrubber so renaming the persona in
        ``config/personas/default.yaml`` propagates everywhere without code
        edits, the same way the user's name is read live from the profile.
        """
        name = (cls.get_yaml_persona().get("name") or "").strip()
        return name or "FRIDAY"

    def ensure_default_persona(self):
        if self.context_store.get_persona(self.DEFAULT_PERSONA_ID):
            return
        yaml_data = self._yaml_cache or {}
        defaults = dict(
            persona_id=self.DEFAULT_PERSONA_ID,
            display_name=yaml_data.get("name") or "FRIDAY",
            system_identity=(
                yaml_data.get("identity") or
                "FRIDAY is a voice-first local assistant that feels present, human, and capable. "
                "It keeps responses smooth, calm, and useful while staying privacy-aware."
            ).strip(),
            tone_traits=yaml_data.get("tone")
                or "warm, conversational, capable, grounded",
            conversation_style=yaml_data.get("conversation_style")
                or "natural turn-taking with short clarifications",
            speech_style=yaml_data.get("speech_style")
                or "spoken, smooth, and lightly polished",
            humor_level=yaml_data.get("humor_level") or "subtle",
            verbosity_preference=yaml_data.get("verbosity_preference") or "adaptive",
            formality_level=yaml_data.get("formality_level") or "friendly",
            empathy_style=yaml_data.get("empathy_style") or "steady and reassuring",
            tool_ack_style=yaml_data.get("tool_ack_style")
                or "short spoken acknowledgement before slow actions",
            memory_scope=yaml_data.get("memory_scope") or "shared",
            retrieval_filters=yaml_data.get("retrieval_filters")
                or "prefer recent user preferences and active workflow context",
            disallowed_behaviors=", ".join(yaml_data.get("donts") or [])
                or "sound robotic, over-explain every simple action",
        )
        self.save_persona(PersonaProfile(**defaults))

    def save_persona(self, profile: PersonaProfile | dict):
        payload = asdict(profile) if isinstance(profile, PersonaProfile) else dict(profile)
        self.context_store.save_persona(payload)
        return payload

    def get_persona(self, persona_id: str | None):
        persona_id = persona_id or self.DEFAULT_PERSONA_ID
        record = self.context_store.get_persona(persona_id)
        if record:
            return record
        return self.context_store.get_persona(self.DEFAULT_PERSONA_ID)

    def list_personas(self):
        return self.context_store.list_personas()

    def get_active_persona(self, session_id: str):
        active_id = self.context_store.get_active_persona_id(session_id) or self.DEFAULT_PERSONA_ID
        persona = self.get_persona(active_id)
        if persona:
            return persona
        return self.get_persona(self.DEFAULT_PERSONA_ID)

    def set_active_persona(self, session_id: str, persona_id: str):
        persona = self.get_persona(persona_id)
        if not persona:
            raise ValueError(f"Unknown persona '{persona_id}'")
        self.context_store.set_active_persona(session_id, persona["persona_id"])
        return persona
