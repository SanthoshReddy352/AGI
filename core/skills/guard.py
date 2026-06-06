"""Skill guard — gates skill loading on platform and config (P3.18).

SkillGuard.can_load(skill_meta, config) returns True if the skill's
requirements are met by the current environment.

Supported requirements (from SKILL.md frontmatter `requires:` block):
  lab_mode: true  — requires config key `lab_mode: true`
  platform: linux — requires sys.platform == 'linux'
  platform: win32 — requires sys.platform == 'win32'
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.skill_loader import SkillMeta


class SkillGuard:
    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def can_load(self, skill_meta: "SkillMeta") -> tuple[bool, str]:
        """Return (ok, reason). ok=False means the skill should be skipped."""
        requires = skill_meta.requires or {}
        if requires.get("lab_mode"):
            if not self._config.get("lab_mode"):
                return False, "requires lab_mode: true in config"
        platform_req = requires.get("platform")
        if platform_req and sys.platform != platform_req:
            return False, f"requires platform: {platform_req} (current: {sys.platform})"
        return True, ""

    def update_config(self, config: dict) -> None:
        self._config = config
