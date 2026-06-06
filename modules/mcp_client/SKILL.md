---
name: mcp_client
description: "MCP (Model Context Protocol) client — connects to local or remote MCP servers and registers their tools dynamically."
plugin_module: modules/mcp_client
capabilities:
  - name: mcp_list_servers
    description: "List connected MCP servers and their available tools."
    aliases:
      - "list mcp servers"
      - "show mcp tools"
      - "what mcp servers are connected"
---

# MCP Client Module

Connects FRIDAY to any MCP-compatible tool server. Once connected, the server's
tools appear alongside FRIDAY's native capabilities in the embedding router.

## Setup

1. Install the MCP library (optional but recommended):
   ```
   pip install mcp
   ```

2. Add server entries to `config/mcp_servers.yaml`:
   ```yaml
   servers:
     - name: github
       command: ["gh", "extension", "exec", "mcp-server"]
       description: "GitHub tools"
       enabled: true
   ```

3. Restart FRIDAY — tools are registered at startup.

## Examples

```
Friday, list mcp servers
Friday, list my open GitHub issues          # after connecting GitHub MCP server
Friday, create a PR for my current branch   # after connecting GitHub MCP server
```

## Supported Connection Modes

| Mode     | Config key | Description                        |
|----------|------------|------------------------------------|
| stdio    | `command`  | Local subprocess (JSON-RPC stdio)  |
| HTTP/SSE | `url`      | Remote HTTP server (planned)       |

## Tool naming

MCP tools are registered as `mcp_{server_name}_{tool_name}` (e.g.
`mcp_github_list_issues`). Use natural language — the embedding router
will match your query to the right tool.
