"""SkillHub — central registry for loaded skills (P3.18).

SkillHub wraps SkillLoader to manage the full lifecycle:
  - Initial scan on startup
  - Hot-reload on demand (re-scan SKILL.md files, refresh registry)
  - Access to provenance, usage, and guard sub-components

Wire into FridayApp:
    app.skill_hub = SkillHub(config=app.config)
    app.skill_hub.load_all(router=app.router)
"""
from __future__ import annotations

from core.logger import logger
from core.skill_loader import SkillLoader, SkillMeta
from core.skills.guard import SkillGuard
from core.skills.provenance import SkillProvenance
from core.skills.usage import SkillUsage
from core.skills.sync import SkillSync


class SkillHub:
    def __init__(self, config: dict | None = None, modules_root: str | None = None):
        self._loader = SkillLoader(modules_root)
        self.guard = SkillGuard(config or {})
        self.provenance = SkillProvenance()
        self.usage = SkillUsage()
        self._sync = SkillSync()
        self._skills: list[SkillMeta] = []

    def load_all(self, router=None) -> int:
        """Scan SKILL.md files, apply guard, sync to router. Returns loaded count."""
        all_skills = self._loader.scan()
        self._skills = [s for s in all_skills if self._passes_guard(s)]
        if router:
            self._sync.sync(self, router)
        logger.info("[skill_hub] %d/%d skills loaded.", len(self._skills), len(all_skills))
        return len(self._skills)

    def reload(self, router=None) -> int:
        """Hot-reload: re-scan and re-sync without restarting FRIDAY."""
        logger.info("[skill_hub] Hot-reloading skills...")
        self.provenance = SkillProvenance()
        return self.load_all(router)

    def list_skills(self) -> list[SkillMeta]:
        return list(self._skills)

    def get_skill(self, name: str) -> SkillMeta | None:
        return next((s for s in self._skills if s.name == name), None)

    def record_usage(self, capability_name: str) -> None:
        self.usage.record(capability_name)

    def inspect_summary(self) -> str:
        lines = [
            f"Skills loaded: {len(self._skills)}",
            self.provenance.summary(),
            self.usage.summary(),
        ]
        return "\n".join(lines)

    def _passes_guard(self, skill: SkillMeta) -> bool:
        ok, reason = self.guard.can_load(skill)
        if not ok:
            logger.debug("[skill_hub] Skipped '%s': %s", skill.name, reason)
        return ok
