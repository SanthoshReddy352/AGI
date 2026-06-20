"""Pure helpers of the graphical installer (installer/core.py)."""
from __future__ import annotations

from installer import core


def test_repo_slug_is_renamed():
    assert core.REPO == "SanthoshReddy352/Namma-Agent"
    assert core.REPO_URL.endswith("Namma-Agent.git")


def test_default_install_dir_on_desktop():
    d = core.default_install_dir()
    assert d.name == "Namma-Agent"
    assert d.parent.name in ("Desktop", d.parent.name)  # Desktop, or home fallback


def test_dependency_status_shape():
    s = core.dependency_status()
    assert set(s) == {"python", "git", "node"}
    assert all(isinstance(v, bool) for v in s.values())


def test_install_dep_command_windows():
    assert core.install_dep_command("python", "Windows")[:2] == ["winget", "install"]
    assert "Python.Python.3.12" in core.install_dep_command("python", "Windows")
    assert "Git.Git" in core.install_dep_command("git", "Windows")
    assert "OpenJS.NodeJS.LTS" in core.install_dep_command("node", "Windows")
    assert core.install_dep_command("bogus", "Windows") is None


def test_install_dep_command_macos():
    assert core.install_dep_command("node", "Darwin") == ["brew", "install", "node"]
    assert core.install_dep_command("python", "Darwin") == ["brew", "install", "python"]


def test_venv_python_path_shape(tmp_path):
    p = core.venv_python(tmp_path)
    assert ".venv" in str(p) and p.name.startswith("python")
