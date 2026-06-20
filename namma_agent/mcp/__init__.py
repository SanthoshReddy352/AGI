"""MCP (Model Context Protocol) client for Namma Agent.

Connects to configured stdio MCP servers and exposes their tools through the same
:class:`~namma_agent.core.tools.ToolRegistry` the native tools use — so a third-party
MCP server's tools are indistinguishable from built-ins to the agent.

Self-contained: a stdlib JSON-RPC-over-stdio client (no `mcp` SDK dependency).
"""
from namma_agent.mcp.client import StdioMCPClient
from namma_agent.mcp.manager import MCPManager

__all__ = ["StdioMCPClient", "MCPManager"]
