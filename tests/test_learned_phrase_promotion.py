"""Adaptive Intent Recognition Phase 4 — adaptive phrase memory.

The learning core: confirmed phrasings accrue hits; after PROMOTE_AFTER
zero-correction hits a phrasing is promoted and auto-dispatches deterministically
(`source="learned"`); a correction blocks it. Also covers the in-memory side:
`EmbeddingRouter.add_phrase` folds personal phrasings into the index so they
survive rebuilds, and capture-at-source on the lexical path.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

from core.capability_broker import CapabilityBroker, ToolPlan
from core.embedding_router import EmbeddingRouter
from core.planning.turn_orchestrator import TurnOrchestrator
from core.stores.intent_learning_store import PROMOTE_AFTER, IntentLearningStore


# ---------------------------------------------------------------------------
# Store — promotion / lookup / demotion
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))


def test_promotes_after_n_hits_and_lookup_finds_it(store):
    phrase = "make the screen cozy"
    for _ in range(PROMOTE_AFTER):
        store.note_hit(phrase, "set_brightness")
    row = store.promoted_lookup(phrase)
    assert row is not None
    assert row["tool"] == "set_brightness"
    assert row["status"] == "promoted"


def test_below_threshold_is_not_promoted(store):
    for _ in range(PROMOTE_AFTER - 1):
        store.note_hit("dim it down a touch", "set_brightness")
    assert store.promoted_lookup("dim it down a touch") is None


def test_correction_blocks_a_promoted_phrase(store):
    phrase = "make the screen cozy"
    for _ in range(PROMOTE_AFTER):
        store.note_hit(phrase, "set_brightness")
    assert store.promoted_lookup(phrase) is not None
    store.note_correction(phrase, "set_brightness")
    assert store.promoted_lookup(phrase) is None  # demoted/blocked


def test_active_phrases_excludes_blocked(store):
    store.note_hit("candidate phrasing", "get_battery")
    store.note_correction("bad phrasing", "set_volume")
    actives = {p["normalized"] for p in store.active_phrases()}
    assert "candidate phrasing" in actives
    assert "bad phrasing" not in actives


# ---------------------------------------------------------------------------
# EmbeddingRouter.add_phrase — personal phrasings folded into the index
# ---------------------------------------------------------------------------

class _FakeModel:
    """Deterministic 8-dim encoder: identical strings → identical unit vectors,
    so exact-match queries score cosine 1.0."""

    def encode(self, phrases, **kw):
        out = []
        for p in phrases:
            v = np.zeros(8, dtype=np.float32)
            for i, ch in enumerate(p[:8]):
                v[i % 8] += (ord(ch) % 7) + 1
            n = float(np.linalg.norm(v)) or 1.0
            out.append(v / n)
        return np.array(out, dtype=np.float32)


@pytest.fixture()
def embed_router(monkeypatch):
    # Legacy index path (no catalog) so we control the phrase set exactly.
    monkeypatch.setattr("core.tool_catalog.get_catalog",
                        lambda: SimpleNamespace(entry_for=lambda n: None))
    r = EmbeddingRouter()
    r._get_model = lambda: _FakeModel()  # type: ignore[method-assign]
    return r


def _tools(*names):
    return {n: {"spec": {"name": n, "description": n.replace("_", " ")}} for n in names}


def test_add_phrase_dedups_and_skips_blocklist(embed_router):
    assert embed_router.add_phrase("make it cozy", "set_brightness") is True
    assert embed_router.add_phrase("make it cozy", "set_brightness") is False  # dup
    # set_volume is in the default blocklist (structured args).
    assert embed_router.add_phrase("turn it up", "set_volume") is False


def test_personal_phrase_survives_rebuild_and_routes(embed_router):
    embed_router.add_phrase("make it cozy please", "set_brightness")
    embed_router.build_index(_tools("set_brightness", "get_battery"))
    assert "make it cozy please" in embed_router._tool_phrases
    # Exact match → cosine 1.0 → dispatch.
    match = embed_router.route("make it cozy please")
    assert match is not None and match["tool"] == "set_brightness"

    # A tool-set change forces a full rebuild; the personal phrase must persist.
    embed_router.build_index(_tools("set_brightness", "get_battery", "lock_screen"))
    assert "make it cozy please" in embed_router._tool_phrases


def test_add_phrase_appends_to_live_index(embed_router):
    embed_router.build_index(_tools("get_battery"))
    before = len(embed_router._tool_phrases)
    embed_router.add_phrase("how charged am i", "get_battery")
    assert len(embed_router._tool_phrases) == before + 1
    assert embed_router.route("how charged am i")["tool"] == "get_battery"


# ---------------------------------------------------------------------------
# Broker — learned auto-dispatch + capture-at-source + telemetry
# ---------------------------------------------------------------------------

class _FakeRegistry:
    def get_descriptor(self, name):
        if not name:
            return None
        return SimpleNamespace(side_effect_level="read", connectivity="local",
                               latency_class="interactive")


def _broker_with_store(tmp_path):
    store = IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))
    app = SimpleNamespace(
        session_id="s1",
        capability_registry=_FakeRegistry(),
        intent_learning_store=store,
        config=None,
        router=None,
    )
    return CapabilityBroker(app), store


def test_learned_dispatch_after_promotion(tmp_path):
    broker, store = _broker_with_store(tmp_path)
    phrase = "make the screen cozy"
    for _ in range(PROMOTE_AFTER):
        store.note_hit(phrase, "set_brightness")
    plan = broker._maybe_learned_dispatch(phrase, "t1", "")
    assert plan is not None
    assert plan.mode == "tool"
    assert plan.steps[0].capability_name == "set_brightness"
    assert plan.route_origin == "learned"


def test_learned_dispatch_none_for_unpromoted(tmp_path):
    broker, store = _broker_with_store(tmp_path)
    store.note_hit("only once", "set_brightness")
    assert broker._maybe_learned_dispatch("only once", "t1", "") is None


def test_plan_source_reports_learned():
    plan = ToolPlan(turn_id="t", mode="tool", route_origin="learned")
    assert TurnOrchestrator._plan_source(None, plan) == "learned"


def test_lexical_route_captures_hit(tmp_path, monkeypatch):
    # A near-miss fuzzy dispatch should accrue a learnable hit at source.
    from core.lexical_router import LexicalRouter
    store = IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))
    catalog = SimpleNamespace(entry_for=lambda n: (
        SimpleNamespace(example_phrases=["lock the screen"], is_safe_for_preflight=True)
        if n == "lock_screen" else None))
    monkeypatch.setattr("core.tool_catalog.get_catalog", lambda: catalog)
    lex = LexicalRouter()
    lex.build_index({"lock_screen": {}})
    app = SimpleNamespace(
        session_id="s1", capability_registry=_FakeRegistry(),
        intent_learning_store=store, config=None,
        router=SimpleNamespace(lexical_router=lex, _tools_by_name={"lock_screen": {}}),
    )
    broker = CapabilityBroker(app)
    plan = broker._maybe_lexical_route("lock the screem", "t1", "")
    assert plan is not None and plan.steps[0].capability_name == "lock_screen"
    assert plan.route_origin == "lexical"
    assert store.get_phrase("lock the screem", "lock_screen")["hit_count"] == 1
