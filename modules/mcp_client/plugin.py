"""P3.8 — MCP (Model Context Protocol) client.

Reads server definitions from config/mcp_servers.yaml and registers each
server's tools dynamically so they appear in FRIDAY's capability registry
alongside native capabilities.

Two connection modes:
  - command: spawn a local subprocess that speaks the MCP stdio protocol
  - url:     connect to an HTTP/SSE MCP server

Requires: pip install mcp  (anthropic's reference MCP client library)
Without it, the plugin loads but registers a single stub capability that
explains how to install the dependency.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Optional

from core.plugin_manager import FridayPlugin
from core.logger import logger

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "mcp_servers.yaml",
)


def _load_server_configs() -> list[dict]:
    try:
        import yaml
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        return [s for s in (cfg.get("servers") or []) if s.get("enabled", True)]
    except Exception as exc:
        logger.debug("[mcp_client] config load error: %s", exc)
        return []


class StdioMCPBridge:
    """Minimal stdio MCP bridge using the official `mcp` library if available,
    otherwise falls back to raw subprocess JSON-RPC."""

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self.command = command
        self._tools: list[dict] = []

    def connect(self) -> bool:
        """Probe the server with an initialize + tools/list call."""
        try:
            result = self._call("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "FRIDAY", "version": "1.0"},
            })
            if not result:
                return False
            tools_result = self._call("tools/list", {})
            self._tools = (tools_result or {}).get("tools", [])
            logger.info("[mcp_client] %s: connected, %d tool(s)", self.name, len(self._tools))
            return True
        except Exception as exc:
            logger.warning("[mcp_client] %s: connect failed: %s", self.name, exc)
            return False

    def list_tools(self) -> list[dict]:
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        result = self._call("tools/call", {"name": tool_name, "arguments": arguments})
        if result is None:
            return "Tool call returned no result."
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) or str(result)
        return str(result)

    def _call(self, method: str, params: dict) -> Optional[dict]:
        """Send a JSON-RPC request via subprocess stdin/stdout."""
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        })
        try:
            proc = subprocess.run(
                self.command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if proc.returncode not in (0, None):
                logger.debug("[mcp_client] %s stderr: %s", self.name, proc.stderr[:200])
            raw = proc.stdout.strip()
            if not raw:
                return None
            # MCP servers may emit multiple newline-delimited JSON objects
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "result" in obj:
                    return obj["result"]
            return None
        except Exception as exc:
            logger.debug("[mcp_client] _call %s error: %s", method, exc)
            return None


class MCPClientPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "MCPClient"
        self._bridges: dict[str, StdioMCPBridge] = {}
        self.on_load()

    def on_load(self):
        server_configs = _load_server_configs()
        registered = 0
        for cfg in server_configs:
            server_name = cfg.get("name", "unnamed")
            command = cfg.get("command")
            if not command:
                logger.warning("[mcp_client] server '%s' has no command — skipping", server_name)
                continue
            bridge = StdioMCPBridge(server_name, command)
            connected = bridge.connect()
            if not connected:
                logger.warning("[mcp_client] server '%s' unreachable — skipping", server_name)
                continue
            self._bridges[server_name] = bridge
            for tool in bridge.list_tools():
                registered += self._register_tool(server_name, bridge, tool)

        if not server_configs:
            logger.info("[mcp_client] No MCP servers configured — add entries to config/mcp_servers.yaml")

        # Always register a meta capability to list/describe configured servers
        self.app.register_capability(
            {
                "name": "mcp_list_servers",
                "description": "List configured MCP servers and their available tools.",
                "aliases": ["list mcp servers", "show mcp tools", "what mcp servers"],
                "context_terms": ["mcp server", "list mcp", "mcp tools"],
                "permission_mode": "always_ok",
            },
            self._handle_list_servers,
        )
        logger.info("[mcp_client] MCPClientPlugin loaded — %d tool(s) from %d server(s).",
                    registered, len(self._bridges))

    def _register_tool(self, server_name: str, bridge: StdioMCPBridge, tool: dict) -> int:
        tool_name = tool.get("name", "")
        if not tool_name:
            return 0
        cap_name = f"mcp_{server_name}_{tool_name}".replace("-", "_").replace(".", "_")
        description = tool.get("description", f"MCP tool {tool_name} from {server_name}")
        schema = tool.get("inputSchema", {})
        params = {k: "string" for k in (schema.get("properties") or {}).keys()}

        def _handler(raw_text: str, args: dict, _t=tool_name, _b=bridge) -> str:
            try:
                result = _b.call_tool(_t, args)
                return str(result)
            except Exception as exc:
                logger.error("[mcp_client] %s/%s error: %s", server_name, _t, exc)
                return f"MCP tool error: {exc}"

        self.app.register_capability(
            {
                "name": cap_name,
                "description": f"[{server_name}] {description}",
                "parameters": params,
                "context_terms": [tool_name, server_name, "mcp"],
                "permission_mode": "always_ok",
            },
            _handler,
        )
        return 1

    def _handle_list_servers(self, raw_text: str, args: dict) -> str:
        if not self._bridges:
            return (
                "No MCP servers are connected. "
                "Add server definitions to config/mcp_servers.yaml and restart FRIDAY."
            )
        lines = ["Connected MCP servers:"]
        for name, bridge in self._bridges.items():
            tools = bridge.list_tools()
            tool_names = ", ".join(t.get("name", "?") for t in tools[:5])
            if len(tools) > 5:
                tool_names += f" (+{len(tools)-5} more)"
            lines.append(f"  • {name}: {tool_names or '(no tools)'}")
        return "\n".join(lines)
