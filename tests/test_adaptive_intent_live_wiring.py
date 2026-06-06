"""End-to-end wiring proof for Adaptive Intent Recognition (Phases 2-5).

Unlike the per-phase unit suites (which exercise broker helpers in isolation)
and test_planning_engines.py (which uses a MagicMock broker), this drives the
*real* PlannerEngine over the *real* CapabilityBroker + real IntentLearningStore
through the production plan pipeline — proving the new steps (4a learned, 4b
lexical, 5b confirm) actually fire in order on a live-shaped app, and that the
day-by-day capture lands in the store.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from core.capability_broker import CapabilityBroker
from core.lexical_router import LexicalRouter
from core.planning.planner_engine import PlannerEngine
from core.stores.intent_learning_store import PROMOTE_AFTER, IntentLearningStore


class _Consent:
    @staticmethod
    def is_positive_confirmation(t): return t.strip().lower() in {"yes", "yeah", "sure"}
    @staticmethod
    def is_negative_confirmation(t): return t.strip().lower() in {"no", "nope"}


class _Registry:
    def get_descriptor(self, name):
        if not name:
            return None
        return SimpleNamespace(side_effect_level="read", connectivity="local",
                               latency_class="interactive")
    def has_capability(self, name): return name == "llm_chat"


class _Mem:
    def __init__(self): self.state = {}
    def get_session_state(self, sid): return dict(self.state)
    def set_pending_intent(self, sid, p): self.state["pending_intent"] = dict(p or {})
    def clear_pending_intent(self, sid): self.state["pending_intent"] = {}
    def set_pending_online(self, sid, p): self.state["pending_online"] = dict(p or {})
    def clear_pending_online(self, sid): self.state["pending_online"] = {}


class _EmbedStub:
    """confirm_candidate fires only for the designated confirm-test phrase, so
    the learned/lexical branches own the other phrases."""
    def __init__(self, confirm_for): self._confirm_for = confirm_for
    def build_index(self, tools): pass
    def confirm_candidate(self, text):
        if text.strip().lower() == self._confirm_for:
            return {"tool": "get_battery", "score": 0.55}
        return None


@pytest.fixture()
def live(tmp_path, monkeypatch):
    # Lexical router with a tiny catalog so "lock the screem" near-misses.
    catalog = SimpleNamespace(entry_for=lambda n: (
        SimpleNamespace(example_phrases=["lock the screen"], is_safe_for_preflight=True)
        if n == "lock_screen" else None))
    monkeypatch.setattr("core.tool_catalog.get_catalog", lambda: catalog)
    lex = LexicalRouter()
    lex.build_index({"lock_screen": {}})

    store = IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))
    mem = _Mem()
    tools = {n: {} for n in ["lock_screen", "set_brightness", "get_battery"]}
    router = SimpleNamespace(
        lexical_router=lex,
        embedding_router=_EmbedStub(confirm_for="show me the thingy please"),
        _tools_by_name=tools,
        enable_llm_tool_routing=False,
    )
    cfg = SimpleNamespace(get=lambda k, d=None: d if d is not None else True)
    app = SimpleNamespace(
        session_id="s1",
        intent_learning_store=store,
        capability_registry=_Registry(),
        consent_service=_Consent(),
        memory_service=mem,
        router=router,
        config=cfg,
        assistant_context=None,
        workflow_orchestrator=None,
        intent_recognizer=None,
        route_scorer=None,
        turn_feedback=None,
        dialogue_manager=None,
        _active_turn_record=None,
    )
    broker = CapabilityBroker(app)
    planner = PlannerEngine(broker)
    return planner, broker, store, mem


def test_step4a_learned_dispatch_fires_in_pipeline(live):
    planner, broker, store, mem = live
    phrase = "make the screen cozy"
    for _ in range(PROMOTE_AFTER):
        store.note_hit(phrase, "set_brightness")
    ctx = SimpleNamespace(turn_id="t1", source="user", style_hint="")
    plan = planner.plan(phrase, ctx=ctx)
    assert plan.mode == "tool"
    assert plan.steps[0].capability_name == "set_brightness"
    assert plan.route_origin == "learned"


def test_step4b_lexical_fires_and_captures(live):
    planner, broker, store, mem = live
    ctx = SimpleNamespace(turn_id="t2", source="user", style_hint="")
    plan = planner.plan("lock the screem", ctx=ctx)  # typo near-miss
    assert plan.mode == "tool"
    assert plan.steps[0].capability_name == "lock_screen"
    assert plan.route_origin == "lexical"
    # Capture-at-source landed in the store (drives future promotion).
    assert store.get_phrase("lock the screem", "lock_screen")["hit_count"] == 1


def test_step5b_confirmation_fires_then_resolves(live):
    planner, broker, store, mem = live
    ctx = SimpleNamespace(turn_id="t3", source="user", style_hint="")
    plan = planner.plan("show me the thingy please", ctx=ctx)
    assert plan.mode == "clarify"
    assert plan.requires_confirmation
    assert mem.state["pending_intent"]["tool_name"] == "get_battery"

    # Next turn: "yes" resolves via the broker's pending-confirmation path.
    resolved = broker.check_pending_confirmation("yes", "t4")
    assert resolved is not None and resolved.mode == "tool"
    assert resolved.steps[0].capability_name == "get_battery"
    assert store.get_phrase("show me the thingy please", "get_battery")["hit_count"] == 1


def test_master_switch_disables_learned_dispatch(live, monkeypatch):
    planner, broker, store, mem = live
    # Promote a phrase, then flip the master learning switch off.
    for _ in range(PROMOTE_AFTER):
        store.note_hit("make the screen cozy", "set_brightness")
    broker.app.config = SimpleNamespace(
        get=lambda k, d=None: False if k == "routing.learning_enabled" else (d if d is not None else True))
    ctx = SimpleNamespace(turn_id="t5", source="user", style_hint="")
    plan = planner.plan("make the screen cozy", ctx=ctx)
    # No learned dispatch — falls through to the chat fallback instead.
    assert plan.route_origin != "learned"
