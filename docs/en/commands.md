# Commands

Complete CLI command reference. All commands support `--root <path>` (default: cwd).

## init — Initialize project

```bash
pandaone init [--root PATH]
```

Creates `.pandaone/` with:
- `config.json` — 17 text + 24 binary extensions
- `pandaone.jsonl` — audit log (JSON Lines)
- `binary_snapshots.json` — binary SHA256 dictionary

## lock / unlock

```bash
pandaone lock [--root PATH]
pandaone unlock [--root PATH]
```

Windows: `attrib +R` / `-R`
macOS/Linux: `chmod 444` / `chmod 644`

## write — Audit write (core)

```bash
pandaone write \
    --file <RELATIVE_PATH> \
    --reason "change reason" \
    --problem "problem solved" \
    --approach "approach used" \
    [--old "old"] [--new "new"] \
    [--content "full new content"] \
    [--from-file <PATH>] \
    [--content-base64 "BASE64"]
```

**Text**: use `--old/--new` or `--content`
**Binary**: use `--from-file` or `--content-base64`

`--reason` / `--problem` / `--approach` are **mandatory**.

## log — Audit history

```bash
pandaone log [--root PATH] [--last N] [--status STATUS]
pandaone log --format <fmt> --output <file>
```

13 export formats: text/txt, csv/tsv, json, yaml/yml, md/markdown, html, xlsx/excel, docx/word, pdf, sqlite/db, rst, asciidoc/adoc

## status — Project status dashboard

```bash
pandaone status [--root PATH]
```

Shows: L1 lock, L2 watchdog, L5 fingerprint, audit stats, recent audits, Phase 5 binary snapshots.

**Tri-state semantics** (v0.7.35 — `status` and `doctor` now share **one** source of truth):
- `[N/A]` the layer was never enabled (not a failure)
- `[OK]` configured and passing
- `[WARN]` passing but the baseline is not comparable (e.g. source vs frozen form)
- `[FAIL]` configured but broken (lock released, watchdog PID reused, fingerprint tampered)

Exit codes: `0` = healthy; `1` = project not initialized; `3` = at least one layer is `[FAIL]`
(same semantics as `doctor`).

## install-hook — Install L3 pre-commit hook

```bash
pandaone install-hook [--root PATH]
```

Requires: `.git/` directory.

Installs:
- `.git/hooks/pre-commit` — shell launcher
- `.pandaone/pre-commit-check.py` — Python validation

## watch — Start L2 watchdog

```bash
pandaone watch [--root PATH] [--daemon]
```

`--daemon`: background mode, writes PID to `.pandaone/.watchdog_pid`.

## install-git — Auto-install git

```bash
pandaone install-git
```

## ci — L7 CI verification

```bash
pandaone ci [--root PATH] [--base REF]
```

**base**: baseline ref (default `HEAD~1`)

Exit codes: 0 = all audited, 1 = unaudited changes found.

## update-fingerprint — Update CLI self-fingerprint

```bash
pandaone --update-fingerprint <CODE>
```

Default password is `0000` (single-user / local). For production / CI / multi-user
deployments, override via the `PANDAX_FP_PASSWORD` environment variable — the
source no longer hard-codes a privileged password.

## MCP

`pandaone-mcp` — Start MCP server (stdio JSON-RPC).

Exposes 12 tools for AI Agents (Claude / Cursor / Trae).

See [MCP Integration](mcp-integration.md).

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Rejected (CI failure / bypass blocked / validation failed) |
| 2 | Git working directory dirty |
| 3 | Tests failed |
| 4 | Build failed |
| 5 | Metadata invalid |
| 6 | Upload failed |

---

[← Home](index.md) | [Defense Layers](defense-layers.md) | [MCP](mcp-integration.md)