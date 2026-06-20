"""Tests for shareable Skill & Tool packs (namma_agent/core/packs.py)."""
from __future__ import annotations

import io
import zipfile

import pytest

from namma_agent.core import packs
from namma_agent.core.skills import SkillStore
from namma_agent.core.tools import ToolRegistry

# A minimal but valid user-tool module (matches the authoring template shape).
TOOL_SRC = '''\
"""User-authored tool: echo_it."""
from namma_agent.core.tools import ToolResult

NAME = "echo_it"
DESCRIPTION = "Echo back the input text."


def run(args):
    return f"echo: {args.get('text', '')}"


def register(registry):
    registry.register(NAME, DESCRIPTION, {"type": "object", "properties": {}},
                      lambda args: ToolResult(ok=True, content=run(args)))
'''


@pytest.fixture
def seeded(tmp_path):
    """A SkillStore with one user skill + a tools dir with one tool."""
    skills_dir = tmp_path / "skills"
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    store = SkillStore(user_dir=skills_dir)
    store.create("My Skill", "Does a useful thing.", "# My Skill\nSteps here.")
    (tools_dir / "echo_it.py").write_text(TOOL_SRC, encoding="utf-8")
    return store, tools_dir


def test_list_items(seeded):
    store, tools_dir = seeded
    items = packs.list_items(store, tools_dir)
    assert any(s["name"] == "my-skill" for s in items["skills"])
    assert items["tools"] == [{"name": "echo_it", "file": "echo_it.py",
                               "description": "Echo back the input text."}]
    # Bundled skills must never leak into a user pack listing.
    assert all("deep-research" != s["name"] for s in items["skills"])


def test_tool_meta_no_execution(seeded):
    # _tool_meta reads NAME/DESCRIPTION via AST without importing the module.
    _store, tools_dir = seeded
    name, desc = packs._tool_meta(tools_dir / "echo_it.py")
    assert name == "echo_it"
    assert desc == "Echo back the input text."


def test_build_pack_contents(seeded):
    store, tools_dir = seeded
    data = packs.build_pack(store, tools_dir, ["my-skill"], ["echo_it.py"],
                            created_by="Aria")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "INSTALL.md" in names
        assert "skills/my-skill/SKILL.md" in names
        assert "tools/echo_it.py" in names
        import json
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["created_by"] == "Aria"
    assert [s["name"] for s in manifest["skills"]] == ["my-skill"]
    assert [t["name"] for t in manifest["tools"]] == ["echo_it"]


def test_build_pack_respects_selection(seeded):
    store, tools_dir = seeded
    # Tool deselected -> not in the zip.
    data = packs.build_pack(store, tools_dir, ["my-skill"], [])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert "skills/my-skill/SKILL.md" in names
    assert not any(n.startswith("tools/") for n in names)


def test_inspect_pack_writes_nothing(seeded, tmp_path):
    store, tools_dir = seeded
    data = packs.build_pack(store, tools_dir, ["my-skill"], ["echo_it.py"])

    # Inspect against an *empty* target -> nothing exists yet, nothing written.
    fresh = SkillStore(user_dir=tmp_path / "fresh_skills")
    fresh_tools = tmp_path / "fresh_tools"
    info = packs.inspect_pack(data, fresh, fresh_tools)
    assert [s["name"] for s in info["skills"]] == ["my-skill"]
    assert info["skills"][0]["exists"] is False
    tool = info["tools"][0]
    assert tool["name"] == "echo_it"
    assert "def run(" in tool["source"]
    assert tool["exists"] is False
    assert not fresh_tools.exists()  # inspect never writes


def test_install_only_approved_tools(seeded, tmp_path):
    store, tools_dir = seeded
    data = packs.build_pack(store, tools_dir, ["my-skill"], ["echo_it.py"])

    dest_skills = tmp_path / "dest_skills"
    dest_tools = tmp_path / "dest_tools"
    dest = SkillStore(user_dir=dest_skills)
    reg = ToolRegistry()

    # No approved tools -> skill installs, tool is skipped (never written/loaded).
    summary = packs.install_pack(data, dest, dest_tools, reg,
                                 approved_tools=[], skill_names=["my-skill"])
    assert "my-skill" in summary["skills"]["installed"]
    assert "echo_it" in summary["tools"]["skipped"]
    assert not (dest_tools / "echo_it.py").exists()
    assert "echo_it" not in reg
    assert dest.get("my-skill") is not None


def test_install_approved_tool_loads(seeded, tmp_path):
    store, tools_dir = seeded
    data = packs.build_pack(store, tools_dir, ["my-skill"], ["echo_it.py"])

    dest = SkillStore(user_dir=tmp_path / "dest_skills")
    dest_tools = tmp_path / "dest_tools"
    reg = ToolRegistry()
    summary = packs.install_pack(data, dest, dest_tools, reg,
                                 approved_tools=["echo_it"], skill_names=["my-skill"])
    assert "echo_it" in summary["tools"]["installed"]
    assert (dest_tools / "echo_it.py").exists()
    assert "echo_it" in reg


def test_install_path_traversal_rejected(tmp_path):
    # A crafted skill whose member escapes the skills dir must be refused.
    # (Tools always install by basename, so they can't traverse.)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json",
                    '{"format":"namma-pack","version":1,"tools":[],'
                    '"skills":[{"name":"evil","path":"skills/evil/"}]}')
        zf.writestr("skills/evil/SKILL.md", "ok\n")
        zf.writestr("skills/evil/../../../pwned.py", "X = 1\n")

    dest = SkillStore(user_dir=tmp_path / "s")
    dest_tools = tmp_path / "t"
    reg = ToolRegistry()
    summary = packs.install_pack(buf.getvalue(), dest, dest_tools, reg,
                                 skill_names=["evil"])
    assert "evil" in summary["skills"].get("failed", [])
    assert not (tmp_path / "pwned.py").exists()
