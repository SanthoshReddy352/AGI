"""Structured per-turn spans — Track 0.4 of FRIDAY Consolidation Direction.

Six checkpoints emit a span each turn. Their sum approximates `duration_ms`
to within ±5%, which lets us answer "why was turn X slow?" without ad-hoc
instrumentation per investigation.

The span recorder is attached to the per-turn `ctx.spans` list (or attribute
of equivalent name) by the orchestrator. If no ctx is available (test rigs
that bypass TurnManager), the Span context manager degrades to a no-op so
no caller has to thread None-checks through its code.

Naming the six checkpoints (in order):
    1. context_built       — MemoryBroker bundle (becomes context_resolved
                              once Track 1.4 ContextResolver replaces this
                              step; same span name for continuity).
    2. intent_classified   — IntentEngine.classify
    3. plan_built          — PlannerEngine.plan
    4. plan_validated      — PlanValidator + PlanRepair
    5. tool_executed       — execute() around the chosen path
    6. response_finalized  — final assembly into TurnResponse

Removing or renaming a checkpoint must be paired with a cross-turn test
update, since dashboards and consolidation regression checks key off these
names.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


CHECKPOINTS = (
    "context_built",
    "intent_classified",
    "plan_built",
    "plan_validated",
    "tool_executed",
    "response_finalized",
)


@dataclass
class SpanRecord:
    name: str
    duration_ms: float


@dataclass
class SpanRecorder:
    """Per-turn collector of span timings.

    Spans are appended in the order they close, which (because they don't
    overlap in the single-threaded turn pipeline) matches the named order
    above. Total is summed lazily so partial recordings stay valid even if
    the turn raised partway through.
    """

    spans: list[SpanRecord] = field(default_factory=list)

    def mark(self, name: str, duration_ms: float) -> None:
        self.spans.append(SpanRecord(name=name, duration_ms=round(duration_ms, 3)))

    def total_ms(self) -> float:
        return sum(s.duration_ms for s in self.spans)

    def as_list(self) -> list[dict]:
        """Plain list of dicts — convenient for logging / metrics."""
        return [{"name": s.name, "duration_ms": s.duration_ms} for s in self.spans]


class Span:
    """Context manager that records its wall-clock duration into a recorder.

    Usage:

        with Span(ctx, "intent_classified"):
            intent = self._intent.classify(text)

    If `ctx` doesn't carry a recorder (None / missing attr), the span is a
    no-op so the orchestrator stays trivially callable from unit tests.
    """

    __slots__ = ("_recorder", "_name", "_t0")

    def __init__(self, ctx, name: str):
        self._recorder = _resolve_recorder(ctx)
        self._name = name
        self._t0 = 0.0

    def __enter__(self) -> "Span":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._recorder is None:
            return
        self._recorder.mark(self._name, (time.monotonic() - self._t0) * 1000.0)


def attach_recorder(ctx) -> SpanRecorder | None:
    """Attach a fresh recorder to `ctx.spans` if possible. Returns the
    recorder so the orchestrator can read totals after the turn.

    If `ctx` is None or read-only (frozen dataclass without `spans` field),
    returns None and span recording silently skips.
    """
    if ctx is None:
        return None
    rec = SpanRecorder()
    try:
        ctx.spans = rec
    except (AttributeError, TypeError):
        return None
    return rec


def _resolve_recorder(ctx) -> SpanRecorder | None:
    if ctx is None:
        return None
    rec = getattr(ctx, "spans", None)
    if isinstance(rec, SpanRecorder):
        return rec
    return None
