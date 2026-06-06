"""Skill provenance — records which SKILL.md each capability came from (P3.18).

Used by memory_admin inspect to show where capabilities are defined,
and by SkillHub during hot-reload to invalidate stale registrations.
"""
from __future__ import annotations


class SkillProvenance:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}  # capability_name → SKILL.md path

    def record(self, capability_name: str, skill_path: str) -> None:
        self._map[capability_name] = skill_path

    def get(self, capability_name: str) -> str | None:
        return self._map.get(capability_name)

    def get_all(self) -> dict[str, str]:
        return dict(self._map)

    def capabilities_from_skill(self, skill_path: str) -> list[str]:
        return [cap for cap, path in self._map.items() if path == skill_path]

    def clear_skill(self, skill_path: str) -> None:
        self._map = {cap: p for cap, p in self._map.items() if p != skill_path}

    def summary(self) -> str:
        if not self._map:
            return "No skill provenance recorded."
        lines = [f"  {cap}: {path}" for cap, path in sorted(self._map.items())]
        return "Skill provenance:\n" + "\n".join(lines)
