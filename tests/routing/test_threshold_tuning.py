"""Routing threshold tuner — Adaptive Intent Recognition (Phase 6).

Two layers:
  * Unit tests of the sweep / recommendation math with a deterministic fake
    scorer — run on any interpreter, no embedder needed.
  * An integration test (skipped without sentence-transformers) that runs the
    real sweep over `data/routing_eval.yaml` and asserts the shipped
    `DISPATCH_THRESHOLD` sits on the accuracy plateau — i.e. it's data-validated,
    not leaving correct dispatches on the table.
"""
from __future__ import annotations

import os

import pytest

from core.routing_tuner import (
    band_precision,
    cases_from_eval,
    cases_from_learned,
    on_accuracy_plateau,
    recommend_max_accuracy,
    recommend_promotion_n,
    recommend_threshold,
    sweep_threshold,
)


# A scorer where:
#   "good" → tool_a @ 0.90 (correct, high)
#   "mid"  → tool_a @ 0.55 (correct, mid-band)
#   "bad"  → tool_b @ 0.72 (WRONG, high) — a false dispatch until thr > 0.72
def _fake_score(text):
    table = {
        "good": {"tool": "tool_a", "score": 0.90},
        "mid": {"tool": "tool_a", "score": 0.55},
        "bad": {"tool": "tool_b", "score": 0.72},
        "noise": None,
    }
    return table.get(text)


_CASES = [("good", "tool_a"), ("mid", "tool_a"), ("bad", "tool_a"), ("noise", "tool_a")]


def test_sweep_classifies_correct_false_defer():
    results = sweep_threshold(_fake_score, _CASES, lo=0.50, hi=0.95, step=0.05)
    by_thr = {round(r["threshold"], 2): r for r in results}
    # At 0.50: good+mid correct (2/4), bad false (1/4), noise deferred (1/4).
    r50 = by_thr[0.50]
    assert r50["accuracy"] == pytest.approx(0.5)
    assert r50["false_dispatch_rate"] == pytest.approx(0.25)
    assert r50["defer_rate"] == pytest.approx(0.25)
    # At 0.60: mid drops below threshold → deferred; bad still false.
    assert by_thr[0.60]["accuracy"] == pytest.approx(0.25)
    assert by_thr[0.60]["false_dispatch_rate"] == pytest.approx(0.25)
    # At 0.75: bad (0.70) now deferred too → no false dispatches left.
    assert by_thr[0.75]["false_dispatch_rate"] == pytest.approx(0.0)


def test_recommend_threshold_bounds_false_dispatch():
    results = sweep_threshold(_fake_score, _CASES, lo=0.50, hi=0.95, step=0.05)
    # Lowest threshold with false-rate ≤ 0 is just above the bad case's 0.70.
    rec = recommend_threshold(results, max_false_rate=0.0)
    assert rec == pytest.approx(0.75)
    # With a looser budget the 0.70 false case is tolerated → lower threshold.
    rec_loose = recommend_threshold(results, max_false_rate=0.30)
    assert rec_loose <= 0.55


def test_recommend_max_accuracy_and_plateau():
    results = sweep_threshold(_fake_score, _CASES, lo=0.50, hi=0.95, step=0.05)
    # Peak accuracy (0.5) is on the plateau up to 0.55 (good+mid both dispatch).
    assert recommend_max_accuracy(results) == pytest.approx(0.55)
    assert on_accuracy_plateau(results, 0.50)
    assert not on_accuracy_plateau(results, 0.90)


def test_band_precision():
    # Band [0.50, 0.60): only "mid" (0.55, correct) lands here → precision 1.0.
    b = band_precision(_fake_score, _CASES, 0.50, 0.60)
    assert b["in_band"] == pytest.approx(1.0)
    assert b["precision"] == pytest.approx(1.0)


def test_cases_from_learned_weights_by_hits():
    class _Store:
        def active_phrases(self):
            return [
                {"raw": "make it cozy", "tool": "set_brightness", "hit_count": 5},
                {"normalized": "dim screen", "tool": "set_brightness", "hit_count": 0},
            ]
    cases = cases_from_learned(_Store())
    assert ("make it cozy", "set_brightness", 5.0) in cases
    # hit_count 0 floors to weight 1.0, normalized used when raw absent.
    assert ("dim screen", "set_brightness", 1.0) in cases


def test_recommend_promotion_n_guards_corrected_phrases():
    class _Store:
        def active_phrases(self):
            return [{"hit_count": 4, "corrected_count": 1}]  # corrected at 4 hits

        def _connect(self):
            raise RuntimeError("no db in this stub")
    # A phrasing corrected after 4 hits → N must exceed 4 so it can't promote.
    assert recommend_promotion_n(_Store(), default=3) >= 5


# ---------------------------------------------------------------------------
# Integration — real embedder over the shipped eval set
# ---------------------------------------------------------------------------

def _has_real_embedder() -> bool:
    from core.memory.embeddings import SentenceTransformerEmbedder, get_shared_embedder
    return isinstance(get_shared_embedder(), SentenceTransformerEmbedder)


@pytest.mark.skipif(not _has_real_embedder(),
                    reason="needs sentence-transformers")
def test_shipped_dispatch_threshold_is_on_accuracy_plateau():
    from core.embedding_router import DISPATCH_THRESHOLD, EmbeddingRouter
    from core.tool_catalog import get_catalog

    router = EmbeddingRouter(blocklist=frozenset())
    router.build_index({n: {"spec": {"name": n}} for n in get_catalog().names()})
    cases = cases_from_eval()
    results = sweep_threshold(router.best_match, cases, lo=0.40, hi=0.80, step=0.02)
    # The shipped threshold must not be leaving correct dispatches on the table.
    assert on_accuracy_plateau(results, DISPATCH_THRESHOLD), (
        f"DISPATCH_THRESHOLD={DISPATCH_THRESHOLD} is below peak accuracy; "
        "re-tune via `python -m core.routing_tuner`."
    )
