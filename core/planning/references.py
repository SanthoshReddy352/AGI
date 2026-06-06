"""Track 1.3b — Reference Registry as a first-class turn-scoped API.

The Direction calls for `current_turn().references` as the canonical
place plugins emit numbered lists and ordinal references get resolved.
Before this module, references lived in `ContextStore.references` (a
session-state JSON blob) and were populated implicitly by
`ResponseFinalizer._update_reference_registry` regex-scanning the
final response text. Two problems with that:

* The implicit regex scan only catches ``^\\d+\\.`` shapes; producers
  that emit dashes / `*` bullets miss the registry entirely.
* The scope is session-wide; cross-turn state leaks between
  unrelated lists (the user's earlier "find file readme" stays in
  scope when they later "find email reports", until the registry is
  overwritten).

`TurnReferences` is the explicit, typed API. Plugins call
`turn.references.register(items, kind="files")` after producing a
numbered list. The class WRITES THROUGH to `context_store.references`
so existing readers (intent_recognizer._parse_pending_selection,
ContextResolver._ordinal_target) continue to work without migration.
That keeps Track 1.3b additive — no behavior change for legacy code,
new code gets the cleaner API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


_ORDINAL_WORDS = (
    "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
)
_DIGIT_ORDINAL_TO_WORD = {
    "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth",
    "5th": "fifth", "6th": "sixth", "7th": "seventh", "8th": "eighth",
    "9th": "ninth", "10th": "tenth",
}


@dataclass
class TurnReferences:
    """Per-turn references registry.

    Constructed by `TurnManager` and attached to `TurnContext`. The
    plugin / handler creating a numbered list calls
    `register(items, kind="files"|"emails"|"results"|...)` once; the
    registry maps each item to its ordinal slot AND to a kind-tagged
    `last_list` so future turns can replay the most recent list.

    Writes mirror to `context_store.references` (session-state JSON)
    so legacy readers don't need migration. Reads consult the mirror
    too, which means after a process restart the references survive
    if the session persists.
    """

    _store: object | None = None  # ContextStore-shaped
    _session_id: str = ""
    _kind: str = ""
    _items: list[str] = field(default_factory=list)

    def register(self, items: Sequence[str], *, kind: str = "items") -> None:
        """Record a numbered list of `items` under `kind` (e.g. "files",
        "emails", "results"). Ordinals (`first` … `tenth`) are bound to
        the first 10 items; `last_list` holds the full set as a newline-
        joined string for downstream consumers."""
        clean = [str(item).strip() for item in items if str(item).strip()]
        self._kind = (kind or "items").strip().lower() or "items"
        self._items = clean[:10]
        if self._store is None or not self._session_id:
            return
        try:
            for index, item in enumerate(self._items):
                if index < len(_ORDINAL_WORDS):
                    self._store.save_reference(self._session_id, _ORDINAL_WORDS[index], item)
            self._store.save_reference(self._session_id, "last_list", "\n".join(self._items))
            self._store.save_reference(self._session_id, "last_list_kind", self._kind)
        except Exception:
            pass

    def resolve(self, ordinal: str) -> str:
        """Map an ordinal word ("first", "second", …, "tenth", "last")
        OR digit form ("1st", "2nd", …, "10th") to its registered item.
        Returns "" when no match."""
        if not ordinal:
            return ""
        token = ordinal.strip().lower()
        if token == "last":
            if self._items:
                return self._items[-1]
            return self._lookup_last_from_store()
        if token in _DIGIT_ORDINAL_TO_WORD:
            token = _DIGIT_ORDINAL_TO_WORD[token]
        if token not in _ORDINAL_WORDS:
            return ""
        if self._items and token in _ORDINAL_WORDS:
            index = _ORDINAL_WORDS.index(token)
            if 0 <= index < len(self._items):
                return self._items[index]
        if self._store is not None and self._session_id:
            try:
                value = self._store.get_reference(self._session_id, token) or ""
            except Exception:
                return ""
            return value
        return ""

    def kind(self) -> str:
        """Return the kind label of the currently-registered list (e.g.
        "files", "emails"). Empty when no list is registered."""
        if self._kind:
            return self._kind
        if self._store is not None and self._session_id:
            try:
                return self._store.get_reference(self._session_id, "last_list_kind") or ""
            except Exception:
                return ""
        return ""

    def items(self) -> list[str]:
        """Return the in-memory item list. Empty if no `register` was
        called this turn — does NOT replay from the store (that's a
        session-state question, callers can use `resolve` for ordinals)."""
        return list(self._items)

    def _lookup_last_from_store(self) -> str:
        if self._store is None or not self._session_id:
            return ""
        try:
            blob = self._store.get_reference(self._session_id, "last_list") or ""
        except Exception:
            return ""
        if not blob:
            return ""
        tail = blob.rstrip().split("\n")
        return tail[-1] if tail else ""


def attach(store, session_id: str) -> TurnReferences:
    """Convenience factory used by TurnManager to attach a fresh
    `TurnReferences` to a TurnContext at turn-start. Pre-binds the
    store + session so plugin code can just call `register(...)` /
    `resolve(...)` without passing those each time."""
    return TurnReferences(_store=store, _session_id=session_id or "")
