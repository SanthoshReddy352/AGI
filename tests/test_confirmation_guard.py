"""Phase 3 — ConfirmationGuard (reusable confirm-before-destructive guard)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflows.confirmation import ConfirmationGuard, PENDING_KEY


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self):
        self._states = {}

    def get_session_state(self, session_id):
        return dict(self._states.get(session_id, {}))

    def save_session_state(self, session_id, state):
        self._states[session_id] = dict(state)


class _Result:
    def __init__(self, output="", ok=True, error=""):
        self.output = output
        self.ok = ok
        self.error = error


class _FakeExecutor:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def execute(self, name, raw_text, args):
        self.calls.append((name, raw_text, dict(args)))
        return self._result


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeApp:
    def __init__(self, *, result=None, config=None):
        self.context_store = _FakeStore()
        self.session_id = "sess-1"
        self.capability_executor = _FakeExecutor(result or _Result("done"))
        self.config = config if config is not None else _FakeConfig()


# ---------------------------------------------------------------------------
# arm / peek / clear
# ---------------------------------------------------------------------------

def test_arm_persists_and_returns_prompt():
    app = _FakeApp()
    guard = ConfirmationGuard(app)
    prompt = guard.arm(action="lock_screen", preview="I'll lock the screen.")

    assert "lock the screen" in prompt.lower()
    assert "yes to confirm" in prompt.lower()
    pending = guard.peek()
    assert pending["action"] == "lock_screen"
    # The raw session state carries the armed action under the shared key.
    assert app.context_store.get_session_state("sess-1")[PENDING_KEY]["action"] == "lock_screen"


def test_peek_returns_none_when_nothing_armed():
    assert ConfirmationGuard(_FakeApp()).peek() is None


def test_clear_pops_armed_action():
    guard = ConfirmationGuard(_FakeApp())
    guard.arm(action="delete_goal", args={"goal_id": "g1"}, preview="x")
    popped = guard.clear()
    assert popped["action"] == "delete_goal"
    assert popped["args"] == {"goal_id": "g1"}
    assert guard.peek() is None  # gone after clear


# ---------------------------------------------------------------------------
# confirm / cancel
# ---------------------------------------------------------------------------

def test_confirm_redispatches_with_confirmed_flag():
    app = _FakeApp(result=_Result("Screen locked."))
    guard = ConfirmationGuard(app)
    guard.arm(action="lock_screen", args={}, preview="I'll lock the screen.")

    out = guard.confirm(raw_text="yes")
    assert out == "Screen locked."
    name, _raw, args = app.capability_executor.calls[0]
    assert name == "lock_screen"
    assert args["_confirmed"] is True
    # Pending cleared after confirm so it can't fire twice.
    assert guard.peek() is None


def test_confirm_passes_through_resolved_args():
    app = _FakeApp(result=_Result("Turned on lamp."))
    guard = ConfirmationGuard(app)
    guard.arm(action="ha_turn_on", args={"entity": "lamp"}, preview="x")
    guard.confirm()
    _name, _raw, args = app.capability_executor.calls[0]
    assert args["entity"] == "lamp"
    assert args["_confirmed"] is True


def test_confirm_with_nothing_armed_is_graceful():
    out = ConfirmationGuard(_FakeApp()).confirm()
    assert "nothing waiting" in out.lower()


def test_confirm_reports_handler_error():
    app = _FakeApp(result=_Result(output=None, ok=False, error="boom"))
    guard = ConfirmationGuard(app)
    guard.arm(action="lock_screen", preview="x")
    assert guard.confirm() == "boom"


def test_cancel_clears_and_acknowledges():
    guard = ConfirmationGuard(_FakeApp())
    guard.arm(action="lock_screen", preview="x")
    out = guard.cancel()
    assert "cancel" in out.lower()
    assert guard.peek() is None


# ---------------------------------------------------------------------------
# needs_confirmation / enabled toggle
# ---------------------------------------------------------------------------

def test_needs_confirmation_true_on_first_call():
    assert ConfirmationGuard(_FakeApp()).needs_confirmation({}) is True


def test_needs_confirmation_false_when_already_confirmed():
    assert ConfirmationGuard(_FakeApp()).needs_confirmation({"_confirmed": True}) is False


def test_disabled_by_config_skips_confirmation():
    app = _FakeApp(config=_FakeConfig({"routing.confirm_destructive": False}))
    guard = ConfirmationGuard(app)
    assert guard.enabled is False
    assert guard.needs_confirmation({}) is False


def test_enabled_defaults_true_without_config_key():
    assert ConfirmationGuard(_FakeApp()).enabled is True
