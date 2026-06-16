"""Tests for the skill system (procedural memory ported from hermes-agent)."""
from __future__ import annotations

from pathlib import Path

import pytest

from friday.core.builtins import register_skill_tools
from friday.core.skills import SkillStore, parse_frontmatter
from friday.core.tools import ToolRegistry


def test_parse_frontmatter():
    fm, body = parse_frontmatter("---\nname: x\ndescription: hello\n---\n\n# Body\ntext")
    assert fm["name"] == "x"
    assert fm["description"] == "hello"
    assert "# Body" in body


def test_parse_frontmatter_none():
    fm, body = parse_frontmatter("# no frontmatter\njust text")
    assert fm == {}
    assert body.startswith("# no frontmatter")


def test_bundled_skills_discovered(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    names = {s.name for s in store.all()}
    # Seed skills that ship with FRIDAY.
    assert {"deep-research", "organize-files", "one-three-one-rule"} <= names


def test_render_includes_body(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    body = store.render("deep-research")
    assert body is not None
    assert "Procedure" in body
    assert body.startswith("# Skill: deep-research")


def test_render_unknown(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    assert store.render("does-not-exist") is None


def test_create_and_reload(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    skill = store.create("My Cool Skill", "when to use it", "# Body\nstep 1", category="test")
    assert skill.name == "my-cool-skill"
    assert skill.source == "user"
    assert (tmp_path / "skills" / "my-cool-skill" / "SKILL.md").exists()
    # Survives a reload (round-trips through disk).
    store.reload()
    assert store.get("my-cool-skill") is not None


def test_user_overrides_bundled(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    store.create("deep-research", "overridden", "# Overridden body")
    assert store.get("deep-research").source == "user"
    assert "Overridden body" in store.render("deep-research")


def test_update_skill(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    store.create("temp", "desc", "# Old")
    store.update("temp", body="# New body", description="new desc")
    skill = store.get("temp")
    assert skill.description == "new desc"
    assert "New body" in store.render("temp")


def test_inline_shell_opt_in(tmp_path):
    udir = tmp_path / "skills"
    (udir / "echoer").mkdir(parents=True)
    (udir / "echoer" / "SKILL.md").write_text(
        "---\nname: echoer\ndescription: d\n---\nValue: !`echo HELLO`\n", encoding="utf-8"
    )
    off = SkillStore(user_dir=udir, allow_inline_shell=False)
    assert "!`echo HELLO`" in off.render("echoer")
    on = SkillStore(user_dir=udir, allow_inline_shell=True)
    assert "HELLO" in on.render("echoer")


def test_skill_tools(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    reg = ToolRegistry()
    register_skill_tools(reg, store)
    assert {"list_skills", "use_skill", "create_skill", "update_skill"} <= set(reg.names())

    listed = reg.execute("list_skills", {})
    assert listed.ok and "deep-research" in listed.content

    used = reg.execute("use_skill", {"name": "deep-research"})
    assert used.ok and "Procedure" in used.content

    created = reg.execute("create_skill", {
        "name": "from-tool", "description": "d", "body": "# B",
    })
    assert created.ok
    assert store.get("from-tool") is not None
