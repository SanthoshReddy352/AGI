"""Track 6.3 — ScreenLock unit tests."""
from __future__ import annotations

import hashlib

import pytest

from core.screen_lock import BLOCKED_WHEN_LOCKED, ScreenLock, _hash_pin


def _hex(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def test_default_state_unlocked():
    lock = ScreenLock(expected_hash=_hex("1234"))
    assert lock.is_locked() is False
    assert lock.is_configured() is True


def test_unconfigured_lock_explains_setup(monkeypatch):
    monkeypatch.delenv("FRIDAY_LOCK_PIN_HASH", raising=False)
    lock = ScreenLock(expected_hash="")
    assert lock.is_configured() is False
    msg = lock.lock()
    assert "FRIDAY_LOCK_PIN_HASH" in msg
    assert lock.is_locked() is False  # cannot lock without configuration


def test_lock_then_unlock_round_trip():
    lock = ScreenLock(expected_hash=_hex("4321"))
    lock.lock()
    assert lock.is_locked() is True
    ok, msg = lock.try_unlock("4321")
    assert ok is True
    assert lock.is_locked() is False
    assert "unlocked" in msg.lower()


def test_wrong_pin_keeps_locked():
    lock = ScreenLock(expected_hash=_hex("4321"))
    lock.lock()
    ok, msg = lock.try_unlock("0000")
    assert ok is False
    assert lock.is_locked() is True
    assert "wrong" in msg.lower()


def test_empty_pin_rejected():
    lock = ScreenLock(expected_hash=_hex("1"))
    lock.lock()
    ok, msg = lock.try_unlock("")
    assert ok is False
    assert "provide a pin" in msg.lower()


def test_is_allowed_respects_lock_state():
    lock = ScreenLock(expected_hash=_hex("9999"))
    # When unlocked: every tool is allowed.
    assert lock.is_allowed("any_tool_name") is True
    assert lock.is_allowed("launch_app") is True
    lock.lock()
    # When locked: only the screen-dependent denylist is refused; everything
    # else (chat, email, research, …) still runs.
    assert lock.is_allowed("llm_chat") is True
    assert lock.is_allowed("check_unread_emails") is True
    for name in BLOCKED_WHEN_LOCKED:
        assert lock.is_allowed(name) is False


def test_env_var_picked_up(monkeypatch):
    monkeypatch.setenv("FRIDAY_LOCK_PIN_HASH", _hex("env-pin"))
    lock = ScreenLock()
    assert lock.is_configured() is True
    lock.lock()
    ok, _ = lock.try_unlock("env-pin")
    assert ok is True


def test_hash_helper_matches_sha256():
    assert _hash_pin("abc") == hashlib.sha256(b"abc").hexdigest()
