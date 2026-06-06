"""Adaptive Intent Recognition Phase 3 — fuzzy / lexical router.

The lexical router catches cheap near-misses (STT mishears, typos, word-order
shuffles) the regex layer drops, before the embedding router runs. It must be
conservative: high token_set_ratio threshold + a margin over the runner-up, so
it never poaches a turn that the embedding/LLM layers should arbitrate.
"""
from __future__ import annotations

import pytest

from core.lexical_router import (
    LEXICAL_THRESHOLD,
    LexicalRouter,
    _expand_synonyms,
    _normalize,
    _token_set_ratio,
)


# A tiny stand-in catalog so the tests don't depend on the real YAML. The
# router pulls phrases from get_catalog().entry_for(name).example_phrases, so
# we patch get_catalog to return this.
class _Entry:
    def __init__(self, name, phrases, safe=True):
        self.name = name
        self.example_phrases = phrases
        self._safe = safe

    @property
    def is_safe_for_preflight(self):
        return self._safe


class _Catalog:
    def __init__(self, entries):
        self._by_name = {e.name: e for e in entries}

    def entry_for(self, name):
        return self._by_name.get(name)


@pytest.fixture()
def router(monkeypatch):
    catalog = _Catalog([
        _Entry("lock_screen", ["lock the screen", "lock my computer", "secure the screen"]),
        _Entry("take_screenshot", ["take a screenshot", "capture my screen", "grab the screen"]),
        _Entry("get_battery", ["how much battery is left", "check the battery"]),
        # A structured-arg tool that must be excluded from empty-args dispatch.
        _Entry("set_volume", ["set the volume to fifty"], safe=False),
    ])
    monkeypatch.setattr("core.tool_catalog.get_catalog", lambda: catalog)
    r = LexicalRouter()
    tools = {n: {} for n in ["lock_screen", "take_screenshot", "get_battery", "set_volume"]}
    r.build_index(tools)
    return r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_normalize_and_synonym_expansion():
    assert _normalize("  Lock  the SCREEN! ") == "lock the screen"
    # "screem" is a common STT miss for "screen"; "pic" folds to screenshot.
    assert "screen" in _expand_synonyms(_normalize("lock the screem"))
    assert "screenshot" in _expand_synonyms(_normalize("take a pic"))


def test_token_set_ratio_order_invariant():
    assert _token_set_ratio("lock the screen", "screen the lock") >= 95.0


# ---------------------------------------------------------------------------
# Routing — positives (genuine near-misses)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance,expected", [
    ("lock the screem", "lock_screen"),          # STT miss
    ("lock teh scren", "lock_screen"),           # typos
    ("screen lock the", "lock_screen"),          # word order
    ("capture my scren", "take_screenshot"),     # typo
    ("how much batery is left", "get_battery"),  # typo
])
def test_route_catches_near_misses(router, utterance, expected):
    match = router.route(utterance)
    assert match is not None, f"{utterance!r} should fuzzy-match {expected}"
    assert match["tool"] == expected
    assert match["score"] >= LEXICAL_THRESHOLD


# ---------------------------------------------------------------------------
# Routing — negatives (must NOT match)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "what's the weather like in tokyo tomorrow",   # unrelated
    "tell me a joke",                              # unrelated
    "the lock on my car door is broken",           # contains 'lock' but off-domain
])
def test_route_rejects_unrelated(router, utterance):
    assert router.route(utterance) is None


def test_route_excludes_structured_arg_tools(router):
    # set_volume is blocked_from_chat_preflight (safe=False) → never indexed,
    # so even a near-exact phrasing must not fuzzy-dispatch it.
    assert router.route("set the volume to fifty") is None


def test_empty_and_unbuilt_router_return_none():
    fresh = LexicalRouter()
    assert fresh.route("anything") is None  # no index built yet
    assert fresh.route("") is None


def test_stats_reports_backend(router):
    s = router.stats()
    assert s["indexed_tools"] == 3  # set_volume excluded
    assert s["backend"] in {"rapidfuzz", "difflib"}


def test_extra_phrases_are_indexed(monkeypatch):
    monkeypatch.setattr("core.tool_catalog.get_catalog", lambda: _Catalog([]))
    r = LexicalRouter()
    r.build_index({"refresh_app_index": {}},
                  extra_phrases=[("rescan my applications", "refresh_app_index")])
    match = r.route("rescan my aplications")  # typo against the learned phrase
    assert match is not None
    assert match["tool"] == "refresh_app_index"
