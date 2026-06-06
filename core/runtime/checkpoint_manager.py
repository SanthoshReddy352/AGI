"""P3.16 — Checkpoint manager for multi-step task resume.

Persists intermediate task state to data/checkpoints/{task_id}.json so a
long-running research workflow or multi-stage tool chain can resume after
an interrupt or restart without re-running completed steps.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional

_DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "checkpoints",
)


class CheckpointManager:
    def __init__(self, checkpoints_dir: str = _DEFAULT_DIR) -> None:
        self._dir = checkpoints_dir
        os.makedirs(self._dir, exist_ok=True)

    def save(self, task_id: str, state: dict[str, Any]) -> str:
        """Persist state for task_id. Returns the checkpoint file path."""
        path = os.path.join(self._dir, f"{task_id}.json")
        payload = {"task_id": task_id, "saved_at": time.time(), "state": state}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return path

    def load(self, task_id: str) -> Optional[dict[str, Any]]:
        """Return saved state dict, or None if no checkpoint exists."""
        path = os.path.join(self._dir, f"{task_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("state")

    def delete(self, task_id: str) -> bool:
        """Remove a checkpoint file. Returns True if it existed."""
        path = os.path.join(self._dir, f"{task_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def list_tasks(self) -> list[str]:
        """Return task IDs for all persisted checkpoints."""
        try:
            return [f[:-5] for f in os.listdir(self._dir) if f.endswith(".json")]
        except FileNotFoundError:
            return []

    def new_task_id(self) -> str:
        return uuid.uuid4().hex[:12]
