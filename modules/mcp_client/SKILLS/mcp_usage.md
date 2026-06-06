---
name: mcp-usage
description: "Discover and call tools exposed by Model Context Protocol (MCP) servers."
source: "hermes-agent skills/mcp (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - mcp_list_servers
---

# MCP usage

## When to use

The user asks FRIDAY to use an external tool registered through an MCP server — usually because the user has configured something specific (a project tracker, a private API, a custom Python script exposed via stdio). Triggers: "list my linear issues" (MCP `linear` server), "fetch from my custom MCP", "what MCP tools do I have".

If the user's request looks like it should be handled by a native plugin, prefer that — MCP is the fallback for "I plugged in a thing and want FRIDAY to know about it".

## Discovery

`mcp_list_servers` (always registered, even with no servers configured) returns:
- the list of `name → state` from `config/mcp_servers.yaml`
- per server, the tools enumerated at startup

If a user says "what can I do with the gh server", answer from this list — don't guess.

## Adding a server

Edit `config/mcp_servers.yaml`:
```yaml
servers:
  - name: gh
    transport: stdio
    command: ["gh", "mcp", "serve"]
    enabled: true
  - name: my_tool
    transport: stdio
    command: ["python", "/abs/path/to/my_mcp.py"]
    enabled: true
```

Restart FRIDAY for changes to take effect (the bridge enumerates tools at startup; hot-reload is not supported yet).

## Invoking a tool

Each MCP tool is registered as a capability named `mcp_<server>_<tool>`. Phrases configured in the server's MCP description feed the embedding router automatically.

Examples (once `gh` MCP server is added):
- "Friday, list my open GitHub issues" → routes to `mcp_gh_list_issues`.
- "Friday, file a new issue on owner/repo titled X" → routes to `mcp_gh_create_issue` (gated by `core.approval` for any write tool).

## Common failures and recovery

- **`mcp` Python package not installed** → `pip install mcp`. Without it the bridge logs a warning at startup and the servers don't load.
- **Server process exits at startup** → check the command line in `config/mcp_servers.yaml` and the stderr in `logs/friday.log`. Fix and restart.
- **Tool call hangs** → the bridge times out after 30 s. The server is the problem, not FRIDAY — debug it standalone (`<command> 2>&1 | jq .`).
- **Discovered tools clash with native capability names** → MCP tools are prefixed with `mcp_<server>_` to avoid collisions; if a clash happens anyway, audit `config/mcp_servers.yaml` for duplicate `name:` fields.
