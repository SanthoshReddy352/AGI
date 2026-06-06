"""P3.16 — Runtime interrupt: graceful SIGINT → SIGKILL escalation.

When the user says "stop" mid-tool-call, the interrupt bus fires. This
module's wire_interrupt_bus() subscriber translates that signal into an
OS-level interrupt for every process registered in the ProcessRegistry,
with a 3-second SIGKILL escalation if the process ignores SIGINT.

Usage in tool code:
    from core.runtime.process_registry import get_process_registry
    from core.runtime import interrupt as rt_interrupt

    proc = subprocess.Popen(...)
    get_process_registry().register(proc.pid, label="nmap-scan", session_id=sid)
    try:
        proc.wait(timeout=300)
    finally:
        get_process_registry().unregister(proc.pid)
"""
from __future__ import annotations

import os
import signal
import threading
import time

from core.logger import logger
from core.runtime.process_registry import get_process_registry


def cancel_process(pid: int, timeout_sec: float = 3.0) -> bool:
    """Send SIGINT to pid; escalate to SIGKILL after timeout_sec if still alive.

    Returns True if the initial signal was delivered, False if the process
    did not exist or we lacked permission.
    """
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return False
    except PermissionError:
        logger.warning("[interrupt] permission denied signalling pid=%d", pid)
        return False

    def _escalate() -> None:
        time.sleep(timeout_sec)
        try:
            os.kill(pid, signal.SIGKILL)
            logger.info("[interrupt] SIGKILL escalated to pid=%d", pid)
        except (ProcessLookupError, PermissionError):
            pass  # already dead — normal path

    threading.Thread(target=_escalate, daemon=True).start()
    return True


def cancel_session(session_id: str, timeout_sec: float = 3.0) -> int:
    """Cancel all processes registered for session_id. Returns count cancelled."""
    registry = get_process_registry()
    entries = registry.all_for_session(session_id)
    count = 0
    for entry in entries:
        if cancel_process(entry.pid, timeout_sec=timeout_sec):
            registry.unregister(entry.pid)
            count += 1
    return count


def cancel_current(timeout_sec: float = 3.0) -> int:
    """Cancel every currently-registered process. Returns count cancelled."""
    registry = get_process_registry()
    entries = registry.all()
    count = 0
    for entry in entries:
        if cancel_process(entry.pid, timeout_sec=timeout_sec):
            registry.unregister(entry.pid)
            count += 1
    return count


def wire_interrupt_bus(bus=None) -> None:
    """Subscribe to the InterruptBus so user 'stop' commands auto-cancel subprocesses.

    Idempotent — safe to call multiple times; each call adds one subscriber.
    Call once from app startup (e.g. FridayApp.__init__) after the bus is ready.
    """
    if bus is None:
        from core.interrupt_bus import get_interrupt_bus  # noqa: PLC0415
        bus = get_interrupt_bus()

    def _on_interrupt(signal_obj) -> None:
        count = cancel_current(timeout_sec=3.0)
        if count:
            logger.info(
                "[interrupt] bus signal '%s' cancelled %d subprocess(es)",
                signal_obj.reason,
                count,
            )

    bus.subscribe("all", _on_interrupt)
