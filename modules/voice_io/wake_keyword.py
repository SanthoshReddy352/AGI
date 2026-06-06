"""Cross-platform Porcupine wake-keyword resolution.

Both the in-app wake detector (``wake_detector.py``) and the standalone
autostart launcher (``wake_porcupine.py``) need to answer the same question:
*which* Porcupine keyword file should we load on this machine?

A custom Porcupine ``.ppn`` is compiled **per platform** — a Linux ``.ppn``
will be rejected by Porcupine on Windows/macOS. We only bundle the Linux
"Hey Friday" keyword, so this module returns:

1. the OS-matched bundled "Hey Friday" ``.ppn`` if it exists, else
2. a **built-in** keyword shipped inside the ``pvporcupine`` wheel
   (``pvporcupine.KEYWORD_PATHS``) — these exist for Linux, Windows, macOS
   and Raspberry Pi, so wake-word works out of the box on every OS.

Drop ``Wake-up-Friday_en_windows_v4_0_0.ppn`` / ``..._mac_...`` next to this
file and it will be picked up automatically on those platforms.

This module imports no heavy dependencies at module load — ``pvporcupine`` is
imported lazily so importing it never fails on a machine that hasn't installed
the wake-word extras yet.
"""
from __future__ import annotations

import os
import platform

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Default built-in keyword to fall back to when no OS-matched custom keyword
# is bundled. "jarvis" ships for every platform and is an on-theme stand-in
# for "Hey Friday". Override with the FRIDAY_WAKE_KEYWORD env var.
_DEFAULT_BUILTIN = os.environ.get("FRIDAY_WAKE_KEYWORD", "jarvis").strip().lower()


def _platform_token() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "mac"
    return "linux"


def bundled_friday_ppn() -> str | None:
    """Return the path to the bundled 'Hey Friday' keyword for *this* OS.

    Only returns a path whose platform token matches the current OS, so we
    never hand Porcupine a Linux ``.ppn`` on Windows (which would raise).
    """
    name = f"Wake-up-Friday_en_{_platform_token()}_v4_0_0.ppn"
    path = os.path.join(SCRIPT_DIR, name)
    return path if os.path.exists(path) else None


def resolve_keyword(builtin_fallback: str | None = None) -> tuple[str | None, str | None, bool]:
    """Resolve the keyword file to load on this machine.

    Returns ``(keyword_path, label, is_custom)``.

    * ``keyword_path`` — absolute path to a ``.ppn`` Porcupine can load, or
      ``None`` if neither a bundled keyword nor ``pvporcupine`` is available.
    * ``label`` — human-readable wake phrase for logs/UX.
    * ``is_custom`` — True when using the bundled "Hey Friday" keyword.
    """
    custom = bundled_friday_ppn()
    if custom:
        return custom, "Hey Friday", True

    keyword = (builtin_fallback or _DEFAULT_BUILTIN or "jarvis").lower()
    try:
        import pvporcupine  # lazy: optional dependency
    except Exception:
        return None, None, False

    paths = getattr(pvporcupine, "KEYWORD_PATHS", {}) or {}
    if keyword in paths:
        return paths[keyword], keyword, False
    # Last resort: any keyword the wheel ships for this platform.
    for name, path in paths.items():
        return path, name, False
    return None, None, False
