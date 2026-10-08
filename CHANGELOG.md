# Changelog

All notable changes to Pandaone AI Agent will be documented in this file.

## [0.7.15] - 2026-10-04

### Security / 阻断级（必须升级）
- **F-01 L3 隐藏文件旁路修复**：`templates/pre-commit-check.py:95` 用 `_is_protected_path()` 4 规则函数替代 `Path(f).suffix in protected_exts`，修复 `.env` / `.gitignore` / `.htaccess` / `Dockerfile` / `Makefile` 等空后缀文件绕过审计门禁的 Bug #22。同时启用 `exclude_patterns` 字段（之前定义未用）

### Bug Fix（重要）
- **F-02 A1 i18n 裸英文 label**：`part_004.py:116-124` 的 `print(f"file: ...")` / `reason:` / `problem:` / `approach:` / `rejection:` 改为走 `t()` 本地化（`log_field_file/commit/reason/problem/approach/rejection` 6 个新 key）
- **F-03 V2 winreg 实现**：`part_006.py` `_windows_registry_install` 从 V1 SubCommands 模式迁移到 V2 ExtendedSubCommandsKey 模式（Win10/11 推荐）；主菜单 `(Default)=""` + `MUIVerb` + `Icon` + `ExtendedSubCommandsKey="Software\Classes\Pandaone\Shell"`；子菜单统一搬到 EXT_SHELL_KEY 下分离位置；Init 子项 `CommandFlags=0x20` (ECF_SEPARATORBEFORE) 加 Win10/11 modern menu 分隔线
- **F-04 A2 verbose 死变量替换**：`part_004.py:_render_unified_diff()` 新函数，`--verbose` 时显示 difflib.unified_diff 真实完整 diff + 行数统计（v0.7.3 声称的 `--verbose` 完整 diff 此前是纸面功能）
- **F-05 cmd_status 三段补齐**：审计统计段加 APPROVED/REJECTED/UNAUTHORIZED 三分类计数；UNAUTHORIZED > 0 时打印警告（最近 3 条文件路径）
- **F-06 cli.py 入口修复**：loader 第 27 行 `_exec_ns["__name__"]="pandaone.cli"` 后，底部 `if __name__=="__main__":` 块重置 `__name__="__main__"` 让 `python cli.py` 直接调用也工作（之前静默 no-op）
- **F-07 watchdog GBK 编码防护**：`tests/test_watch.py` `subprocess.run` 加 `encoding="utf-8"` + `errors="replace"`，防止 watchdog 在 Windows GBK 编码下输出非 UTF-8 字节（0xcf 等）时 UnicodeDecodeError → check.stdout=None → TypeError

### Governance / 治理
- **F-08 ps1 审计链补齐**：工作树 V1-revert 的 `install_context_menu.ps1` 手动追加 `audit_hotfix2_v0715_001` APPROVED 记录到 `.pandaone/pandaone.jsonl`（补齐审计链 — 选项 A "采纳 hotfix2"）

### Documentation / 文档
- **F-09 4 文档入库**：`docs/HANDOVER.md` / `docs/HANDOVER_CHECKLIST.md` / `接手复盘_HANDOVER审查.md` / `测试验收结论_v0.7.14_实跑验证.md` 全部 `git add` 入库（之前仅 HANDOVER.md 已暂存）
- **F-10 README 真实数字**：徽章与第 365 行从 "342 passed" → "352 passed / 34 failed / 1 skipped"，roadmap 加 v0.7.14-hotfix1 与 v0.7.15 行
- **F-12 HANDOVER 数字统一**：§4.3 与 §12 改用真实数字，移除过期 "342 passed"

### Test Quality / 测试自身修复
- **F-13 `test_readme_loaded.py` ×2**：与 banner isatty 抑制冲突已在 part_006.py 用 `sys.stdout.isatty()` 解决；调整断言期望即可
- **F-14 `test_audit_i18n_ci.py` ×6**：排除中文注释（注释行以 `#` 开头且不含引号不算硬编码）
- **F-15 install_git/log/phase2_e2e 测试自身 bug**：`test_install_git.py` 用 monkeypatch 移除 git；`test_log.py` 检查 stderr 与 stdout；`test_phase2_e2e.py` 修断言变量（检查 watchdog 回调 capture 而非 status 仪表盘输出）

### Migration Notes / 升级注意
- v0.7.14-hotfix1 用户**必须升级**：Win11 22H2+ 子项不可见已修
- v0.7.15 L3 隐藏文件旁路修复**必须升级**：`.env` 等敏感文件未走审计的风险消除
- v0.7.15 V2 winreg 模式**需要重启 explorer（资源管理器）**才能看到菜单变化

### New 方案C 全阶段（hotfix1 之前）
- L5 自指纹 `PANDAX_FP_PATH` env 覆盖 + conftest 指纹备份/恢复 fixture（消除多测试间全局指纹污染 6 个 flake）
- `package-data` 声明补全（ICO/installer 进 wheel）
- `cmd_status` L2 watchdog 段补修
- banner 仅在 TTY 输出（Unix 惯例）
- `part_004`：`--verbose` 统一 diff + i18n 标签接入 `t()`
- hotfix2：右键菜单安装脚本 V2 ExtendedSubCommandsKey → V1 SubCommands（与 winreg 一致）

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