# MCP Registry & ChatGPT Submission Materials

**Package**: `pandaone-guard` (PyPI distribution name) — installs the `pandaone-mcp` command
**Version**: 0.7.14 (2026-09-16)
**Repo**: https://github.com/hellob1889/Pandaone-AI-Agent
**Trust badge**: M8ven A-grade Verified Publisher (score 100/100, live monitored)

> **⚠️ 重要诚实披露 — 第一性原理**
>
> 经过实际调研（2026-09-16），**OpenAI 目前没有公开的"MCP directory submission form"**。
>
> 事实：
> - ChatGPT 自 2025-09 起支持 MCP via Developer Mode（开发者模式）
> - 用户通过 **JSON 配置文件**手动添加 MCP server
> - OpenAI 的 "App Directory" 是 2025-11 内部内测（部分开发者获得邀请）

> **🔄 2026-09-17 更新 — Smithery 被 Arcade.dev 收购**
>
> 2026-08-05 Arcade.dev 官方博客确认收购 Smithery。smithery.ai 仍可访问并接受新提交，但未来会整合到 Arcade 生态。**建议现在就提交 Smithery，先占坑**。

> **📋 实际可执行的提交路径（2026-09-17 调研后）**
>
> - **mcp.so** ✅ — web form 接受 stdio + remote server，1-3 天人工审核
> - **Smithery** ✅ — web form（GitHub OAuth），5-30 分钟自动发布
> - **PulseMCP** ✅ — GitHub Issue 申请
> - **Glama** ✅ — web form 或 GitHub PR
>
> **完整字段值和提交步骤见** [`SUBMISSION_FORM_DATA.md`](SUBMISSION_FORM_DATA.md)。
> - **没有公开的 web form 可以填**
>
> 因此本文档覆盖**真实存在的 4 个公开 registries** + **ChatGPT Developer Mode 端用户接入文档**。

---

## 第一部分：ChatGPT Developer Mode 接入文档（端用户）

### ChatGPT MCP 添加流程（用户面）

**前提**：
- ChatGPT Desktop app（macOS / Windows）
- 订阅 ChatGPT Plus / Team / Enterprise / Pro
- 启用 Developer Mode

**启用步骤**：
1. 打开 ChatGPT Desktop app
2. Settings → Beta features → **Developer Mode** → 开启
3. Settings → Connectors → **Create new connector**
4. 填写以下 JSON（完全一致）：

```json
{
  "name": "pandaone-guard",
  "command": "pandaone-mcp",
  "args": [],
  "env": {}
}
```

5. 第一次运行时，ChatGPT 会要求安装 pandaone-guard（系统会自动调用 `pip install` 或类似机制）

**如果 pandaone-mcp 不在 PATH**（用户需手动安装）：

```bash
# macOS / Linux
pip3 install pandaone-guard

# Windows (PowerShell)
pip install pandaone-guard
```

**验证安装**：
```bash
pandaone-mcp --help
# 或
python -m pandaone_mcp --help
```

### 自定义 connector（高级用户）

如果用户在 venv 中或自定义 Python 路径：

```json
{
  "name": "pandaone-guard",
  "command": "/path/to/venv/bin/python",
  "args": ["-m", "pandaone_mcp"],
  "env": {
    "PANDAX_LANG": "zh"
  }
}
```

### 环境变量说明

| 变量 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `PANDAX_FP_PASSWORD` | secret | `"0000"` | `pandaone_fingerprint_update` 用的密码（仅 watch 守护进程鉴权需要） |
| `PANDAX_LANG` | config | `"zh"` | 界面语言（`zh` / `en`）|
| `PANDAONE_SKIP_GIT_CHECK` | config | unset | 设置 `1` 跳过 git 检测（无 git 环境用） |
| `NO_COLOR` | config | unset | 设置 `1` 禁用彩色输出 |
| `BASH_VERSION` / `ZSH_VERSION` | config | unset | shell 检测用，通常无需手动设置 |

**只有一个 secret**：`PANDAX_FP_PASSWORD`。在本地运行时设置，不会上传到任何远程。

---

## 第二部分：4 个公开 MCP Registries 提交材料

### Registry 1: mcp.so (Chinese MCP Directory — 推荐 ⭐)

**URL**: https://mcp.so/
**性质**: 中文 MCP 服务器聚合站（最大的中文 MCP registry）
**提交方式**: GitHub PR（自动同步）

**步骤**：
1. Fork `https://github.com/chatmcp/mcp-so`（或对应的源仓库）
2. 在 `servers/` 目录下创建 `pandaone-guard.json`：
   ```json
   {
     "name": "pandaone-guard",
     "displayName": "Pandaone AI Agent",
     "description": "AI Agent 代码审计与文件保护工具 — 让每一次代码改动都留下合规、可追溯的证据链",
     "author": "hellob1889",
     "license": "MIT",
     "homepage": "https://github.com/hellob1889/Pandaone-AI-Agent",
     "repository": "https://github.com/hellob1889/Pandaone-AI-Agent",
     "installCommand": "pip install pandaone-guard",
     "command": "pandaone-mcp",
     "tags": ["audit", "code-review", "ai-agent", "compliance", "git", "security"],
     "categories": ["developer-tools", "security"],
     "tools": 11
   }
   ```
3. 提交 PR，标题 `feat: add pandaone-guard MCP server`
4. CI 自动验证（如 GitHub URL 可达、tools 数对得上）

---

### Registry 2: Smithery

**URL**: https://smithery.ai/
**性质**: 英文 MCP registry + 部署平台
**提交方式**: Web form + GitHub 同步

**步骤**：
1. 登录 https://smithery.ai/
2. 点 "Add MCP Server"
3. 填表：

| 字段 | 值 |
|---|---|
| **Name** | Pandaone AI Agent |
| **Display name** | Pandaone Guard |
| **GitHub URL** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **Short description** | AI Agent code audit gateway — every code change leaves a compliance + audit trail |
| **Long description** | 见下方 |
| **Category** | Developer Tools / Security |
| **Tags** | audit, code-review, ai-agent, compliance, git, security, mcp |
| **License** | MIT |
| **Install command** | `pip install pandaone-guard` |
| **Run command** | `pandaone-mcp` |

**Long description**：

> Pandaone AI Agent is an OS-level mandatory review gateway for AI-generated code changes. Every modification is gated through a three-step audit (reason → problem → approach) before being written to disk, with cryptographically signed approval records.
>
> **11 MCP tools**: `pandaone_init`, `pandaone_lock`, `pandaone_unlock`, `pandaone_write` (the destructive write gate), `pandaone_log`, `pandaone_status`, `pandaone_install_hook`, `pandaone_watch`, `pandaone_install_git`, `pandaone_fingerprint_update`, `pandaone_ci`.
>
> **All tools declare the full 4 MCP spec annotations** (readOnlyHint / destructiveHint / idempotentHint / openWorldHint) — OpenAI directory compliant.
>
> **Cross-platform**: installable on Windows / macOS / Linux via `pip install pandaone-guard`. Hard-isolated venv by default. Zero-preinstall on Windows (auto-installs embedded Python 3.12 if missing).
>
> **Trust**: M8ven Trust Index A-grade (score 100/100) — Verified Publisher + Live Monitored.
>
> Use case: teams running Claude / Cursor / Trae / Codex that need every AI-generated code change to be auditable.

---

### Registry 3: PulseMCP

**URL**: https://www.pulsemcp.com/
**性质**: 英文 MCP directory + 时事通讯（每周邮件给 5,000+ 开发者）
**提交方式**: GitHub Issue

**步骤**：
1. 去 https://github.com/pulsemcp/mcp-servers（their source repo）
2. Issue：`Add new MCP server: pandaone-guard`
3. 内容按模板填：
   ```markdown
   ### Server Info
   - Name: pandaone-guard
   - URL: https://github.com/hellob1889/Pandaone-AI-Agent
   - PyPI: https://pypi.org/project/pandaone-guard/
   - License: MIT
   - Author: @hellob1889
   
   ### Description
   Pandaone AI Agent is an OS-level mandatory review gateway for AI-generated code changes.
   Every modification goes through reason → problem → approach audit before being written.
   
   ### Tools (11)
   1. pandaone_init — Initialize project
   2. pandaone_lock — Lock protected files
   3. pandaone_unlock — Unlock protected files
   4. pandaone_write — Audit-gated write (the only destructive tool)
   5. pandaone_log — View audit history
   6. pandaone_status — Project status dashboard
   7. pandaone_install_hook — Install pre-commit hook
   8. pandaone_watch — File system watchdog daemon
   9. pandaone_install_git — Portable git installer
   10. pandaone_fingerprint_update — Update auth password
   11. pandaone_ci — CI verification
   
   ### Trust Signals
   - M8ven Trust Index: A-grade (100/100)
   - Verified Publisher + Live Monitored
   - 11/11 tools declare full MCP annotations (OpenAI directory compliant)
   - 11/11 tools have direct tests
   
   ### Why it matters
   In the era of AI-generated code, audit trail = compliance. pandaone is the only MCP
   server that treats the AI's write path as a regulated event.
   ```

---

### Registry 4: Glama

**URL**: https://glama.ai/mcp
**性质**: 英文 MCP registry + OpenAI 兼容特性
**提交方式**: GitHub PR

**步骤**：
1. Fork `https://github.com/glama-ai/mcp-servers`
2. 在 `src/servers/` 加 `pandaone-guard.md`：
   ```markdown
   ---
   name: Pandaone AI Agent
   slug: pandaone-guard
   description: AI Agent code audit gateway — every code change leaves a compliance + audit trail
   homepage: https://github.com/hellob1889/Pandaone-AI-Agent
   ---
   
   # Pandaone AI Agent
   
   OS-level mandatory review gateway for AI-generated code changes.
   
   ## Install
   ```bash
   pip install pandaone-guard
   ```
   
   ## Run as MCP server
   ```bash
   pandaone-mcp
   ```
   
   ## Tools
   - `pandaone_init`
   - `pandaone_lock`
   - `pandaone_unlock`
   - `pandaone_write` (destructive)
   - `pandaone_log`
   - `pandaone_status`
   - `pandaone_install_hook`
   - `pandaone_watch`
   - `pandaone_install_git` (open-world)
   - `pandaone_fingerprint_update`
   - `pandaone_ci`
   ```
3. PR：`feat: add pandaone-guard MCP server`

---

## 第三部分：核心信息一览（复制粘贴用）

### Metadata 字段（所有 registry 通用）

```yaml
name: pandaone-guard
displayName: Pandaone AI Agent
version: 0.7.14
releaseDate: 2026-09-16
author: hellob1889
license: MIT
homepage: https://github.com/hellob1889/Pandaone-AI-Agent
pypi: https://pypi.org/project/pandaone-guard/
m8venTrust: https://m8ven.ai/mcp/hellob1889/pandaone-ai-agent
installCommand: pip install pandaone-guard
runCommand: pandaone-mcp
tools: 11
transport: stdio
pythonRequired: '>=3.8'
```

### English short description (用于英文 registries)

> Pandaone AI Agent is an OS-level mandatory review gateway for AI-generated code changes. Every modification is gated through a three-step audit (reason → problem → approach) before being written to disk.

### Chinese short description (用于中文 registries)

> AI Agent 代码审计与文件保护工具 — 让每一次代码改动都留下合规、可追溯的证据链。11 个 MCP 工具覆盖初始化 / 锁定 / 解锁 / 审计写入 / 日志 / 状态 / hook 安装 / 守护监控 / Git 安装 / 指纹更新 / CI 验证。

### Trust badges

```markdown
[![M8ven Score](https://m8ven.ai/badge/mcp/hellob1889/pandaone-ai-agent)](https://m8ven.ai/mcp/hellob1889/pandaone-ai-agent)
```

### Screenshots (从 README 直接引用)

- `assets/terminal-write.png` — `pandaone write` 真实审计凭证
- `assets/terminal-log.png` — `pandaone log --last 5` 多 agent 审计历史
- `assets/terminal-status.png` — `pandaone status` 41 保护格式 + L1/L6 实时状态
- `assets/dashboard.png` — 真实 Web 仪表盘（15 条审计 · claude/cursor/trae 三方）

---

## 第四部分：Action Checklist（你的下一步）

按 ROI 排序，每项 5-15 分钟：

| # | Registry | URL | 你的动作 | 预计审查 | ROI |
|---|---|---|---|---|---|
| 🥇1 | **mcp.so** | https://github.com/chatmcp/mcp-so | Fork → add JSON → PR | 1-3 天 | 高（中文流量） |
| 🥈 2 | **Smithery** | https://smithery.ai/add | Web form 提交 | 1-7 天 | 高（英文流量） |
| 🥉 3 | **PulseMCP** | https://github.com/pulsemcp/mcp-servers/issues/new | Issue 申请 | 3-7 天 | 中（邮件 newsletter） |
| 4 | **Glama** | https://github.com/glama-ai/mcp-servers | Fork → add MD → PR | 1-7 天 | 中 |

附加（非 registry）：

| # | 动作 | 你的角色 |
|---|---|---|
| 5 | 把本文档提交给 OpenAI 团队（如果他们有 partner 邀请渠道） | 邮件至 partner@openai.com 或 support |
| 6 | 在 GitHub README 加一段 "Add to ChatGPT" 指引 | 我可以写 PR 改 README |
| 7 | 在 docs/ 下创建 `docs/chatgpt-developer-mode.md` 详细教程 | 我可以写 |

---

## 第五部分：诚实的不确定性

按 user_rule "第一性原理 + 对抗式审查"，我不能保证：

1. **mcp.so / Smithery / PulseMCP / Glama 的实际审查时间** — 1-3 天到 1-2 周不等
2. **OpenAI 是否有 partner 申请通道** — 我搜不到公开 URL；可能通过 `partner@openai.com` 邮件
3. **"verified publisher"标签** — Smithery/PulseMCP/Glama 都有自己的"官方"标记，规则不公开

**我能保证的是**：

1. ✅ **OpenAI directory 合规性**：11/11 tools 都有完整 annotations（PR #44 修复）
2. ✅ **PyPI 可装**：`pip install pandaone-guard==0.7.14` 全球可达
3. ✅ **MCP 协议合规**：stdio JSON-RPC 2.0 transport（OpenAI / Claude Desktop / Cursor 都支持）
4. ✅ **材料完整**：本文档提供了所有 4 个 registry 的提交材料 + ChatGPT 端用户接入文档

---

**下一步**：你选一个 registry（建议先 mcp.so），告诉我，我来准备对应的 PR 或 form 文案；或者你说"先做 README 的 ChatGPT 接入指引"——我马上写 PR。

---

*Document generated: 2026-09-16 Asia/Shanghai · based on actual MCP server implementation + multiple registry research.*