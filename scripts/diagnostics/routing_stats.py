#!/usr/bin/env python3
"""Routing observability — summarize the `[ROUTE]` decision log.

Every turn, the orchestrator emits one structured line
(`core/planning/turn_orchestrator.py`):

    [ROUTE] source=intent tool=set_brightness mode= intent_conf=1.00 elapsed_ms=12

This read-only tool aggregates those lines into the numbers you actually want in
production: the **routing source distribution** (how often the fast deterministic
path wins vs. falling through to the LLM planner), the **fallback rate**, the
**per-tool frequency**, and **latency percentiles**. It never touches the hot
path — point it at a log file after the fact.

    python scripts/diagnostics/routing_stats.py                 # logs/friday.log
    python scripts/diagnostics/routing_stats.py path/to/run.log
    python scripts/diagnostics/routing_stats.py --top 15
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_LOG = os.path.join(_PROJECT_ROOT, "logs", "friday.log")

# Fast path that wins without the LLM planner; everything else is a "fallback".
_FAST_SOURCES = {"intent", "deterministic"}

_ROUTE_RE = re.compile(
    r"\[ROUTE\]\s+source=(?P<source>\S+)\s+tool=(?P<tool>\S*)\s+mode=(?P<mode>\S*)\s+"
    r"intent_conf=(?P<conf>[\d.]+)\s+elapsed_ms=(?P<elapsed>[\d.]+)"
)


def parse_routes(lines):
    """Yield dicts for each `[ROUTE]` line in an iterable of log lines."""
    for line in lines:
        m = _ROUTE_RE.search(line)
        if not m:
            continue
        d = m.groupdict()
        yield {
            "source": d["source"],
            "tool": d["tool"] or "(none)",
            "mode": d["mode"] or "",
            "conf": float(d["conf"]),
            "elapsed": float(d["elapsed"]),
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def summarize(routes: list[dict]) -> dict:
    total = len(routes)
    sources: dict[str, int] = {}
    tools: dict[str, int] = {}
    elapsed: list[float] = []
    confs: list[float] = []
    fallback = 0
    for r in routes:
        sources[r["source"]] = sources.get(r["source"], 0) + 1
        tools[r["tool"]] = tools.get(r["tool"], 0) + 1
        elapsed.append(r["elapsed"])
        confs.append(r["conf"])
        if r["source"] not in _FAST_SOURCES:
            fallback += 1
    return {
        "total": total,
        "sources": sources,
        "tools": tools,
        "fallback_rate": (fallback / total) if total else 0.0,
        "p50_ms": _percentile(elapsed, 50),
        "p95_ms": _percentile(elapsed, 95),
        "avg_conf": (sum(confs) / len(confs)) if confs else 0.0,
    }


def print_summary(stats: dict, top: int = 10) -> None:
    total = stats["total"]
    print(f"\nRouting stats — {total} turn(s)\n")
    if not total:
        print("  no [ROUTE] lines found.")
        return
    print("Source distribution:")
    for source, n in sorted(stats["sources"].items(), key=lambda kv: -kv[1]):
        print(f"  {source:<14} {n:>6}  {100.0 * n / total:5.1f}%")
    print(f"\nFallback rate (LLM planner/chat): {100.0 * stats['fallback_rate']:.1f}%")
    print(f"Latency: p50={stats['p50_ms']:.0f}ms  p95={stats['p95_ms']:.0f}ms")
    print(f"Avg intent confidence: {stats['avg_conf']:.2f}")
    print(f"\nTop {top} tools:")
    for tool, n in sorted(stats["tools"].items(), key=lambda kv: -kv[1])[:top]:
        print(f"  {tool:<28} {n:>6}  {100.0 * n / total:5.1f}%")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Summarize FRIDAY routing decisions")
    parser.add_argument("logfile", nargs="?", default=_DEFAULT_LOG, help="path to a log file")
    parser.add_argument("--top", type=int, default=10, help="how many tools to list")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.logfile):
        print(f"log file not found: {args.logfile}", file=sys.stderr)
        return 2
    with open(args.logfile, encoding="utf-8", errors="replace") as fh:
        routes = list(parse_routes(fh))
    print_summary(summarize(routes), top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
