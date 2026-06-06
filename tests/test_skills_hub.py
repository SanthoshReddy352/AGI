"""P3.1 + P3.18 — SkillLoader, SkillHub, and lifecycle components."""
import os
import tempfile

import pytest

from core.skill_loader import SkillLoader, SkillMeta
from core.skills.hub import SkillHub
from core.skills.provenance import SkillProvenance
from core.skills.usage import SkillUsage
from core.skills.guard import SkillGuard


_SKILL_MD = """\
---
name: test_skill
description: "A test skill for unit testing"
plugin_module: modules/test_skill
capabilities:
  - name: do_thing
    description: "Do a test thing"
    aliases:
      - "test thing"
      - "run test"
---

# Test Skill

Body text here.
"""


@pytest.fixture()
def skill_dir(tmp_path):
    skill_dir = tmp_path / "test_plugin"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    return str(tmp_path)


# ── SkillLoader ────────────────────────────────────────────────────────────

def test_scan_finds_skill_md(skill_dir):
    loader = SkillLoader(modules_root=skill_dir)
    skills = loader.scan()
    assert len(skills) == 1
    assert skills[0].name == "test_skill"


def test_skill_capabilities_parsed(skill_dir):
    loader = SkillLoader(modules_root=skill_dir)
    skills = loader.scan()
    cap = skills[0].capabilities[0]
    assert cap.name == "do_thing"
    assert "test thing" in cap.aliases


def test_empty_dir_no_skills(tmp_path):
    loader = SkillLoader(modules_root=str(tmp_path))
    assert loader.scan() == []


def test_real_skill_mds_load():
    """Verify at least the 3 seeded SKILL.md files load cleanly."""
    project_root = os.path.dirname(os.path.dirname(__file__))
    loader = SkillLoader(modules_root=os.path.join(project_root, "modules"))
    skills = loader.scan()
    names = [s.name for s in skills]
    assert "security_tools" in names
    assert "system_control" in names
    assert "memory_manager" in names


# ── SkillHub ───────────────────────────────────────────────────────────────

def test_hub_load_all(skill_dir):
    hub = SkillHub(modules_root=skill_dir)
    count = hub.load_all()
    assert count == 1
    assert hub.get_skill("test_skill") is not None


def test_hub_reload(skill_dir):
    hub = SkillHub(modules_root=skill_dir)
    hub.load_all()
    count = hub.reload()
    assert count == 1


def test_hub_inspect_summary(skill_dir):
    hub = SkillHub(modules_root=skill_dir)
    hub.load_all()
    hub.record_usage("do_thing")
    summary = hub.inspect_summary()
    assert "test_skill" in summary or "loaded" in summary.lower()


# ── SkillProvenance ────────────────────────────────────────────────────────

def test_provenance_record_and_get():
    p = SkillProvenance()
    p.record("my_tool", "/path/to/SKILL.md")
    assert p.get("my_tool") == "/path/to/SKILL.md"


def test_provenance_capabilities_from_skill():
    p = SkillProvenance()
    p.record("tool_a", "/skill/A.md")
    p.record("tool_b", "/skill/A.md")
    p.record("tool_c", "/skill/B.md")
    assert set(p.capabilities_from_skill("/skill/A.md")) == {"tool_a", "tool_b"}


def test_provenance_clear_skill():
    p = SkillProvenance()
    p.record("tool_a", "/skill/A.md")
    p.clear_skill("/skill/A.md")
    assert p.get("tool_a") is None


# ── SkillUsage ─────────────────────────────────────────────────────────────

def test_usage_record_and_get():
    u = SkillUsage()
    u.record("ping_sweep")
    u.record("ping_sweep")
    assert u.get("ping_sweep") == 2


def test_usage_top():
    u = SkillUsage()
    for _ in range(3):
        u.record("a")
    for _ in range(1):
        u.record("b")
    top = u.top(2)
    assert top[0][0] == "a"


def test_usage_reset():
    u = SkillUsage()
    u.record("x")
    u.reset()
    assert u.get("x") == 0


# ── SkillGuard ─────────────────────────────────────────────────────────────

def test_guard_no_requirements(skill_dir):
    from core.skill_loader import SkillMeta
    g = SkillGuard(config={})
    skill = SkillMeta("s", "desc", "mod", "/path", requires={}, capabilities=[])
    ok, reason = g.can_load(skill)
    assert ok


def test_guard_lab_mode_required_and_present():
    from core.skill_loader import SkillMeta
    g = SkillGuard(config={"lab_mode": True})
    skill = SkillMeta("s", "d", "m", "/p", requires={"lab_mode": True}, capabilities=[])
    ok, _ = g.can_load(skill)
    assert ok


def test_guard_lab_mode_required_and_absent():
    from core.skill_loader import SkillMeta
    g = SkillGuard(config={})
    skill = SkillMeta("s", "d", "m", "/p", requires={"lab_mode": True}, capabilities=[])
    ok, reason = g.can_load(skill)
    assert not ok
    assert "lab_mode" in reason


# ── P4 sub-skill discovery ─────────────────────────────────────────────────

_PLUGIN_SKILL = """\
---
name: web
description: "Web tools"
plugin_module: modules/web
capabilities:
  - name: web_search
    description: "Search the web"
---

# Web
"""

_SUB_SKILL = """\
---
name: arxiv-research
description: "Find and summarise arxiv papers."
source: "hermes-agent skills/research/arxiv (MIT)"
requires:
  - web_search
  - web_extract
---

# arxiv research
"""


@pytest.fixture()
def sub_skill_dir(tmp_path):
    plugin = tmp_path / "web"
    plugin.mkdir()
    (plugin / "SKILL.md").write_text(_PLUGIN_SKILL, encoding="utf-8")
    sub = plugin / "SKILLS"
    sub.mkdir()
    (sub / "arxiv.md").write_text(_SUB_SKILL, encoding="utf-8")
    return str(tmp_path)


def test_scan_picks_up_subskills(sub_skill_dir):
    loader = SkillLoader(modules_root=sub_skill_dir)
    skills = loader.scan()
    names = {s.name for s in skills}
    assert "web" in names
    assert "arxiv-research" in names


def test_subskill_requires_as_list(sub_skill_dir):
    loader = SkillLoader(modules_root=sub_skill_dir)
    loader.scan()
    arxiv = next(s for s in loader.skills if s.name == "arxiv-research")
    # requires came in as a YAML list, not a dict — loader must accept both.
    assert isinstance(arxiv.requires, list)
    assert "web_search" in arxiv.requires


def test_full_modules_tree_loads_22_skills():
    """8 plugin SKILL.md + 14 P4 sub-skills under SKILLS/ = 22 total."""
    loader = SkillLoader()
    skills = loader.scan()
    assert len(skills) == 22, [s.source_path for s in skills]
    sub_names = {s.name for s in skills if "/SKILLS/" in s.source_path}
    expected = {
        "arxiv-research", "blog-watcher", "research-paper-writing",
        "llm-wiki", "email", "github",
        "note-taking", "diagramming", "creative-writing", "media",
        "software-development", "smart-home-scenes", "mcp-usage", "red-teaming",
    }
    assert expected <= sub_names
