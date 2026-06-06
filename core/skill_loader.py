"""SKILL.md companion loader (P3.1).

Each plugin directory may contain a SKILL.md file with YAML frontmatter
describing the plugin's capabilities. SkillLoader scans modules/ for
these files, parses the metadata, and can register descriptions in the
embedding router so phrase matching covers SKILL.md aliases.

SKILL.md frontmatter format:
  ---
  name: security_tools
  description: "Short one-line description"
  plugin_module: modules/security_tools
  requires:
    lab_mode: true        # optional
  capabilities:
    - name: ping_sweep
      description: "Ping sweep a network range"
      aliases: ["scan my network"]   # optional extra phrases
  ---
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from core.logger import logger


@dataclass
class CapabilityMeta:
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class SkillMeta:
    name: str
    description: str
    plugin_module: str
    source_path: str
    # `requires:` may be either a dict (top-level plugin SKILL.md —
    # e.g. {lab_mode: true}) or a list (P4 sub-skills naming the
    # capabilities they lean on — e.g. [web_search, llm_chat]).
    requires: dict | list = field(default_factory=dict)
    capabilities: list[CapabilityMeta] = field(default_factory=list)


class SkillLoader:
    def __init__(self, modules_root: str | None = None):
        self._root = modules_root or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "modules"
        )
        self._skills: list[SkillMeta] = []

    def scan(self) -> list[SkillMeta]:
        """Walk modules/ and load every SKILL.md plus every SKILLS/*.md found."""
        self._skills = []
        for dirpath, dirs, files in os.walk(self._root):
            # Top-level plugin skill (one per plugin folder).
            if "SKILL.md" in files:
                path = os.path.join(dirpath, "SKILL.md")
                skill = self._load(path)
                if skill:
                    self._skills.append(skill)
                    logger.debug("[skill_loader] Loaded: %s from %s", skill.name, path)
            # P4 sub-skills under <plugin>/SKILLS/*.md — pure markdown,
            # no `capabilities:` block, but their description still feeds
            # the SkillHub registry so the LLM can locate the right doc.
            if os.path.basename(dirpath) == "SKILLS":
                for fname in files:
                    if not fname.endswith(".md"):
                        continue
                    path = os.path.join(dirpath, fname)
                    skill = self._load(path)
                    if skill and skill.name:
                        self._skills.append(skill)
                        logger.debug("[skill_loader] Loaded sub-skill: %s from %s",
                                     skill.name, path)
        logger.info("[skill_loader] Scanned %d SKILL.md files.", len(self._skills))
        return list(self._skills)

    def _load(self, path: str) -> Optional[SkillMeta]:
        try:
            return _parse_skill_md(path)
        except Exception as exc:
            logger.warning("[skill_loader] Failed to parse %s: %s", path, exc)
            return None

    def index_in_router(self, router) -> None:
        """Register SKILL.md descriptions + aliases in the embedding router."""
        indexed = 0
        for skill in self._skills:
            for cap in skill.capabilities:
                phrases = [cap.description] + cap.aliases
                _register_phrases(router, cap.name, phrases)
                indexed += len(phrases)
        logger.info("[skill_loader] Indexed %d skill phrases in router.", indexed)

    @property
    def skills(self) -> list[SkillMeta]:
        return list(self._skills)


def _parse_skill_md(path: str) -> Optional[SkillMeta]:
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    front, _ = _split_frontmatter(content)
    if not front:
        return None
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(front) or {}
    except Exception:
        return None
    caps = [
        CapabilityMeta(
            name=str(c.get("name", "")),
            description=str(c.get("description", "")),
            aliases=list(c.get("aliases") or []),
        )
        for c in (data.get("capabilities") or [])
        if c.get("name")
    ]
    raw_requires = data.get("requires") or {}
    if isinstance(raw_requires, list):
        requires: dict | list = list(raw_requires)
    elif isinstance(raw_requires, dict):
        requires = dict(raw_requires)
    else:
        requires = {}
    return SkillMeta(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        plugin_module=str(data.get("plugin_module", "")),
        source_path=path,
        requires=requires,
        capabilities=caps,
    )


def _split_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---"):
        return "", content
    end = content.find("\n---", 3)
    if end == -1:
        return "", content
    return content[3:end].strip(), content[end + 4:].strip()


def _register_phrases(router, capability_name: str, phrases: list[str]) -> None:
    embedding_router = getattr(router, "embedding_router", None) or getattr(router, "_embedding_router", None)
    if embedding_router is None:
        return
    try:
        for phrase in phrases:
            if phrase:
                embedding_router.add_phrase(phrase, capability_name)
    except Exception:
        pass
