"""Shareable Skill & Tool *packs* — export the user's own creations and import
someone else's.

Namma Agent can author its own **skills** (``~/.namma_agent/skills/<slug>/SKILL.md``) and
**tools** (``~/.namma_agent/tools/*.py``). A *pack* is a single ``.zip`` that bundles a
selection of those, carries its own install instructions, and lists what's inside:

    manifest.json          — format/version/created + skills[] + tools[]
    INSTALL.md             — human/agent-readable "how to install this" prompt
    skills/<slug>/...       — each skill folder verbatim (SKILL.md + support files)
    tools/<name>.py         — each authored tool file verbatim

Importing is asymmetric on purpose: skills are just markdown and install silently,
but tools are arbitrary Python that loads in-process — so the caller must pass the
explicit set of ``approved_tools`` (the UI shows each tool's source + a warning and
defaults every approval to *off*). Tools not in that set are never written.

The zip is untrusted input, so extraction is guarded against path traversal.
"""
from __future__ import annotations

import ast
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from namma_agent.core.logger import logger

PACK_FORMAT = "namma-pack"
PACK_VERSION = 1


# ── tool introspection (no execution) ───────────────────────────────────────

def _tool_meta(path: Path) -> tuple[str, str]:
    """Pull a tool module's ``NAME``/``DESCRIPTION`` constants *without importing it*.

    User tools execute on import, so we parse the AST for module-level string
    assignments instead. Falls back to the file stem / empty description.
    """
    name, description = path.stem, ""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError) as exc:
        logger.warning("[packs] cannot parse tool %s: %s", path.name, exc)
        return name, description
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "NAME":
                name = value.value or name
            elif isinstance(target, ast.Name) and target.id == "DESCRIPTION":
                description = value.value
    return name, description


def _user_tool_files(tools_dir: Path) -> list[Path]:
    if not tools_dir.exists():
        return []
    return sorted(p for p in tools_dir.glob("*.py") if not p.name.startswith("_"))


# ── listing (drives the export checkboxes) ──────────────────────────────────

def list_items(store, tools_dir: Path) -> dict:
    """Everything the user has created and could share."""
    skills = [
        {"name": s.name, "description": s.one_line(200)}
        for s in store.all() if s.source == "user"
    ]
    tools = []
    for path in _user_tool_files(tools_dir):
        name, description = _tool_meta(path)
        tools.append({"name": name, "file": path.name, "description": description})
    return {"skills": skills, "tools": tools}


# ── export ──────────────────────────────────────────────────────────────────

def _install_prompt(created_by: str, skills: list[dict], tools: list[dict]) -> str:
    lines = [
        f"# {created_by} — Skill & Tool Pack",
        "",
        "This is a shareable pack of assistant-authored skills and tools. To install:",
        "",
        "- **In the app:** open **Settings → Packs → Import**, choose this `.zip`, "
        "review the contents, and approve any tools you trust.",
        "- **Hands-free:** hand this file to your assistant and say *\"install this pack\"*.",
        "",
        "> ⚠️ **Tools run code on your machine.** Skills are just instructions "
        "(markdown) and are safe; tools are Python that loads into the assistant. "
        "Only install tools from a source you trust — review each one first.",
        "",
    ]
    if skills:
        lines.append("## Skills")
        lines += [f"- **{s['name']}** — {s.get('description', '')}".rstrip(" —") for s in skills]
        lines.append("")
    if tools:
        lines.append("## Tools")
        lines += [f"- **{t['name']}** — {t.get('description', '')}".rstrip(" —") for t in tools]
        lines.append("")
    return "\n".join(lines)


def build_pack(
    store,
    tools_dir: Path,
    skill_names: Iterable[str],
    tool_files: Iterable[str],
    *,
    created_by: str = "Namma Agent",
) -> bytes:
    """Build a pack zip from the selected user skills + tool files."""
    skill_names = {n.strip() for n in skill_names if n and n.strip()}
    tool_files = {n.strip() for n in tool_files if n and n.strip()}

    manifest_skills: list[dict] = []
    manifest_tools: list[dict] = []
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Skills — zip the whole folder so support files come along.
        for skill in store.all():
            if skill.source != "user" or skill.name not in skill_names:
                continue
            slug = skill.directory.name
            for f in sorted(skill.directory.rglob("*")):
                if f.is_dir() or "__pycache__" in f.parts:
                    continue
                arc = f"skills/{slug}/{f.relative_to(skill.directory).as_posix()}"
                zf.write(f, arc)
            manifest_skills.append({
                "name": skill.name,
                "description": skill.one_line(200),
                "path": f"skills/{slug}/",
            })

        # Tools — copy each authored .py verbatim.
        by_file = {p.name: p for p in _user_tool_files(tools_dir)}
        for fname in tool_files:
            path = by_file.get(fname)
            if not path:
                continue
            name, description = _tool_meta(path)
            arc = f"tools/{path.name}"
            zf.writestr(arc, path.read_text(encoding="utf-8", errors="replace"))
            manifest_tools.append({"name": name, "description": description, "path": arc})

        manifest = {
            "format": PACK_FORMAT,
            "version": PACK_VERSION,
            "created": datetime.now().isoformat(timespec="seconds"),
            "created_by": created_by,
            "skills": manifest_skills,
            "tools": manifest_tools,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("INSTALL.md", _install_prompt(created_by, manifest_skills, manifest_tools))

    return buf.getvalue()


# ── import ───────────────────────────────────────────────────────────────────

def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        return json.loads(zf.read("manifest.json").decode("utf-8"))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"not a valid pack (bad/missing manifest.json): {exc}") from exc


def _skill_slug(arc_path: str) -> str:
    # "skills/<slug>/..." -> "<slug>"
    parts = arc_path.strip("/").split("/")
    return parts[1] if len(parts) > 1 else ""


def inspect_pack(zip_bytes: bytes, store, tools_dir: Path) -> dict:
    """Describe a pack's contents *without writing anything* — drives the import preview."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = _read_manifest(zf)
        names = set(zf.namelist())

        skills_dir = store.user_dir
        skills = []
        for s in manifest.get("skills", []):
            slug = _skill_slug(s.get("path", ""))
            skills.append({
                "name": s.get("name", slug),
                "description": s.get("description", ""),
                "slug": slug,
                "exists": bool(slug) and (skills_dir / slug).exists(),
            })

        tools = []
        for t in manifest.get("tools", []):
            arc = t.get("path", "")
            fname = Path(arc).name
            source = zf.read(arc).decode("utf-8", "replace") if arc in names else ""
            tools.append({
                "name": t.get("name", Path(fname).stem),
                "description": t.get("description", ""),
                "file": fname,
                "source": source,
                "exists": bool(fname) and (tools_dir / fname).exists(),
            })

    return {
        "format": manifest.get("format"),
        "version": manifest.get("version"),
        "created_by": manifest.get("created_by", ""),
        "created": manifest.get("created", ""),
        "skills": skills,
        "tools": tools,
    }


def _safe_extract_to(zf: zipfile.ZipFile, arc: str, dest_root: Path, dest_rel: str) -> Path:
    """Write ``arc`` to ``dest_root/dest_rel``, refusing any path that escapes root."""
    dest_root = dest_root.resolve()
    target = (dest_root / dest_rel).resolve()
    if not (target == dest_root or dest_root in target.parents):
        raise ValueError(f"unsafe path in pack: {dest_rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(zf.read(arc))
    return target


def install_pack(
    zip_bytes: bytes,
    store,
    tools_dir: Path,
    registry,
    *,
    approved_tools: Optional[Iterable[str]] = None,
    skill_names: Optional[Iterable[str]] = None,
    overwrite: bool = False,
) -> dict:
    """Install selected skills + *approved* tools from a pack.

    ``skill_names`` / ``approved_tools`` are filters (by manifest name); when ``None``
    all skills install but **no** tools do — tools are never installed implicitly.
    Returns ``{skills: {installed, skipped}, tools: {installed, skipped, failed}}``.
    """
    skill_filter = None if skill_names is None else {n.strip() for n in skill_names}
    tool_filter = {n.strip() for n in (approved_tools or [])}

    summary = {
        "skills": {"installed": [], "skipped": []},
        "tools": {"installed": [], "skipped": [], "failed": []},
    }
    skills_dir = store.user_dir
    skills_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = _read_manifest(zf)
        names = set(zf.namelist())

        # -- skills -------------------------------------------------------
        for s in manifest.get("skills", []):
            sname = s.get("name", "")
            slug = _skill_slug(s.get("path", ""))
            if not slug:
                continue
            if skill_filter is not None and sname not in skill_filter:
                continue
            if (skills_dir / slug).exists() and not overwrite:
                summary["skills"]["skipped"].append(sname or slug)
                continue
            prefix = f"skills/{slug}/"
            members = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
            try:
                for arc in members:
                    _safe_extract_to(zf, arc, skills_dir, arc[len("skills/"):])
                summary["skills"]["installed"].append(sname or slug)
            except ValueError as exc:
                logger.warning("[packs] skill %s rejected: %s", slug, exc)
                summary["skills"]["failed"] = summary["skills"].get("failed", []) + [sname or slug]

        # -- tools (only the approved ones) -------------------------------
        for t in manifest.get("tools", []):
            tname = t.get("name", "")
            arc = t.get("path", "")
            fname = Path(arc).name
            if tname not in tool_filter:
                summary["tools"]["skipped"].append(tname or fname)
                continue
            if arc not in names:
                summary["tools"]["failed"].append(tname or fname)
                continue
            if (tools_dir / fname).exists() and not overwrite:
                summary["tools"]["skipped"].append(tname or fname)
                continue
            try:
                target = _safe_extract_to(zf, arc, tools_dir, fname)
            except ValueError as exc:
                logger.warning("[packs] tool %s rejected: %s", fname, exc)
                summary["tools"]["failed"].append(tname or fname)
                continue
            # Load it live so it's usable immediately.
            try:
                from namma_agent.tools.authoring import _load_user_tool
                _load_user_tool(target, registry)
                summary["tools"]["installed"].append(tname or fname)
            except Exception as exc:  # noqa: BLE001 — bad code shouldn't crash import
                logger.warning("[packs] tool %s written but failed to load: %s", fname, exc)
                summary["tools"]["failed"].append(tname or fname)

    store.reload()
    return summary
