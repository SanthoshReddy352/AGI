"""P3.15 — Smart home / Home Assistant plugin."""
import json
import pytest
from unittest.mock import MagicMock, patch

from modules.smart_home.plugin import (
    SmartHomePlugin, HomeAssistantClient, _extract_entity, _extract_number,
)


# ── HomeAssistantClient ───────────────────────────────────────────────────────

def test_client_turn_on_calls_correct_service():
    client = HomeAssistantClient("http://ha.local:8123", "token123")
    with patch.object(client, "_request", return_value={}) as mock_req:
        client.turn_on("light.bedroom")
    mock_req.assert_called_once()
    # _request(method, path, data) — path is args[1]
    path = mock_req.call_args.args[1]
    assert "light" in path
    assert "turn_on" in path


def test_client_turn_off_calls_correct_service():
    client = HomeAssistantClient("http://ha.local:8123", "token")
    with patch.object(client, "_request", return_value={}) as mock_req:
        client.turn_off("switch.fan")
    mock_req.assert_called_once()
    path = mock_req.call_args.args[1]
    assert "turn_off" in path


def test_client_get_state_calls_get():
    client = HomeAssistantClient("http://ha.local:8123", "token")
    with patch.object(client, "_request", return_value={"state": "on"}) as mock_req:
        state = client.get_state("light.bedroom")
    assert state["state"] == "on"
    mock_req.assert_called_with("GET", "states/light.bedroom")


def test_client_set_temperature():
    client = HomeAssistantClient("http://ha.local:8123", "token")
    with patch.object(client, "_request", return_value={}) as mock_req:
        client.set_temperature("climate.living_room", 22.0)
    call_data = mock_req.call_args.args[2]
    assert call_data["temperature"] == 22.0


# ── helpers ───────────────────────────────────────────────────────────────────

def test_extract_entity_strips_command_words():
    entity = _extract_entity("turn on the bedroom lights")
    assert "bedroom lights" in entity.lower() or "lights" in entity.lower()


def test_extract_number_finds_int():
    assert _extract_number("set to 22 degrees") == 22.0


def test_extract_number_finds_float():
    assert _extract_number("set to 22.5 degrees") == 22.5


def test_extract_number_none_if_missing():
    assert _extract_number("no numbers here") is None


# ── Plugin ────────────────────────────────────────────────────────────────────

def _make_plugin(ha_configured=False):
    app = MagicMock()
    app.register_capability = MagicMock()
    cfg = {"url": "http://ha.local:8123", "token": "t", "aliases": {}} if ha_configured else {}
    with patch("modules.smart_home.plugin._load_config", return_value=cfg):
        plugin = SmartHomePlugin(app)
    return plugin


def test_plugin_registers_four_capabilities():
    plugin = _make_plugin()
    # FridayPlugin shim forwards to app.router.register_tool
    calls = plugin.app.router.register_tool.call_args_list
    cap_names = [c.args[0]["name"] for c in calls]
    assert "ha_turn_on" in cap_names
    assert "ha_turn_off" in cap_names
    assert "ha_get_state" in cap_names
    assert "ha_set_temperature" in cap_names


def test_turn_on_not_configured_returns_guidance():
    plugin = _make_plugin(ha_configured=False)
    plugin._handle_turn_on = SmartHomePlugin._handle_turn_on.__get__(plugin, SmartHomePlugin)
    result = plugin._handle_turn_on("turn on lights", {"entity": "lights"})
    assert "not configured" in result.lower() or "home assistant" in result.lower()


def test_turn_on_calls_client():
    plugin = _make_plugin(ha_configured=True)
    plugin.app.confirmation_guard = None  # no guard → act directly
    plugin._handle_turn_on = SmartHomePlugin._handle_turn_on.__get__(plugin, SmartHomePlugin)
    with patch.object(plugin._client, "turn_on", return_value={}):
        result = plugin._handle_turn_on("turn on lights", {"entity": "lights"})
    assert "turned on" in result.lower()


def test_turn_on_arms_confirmation_first():
    """Phase 3: the first turn-on request arms the confirmation guard and
    does NOT call the client until confirmed."""
    plugin = _make_plugin(ha_configured=True)
    plugin.app.confirmation_guard.needs_confirmation.return_value = True
    plugin.app.confirmation_guard.arm.return_value = "I'll turn on lights. Shall I go ahead?"
    plugin._handle_turn_on = SmartHomePlugin._handle_turn_on.__get__(plugin, SmartHomePlugin)
    with patch.object(plugin._client, "turn_on", return_value={}) as m:
        result = plugin._handle_turn_on("turn on lights", {"entity": "lights"})
    m.assert_not_called()
    args, kwargs = plugin.app.confirmation_guard.arm.call_args
    assert kwargs["action"] == "ha_turn_on"
    assert "go ahead" in result.lower()


def test_alias_resolution():
    plugin = _make_plugin(ha_configured=True)
    plugin._aliases = {"bedroom lights": "light.bedroom_main"}
    resolved = plugin._resolve_entity("bedroom lights")
    assert resolved == "light.bedroom_main"
