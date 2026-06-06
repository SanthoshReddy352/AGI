"""Persona → system prompt for FRIDAY v2.

Ports the v1 YAML persona idea (kept — it's good): identity/tone/dos/donts live
in ``friday/personas/<id>.yaml`` and compose the system prompt. User facts and a
tool-usage/narration preamble are appended at build time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from friday.core.logger import logger

_PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"

# Behavioral preamble shared by all personas: how to call tools and narrate.
_AGENT_PREAMBLE = """\
You are a capable desktop agent. You have tools — use them to actually do things
rather than describing what you would do. Never claim a tool succeeded unless you
called it and saw the result.

When a task may take a moment, say a short, natural spoken line FIRST (in the same
turn as the tool call), e.g. "Sure, let me pull that up." Keep it human and brief
— no preamble like "Of course" or markdown. After tools run, answer directly.
"""


class Persona:
    def __init__(self, data: dict):
        self.id = data.get("persona_id", "friday_core")
        self.name = data.get("name", "FRIDAY")
        self.identity = (data.get("identity") or "").strip()
        self.tone = data.get("tone", "")
        self.dos = data.get("dos") or []
        self.donts = data.get("donts") or []
        self.speech_style = data.get("speech_style", "")
        self.conversation_style = data.get("conversation_style", "")

    def system_prompt(self, facts: Optional[list[dict]] = None) -> str:
        parts: list[str] = [self.identity or f"You are {self.name}."]
        if self.tone:
            parts.append(f"Tone: {self.tone}.")
        if self.dos:
            parts.append("Do:\n" + "\n".join(f"- {d}" for d in self.dos))
        if self.donts:
            parts.append("Don't:\n" + "\n".join(f"- {d}" for d in self.donts))
        parts.append(_AGENT_PREAMBLE)
        if facts:
            fact_lines = "\n".join(f"- {f['key']}: {f['value']}" for f in facts)
            parts.append(
                "USER_FACTS (these describe the USER, not you):\n" + fact_lines
            )
        return "\n\n".join(p for p in parts if p).strip()


def load_persona(persona_id: str = "friday_core") -> Persona:
    path = _PERSONA_DIR / f"{persona_id}.yaml"
    if not path.exists():
        logger.warning("[persona] %s not found, using minimal default", persona_id)
        return Persona({"persona_id": persona_id, "name": "FRIDAY"})
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Persona(data)
