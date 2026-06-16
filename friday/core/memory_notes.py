"""Agent-curated memory notes — ``MEMORY.md`` + ``USER.md``.

Ported from NousResearch/hermes-agent's human-readable memory files. These sit
*alongside* the structured ``facts`` table (key/value user profile) and the
SQLite session history, and hold free-form prose the agent curates itself:

  * ``USER.md``   — a narrative profile of the user (who they are, how they like
    to work, preferences that don't fit a single key/value fact)
  * ``MEMORY.md`` — the agent's own long-term working notes (ongoing projects,
    decisions, context worth carrying between sessions)

Both are plain markdown on disk (``data/memory/`` by default), injected into the
system prompt each turn so they're always-on context, and edited by the agent
through the memory tools. Everything is visible — no hidden state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_USER_HEADER = "# User Profile\n\n_FRIDAY's curated notes about the user._\n"
_MEMORY_HEADER = "# FRIDAY Memory\n\n_Long-term working notes the agent keeps for itself._\n"
_MAX_INJECT = 6000  # chars per file folded into the prompt


class MemoryNotes:
    def __init__(self, directory: str | Path = "data/memory"):
        self.dir = Path(directory).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.user_path = self.dir / "USER.md"
        self.memory_path = self.dir / "MEMORY.md"
        if not self.user_path.exists():
            self.user_path.write_text(_USER_HEADER, encoding="utf-8")
        if not self.memory_path.exists():
            self.memory_path.write_text(_MEMORY_HEADER, encoding="utf-8")

    # -- read --------------------------------------------------------------

    def read_user(self) -> str:
        return self.user_path.read_text(encoding="utf-8", errors="replace")

    def read_memory(self) -> str:
        return self.memory_path.read_text(encoding="utf-8", errors="replace")

    def block(self) -> str:
        """Compact prompt block combining both files (trimmed)."""
        user = self.read_user().strip()
        mem = self.read_memory().strip()
        parts: list[str] = []
        if user and user != _USER_HEADER.strip():
            parts.append("USER PROFILE (curated notes about the user):\n" + user[:_MAX_INJECT])
        if mem and mem != _MEMORY_HEADER.strip():
            parts.append("MEMORY (your long-term working notes):\n" + mem[:_MAX_INJECT])
        return "\n\n".join(parts)

    # -- write -------------------------------------------------------------

    def write_user(self, content: str) -> None:
        self.user_path.write_text(content.rstrip() + "\n", encoding="utf-8")

    def write_memory(self, content: str) -> None:
        self.memory_path.write_text(content.rstrip() + "\n", encoding="utf-8")

    def reset(self) -> None:
        """Wipe both curated files back to their empty headers."""
        self.user_path.write_text(_USER_HEADER, encoding="utf-8")
        self.memory_path.write_text(_MEMORY_HEADER, encoding="utf-8")

    def append_note(self, note: str) -> None:
        """Append a dated bullet to MEMORY.md."""
        note = note.strip()
        if not note:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.memory_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- ({stamp}) {note}")
