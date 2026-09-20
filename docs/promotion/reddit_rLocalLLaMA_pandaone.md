# Show: Pandaone Guard — local MCP server that gives every AI code change a structured audit trail (MIT, M8ven A-grade)

I built this for my own LLM-assisted coding workflow and figured I'd share. The repo is small (~3000 LoC Python) so anyone can audit it themselves.

Repo: https://github.com/hellob1889/Pandaone-AI-Agent

---

## The local-first angle

Everything runs on your machine:

- No telemetry
- No hosted backend
- No API key
- 137 KB wheel

The MCP server speaks stdio (per MCP spec), so it works with Claude Code, Cursor, Trae, ChatGPT Developer Mode, or any compliant client.

The audit log is just JSONL appended to `.pandaone/pandaone.jsonl`. You can grep it, jq it, pipe it into your own analytics. No lock-in.

---

## The MCP tool surface

11 tools, all annotated per the MCP spec:

| Tool | readOnly | destructive | idempotent | openWorld |
|---|---|---|---|---|
| `pandaone_init` | false | false | false | false |
| `pandaone_lock` | false | false | true | false |
| `pandaone_unlock` | false | false | true | false |
| `pandaone_write` | false | **true** | false | false |
| `pandaone_log` | true | false | true | false |
| `pandaone_status` | true | false | true | false |
| `pandaone_install_hook` | false | false | true | false |
| `pandaone_watch` | false | false | false | false |
| `pandaone_install_git` | false | false | true | **true** |
| `pandaone_fingerprint_update` | false | false | true | false |
| `pandaone_ci` | true | false | true | false |

The annotations aren't decoration — OpenAI's MCP directory refuses to list servers without them. We learned that the hard way (v0.7.10 → v0.7.14 cycle was mostly about filling these in correctly).

---

## What's next

If people find this useful, the v0.8.0 plan is to add an optional OPA-based policy engine: declarative rules like "AI cannot modify anything under `/auth/*`". That gives you a way to enforce constraints without writing Python.

PRs / issues / feedback welcome.