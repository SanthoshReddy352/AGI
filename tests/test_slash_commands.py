"""Track 6.3 — slash command dispatcher tests.

The dispatcher must be safe to call without a fully-built FridayApp —
this module uses a SimpleNamespace stand-in so tests stay fast.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from unittest.mock import patch

from core.slash_commands import REGISTRY, dispatch, is_slash_command


def test_is_slash_command_positive_cases():
    assert is_slash_command("/help") is True
    assert is_slash_command("/research transformers") is True
    assert is_slash_command("  /lock ") is True


def test_is_slash_command_rejects_paths_and_chat():
    assert is_slash_command("/home/tricky/file.txt") is False
    assert is_slash_command("/") is False
    assert is_slash_command("hello /world") is False
    assert is_slash_command("") is False


def test_help_lists_every_registered_command():
    app = SimpleNamespace()
    response = dispatch(app, "/help")
    for name, _, _ in REGISTRY:
        assert f"/{name}" in response


def test_unknown_command_points_to_help():
    app = SimpleNamespace()
    response = dispatch(app, "/banana")
    assert "/help" in response.lower()
    assert "banana" in response


def test_lock_command_locks_os_session():
    """/lock now locks the real OS session (not the FRIDAY PIN gate)."""
    app = SimpleNamespace()
    with patch("modules.system_control.os_lock.lock_os_session",
               return_value=(True, "Screen locked.")) as m:
        response = dispatch(app, "/lock")
    m.assert_called_once()
    assert "locked" in response.lower()


def test_lock_command_reports_failure_message():
    app = SimpleNamespace()
    with patch("modules.system_control.os_lock.lock_os_session",
               return_value=(False, "I couldn't lock the screen — no supported locker.")):
        response = dispatch(app, "/lock")
    assert "couldn't lock" in response.lower()


def test_unlock_command_explains_system_password():
    app = SimpleNamespace()
    response = dispatch(app, "/unlock 1234")
    assert "system password" in response.lower()


def test_research_requires_topic():
    app = SimpleNamespace()
    response = dispatch(app, "/research")
    assert "usage" in response.lower()


def test_web_requires_query():
    app = SimpleNamespace()
    response = dispatch(app, "/web")
    assert "usage" in response.lower()


def test_voice_status_usage():
    app = SimpleNamespace()
    response = dispatch(app, "/voice maybe")
    assert "usage" in response.lower()


def test_non_slash_returns_none():
    app = SimpleNamespace()
    assert dispatch(app, "hello world") is None
    assert dispatch(app, "!ls") is None


# ---------------------------------------------------------------------------
# /new true-reset (2026-05-23 — Step 1)
# ---------------------------------------------------------------------------


class _FakeContextStore:
    def __init__(self):
        self.sessions = {"old-session": {"pending_memory_wipe": True}}
        self.started = []
        self.saved = []

    def start_session(self, meta):
        new_id = f"new-{len(self.started) + 1}"
        self.sessions[new_id] = {}
        self.started.append((new_id, meta))
        return new_id

    def get_session_state(self, sid):
        return dict(self.sessions.get(sid, {}))

    def save_session_state(self, sid, state):
        self.sessions[sid] = dict(state)
        self.saved.append((sid, dict(state)))


class _FakeBrowser:
    def __init__(self):
        self.reset_calls = 0

    def reset_session(self):
        self.reset_calls += 1


class _FakeAssistantContext:
    def __init__(self):
        self.history = ["old turn"]
        self.bound = None

    def bind_context_store(self, store, sid):
        self.bound = (store, sid)


class _FakeDialogState:
    def __init__(self):
        self.reset_reason = None

    def reset_pending(self, reason):
        self.reset_reason = reason


class _FakeRoutingState:
    def __init__(self):
        self.resets = 0

    def reset_for_turn(self):
        self.resets += 1


def _make_full_app():
    return SimpleNamespace(
        session_id="old-session",
        context_store=_FakeContextStore(),
        browser_media_service=_FakeBrowser(),
        assistant_context=_FakeAssistantContext(),
        dialog_state=_FakeDialogState(),
        routing_state=_FakeRoutingState(),
    )


def test_new_session_clears_browser_handles():
    app = _make_full_app()
    response = dispatch(app, "/new")
    assert "new conversation" in response.lower()
    assert app.browser_media_service.reset_calls == 1, (
        "browser_media_service.reset_session() must be called so the new "
        "conversation can't pause/resume the prior YouTube tab"
    )


def test_new_session_clears_pending_wipe_on_outgoing_session():
    """Regression: 'yes wipe everything' in the new session must NOT
    confirm a wipe that was queued before /new."""
    app = _make_full_app()
    # Pre-condition: outgoing session has a pending wipe.
    assert app.context_store.sessions["old-session"]["pending_memory_wipe"] is True
    dispatch(app, "/new")
    assert app.context_store.sessions["old-session"].get("pending_memory_wipe") is None


def test_new_session_kills_active_shell():
    """A live `!sudo` session must be cancelled by /new so its stdin
    can't be poisoned by the next conversation's first turn."""
    import core.shell_prefix as sp
    sp.cancel_active_session(reason="test pre")  # clean slate
    # Start a long-running shell so has_active_session() is True
    if not (lambda: True)():  # placeholder so pyflakes ignores
        pass
    # We can only really test this on POSIX (PTY); on Windows
    # `has_active_session()` is always False, so skip cleanly.
    import os
    if os.name != "posix":
        pytest.skip("PTY shell only on POSIX")

    sp.run_shell("!sleep 30")
    assert sp.has_active_session()
    app = _make_full_app()
    dispatch(app, "/new")
    assert not sp.has_active_session(), (
        "/new must cancel any live shell session via "
        "core.shell_prefix.cancel_active_session"
    )


def test_new_session_rotates_session_id():
    app = _make_full_app()
    old_id = app.session_id
    dispatch(app, "/new")
    assert app.session_id != old_id
    assert app.session_id.startswith("new-")


def test_new_session_resets_routing_state():
    app = _make_full_app()
    dispatch(app, "/new")
    assert app.routing_state.resets == 1


def test_clear_is_alias_for_new():
    """The /clear slash dispatches the same handler as /new — same
    cleanup must run."""
    app = _make_full_app()
    dispatch(app, "/clear")
    assert app.browser_media_service.reset_calls == 1
    assert app.routing_state.resets == 1


def test_new_session_survives_missing_optional_attrs():
    """If the app stand-in is missing browser/shell/routing, /new must
    not crash — it just skips those steps."""
    minimal = SimpleNamespace(session_id="old", context_store=_FakeContextStore())
    response = dispatch(minimal, "/new")
    assert "new conversation" in response.lower()
