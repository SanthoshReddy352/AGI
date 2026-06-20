#!/usr/bin/env python3
"""Build the branded native installer for the CURRENT operating system.

It freezes the Tkinter installer (`installer/`) with PyInstaller, bundling the app
source (incl. the prebuilt web UI) inside — so the resulting installer shows the
Namma Agent UI even on a machine with no Python, then installs everything. Outputs
land in ``installers/native/dist/``:

    Windows -> NammaAgentInstaller-<ver>.exe          (single file)
    macOS   -> NammaAgent-<ver>.dmg                    (contains the .app)
    Linux   -> NammaAgentInstaller-<ver>-x86_64.AppImage  (or a raw binary)

Run it on each OS (CI does this automatically — see .github/workflows/release.yml):
    pip install pyinstaller
    python installers/native/build.py

Prereqs: Node 18+ (UI build), git; macOS needs hdiutil (built in); Linux needs
appimagetool on PATH for the .AppImage (otherwise the raw binary is produced).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "installers" / "native"
BUILD = NATIVE / "build"
DIST = NATIVE / "dist"
APP = BUILD / "app"
NAME = "NammaAgentInstaller"


def version() -> str:
    t = (ROOT / "namma_agent" / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', t).group(1)


def run(cmd, cwd=None):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd and str(cwd), check=True)


def stage_app():
    """Stage a clean app copy (tracked files + the prebuilt UI) at build/app."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    APP.mkdir(parents=True)
    webui = ROOT / "namma_agent" / "webui"
    if not (webui / "dist" / "index.html").exists():
        run(["npm", "install"], cwd=webui)
        run(["npm", "run", "build"], cwd=webui)
    tar = BUILD / "src.tar"
    run(["git", "archive", "-o", tar, "HEAD"], cwd=ROOT)
    with tarfile.open(tar) as t:
        t.extractall(APP)
    tar.unlink()
    dst = APP / "namma_agent" / "webui" / "dist"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(webui / "dist", dst, dirs_exist_ok=True)


def freeze(ver: str):
    """PyInstaller-freeze installer/ with the staged app bundled in."""
    sep = ";" if os.name == "nt" else ":"
    onefile = platform.system() != "Darwin"   # macOS wants a .app (onedir) for the .dmg
    # `python -m PyInstaller` (not the `pyinstaller` script) so it works regardless
    # of whether the Scripts/bin dir is on PATH.
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
            "--add-data", f"{APP}{sep}app",
            "--distpath", DIST, "--workpath", BUILD / "pyi", "--specpath", BUILD]
    if onefile:
        args.append("--onefile")
    ico = ROOT / "namma_agent" / "assets" / ("sparkle.ico" if os.name == "nt" else "sparkle.png")
    if ico.exists():
        args += ["--icon", ico]
    args.append(ROOT / "installer" / "__main__.py")
    run(args, cwd=ROOT)


def package(ver: str):
    DIST.mkdir(parents=True, exist_ok=True)
    sysname = platform.system()
    if sysname == "Windows":
        src = DIST / f"{NAME}.exe"
        out = DIST / f"{NAME}-{ver}.exe"
        if src.exists():
            src.replace(out)
        print(f"\nBuilt: {out}")
    elif sysname == "Darwin":
        appbundle = DIST / f"{NAME}.app"
        dmg = DIST / f"NammaAgent-{ver}.dmg"
        if dmg.exists():
            dmg.unlink()
        run(["hdiutil", "create", "-volname", "Namma Agent", "-srcfolder", appbundle,
             "-ov", "-format", "UDZO", dmg])
        print(f"\nBuilt: {dmg}")
    else:  # Linux
        binary = DIST / NAME
        if shutil.which("appimagetool"):
            appdir = BUILD / "NammaAgent.AppDir"
            (appdir / "usr" / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, appdir / "usr" / "bin" / NAME)
            (appdir / "AppRun").write_text(
                f'#!/bin/bash\nexec "$(dirname "$(readlink -f "$0")")/usr/bin/{NAME}" "$@"\n')
            os.chmod(appdir / "AppRun", 0o755)
            (appdir / "namma-agent.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Namma Agent\n"
                f"Exec={NAME}\nIcon=namma-agent\nCategories=Utility;\nTerminal=false\n")
            icon = ROOT / "namma_agent" / "assets" / "sparkle.png"
            if icon.exists():
                shutil.copy2(icon, appdir / "namma-agent.png")
            out = DIST / f"{NAME}-{ver}-x86_64.AppImage"
            run(["appimagetool", appdir, out], cwd=BUILD)
            print(f"\nBuilt: {out}")
        else:
            print(f"\nappimagetool not found — raw binary is at {binary}")


def main():
    ver = version()
    print(f"== Building Namma Agent installer {ver} on {platform.system()} ==")
    stage_app()
    freeze(ver)
    package(ver)


if __name__ == "__main__":
    sys.exit(main())
