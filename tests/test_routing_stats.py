"""Tests for the routing-stats log analyzer (scripts/diagnostics/routing_stats.py)."""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_PROJECT_ROOT, "scripts", "diagnostics")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import routing_stats  # noqa: E402


_SAMPLE = [
    "2026-05-30 12:00:00 INFO [ROUTE] source=intent tool=set_brightness mode= intent_conf=1.00 elapsed_ms=12",
    "2026-05-30 12:00:01 INFO [ROUTE] source=intent tool=get_time mode= intent_conf=1.00 elapsed_ms=8",
    "2026-05-30 12:00:02 INFO [ROUTE] source=planner tool=research_topic mode=plan intent_conf=0.00 elapsed_ms=240",
    "2026-05-30 12:00:03 INFO [ROUTE] source=chat tool= mode=chat intent_conf=0.00 elapsed_ms=300",
    "some unrelated log line that should be ignored",
]


def test_parse_routes_ignores_non_route_lines():
    routes = list(routing_stats.parse_routes(_SAMPLE))
    assert len(routes) == 4
    assert routes[0]["source"] == "intent"
    assert routes[0]["tool"] == "set_brightness"
    assert routes[3]["tool"] == "(none)"


def test_summary_source_distribution_and_fallback():
    stats = routing_stats.summarize(list(routing_stats.parse_routes(_SAMPLE)))
    assert stats["total"] == 4
    assert stats["sources"]["intent"] == 2
    # planner + chat are fallbacks (2 of 4).
    assert stats["fallback_rate"] == 0.5
    assert stats["tools"]["set_brightness"] == 1


def test_summary_latency_percentiles():
    stats = routing_stats.summarize(list(routing_stats.parse_routes(_SAMPLE)))
    assert stats["p50_ms"] >= 0
    assert stats["p95_ms"] >= stats["p50_ms"]


def test_summary_handles_empty():
    stats = routing_stats.summarize([])
    assert stats["total"] == 0
    assert stats["fallback_rate"] == 0.0
