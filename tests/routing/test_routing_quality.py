"""Routing-quality eval harness — Adaptive Intent Recognition (Phase 1).

A labelled (utterance -> expected tool) set, routed through the real
:class:`core.embedding_router.EmbeddingRouter` over the curated
`data/tool_catalog.yaml` phrases. Reports top-1 accuracy and miss rate so a
catalog edit, embedder swap, or threshold change can't silently regress how
well FRIDAY catches paraphrased intent.

Run standalone for a metrics dump (and a per-case breakdown of misses):

    .venv/bin/python3 tests/routing/test_routing_quality.py

The thresholds are deliberately conservative — they assert the embedding
tier is doing real semantic routing (paraphrases land), not a specific
model's exact numbers, so a model swap that stays good still passes.
"""
from __future__ import annotations

import os

import pytest

from core.embedding_router import EmbeddingRouter
from core.memory.embeddings import SentenceTransformerEmbedder, get_shared_embedder
from core.tool_catalog import get_catalog


EVAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "routing_eval.yaml",
)

# Regression floors, set below the measured baseline (96.4% top-1 / 0% miss
# after the 2026-05-25 catalog expansion) to leave authoring headroom while
# catching a real backslide. Ratchet UP as the catalog grows; tune downward
# only with a recorded reason in docs/testing_guide.md.
MIN_TOP1_ACCURACY = 0.85
MAX_MISS_RATE = 0.10


def _has_real_embedder() -> bool:
    return isinstance(get_shared_embedder(), SentenceTransformerEmbedder)


def _load_cases() -> list[tuple[str, str]]:
    import yaml  # noqa: PLC0415

    with open(EVAL_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [(c["say"], c["tool"]) for c in data.get("cases", []) if c.get("say")]


def _build_router() -> EmbeddingRouter:
    """Index every catalog tool (empty blocklist) so the harness measures
    the catalog's raw separability, independent of the runtime safety
    blocklist that suppresses empty-arg dispatch in production."""
    catalog = get_catalog()
    tools_by_name = {name: {"spec": {"name": name}} for name in catalog.names()}
    router = EmbeddingRouter(blocklist=frozenset())
    router.build_index(tools_by_name)
    return router


def _score_cases(router: EmbeddingRouter, cases):
    hits, misses, wrong = 0, 0, []
    for say, expected in cases:
        result = router.route(say)
        if result is None:
            misses += 1
            wrong.append((say, expected, "<miss>", 0.0))
        elif result["tool"] == expected:
            hits += 1
        else:
            wrong.append((say, expected, result["tool"], result["score"]))
    return hits, misses, wrong


@pytest.mark.skipif(not _has_real_embedder(),
                    reason="needs sentence-transformers; hash-embedder fallback can't route")
def test_routing_top1_accuracy():
    cases = _load_cases()
    assert cases, "routing_eval.yaml has no cases"
    router = _build_router()
    hits, misses, wrong = _score_cases(router, cases)
    total = len(cases)
    accuracy = hits / total
    miss_rate = misses / total
    detail = "\n".join(
        f"  {say!r} -> got {got!r} ({score:.2f}), expected {exp!r}"
        for say, exp, got, score in wrong
    )
    assert accuracy >= MIN_TOP1_ACCURACY, (
        f"top-1 accuracy {accuracy:.2%} < {MIN_TOP1_ACCURACY:.0%}\n{detail}"
    )
    assert miss_rate <= MAX_MISS_RATE, (
        f"miss rate {miss_rate:.2%} > {MAX_MISS_RATE:.0%}\n{detail}"
    )


def _report():
    if not _has_real_embedder():
        print("sentence-transformers unavailable — cannot run routing eval.")
        return
    cases = _load_cases()
    router = _build_router()
    hits, misses, wrong = _score_cases(router, cases)
    total = len(cases)
    print(f"\nRouting eval: {hits}/{total} top-1 "
          f"({hits / total:.1%}), {misses} misses ({misses / total:.1%})")
    if wrong:
        print("Mismatches / misses:")
        for say, exp, got, score in wrong:
            print(f"  {say!r} -> {got!r} ({score:.2f}), expected {exp!r}")


if __name__ == "__main__":
    _report()
