"""Regression: Extension capabilities that carry metadata must land in the
router's `_tools_by_name` map, not just the capability registry.

Root cause of the 2026-05-25 "email workflow not working" report: the
extension protocol called `router.register_tool(spec, handler, metadata=...)`
but the router's kwarg is `capability_meta`. The TypeError was swallowed by a
bare `except Exception: pass`, so every Extension capability with metadata
(all of workspace_agent's email/calendar/drive tools) silently never reached
the router. IntentRecognizer then couldn't see them and the turn fell through
to the chat model, which fabricated "Checking your mail...".
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.capability_registry import CapabilityRegistry
from core.extensions.protocol import ExtensionContext
from core.router import CommandRouter


def _make_ctx():
    router = CommandRouter(MagicMock())
    app = MagicMock()
    app.router = router
    ctx = ExtensionContext(
        registry=CapabilityRegistry(),
        events=MagicMock(),
        consent=MagicMock(),
        config={},
        app_ref=app,
    )
    return ctx, router


def test_capability_with_metadata_registers_in_router():
    ctx, router = _make_ctx()
    ctx.register_capability(
        {"name": "check_unread_emails", "description": "x", "parameters": {}},
        lambda raw, args: "ok",
        metadata={
            "connectivity": "online",
            "permission_mode": "always_ok",
            "latency_class": "slow",
            "side_effect_level": "read",
        },
    )
    assert "check_unread_emails" in router._tools_by_name
    assert router._tools_by_name["check_unread_emails"]["capability_meta"]["connectivity"] == "online"


def test_capability_without_metadata_still_registers():
    ctx, router = _make_ctx()
    ctx.register_capability(
        {"name": "no_meta_tool", "description": "x", "parameters": {}},
        lambda raw, args: "ok",
    )
    assert "no_meta_tool" in router._tools_by_name


@pytest.mark.parametrize("name", [
    "check_unread_emails", "summarize_inbox", "read_latest_email",
])
def test_email_tools_route_after_registration(name):
    """End-to-end: register an email tool with metadata, then confirm the
    recognizer routes the matching phrase to it (it couldn't before the fix)."""
    from core.intent_recognizer import IntentRecognizer

    ctx, router = _make_ctx()
    ctx.register_capability(
        {"name": name, "description": "x", "parameters": {}},
        lambda raw, args: "ok",
        metadata={"connectivity": "online", "side_effect_level": "read"},
    )
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds

    phrase = {
        "check_unread_emails": "check my mail",
        "summarize_inbox": "summarize my emails",
        "read_latest_email": "read my latest email",
    }[name]
    actions = IntentRecognizer(router).plan(phrase)
    assert actions and actions[0]["tool"] == name
