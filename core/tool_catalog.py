"""Tool catalog — single source of truth for user-facing capabilities.

Loaded once at boot from `data/tool_catalog.yaml`. Three consumers:

  • :class:`core.embedding_router.EmbeddingRouter` — embeds every
    `example_phrases` entry so cosine similarity matches *how users
    actually talk*, not the noun cloud auto-built from plugin
    `aliases` / `context_terms`.
  • The Qwen-4B planner prompt builder — injects the top-K closest
    example_phrases as few-shot context.
  • :mod:`modules.llm_chat.plugin` — pre-flight reroute: if the user
    query cosines ≥ 0.62 against any catalog phrase, the chat plugin
    aborts generation and dispatches the tool instead.

Why YAML instead of generating from capability registrations:

  - Authoring `example_phrases` is a *prompting* exercise, not a
    coding exercise. It belongs in a data file curated by humans, not
    inside a Python plugin file mixed with implementation logic.
  - The catalog can be shipped, diffed, and reviewed independently.
  - One file, one PR, one place to update when adding a new tool.

Schema validation is intentionally loose — we warn instead of raising
so an out-of-date entry never kills boot. The registered-capability
cross-check happens at `bind_registry()` time and warns about catalog
entries that point at non-existent tools (and vice versa).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from core.logger import logger


CATALOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "tool_catalog.yaml",
)


@dataclass
class CatalogEntry:
    """One tool entry in the catalog. See data/tool_catalog.yaml schema."""
    name: str
    category: str
    summary: str
    example_phrases: list[str]
    parameters: dict[str, str] = field(default_factory=dict)
    embeddable: bool = True
    blocked_from_chat_preflight: bool = False

    @property
    def is_safe_for_preflight(self) -> bool:
        """True iff the chat-side pre-flight may auto-dispatch this tool.

        Tools with required structured args (e.g. set_volume needs a
        percent, set_reminder needs a time) should set
        `blocked_from_chat_preflight: true` in the catalog so an empty-
        args dispatch doesn't surprise the user. The planner can still
        route to them with the LLM's argument-extraction.
        """
        return self.embeddable and not self.blocked_from_chat_preflight


class Catalog:
    """In-memory view of the tool catalog."""

    def __init__(self, entries: list[CatalogEntry]):
        self._entries = entries
        self._by_name: dict[str, CatalogEntry] = {e.name: e for e in entries}

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def names(self) -> list[str]:
        return [e.name for e in self._entries]

    def entry_for(self, name: str) -> Optional[CatalogEntry]:
        return self._by_name.get(name)

    def entries_in_category(self, category: str) -> list[CatalogEntry]:
        return [e for e in self._entries if e.category == category]

    def iter_phrases(self):
        """Yield (tool_name, phrase) for every example phrase in the catalog."""
        for entry in self._entries:
            for phrase in entry.example_phrases:
                yield entry.name, phrase

    def bind_registry(self, tools_by_name: dict) -> None:
        """Cross-check catalog vs. live registry; warn on mismatches.

        We never raise — a stale catalog should never kill boot. But the
        log surface makes it obvious when an entry has rotted or a new
        tool was added without a catalog entry.
        """
        registered = set(tools_by_name.keys())
        cataloged = set(self._by_name.keys())

        missing_from_catalog = sorted(
            n for n in registered - cataloged
            # Skip internal / framework names that aren't user-invoked.
            if not n.startswith("_") and n not in _INTERNAL_TOOL_NAMES
        )
        if missing_from_catalog:
            logger.info(
                "[catalog] %d registered tool(s) lack a catalog entry: %s",
                len(missing_from_catalog),
                ", ".join(missing_from_catalog[:10])
                + ("…" if len(missing_from_catalog) > 10 else ""),
            )

        stale = sorted(cataloged - registered)
        if stale:
            logger.warning(
                "[catalog] %d catalog entry/entries reference unregistered tools: %s",
                len(stale), ", ".join(stale[:10]),
            )


# Tools that are framework-internal — never user-invoked — and therefore
# don't need a catalog entry. Updating this list is fine; the catalog
# bind_registry() warning is the only consumer.
_INTERNAL_TOOL_NAMES = frozenset({
    "extract_answer_or_skip",
    "extract_user_name_or_skip",
    "send_progress",
    "send_notification",  # has a catalog entry under the same name — keep both safe
    "complete_onboarding",
    "detect_media_command",
    "detect_new_filename",
    "browser_media_dispatch",
    "confirm_yes",
    "confirm_no",
    "select_file_candidate",
    "confirm_memory_wipe",
    "cancel_memory_wipe",
    "resume_session",
    "start_fresh_session",
    "FRIDAY",
    "show_capabilities",
    "string",  # parameter-stub artifact from one of the plugin specs
    "llm_chat",  # the catch-all itself
    "mcp_list_servers",
})


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_catalog(path: str = CATALOG_PATH_DEFAULT) -> Catalog:
    """Parse the YAML catalog at *path* and return a :class:`Catalog`.

    Returns an empty catalog (and warns) if PyYAML isn't installed or the
    file is malformed. Never raises — routing must still work without
    the catalog (we just lose example-phrase embedding coverage).
    """
    if not os.path.exists(path):
        logger.warning("[catalog] not found at %s; routing falls back to legacy paths", path)
        return Catalog([])

    try:
        import yaml  # noqa: PLC0415 — runtime-optional
    except ImportError:
        logger.warning("[catalog] PyYAML not installed; skipping catalog load")
        return Catalog([])

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("[catalog] parse failure for %s: %s", path, exc)
        return Catalog([])

    if not isinstance(data, dict) or "tools" not in data:
        logger.warning("[catalog] %s has no top-level 'tools:' key", path)
        return Catalog([])

    entries: list[CatalogEntry] = []
    seen_names: set[str] = set()
    for raw in data.get("tools") or []:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            logger.warning("[catalog] dropping entry with no name: %r", raw)
            continue
        if name in seen_names:
            logger.warning("[catalog] duplicate entry for %r — keeping the first", name)
            continue
        seen_names.add(name)

        phrases = raw.get("example_phrases") or []
        if not isinstance(phrases, list) or not phrases:
            logger.warning("[catalog] %s has no example_phrases — won't be embedded", name)
            phrases = []
        phrases = [str(p).strip() for p in phrases if str(p).strip()]

        params_raw = raw.get("parameters") or {}
        parameters: dict[str, str] = {}
        if isinstance(params_raw, dict):
            for k, v in params_raw.items():
                parameters[str(k)] = str(v)

        entry = CatalogEntry(
            name=name,
            category=str(raw.get("category") or "misc"),
            summary=str(raw.get("summary") or "").strip(),
            example_phrases=phrases,
            parameters=parameters,
            embeddable=bool(raw.get("embeddable", True)),
            blocked_from_chat_preflight=bool(raw.get("blocked_from_chat_preflight", False)),
        )
        entries.append(entry)

    logger.info("[catalog] loaded %d entries from %s", len(entries), os.path.basename(path))
    return Catalog(entries)


_singleton: Optional[Catalog] = None


def get_catalog() -> Catalog:
    """Process-wide singleton accessor (lazy)."""
    global _singleton
    if _singleton is None:
        _singleton = load_catalog()
    return _singleton


def reset_catalog_for_tests(path: Optional[str] = None) -> Catalog:
    """Force-reload the catalog. Tests use this to point at a temp file."""
    global _singleton
    _singleton = load_catalog(path) if path else load_catalog()
    return _singleton
