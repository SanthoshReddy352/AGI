"""PromptBuilder — composable, labelled system-prompt sections (P3.21).

Replaces ad-hoc FRIDAY_PERSONA string concat in llm_chat/plugin.py.
Sections are named so tests can assert their presence structurally,
and the static identity section is pre-built at module load time.

Usage:
    pb = friday_prompt()           # standard FRIDAY persona builder
    pb.add_section("USER_FACTS", user_facts_text, cacheable=False)
    messages = pb.build_messages(query)

Or use the module-level helper:
    messages = build_default_messages(query)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _Section:
    name: str
    content: str
    cacheable: bool = True


# The base FRIDAY identity text — single source of truth.
FRIDAY_IDENTITY = (
    "You are FRIDAY, a personal AI assistant. "
    "You are intelligent, warm, and speak like a real person — not a formal assistant. "
    "Match the user's energy and give responses as long as the topic deserves. "
    "No preamble, no chain-of-thought, no emoji unless the user uses one first. "
    "When the user asks who YOU are, answer with this identity — never describe yourself "
    "using facts from the USER_FACTS block (those describe the user, not you)."
)


class PromptBuilder:
    """Compose a system prompt from named, ordered sections."""

    def __init__(self) -> None:
        self._sections: list[_Section] = []

    def add_section(self, name: str, content: str, cacheable: bool = True) -> "PromptBuilder":
        if content and content.strip():
            self._sections.append(_Section(name=name, content=content.strip(), cacheable=cacheable))
        return self

    def remove_section(self, name: str) -> "PromptBuilder":
        self._sections = [s for s in self._sections if s.name != name]
        return self

    def has_section(self, name: str) -> bool:
        return any(s.name == name for s in self._sections)

    def section_names(self) -> list[str]:
        return [s.name for s in self._sections]

    def build(self) -> str:
        parts = [
            f"<{s.name}>\n{s.content}\n</{s.name}>"
            for s in self._sections if s.content
        ]
        return "\n\n".join(parts)

    def build_messages(self, query: str) -> list[dict]:
        system = self.build()
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": query})
        return msgs


def friday_prompt(extra_identity: str = "") -> PromptBuilder:
    """Return a PromptBuilder pre-loaded with the standard FRIDAY identity.

    P2.5: identity is sourced from ``config/personas/default.yaml`` via
    ``PersonaManager.identity_prompt()`` when available. Falls back to
    the hardcoded ``FRIDAY_IDENTITY`` if the YAML is missing / empty.
    """
    identity = FRIDAY_IDENTITY
    try:
        from core.persona_manager import PersonaManager  # noqa: PLC0415
        yaml_identity = PersonaManager.identity_prompt()
        if yaml_identity:
            identity = yaml_identity
    except Exception:
        pass
    if extra_identity:
        identity = identity + " " + extra_identity.strip()
    return PromptBuilder().add_section("ASSISTANT_IDENTITY", identity, cacheable=True)


def build_default_messages(query: str, user_facts: str = "") -> list[dict]:
    """Convenience: build the minimal fallback message list for a query."""
    pb = friday_prompt()
    if user_facts:
        pb.add_section("USER_FACTS", user_facts, cacheable=False)
    return pb.build_messages(query)
