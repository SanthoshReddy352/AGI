"""Routing threshold tuner — Adaptive Intent Recognition (Phase 6).

Phases 1-5 picked thresholds by hand (`DISPATCH_THRESHOLD=0.62`,
`CONFIRM_LOW=0.50`, `LEXICAL_THRESHOLD=88`, `TIE_EPSILON=0.05`,
`PROMOTE_AFTER=3`). This module replaces guesses with data: it sweeps a
score threshold over a labelled case set and reports, per threshold,
accuracy / false-dispatch / defer rates so we can pick the operating point
that maximises coverage while bounding wrong dispatches.

Case sources:
  * `cases_from_eval()`  — the static paraphrase set `data/routing_eval.yaml`.
  * `cases_from_learned(store)` — the user's own confirmed phrasings from the
    IntentLearningStore (weighted by hit_count). This is what makes the tuning
    *adaptive*: the operating point can be re-derived from how THIS user talks.

The sweep is generic over a `score_fn(text) -> {"tool", "score"} | None`, so it
tunes the embedding dispatch band today and the lexical ratio tomorrow with the
same machinery.

CLI (metrics dump + recommendation):

    .venv/bin/python3 -m core.routing_tuner
"""
from __future__ import annotations

import os
from typing import Callable, Iterable


Case = tuple[str, str, float]  # (text, expected_tool, weight)


def _norm_cases(cases: Iterable) -> list[Case]:
    out: list[Case] = []
    for c in cases:
        if len(c) == 2:
            text, expected = c
            weight = 1.0
        else:
            text, expected, weight = c
        if text and expected:
            out.append((text, expected, float(weight)))
    return out


def cases_from_eval(path: str | None = None) -> list[Case]:
    import yaml  # noqa: PLC0415

    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "routing_eval.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [(c["say"], c["tool"], 1.0) for c in data.get("cases", []) if c.get("say")]


def cases_from_learned(store) -> list[Case]:
    """Positive cases from the user's non-blocked learned phrasings, weighted
    by how often they were confirmed."""
    try:
        rows = store.active_phrases()
    except Exception:
        return []
    out: list[Case] = []
    for r in rows:
        text = r.get("raw") or r.get("normalized") or ""
        tool = r.get("tool") or ""
        if text and tool:
            out.append((text, tool, float(max(1, int(r.get("hit_count", 1))))))
    return out


def sweep_threshold(score_fn: Callable[[str], dict | None], cases: Iterable,
                    lo: float = 0.40, hi: float = 0.80,
                    step: float = 0.02) -> list[dict]:
    """For each threshold in [lo, hi], classify every case as correct /
    false-dispatch / deferred and return weighted rates. Scores are computed
    once per case, so the sweep itself is cheap."""
    norm = _norm_cases(cases)
    scored = []
    for text, expected, weight in norm:
        try:
            r = score_fn(text)
        except Exception:
            r = None
        scored.append((expected, weight,
                       (r["tool"], float(r["score"])) if r else None))

    results: list[dict] = []
    t = lo
    while t <= hi + 1e-9:
        correct = wrong = deferred = 0.0
        for expected, weight, sc in scored:
            if sc is None or sc[1] < t:
                deferred += weight
            elif sc[0] == expected:
                correct += weight
            else:
                wrong += weight
        total = correct + wrong + deferred
        dispatched = correct + wrong
        results.append({
            "threshold": round(t, 4),
            "accuracy": correct / total if total else 0.0,
            "false_dispatch_rate": wrong / total if total else 0.0,
            "defer_rate": deferred / total if total else 0.0,
            "precision": correct / dispatched if dispatched else 0.0,
        })
        t += step
    return results


def recommend_threshold(results: list[dict], max_false_rate: float = 0.02) -> float:
    """Lowest threshold whose false-dispatch rate is within budget (maximises
    coverage while bounding wrong dispatches). Falls back to the most precise
    operating point when nothing meets the budget."""
    if not results:
        return 0.0
    eligible = [r for r in results if r["false_dispatch_rate"] <= max_false_rate]
    if eligible:
        return min(eligible, key=lambda r: r["threshold"])["threshold"]
    return max(results, key=lambda r: (r["precision"], -r["threshold"]))["threshold"]


def recommend_max_accuracy(results: list[dict]) -> float:
    """Highest threshold that still achieves the sweep's peak accuracy — the
    top of the coverage plateau. Lower values on the plateau are equivalent on
    this data, so the highest is the most discriminating safe choice."""
    if not results:
        return 0.0
    peak = max(r["accuracy"] for r in results)
    plateau = [r for r in results if r["accuracy"] >= peak - 1e-9]
    return max(plateau, key=lambda r: r["threshold"])["threshold"]


def on_accuracy_plateau(results: list[dict], threshold: float,
                        tol: float = 1e-9) -> bool:
    """True iff ``threshold`` achieves the sweep's peak accuracy — i.e. the
    current operating point is not leaving correct dispatches on the table."""
    if not results:
        return False
    peak = max(r["accuracy"] for r in results)
    here = min((r for r in results), key=lambda r: abs(r["threshold"] - threshold))
    return here["accuracy"] >= peak - tol


def band_precision(score_fn: Callable[[str], dict | None], cases: Iterable,
                   lo: float, hi: float) -> dict:
    """Precision of matches whose score lands in the confirmation band
    [lo, hi). Informs CONFIRM_LOW: below the point where band precision drops
    too far, asking 'did you mean…?' is no better than guessing."""
    correct = wrong = 0.0
    for text, expected, weight in _norm_cases(cases):
        try:
            r = score_fn(text)
        except Exception:
            r = None
        if r is None or not (lo <= float(r["score"]) < hi):
            continue
        if r["tool"] == expected:
            correct += weight
        else:
            wrong += weight
    n = correct + wrong
    return {"band": (lo, hi), "in_band": n,
            "precision": correct / n if n else 0.0}


def recommend_promotion_n(store, default: int = 3) -> int:
    """Smallest N such that no phrasing that was ever corrected would have
    auto-promoted before its first correction. Conservative: keeps a phrasing
    the user pushed back on from auto-dispatching too eagerly."""
    try:
        rows = store.active_phrases() + [
            p for p in _safe_blocked(store)
        ]
    except Exception:
        return default
    risky = [int(r.get("hit_count", 0)) for r in rows
             if int(r.get("corrected_count", 0)) > 0]
    if not risky:
        return default
    return max(default, max(risky) + 1)


def _safe_blocked(store) -> list[dict]:
    try:
        with store._connect() as conn:  # noqa: SLF001 - tuner is store-aware
            import sqlite3  # noqa: PLC0415
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM learned_phrases WHERE status='blocked'")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CLI report
# ---------------------------------------------------------------------------

def _report():
    from core.embedding_router import CONFIRM_LOW, DISPATCH_THRESHOLD, EmbeddingRouter
    from core.memory.embeddings import SentenceTransformerEmbedder, get_shared_embedder
    from core.tool_catalog import get_catalog

    if not isinstance(get_shared_embedder(), SentenceTransformerEmbedder):
        print("sentence-transformers unavailable — cannot tune.")
        return

    catalog = get_catalog()
    router = EmbeddingRouter(blocklist=frozenset())
    router.build_index({n: {"spec": {"name": n}} for n in catalog.names()})

    cases = cases_from_eval()
    results = sweep_threshold(router.best_match, cases)
    print(f"\nThreshold sweep over {len(cases)} labelled cases:")
    print(f"{'thr':>5} {'acc':>7} {'false':>7} {'defer':>7} {'prec':>7}")
    for r in results:
        print(f"{r['threshold']:>5.2f} {r['accuracy']:>7.1%} "
              f"{r['false_dispatch_rate']:>7.1%} {r['defer_rate']:>7.1%} "
              f"{r['precision']:>7.1%}")

    rec = recommend_threshold(results)
    plateau_top = recommend_max_accuracy(results)
    band = band_precision(router.best_match, cases, CONFIRM_LOW, DISPATCH_THRESHOLD)
    print(f"\nCurrent DISPATCH_THRESHOLD = {DISPATCH_THRESHOLD:.2f} "
          f"(on accuracy plateau: {on_accuracy_plateau(results, DISPATCH_THRESHOLD)})")
    print(f"Coverage-max (false-dispatch ≤ 2%) = {rec:.2f}")
    print(f"Accuracy-plateau top              = {plateau_top:.2f}")
    print(f"Confirmation band [{CONFIRM_LOW:.2f}, {DISPATCH_THRESHOLD:.2f}): "
          f"{band['in_band']:.0f} cases, precision {band['precision']:.1%} "
          f"(0 ⇒ no good paraphrase lands in-band; needs real routing_observations to tune)")


if __name__ == "__main__":
    _report()
