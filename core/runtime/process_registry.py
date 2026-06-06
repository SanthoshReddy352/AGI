"""P3.16 — Process registry for long-running subprocesses.

Tracks every subprocess spawned by a tool call (nmap scans, web crawls,
browser sessions) so the interrupt layer can send a signal to the right PID.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessEntry:
    pid: int
    label: str
    session_id: str
    started_at: float = field(default_factory=time.time)


class ProcessRegistry:
    """Thread-safe registry of active child processes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, ProcessEntry] = {}

    def register(self, pid: int, label: str, session_id: str = "") -> None:
        with self._lock:
            self._entries[pid] = ProcessEntry(
                pid=pid, label=label, session_id=session_id
            )

    def unregister(self, pid: int) -> None:
        with self._lock:
            self._entries.pop(pid, None)

    def get(self, pid: int) -> Optional[ProcessEntry]:
        with self._lock:
            return self._entries.get(pid)

    def all_for_session(self, session_id: str) -> list[ProcessEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.session_id == session_id]

    def all(self) -> list[ProcessEntry]:
        with self._lock:
            return list(self._entries.values())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_REGISTRY = ProcessRegistry()


def get_process_registry() -> ProcessRegistry:
    return _REGISTRY
