# Changelog

All notable changes to Pandaone AI Agent will be documented in this file.

## [0.7.15] - 2026-10-04

### 主题：AI Agent 真实体验修复 —「装上就能用，接上就干净」

**背景**：GitHub 下载量 22 次 / 0 star / main CI 红。逐条复盘真实使用链路（pip install → MCP 接入 → 日常调用）后，发现的问题不在宣传的功能列表里，而在**第一次真实调用**上。本版本全部围绕「让 MCP 客户端和脚本拿到的输出干净、让 CLI 直调不失效」。

### Fixed: CLI 直接运行静默 no-op（致命）

`cli.py` 是 loader，通过 `exec()` 把 `cli_chunks/part_001-006.py` 编译进同一命名空间，但 exec 时把 `__name__` 覆写为 `"pandaone.cli"`，导致 `python cli.py` 的 `if __name__ == "__main__"` 永假——**直接运行 CLI 什么都不发生，exit code 0**。保存 `_is_main` 标记修复。这是比任何功能缺陷都严重的一类 bug：用户装完第一次敲命令就哑火。

### Fixed: MCP 输出三重噪音（ANSI 转义 + banner + roadmap）

MCP server 通过 subprocess 调 CLI 再回传 stdout，此前把 40+ 行彩色 banner、README 摘要、roadmap 一起塞给 MCP 客户端，污染模型上下文。修复：

- `_run_cli` 统一加 `--silent`，并用 `_strip_ansi()` 剥离 ANSI 转义序列
- CLI 的 banner / README 摘要改为**仅 TTY 输出**（`sys.stdout.isatty()` 门控）——人类在终端仍能看到完整 banner，管道和 MCP 拿到的只有结果

### Added: write 审计通道支持新建文件

此前 `write` 对不存在的文件直接 REJECTED（"目标文件不存在"），Agent 无法通过审计通道创建任何新文件。现在：提供 `--content` + 受保护扩展名即可创建，父目录自动补建，审计记录标注 `"action": "create"`。

### Fixed: 只读检测在 root 下失效

`os.access(path, os.W_OK)` 对 root 恒返回 True，导致 L1 锁（444 文件）对 root 不设防。改为直接检查权限位 `st_mode & S_IWUSR`。（注：OS 层面 root 物理上不受权限位约束，本修复保证 CLI 审计层行为一致；相关测试在 root 环境标记 skip。）

### Improved: log / status 输出补全

- `log` 打印此前为死代码的记录头（ID / 时间 / agent），字段标签本地化，新增 `Lines: +N -M` 与 Diff 面板（verbose 不截断）
- `status` 补 L2 watchdog 区块（`os.kill(pid, 0)` 探活）与未 init 提示；计数标签本地化
- `log` / `export` 未 init 时给出明确提示而非空输出

### Fixed: MCP server 版本漂移

`pandaone_mcp` 硬编码 `__version__ = "0.7.7"`，与实际包版本（0.7.14+）脱节 7 个版本。改为动态解析 `pandaone.__version__`，`serverInfo` 同步。

### Fixed: 测试套件可移植性（CI 红的直接原因）

- 5 个测试文件硬编码作者机器路径（`D:\软件\Git\cmd\git.exe`）→ `shutil.which("git")` 动态探测
- 2 个静态分析测试读 `cli.py`（loader）而非 `cli_chunks/` → 修正读取方式
- `test_audit_i18n_ci.py` 的 `fresh_cli` fixture 从 `git show HEAD` 恢复文件，会**静默回滚开发者未提交的修改**（本次开发中实际吃掉过一次修复）→ 改为备份工作区状态
- install-git 测试的输出长度阈值按英文硬编码（>50），i18n 中文输出（38 字符）必挂 → 对齐为 >20
- 权限类测试在 root 环境标记 skip（环境限制，非产品缺陷）

### Fixed: 安装包缺文件

`pyproject.toml` 补 `[tool.setuptools.package-data]`：`installer/windows/*.ps1`、`installer/macos/*.sh`、`installer/linux/*.sh` 随包分发，修复安装后右键菜单脚本缺失。

## [0.7.14-hotfix1] - 2026-09-21

### Fixed: 右键菜单子项不可见（ExtendedSubCommandsKey 迁移）

Win11 22H2+ 右键能看到 Pandaone 但展开看不到 4 个子项。原脚本用 MUIVerb + SubCommands (V1) 与 Win11 资源管理器渲染逻辑不兼容。

迁移到微软官方推荐的 ExtendedSubCommandsKey (V2)：父菜单 (Default) 改为空字符串（V2 强制）；删除 MUIVerb/SubCommands；4 个 verb 搬到独立 Shell\ 子键；3 个入口共享命令仓库（注册表 -51%）；Init 加 CommandFlags=0x20 视觉分隔。最低 Win10 1809。

顺手修复 SetRegValue 对 DWord/Binary 不支持（PS5.1 把 0x20 推断为 long），该隐患从 v0.7.x 就存在，本次因 CommandFlags 首次暴露。

新增 test_registry.bat / .ps1 / _real.bat 三个回归测试。

实战报告：`实战验证报告_v0.7.14_右键菜单修复.md`。

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
- `test_call_fingerprint_update_writes_hash` — 使用默认密码 `0000`（CLI 默认值）
- `test_call_ci_reachable_returns_verification` — 验证 MCP wrapper 在 base 不存在时不崩溃

测试结果：**89 passed (was 84)** · 11/11 工具覆盖（was 7/11 = 64%）

### Added: README 视觉冲击升级（PR #43）

**问题**：README 首屏只有 ASCII 框 + 徽章，新访客 5 秒内**看不出** pandaone 是干嘛的。

**修复**：在 4 个战略位置嵌入真实截图：

| 位置 | 截图 | 视觉作用 |
|---|---|---|
| 第 11-15 行（顶部 logo 下方） | `terminal-write.png` | 首屏直接看到 `[APPROVED]` 凭证 |
| 查看审计日志 章节 | `terminal-log.png` | 展示 reason/problem/approach 三段式凭证 |
| 项目状态仪表盘 章节 | `terminal-status.png` | 41 保护格式 + L1/L6 实时状态 |
| Web