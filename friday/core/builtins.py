"""Built-in tools wired to core services (memory, persona).

These are always available regardless of which capability modules are loaded.
Phase 7 ports the domain modules (file/web/security/...) on top of this.
"""
from __future__ import annotations

from friday.core.memory import Database
from friday.core.tools import ToolRegistry, ToolResult


def register_memory_tools(registry: ToolRegistry, db: Database) -> None:
    """Register remember_fact / recall_facts against the database."""

    def remember_fact(args: dict) -> ToolResult:
        key = (args.get("key") or "").strip()
        value = (args.get("value") or "").strip()
        if not key or not value:
            return ToolResult(ok=False, content="", error="both 'key' and 'value' are required")
        db.save_fact(key, value, category=args.get("category", "general"))
        return ToolResult(ok=True, content=f"Saved: {key} = {value}")

    def recall_facts(args: dict) -> ToolResult:
        query = (args.get("query") or "").strip()
        hits = db.search_facts(query) if query else db.all_facts()
        if not hits:
            return ToolResult(ok=True, content="No matching facts.")
        lines = "\n".join(f"- {h['key']}: {h['value']}" for h in hits)
        return ToolResult(ok=True, content=lines, data=hits)

    registry.register(
        name="remember_fact",
        description="Save a durable fact about the user for future conversations.",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "short fact name, e.g. 'preferred_editor'"},
                "value": {"type": "string", "description": "the fact value"},
                "category": {"type": "string", "description": "optional grouping"},
            },
            "required": ["key", "value"],
        },
        handler=remember_fact,
    )

    registry.register(
        name="recall_facts",
        description="Search saved facts about the user. Omit query to list all.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "keywords to search; empty lists all"},
            },
        },
        handler=recall_facts,
    )
