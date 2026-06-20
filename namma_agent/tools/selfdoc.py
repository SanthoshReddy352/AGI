"""Self-knowledge tool — the assistant can answer questions about itself/its config."""
from __future__ import annotations

import re
from pathlib import Path

from namma_agent.config import assistant_name
from namma_agent.core.tools import ToolRegistry, ToolResult

_SELF_DOC = Path(__file__).resolve().parent.parent / "self_knowledge.md"

# The literal "FRIDAY" is the placeholder token used inside self_knowledge.md; it is
# substituted with the live display name at read time (but NOT the NAMMA_* env prefix).
_NAME_TOKEN = re.compile(r"\bFRIDAY\b(?!_)")


def _about_namma(args: dict) -> ToolResult:
    if not _SELF_DOC.exists():
        return ToolResult(ok=False, content="", error="self-knowledge doc missing")
    text = _SELF_DOC.read_text(encoding="utf-8", errors="replace")
    # Reflect the configured display name (env-var names like NAMMA_API_KEY stay).
    name = assistant_name()
    if name != "FRIDAY":
        text = _NAME_TOKEN.sub(name, text)
    topic = (args.get("topic") or "").strip().lower()
    if topic:
        # Return only the section(s) whose heading matches the topic.
        blocks = text.split("\n## ")
        hits = [b if b.startswith("# About") else "## " + b
                for b in blocks if topic in b.lower()]
        if hits:
            return ToolResult(ok=True, content="\n\n".join(hits))
    return ToolResult(ok=True, content=text)


def register(registry: ToolRegistry) -> None:
    registry.register(
        "about_namma",
        "Look up how Namma Agent itself works/configures (modes, switching the model "
        "provider, tools, skills, memory, browser, telegram, logging). Use this to "
        "answer the user's questions about Namma Agent's own settings and capabilities.",
        {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "description": "optional keyword to fetch one section (e.g. 'provider', 'memory')"},
            },
        }, _about_namma)
