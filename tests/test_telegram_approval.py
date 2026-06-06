"""Phase 7 tests — Telegram approval gate, source-aware progress streaming,
security consent evaluation, end-to-end workflow integration."""
from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.capability_registry import CapabilityDescriptor
from core.kernel.consent import ConsentDecision, ConsentResult, ConsentService
from core.turn_context import TurnContext, turn_scope
from modules.comms.telegram import TelegramChannel


# ---------------------------------------------------------------------------
# TelegramChannel.request_approval — synchronous wait, options matching
# ---------------------------------------------------------------------------

def _make_channel_online() -> TelegramChannel:
    ch = TelegramChannel(token="t", chat_id="c")
    # Suppress every method that would otherwise hit the Telegram HTTP
    # API. The 2026-05-23 Track 6.3-followup added send_capturing_id +
    # edit_message + delete_message + chat_action; the old test fixture
    # only stubbed _send_sync, which left the new code path calling the
    # real network and failing.
    ch._send_sync = MagicMock()  # type: ignore[method-assign]
    ch.send_capturing_id = MagicMock(return_value=42)  # type: ignore[method-assign]
    ch.edit_message = MagicMock(return_value=True)  # type: ignore[method-assign]
    ch.delete_message = MagicMock(return_value=True)  # type: ignore[method-assign]
    ch.chat_action = MagicMock()  # type: ignore[method-assign]
    ch.typing_loop = MagicMock(return_value=(threading.Event(), MagicMock()))  # type: ignore[method-assign]
    return ch


def test_request_approval_resolves_on_matching_token():
    ch = _make_channel_online()
    result_box: dict = {}

    def waiter():
        result_box["v"] = ch.request_approval("Run lab scan?", timeout=2)

    t = threading.Thread(target=waiter)
    t.start()
    # Wait for the gate to open before sending the response.
    for _ in range(50):
        if ch._current_gate is not None:
            break
        time.sleep(0.01)
    consumed = ch.try_resolve_approval("approve")
    assert consumed is True
    t.join(timeout=2)
    assert result_box["v"] == "approve"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("yes", "approve"),
        ("YES", "approve"),
        ("ok", "approve"),
        ("confirm", "approve"),
        ("do it", "approve"),
        ("no", "deny"),
        ("nope", None),       # not in the canonical map -> NOT resolved
        ("cancel", "cancel"),
        ("abort", "cancel"),
        ("maybe", None),
    ],
)
def test_request_approval_token_matching(text, expected):
    ch = _make_channel_online()
    box: dict = {}
    t = threading.Thread(target=lambda: box.setdefault("v", ch.request_approval("Q?", timeout=2)))
    t.start()
    for _ in range(50):
        if ch._current_gate is not None:
            break
        time.sleep(0.01)
    consumed = ch.try_resolve_approval(text)
    if expected is None:
        assert consumed is False
        # Resolve manually so the thread can finish.
        assert ch.try_resolve_approval("cancel") is True
        t.join(timeout=2)
    else:
        assert consumed is True
        t.join(timeout=2)
        assert box["v"] == expected


def test_request_approval_times_out():
    ch = _make_channel_online()
    result = ch.request_approval("Q?", timeout=1)
    assert result == "timeout"


def test_request_approval_returns_deny_when_offline():
    ch = TelegramChannel(token="", chat_id="")
    assert ch.available is False
    assert ch.request_approval("Q?", timeout=1) == "deny"


def test_try_resolve_approval_no_open_gate_returns_false():
    ch = _make_channel_online()
    assert ch.try_resolve_approval("yes") is False


def test_request_approval_cancels_previous_open_gate():
    """If a second request_approval starts while the first is still open,
    the first must resolve to ``cancel`` so its caller can clean up."""
    ch = _make_channel_online()
    box: dict = {}
    t1 = threading.Thread(target=lambda: box.setdefault("a", ch.request_approval("Q1?", timeout=5)))
    t1.start()
    for _ in range(50):
        if ch._current_gate is not None:
            break
        time.sleep(0.01)
    # Now open a second gate.
    t2 = threading.Thread(target=lambda: box.setdefault("b", ch.request_approval("Q2?", timeout=2)))
    t2.start()
    t1.join(timeout=2)
    assert box["a"] == "cancel"
    # Resolve the second gate so the test exits cleanly.
    for _ in range(50):
        if ch._current_gate is not None:
            break
        time.sleep(0.01)
    ch.try_resolve_approval("approve")
    t2.join(timeout=2)
    assert box["b"] == "approve"


# ---------------------------------------------------------------------------
# TelegramInbound interception
# ---------------------------------------------------------------------------

def test_inbound_dispatch_consumes_approval_response_without_routing():
    from modules.comms.telegram import TelegramInbound
    ch = _make_channel_online()
    app = MagicMock()
    app.process_input.return_value = "FRIDAY response"
    inbound = TelegramInbound(ch, app)
    # Open the approval gate
    threading.Thread(
        target=lambda: ch.request_approval("Q?", timeout=2),
        daemon=True,
    ).start()
    for _ in range(50):
        if ch._current_gate is not None:
            break
        time.sleep(0.01)

    update = {"message": {"chat": {"id": "c"}, "text": "approve"}}
    inbound._dispatch(update)
    # The approval gate consumed it — process_input never called.
    app.process_input.assert_not_called()


def test_inbound_dispatch_routes_normal_text_when_no_gate_open():
    from modules.comms.telegram import TelegramInbound
    ch = _make_channel_online()
    app = MagicMock()
    app.process_input.return_value = ""
    app.telegram_turn_active = False
    inbound = TelegramInbound(ch, app)

    update = {"message": {"chat": {"id": "c"}, "text": "what's the weather"}}
    inbound._dispatch(update)
    # Give the worker thread a moment to call process_input.
    for _ in range(50):
        if app.process_input.called:
            break
        time.sleep(0.01)
    app.process_input.assert_called_once()
    args, kwargs = app.process_input.call_args
    assert "weather" in args[0]
    assert kwargs.get("source") == "telegram"


def test_inbound_dispatch_routes_slash_commands_to_friday():
    """Regression for 2026-05-23: pre-Track-6.3 code silently dropped
    every slash command except `/start`. The user reported '/new etc.
    don't work in Telegram'. Confirm every slash now forwards to
    process_input so core/slash_commands.dispatch can handle it.
    """
    from modules.comms.telegram import TelegramInbound
    ch = _make_channel_online()
    app = MagicMock()
    app.process_input.return_value = "ok"
    app.telegram_turn_active = False
    inbound = TelegramInbound(ch, app)

    for slash_text in ("/new", "/research transformers", "/lock", "/help"):
        app.process_input.reset_mock()
        update = {"message": {"chat": {"id": "c"}, "text": slash_text}}
        inbound._dispatch(update)
        for _ in range(50):
            if app.process_input.called:
                break
            time.sleep(0.01)
        app.process_input.assert_called_once()
        args, kwargs = app.process_input.call_args
        assert args[0].startswith("/"), f"slash command not forwarded: {slash_text}"
        assert kwargs.get("source") == "telegram"


def test_inbound_dispatch_strips_bot_username_suffix():
    """Telegram appends `@BotUsername` to slash commands in group chats —
    `/new@FridayBot foo` must reach FRIDAY as `/new foo`.
    """
    from modules.comms.telegram import TelegramInbound
    ch = _make_channel_online()
    app = MagicMock()
    app.process_input.return_value = "ok"
    app.telegram_turn_active = False
    inbound = TelegramInbound(ch, app)

    update = {"message": {"chat": {"id": "c"}, "text": "/research@FridayBot transformers"}}
    inbound._dispatch(update)
    for _ in range(50):
        if app.process_input.called:
            break
        time.sleep(0.01)
    app.process_input.assert_called_once()
    args, _ = app.process_input.call_args
    assert args[0] == "/research transformers"


def test_inbound_dispatch_start_still_handled_locally():
    """`/start` is Telegram-bot convention and stays handled inside the
    inbound dispatcher (with a welcome message); it must NOT reach
    process_input.
    """
    from modules.comms.telegram import TelegramInbound
    ch = _make_channel_online()
    app = MagicMock()
    app.process_input.return_value = "should not be called"
    app.telegram_turn_active = False
    inbound = TelegramInbound(ch, app)

    update = {"message": {"chat": {"id": "c"}, "text": "/start"}}
    inbound._dispatch(update)
    time.sleep(0.05)
    app.process_input.assert_not_called()


# ---------------------------------------------------------------------------
# ConsentService.evaluate_security_action
# ---------------------------------------------------------------------------

def test_consent_security_allows_read_only_local_capability():
    cs = ConsentService()
    desc = CapabilityDescriptor(
        name="local_read",
        description="x",
        side_effect_level="read",
        network_scope="local",
        requires_authorization=False,
    )
    result = cs.evaluate_security_action(desc)
    assert result.allowed is True


def test_consent_security_asks_when_requires_authorization():
    cs = ConsentService()
    desc = CapabilityDescriptor(
        name="host_service_scan",
        description="x",
        side_effect_level="read",
        network_scope="lab",
        requires_authorization=True,
    )
    result = cs.evaluate_security_action(desc)
    assert result.needs_confirmation is True
    assert "host_service_scan" in result.prompt
    assert "authorization" in result.prompt.lower()


def test_consent_security_asks_for_write_side_effect():
    cs = ConsentService()
    desc = CapabilityDescriptor(
        name="some_writer",
        description="x",
        side_effect_level="write",
        network_scope="local",
        requires_authorization=False,
    )
    result = cs.evaluate_security_action(desc)
    assert result.needs_confirmation is True


def test_consent_security_asks_for_public_network_scope():
    cs = ConsentService()
    desc = CapabilityDescriptor(
        name="external_thing",
        description="x",
        side_effect_level="read",
        network_scope="public",
        requires_authorization=False,
    )
    result = cs.evaluate_security_action(desc)
    assert result.needs_confirmation is True


def test_consent_security_handles_missing_descriptor():
    cs = ConsentService()
    assert cs.evaluate_security_action(None).allowed is True


# ---------------------------------------------------------------------------
# CommsPlugin.send_progress — source-aware routing
# ---------------------------------------------------------------------------

def _make_app_with_comms(*, telegram_available: bool = True) -> tuple[MagicMock, MagicMock]:
    """Construct a mocked app with a CommsPlugin attached. Returns (app, plugin)."""
    from modules.comms.plugin import CommsPlugin

    app = MagicMock()
    app.router = MagicMock()
    app.event_bus = MagicMock()
    app.tts = MagicMock()
    app.tts.speak = MagicMock()
    # Bypass plugin.on_load() — it would try to spin up Telegram/Discord polling.
    plugin = CommsPlugin.__new__(CommsPlugin)
    plugin.app = app
    plugin.name = "Comms"
    plugin.telegram = MagicMock()
    plugin.telegram.available = telegram_available
    plugin.telegram.send = MagicMock(return_value=True)
    plugin.discord = MagicMock()
    plugin.discord.available = False
    return app, plugin


def test_send_progress_routes_to_telegram_when_source_is_telegram():
    app, plugin = _make_app_with_comms(telegram_available=True)
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        plugin.send_progress("Step 1/2: live hosts found")
    plugin.telegram.send.assert_called_once()
    sent = plugin.telegram.send.call_args.args[0]
    assert "Step 1/2" in sent
    app.event_bus.publish.assert_not_called()
    app.tts.speak.assert_not_called()


def test_send_progress_routes_to_tts_when_source_is_voice():
    app, plugin = _make_app_with_comms(telegram_available=True)
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="voice", text="")
    with turn_scope(ctx):
        plugin.send_progress("voice update")
    app.tts.speak.assert_called_once()
    plugin.telegram.send.assert_not_called()


def test_send_progress_publishes_event_for_gui_source():
    app, plugin = _make_app_with_comms(telegram_available=True)
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="gui", text="")
    with turn_scope(ctx):
        plugin.send_progress("gui update")
    app.event_bus.publish.assert_called_once()
    event, payload = app.event_bus.publish.call_args.args
    assert event == "progress_update"
    assert payload["source"] == "gui"
    assert "gui update" in payload["text"]


def test_send_progress_telegram_unavailable_falls_back_to_eventbus():
    app, plugin = _make_app_with_comms(telegram_available=False)
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        plugin.send_progress("orphan update")
    plugin.telegram.send.assert_not_called()
    app.event_bus.publish.assert_called_once()


def test_handle_send_progress_capability_wraps_send_progress():
    app, plugin = _make_app_with_comms(telegram_available=True)
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        out = plugin.handle_send_progress("ignored", {"message": "progress!"})
    assert out == "ok"
    plugin.telegram.send.assert_called_once()


# ---------------------------------------------------------------------------
# TemplateWorkflow integration — approval gate fires for security workflow
# ---------------------------------------------------------------------------

def _make_app_with_security_registry(telegram_available: bool = True):
    """Build a full mock app suitable for TemplateWorkflow.run_with_replanning."""
    from core.capability_registry import CapabilityRegistry
    from core.kernel.consent import ConsentService
    from core.planning.replan_controller import ReplanController

    app = MagicMock()
    reg = CapabilityRegistry()
    reg.register_tool(
        {"name": "ping_sweep", "description": "x",
         "parameters": {"subnet": "..."}},
        handler=lambda t, a: "ok",
        metadata={
            "side_effect_level": "read",
            "network_scope": "lab",
            "requires_authorization": True,
        },
    )
    reg.register_tool(
        {"name": "host_service_scan", "description": "x",
         "parameters": {"target": "...", "profile": "...", "ports": "..."}},
        handler=lambda t, a: "ok",
        metadata={
            "side_effect_level": "read",
            "network_scope": "lab",
            "requires_authorization": True,
        },
    )
    app.capability_registry = reg
    app.config = MagicMock()
    app.config.get.side_effect = lambda key: {
        "routing.execution_engine": "ordered",
        "routing.use_replanning": True,
        "routing.max_workflow_steps": 12,
        "routing.max_step_retries": 2,
        "routing.workflow_total_timeout_sec": 60,
    }.get(key)
    app.ordered_tool_executor = MagicMock()
    app.task_graph_executor = MagicMock()
    app.context_store = MagicMock()
    app.context_store.get_active_workflow.return_value = None
    app.memory_service = None
    app.consent_service = ConsentService()
    app.replan_controller = ReplanController(workflow_total_timeout_sec=60)
    app.event_bus = MagicMock()
    app.tts = MagicMock()
    # Comms with telegram approval API mocked.
    app.comms = MagicMock()
    app.comms.telegram = MagicMock()
    app.comms.telegram.available = telegram_available
    app.comms.telegram.request_approval = MagicMock(return_value="approve")
    app.comms.send_progress = MagicMock()
    return app


def test_workflow_requests_approval_via_telegram_for_lab_scan():
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.ordered_tool_executor.execute.side_effect = ["sweep ok", "scan ok"]
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success", "summary": "live host"}
        ctx.observations["s2"] = {"status": "success", "summary": "open port"}
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "continue"
    # Both steps required authorization → two approval requests.
    assert app.comms.telegram.request_approval.call_count == 2
    # Progress emitted after each successful step.
    assert app.comms.send_progress.call_count == 2


def test_workflow_aborts_when_telegram_user_denies_approval():
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.comms.telegram.request_approval = MagicMock(return_value="deny")
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "refuse"
    app.ordered_tool_executor.execute.assert_not_called()
    app.comms.send_progress.assert_not_called()


def test_workflow_aborts_when_approval_times_out():
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.comms.telegram.request_approval = MagicMock(return_value="timeout")
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "stop"
    assert "timed out" in result.state["reason"]
    app.ordered_tool_executor.execute.assert_not_called()


def test_workflow_telegram_unavailable_refuses_security_steps():
    """When source=telegram but the channel isn't configured, security
    steps must refuse-by-default rather than auto-allow."""
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry(telegram_available=False)
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="telegram", text="")
    with turn_scope(ctx):
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "refuse"
    app.ordered_tool_executor.execute.assert_not_called()


def test_workflow_voice_source_auto_allows_security_steps_for_now():
    """Phase 7 keeps approval round-trips Telegram-only. Voice and GUI
    sources auto-allow so the existing voice consent flow remains
    authoritative for those channels."""
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.ordered_tool_executor.execute.side_effect = ["sweep ok", "scan ok"]
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="voice", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success"}
        ctx.observations["s2"] = {"status": "success"}
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "continue"
    # Telegram never consulted.
    app.comms.telegram.request_approval.assert_not_called()
    # Progress emission still fires (uses send_progress, which routes by source).
    assert app.comms.send_progress.call_count == 2
