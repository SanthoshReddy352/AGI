"""Config loading for FRIDAY v2.

Loads a YAML config and a ``.env`` file (no external dependency — a tiny parser
covers the ``KEY=value`` format). Resolution order for the config path:

  1. ``$FRIDAY_CONFIG`` if set
  2. ``friday/config.yaml`` (the v2 config, preferred during the migration)
  3. ``config.yaml`` at the repo root (legacy fallback)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Optional[str] = None) -> None:
    """Load ``.env`` into ``os.environ``.

    A real, non-empty environment variable still wins (the documented precedence),
    but an **empty or whitespace-only** existing var does NOT shadow ``.env`` — that
    case (e.g. a shell that exports ``OPENAI_API_KEY=``) was silently blanking the
    provider key and making every provider look "unavailable"."""
    env_path = Path(path) if path else _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key, "").strip():
            os.environ[key] = value


def _config_path() -> Path:
    if os.environ.get("FRIDAY_CONFIG"):
        return Path(os.environ["FRIDAY_CONFIG"])
    v2 = _REPO_ROOT / "friday" / "config.yaml"
    if v2.exists():
        return v2
    return _REPO_ROOT / "config.yaml"


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge ``overrides`` into ``base`` (overrides win)."""
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _local_overrides_path(cfg_path: Path) -> Path:
    """UI-written overrides live beside the base config as ``config.local.yaml``;
    merged on top so the documented, commented base file is never rewritten."""
    return cfg_path.with_name("config.local.yaml")


def load_config(path: Optional[str] = None) -> dict[str, Any]:
    """Load the merged config dict (base + local overrides) and ensure ``.env``."""
    load_dotenv()
    cfg_path = Path(path) if path else _config_path()
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    local = _local_overrides_path(cfg_path)
    if local.exists():
        _deep_merge(data, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    return data


def update_config(updates: dict, path: Optional[str] = None) -> dict:
    """Persist ``updates`` (deep-merged) into ``config.local.yaml`` and return the
    merged effective config. Leaves the commented base ``config.yaml`` untouched."""
    cfg_path = Path(path) if path else _config_path()
    local = _local_overrides_path(cfg_path)
    current = (yaml.safe_load(local.read_text(encoding="utf-8")) or {}) if local.exists() else {}
    _deep_merge(current, updates or {})
    local.write_text(yaml.safe_dump(current, sort_keys=False, default_flow_style=False),
                     encoding="utf-8")
    return load_config(path)


def assistant_name(config: Optional[dict] = None) -> str:
    """The assistant's display name — the single source of truth for what the
    assistant is called everywhere (system prompt, UI, voice, messaging).

    Resolution order: ``$ASSISTANT_NAME`` env override → ``assistant.name`` in the
    config → ``"FRIDAY"``. Change it in one place (``friday/config.yaml`` under
    ``assistant.name``, or the ``ASSISTANT_NAME`` env var) to rename the assistant.
    """
    env = os.environ.get("ASSISTANT_NAME")
    if env and env.strip():
        return env.strip()
    cfg = config if config is not None else load_config()
    name = ((cfg.get("assistant") or {}).get("name") or "").strip()
    return name or "FRIDAY"


def set_env_values(updates: dict, path: Optional[str] = None) -> list[str]:
    """Create/update ``KEY=value`` lines in ``.env`` (preserving other lines).
    Also applies to the live ``os.environ``. Returns the keys written."""
    env_path = Path(path) if path else _REPO_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    written: list[str] = []
    for key, value in (updates or {}).items():
        key = str(key).strip()
        if not key:
            continue
        value = "" if value is None else str(value)
        new_line = f"{key}={value}"
        for i, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped and not stripped.startswith("#") and stripped.split("=", 1)[0].strip() == key:
                lines[i] = new_line
                break
        else:
            lines.append(new_line)
        os.environ[key] = value
        written.append(key)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written
