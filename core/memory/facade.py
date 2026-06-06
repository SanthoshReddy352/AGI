"""Track 2 — MemoryFacade: the single canonical writer/reader for facts.

Before this facade existed, six stores wrote the same fact independently:
SemanticMemory, Mem0, PersonaManager, the entity-graph extractor,
ContextStore.facts (user_profile namespace), and ProceduralMemory. Each
stored the user's location (or name, or role) with a different
normalization, which produced the "Nellore vs Nolo-re" class of bug —
two spellings of the same fact returned from different stores in the
same response.

The facade provides ONE write path (`remember`) and ONE read path
(`recall`). Internally it delegates to SemanticMemory (canonical store
per the Track 2 Direction decision: SemanticMemory wins because FRIDAY
is local-first and Mem0's 8181-port service is operational surface area
we don't need).

Normalization happens on write:
  * Same-key conflict: if the new value is a near-duplicate of the
    existing value (Levenshtein-distance ratio above threshold), the
    longer / more-distinct spelling wins. This catches STT
    misrecognitions ("Nolo-re" vs "Nellore" — same fact, the longer
    user-spelling is canonical).
  * Known-alias replacement: a small alias map fixes common STT
    mishearings deterministically.
  * Distinct fact: when the new value is meaningfully different, it
    replaces (user updated). Older value is logged as superseded.

Subsequent Track 2 commits will:
  * Add a deterministic extractor for "my X is Y" patterns so facts
    actually flow into the facade without depending on the LLM.
  * Migrate PersonaManager + entity-graph extractor writes into the
    facade.
  * Delete Mem0 entirely (it currently runs on port 8181 and writes a
    parallel store the facade ignores).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Iterable

from core.memory.semantic import SemanticMemory


# Lightweight STT-misrecognition alias map. Add canonical spellings here
# when we observe a fact being persistently mishead. The keys are lowercased,
# whitespace-normalized values; lookups normalize the same way before matching.
_VALUE_ALIASES: dict[str, str] = {
    "nolo-re": "Nellore",
    "nolore": "Nellore",
    "noler": "Nellore",
}

# Track 2.2: when the facade writes one of these keys, it also mirrors the
# value into ContextStore's `user_profile` namespace so the legacy read
# paths in assistant_context.build_chat_messages and modules/onboarding
# continue to surface the same value. Once every consumer reads through
# the facade (Track 2.3), the mirror can be deleted.
_PROFILE_KEYS: frozenset[str] = frozenset({
    "name", "role", "location", "preferences", "comm_style",
    "employer", "hometown", "city", "job", "profession",
    "email", "phone", "birthday",
    "loves", "likes", "hates", "prefers",
})


@dataclass
class Fact:
    """A single remembered fact. Source identifies who provided it
    (user/extracted/system); scope governs lifetime."""

    key: str
    value: str
    source: str = "user"
    scope: str = "session"  # session | persona | persistent
    confidence: float = 1.0
    stored_at: float = 0.0
    superseded_value: str = ""

    def __post_init__(self) -> None:
        if self.stored_at == 0.0:
            self.stored_at = time.time()


# ---------------------------------------------------------------------------
# Normalization helpers — top-level so other modules can reuse them.
# ---------------------------------------------------------------------------


def normalize_value(value: str) -> str:
    """Apply the deterministic alias map to a candidate fact value.

    Returns the canonical spelling when the input matches a known alias,
    otherwise returns the input unchanged (whitespace-stripped). Pure
    function — no I/O, safe to call from anywhere.
    """
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    key = re.sub(r"\s+", " ", stripped).lower()
    return _VALUE_ALIASES.get(key, stripped)


def _is_near_duplicate(a: str, b: str) -> bool:
    """Cheap Levenshtein-distance ratio check. True when two strings are
    >=80% similar by character-level edit distance. Used to decide whether
    a same-key write is a different spelling (preserve longer) or a real
    update (replace)."""
    if not a or not b:
        return False
    if a == b:
        return True
    # difflib.SequenceMatcher is good enough for short fact values and
    # ships in stdlib (no new dep).
    import difflib  # noqa: PLC0415
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return ratio >= 0.80


def _prefer_canonical(existing: str, candidate: str) -> str:
    """When two near-duplicate spellings collide, return the more-canonical
    one. Heuristic: prefer longer strings (more letters → fewer dropped
    phonemes from STT), and prefer strings without hyphens / digits (those
    are usually misrecognition artifacts)."""
    if existing == candidate:
        return existing
    # Hyphens / digits are STT artifacts more often than not.
    def _stt_penalty(s: str) -> int:
        return sum(1 for c in s if c in "-0123456789")
    e_pen, c_pen = _stt_penalty(existing), _stt_penalty(candidate)
    if e_pen != c_pen:
        return candidate if c_pen < e_pen else existing
    if len(candidate) != len(existing):
        return candidate if len(candidate) > len(existing) else existing
    return existing  # tie → prior wins (stability)


# ---------------------------------------------------------------------------
# MemoryFacade
# ---------------------------------------------------------------------------


class MemoryFacade:
    """Single canonical writer/reader for session facts.

    Backed by SemanticMemory. Adds normalization, deduplication, and a
    uniform API the MemoryBroker and any plugin can call without knowing
    which store holds the truth.
    """

    def __init__(self, context_store, semantic: SemanticMemory | None = None):
        self._store = context_store
        self._semantic = semantic or SemanticMemory(context_store)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def remember(
        self,
        session_id: str,
        key: str,
        value: str,
        *,
        source: str = "user",
        scope: str = "session",
        confidence: float = 1.0,
        persona_id: str = "",
    ) -> Fact:
        """Store a fact. Normalizes the value, reconciles against any
        existing value for the same key, and returns the final Fact that
        was persisted (which may differ from the candidate when an older
        spelling won out).
        """
        if not key or not isinstance(value, str):
            return Fact(key=key or "", value="")
        candidate = normalize_value(value)
        if not candidate:
            return Fact(key=key, value="")

        existing = self._lookup_value(session_id, key, persona_id=persona_id)
        if existing and _is_near_duplicate(existing, candidate):
            winner = _prefer_canonical(existing, candidate)
            superseded = candidate if winner == existing else existing
        else:
            winner = candidate
            superseded = existing if existing else ""

        self._semantic.remember(
            session_id, key, winner,
            confidence=confidence, persona_id=persona_id,
        )
        # Track 2.2: mirror canonical profile fields into the legacy
        # `user_profile` namespace so existing readers (the chat prompt's
        # USER_FACTS injection, the onboarding `read_profile` helper) see
        # the same normalized value. Best-effort — never raises.
        if key in _PROFILE_KEYS:
            try:
                self._store.store_fact(key, winner, namespace="user_profile")
            except Exception:
                pass
        return Fact(
            key=key, value=winner, source=source, scope=scope,
            confidence=confidence, superseded_value=superseded,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recall(
        self,
        session_id: str,
        *,
        key: str | None = None,
        query: str | None = None,
        limit: int = 4,
        persona_id: str = "",
    ) -> list[Fact]:
        """Return facts matching `key` (exact key lookup) and/or `query`
        (semantic search). When both are None, returns the most-recent
        facts up to `limit`.
        """
        facts: list[Fact] = []
        if key:
            value = self._lookup_value(session_id, key, persona_id=persona_id)
            if value:
                facts.append(Fact(key=key, value=value, source="store"))
        if query:
            try:
                recalls = self._semantic.recall(session_id, query, limit=limit)
            except Exception:
                recalls = []
            for item in recalls:
                fact = self._item_to_fact(item)
                if fact is not None and not any(f.key == fact.key for f in facts):
                    facts.append(fact)
        if not facts and not key and not query:
            try:
                recents = self._semantic.recent(
                    session_id, limit=limit, persona_id=persona_id
                )
            except Exception:
                recents = []
            for item in recents:
                fact = self._item_to_fact(item)
                if fact is not None:
                    facts.append(fact)
        return facts[:limit]

    def forget(self, session_id: str, key: str, *, persona_id: str = "") -> bool:
        """Remove a stored fact. Returns True when something was deleted.

        Also clears the mirrored value from the `user_profile` namespace
        when the key is in `_PROFILE_KEYS`, so legacy readers stop seeing
        the fact too.
        """
        if not key:
            return False
        existed = bool(self._lookup_value(session_id, key, persona_id=persona_id))
        try:
            self._semantic.forget(session_id, key)
        except Exception:
            pass
        if key in _PROFILE_KEYS:
            try:
                self._store.store_fact(key, "", namespace="user_profile")
            except Exception:
                pass
        return existed

    def list_all(
        self,
        session_id: str,
        *,
        limit: int = 20,
        persona_id: str = "",
    ) -> list[Fact]:
        """Return all currently-known facts for the session. Used by the
        user-facing `show_memories` capability."""
        return self.recall(session_id, limit=limit, persona_id=persona_id)

    def render_user_facts(
        self,
        session_id: str,
        *,
        keys: Iterable[str] | None = None,
        persona_id: str = "",
    ) -> str:
        """Render the user's stored facts as a single multi-line string for
        injection into the chat system prompt. Optional `keys` filters to a
        subset (default: all recent)."""
        if keys is None:
            facts = self.recall(session_id, persona_id=persona_id, limit=10)
        else:
            facts = []
            for key in keys:
                value = self._lookup_value(session_id, key, persona_id=persona_id)
                if value:
                    facts.append(Fact(key=key, value=value, source="store"))
        if not facts:
            return ""
        lines = [f"- {fact.key}: {fact.value}" for fact in facts]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _lookup_value(self, session_id: str, key: str, persona_id: str = "") -> str:
        """Pull the current value for `key` out of the semantic store. The
        SemanticMemory upsert encodes facts with item_id `sem:<sid>:<key>`,
        so we scan recent semantic items and pick the one whose metadata
        key matches.
        """
        try:
            items = self._store.recent_memory_items(
                session_id, limit=100, persona_id=persona_id
            ) or []
        except Exception:
            return ""
        for item in items:
            if item.get("memory_type") != "semantic":
                continue
            meta = item.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if meta.get("key") == key:
                value = meta.get("value")
                if isinstance(value, str) and value:
                    return value
        return ""

    def _item_to_fact(self, item: dict) -> Fact | None:
        if item.get("memory_type") != "semantic":
            return None
        meta = item.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        key = meta.get("key") or ""
        value = meta.get("value") or ""
        if not key or not isinstance(value, str):
            return None
        return Fact(
            key=key,
            value=value,
            source="store",
            confidence=float(meta.get("confidence", 1.0)),
        )
