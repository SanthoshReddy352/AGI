"""Adaptive Intent Recognition Phase 5 — profile biasing + user controls.

Covers: favourite-arg capture/retrieval + the broker's preference-only
arg-default fill, the profile tie-breaker in the embedding router, and the
master `routing.learning_enabled` privacy switch.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

from core.capability_broker import CapabilityBroker
from core.embedding_router import TIE_EPSILON, EmbeddingRouter
from core.stores.intent_learning_store import IntentLearningStore


@pytest.fixture()
def store(tmp_path):
    return IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))


# ---------------------------------------------------------------------------
# Favourite args
# ---------------------------------------------------------------------------

def test_favorite_args_tracks_most_common(store):
    store.record_args("play_music", {"app": "spotify"})
    store.record_args("play_music", {"app": "spotify"})
    store.record_args("play_music", {"app": "youtube"})
    assert store.favorite_args("play_music")["app"] == "spotify"


def test_record_args_ignores_long_and_nonscalar(store):
    store.record_args("t", {"query": "x" * 200, "ok": True, "obj": {"a": 1}})
    favs = store.favorite_args("t")
    assert "query" not in favs and "obj" not in favs
    assert favs["ok"] == "True"


def test_profile_score_rewards_frequency(store):
    store.bump_profile("a", hour=10)
    store.bump_profile("a", hour=10)
    store.bump_profile("b", hour=10)
    assert store.profile_score("a", hour=10) > store.profile_score("b", hour=10)
    assert store.profile_score("never_used", hour=10) == 0.0


# ---------------------------------------------------------------------------
# Broker arg-default fill (preference keys only, missing only)
# ---------------------------------------------------------------------------

def _broker(tmp_path, learning=True):
    store = IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))
    cfg = SimpleNamespace(get=lambda k, d=None: learning if k == "routing.learning_enabled" else d)
    app = SimpleNamespace(intent_learning_store=store, config=cfg)
    return CapabilityBroker(app), store


def test_arg_defaults_fill_missing_preference(tmp_path):
    broker, store = _broker(tmp_path)
    store.record_args("play_music", {"app": "spotify"})
    out = broker._apply_arg_defaults("play_music", {})
    assert out["app"] == "spotify"


def test_arg_defaults_never_override_explicit(tmp_path):
    broker, store = _broker(tmp_path)
    store.record_args("play_music", {"app": "spotify"})
    out = broker._apply_arg_defaults("play_music", {"app": "youtube"})
    assert out["app"] == "youtube"  # explicit wins


def test_arg_defaults_skip_content_args(tmp_path):
    broker, store = _broker(tmp_path)
    store.record_args("search", {"query": "cats"})
    out = broker._apply_arg_defaults("search", {})
    assert "query" not in out  # query is not a preference key


def test_arg_defaults_off_when_learning_disabled(tmp_path):
    broker, store = _broker(tmp_path, learning=False)
    store.record_args("play_music", {"app": "spotify"})
    assert broker._apply_arg_defaults("play_music", {}) == {}


# ---------------------------------------------------------------------------
# Embedding router tie-breaker
# ---------------------------------------------------------------------------

class _FakeModel:
    """Fixed unit vectors engineering (a) a symmetric near-tie query and
    (b) a clear-winner query, so the tie-breaker's epsilon gate is exercised."""

    _VEC = {
        "alpha": np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float32),  # tool_a phrase
        "beta": np.array([1.0, 0.0, 1.0, 0.0], dtype=np.float32),   # tool_b phrase
        "tie q": np.array([1.0, 0.5, 0.5, 0.0], dtype=np.float32),  # equidistant
        "clear a": np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float32),  # == alpha
    }

    def encode(self, phrases, **kw):
        out = []
        for p in phrases:
            v = self._VEC.get(p, np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)).copy()
            v = v / (float(np.linalg.norm(v)) or 1.0)
            out.append(v)
        return np.array(out, dtype=np.float32)


@pytest.fixture()
def tie_router(monkeypatch):
    monkeypatch.setattr("core.tool_catalog.get_catalog",
                        lambda: SimpleNamespace(entry_for=lambda n: None))
    r = EmbeddingRouter(dispatch_threshold=0.4)
    r._get_model = lambda: _FakeModel()  # type: ignore[method-assign]
    tools = {
        "tool_a": {"spec": {"name": "tool_a", "description": "alpha"}},
        "tool_b": {"spec": {"name": "tool_b", "description": "beta"}},
    }
    r.build_index(tools)
    return r


def test_tie_breaker_picks_preferred_among_close(tie_router):
    base = tie_router.best_match("tie q")
    assert base["tool"] in {"tool_a", "tool_b"}

    # Inject a tie-breaker that prefers tool_b; the two are within TIE_EPSILON.
    tie_router.set_tie_breaker(lambda cands: "tool_b")
    assert tie_router.best_match("tie q")["tool"] == "tool_b"


def test_tie_breaker_ignored_when_not_close(tie_router):
    # "clear a" == tool_a's phrase (cos 1.0) vs tool_b (cos 0.5) — far past
    # epsilon, so the tie-breaker must not override the cosine winner.
    tie_router.set_tie_breaker(lambda cands: "tool_b")
    assert tie_router.best_match("clear a")["tool"] == "tool_a"


def test_tie_breaker_none_keeps_cosine_winner(tie_router):
    tie_router.set_tie_breaker(lambda cands: None)
    assert tie_router.best_match("tie q")["tool"] in {"tool_a", "tool_b"}
