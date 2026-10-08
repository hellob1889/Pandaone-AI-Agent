# Pandaone AI Agent 优化待办（Optimization Backlog）

> **写于**：2026-10-07
> **写者**：老八（前一个 session 留底 + 本轮对齐）
> **基于**：v0.7.15 release commit `58e140c`（2026-10-04）之后的代码与文档实证
> **用途**：接手者单一 TODO 真相源；按 P0/P1/P2/P3 排序；标注每项状态

---

## 0. 已完成（v0.7.15 release `58e140c` 已落地）

下列项**已不再待办**，列在此避免重复做工：

- [x] 方案 C（测试稳定性）：`part_001` FP 路径隔离 / `part_004` L2 段 + header_line / `part_006` banner TTY 抑制 / `conftest` 全局 FP 文件备份恢复 fixture / 补全 `test_export_subcommand` / `test_watchdog_dedupe`
- [x] hotfix2 采纳：`install_context_menu.ps1` V2 ExtendedSubCommandsKey 回退 V1 SubCommands（与 winreg 实际行为一致），并补 audit 记录
- [x] HANDOVER.md + HANDOVER_CHECKLIST.md 入仓（docs/HANDOVER*.md）
- [x] pyproject package-data / MANIFEST.in 修 Bug #25
- [x] `.gitignore` 锁定本地分析文档 / IDE 状态；`.pandaone/pandaone.jsonl` 审计链更新
- [x] README badge + 测试数文案修正（L67 + L365）→ 实测 `352 passed / 34 failed / 1 skipped`
- [x] 测试验收结论文档归位：`docs/zh/test-reports/acceptance-v0.7.14.md`

---

## P0 — 文档真相源统一（影响接手者信任）

| ID | 项 | 现状 / 证据 | 修复方向 | 验证 |
|---|---|---|---|---|
| P0-1 | `docs/HANDOVER.md` 仍写 `357 passed / 30 failed / 1 skipped`（方案 C 目标值） | 实测 `352 / 34 / 1` | 在 HANDOVER.md §1 / §3 加脚注："本数字为方案 C 目标值；实测见 `docs/zh/test-reports/acceptance-v0.7.14.md`"，不强行覆盖原作者意图 | 三处文档交叉引用 |
| P0-2 | `docs/HANDOVER_CHECKLIST.md` §0/§2.3 也写 `357 / 30` | 同上 | 同 P0-1 处理 | 同上 |
| P0-3 | `CHANGELOG.md.draft` 文件存在但未启用 | v0.7.15 已发，draft 应归档或删除 | 检查内容是否合并到 `CHANGELOG.md`；归档 `docs/archive/CHANGELOG_drafts/` 或删 | diff 确认无信息丢失 |

---

## P1 — 真功能 bug（影响代码正确性）

| ID | 项 | 现状 / 证据 | 修复方向 | 验证 |
|---|---|---|---|---|
| P1-1 | A1 `part_004.py` 裸英文 label | `_print_log` L116/120/121/122/124 直接 `print(f"file: {file_}")`、`reason:`、`problem:`、`approach:`、`rejection:`，未走 `t()` | 把这 5 个字符串包成 `t("file_label")` 等 key，补 i18n dict zh+en | `pytest tests/test_i18n_log_status.py` 5 用例全绿 |
| P1-2 | A2 `--verbose` 死变量 | `_print_log` L92 `verbose = getattr(...)`，循环体 L99-125 从未引用 `verbose`，无 unified diff 渲染 | 加 `if verbose:` 分支，`difflib.unified_diff(old_lines, new_lines, ...)`，逐行 print | `pytest tests/test_v073_audit_diff.py` 3 用例全绿 |
| P1-3 | A3 GBK 编码崩溃 | `pandaone_serve.py` SSE 输出含非 UTF-8 字节时 reader 线程 `UnicodeDecodeError` → `check.stdout = None` → `TypeError` | SSE writer 加 `errors="replace"`；reader 用 `errors="replace"` 解码 | `pytest tests/test_watch.py::test_watch_daemon_writes_pid` |
| P1-4 | A4 `cli.py:27` 入口 no-op | `_exec_ns["__name__"] = "pandaone.cli"` → `python cli.py` 静默空操作，正确入口是 `pandaone_dev.py` | 改为 `_exec_ns["__name__"] = "__main__"` 或增加 if 守卫 | `python cli.py --help` 输出正常 |

---

## P1 — 测试套件稳定性（影响 CI 可信度）

| ID | 项 | 现状 / 证据（B/C 类失败） | 修复方向 | 验证 |
|---|---|---|---|---|
| P1-5 | C 类：fp 文件全局污染 | 全量跑 34 failed / 隔离同 34 node id → 28 failed 6 passed | 已有 fixture 仍不够；改测试用 `PANDAX_FP_PATH` 环境变量隔离（`part_001._resolve_fp_path` 已支持） | 两次全量 + 一次隔离失败数稳定 |
| P1-6 | B1 `test_readme_loaded.py` ×2 | 设计行为（非 TTY 抑制 banner）vs 测试期望打印 Phase 冲突 | 测试改伪 TTY `monkeypatch.setattr(sys, "stdout", ...)` | 重跑该 2 用例 |
| P1-7 | B2 `test_audit_i18n_ci.py` ×6 | 工具把中文注释当硬编码误报 | 工具加 `is_comment = line.lstrip().startswith(("#", "//"))` 跳过 | 重跑 6 用例 |
| P1-8 | B3 `test_install_git_handles_missing_git_gracefully` | 本机/CI 都有 git，走不到缺失分支 | `monkeypatch.setenv("PATH", "")` 移除 git | 重跑 |
| P1-9 | B5 `test_l5_fingerprint_protects_pandaone_itself` | 全量失败、隔离未重现 = 输出捕获问题 | 改用 `capsys.readouterr().err` 或 subprocess | 重跑 |

> 修完 P1-5 ~ P1-9，34 failed 大概率收敛到 4 真失败（A1/A2 + A3/A4 子集）。

---

## P1 — 安全与默认值治理

| ID | 项 | 现状 / 证据 | 修复方向 | 验证 |
|---|---|---|---|---|
| P1-10 | `PANDAX_FP_PASSWORD` 默认 `0000` | 文档默认 + 代码 fallback | 首次 `init` 检测 password=="0000" → 强提示 + 写 audit log | 单测覆盖提示路径 |
| P1-11 | Audit token 存储 | `.pandaone/.audit_token` 明文（uuid4） | 文件权限 0o600 + Windows ACL；中期接 OS keyring | `ls -la` / `icacls` 验证 |
| P1-12 | 安装脚本审计门 | hotfix2 ps1 V1-revert 已补 audit 记录（v0.7.15 commit 落地） | ✅ 已闭环 | `pandaone log` 见 audit |

---

## P2 — 架构与可维护性

| ID | 项 | 现状 / 证据 | 修复方向 | 验证 |
|---|---|---|---|---|
| P2-1 | `pandaone_serve.py` 无 `/healthz` | 仅 SSE bus + 5s heartbeat | 加 `@app.route("/healthz")` 返回 200 + 版本号 | `curl /healthz` |
| P2-2 | SSE 错配处理 | 仅 stale cleanup on 3+ misses | 加客户端断开显式信号 + queue 容量上限 | 压测断开 |
| P2-3 | i18n 字典覆盖 | A1 裸英文 label 说明字典不全 | 跑 `audit_bilingual.py` 报告所有裸英文字符串，逐项补 | 该工具 0 报 |
| P2-4 | 文档真相源统一 | README / HANDOVER / CHECKLIST / 实测报告 / CodeAudit HTML 五处各说 | 设 `docs/STATE.md` 为唯一真相源，其余改引用 | 校验链接 200 |

---

## P2 — DevOps 与发布工程

| ID | 项 | 现状 / 证据 | 修复方向 | 验证 |
|---|---|---|---|---|
| P2-5 | CI matrix 不含 Windows 真机 | `.github/workflows/` 仅 ubuntu-latest | 加 `windows-latest` job 跑 ps1 + `pandaone context-menu install` + 注册表断言 | CI 日志可见 |
| P2-6 | CHANGELOG 自动生成 | 手工写 | 接 `git-cliff` 或 `conventional-changelog` | 跑工具 diff vs 当前 |
| P2-7 | 依赖升级测试覆盖 | `dependabot.yml` 有但升级后无 smoke | `audit.yml` 加"升级依赖后跑 smoke pytest"步骤 | PR 见执行记录 |
| P2-8 | 工作树卫生 | 当前 `M README.md` + `?? docs/zh/test-reports/`（仅 2 项） | 按主题拆 commit：①README 修正 ②docs 归位 | `git status` 干净 |

---

## P3 — 生态冷启动（不写代码但决定生死）

| ID | 项 | 现状 | 建议 |
|---|---|---|---|
| P3-1 | GitHub 0 stars / 4 issues 未回 | 项目卖点 vs 真实生态脱节 | 优先处理 4 个 issue "我能帮你" 回复 + CHANGELOG v0.7.15 计划 |
| P3-2 | 营销文档未发布 | `docs/promotion/` 9 篇草稿就绪 | 选 1-2 篇（dev.to / hashnode / 知乎）先发，标题聚焦"AI agent 改一行也能审计" |
| P3-3 | 演示视频缺失 | `assets/demo*` 仅导出 JSONL | 录 3 分钟：init → write → 篡改 → rollback → log |

---

## 一句话优先级

> **P0 先做**（文档交叉引用统一，< 1 小时）；**P1-1/P1-2/P1-4 三处真功能 bug 先修**（改 50 行内，全套测试从 352/34 → ~352/4）；**P2/P3 留给接手者按节奏推进**。

---

## 附：本 backlog 来源

- v0.7.14-hotfix1 → v0.7.15 期间 18 轮深度阅读（覆盖 201/223 文件）
- `docs/HANDOVER.md` / `docs/HANDOVER_CHECKLIST.md`（v0.7.15 入仓）
- `接手复盘_HANDOVER审查.md`（对抗式审查证据）
- `测试验收结论_v0.7.14_实跑验证.md`（实测 387 → 352/34/1；隔离 28/6）
- `实战验证报告.md` / `实战验证报告_v0.7.14_右键菜单修复.md`（hotfix1 / hotfix2 实战）
- `CodeAudit_项目文档.html`（§11 对抗式审查 + §12 业界对比）

—— 老八 留底
