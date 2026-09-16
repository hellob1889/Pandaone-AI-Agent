# Changelog

All notable changes to Pandaone AI Agent will be documented in this file.

## [0.7.14] - 2026-09-16

### M8ven Trust Index A 级 — Verified Publisher

**用户旅程**：「用户能在 GitHub 上面下载就能用的」原则延伸到「AI Agent 生态可信」层面。

v0.7.14 是 v0.7.13 后**两天内的快速迭代**，核心目标是：

1. **通过 M8ven Trust Index 全量审查**
2. **修复 M8ven 公开 finding 中的 1 个 hard blocker**
3. **让 README 在 GitHub 首屏 5 秒内传达产品价值**

### Added: MCP 工具 annotations 全量声明（PR #44）

**问题（M8ven 公开 finding）**：
- 11 个 MCP 工具 **全部**缺失 4 个 MCP spec 要求的 hints（readOnlyHint / destructiveHint / idempotentHint / openWorldHint）
- OpenAI 目录**直接拒绝收录**缺少任一 hint 的工具
- 这是 OpenAI 目录合规的硬性要求，不是软建议

**修复**（`src/pandaone_mcp/__main__.py`）：

| 工具 | readOnly | destructive | idempotent | openWorld | 行为依据 |
|---|---|---|---|---|---|
| `pandaone_init` | F | F | F | F | 创建 `.pandaone/`，每次运行变更状态 |
| `pandaone_lock` | F | F | T | F | 改 attrs；可逆；锁两次=锁一次 |
| `pandaone_unlock` | F | F | T | F | 锁的反操作；同样幂等 |
| `pandaone_write` | F | **T** | F | F | 覆盖文件内容；每次追加审计记录 |
| `pandaone_log` | **T** | F | T | F | 只读查询 |
| `pandaone_status` | **T** | F | T | F | 只读查询 |
| `pandaone_install_hook` | F | F | T | F | 写 `.git/hooks/pre-commit`；幂等 |
| `pandaone_watch` | F | F | F | F | 启动守护进程；不幂等 |
| `pandaone_install_git` | F | F | T | **T** | 从 GitHub Releases 下载便携 git |
| `pandaone_fingerprint_update` | F | F | T | F | 写哈希；同密码→同状态 |
| `pandaone_ci` | **T** | F | T | F | 纯校验；不改仓库 |

**配套测试**（`tests/test_mcp_server.py`）：

- `test_each_tool_has_annotations` — schema 验证，确保每个工具有 4 个 hints 都是 bool
- `test_call_install_hook_creates_precommit` — 验证 hook 文件被写入
- `test_call_install_git_probe_only_safe` — 验证不触发下载
- `test_call_fingerprint_update_writes_hash` — 使用默认密码 `"0000"`（CLI 默认值）
- `test_call_ci_reachable_returns_verification` — 验证 MCP wrapper 在 base 不存在时不崩溃

测试结果：**89 passed (was 84)** · 11/11 工具覆盖（was 7/11 = 64%）

### Added: README 视觉冲击升级（PR #43）

**问题**：README 首屏只有 ASCII 框 + 徽章，新访客 5 秒内**看不出** pandaone 是干嘛的。

**修复**：在 4 个战略位置嵌入真实截图：

| 位置 | 截图 | 视觉作用 |
|---|---|---|
| 第 11-15 行（顶部 logo 下方） | `terminal-write.png` | 首屏直接看到 `[APPROVED]` 凭证 |
| "查看审计日志" 章节 | `terminal-log.png` | 展示 reason/problem/approach 三段式凭证 |
| "项目状态仪表盘" 章节 | `terminal-status.png` | 41 保护格式 + L1/L6 实时状态 |
| "Web 实时仪表盘" 章节 | `dashboard.png` | 真实 Web 仪表盘截图 |

**第一性原则：真实数据，非 mockup**

所有截图用 `pandaone.jsonl` 真实审计数据渲染，rich 库重画保证排版整齐。**不是编的**。

### Added: M8ven Verified Publisher 徽章

**Claim 流程**（用户手动）：
1. 访问 `https://github.com/apps/m8ven-verify/installations/new?state=...`
2. 选择 "Only select repositories" → `hellob1889/Pandaone-AI-Agent`
3. GitHub sudo mode 密码确认
4. 安装完成 → M8ven 自动识别 publisher

**徽章**（README 第 75 行）：

```markdown
[![M8ven Score](https://m8ven.ai/badge/mcp/hellob1889/pandaone-ai-agent)](https://m8ven.ai/mcp/hellob1889/pandaone-ai-agent)
```

使用**官方 M8ven URL**而非 hardcoded shields.io，**分数变化自动更新**。

### M8ven Trust Index 分数变化

| 节点 | score | grade | trust | warn | fail |
|---|---|---|---|---|---|
| 初始（未 claim） | 74 | C | — | 2 | 1 |
| Claim 完成 | 96 | A | 89 | 2 | 1 |
| **v0.7.14（PR #43 + #44 merged）** | **100** | **A** | 89 | **0** | **0** |

**对用户的实际好处**：
- OpenAI 目录合规（之前会被拒绝）
- 11/11 工具覆盖（之前 7/11 = 64%）
- Live Monitored = 每次 push 自动重测 + CVE 告警

### Operational: 每日 M8ven 监控 cron

创建了 Schedule `89dfb0b6`（每天 09:00 Asia/Shanghai），自动：
1. 抓取最新 M8ven score JSON
2. 与历史记录对比 delta
3. 写到 `.pandaone/m8ven_history.jsonl`
4. 输出简短报告；分数下降 / warn 增加时触发 ALERT

### 对抗式审查（v0.7.14）

- ✅ 11/11 工具 annotations 严格匹配 handler 实际行为
- ✅ 全部 5 张视觉资产 HTTP 200 + valid PNG signature
- ✅ M8ven badge URL 是官方端点，会自动更新（非 hardcoded）
- ✅ git pre-commit hook (L3) 仍正常工作 — 大文件 push 没绕过
- ⚠️ 3 hidden improvements 需要 M8ven 付费 API key 才能解锁（不是必需的）
- ⚠️ trust_score 89 不是 100，原因是 `stars=0, adoption_tier=unknown`（reputation 子项）

## [0.7.13] - 2026-09-15

### Changed: install 脚本支持新电脑零前置环境 (PR #42 增强)

**用户诉求**：「新电脑，需要配什么环境，才能使用，我希望拉取下来的 pandaone 能自动配好所有的环境，而不是手动配」

之前 v0.7.12 要求新电脑**必须先装 Python ≥ 3.8**，否则 install 失败退出。v0.7.13 让 install 脚本真正"零前置"：

| 场景 | v0.7.12 行为 | v0.7.13 行为 |
|---|---|---|
| PATH 没 Python | ❌ 退出，提示"please install Python" | ✅ **自动下载嵌入式 Python 3.12** 到 `%LOCALAPPDATA%\pandaone\python\`（无需管理员） |
| PATH 没 Git | ⚠️ 静默跳过 hook 步骤 | ✅ 明确打印安装命令（winget / brew / apt / dnf / pacman / apk） |
| git hook 步骤但 git 不可用 | ⚠️ 跑 install-hook 失败 warn | ✅ 直接跳过 hook 步骤 |

**自动装 Python 实现（Windows）**：
1. 检测 `python` / `python3` / `py` 在 PATH 里 ≥ 3.8
2. 没有 → 从 python.org 下载 `python-3.12.7-embed-amd64.zip` (~11 MB)
3. 解压到 `%LOCALAPPDATA%\pandaone\python\`（**用户级，无管理员**）
4. 启用 `import site`（嵌入式 Python 默认禁用，否则 venv 装 pip 包会失败）
5. 用这个嵌入式 Python 创建 venv + 装 wheel

**macOS / Linux 自动装 Python**：⚠️ **不做**
- macOS 用 brew install python3（需要用户先装 brew）
- Linux apt/yum/dnf/pacman 都涉及 sudo
- 嵌入式 Python 在 Linux/macOS 平台限制较多
- install 脚本仍给对应命令提示（brew / apt / dnf / pacman / apk）

**自动装 Git**：⚠️ **不做**（所有平台）
- Windows: 需要 winget admin 或手动下载 MSI
- macOS: xcode-select --install 或 brew install git
- Linux: 涉及 sudo
- install 脚本打印对应命令，git 装好后用户重跑 install 即可

**对抗式审查**：
- ✅ 嵌入式 Python 是**无管理员、无 GUI、安全可控**的（python.org 官方分发）
- ⚠️ 自动装 Python 在 macOS/Linux **不做**——平台差异 + 权限问题
- ⚠️ 自动装 Git **不做**——风险大于价值
- ✅ Git 不可用时 hook 步骤**优雅跳过**（不报错）
- ✅ 友好提示让用户知道下一步该做什么

**新电脑 onboarding 流程（v0.7.13）**：
```powershell
# Windows: 之前需要先装 Python, 现在只需要 PowerShell
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.ps1 | iex

# 跑完输出:
#   ✓ Embedded Python installed
#   ⚠ git not found, run: winget install Git.Git
#   ✓ Context-menu installed (右键菜单)
#   ✓ Git pre-commit hook installed (or [SKIP] if no git)

# 用户装好 git 后再跑一次 install.ps1 → hook 自动装好
```

## [0.7.12] - 2026-09-15

### Changed: install 脚本默认自动配置环境 (PR #41 增强)

**用户诉求**：「如果从 GitHub 安装 pandaone，所有的环境要自动配置好」

之前 v0.7.11 的 install.ps1/install.sh 只做了"装 pandaone + 加 PATH"，**Windows 右键菜单**和 **git pre-commit hook** 还要用户手动跑 `pandaone install-context` / `pandaone install-hook`。

**v0.7.12 默认全自动**：

| 步骤 | v0.7.11 行为 | v0.7.12 行为 |
|---|---|---|
| 装 pandaone 到 venv | ✅ 自动 | ✅ 自动 |
| 加 venv/Scripts 到 PATH | ✅ 自动 | ✅ 自动 |
| Windows 右键菜单 | ❌ 手动 `pandaone install-context` | ✅ **自动** `pandaone install-context`（仅 Windows） |
| Git pre-commit hook | ❌ 手动 `pandaone install-hook` | ✅ **自动** `pandaone install-hook`（仅当 cwd 是 git repo） |

**用法（无变化）**：
```powershell
# Windows
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -sSL https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.sh | bash
```

跑这一行命令后，**所有环境都配置好**，不用任何后续步骤。

**Opt-out flags**（不想自动配置环境的）：
```powershell
irm ... | iex -SkipContext -SkipHook   # Windows
curl ... | bash --skip-hook             # macOS/Linux
```

**对抗式审查**：
- ✅ Idempotent：右键菜单/hook 已存在时不重复装
- ✅ Per-repo scope：hook 安装只在当前 cwd 的 git repo 内（不污染其他 repo）
- ✅ Non-blocking：自动配置失败不影响 pandaone 主功能（仅 warn）
- ✅ Opt-out：-SkipContext / -SkipHook / --skip-hook 让用户能关闭
- ✅ No silent fallback：失败时打印明确错误 + 重试命令

## [0.7.11] - 2026-09-15

### Added: 一键硬隔离安装 (PR #41)

**问题**：用户机器上多个 Python 版本（3.10 + 3.11）共存时，`pip install --user pandaone-guard==0.7.10` 只更新其中一个 Python 的 site-packages，另一个 Python 的 entry point（`pandaone.EXE`）会继续跑旧版本（0.7.8），导致 `pandaone doctor` 报告错误的版本号。这是 Python 多版本隔离的通用坑，不是 pandaone 独有。

**解决方案**：GitHub Release v0.7.11 新增两个**硬隔离**安装脚本，自动把所有内容装到专用 venv（不碰任何 site-packages）：

| 平台 | 脚本 | venv 路径 |
|---|---|---|
| Windows | `install.ps1` | `%LOCALAPPDATA%\pandaone\venv\` |
| macOS / Linux | `install.sh` | `~/.local/share/pandaone/venv` |

**特性**：
- ✅ 硬隔离：永远 venv 装，**不** fallback 到 `--user` / system site-packages
- ✅ 从 GitHub Release API 拉**最新** wheel（不是 PyPI，永远跟随最新 release）
- ✅ SHA256 校验 GitHub attestation（防止中间人）
- ✅ 自动把 venv/Scripts（Windows）或 venv/bin（*nix）加到 PATH
- ✅ 自动验证 `pandaone --version` 和 `importlib.metadata.version`
- ✅ 复用已下载 wheel + 已存在 venv（升级而非重建）

**用法**：

```powershell
# Windows 一行 (PowerShell)
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.ps1 | iex
```

```bash
# macOS / Linux 一行
curl -sSL https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.sh | bash
```

或从 [GitHub Release v0.7.11](https://github.com/hellob1889/Pandaone-AI-Agent/releases/tag/v0.7.11) Assets 下载 `install.ps1` / `install.sh` 本地跑。

**publish.yml 修改**：
- L270 `files:` 改为 multi-line glob：`dist/*.whl` + `dist/*.tar.gz` + `install.ps1` + `install.sh`，让 GitHub Release 自动 attach 这两个脚本
- release body 加 "Hard-isolated install" 段落，链接到 GitHub raw URL

**对比传统 pip install**：

```bash
# 传统方式 (用户机器 Python 3.10/3.11 共存时会冲突):
pip install --user pandaone-guard==0.7.10
# → 装到 Python 3.10 user site-packages
# → 但 pandaone.EXE 来自 Python 3.11 scripts，仍然跑 Python 3.11 site-packages 里的旧版本
# → pandaone --version 显示旧版本号

# 硬隔离方式 (推荐):
irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/install.ps1 | iex
# → 装到独立 venv: C:\Users\X\AppData\Local\pandaone\venv\
# → pandaone.EXE 来自该 venv Scripts 目录
# → pandaone --version 永远显示真实装的版本
```

### 升级方式

- **已用 install.ps1/install.sh 装的**：`irm ... | iex` 再次跑一次（自动检测并升级）
- **传统 pip install 装的**：`pip install --upgrade pandaone-guard`（不变）

## [0.7.10] - 2026-09-15

### Fixed (PR #40 — Bug #40: 移除 `D:\软件\Git\cmd` 等作者机器硬编码路径)

**问题**：v0.7.9 及之前版本，`pandaone doctor` / `pandaone install-git` / git auto-detection 在 4 处硬编码了作者自用机器的路径 `D:\软件\Git\cmd`。99.9% 的 Windows 用户都没有这条路径，导致：
- `_find_git_executable` 永远多跑一次 `os.path.isfile('D:\软件\Git\cmd\git.exe')` 返回 False
- `for prefix in ["D:\\", "C:\\"]: for sub in ["软件", "Program Files", ...]` 这种"作者目录白名单"模式跨语言失效（中文 Windows 是"软件"，英文 Windows 是"Software"）
- 4 处候选列表各自维护，重复硬编码 → 永远同步不齐

**修复**：
- 在 `src/pandaone/git_installer.py` 新增 `_windows_candidate_dirs()` 单一来源函数
- 来源基于**环境变量 + 注册表**：
  1. `%ProgramFiles%` / `%ProgramFiles(x86)` / `%ProgramW6432%\Git\cmd|bin`
  2. `%LOCALAPPDATA%\Programs\Git\cmd|bin` (Portable Git / 微软商店版)
  3. `%USERPROFILE%\scoop\apps\git\current|2.47.1|2.43.0\cmd|bin` (Scoop 安装)
  4. 注册表 `HKLM\SOFTWARE\GitForWindows\InstallPath\cmd|bin` (Git for Windows 安装器自写)
  5. `C:\Git\cmd|bin` (便携位置)
  6. `%USERPROFILE%\Git\cmd` 等常见解压位置
- 4 处调用点全部改为调用 `_windows_candidate_dirs()`：
  - `git_installer.py` `_find_git_executable`
  - `cli_chunks/part_003.py` `_resolve_git_exe`
  - `cli_chunks/part_005.py` `cmd_install_git`
  - `pandaone_guard/__main__.py` `_ensure_git_in_path`
  - `tests/conftest.py` `GIT_CANDIDATES`

**对抗式审查**：
- 不假设用户在哪个盘（C/D/E/...）
- 不假设语言环境（中文"软件" vs 英文"Software"）
- 不假设安装方式（标准 / Scoop / 微软商店 / 解压）
- 注册表项是 Git for Windows 安装器**自己写的**，作为权威来源
- 所有调用点共用一个函数，杜绝未来再漂移

### 用户面行为变化

- `pandaone doctor` 在 Windows 上能正确检测到**用户实际安装**的 git（不再受作者机器路径污染）
- Git 在 PATH 时仍优先返回（保持 fast path 行为）
- 在 Windows 上 Git 装在非默认位置（`D:\dev\Git` 等）也能检测（注册表 InstallPath + 多种常见子目录模式）

### 升级方式

```bash
pip install --upgrade pandaone-guard==0.7.10
```

无需 `--update-fingerprint`（本次未改 cli loader，纯 git 检测逻辑）。

## [0.7.9] - 2026-09-14

### Fixed (PR #35 — `pandaone install-context` Windows broken since v0.7.0)

**问题**：Windows 用户从 v0.7.0 起右键菜单永远不可用。修 PS1 6 个 bug 仍不能完整工作。

**Root cause**：PowerShell 脚本 5 个累积 bug 导致 parser 失败：

1. **5 个 UTF-8 BOM**：文件头 `EF BB BF` 重复 5 次，PowerShell 5.1 parser 把后续 `[CmdletBinding()]` 误认为普通 attribute
2. **`#Requires -Version 5.1` line**：v0.7.4+ 添加，PowerShell 5.1 parser 把它当成 `#Requires` 后立即接 `[CmdletBinding()]` 失败
3. **`[CmdletBinding()]` 后函数体内 `$ErrorActionPreference = 'Stop'`**：PowerShell 5.1 parser bug，把 param list 延伸到 `$ErrorActionPreference`
4. **注释里的 `(任意文件) (pandaone init) (pandaone lock)`**：PowerShell 5.1 parser 把注释里的括号也算 param list 括号
5. **PowerShell 7+ 表达式 `if`**：`$VAR = if (...) { ... } else { ... }` 是 PS7+ 语法，用户机器 PS5.1 不支持

**修复策略**：不再折腾 PowerShell — Windows 直接用 Python `winreg` 模块写注册表，完全 bypass PowerShell。注册表结构与原 PS1 等价（HKCU\\Software\\Classes\\\*\\shell\\Pandaone + 4 subcommands）。

### Fixed (PR #35 — cli.py loader `__file__` bug)

`cli.py` loader 用 `_exec_ns["__file__"] = str(Path(__file__).resolve())` 把 `__file__` 钉死成 cli.py 自己路径，所有 part_* 脚本里 `ROOT = Path(__file__).parent.parent` 解析到 site-packages/ 而非 site-packages/pandaone/。导致 L4 防线 README.md 找不到 + portable git 下载错位 + sys.path.insert 错。

**修复**：loader 在每个 chunk exec 前 `_exec_ns["__file__"] = str(chunk.resolve())` 让每个 chunk 用自己路径。

### Fixed (PR #35 — README.md not in wheel)

`MANIFEST.in` 没 `include src/pandaone/README.md`，导致 wheel 安装后 L4 防线 README summary 永远报错 "[ERROR] README.md 未找到"。

**修复**：`include src/pandaone/README.md`。

### Added (PR #35 — install-context 暴露 stderr)

`cmd_install_context` 之前用 `subprocess.run(..., capture_output=True)` 把 PowerShell stderr 完全吞掉，用户只能看到 exit 1 不知道原因。

**修复**：去掉 `capture_output=True`，stderr 直接输出 + 加 `TimeoutExpired/FileNotFoundError` 友好错误消息。

### 升级方式

```bash
pip install --upgrade pandaone-guard

# 升级后首次跑会触发 L5 指纹更新（v0.7.9 改了 cli loader, SHA256 变了）:
pandaone --update-fingerprint 0000

# 然后右键菜单安装:
pandaone install-context
```

### 用户面行为变化

- `pandaone install-context` 在 Windows **真的能用**了（之前 v0.7.0~v0.7.8 一直不可用）
- 注册表写入通过 Python `winreg`，不依赖 PowerShell（无 PS5.1/PS7 兼容问题）
- 4 个子命令：Init / Lock / Status / Unlock
- macOS / Linux 仍用 .sh 脚本（未受影响）

## [0.7.8] - 2026-09-14

### Fixed (PR #28 follow-up: git auto-installer + doctor 子命令真正可用)

PR #28 在 fix/auto-install-git 分支写了 git_installer.py / cmd_doctor.py / i18n_extras.py,
通过 PR #31 merge 到 main。但 PR #28 设计了两个**隐藏 bug**,让 doctor 子命令
对 `pandaone` entry point 实际**不可用**,`ci --base` 参数**被忽略**。v0.7.8 修复
这两个 bug + 加 doctor 的 cmd_doctor 等价 PR #28 的内容。

- **PR #32 (P0 / 阻断): `pandaone doctor` 不可用**
  - 现象:`pandaone --help` 列 14 个子命令,没有 doctor。`pandaone doctor` 报
    `invalid choice: 'doctor'`。
  - 根因(双 bug):
    1. `pyproject.toml` entry point `pandaone = "pandaone:main"` 走
       `pandaone/__init__.py:main`,**完全跳过 `__main__.py`** — monkey-patch
       注册的 doctor 子命令从未生效。
    2. v0.7.7 把 84KB cli.py 拆 cli_chunks/part_*.py 用 `exec()` 加载,loader 用独立
       `_exec_ns` dict 作 exec namespace,exec 后 `for k,v: globals()[k]=v` 浅复制。
       Python 函数 `__globals__` 在 def 时绑定,part_006 的 `def main():` 的
       `__globals__` 指向原 `_exec_ns` (不是 cli 模块 globals)。monkey-patch
       `cli.build_parser = patched` 只改 cli 模块 globals,`cli.main()` 内部查找
       `build_parser` 走自己的 `__globals__` — 看不到 patched version。
  - 修复:
    1. `src/pandaone/__main__.py`:把 `if __name__ == "__main__":` 保护块改成
       顶层 `def main():`,让 entry point 能调到。
    2. `pyproject.toml`:entry point 改 `"pandaone.__main__:main"` — import 时
       触发 `_ensure_doctor_registered()` 注册副作用。
    3. `src/pandaone/cli.py` loader:`_exec_ns = globals()` 直接共享 dict 引用,
       让 part_006 main 函数的 `__globals__` 自然指向 cli 模块 globals。

- **PR #33 (P1): `pandaone ci --base` 被 HEAD~1 fallback 顶替**
  - 现象:`pandaone ci --base main --head HEAD` 即使 base 解析成功,实际 diff
    仍是 `HEAD~1..HEAD`,`--base main` 参数被静默忽略。
  - 根因:`cmd_ci` 里 `candidates = ["HEAD~1", base, f"origin/{base}", ...]`
    `HEAD~1` 永远存在且排第一,`for ref in candidates: ... base = ref` 把
    用户的 base 顶替掉。
  - 修复:把顺序改成 `[base, f"origin/{base}", "HEAD~1", "main", "master", ...]` —
    用户传的 base 优先,HEAD~1 降级为真正的 fallback。
  - 测试:新增 `test_ci_explicit_base_overrides_head_minus_1` 回归测试,用
    detached HEAD 让 main 不跟随 forward,断言 `--base HEAD~1` 和 `--base main`
    表现不同 (证明 base 真的在用),`--base <evil_sha>` 看 0 变更 PASS。

### Added (PR #28 / #31)
- **`git_installer.py`**:跨平台 git 自动安装 (Windows: winget / choco / scoop /
  manual download;macOS: brew;Linux: apt / dnf / yum)。多路径探测 (PATH +
  WindowsApps shim + `D:\软件\Git` 等用户目录 + USERPROFILE `\cmd\git.exe`)。
  缺失 git 时 `pandaone` 启动自动触发安装,避免 L2 (watchdog 回滚) 和 L3
  (pre-commit hook) 静默降级。
- **`cmd_doctor.py`**:`pandaone doctor` 子命令。报告 7 层防护 + git + Python
  状态,支持 `--silent --json` 输出给 CI / 监控系统用。退出码:0=全部 OK,
  1=git 缺失,2=Python 太老。
- **`i18n_extras.py`**:18 个新 key × 2 语言 (zh-CN + en) 翻译,doctor + git gate
  文案。
- **32 个新单测**:`tests/test_git_installer.py` (19 个) + `tests/test_cmd_doctor.py`
  (13 个),覆盖跨平台 git 检测、安装、doctor 输出格式、JSON 结构、退出码。

### Notes
- 升级方式:`pip install --upgrade pandaone-guard`
- 用户面行为变化:
  - `pandaone --help` 多一个 `doctor` 子命令
  - `pandaone ci --base <ref>` 现在尊重用户传的 `<ref>`,不被 HEAD~1 顶替
  - `pandaone` 启动自动检测 git,缺失时尝试自动安装 (可用
    `PANDAONE_SKIP_GIT_CHECK=1` 环境变量跳过,适合 CI 环境)
- API 兼容性:不破坏现有 API;`pandaone write` / `pandaone init` / `pandaone ci`
  等所有子命令行为不变

## [0.7.7] - 2026-09-13

### Fixed (验证报告驱动的批量 bugfix)

本 release 修复了 pandaone-运行可行性验证报告.html 中识别的 6 个问题，让 L7 防线 (GitHub Actions CI 审计) 真正生效。

- BUG-04a (P0 / 阻断): .github/workflows/audit.yml 切到 pip install -e . + pandaone ci
  - 之前 audit.yml 装的是 PyPI 上的 pandax-guard 固定版本 + 调用旧 CLI pandax ci。
  - 后果：CI 一直跑"绿色假阳性"，验证的是被废弃的旧实现。
  - 修复：装当前分支 (pip install -e .)，调用命令切到 pandaone ci。
- BUG-01 (P1): src/pandaone_mcp/__init__.py 补 from .__main__ import main re-export
  - console_scripts 入口 pandaone_mcp:main 要求 main 从 package 顶层可导入。
  - 修复：参考 pandaone_guard/__init__.py 的同模式，显式 re-export。
- BUG-04b (P2): README 解析器兼容中英对照标题 ## 当前阶段 / Current Phase
  - 旧解析器严格相等匹配，双语标题会让 phase_lines 永远为空。
  - 修复：增加 OR 分支接受双语标题。
- BUG-05 (P3): pandaone write 用 git add -f 强制暂存审计日志
  - .pandaone/pandaone.jsonl 被 .gitignore 排除，普通 git add 会被 git 拒绝。
  - 修复：加 -f 强制暂存，让审计 jsonl 跟 commit 原子绑定。
- BUG-02 + BUG-06 (P4): 仓库卫生清理
  - 清理磁盘残留：src/pandax_guard.egg-info/ / test_project/ / __pycache__/ x 6 / .pytest_cache/
  - 验证 .gitignore 已覆盖所有模式。

### Notes
- 本 release 是纯 bugfix，不引入新功能、不破坏 API
- 升级方式：pip install --upgrade pandaone-guard
- 用户面行为变化：MCP server 现在能正常启动（之前是 import 报错）

## [0.7.6] - 2026-09-13

### Changed (品牌切回 / Rebrand Cutover)

- PyPI 分发名从 pandax-guard 切回 pandaone-guard (PR #23)
- pyproject.toml name = "pandaone-guard", version = "0.7.6"
- 13 个用户面文件:pandax-guard → pandaone-guard (还原 PR #12 临时回退)
- 发布到 PyPI 后用户可执行 pip install pandaone-guard