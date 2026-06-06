"""Skill usage stats — in-memory invocation counters (P3.18).

SkillUsage.record(capability_name) is called by the router after each
successful tool invocation. get_counts() exposes counts for display
in memory_admin inspect and any future dashboard.
"""
from __future__ import annotations

from collections import Counter


class SkillUsage:
    def __init__(self) -> None:
        self._counts: Counter = Counter()

    def record(self, capability_name: str) -> None:
        self._counts[capability_name] += 1

    def get(self, capability_name: str) -> int:
        return self._counts[capability_name]

    def get_counts(self) -> dict[str, int]:
        return dict(self._counts.most_common())

    def top(self, n: int = 10) -> list[tuple[str, int]]:
        return self._counts.most_common(n)

    def reset(self) -> None:
        self._counts.clear()

    def summary(self, n: int = 10) -> str:
        top = self.top(n)
        if not top:
            return "No capability invocations recorded."
        lines = [f"  {cap}: {count}x" for cap, count in top]
        return "Top capabilities:\n" + "\n".join(lines)
