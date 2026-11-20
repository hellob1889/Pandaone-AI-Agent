# MCP Integration

> **Let AI Agents (Claude / Cursor / Trae) directly call Pandaone AI Agent.**

## What is MCP?

[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) is a standard protocol for AI Agents to call external tools via stdio JSON-RPC.

Pandaone implements as a **stdio JSON-RPC 2.0 server** — **no network exposure**, IDE-managed process lifecycle.

## Client Configuration

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "pandaone": {
      "command": "pandaone-mcp",
      "env": {}
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "pandaone": {
      "command": "pandaone-mcp"
    }
  }
}
```

## 12 Tools Exposed

| Tool | Purpose |
|---|---|
| `pandaone_init` | Initialize Pandaone in directory |
| `pandaone_lock` | Lock all protected files |
| `pandaone_unlock` | Unlock |
| `pandaone_write` | Audit write (core) |
| `pandaone_log` | Query audit history, 13 export formats |
| `pandaone_status` | Show project status dashboard |
| `pandaone_install_hook` | Install L3 pre-commit hook |
| `pandaone_watch` | Start watchdog daemon |
| `pandaone_install_git` | Probe/install git |
| `pandaone_fingerprint_update` | Update CLI self-fingerprint |
| `pandaone_ci` | L7 CI verification |

## Why stdio over HTTP?

- ✅ **Zero network exposure** (no ports, no auth)
- ✅ IDE-managed process (start/restart/sandbox)
- ✅ Standard protocol (any MCP client works)
- ✅ Low latency (no HTTP overhead)

## Test MCP Manually

```bash
pandaone-mcp &
echo '{"jsonrpc":"2.0","method":"initialize","params":{"clientInfo":{"name":"test"}},"id":1}' | pandaone-mcp
```

Full demo: [examples/04_mcp_client.py](../../examples/04_mcp_client.py)

---

[← Home](index.md) | [CI Integration](ci-integration.md)