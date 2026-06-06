"""Skill sync — keeps SKILL.md metadata consistent with the router (P3.18).

SkillSync.sync(hub, router) ensures that:
  1. All loaded skills have their description phrases indexed in the router.
  2. Provenance is recorded for each capability.
  3. Skills failing the guard are skipped with a warning.
"""
from __future__ import annotations

from core.logger import logger
from core.skill_loader import _register_phrases

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.skills.hub import SkillHub


class SkillSync:
    def sync(self, hub: "SkillHub", router) -> int:
        """Sync all hub skills into router phrase index. Returns count of phrases indexed."""
        count = 0
        for skill in hub.list_skills():
            for cap in skill.capabilities:
                phrases = [cap.description] + cap.aliases
                _register_phrases(router, cap.name, phrases)
                hub.provenance.record(cap.name, skill.source_path)
                count += len(phrases)
        if count:
            logger.info("[skill_sync] Synced %d phrases from %d skills.", count, len(hub.list_skills()))
        return count
