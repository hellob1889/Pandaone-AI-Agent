# 测试验收结论 —— Pandaone AI Agent v0.7.14 实跑验证

> 撰写：老八（第一性原理 + 对抗式审查，全程实跑 + 源码复核，非推断）
> 日期：2026-10-04
> 验证对象：`D:\绿联云办公\项目 水龙头项目 CodeAudit_项目文档`（PyPI `pandaone-guard`，import `pandaone`）

---

## 0. 一句话结论

README 第 365 行与徽章宣称「**342 passed**」**不成立**。实跑结果：

```
387 collected → 352 passed / 34 failed / 1 skipped
```

- passed 数本身就是过时的（实为 352，非 342）；
- 更严重的是 **34 个失败被完全隐瞒**，README 给人「全绿」的错觉。
- 隔离复跑同一批 34 个失败用例 → **28 failed / 6 passed**，证明其中 6 个是**全局状态污染导致的偶发失败** → 套件不可重复。

---

## 1. 验证方法（可复现）

1. 读完全部 `docs/zh/`（8 篇）+ 全部 `tests/`（43 个 `.py` 测试文件）。
2. 两次实跑（Python 3.11 系统解释器，PYTHONPATH=src）：
   - 全量：`pytest tests/ -q --timeout=90 -p no:cacheprovider` → **352 passed, 34 failed, 1 skipped**（419s）
   - 隔离：仅跑 34 个失败 node id → **28 failed, 6 passed**（44s）
3. 对 8 个指纹测试 + i18n log/status + verbose diff 做**源码级核实**：
   - `src/pandaone/cli_chunks/part_001.py`（指纹路径、参数）
   - `src/pandaone/cli_chunks/part_002.py`（`compute_fingerprint` / `check_fingerprint`）
   - `src/pandaone/cli_chunks/part_004.py`（`_print_log` / `cmd_log` / `cmd_status`）
   - `src/pandaone/cli_chunks/part_006.py`（`main()` 调用流、非 TTY 抑制逻辑）

---

## 2. 34 个失败分类与根因（带代码证据）

### A. 真实代码缺陷（应修）

| ID | 失败用例 | 根因（代码证据） | 严重度 |
|----|----------|------------------|--------|
| A1 | `test_i18n_log_status.py` ×5 | `part_004.py:116/120/121/122/124` 直接 `print(f"file: {file_}")`、`reason:`、`problem:`、`approach:`、`rejection:`，**未走 `t()`**。期望本地化 `文件:`/`File:`/`原因:`/`已批准:` 等。 | **P1** |
| A2 | `test_v073_audit_diff.py` ×3 | `_print_log` 在 `part_004.py:92` 读取 `verbose = getattr(_print_log,"_verbose",False)`，但循环体（99–125 行）**从未使用 `verbose`，无任何 diff 渲染逻辑**。v0.7.3 宣称的 `--verbose` 完整 unified diff **未实现**。 | **P1** |
| A3 | `test_watch.py::test_watch_daemon_writes_pid` | 看门狗输出含非 UTF-8 字节（GBK `0xcf`）→ reader 线程 `UnicodeDecodeError` → `check.stdout` 为 `None` → `assert str(pid) in check.stdout` 抛 `TypeError`。Windows 编码未防护。 | P2 |
| A4 | `test_bug_48_trust_default.py::test_without_trust_default_still_fails` | 未初始化目录时 `cmd_write` 先报「未初始化」拦截（`part_004.py:138` 同款逻辑），指纹校验（缺 `--trust-default` 告警）根本没机会触发；测试预期「指纹不匹配」落空。 | P2（测试前提错） |
| A5 | `test_e2e.py::test_full_workflow_e2e` | 拒绝记录文案为 `reason 长度不足（< 5 宽度单位…）`，不含 `attempted`/`尝试`；断言过严或文案漂移。 | P2 |
| A6 | `test_phase2_e2e.py::test_full_defense_chain` | `[UNAUTHORIZED] on_modified: main.py` 实际打印在 watchdog 回调的 capture 中，断言却检查 `out`（status 仪表盘输出），**抓错变量**。 | P2（测试抓错输出） |

### B. 测试 / 工具自身缺陷（非代码缺陷，但让 suite 红）

| ID | 失败用例 | 说明 |
|----|----------|------|
| B1 | `test_readme_loaded.py` ×2 | `part_006.py:309` **有意**在非 TTY（被 pytest capture）时抑制 banner + README 摘要；测试却期望无参启动时打印 `Phase`/`已完成`/`[x]`。设计行为 vs 测试预期冲突。 |
| B2 | `test_audit_i18n_ci.py` ×6 | i18n 审计工具把 `part_004.py:114` 的**中文注释**（`# Bug fix (v0.7.15): 之前构造了 header_line 但从未打印`）判为「1 处硬编码」报 FAIL。注释误报，工具过严。 |
| B3 | `test_install_git.py::test_install_git_handles_missing_git_gracefully` | 本机与 CI 均有 git（conftest 注入 PATH），走不到「缺失 graceful」分支，输出 46 字符 < 50 阈值。测试非密封。 |
| B4 | `test_log.py::test_log_empty_when_no_init` | 未初始化时 `rc=1` 但 stdout 为空（错误可能走 stderr），测试只查 stdout。 |
| B5 | `test_phase2_e2e.py::test_l5_fingerprint_protects_pandaone_itself` | 与 A6 同类输出捕获问题（全量跑失败，隔离未重现）。 |

### C. 偶发 / 全局状态污染（suite 非确定性，最该警惕）

- 全量跑 **34 failed**；隔离重跑同 34 个 node id → **28 failed, 6 passed**。
- 这 6 个（含 `test_fingerprint_file_exists_after_run` / `test_fingerprint_matches_pandaone_py` 等）在隔离时通过、全量时失败 → 根因是共享全局 `~/.pandaone_fp.txt`（指纹文件）被其他测试误删/篡改后未还原。
- 含义：**测试套件不可重复、存在顺序依赖**，CI 偶绿偶红风险高。

---

## 3. 对先前结论的修正（已在 workspace memory 校正）

- `HANDOVER.md` 宣称的 L5「指纹不匹配 CRITICAL」、hotfix2=SHChangeNotify、修复命令 `pandaone_fingerprint_update` —— 均不成立：
  - L5 仅对 `cli.py` 算 SHA256（`compute_fingerprint` 经 exec 后 `__file__` 已还原为 cli.py 路径）；
  - 真实指纹更新入口是 `--update-fingerprint`（默认密码 `0000`），非 HANDOVER 写的子命令；
  - 右键菜单实路径是 `part_006.py` 的 `winreg`，`.ps1` 是 Windows 死代码。
- 本次进一步确认：**指纹相关 8 个测试大量失败**，说明 L5 自指纹逻辑（尤其与 `--trust-default`、`PANDAX_FP_PASSWORD` 环境变量、全局文件状态的交互）目前**不可靠**，必须重点回归。

---

## 4. 验收判定

- ❌ **不满足「全绿」验收标准**。
- README 第 365 行 + 徽章（第 67 行）应更正为真实数字并标注已知失败。
- 严重度分布：**P0 = 0**（无阻断性崩溃）；**P1 = A1/A2**（i18n 标签 + verbose diff 未实现，影响核心审计可读性）；**P2 = A3–A6、B 类、C 类**（稳定性 / 测试质量）。

---

## 5. 建议下一步（按项目规范：建议，非代执行）

1. **修 A1/A2 真缺陷**：`part_004.py` 打印接 `t()`；`_print_log` 接 `verbose` 渲染 unified diff。
2. **修 C 类稳定性**：指纹测试改用 `PANDAX_FP_PATH` 环境变量隔离（代码已支持，见 `part_001.py:57` `_resolve_fp_path`），消除 `~/.pandaone_fp.txt` 全局污染。
3. **修 B 类测试**：`readme_loaded` 用伪 TTY 或调整断言；`audit_i18n_ci` 排除注释；`install_git` 用 monkeypatch 移除 git；`log`/`phase2` 检查正确输出流。
4. **更正文档**：README 第 365 行 + 徽章改为真实 `352 passed / 34 failed / 1 skipped`，附已知 issue 列表。
5. **登记事项**：将 34 个失败登记为事项，分配研发，关联 v0.7.14 / v0.7.15，关联原 PR/需求。

---

### 附：复跑命令

```bash
cd /d/绿联云办公/项目\ 水龙头项目\ CodeAudit_项目文档
PY="C:/Users/Administrator/AppData/Local/Programs/Python/Python311/python.exe"
"$PY" -m pytest tests/ -q -p no:cacheprovider --timeout=90
# 实测：352 passed, 34 failed, 1 skipped（387 collected）
```
