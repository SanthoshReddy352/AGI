"""UI-free installer logic (driven by installer/gui.py).

Flow, in order: ensure Python/Git/Node -> get the source onto the user's Desktop
(copy the bundled source when frozen, else git-clone) -> create a .venv ->
install requirements -> build the UI if needed -> write the chosen provider +
the onboarding answers into the app's config/DB -> done.

Everything that touches the network / filesystem is a plain function so the GUI
can run it on a worker thread and stream progress; the pure helpers below are unit
tested.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

REPO = "SanthoshReddy352/Namma-Agent"
REPO_URL = f"https://github.com/{REPO}.git"
APP_DIR_NAME = "Namma-Agent"

Log = Callable[[str], None]
_PY_CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python")


# ── locations ────────────────────────────────────────────────────────────────

def desktop_dir() -> Path:
    home = Path.home()
    d = home / "Desktop"
    return d if d.exists() else home


def default_install_dir() -> Path:
    """Where the app lands: <Desktop>/Namma-Agent."""
    return desktop_dir() / APP_DIR_NAME


def venv_python(install_dir: Path) -> Path:
    if os.name == "nt":
        return install_dir / ".venv" / "Scripts" / "python.exe"
    return install_dir / ".venv" / "bin" / "python"


def bundled_source() -> Optional[Path]:
    """When frozen by PyInstaller, the app source is bundled at <_MEIPASS>/app."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "app"
        if (p / "namma_agent").is_dir():
            return p
    return None


# ── dependency detection ─────────────────────────────────────────────────────

def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _is_py310(exe: str) -> bool:
    try:
        out = subprocess.run([exe, "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"],
                             capture_output=True, text=True, timeout=15)
        major, minor = out.stdout.split()[:2]
        return (int(major), int(minor)) >= (3, 10)
    except Exception:  # noqa: BLE001
        return False


def find_python() -> Optional[str]:
    """Path to a Python 3.10+ on PATH the app's venv can be built from."""
    for c in _PY_CANDIDATES:
        exe = shutil.which(c)
        if exe and _is_py310(exe):
            return exe
    return None


def dependency_status() -> dict:
    """{'python': bool, 'git': bool, 'node': bool} — what's already installed."""
    return {"python": find_python() is not None, "git": _has("git"), "node": _has("npm")}


def install_dep_command(tool: str, system: Optional[str] = None) -> Optional[list[str]]:
    """The OS-appropriate command to install a missing tool, or None if unknown.
    Pure (no execution) so it's testable. ``tool`` in {python, git, node}."""
    system = system or platform.system()
    if system == "Windows":
        ids = {"python": "Python.Python.3.12", "git": "Git.Git", "node": "OpenJS.NodeJS.LTS"}
        if tool not in ids:
            return None
        return ["winget", "install", "-e", "--id", ids[tool], "--silent",
                "--accept-source-agreements", "--accept-package-agreements"]
    if system == "Darwin":
        pkg = {"python": "python", "git": "git", "node": "node"}.get(tool)
        return ["brew", "install", pkg] if pkg else None
    # Linux: choose by available package manager.
    matrix = {
        "apt-get": (["sudo", "apt-get", "install", "-y"],
                    {"python": ["python3", "python3-venv", "python3-pip"], "git": ["git"], "node": ["nodejs", "npm"]}),
        "dnf": (["sudo", "dnf", "install", "-y"],
                {"python": ["python3", "python3-pip"], "git": ["git"], "node": ["nodejs", "npm"]}),
        "pacman": (["sudo", "pacman", "-Sy", "--noconfirm"],
                   {"python": ["python"], "git": ["git"], "node": ["nodejs", "npm"]}),
        "zypper": (["sudo", "zypper", "install", "-y"],
                   {"python": ["python3", "python3-venv"], "git": ["git"], "node": ["nodejs", "npm"]}),
    }
    for pm, (prefix, names) in matrix.items():
        if _has(pm) and tool in names:
            return prefix + names[tool]
    return None


# ── steps ────────────────────────────────────────────────────────────────────

def ensure_dependencies(log: Log) -> None:
    status = dependency_status()
    for tool in ("git", "node", "python"):
        if status.get(tool):
            continue
        cmd = install_dep_command(tool)
        if not cmd:
            log(f"  ! {tool} missing and no installer available — please install it manually.")
            continue
        log(f"  Installing {tool} ({' '.join(cmd[:3])} …)")
        subprocess.run(cmd, check=False)
    if find_python() is None:
        raise RuntimeError("Python 3.10+ is required but could not be installed automatically.")


def fetch_source(install_dir: Path, log: Log) -> None:
    src = bundled_source()
    if src:
        log(f"  Copying app files to {install_dir} …")
        install_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, install_dir, dirs_exist_ok=True)
    elif (install_dir / ".git").is_dir():
        log("  Updating existing copy (git pull) …")
        subprocess.run(["git", "pull", "--ff-only"], cwd=str(install_dir), check=False)
    else:
        log(f"  Cloning {REPO_URL} to {install_dir} …")
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(install_dir)], check=True)


def create_venv(install_dir: Path, log: Log) -> None:
    py = find_python()
    if not py:
        raise RuntimeError("No suitable Python found for the virtual environment.")
    if not venv_python(install_dir).exists():
        log("  Creating the Python environment (.venv) …")
        subprocess.run([py, "-m", "venv", str(install_dir / ".venv")], check=True)


def install_requirements(install_dir: Path, log: Log) -> None:
    vpy = str(venv_python(install_dir))
    log("  Installing dependencies (a few minutes) …")
    subprocess.run([vpy, "-m", "pip", "install", "--upgrade", "pip"], check=False)
    subprocess.run([vpy, "-m", "pip", "install", "-r",
                    str(install_dir / "namma_agent" / "requirements.txt")], check=True)


def build_ui(install_dir: Path, log: Log) -> None:
    if (install_dir / "namma_agent" / "webui" / "dist" / "index.html").exists():
        return
    if _has("npm"):
        log("  Building the web UI …")
        webui = str(install_dir / "namma_agent" / "webui")
        subprocess.run(["npm", "install"], cwd=webui, check=False)
        subprocess.run(["npm", "run", "build"], cwd=webui, check=False)


def _run_app_cli(install_dir: Path, args: list[str]) -> None:
    subprocess.run([str(venv_python(install_dir)), "-m", "namma_agent", *args],
                   cwd=str(install_dir), check=False)


def write_provider(install_dir: Path, provider: dict) -> None:
    """provider = {type, model?, api_key?, base_url?} -> config.local.yaml + .env."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(provider, f)
        path = f.name
    try:
        _run_app_cli(install_dir, ["--configure", path])
    finally:
        os.unlink(path)


def write_onboarding(install_dir: Path, answers: dict) -> None:
    """answers = {name, date_of_birth, occupation, ...} -> saved into the app DB."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(answers, f)
        path = f.name
    try:
        _run_app_cli(install_dir, ["--onboard", path])
    finally:
        os.unlink(path)


def launch(install_dir: Path) -> None:
    """Open the installed app, detached, then return."""
    vpy = str(venv_python(install_dir))
    if os.name == "nt":
        pyw = install_dir / ".venv" / "Scripts" / "pythonw.exe"
        exe = str(pyw) if pyw.exists() else vpy
        subprocess.Popen([exe, "-m", "namma_agent"], cwd=str(install_dir), close_fds=True)
    else:
        subprocess.Popen([vpy, "-m", "namma_agent"], cwd=str(install_dir),
                         start_new_session=True, close_fds=True)


def bootstrap(install_dir: Path, log: Log) -> Path:
    """The heavy half (deps -> source -> venv -> requirements -> UI). Provider +
    onboarding are written afterwards from the GUI forms."""
    log("Checking Python, Git and Node.js…")
    ensure_dependencies(log)
    log("Getting the app files…")
    fetch_source(install_dir, log)
    log("Setting up the environment…")
    create_venv(install_dir, log)
    install_requirements(install_dir, log)
    build_ui(install_dir, log)
    log("Base install complete.")
    return install_dir
