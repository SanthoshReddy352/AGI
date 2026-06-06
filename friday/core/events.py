"""Event bus + fan-out for FRIDAY v2.

The agent emits typed events (``turn_started``, ``preamble``, ``tool_started``,
``tool_finished``, ``turn_completed``, plus ``token`` for streaming). Multiple
sinks consume the same stream: the narration engine (→ Piper TTS), the backend
WebSocket (→ GUI), and logging.

``fanout`` adapts several ``emit(event_type, payload)`` callables into one, so the
agent's single ``emit`` hook can drive all of them.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from friday.core.logger import logger

EmitFn = Callable[[str, dict], None]


class EventBus:
    """Minimal pub/sub. Subscribe by event type (or ``"*"`` for all)."""

    def __init__(self):
        self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        self._subs[event_type].append(callback)

    def publish(self, event_type: str, payload: dict) -> None:
        for cb in self._subs.get(event_type, []):
            self._safe(cb, payload)
        for cb in self._subs.get("*", []):
            self._safe(cb, {"type": event_type, **payload})

    @staticmethod
    def _safe(cb, payload):
        try:
            cb(payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("event handler %s failed: %s", cb, exc)

    def emit(self, event_type: str, payload: dict) -> None:
        """Adapter matching the agent's ``emit(event_type, payload)`` signature."""
        self.publish(event_type, payload)


def fanout(*sinks: EmitFn) -> EmitFn:
    """Combine several emit callables into one."""

    def emit(event_type: str, payload: dict) -> None:
        for sink in sinks:
            if sink is None:
                continue
            try:
                sink(event_type, payload)
            except Exception as exc:  # noqa: BLE001
                logger.error("event sink failed: %s", exc)

    return emit
