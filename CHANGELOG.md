# Changelog

All notable changes to Pandaone AI Agent will be documented in this file.

## [0.7.17] - 2026-10-07

### Added: CI 真实安装冒烟关卡（防「装上了跑不起来」复发）

**动机**：v0.7.14 的致命缺陷是用户 `pip install` 之后 CLI 跑不起来。复盘发现 CI 里
唯一的冒烟用的是 **editable 安装**（`pip install -e .`）——它直接从源码目录 import，
**绕开整个 wheel 打包路径**，因此 package-data 漏配、入口点写错、子包没打进 wheel
这几类问题在结构上永远不可能被 editable 冒烟发现。CI 全程绿，用户第一分钟就崩。

**处置**：在 `lint.yml` 的 Smoke Tests job（仓库规则集的必需状态检查）里补一步
**非 editable 真实安装**：

```
python -m venv … && pip install .   # 真正走 wheel
pandaone --help                      # CLI 可执行
command -v pandaone-mcp              # MCP 入口点在
已装版本 == pyproject 声明版本        # 版本漂移
```

这一步复现的就是真实用户的第一分钟，且因为挂在必需检查上，**装坏了就合不进 main**。

### Changed: `pandax-guard` 弃用声明

PyPI 上的旧包名 **`pandax-guard` 已弃用**（停在 0.7.4，不再更新也不再修 bug）。
README 中英文双语顶部均加入醒目提示，并给出迁移命令：

```bash
pip uninstall pandax-guard && pip install pandaone-guard
```

避免新用户搜到旧包装上，得到一份 2026-09 的、带已知缺陷的实现。

## [0.7.16] - 2026-10-07

### Fixed: unlock 不再把受保护文件变成 world-writable（安全缺陷）

**问题**：`unlock` 用 `mode | S_IWUSR | S_IWGRP | S_IWOTH` 解除只读，把 444 解成 **666** —— 门禁自己给同机任意用户开了写后门。而 `lock` 会清除全部三种写位，原始权限就此丢失，解锁时无从还原。

**修复**（`src/pandaone/cli_chunks/part_003.py`）：

| 场景 | 行为 |
|------|------|
| lock | 上锁前把每个文件的原始 mode 记入 `.pandaone/lock_modes.json` |
| unlock（有记录） | 精确还原锁定前的 mode（644 → lock 444 → unlock 644） |
| unlock（无记录，旧版 lock / 手工 chmod） | 只恢复属主写位，绝不补 group/other（默认 644） |
| write 通道临时解锁 | 由 `\|USER\|GROUP\|OTHER` 收窄为只加 `S_IWUSR`，缩短 world-writable 暴露窗口 |

`.pandaone/lock_modes.json` 随 unlock 完成后清理，避免陈旧记录影响后续轮次。

新增两条回归测试：精确还原 644、无记录退化为属主可写。

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