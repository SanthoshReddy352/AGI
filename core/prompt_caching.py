"""PromptCache — lightweight TTL cache for prompt fragments (P3.21).

Sections that don't change turn-to-turn (ASSISTANT_IDENTITY, static
USER_FACTS) are cached so PromptBuilder doesn't recompute them on
every call. TTL defaults to 300 s (5-minute Anthropic cache window).

Module-level functions delegate to a single process-wide singleton.
"""
from __future__ import annotations

import time
from typing import Optional

_DEFAULT_TTL = 300  # seconds


class PromptCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires = entry
        if time.monotonic() > expires:
            del self._store[key]
            return None
        return value

    def put(self, key: str, value: str, ttl: int = _DEFAULT_TTL) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_all(self) -> None:
        self._store.clear()

    def size(self) -> int:
        now = time.monotonic()
        return sum(1 for _, expires in self._store.values() if expires > now)


_cache = PromptCache()


def get(key: str) -> Optional[str]:
    return _cache.get(key)


def put(key: str, value: str, ttl: int = _DEFAULT_TTL) -> None:
    _cache.put(key, value, ttl)


def invalidate(key: str) -> None:
    _cache.invalidate(key)


def invalidate_all() -> None:
    _cache.invalidate_all()
