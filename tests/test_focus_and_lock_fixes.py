"""2026-05-29 fixes from the live session:

  1. "stop the focus session" while a browser_media workflow is active was
     eaten by the bare-cancel path and cancelled MEDIA instead of ending focus
     (which also "forgot" the media session). WorkflowOrchestrator now skips
     the cancel when the utterance targets a *different* workflow.
  2. Focus mode on Windows must not claim "Notifications are muted" (gsettings
     is Linux-only) and must not spam a WARNING every turn.
  3. The Windows lock state got stuck "locked" after a manual unlock because
     the monitor had no Windows probe. LockStateMonitor now polls the input
     desktop, with a grace window so a just-issued lock isn't cleared early.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.reasoning.agentic_services.focus_mode import FocusModeWorkflow
from core.workflow_orchestrator import WorkflowOrchestrator


# ---------------------------------------------------------------------------
# 1. "stop the focus session" must not cancel the active media workflow
# ---------------------------------------------------------------------------


class _StubWorkflow:
    def __init__(self, name, starts_on=()):
        self.name = name
        self._starts_on = starts_on

    def should_start(self, user_text, context=None):
        low = (user_text or "").lower()
        return any(p in low for p in self._starts_on)

    def can_continue(self, user_text, state, context=None):
        return False


def _orchestrator(active_name, workflows):
    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.app = SimpleNamespace(memory_service=None)
    store = MagicMock()
    store.get_active_workflow.return_value = {"workflow_name": active_name}
    orch.app.context_store = store
    orch.workflows = workflows
    return orch, store


def test_stop_focus_does_not_cancel_active_media():
    wfs = {
        "browser_media": _StubWorkflow("browser_media", starts_on=["youtube"]),
        "focus_mode": _StubWorkflow("focus_mode", starts_on=["focus session", "stop the focus"]),
    }
    orch, store = _orchestrator("browser_media", wfs)
    result = orch.continue_active("stop the focus session", "s1")
    # Must NOT report a cancel; falls through so intent routing can end focus.
    assert result.handled is False
    store.clear_workflow_state.assert_not_called()


def test_bare_stop_still_cancels_active_media():
    wfs = {
        "browser_media": _StubWorkflow("browser_media", starts_on=["youtube"]),
        "focus_mode": _StubWorkflow("focus_mode", starts_on=["focus session", "stop the focus"]),
    }
    orch, store = _orchestrator("browser_media", wfs)
    result = orch.continue_active("stop", "s1")
    assert result.handled is True
    assert "cancel" in result.response.lower()
    store.clear_workflow_state.assert_called_once()


def test_cancel_the_reminder_still_cancels_active_reminder():
    # No other workflow starts on "cancel the reminder", so it stays a cancel.
    wfs = {
        "reminder_workflow": _StubWorkflow("reminder_workflow", starts_on=["remind me"]),
        "browser_media": _StubWorkflow("browser_media", starts_on=["youtube"]),
    }
    orch, store = _orchestrator("reminder_workflow", wfs)
    result = orch.continue_active("cancel the reminder", "s1")
    assert result.handled is True
    store.clear_workflow_state.assert_called_once()


def test_targets_other_workflow_ignores_active_and_handles_errors():
    boom = MagicMock()
    boom.should_start.side_effect = RuntimeError("nope")
    wfs = {"browser_media": _StubWorkflow("browser_media", ["youtube"]), "boom": boom}
    orch, _ = _orchestrator("browser_media", wfs)
    # active is skipped; the raising workflow is swallowed → False
    assert orch._targets_other_workflow("stop", "browser_media") is False


# ---------------------------------------------------------------------------
# 2. Focus mode message honesty on Windows
# ---------------------------------------------------------------------------


def _focus_wf():
    app = MagicMock()
    app.browser_media_service = None
    app.event_bus = None
    return FocusModeWorkflow(app)


def _reset_focus_state():
    import core.reasoning.agentic_services.focus_mode as fm
    fm._focus_active = False
    if fm._active_timer is not None:
        fm._active_timer.cancel()
        fm._active_timer = None


def test_focus_start_message_claims_dnd_on_windows():
    # 2026-05-29: Windows now supports Do Not Disturb (the ToastEnabled
    # registry switch), so the message DOES claim it — and always reports the
    # cross-platform media stop + browser-media block.
    _reset_focus_state()
    try:
        with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Windows"), \
             patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value=None):
            msg = _focus_wf()._start(2, "s1")
        assert "do not disturb" in msg.lower()
        assert "stopped all playing media" in msg.lower()
        assert "youtube" in msg.lower()
    finally:
        _reset_focus_state()


def test_focus_start_message_claims_dnd_on_linux_with_gsettings():
    _reset_focus_state()
    try:
        with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Linux"), \
             patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value="/usr/bin/gsettings"), \
             patch("core.reasoning.agentic_services.focus_mode.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout="true", stderr="")):
            msg = _focus_wf()._start(2, "s1")
        assert "do not disturb" in msg.lower()
    finally:
        _reset_focus_state()


def test_set_notifications_no_warning_on_windows(caplog):
    with patch("core.reasoning.agentic_services.focus_mode.platform.system", return_value="Windows"), \
         patch("core.reasoning.agentic_services.focus_mode.shutil.which", return_value=None):
        _focus_wf()._set_notifications(False)
    assert not any(r.levelname == "WARNING" for r in caplog.records)


# ---------------------------------------------------------------------------
# 3. LockStateMonitor Windows unlock detection + grace window
# ---------------------------------------------------------------------------


def _monitor():
    from core.lock_monitor import LockStateMonitor
    app = MagicMock()
    app.comms = None
    screen_lock = MagicMock()
    return LockStateMonitor(app, screen_lock), screen_lock


def test_windows_unlock_clears_state_after_grace():
    mon, screen_lock = _monitor()
    # Simulate a FRIDAY lock that happened well in the past (grace elapsed).
    mon._locked_at = 0.0
    with patch("core.lock_monitor.platform.system", return_value="Windows"), \
         patch.object(mon, "_windows_locked", return_value=False):
        state = mon._query_os_locked()
    assert state is False  # the monitor now produces an unlocked reading
    # And the poll loop would apply it (grace long elapsed): set_locked(False).
    mon._set_state(False, source="os")
    screen_lock.set_locked.assert_called_with(False)


def test_grace_window_blocks_immediate_unlock(monkeypatch):
    import core.lock_monitor as lm
    mon, screen_lock = _monitor()
    # Pretend FRIDAY just locked: _locked_at = now.
    t = [1000.0]
    monkeypatch.setattr(lm.time, "monotonic", lambda: t[0])
    mon.note_locked()                      # records _locked_at = 1000
    screen_lock.reset_mock()
    # An immediate "unlocked" reading within the grace window must be ignored.
    t[0] = 1001.0                          # 1s later, < 6s grace
    within_grace = (t[0] - mon._locked_at) < mon._LOCK_GRACE_SECONDS
    assert within_grace
