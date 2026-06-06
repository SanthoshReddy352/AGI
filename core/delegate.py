"""P3.12 — Delegate: spawn a child turn-orchestrator for long-running queries.

Runs a query through the CommandRouter in a background thread, letting the
main voice pipeline stay responsive. The caller can either fire-and-forget
(run_async) or block with a timeout (run_and_wait).

Usage:
    d = Delegate(app.router)
    result, timed_out = d.run_and_wait("summarise the last 10 news headlines", timeout_sec=30)
    if not timed_out:
        app.say(result)

    # Fire-and-forget with callback:
    d.run_async("long research query", callback=lambda r: app.say(r))
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from core.logger import logger


class Delegate:
    """Runs a query through the router in a background thread."""

    def __init__(self, router) -> None:
        self._router = router

    def run(self, query: str, timeout_sec: float = 60.0) -> str:
        """Run query synchronously (blocks the calling thread). Returns response text."""
        try:
            result = self._router.process_text(query)
            return result if isinstance(result, str) else str(result or "")
        except Exception as exc:
            logger.error("[delegate] sub-turn failed: %s", exc)
            return f"Delegation failed: {exc}"

    def run_async(
        self,
        query: str,
        callback: Optional[Callable[[str], None]] = None,
        timeout_sec: float = 60.0,
    ) -> threading.Thread:
        """Start query in a daemon thread. Calls callback(result) when done."""

        def _worker() -> None:
            result = self.run(query, timeout_sec=timeout_sec)
            if callback:
                try:
                    callback(result)
                except Exception as exc:
                    logger.error("[delegate] callback raised: %s", exc)

        t = threading.Thread(target=_worker, daemon=True, name="friday-delegate")
        t.start()
        return t

    def run_and_wait(
        self, query: str, timeout_sec: float = 60.0
    ) -> tuple[str, bool]:
        """Run in background and block until done or timeout.

        Returns (result, timed_out). On timeout returns a descriptive string
        and timed_out=True; the background thread still finishes on its own.
        """
        result_holder: list[str] = []
        done = threading.Event()

        def _worker() -> None:
            result_holder.append(self.run(query, timeout_sec=timeout_sec))
            done.set()

        threading.Thread(target=_worker, daemon=True, name="friday-delegate-wait").start()
        completed = done.wait(timeout=timeout_sec)
        if not completed:
            return "That's taking longer than expected — I'll update you when it's done.", True
        return result_holder[0] if result_holder else "", False


def make_delegate(router) -> Delegate:
    """Factory: create a Delegate bound to the given router."""
    return Delegate(router)
