<p align="center">
  <img src="assets/banner-readme.svg" alt="Pandaone AI Agent — AI Agent 代码审计门禁" width="800"/>
</p>

# Pandaone

<p align="center">
  <img src="assets/icon-github.svg" alt="Pandaone Logo" width="96" height="96"/>
</p>

## 🧑‍💼 Pandaone is your codebase's personal manager. / Pandaone 是你代码库的专属经理。

Every AI agent is an employee working in your company — your codebase. Without a personal manager, employees do what they want — edit files, push commits, break production — and you have no idea what they did, when, or why.

**Pandaone is the personal manager you hired to protect your code.** Every AI agent — Claude, Cursor, Trae, or any tool you adopt tomorrow — must report to Pandaone first. Nothing gets written, nothing gets committed, nothing gets deployed until Pandaone approves it with a signed, auditable receipt:

```
┌─────────────────────────────────────────────┐
│ [APPROVED]                  2026-09-11 03:47 │
│ File:      src/payment.py                    │
│ Agent:     Claude Code (employee #3)         │
│ Reason:    "Fix rounding"                    │
│ Problem:   "Charge $50,001 on $50,000 bill"  │
│ Approach:  "Round before transfer, not after"│
│ Commit:    a3f7b2c                           │
└─────────────────────────────────────────────┘
```

Without a personal manager, your agents move money — er, code — without receipts:

```
Without Pandaone          With Pandaone
──────────────          ──────────────
$50,000 ???            $50,000  src/payment.py
                        Reason:  "Fix rounding"
                        By:      Claude Code
                        When:    2026-09-11 03:47
                        Commit:  a3f7b2c
```

**The left column is how most AI-agent-driven codebases look today.**
**The right column is how yours will look with one command:**

```bash
pip install pandaone-guard
```

Your personal manager is on duty 24/7 — **before, during, and after every code change**. Every AI agent — Claude, Cursor, Trae — operates under one auditable protocol. **No exceptions. No bypass.**

<p align="center">
  <img src="assets/quick-demo.svg" alt="Pandaone Quick Demo — 3-Step Workflow" width="1200"/>
</p>

> **AI Agent 代码审计门禁** — 让每一次代码改动都留下合规、可追溯的证据链。

[![PyPI version](https://img.shields.io/pypi/v/pandaone-guard?color=blue)](https://pypi.org/project/pandaone-guard/)
[![Downloads](https://pepy.tech/badge/pandaone-guard)](https://pepy.tech/project/pandaone-guard)
[![Downloads/month](https://pepy.tech/badge/pandaone-guard/month)](https://pepy.tech/project/pandaone-guard)
[![Python](https://img.shields.io/pypi/pyversions/pandaone-guard)](https://pypi.org/project/pandaone-guard/)
[![License](https://img.shields.io/pypi/l/pandaone-guard)](https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/LICENSE)
[![Tests](https://img.shields.io/badge/tests-342%20passed-brightgreen)](https://github.com/hellob1889/Pandaone-AI-Agent/actions/workflows/audit.yml)
[![Bugs](https://img.shields.io/badge/bugs-28%20fixed%20(v0.7.1)-success)](https://github.com/hellob1889/Pandaone-AI-Agent/releases/tag/v0.7.1)
[![i18n](https://img.shields.io/badge/i18n-295%20keys%20zh%20%E2%89%88%20en-blueviolet)](https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/src/pandaone/i18n.py)
[![Lint & i18n CI](https://img.shields.io/badge/Lint%20%26%20i18n-passing-success)](https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/.github/workflows/lint.yml)
[![OS](https://img.shields.io/badge/OS-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://pypi.org/project/pandaone-guard/)
[![Phase](https://img.shields.io/badge/status-v0.7.13%20production--ready-success)](https://github.com/hellob1889/Pandaone-AI-Agent/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/hellob1889/Pandaone-AI-Agent/audit.yml?branch=main&label=CI&logo=github)](https://github.com/hellob1889/Pandaone-AI-Agent/actions/workflows/audit.yml)
[![Lint](https://img.shields.io/github/actions/workflow/status/hellob1889/Pandaone-AI-Agent/lint.yml?branch=main&label=Lint&logo=github)](https://github.com/hellob1889/Pandaone-AI-Agent/actions/workflows/lint.yml)
[![M8ven Trust](https://img.shields.io/badge/M8ven_Trust-A_96%2F100_%E2%9C%93_Live_Monitored-success?logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDAgMTAwIj48dGV4dCB5PSI4MCIgZm9udC1zaXplPSI4MCI+8J%2bRjzwvdGV4dD48L3N2Zz4=)](https://m8ven.ai/mcp/hellob1889/pandaone-ai-agent)

[English](#english) | [中文](#中文)

---

## 中文 / Chinese

### 是什么？ / What is it?

Pandaone 是一个 **7 层防御体系**，强制 AI Agent（或任何开发者）写代码前必须经过审计：
任何受保护文件的修改都必须通过 `pandaone write` 命令，留下 reason / problem / approach 三段式审计记录。

**适用场景 / Use Cases**：
- 🤖 AI Agent 开发：防止 Agent 绕过审查直接改代码
- 🏢 企业合规：满足 SOC2 / ISO 27001 等代码变更审计要求
- 👥 团队协作：所有 PR 必须有审计记录才能合入

### 核心特性 / Core Features

- **17 种文本格式 + 24 种二进制格式保护**（`.py` / `.md` / `.json` / `.yml` / `.env` / `.png` / `.pdf` / ...）
- **7 层防御体系** / **7-Layer Defense System** (see [Defense Layers](#防御体系))
- **MCP Server 原生支持** — Claude / Cursor / Trae 等 AI IDE 直连
- **13 种审计日志导出格式**（Excel / Word / PDF / SQLite / ...）
- **纯 Python** — Windows / macOS / Linux 通吃，**无 C 扩展**
- **右键菜单集成** — 一行命令在 3 大平台安装原生右键菜单（HKCU / Quick Action / Nautilus + Dolphin）
- **i18n 国际化** — `zh-CN` / `en` 双语 CLI 自动检测 + `--lang` 强制 + 持久化偏好

### 快速开始 / Quick Start

#### 安装 / Installation

**推荐：一键硬隔离安装（v0.7.11+；v0.7.13 零前置，新电脑不用装 Python）**

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -sSL https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.sh | bash
```

**自动做的事 / Auto-handles**：
1. 检测 Python ≥ 3.8（Windows 没装 → 自动下载嵌入式 Python 3.12，**无管理员**）
2. 检测 git（没装 → 打印平台特定安装命令）
3. 创建硬隔离 venv（不污染系统 site-packages）
4. 从 GitHub Release 拉最新 wheel + SHA256 校验
5. 装 pandaone + 加 PATH
6. **自动跑 `pandaone install-context`**（Windows 右键菜单）
7. **自动跑 `pandaone install-hook`**（git pre-commit hook，cwd 是 git repo 时）

详见 [完整安装说明](docs/zh/install.md) · [Full Install Guide](docs/en/install.md)。

**备选：传统 pip 安装**

```bash
pip install pandaone-guard
pandaone install-context   # Windows 右键菜单
pandaone install-hook      # git pre-commit hook
```

#### 环境诊断（任何时候都能跑）/ Environment Diagnostics (run anytime)

```bash
python scripts/doctor.py                 # 人类可读
python scripts/doctor.py --json          # CI 用（返回 pass/fail）
python scripts/doctor.py --quiet         # 只显示 WARN / FAIL
python scripts/doctor.py --fix           # 自动修复 13 类问题（仅当前会话生效）
python scripts/doctor.py --fix --persist-path   # 持久化 PATH 到 HKCU（重启 shell 生效）
python scripts/doctor.py --fix-only      # 只跑修复 + 重测，跳过详细诊断
```

检测 9 个项目 + **自动修复 13 类问题**（pip / git / pandaone 装在 site-packages / pandaone.exe PATH / 指纹污染 / setuptools / 5 个运行时依赖）。

**`--fix --persist-path` 会做什么**：
- 卸载 site-packages 老版本 → 重装本地源码
- 删除污染的 `~/.pandaone_fp.txt`
- 自动 `pip install` 缺失的运行时依赖
- Windows：用 `setx PATH "%PATH%;<Scripts>"` 持久化到 `HKCU\Environment\Path`（新开的 PowerShell 自动看到）
- macOS / Linux：追加 `export PATH="..."` 到 `~/.bashrc` / `~/.zshrc`

#### 初始化项目 / Initialize Project

```bash
cd /path/to/your-project
pandaone init --root .
# 自动：
#   - 创建 .pandaone/ 目录
#   - 生成 config.json（17 文本 + 24 二进制扩展名）
#   - 创建 binary_snapshots.json（SHA256 字典）
#   - 初始化 .gitignore 排除
```

#### 写代码（合规路径）/ Write Code (Compliant Path)

```bash
# 修改 Python 文件
pandaone write \
    --file src/main.py \
    --reason "修复 user_id 类型注解" \
    --problem "原代码用 int，实际可能是 None" \
    --approach "改为 Optional[int]" \
    --old 'def get_user(user_id: int):' \
    --new 'def get_user(user_id: Optional[int]):'

# 替换二进制文件（图片/文档/PDF 等）
pandaone write \
    --file assets/logo.png \
    --reason "更新品牌 logo" \
    --problem "旧 logo 与新品牌色不匹配" \
    --approach "用新版 logo 替换" \
    --from-file /tmp/new_logo.png
```

#### 查看审计日志 / View Audit Log

```bash
# 命令行查看
pandaone log --last 10

# 导出为 Excel
pandaone log --format xlsx --output audit_report.xlsx

# 导出为 PDF（含中文支持）
pandaone log --format pdf --output audit_report.pdf

# 全部 13 种格式：text / csv / tsv / json / yaml / md / html / xlsx / docx / pdf / sqlite / rst / asciidoc
```

#### 项目状态仪表盘 / Project Status Dashboard

```bash
pandaone status --root .
```

显示 / Displays：项目路径、配置摘要、L1 锁定状态、二进制快照、最近审计、版本指纹等。
Project path, configuration summary, L1 lock state, binary snapshots, recent audits, version fingerprints, etc.

### 防御体系（7 层） / Defense Layers (7 Layers)

| 层 / Layer | 组件 / Component | 作用 / Function | 被绕过后的兜底 / Fallback if Bypassed |
|---|---|---|---|
| **L1** | file chmod | 文件级只读锁（attrib +r / chmod -w）<br/>File-level read-only lock | L2 watchdog |
| **L2** | watchdog | 实时文件监控 + git checkout 回滚<br/>Real-time file monitor + git checkout rollback | L3 hook |
| **L3** | pre-commit hook | 严格校验每个 staged 文件的 APPROVED 记录<br/>Strict validation of APPROVED record for every staged file | L4 / L5 |
| **L4** | 启动读 README<br/>Read README on startup | CLI 启动时加载项目元数据<br/>CLI loads project metadata at startup | L5 |
| **L5** | 自指纹<br/>Self-fingerprint | CLI 自身 SHA256 检测篡改<br/>CLI's own SHA256 detects tampering | L6 |
| **L6** | 二进制 SHA256 snapshot<br/>Binary SHA256 snapshot | 检测 .png/.pdf 等二进制篡改<br/>Detects tampering of .png/.pdf binaries | L7 |
| **L7** | GitHub Actions CI | PR 合入前审计验证（最终兜底）<br/>Audit verification before PR merge (final fallback) | 人工 review<br/>Manual review |

### MCP Server（AI Agent 直连 / AI Agent Native）

```json
// claude_desktop_config.json 或 Cursor MCP 配置
// claude_desktop_config.json or Cursor MCP configuration
{
  "mcpServers": {
    "pandaone": {
      "command": "pandaone-mcp",
      "env": {}
    }
  }
}
```

暴露 **11 个工具**：`pandaone_init` / `pandaone_lock` / `pandaone_unlock` / `pandaone_write` / `pandaone_log` / `pandaone_status` / `pandaone_install_hook` / `pandaone_watch` / `pandaone_install_git` / `pandaone_fingerprint_update` / `pandaone_ci`

### 真实场景测试 / Real-World Validation

完整实战验证报告：[实战验证报告.md](实战验证报告.md)

包含 / Includes：
- 7 层防御每层实战证据 / 7-layer defense, each layer with real-world evidence
- L3 hook 严重 bug 的发现 + 修复
- 隐藏文件锁定 bug 的发现 + 修复
- 13 种导出格式实测 / 13 export formats tested
- MCP 协议完整工作流

### 详细示例集 / Detailed Examples

- [EXAMPLES.md](EXAMPLES.md) — 10 个真实工作流 + 终端输出
- [examples/](examples/) — 5 个可运行的 Python demo 脚本
- [docs/](docs/) — 中英双语文档站（mkdocs）
- [docs/index.html](docs/index.html) — 交互式 HTML 文档首页（带终端动画）

### 命令清单 / Command List

| 命令 / Command | 用途 / Purpose |
|---|---|
| `pandaone init` | 初始化项目 |
| `pandaone lock` / `unlock` | 锁定 / 解锁所有受保护文件 |
| `pandaone write` | **核心**：审计写入（支持文本/二进制） |
| `pandaone log` | 查询审计历史（13 种导出格式） |
| `pandaone status` | 项目状态仪表盘 |
| `pandaone install-hook` | 安装 L3 pre-commit hook |
| `pandaone watch` | 启动 L2 watchdog 守护进程 |
| `pandaone serve` | **🆕 Web 实时仪表盘**（浏览器打开 `localhost:8765`,watchdog + SSE <100ms 推送）|
| `pandaone install-git` | 自动安装 git |
| `pandaone ci` | L7 CI 验证（git diff vs audit log）|
| `pandaone-mcp` | 启动 MCP server（stdio JSON-RPC） |

### 开发与测试 / Development & Testing

```bash
git clone https://github.com/hellob1889/Pandaone-AI-Agent
cd pandaone
pip install -e .[dev]
pytest tests/ -v
```

当前测试数：**342 passed, 1 skipped**（覆盖 i18n / write / status / lock / ci / watchdog / export / init / e2e / serve / desktop-icon / gitignore）

### 路线图 / Roadmap

| 版本 / Version | 状态 / Status | 关键能力 / Key Capability |
|---|---|---|
| v0.1.0 | ✅ | Phase 1-3 MVP（5 层防御） |
| v0.2.0 | ✅ | 多格式导出（7 种） |
| v0.3.0 | ✅ | 17 种文本保护 |
| v0.4.0 | ✅ | 24 种二进制 SHA256 |
| v0.5.0 | ✅ | MCP Server |
| v0.6.0 | ✅ | GitHub Actions CI |
| v0.6.1 | ✅ | L3 hook 强化（实战验证） |
| **v0.6.2** | ✅ | 隐藏文件锁定 bug 修复 |
| **v0.7.0** | ✅ | Phase 9 OS 右键菜单 + Phase 10 i18n（zh-CN/en）+ doctor.py 环境自检 + auto-fix 13 类 + PATH 持久化 |
| **v0.7.1** | ✅ | **28 个 bug 全修 + 4 大新功能**：P0 安全（#8/#12×2/#22/#23）+ P1（#2/#5/#15/#29）+ P2（#21/#6/#20/#9-#10）+ P3（#13/#4/#26/#39）+ UX（#14/#17/#48/#25/#28）+ 工程化（#版本漂移 / #README 分组标签 / #CRLF 根因）+ **🆕 文件夹熊猫锁图标**（desktop.ini + ICO）+ **🆕 Web 实时仪表盘**（watchdog + SSE <100ms）+ **🆕 Git 兼容**（init 自动写 .gitignore）+ **🆕 右键菜单真实可用验证**，298 测试通过 |
| **v0.7.2** | ✅ | **CI 工程化修复**：publish.yml Tests job 在干净 ubuntu-latest 容器 25s exit 1（setuptools pin 缺失）→ pin `setuptools==80.10.2` + `--no-build-isolation`，新增 pytest log artifact 上传。340 测试通过 |
| **v0.7.3** | ✅ | **agent 身份 + diff 捕获 + 面板 UI**：`--agent` 参数追踪调用方（Claude / Cursor / Trae / user:name）+ `--verbose` 完整 diff + 彩色面板格式（状态 / 文件 / commit / 行数 / 原因 / 问题 / 方法 / 差异）+ status 加 agent 分组统计 + HTML 导出加卡片布局 + i18n 新增 16 个键。342 测试通过 |
| **v0.7.9** | ✅ | **修 Windows `pandaone install-context`**：自 v0.7.0 失效（5 个 PowerShell bug 累积），改用 Python `winreg` 直接写 HKCU 注册表 |
| **v0.7.10** | ✅ | **Bug #40 修复**：移除 5 处 `D:\软件\Git\cmd` 硬编码路径，统一从 `%ProgramFiles%` / `LOCALAPPDATA` / `USERPROFILE` / `HKLM\SOFTWARE\GitForWindows\InstallPath` 动态派生候选路径——跨语言 Windows 通用 |
| **v0.7.11** | ✅ | **一键硬隔离安装脚本**：`install.ps1` (Windows) + `install.sh` (macOS/Linux)，从 GitHub Release 拉 wheel + SHA256 校验 + 强制 venv 隔离 + 加 PATH |
| **v0.7.12** | ✅ | **install 脚本默认全自动配环境**：自动跑 `install-context`（Windows 右键菜单）+ `install-hook`（git pre-commit hook，cwd 是 git repo 时）。`publish.yml` 修 checkout step，自动 attach install 脚本到 GitHub Release |
| **v0.7.13** | ✅ | **零前置安装**：Windows PATH 没 Python → 自动下载嵌入式 Python 3.12（**无管理员**、无 GUI）；Git 检测 + 平台特定命令（winget / brew / xcode-select / apt / dnf / yum / pacman / apk）；git 不可用时优雅跳过 hook 步骤 |

完整历史：[CHANGELOG.md](CHANGELOG.md)

### 许可 / License

MIT License — 详见 [LICENSE](LICENSE)

---

## English

### What is it?

Pandaone is a **7-layer defense system** that forces every code change through an audit gate.
Any modification to a protected file (17 text + 24 binary formats) must go through `pandaone write`,
which records reason / problem / approach as immutable audit evidence.

### Use cases

- 🤖 AI Agent development: prevent agents from bypassing review
- 🏢 Enterprise compliance: meet SOC2 / ISO 27001 code change audit requirements
- 👥 Team collaboration: every PR must have audit records before merging

### Install

**Recommended: One-line hard-isolated installer (v0.7.11+; v0.7.13 zero-preinstall)**

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -sSL https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.sh | bash
```

**Auto-handles**:
1. Detects Python ≥ 3.8 (Windows: auto-downloads embedded Python 3.12 if missing, **no admin**)
2. Detects git (prints platform-specific install command if missing)
3. Creates hard-isolated venv (no system site-packages pollution)
4. Pulls latest wheel from GitHub Release + SHA256 verify
5. Installs pandaone + adds to PATH
6. **Auto-runs `pandaone install-context`** (Windows right-click menu)
7. **Auto-runs `pandaone install-hook`** (git pre-commit hook, if cwd is a git repo)

See [Full Install Guide](docs/en/install.md) · [完整安装说明](docs/zh/install.md).

**Alternative: traditional pip install**

```bash
pip install pandaone-guard
pandaone install-context   # Windows right-click menu
pandaone install-hook      # git pre-commit hook
```

### Environment diagnostics (run anytime)

```bash
python scripts/doctor.py                 # human-readable
python scripts/doctor.py --json          # CI mode (returns pass/fail)
python scripts/doctor.py --quiet         # only WARN / FAIL
python scripts/doctor.py --fix           # auto-fix 13 issue classes (session only)
python scripts/doctor.py --fix --persist-path   # persist PATH to HKCU (new shell)
python scripts/doctor.py --fix-only      # just fix + re-check, skip detailed diagnosis
```

Checks 9 items + **auto-fixes 13 issue classes** (pip / git / pandaone-in-site-packages / pandaone.exe PATH / fingerprint pollution / setuptools / 5 runtime dependencies).

**What `--fix --persist-path` does**:
- Uninstall stale site-packages version, reinstall local source
- Remove polluted `~/.pandaone_fp.txt`
- Auto `pip install` for missing runtime deps
- Windows: use `setx PATH "%PATH%;<Scripts>"` to persist to `HKCU\Environment\Path` (new PowerShell shells see it automatically)
- macOS / Linux: append `export PATH="..."` to `~/.bashrc` / `~/.zshrc`

### Quick start

```bash
cd /path/to/your-project
pandaone init --root .

pandaone write \
    --file src/main.py \
    --reason "Fix user_id type annotation" \
    --problem "Original used int, could be None" \
    --approach "Change to Optional[int]" \
    --old 'def get_user(user_id: int):' \
    --new 'def get_user(user_id: Optional[int]):'
```

### 7 Defense Layers

| Layer | Component | Purpose |
|---|---|---|
| L1 | file chmod | File-level read-only lock |
| L2 | watchdog | Real-time file monitoring + git checkout rollback |
| L3 | pre-commit hook | Strict per-file APPROVED validation |
| L4 | startup README | CLI loads project metadata on startup |
| L5 | self-fingerprint | CLI's own SHA256 detects tampering |
| L6 | binary SHA256 snapshot | Detect .png/.pdf binary tampering |
| L7 | GitHub Actions CI | Pre-merge audit verification (final backstop) |

### MCP Server

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

Exposes 11 tools for AI agents (Claude / Cursor / Trae).

### License

MIT — see [LICENSE](LICENSE)

### Links

- [PyPI Package](https://pypi.org/project/pandaone-guard/)
- [GitHub Repository](https://github.com/hellob1889/Pandaone-AI-Agent)
- [Issue Tracker](https://github.com/hellob1889/Pandaone-AI-Agent/issues)
- [Documentation](https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/README.md)
- [Changelog](https://github.com/hellob1889/Pandaone-AI-Agent/blob/main/CHANGELOG.md)
- [实战验证报告 (Validation Report)](实战验证报告.md)