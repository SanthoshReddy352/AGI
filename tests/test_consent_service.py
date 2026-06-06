"""Tests for ConsentService — Track 4.2.

Restores tiered consent: online tools route through user prompt unless
session-cached as approved; local tools silent-allow.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.kernel.consent import ConsentDecision, ConsentResult, ConsentService


def _descriptor(
    connectivity: str = "local",
    side_effect_level: str = "read",
    permission_mode: str = "always_ok",
):
    return SimpleNamespace(
        connectivity=connectivity,
        side_effect_level=side_effect_level,
        permission_mode=permission_mode,
    )


def test_evaluate_silent_allows_local_read():
    svc = ConsentService()
    result = svc.evaluate("get_time", _descriptor("local", "read"), "what time is it")
    assert result.allowed
    assert result.decision == ConsentDecision.ALLOW
    assert not result.needs_confirmation


def test_evaluate_silent_allows_local_write():
    """Local writes (file create, dictation save, etc.) silent-allow.
    Track 4.2b narrowed the stricter rule to `critical` only — `write`
    is too common a side-effect to gate on every use. `write` tools
    get the next-pass review (4.2c) with per-tool opt-in metadata."""
    svc = ConsentService()
    result = svc.evaluate("manage_file", _descriptor("local", "write"), "create my.txt")
    assert result.allowed


def test_evaluate_asks_for_local_critical():
    """Track 4.2b: critical-side-effect tools (destructive: delete,
    drop, format) prompt the user before the first session use."""
    svc = ConsentService()
    result = svc.evaluate(
        "delete_workspace", _descriptor("local", "critical"), "delete X"
    )
    assert not result.allowed
    assert result.needs_confirmation


def test_evaluate_silent_allows_critical_after_session_approval():
    """Track 4.2b: once the user approves a critical tool, subsequent
    calls silent-allow within the session (same as online tools)."""
    svc = ConsentService()
    desc = _descriptor("local", "critical")
    assert svc.evaluate("delete_workspace", desc, "X").needs_confirmation
    svc.mark_approved("delete_workspace")
    assert svc.evaluate("delete_workspace", desc, "X").allowed


def test_evaluate_asks_for_permission_mode_ask_first():
    """Track 4.2c: per-tool opt-in via `permission_mode: ask_first` in
    the spec metadata. Lets a plugin author declare a routine `write`
    tool as sensitive without changing the global write rule."""
    svc = ConsentService()
    desc = _descriptor("local", "write", permission_mode="ask_first")
    result = svc.evaluate("send_message", desc, "send hello")
    assert not result.allowed
    assert result.needs_confirmation


def test_evaluate_silent_allows_ask_first_after_session_approval():
    """Track 4.2c: same session-cache mechanism as online / critical."""
    svc = ConsentService()
    desc = _descriptor("local", "write", permission_mode="ask_first")
    assert svc.evaluate("send_message", desc, "X").needs_confirmation
    svc.mark_approved("send_message")
    assert svc.evaluate("send_message", desc, "X").allowed


def test_evaluate_silent_allows_when_permission_mode_is_always_ok():
    """Default `permission_mode: always_ok` keeps the silent-allow behavior."""
    svc = ConsentService()
    desc = _descriptor("local", "write", permission_mode="always_ok")
    assert svc.evaluate("manage_file", desc, "create X").allowed


def test_evaluate_asks_for_online_first_time():
    svc = ConsentService()
    result = svc.evaluate("search_web", _descriptor("online", "read"), "search X")
    assert not result.allowed
    assert result.needs_confirmation
    assert result.decision == ConsentDecision.ASK
    assert "online" in result.prompt.lower() or "yes or no" in result.prompt.lower()


def test_evaluate_silent_allows_after_session_approval():
    svc = ConsentService()
    # First call asks.
    assert svc.evaluate("search_web", _descriptor("online"), "X").needs_confirmation
    # Mark approved (simulates user replying "yes" in the pending-online flow).
    svc.mark_approved("search_web")
    # Subsequent calls silent-allow.
    assert svc.evaluate("search_web", _descriptor("online"), "X").allowed


def test_mark_approved_is_per_tool_not_global():
    svc = ConsentService()
    svc.mark_approved("search_web")
    # Different tool still prompts even after approving the first.
    assert svc.evaluate("send_email", _descriptor("online"), "send X").needs_confirmation
    # Same tool stays silent.
    assert svc.evaluate("search_web", _descriptor("online"), "X").allowed


def test_clear_session_approvals_resets_cache():
    svc = ConsentService()
    svc.mark_approved("search_web")
    assert svc.evaluate("search_web", _descriptor("online"), "X").allowed
    svc.clear_session_approvals()
    assert svc.evaluate("search_web", _descriptor("online"), "X").needs_confirmation


def test_evaluate_handles_missing_descriptor():
    """Defensive: no descriptor (e.g. partial test apps) → allow."""
    svc = ConsentService()
    assert svc.evaluate("anything", None, "text").allowed


def test_evaluate_handles_descriptor_with_no_connectivity_attr():
    """Defensive: descriptor missing `connectivity` attribute → default
    to 'local' (silent allow). The string-coerce in evaluate handles
    None / empty values."""
    svc = ConsentService()
    descriptor = SimpleNamespace(side_effect_level="read")  # no connectivity
    assert svc.evaluate("any_tool", descriptor, "text").allowed


def test_mark_approved_with_empty_tool_name_is_noop():
    svc = ConsentService()
    svc.mark_approved("")
    # Empty key wasn't added — evaluating a non-empty tool still prompts.
    assert svc.evaluate("search_web", _descriptor("online"), "X").needs_confirmation


def test_consent_result_factories():
    """Track 4.2: factory methods produce the right decision enum."""
    assert ConsentResult.allow().decision == ConsentDecision.ALLOW
    assert ConsentResult.ask("hey?").decision == ConsentDecision.ASK
    assert ConsentResult.ask("hey?").prompt == "hey?"
    assert ConsentResult.deny().decision == ConsentDecision.DENY
