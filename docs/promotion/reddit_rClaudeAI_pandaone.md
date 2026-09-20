# [Project] I built an MCP server that audits every change my AI Agent makes — open source, MIT, M8ven A-grade

**TL;DR:** When Claude Code rewrites 200 lines of my payment module, I want to know *why*. So I built Pandaone Guard — a free MCP server that forces every AI code change to leave a structured `problem / reason / approach` audit record before it hits git. Pre-commit hook blocks unaudited commits. M8ven Trust score: 100. PyPI: `pip install pandaone-guard==0.7.14`.

Repo: https://github.com/hellob1889/Pandaone-AI-Agent

---

## The problem I kept hitting

I'd ship features with Claude Code or Cursor, feel productive, then three months later get paged for a bug. I'd `git blame` my way back to the AI-written commit, see "fix bug", and have no idea what the AI was *thinking* when it made the change. No record of:

- What problem the AI was solving
- What approach it took (and why)
- Whether the change was routine or destructive

That's the gap this tool closes.

---

## What it does

Pandaone Guard is an MCP server with 11 tools. The core loop:

1. AI wants to modify a file → calls `pandaone_write <file> --problem "..." --reason "..." --approach "..."`
2. Tool appends a JSONL audit record
3. Pre-commit hook scans the audit log; rejects commits with unaudited changes
4. GitHub Pages dashboard renders the audit trail in real time

Six defense layers (each opt-out-able):

- L1: Protected file formats (audit logs are read-only to the AI)
- L2: File locks (`pandaone_lock` / `unlock`)
- L3: Audit log (`pandaone_write`)
- L4: Pre-commit hook
- L5: CI verification (`pandaone ci`)
- L6: Scheduled reconciliation cron

---

## What's actually in the audit record

```json
{
  "timestamp": "2026-09-15T08:14:23Z",
  "ai_agent": "claude-3.5-sonnet",
  "file": "src/payment/refund.py",
  "problem": "Refund calculation was using integer division instead of Decimal, causing rounding errors on JPY",
  "reason": "Customer support ticket #4521 — 12 complaints about 1 JPY discrepancies",
  "approach": "Switched to Decimal with ROUND_HALF_UP, kept public API stable via __round__ override",
  "tags": ["bugfix", "financial-correctness"]
}
```

Compare this to the alternative: a git commit message saying "fix refund bug". Six months later when you're debugging production, the difference is night and day.

---

## Honest limitations

I'm not going to pretend this is silver bullet:

- **Not a linter.** Doesn't tell you if the code is good. Pair it with ruff/mypy.
- **Not a code review replacement.** A clean entry doesn't mean correct code. Humans still need to read.
- **Not a security boundary on its own.** A malicious AI could lie in the audit record. The defense is "you have to lie in writing" — which is way higher bar than "lie at all".
- **Not hosted.** Runs locally as stdio MCP. Your code never leaves your machine.

---

## Install

```bash
pip install pandaone-guard==0.7.14
pandaone init
pandaone install-hook
```

Wire into Claude Code / Cursor / Trae:

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

## Numbers

- 11 MCP tools (annotations all 4 hints filled)
- 15 tests, 100% coverage of MCP server
- M8ven Trust Index: **100/100, A grade, Verified Publisher, Live Monitored**
- 137 KB wheel
- 22+ PyPI downloads (v0.7.x cumulative, real number)
- 0 GitHub stars (this is the bottleneck, not the code)

---

## Links

- Repo: https://github.com/hellob1889/Pandaone-AI-Agent
- PyPI: https://pypi.org/project/pandaone-guard/
- M8ven: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent
- Docs (EN/ZH): https://github.com/hellob1889/Pandaone-AI-Agent/tree/main/docs

MIT licensed. Free forever. Local-first. No telemetry. Happy to answer questions about the design.