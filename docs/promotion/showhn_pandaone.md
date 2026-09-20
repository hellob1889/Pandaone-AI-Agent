# Show HN: Pandaone Guard — Local MCP server that audits every AI Agent code change

**Tagline:** Force every AI-initiated code change to leave a structured `problem / reason / approach` audit record before it hits git.

**URL:** https://github.com/hellob1889/Pandaone-AI-Agent

**Try it in 30 seconds:**

```bash
pip install pandaone-guard==0.7.14
pandaone init
pandaone write README.md --problem "demo" --reason "trying it out" --approach "manual first audit"
pandaone status
```

---

## What this is

A free, MIT-licensed MCP server (11 tools) that sits between your AI coding agent (Claude Code, Cursor, Trae, ChatGPT Developer Mode) and your git repo. Every time the AI wants to modify a file, it has to call `pandaone_write` first with a structured explanation. A pre-commit hook then blocks any commit whose changes weren't audited.

The result: a JSONL audit log of every AI code change, with the AI's own structured description of why.

---

## Why I built it

After 6 months of Claude Code / Cursor / Trae, I realized I couldn't answer basic questions about my own codebase:

- Why was this function renamed?
- Why was this dependency added?
- Was this AI edit destructive or routine?
- If this breaks in 3 months, can I reconstruct why?

Git tells me *what* changed. It doesn't tell me *why*. AI coding agents are bigger than Xgboost-level autocomplete — they refactor across files, rename symbols, delete code, add deps. The audit gap was real.

---

## Key design choices

1. **Local-first, no hosted service.** Runs as stdio MCP. Your code never leaves your machine. No API key, no telemetry, no SaaS.

2. **Six independent defense layers, each opt-out-able:**
   - L1 protected file formats
   - L2 file locks
   - L3 audit log
   - L4 pre-commit hook
   - L5 CI verification
   - L6 scheduled reconciliation cron

3. **The AI must lie in writing.** A malicious AI can lie in the audit record, but that lie is now permanent in JSONL. When the on-call engineer finds the bug, the lie is searchable. Way higher bar than "lie at all".

4. **MCP annotations filled in** (readOnlyHint, destructiveHint, idempotentHint, openWorldHint on all 11 tools). This is what got us into OpenAI's directory.

5. **Honest scope:** not a linter, not a code review replacement, not a security boundary on its own. It's a structured *intent capture* layer.

---

## Numbers

- 11 MCP tools, all 4 annotation hints filled
- 15 tests, 100% MCP server coverage
- M8ven Trust Index: **100/100, A grade, Verified Publisher, Live Monitored**
- 137 KB wheel, pure Python, deps are `click` + `rich`
- 22+ PyPI downloads (v0.7.x cumulative, real)
- 0 GitHub stars ← the bottleneck, not the code

---

## What I'd love feedback on

1. Is the 3-field `problem/reason/approach` schema the right granularity? Should I add a 4th field (e.g., `risk_assessment`)?
2. The pre-commit hook blocks unaudited commits — should there be a `--no-verify` audit (record "AI skipped audit for this commit") or is that a footgun?
3. Roadmap item: OPA-based policy engine for "AI cannot modify /auth/*". Useful, or overengineered?

---

## Links

- Repo: https://github.com/hellob1889/Pandaone-AI-Agent
- PyPI: https://pypi.org/project/pandaone-guard/
- M8ven: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent
- Docs (EN): https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/docs/en/index.md

Happy to answer questions. I'll be in the thread.