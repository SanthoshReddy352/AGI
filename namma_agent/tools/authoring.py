"""Self-authoring — let Namma Agent write a brand-new tool on request and load it live.

The user can say "make a tool that …" and the agent calls ``create_tool`` with a
``run(args)`` function body. The module is written to ``~/.namma_agent/tools/`` (loaded
on every startup) and registered into the live registry immediately. Code that the
model writes runs in-process, so this is approval-gated.

(For procedures/workflows that don't need new Python, prefer ``create_skill`` —
that's the lighter-weight path and needs no code.)
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry, ToolResult

USER_TOOLS_DIR = Path("~/.namma_agent/tools").expanduser()

_TEMPLATE = '''\
"""User-authored tool: {name}."""
from namma_agent.core.tools import ToolResult

NAME = {name!r}
DESCRIPTION = {description!r}
PARAMETERS = {parameters!r}


{code}


def register(registry):
    def _handler(args):
        out = run(args)
        if isinstance(out, ToolResult):
            return out
        if isinstance(out, dict):
            return ToolResult(ok=bool(out.get("ok", True)),
                              content=str(out.get("content", out)), data=out)
        return ToolResult(ok=True, content=str(out))

    registry.register(NAME, DESCRIPTION, PARAMETERS, _handler)
'''


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
    return s or "tool"


def _load_user_tool(path: Path, registry: ToolRegistry) -> None:
    spec = importlib.util.spec_from_file_location(f"namma_agent_user_tools.{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "register"):
        module.register(registry)


def load_user_tools(registry: ToolRegistry) -> int:
    """Import every user-authored tool from ~/.namma_agent/tools (called at startup)."""
    if not USER_TOOLS_DIR.exists():
        return 0
    n = 0
    for path in sorted(USER_TOOLS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            _load_user_tool(path, registry)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[authoring] failed to load user tool %s: %s", path.name, exc)
    if n:
        logger.info("[authoring] loaded %d user-authored tool(s)", n)
    return n


def register(registry: ToolRegistry) -> None:
    def create_tool(args: dict) -> ToolResult:
        name = _slug(args.get("name") or "")
        description = (args.get("description") or "").strip()
        code = (args.get("code") or "").strip()
        params = args.get("parameters") or {"type": "object", "properties": {}}
        if not (name and description and code):
            return ToolResult(ok=False, content="",
                              error="'name', 'description', and 'code' are required")
        if "def run(" not in code:
            return ToolResult(ok=False, content="",
                              error="code must define `def run(args):` returning a string/dict/ToolResult")
        USER_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        path = USER_TOOLS_DIR / f"{name}.py"
        path.write_text(_TEMPLATE.format(name=name, description=description,
                                         parameters=params, code=code), encoding="utf-8")
        try:
            _load_user_tool(path, registry)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content="", error=f"tool written but failed to load: {exc}")
        return ToolResult(ok=True, content=f"Created and loaded tool '{name}'. It's available now.")

    registry.register(
        "create_tool",
        "Author a NEW tool from Python and load it live (for capabilities no existing "
        "tool covers). Provide `code` defining `def run(args):` that returns a string/"
        "dict/ToolResult. For plain procedures, prefer create_skill instead.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "short snake_case tool name"},
                "description": {"type": "string", "description": "what the tool does (the model reads this to route)"},
                "code": {"type": "string", "description": "Python defining `def run(args): ...`"},
                "parameters": {"type": "object", "description": "JSON Schema for the tool's args (optional)"},
            },
            "required": ["name", "description", "code"],
        },
        create_tool, destructive=True)
