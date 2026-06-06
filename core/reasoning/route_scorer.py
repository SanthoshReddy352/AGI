"""RouteScorer — deterministic capability routing extracted from CommandRouter.

Phase 5: Moves the scoring/matching logic out of CommandRouter so that
CapabilityBroker can find the best route without importing the router at all.

The scorer consumes a list of "route entries" with the same shape the router
builds internally:
    {
        "spec": {"name": str, "description": str, ...},
        "aliases": [str, ...],
        "patterns": [compiled re, ...],
        "context_terms": [str, ...],
    }

RouteScorer can also build route entries from plain CapabilityDescriptors so
CapabilityRegistry can eventually replace the router's tool list entirely.
"""
from __future__ import annotations

import re
from typing import Callable



# Track 4.1b deeper extraction: defaults consolidated into
# core/reasoning/routing_defaults.py as the single source of truth.
# CommandRouter._default_*_for and this module both consume it.
from core.reasoning.routing_defaults import (  # noqa: E402
    DEFAULT_ALIASES as _DEFAULT_ALIASES,
    DEFAULT_CONTEXT_TERMS as _DEFAULT_CONTEXT_TERMS,
    DEFAULT_PATTERNS as _DEFAULT_PATTERNS,
)



class RouteScorer:
    """Score capability routes against user text without requiring CommandRouter.

    Accepts a callable that returns the current tools list so it always reflects
    newly registered capabilities.
    """

    def __init__(self, tools_getter: Callable[[], list[dict]]):
        self._get_tools = tools_getter

    # ------------------------------------------------------------------
    # Public API (same shape as CommandRouter.find_best_route)
    # ------------------------------------------------------------------

    def find_best_route(self, text: str, min_score: int = 20) -> dict | None:
        text_lower = _normalize(text)
        best_route = None
        best_score = 0
        for route in self._get_tools():
            if route["spec"]["name"] == "llm_chat":
                continue
            score = self._score_route(route, text_lower)
            if score > best_score:
                best_score = score
                best_route = route
        return best_route if best_score >= min_score else None

    # ------------------------------------------------------------------
    # Factory: build route entry from a plain spec dict
    # ------------------------------------------------------------------

    @classmethod
    def build_route_entry(cls, spec: dict, callback) -> dict:
        """Build a route entry dict from a capability spec + callback."""
        return {
            "spec": spec,
            "callback": callback,
            "aliases": cls._build_aliases(spec),
            "patterns": cls._build_patterns(spec),
            "context_terms": cls._build_context_terms(spec),
        }

    # ------------------------------------------------------------------
    # Scoring internals (extracted from CommandRouter._score_route)
    # ------------------------------------------------------------------

    @staticmethod
    def _score_route(route: dict, text_lower: str) -> int:
        score = 0

        if text_lower in route.get("aliases", []):
            score = max(score, 120)

        for pattern in route.get("patterns", []):
            if pattern.fullmatch(text_lower):
                score = max(score, 110)
            elif pattern.search(text_lower):
                score = max(score, 90)

        for alias in route.get("aliases", []):
            if alias == text_lower:
                score = max(score, 120)
            elif len(alias) > 2 and re.search(rf"\b{re.escape(alias)}\b", text_lower):
                score = max(score, 40 + len(alias.split()))

        for term in route.get("context_terms", []):
            if len(term) > 2 and re.search(rf"\b{re.escape(term)}\b", text_lower):
                score += 6

        tool_name_words = route["spec"]["name"].split("_")
        if tool_name_words and all(word in text_lower for word in tool_name_words):
            score = max(score, 25)

        return score

    # ------------------------------------------------------------------
    # Route entry builders
    # ------------------------------------------------------------------

    @classmethod
    def _build_aliases(cls, spec: dict) -> list[str]:
        name = spec["name"]
        aliases = set(spec.get("aliases", []))
        aliases.add(name.replace("_", " "))
        aliases.update(_DEFAULT_ALIASES.get(name, set()))
        return sorted(a for a in aliases if a)

    @classmethod
    def _build_patterns(cls, spec: dict) -> list:
        name = spec["name"]
        raw = list(spec.get("patterns", []) or []) + _DEFAULT_PATTERNS.get(name, [])
        compiled = []
        for p in raw:
            if isinstance(p, str):
                try:
                    compiled.append(re.compile(p, re.IGNORECASE))
                except re.error:
                    pass
            else:
                compiled.append(p)
        return compiled

    @classmethod
    def _build_context_terms(cls, spec: dict) -> list[str]:
        name = spec["name"]
        terms = set(spec.get("context_terms", []))
        terms.update(name.split("_"))
        terms.update(_DEFAULT_CONTEXT_TERMS.get(name, set()))
        return sorted(t for t in terms if t)


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().strip().split())
