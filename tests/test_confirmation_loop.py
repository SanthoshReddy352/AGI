"""Adaptive Intent Recognition Phase 2 — mid-band confirmation loop.

Covers two layers:

* `EmbeddingRouter.confirm_candidate` — fires only in the band
  [confirm_low, dispatch_threshold), and never for a tool that can't be
  dispatched with empty args.
* `CapabilityBroker` pending-intent machinery — propose → "did you mean …?"
  → yes dispatches the tool *and* records the learning hit; → no records a
  correction and never dispatches. This is the cross-turn learning signal.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from core.capability_broker import CapabilityBroker
from core.embedding_router import CONFIRM_LOW, DISPATCH_THRESHOLD, EmbeddingRouter
from core.stores.intent_learning_store import IntentLearningStore


# ---------------------------------------------------------------------------
# EmbeddingRouter.confirm_candidate band logic
# ---------------------------------------------------------------------------

def _router_with_best(score, tool="zz_not_in_catalog"):
    # Default tool is absent from the catalog, so entry_for() returns None and
    # the preflight-safety filter is a no-op — these cases isolate band logic.
    router = EmbeddingRouter()
    router.best_match = lambda text: {"tool": tool, "score": score}
    return router


def test_confirm_candidate_fires_inside_band():
    mid = (CONFIRM_LOW + DISPATCH_THRESHOLD) / 2
    router = _router_with_best(mid)
    cand = router.confirm_candidate("make the display dimmer maybe")
    assert cand is not None
    assert cand["tool"] == "zz_not_in_catalog"


def test_confirm_candidate_silent_above_dispatch_threshold():
    # At/above the dispatch threshold the router would auto-dispatch, not ask.
    router = _router_with_best(DISPATCH_THRESHOLD + 0.05)
    assert router.confirm_candidate("set brightness to fifty") is None


def test_confirm_candidate_silent_below_confirm_low():
    # Below the floor it's noise — don't even ask.
    router = _router_with_best(CONFIRM_LOW - 0.05)
    assert router.confirm_candidate("what's the meaning of life") is None


def test_confirm_candidate_skips_unsafe_for_empty_args(monkeypatch):
    """A tool flagged blocked_from_chat_preflight can't run on empty args, so
    we must not offer to confirm it (the dispatch would dead-end)."""
    mid = (CONFIRM_LOW + DISPATCH_THRESHOLD) / 2
    router = _router_with_best(mid, tool="set_volume")
    entry = SimpleNamespace(is_safe_for_preflight=False)
    monkeypatch.setattr(
        "core.tool_catalog.get_catalog",
        lambda: SimpleNamespace(entry_for=lambda name: entry),
    )
    assert router.confirm_candidate("turn it up a bit") is None


# ---------------------------------------------------------------------------
# Broker pending-intent machinery (cross-turn confirmation + learning)
# ---------------------------------------------------------------------------

class _FakeConsent:
    @staticmethod
    def is_negative_confirmation(text):
        return text.strip().lower() in {"no", "nope", "nah", "no thanks"}

    @staticmethod
    def is_positive_confirmation(text):
        t = text.strip().lower()
        return t in {"yes", "yeah", "yep", "sure", "ok", "okay"}


class _FakeRegistry:
    def get_descriptor(self, name):
        if not name:
            return None
        return SimpleNamespace(
            side_effect_level="read", connectivity="local",
            latency_class="interactive",
        )


def _build_broker(tmp_path):
    store = IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))
    # Tiny in-memory session-state surface mirroring MemoryService's API.
    state = {}

    class _Mem:
        def get_session_state(self, sid):
            return dict(state)

        def set_pending_intent(self, sid, payload):
            state["pending_intent"] = dict(payload or {})

        def clear_pending_intent(self, sid):
            state["pending_intent"] = {}

    app = SimpleNamespace(
        session_id="s1",
        memory_service=_Mem(),
        consent_service=_FakeConsent(),
        capability_registry=_FakeRegistry(),
        intent_learning_store=store,
        config=None,
    )
    return CapabilityBroker(app), store, state


def test_propose_then_yes_dispatches_and_records_hit(tmp_path):
    broker, store, state = _build_broker(tmp_path)
    # Turn 1: propose a confirmation for an ambiguous phrasing.
    plan = broker._propose_intent_confirmation(
        "set_brightness", "make the screen softer", "t1", "", 0.55
    )
    assert plan.mode == "clarify"
    assert plan.requires_confirmation
    assert state["pending_intent"]["tool_name"] == "set_brightness"

    # Turn 2: "yes" → dispatch the tool + learn the phrasing.
    resolved = broker._plan_pending_intent("yes", "t2", "")
    assert resolved is not None
    assert resolved.mode == "tool"
    assert resolved.steps[0].capability_name == "set_brightness"
    assert not state["pending_intent"]  # cleared

    phrase = store.get_phrase("make the screen softer", "set_brightness")
    assert phrase is not None
    assert phrase["hit_count"] == 1
    assert store.top_tools()[0]["tool"] == "set_brightness"


def test_propose_then_no_records_correction_no_dispatch(tmp_path):
    broker, store, state = _build_broker(tmp_path)
    broker._propose_intent_confirmation(
        "set_brightness", "make the screen softer", "t1", "", 0.55
    )
    resolved = broker._plan_pending_intent("no", "t2", "")
    assert resolved is not None
    assert resolved.mode == "clarify"  # not a tool dispatch
    assert not state["pending_intent"]

    phrase = store.get_phrase("make the screen softer", "set_brightness")
    assert phrase is not None
    assert phrase["corrected_count"] == 1
    assert phrase["status"] == "blocked"


def test_no_pending_intent_passes_through(tmp_path):
    broker, store, state = _build_broker(tmp_path)
    # "yes" with nothing pending must not resolve to anything.
    assert broker._plan_pending_intent("yes", "t1", "") is None


def test_non_confirmation_text_does_not_resolve_pending(tmp_path):
    broker, store, state = _build_broker(tmp_path)
    broker._propose_intent_confirmation(
        "set_brightness", "make the screen softer", "t1", "", 0.55
    )
    # A fresh unrelated utterance is neither yes nor no — leave the pending
    # entry alone so routing can handle the new text normally.
    assert broker._plan_pending_intent("what time is it", "t2", "") is None
    assert state["pending_intent"]["tool_name"] == "set_brightness"


def test_expired_pending_intent_is_dropped(tmp_path):
    broker, store, state = _build_broker(tmp_path)
    broker._propose_intent_confirmation(
        "set_brightness", "make the screen softer", "t1", "", 0.55
    )
    # Backdate the proposal beyond the TTL — a late "yes" must not fire it.
    from datetime import datetime, timedelta
    stale = (datetime.now() - timedelta(seconds=broker._PENDING_INTENT_TTL_S + 5))
    state["pending_intent"]["proposed_at"] = stale.isoformat()
    assert broker._plan_pending_intent("yes", "t2", "") is None
    assert not state["pending_intent"]


def test_check_pending_confirmation_routes_to_intent_when_no_online(tmp_path):
    broker, store, state = _build_broker(tmp_path)
    # No pending_online; add a get/set/clear_pending_online no-op surface.
    broker.app.memory_service.get_session_state = lambda sid: dict(state)
    broker._propose_intent_confirmation(
        "set_brightness", "make the screen softer", "t1", "", 0.55
    )
    resolved = broker.check_pending_confirmation("yes", "t2")
    assert resolved is not None
    assert resolved.mode == "tool"
    assert resolved.steps[0].capability_name == "set_brightness"
