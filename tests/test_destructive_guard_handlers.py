"""Phase 3 — destructive handlers arm the confirmation guard.

Covers the Phase-3 *expansion* set wired after the initial group:
`shutdown_assistant` and `forget_memory` (the remaining clearly-destructive
capabilities). Each must arm the guard on the first call and run for real
only once `_confirmed` is set (the state the guard re-dispatches with).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# shutdown_assistant
# ---------------------------------------------------------------------------

def _system_plugin():
    from modules.system_control.plugin import SystemControlPlugin
    plugin = SystemControlPlugin.__new__(SystemControlPlugin)
    plugin.app = MagicMock()
    return plugin


def test_shutdown_arms_confirmation_first():
    plugin = _system_plugin()
    plugin.app.confirmation_guard.needs_confirmation.return_value = True
    plugin.app.confirmation_guard.arm.return_value = "I'll shut down. Shall I go ahead?"
    out = plugin.handle_shutdown("shut down", {})
    plugin.app.confirmation_guard.arm.assert_called_once()
    assert plugin.app.confirmation_guard.arm.call_args.kwargs["action"] == "shutdown_assistant"
    assert "go ahead" in out.lower()


def test_shutdown_proceeds_when_no_guard():
    plugin = _system_plugin()
    plugin.app.confirmation_guard = None
    # Stub the heavy shutdown internals so the test stays fast/offline.
    with patch("threading.Thread"):
        out = plugin.handle_shutdown("shut down", {"_confirmed": True})
    # Returns a farewell string rather than a confirmation prompt.
    assert "go ahead" not in out.lower()
    assert out  # some farewell


# ---------------------------------------------------------------------------
# forget_memory
# ---------------------------------------------------------------------------

def _memory_plugin(removed=True):
    from modules.memory_manager.plugin import MemoryManagerPlugin
    plugin = MemoryManagerPlugin.__new__(MemoryManagerPlugin)
    plugin.app = MagicMock()
    plugin.app.session_id = "sess-1"
    facade = MagicMock()
    facade.forget.return_value = removed
    plugin._facade = lambda: facade  # type: ignore[method-assign]
    plugin._session_id = lambda: "sess-1"  # type: ignore[method-assign]
    return plugin, facade


def test_forget_memory_arms_with_resolved_key():
    plugin, facade = _memory_plugin()
    plugin.app.confirmation_guard.needs_confirmation.return_value = True
    plugin.app.confirmation_guard.arm.return_value = "I'll forget your location. Shall I go ahead?"
    out = plugin._handle_forget_memory("forget my location", {"key": "location"})
    facade.forget.assert_not_called()  # armed, not yet forgotten
    kwargs = plugin.app.confirmation_guard.arm.call_args.kwargs
    assert kwargs["action"] == "forget_memory"
    assert kwargs["args"]["key"] == "location"
    assert "location" in out.lower()


def test_forget_memory_runs_when_confirmed():
    plugin, facade = _memory_plugin()
    plugin.app.confirmation_guard.needs_confirmation.return_value = False
    out = plugin._handle_forget_memory("", {"key": "location", "_confirmed": True})
    facade.forget.assert_called_once_with("sess-1", "location")
    assert "forgotten" in out.lower()


def test_forget_memory_asks_for_key_when_missing():
    plugin, _facade = _memory_plugin()
    out = plugin._handle_forget_memory("forget something", {})
    # Re-asks before ever touching the guard.
    assert "which fact" in out.lower()
