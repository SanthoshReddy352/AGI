"""P3.8 — MCP client plugin."""
import json
import pytest
from unittest.mock import MagicMock, patch

from modules.mcp_client.plugin import (
    MCPClientPlugin, StdioMCPBridge, _load_server_configs,
)


# ── StdioMCPBridge ────────────────────────────────────────────────────────────

def test_bridge_list_tools_empty_before_connect():
    bridge = StdioMCPBridge("test", ["echo", "{}"])
    assert bridge.list_tools() == []


def test_bridge_connect_parses_tools():
    bridge = StdioMCPBridge("test", ["cat"])
    # Simulate a tools/list response
    init_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}})
    tools_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
        "tools": [{"name": "my_tool", "description": "A test tool", "inputSchema": {"properties": {}}}]
    }})

    call_count = [0]
    def fake_call(self_bridge, method, params):
        call_count[0] += 1
        if method == "initialize":
            return {"protocolVersion": "2024-11-05"}
        if method == "tools/list":
            return {"tools": [{"name": "my_tool", "description": "A test tool"}]}
        return None

    with patch.object(StdioMCPBridge, "_call", fake_call):
        connected = bridge.connect()
    assert connected
    assert any(t["name"] == "my_tool" for t in bridge.list_tools())


def test_bridge_call_tool_returns_text():
    bridge = StdioMCPBridge("test", ["cat"])
    bridge._tools = [{"name": "my_tool"}]

    def fake_call(self_bridge, method, params):
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "tool output"}]}
        return None

    with patch.object(StdioMCPBridge, "_call", fake_call):
        result = bridge.call_tool("my_tool", {})
    assert result == "tool output"


def test_bridge_connect_returns_false_on_failure():
    bridge = StdioMCPBridge("bad", ["/nonexistent/command"])
    connected = bridge.connect()
    assert connected is False


# ── Plugin ────────────────────────────────────────────────────────────────────

def _make_plugin():
    app = MagicMock()
    app.register_capability = MagicMock()
    with patch("modules.mcp_client.plugin._load_server_configs", return_value=[]):
        plugin = MCPClientPlugin(app)
    return plugin


def test_plugin_loads_with_no_servers():
    plugin = _make_plugin()
    # FridayPlugin shim forwards register_capability to app.router.register_tool
    calls = plugin.app.router.register_tool.call_args_list
    cap_names = [c.args[0]["name"] for c in calls]
    assert "mcp_list_servers" in cap_names


def test_list_servers_no_servers_configured():
    plugin = _make_plugin()
    plugin._handle_list_servers = MCPClientPlugin._handle_list_servers.__get__(
        plugin, MCPClientPlugin
    )
    plugin._bridges = {}
    result = plugin._handle_list_servers("", {})
    assert "no mcp" in result.lower() or "servers" in result.lower()


def test_list_servers_shows_bridge():
    plugin = _make_plugin()
    plugin._handle_list_servers = MCPClientPlugin._handle_list_servers.__get__(
        plugin, MCPClientPlugin
    )
    mock_bridge = MagicMock()
    mock_bridge.list_tools.return_value = [{"name": "list_issues"}]
    plugin._bridges = {"github": mock_bridge}
    result = plugin._handle_list_servers("", {})
    assert "github" in result
    assert "list_issues" in result


def test_load_server_configs_returns_empty_list_on_missing_file():
    with patch("modules.mcp_client.plugin._CONFIG_PATH", "/nonexistent.yaml"):
        configs = _load_server_configs()
    assert configs == []
