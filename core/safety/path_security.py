"""Path security — prevents path-traversal and sandbox escapes (P3.17).

check_path() is the single entry point. Wire it into every file
capability helper before opening or writing a path.

Safe roots are the directories where FRIDAY is permitted to operate:
  - The user's home directory
  - The FRIDAY project directory
  - Standard temp dirs

A path is rejected if:
  - It contains '..' components (traversal)
  - It contains null bytes (null-byte injection)
  - After resolution it lives outside every safe root
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

# Default safe roots — override per deployment via PathSecurity(roots=[...])
_DEFAULT_ROOTS: list[str] = [
    os.path.expanduser("~"),
    "/tmp",
    "/var/tmp",
]


class PathSecurity:
    def __init__(self, roots: Sequence[str] | None = None):
        self._roots = [str(Path(r).resolve()) for r in (roots or _DEFAULT_ROOTS)]

    def validate(self, path: str) -> tuple[bool, str]:
        """Return (ok, reason). ok=True means the path is safe to use."""
        if not path:
            return False, "empty path"
        if "\x00" in path:
            return False, "null byte in path"
        if ".." in Path(path).parts:
            return False, "path traversal (..)"
        try:
            resolved = str(Path(path).resolve())
        except Exception as exc:
            return False, f"resolve error: {exc}"
        if not any(resolved.startswith(root) for root in self._roots):
            return False, f"path outside safe roots: {resolved}"
        return True, ""

    def safe_join(self, base: str, *parts: str) -> str | None:
        """Join base + parts and validate the result. Returns None if unsafe."""
        joined = os.path.join(base, *parts)
        ok, _ = self.validate(joined)
        return joined if ok else None


# Module-level singleton with default roots.
_default = PathSecurity()


def check_path(path: str) -> tuple[bool, str]:
    """Validate a path against the default safe roots."""
    return _default.validate(path)
