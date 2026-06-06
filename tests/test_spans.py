"""Tests for core/planning/spans.py — Track 0.4."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from core.planning.spans import (
    CHECKPOINTS,
    Span,
    SpanRecorder,
    attach_recorder,
)


def test_span_records_duration_into_recorder():
    rec = SpanRecorder()
    ctx = SimpleNamespace(spans=rec)
    with Span(ctx, "intent_classified"):
        time.sleep(0.005)
    assert len(rec.spans) == 1
    assert rec.spans[0].name == "intent_classified"
    assert rec.spans[0].duration_ms >= 5.0
    assert rec.spans[0].duration_ms < 200.0  # generous CI ceiling


def test_span_is_no_op_when_ctx_has_no_recorder():
    ctx = SimpleNamespace()  # no .spans attribute
    with Span(ctx, "intent_classified"):
        time.sleep(0.001)
    assert not hasattr(ctx, "spans")  # never created


def test_span_is_no_op_when_ctx_is_none():
    with Span(None, "intent_classified"):
        time.sleep(0.001)
    # Just must not raise.


def test_attach_recorder_creates_a_fresh_recorder():
    ctx = SimpleNamespace()
    rec = attach_recorder(ctx)
    assert rec is ctx.spans
    assert isinstance(rec, SpanRecorder)
    assert rec.spans == []


def test_attach_recorder_returns_none_for_none_ctx():
    assert attach_recorder(None) is None


def test_recorder_total_ms_sums_all_spans():
    rec = SpanRecorder()
    ctx = SimpleNamespace(spans=rec)
    for name in CHECKPOINTS:
        with Span(ctx, name):
            time.sleep(0.002)
    assert len(rec.spans) == len(CHECKPOINTS)
    assert rec.total_ms() >= 2.0 * len(CHECKPOINTS)


def test_recorder_as_list_returns_plain_dicts():
    rec = SpanRecorder()
    ctx = SimpleNamespace(spans=rec)
    with Span(ctx, "tool_executed"):
        pass
    out = rec.as_list()
    assert out == [{"name": "tool_executed", "duration_ms": pytest.approx(out[0]["duration_ms"], abs=0.01)}]
    assert isinstance(out[0]["duration_ms"], float)


def test_span_exits_cleanly_on_exception_and_still_records():
    rec = SpanRecorder()
    ctx = SimpleNamespace(spans=rec)
    with pytest.raises(RuntimeError):
        with Span(ctx, "plan_built"):
            raise RuntimeError("boom")
    # Span must still have recorded — observability matters most when things
    # fail, so the partial duration is captured.
    assert len(rec.spans) == 1
    assert rec.spans[0].name == "plan_built"


def test_checkpoints_constant_lists_the_six_canonical_names():
    assert set(CHECKPOINTS) == {
        "context_built",
        "intent_classified",
        "plan_built",
        "plan_validated",
        "tool_executed",
        "response_finalized",
    }
