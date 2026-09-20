# Product Hunt — Pandaone Guard

## Tagline (≤60 chars)
"AI code audit trail. Free, local, MIT."

## One-line description (≤160 chars)
"Open-source MCP server that forces every AI Agent code change to leave a structured problem/reason/approach audit record before commit. Local-first, no API key."

## Full description

Every day, AI coding agents (Claude Code, Cursor, Trae, ChatGPT) rewrite thousands of lines of code. Git records *what* changed. Nothing records *why*.

Pandaone Guard is a free, open-source MCP server that closes that gap. It gives every AI Agent 11 tools, the core one being `pandaone_write` — a forced "audit ticket" with `problem`, `reason`, and `approach` fields. A pre-commit hook then blocks any commit whose changes weren't audited.

The result: a JSONL audit log of every AI code change, with the AI's own structured explanation of what problem it was solving and what approach it took.

### Key features

- **11 MCP tools** — full coverage of the AI agent workflow (init, lock, unlock, write, log, status, install-hook, watch, install-git, fingerprint-update, ci)
- **6 defense layers** — protected file formats, file locks, audit log, pre-commit hook, CI verification, scheduled reconciliation. Each layer is opt-out-able
- **Honest AI** — the AI has to lie in writing. Its lies are now permanent and searchable
- **Local-first** — no hosted service, no telemetry, no API key, no SaaS
- **Multi-platform** — Claude Code, Cursor, Trae, ChatGPT Developer Mode, any MCP-compliant client
- **Cross-platform** — Windows, macOS, Linux. Python 3.11+ with bundled installer option for zero-setup

### Numbers

- M8ven Trust Index: **100/100, A grade, Verified Publisher, Live Monitored**
- 15 tests, 100% MCP server coverage
- 137 KB wheel
- MIT licensed, free forever

### Try it

```bash
pip install pandaone-guard==0.7.14
pandaone init
pandaone install-hook
```

Then add to your MCP config:

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

---

## First comment (Maker's response)

Hey Product Hunt! 👋

I'm the maker of Pandaone Guard. Quick backstory: six months ago I started using Claude Code to ship features faster. Three months later, I got paged for a bug in production. I `git blame`'d my way back to an AI-written commit, saw "fix bug", and realized I had no idea what the AI was *thinking* when it made that change.

That bug wasn't anyone's fault. It was a tooling gap. Git records *what* changed. Nothing records *why*. So I built this.

The core insight is simple: **the AI has to lie in writing**. A malicious AI can still bypass the audit log, but its lie is now permanent in JSONL — searchable, comparable, auditable. Way higher bar than "lie at all".

This is v0.7.14. The whole thing is ~3000 lines of Python, MIT licensed, runs locally as a stdio MCP server. Your code never leaves your machine.

I'd love feedback on:
1. Is the `problem/reason/approach` schema the right granularity?
2. Should `git commit --no-verify` produce an audit record, or is that a footgun?
3. Roadmap item: OPA-based policy engine for "AI cannot modify /auth/*". Useful?

Happy to answer questions in the comments!

— hellob1889

## Links
- Website: https://hellob1889.github.io/Pandaone-AI-Agent/
- GitHub: https://github.com/hellob1889/Pandaone-AI-Agent
- PyPI: https://pypi.org/project/pandaone-guard/
- M8ven: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent

## Categories (pick 3-4)
- Developer Tools
- Open Source
- Artificial Intelligence
- Security

## Topics/Tags
- AI
- Code Audit
- MCP
- Claude
- Cursor
- Local-first
- Open Source
- Python
- Security
- Developer Tools