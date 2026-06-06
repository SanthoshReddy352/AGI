"""IntentLearningStore — Adaptive Intent Recognition (Phase 1).

Covers the three tables: routing_observations (measurement), learned_phrases
(hit/correction ledger + auto-promotion at N=3), and intent_profile
(usage aggregates).
"""
from __future__ import annotations

import os

import pytest

from core.stores.intent_learning_store import (
    PROMOTE_AFTER,
    IntentLearningStore,
    normalize_key,
)


@pytest.fixture()
def store(tmp_path):
    return IntentLearningStore(os.path.join(str(tmp_path), "friday.db"))


def test_normalize_key_folds_case_punctuation_and_space():
    assert normalize_key("  Lock   the SCREEN, please! ") == "lock the screen please"
    assert normalize_key("") == ""


def test_record_and_read_observation(store):
    rid = store.record_observation(
        "lock my screen", "lock_screen", "intent",
        turn_id="t1", session_id="s1", plan_mode="action", score=1.0,
    )
    assert rid > 0
    rows = store.recent_observations()
    assert len(rows) == 1
    row = rows[0]
    assert row["chosen_tool"] == "lock_screen"
    assert row["source"] == "intent"
    assert row["normalized"] == "lock my screen"
    assert row["confirmed"] == 0


def test_source_breakdown(store):
    store.record_observation("a", "x", "intent")
    store.record_observation("b", "y", "intent")
    store.record_observation("c", "z", "planner")
    assert store.source_breakdown() == {"intent": 2, "planner": 1}


def test_note_hit_promotes_after_threshold(store):
    phrasings = ["dim the display", "DIM the display!", "  dim the   display "]
    assert len(phrasings) == PROMOTE_AFTER  # guard: test matches the constant
    last = None
    for p in phrasings:
        last = store.note_hit(p, "set_brightness")
    assert last["hit_count"] == PROMOTE_AFTER
    assert last["status"] == "promoted"
    promoted = store.promoted_phrases()
    assert len(promoted) == 1
    assert promoted[0]["tool"] == "set_brightness"


def test_note_hit_below_threshold_stays_candidate(store):
    store.note_hit("open my files", "open_file")
    row = store.get_phrase("open my files", "open_file")
    assert row["hit_count"] == 1
    assert row["status"] == "candidate"
    assert store.promoted_phrases() == []


def test_correction_blocks_and_prevents_promotion(store):
    # Even with enough hits, a correction blocks the pairing.
    for _ in range(PROMOTE_AFTER):
        store.note_hit("read it", "read_file")
    store.note_correction("read it", "read_file")
    row = store.get_phrase("read it", "read_file")
    assert row["status"] == "blocked"
    assert row["corrected_count"] == 1
    assert store.promoted_phrases() == []


def test_forget_all_clears_phrases_but_keeps_observations(store):
    store.record_observation("hello", "greet", "intent")
    store.note_hit("hello there", "greet")
    store.bump_profile("greet")
    removed = store.forget_all()
    assert removed == 1
    assert store.promoted_phrases() == []
    assert store.top_tools() == []
    # observations survive as an audit trail
    assert len(store.recent_observations()) == 1


def test_bump_profile_accumulates_count_and_histogram(store):
    store.bump_profile("get_time", hour=9)
    store.bump_profile("get_time", hour=9)
    store.bump_profile("get_time", hour=14)
    top = store.top_tools()
    assert top[0]["tool"] == "get_time"
    assert top[0]["count"] == 3
    import json
    hist = json.loads(top[0]["hour_histogram"])
    assert hist[9] == 2
    assert hist[14] == 1
