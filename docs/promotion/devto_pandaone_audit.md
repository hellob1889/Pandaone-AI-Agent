# How I built an MCP server to audit every change my AI Agent makes

> Tags: `mcp` `ai-agents` `code-audit` `security` `python` `claude` `cursor` `opensource`

I spent six months using Claude Code, Cursor, and Trae to ship features faster than I ever thought possible. Then I asked myself a question that made me uncomfortable:

> **Who is auditing the AI's changes to my code?**

The AI cheerfully rewrites 200 lines of a payment module at 2 AM. The git history shows "fix bug". The PR description says "WIP". But nobody — not the AI, not me, not my future self — can answer: *why was this changed? what problem does it solve? what's the approach?*

That's the gap I built [Pandaone Guard](https://github.com/hellob1889/Pandaone-AI-Agent) to close. It's a free, open-source MCP server (MIT) that forces every AI-initiated code change to leave a structured audit trail before it hits your repo.

This post walks through what it does, why I designed it this way, and how you can use it today.

---

## The problem with "AI wrote this code"

Modern AI agents are not just autocomplete. They:

- Refactor across multiple files in a single pass
- Rename symbols to match new patterns
- Delete code they consider "dead"
- Add third-party dependencies you didn't ask for
- Touch lock files, config files, and CI scripts

A `git commit` tells you **what** changed. It does not tell you:

- What **problem** the AI was solving
- What **approach** it took (and why not another)
- Whether this is a **routine edit** or a **destructive rewrite**

When something breaks in production three months later, you're guessing. That guesswork is what we used to call "tech debt". With agents in the loop, it's worse — it's *unsupervised tech debt*.

---

## What Pandaone Guard does

Pandaone Guard is an MCP (Model Context Protocol) server that adds **11 tools** your AI agent can call. The core loop:

1. AI wants to modify a file
2. AI calls `pandaone_write <file> --reason "..." --problem "..." --approach "..."`
3. The tool checks: is this a protected file? Is it already locked? Are you authorized?
4. If approved, it appends a JSONL audit record with the AI's structured explanation
5. A pre-commit hook scans the audit log and **rejects** any commit where changes were not audited
6. After merge, a GitHub Pages dashboard renders the audit trail in real time

The result: every line of AI code has a paper trail.

### Screenshot: `pandaone write`

![pandaone write](https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/assets/terminal-write.png)

### Screenshot: `pandaone status` dashboard

![pandaone status](https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/assets/terminal-status.png)

---

## The six defense layers

I deliberately split protection into independent layers so you can opt out of any of them:

| Layer | Mechanism | What it stops |
|---|---|---|
| L1 | Protected file formats (`.jsonl`, audit files) | Accidental AI edits to audit logs |
| L2 | File locks (`pandaone_lock` / `unlock`) | Edits to sensitive files without manual approval |
| L3 | Audit log (`pandaone write`) | Changes without problem/reason/approach metadata |
| L4 | Pre-commit hook | Unaudited changes leaking into git history |
| L5 | CI verification (`pandaone ci`) | Unaudited changes leaking into production |
| L6 | Scheduled reconciliation (cron) | Drift between audit log and reality |

Each layer is testable in isolation. The whole thing is ~3000 lines of Python with no external runtime dependencies beyond `click` and `rich`.

---

## What the audit record looks like

A single `pandaone write` invocation produces a JSONL record like:

```json
{
  "timestamp": "2026-09-15T08:14:23Z",
  "ai_agent": "claude-3.5-sonnet",
  "file": "src/payment/refund.py",
  "problem": "Refund calculation was using integer division instead of Decimal, causing rounding errors on JPY",
  "reason": "Customer support ticket #4521 — 12 complaints about 1 JPY discrepancies",
  "approach": "Switched to Decimal with ROUND_HALF_UP, kept public API stable via __round__ override",
  "destructive_hint": false,
  "tags": ["bugfix", "financial-correctness"]
}
```

Compare this to a git commit message: "fix refund bug".

When the on-call engineer gets paged six months later, they don't need to dig through Slack to find the AI's reasoning. It's right there.

---

## MCP server architecture (for the curious)

```python
# src/pandaone_mcp/__main__.py (excerpt)
TOOLS = [
    {
        "name": "pandaone_write",
        "description": "Record an AI-initiated code change with structured metadata.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,    # writes audit log
            "idempotentHint": False,     # each call appends a new record
            "openWorldHint": False
        },
        ...
    },
    ...
]
```

All 11 tools expose the four MCP-standard annotation hints. This was the change that took M8ven's trust score from 74 to 100 — turns out MCP directories *require* these hints for inclusion.

---

## How to try it (5 minutes)

```bash
pip install pandaone-guard==0.7.14
pandaone init
pandaone write README.md \
  --reason "First audit entry" \
  --problem "Setting up the tool" \
  --approach "Demonstrating the audit flow"
pandaone status
```

To wire it into Claude Code or Cursor, copy this into your MCP config:

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

Full docs: [github.com/hellob1889/Pandaone-AI-Agent](https://github.com/hellob1889/Pandaone-AI-Agent)

---

## Tradeoffs and what I deliberately did NOT do

Honest disclosure:

- **Not a linter.** Pandaone doesn't tell you if the code is *good*. It tells you who changed it and why. Pair it with ruff, mypy, or whatever you already use.
- **Not a replacement for code review.** A clean audit record doesn't mean the change is correct. Humans still need to read intent.
- **Not a security boundary on its own.** A malicious AI that wants to bypass Pandaone can do so by lying in the audit record. The defense is "you have to lie in writing". That's surprisingly effective against accidental AI drift, much less so against a determined attacker.
- **Not hosted.** Pandaone runs locally as a stdio MCP server. Your code never leaves your machine.

---

## What's next

- v0.7.15 (this week): graph visualization of audit dependencies
- v0.8.0 (next month): optional OPA-based policy engine for "no AI changes to /auth/*"

If you ship AI-generated code to production, give it a try. If you don't yet, the question to ask your team is: *if this AI change breaks in 3 months, can we reconstruct why it happened?*

---

GitHub: https://github.com/hellob1889/Pandaone-AI-Agent
PyPI: https://pypi.org/project/pandaone-guard/
M8ven Trust: https://m8ven.ai/mcp/hellob1889-pandaone-ai-agent

*MIT licensed. Free forever. Local-first. No telemetry.*