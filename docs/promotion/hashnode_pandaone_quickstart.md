# Setting up Pandaone Guard for AI code audit in 5 minutes

> A pragmatic walkthrough for engineers using Claude Code, Cursor, or Trae.

Most AI coding setups today look like this:

```
$ claude "add OAuth2 to the user service"
> 200 lines changed across 4 files
> "Done!"
```

Then you `git diff` and see the changes but not the *reasoning*. If the AI later reverts those changes, breaks something, or your teammate asks "why is this code different from last week", you have no record.

[Pandaone Guard](https://github.com/hellob1889/Pandaone-AI-Agent) is a free, open-source MCP server that closes this gap by enforcing an audit trail for every AI-initiated change.

This guide gets you from zero to a fully audited AI workflow in 5 minutes.

---

## Prerequisites

- Python 3.11+ (or use the bundled installer that downloads Python automatically)
- A git repo
- 5 minutes

---

## Step 1: Install

```bash
pip install pandaone-guard==0.7.14
```

This installs both the CLI (`pandaone`) and the MCP server (`pandaone-mcp`).

Verify:

```bash
pandaone --version
# pandaone, version 0.7.14
```

---

## Step 2: Initialize your project

Inside your git repo:

```bash
pandaone init
```

This creates `.pandaone/` directory with:
- `pandaone.jsonl` — append-only audit log
- `config.toml` — default configuration
- `pre-commit` — git hook that blocks unaudited commits

---

## Step 3: Install the git hook

```bash
pandaone install-hook
```

This writes `.git/hooks/pre-commit`. Try to commit something unaudited:

```bash
echo "console.log('hi')" >> app.js
git add app.js
git commit -m "test"
```

You should see:

```
pandaone pre-commit: FAIL
  app.js — no audit record found

Either:
  - Run `pandaone write app.js` first, or
  - Use `git commit --no-verify` to skip (NOT recommended)
```

The hook is your L4 defense layer.

---

## Step 4: Audit your first AI change

```bash
pandaone write src/auth/oauth.py \
  --problem "OAuth flow was missing CSRF token validation" \
  --reason "Security ticket #231 — potential CSRF vulnerability reported by external pentest" \
  --approach "Added state parameter generation in /oauth/start and verification in /oauth/callback. Kept the existing session cookie flow."
```

This appends a structured JSONL record. Inspect it:

```bash
cat .pandaone/pandaone.jsonl | jq
```

```json
{
  "timestamp": "2026-09-15T08:14:23Z",
  "ai_agent": "manual",
  "file": "src/auth/oauth.py",
  "problem": "OAuth flow was missing CSRF token validation",
  "reason": "Security ticket #231 — potential CSRF vulnerability reported by external pentest",
  "approach": "Added state parameter generation in /oauth/start and verification in /oauth/callback. Kept the existing session cookie flow.",
  "tags": ["security", "csrf", "oauth"]
}
```

Now your commit will pass:

```bash
git add src/auth/oauth.py
git commit -m "Add CSRF protection to OAuth flow"
# pandaone pre-commit: PASS
# [main abc1234] Add CSRF protection to OAuth flow
```

---

## Step 5: Connect to your AI agent

### Claude Code / Cursor / Trae

In your MCP config (`~/.config/claude/config.json`, `~/.cursor/mcp.json`, or similar):

```json
{
  "mcpServers": {
    "pandaone-guard": {
      "command": "pandaone-mcp",
      "args": [],
      "env": {
        "PANDAX_FP_PASSWORD": "0000",
        "PANDAX_LANG": "en"
      }
    }
  }
}
```

Now Claude/Cursor has 11 tools it can call, including `pandaone_write`. The AI will (or should) call it before modifying your files.

### ChatGPT (Developer Mode)

Settings → Beta → Developer Mode → Connectors → paste:

```json
{
  "pandaone-guard": {
    "command": "pandaone-mcp",
    "args": [],
    "env": {
      "PANDAX_FP_PASSWORD": "0000",
      "PANDAX_LANG": "en"
    }
  }
}
```

---

## Step 6: Watch the dashboard

```bash
pandaone status
```

```
Pandaone Guard v0.7.14 — Project Dashboard

Audit records:        142
Files covered:        38
Locked files:         2 (.env.production, secrets/master.key)
Pre-commit hook:      installed
Last audit:           2 minutes ago (src/auth/oauth.py)
```

Or open the GitHub Pages dashboard (auto-generated on every push):

`https://hellob1889.github.io/Pandaone-AI-Agent/`

---

## What happens when the AI bypasses Pandaone?

It can't. Without `pandaone_write` producing an audit record, the pre-commit hook blocks the commit. The AI can lie in the audit record (write "I changed nothing" while actually changing everything) — but that lie is now permanent in your JSONL. When the on-call engineer finds the bug six months later, they can see exactly what the AI claimed.

This is the core insight: **"you have to lie in writing"** is a much higher bar than "you have to lie at all".

---

## What's the cost?

- Free, MIT licensed
- Zero external API calls (no telemetry, no hosted service)
- 137 KB wheel
- 11 MCP tools, ~3000 lines of Python
- 15 tests, 100% coverage of MCP server

---

## Where to go from here

- Repo: https://github.com/hellob1889/Pandaone-AI-Agent
- Docs: https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/docs/en/index.md
- PyPI: https://pypi.org/project/pandaone-guard/
- M8ven: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent

If you find a workflow Pandaone doesn't cover, open an issue. The whole point of MIT is that you can fork it.

Happy auditing.