# -*- coding: utf-8 -*-
"""
i18n.py — Pandaone AI Agent 国际化（i18n）模块
=====================================

设计目标：
  - 零依赖（不引入 gettext / babel）
  - 自动检测 OS 语言（Windows: GetUserDefaultLocaleName；Unix: LANG 环境变量）
  - 支持 --lang 覆盖（CLI 旗标）
  - 用户偏好持久化到 ~/.pandaone/config.json
  - 右键菜单场景：使用双语显示（中文 + 英文）

第一性原理：
  - i18n 不是装饰，是软件工程的纪律
  - 一行 hardcoded 字符串都是潜在的技术债
  - 自动检测能减少 95% 用户的认知负担
  - 显式覆盖满足剩下的 5%（双语环境、远程 SSH）

对抗式审查：
  - 攻击：恶意 .mo 文件注入
    缓解：内置 dict，不读外部翻译文件
  - 攻击：用户修改 ~/.pandaone/config.json
    缓解：仅影响显示语言，不影响安全逻辑
  - 攻击：locale 欺骗
    缓解：严格白名单（zh-CN / en）
"""

import json
import locale
import os
import sys
from pathlib import Path
from typing import Optional


# =========================================================
# 1. 语言包（内置 dict，不读外部文件）
# =========================================================

TRANSLATIONS = {
    "zh-CN": {
        # ============ 元信息 ============
        "_lang_name": "简体中文",
        "_lang_self": "中文",

        # ============ 启动 banner / README ============
        "banner_tagline": "AI Agent 代码审计门禁 · Your code's gentle guardian",
        "readme_header": "Pandaone CLI — README 摘要（每次启动自动加载）",
        "current_phase": "【当前阶段】",
        "completed_steps": "【已完成步骤】",

        # ============ 指纹 ============
        "info_fp_generated": "[INFO] 已生成 pandaone 指纹: {fp}...",
        "ok_fp_updated": "[OK] 指纹已更新: {fp}...",
        "err_fingerprint_mismatch": "[ERROR] pandaone 指纹不匹配！可能被篡改。",
        "_stored": "存储: {stored}...",
        "_current": "当前: {current}...",
        "_check_package_data": "请确认 pip 安装时包含 installer/ 目录（package_data）",
        "_interp_unavailable": "解释器不可用: {interp}",
        "err_fingerprint_hint": "如需合法更新: pandaone --update-fingerprint 0000",
        "err_password_wrong": "[ERROR] 密码错误，指纹未更新",

        # ============ init ============
        "ok_initialized": "[OK] 已初始化: {path}",
        "init_config": "  config: {path}",
        "init_audit": "  audit:  {path}",
        "init_binary": "  binary_snapshots: {path}",
        "info_snapshot_count": "  [snapshot] 已记录 {n} 个二进制文件的 SHA256",
        "info_no_binary": "  (无二进制文件)",
        "info_existing_dir": "[INFO] {pandaone_dir} 已存在，将复用",
        "info_existing_dir_force": "[INFO] {pandaone_dir} 已存在，使用 --force 重新生成",

        # ============ lock / unlock ============
        "ok_locked_n": "[OK] 锁定 {n} 个文件（受保护扩展名: {exts}）",
        "ok_unlocked_n": "[OK] 解锁 {n} 个文件（受保护扩展名: {exts}）",
        "warn_lock_failed": "[WARN] {file}: {err}",

        # ============ status ============
        "status_header": "Pandaone AI Agent 状态仪表盘 — {root}",
        "status_l1": "[L1 文件锁]",
        "status_l1_no_py": "[L1 文件锁]  无受保护文件",
        "status_total": "  总受保护文件: {n}",
        "status_locked_unlocked": "  已锁定: {n}  |  未锁定: {m}",
        "status_extensions": "  扩展名: {exts}",
        "status_warn_unlock": "  [WARN] 有 {n} 个受保护文件未锁定，建议运行 pandaone lock",
        "status_l2": "[L2 watchdog 看门狗]",
        "status_watch_on": "  状态: 运行中  (PID: {pid})",
        "status_watch_off": "  状态: 未运行（建议: pandaone watch --daemon）",
        "status_l5": "[L5 自指纹]",
        "status_fp_ok": "  状态: 完整 OK ({fp}...)",
        "status_git_section": "[Git 集成]",
        "status_gitignore_ok": "  .gitignore 已正确排除 .pandaone/ + desktop.ini",
        "status_gitignore_missing": "  [WARN] .gitignore 缺失 {miss} → 重跑 pandaone init 自动修复",
        "status_git_not_repo": "  非 git 仓库,跳过检查",
        "gitignore_added": "[OK] .gitignore 已更新,新增: {names}",
        "gitignore_already_ok": "[OK] .gitignore 已正确包含 Pandaone 条目,无需改动",
        "gitignore_skip": "[SKIP] {root} 不是 git 仓库,跳过 .gitignore 维护",
        "gitignore_write_err": "[ERR] 写 .gitignore 失败: {err_type}: {err}",
        "status_fp_mismatch": "  状态: [WARN] 不匹配！存储={stored} 当前={current}",
        "status_fp_uninit": "  状态: 未生成（首次运行后会自动生成）",
        "status_audit_stats": "[审计统计]",
        "status_total_records": "  总记录: {n}",
        "status_recent_3": "[最近 3 条]",
        "status_binary_section": "[Phase 5 二进制快照]",
        "status_binary_tracked": "  跟踪文件数: {n}",
        "status_binary_ok": "  所有跟踪文件 SHA256 匹配 OK",
        "status_binary_fail": "  [FAIL] {n} 个文件 SHA256 不匹配",
        "_status_binary_disabled": "未启用二进制保护(--no-binary 或 init 在 Phase 5 之前)",

        # Bug #17 fix: 审计统计状态计数用本地化标签
        # v0.7.15: 未授权标签附带英文状态码，便于 CI/报告交叉引用
        "status_count_approved": "  - 已批准: {n}",
        "status_count_rejected": "  - 已拒绝: {n}",
        "status_count_unauthorized": "  - 未授权 (UNAUTHORIZED): {n}",

        # Bug #14 fix: log 输出中硬编码的 id=/file= 标签本地化
        "log_record_header": "[{ts}] {status}  {id_label}={rid}  {file_label}={file_}",
        # v0.7.15: log 面板字段标签完整本地化
        "log_label_file": "文件",
        "log_label_commit": "提交",
        "log_label_reason": "原因",
        "log_label_problem": "问题",
        "log_label_approach": "方法",
        "log_label_rejection": "拒绝原因",
        "log_label_lines": "变更行",
        "log_label_diff": "变更内容 (Diff):",
        "log_not_initialized": "[ERROR] 未初始化：未找到 {path}，请先运行: pandaone init --root <目录>",
        "status_not_initialized": "[ERROR] {root} 未初始化 Pandaone，请先运行: pandaone init --root {root}",

        # ============ write ============
        "err_write_root_not_init": "[ERROR] {root} 未初始化 Pandaone，请先运行: pandaone init --root <path>",
        "err_write_rejected": '[ERROR] {{"status":"REJECTED","reason":"{root} 未初始化 Pandaone"}}',
        "err_file_ext": "{file} 不是受保护扩展名",
        "err_file_notfound": "文件不存在: {file}",
        "err_file_read": "文件已锁定，请先 unlock 或 write",
        "ok_written": "[OK] 已写入: {file}",
        "write_reject_target_not_exist": "目标文件不存在: {file}",
        "write_reject_ext_not_allowed": "只允许修改文本({text_exts})或二进制({binary_exts})保护范围内的文件",
        "write_reject_binary_no_patch": "二进制文件不支持 --old/--new 模式，请用 --content-base64 或 --from-file",
        "write_reject_binary_must_use_content": "二进制文件必须用 --from-file 或 --content-base64",
        "write_reject_binary_old_new": "二进制文件不支持 --old/--new 模式，请用 --content-base64 或 --from-file",
        "write_reject_old_not_found": "--old 字符串不存在",
        "write_reject_readonly_need_force": "文件 {file} 已锁定 (L1 只读)，请加 --force-write 标志或先运行 `pandaone unlock`",
        "write_reject_must_specify": "必须指定 --old/--new 或 --content",
        "write_reject_from_file_not_found": "--from-file 源文件不存在: {path}",
        "write_reject_b64_decode": "--content-base64 解码失败: {err}",
        "write_reject_problem_short": "problem 长度 < {n}",
        "write_reject_problem_required": "请提供 --problem",
        "write_reject_approach_required": "请提供 --approach",
        "write_reject_reason_required": "请提供 --reason",
        # Bug #39 fix: cmd_write 4 处硬编码中文改为 i18n
        "write_reject_empty_reason": "reason 字段为空",
        "write_reject_empty_problem": "problem 字段为空",
        "write_reject_empty_approach": "approach 字段为空",
        # Bug #29 fix: init 检测到已有 config 时的提示
        "warn_init_config_exists": "[WARN] 检测到已存在 config.json（{path}），将保留你的自定义设置",
        # Bug #10b fix: 写后恢复 chmod 失败（文件被另一进程占用等极端情况）
        "warn_chmod_restore_failed": "[WARN] 写后恢复文件锁定失败 {file}: {err} — 文件可能仍可写",
        "write_reject_chmod_restore_failed": "无法恢复文件锁定状态: {err}",
        # Bug #11 fix: 移除 cli.py 硬编码中文
        "err_readme_missing": "[ERROR] README.md 未找到，CLI 无法运行",
        # Bug #12 fix: 移除 cli.py 硬编码英文
        "warn_icon_toggle_failed": "[WARN] icon toggle failed (lock/unlock still ok): {err}",
        # Bug #10 fix: 移除 cli.py 硬编码中文
        "write_reject_reason_short": "reason 长度不足（< {n} 宽度单位，含 CJK 字符按 2 计）",
        "warn_init_config_corrupted": "[WARN] config.json 已损坏：{err}，将重新生成默认配置",
        # Bug #16 fix: zh-CN 同步 en 的 err_config_corrupted / err_snapshot_corrupted
        "err_config_corrupted": "[ERROR] config.json 损坏: {err} → 请运行 `pandaone init --force-reset` 修复",
        "err_snapshot_corrupted": "[ERROR] binary_snapshots.json 损坏: {err}",
        "warn_gitignore_failed": "[WARN] .gitignore 维护失败(不影响 init): {err}",
        # Bug #28 (Solution A): lock auto-init info
        "info_lock_auto_init": "[INFO] 首次使用检测到: 自动为 {root} 运行 init",
        "write_warn_git_add": "[WARN] git add 失败: {err}",
        "write_warn_no_git": "[WARN] git 未安装，跳过 git commit（审计记录已保存）",
        # Bug #18 fix: zh-CN 同步 en 的 warn_subprocess_timeout
        "warn_subprocess_timeout": "[WARN] {cmd} 超时 ({timeout}s) — 可能目标进程挂死，已跳过该步骤",

        # ============ serve (Web 仪表盘) ============
        "serve_ok_url": "[OK] Pandaone 仪表盘启动: {url}",
        "serve_info_root": "  项目根: {root}",
        "serve_info_watch": "  监视文件: {path}",
        "serve_info_watchdog": "  watchdog: {state}",
        "_serve_wd_on": "启用",
        "_serve_wd_off": "未安装或审计文件缺失",
        "serve_info_stop_hint": "  按 Ctrl+C 停止",
        "serve_info_shutdown": "[INFO] 收到 Ctrl+C,正在关闭...",

        # ============ log ============
        "log_header": "审计历史（共 {n} 条）",
        "log_no_records": "[INFO] 无审计记录",
        "log_no_records_file": "[INFO] 该文件无审计记录",
        "log_no_records_session": "[INFO] 该 session 无审计记录",
        "_log_no_commit": "(无)",
        "_status_example": "  示例（前 {n} 个）:",
        "_git_version": "  版本: {ver}",
        "_git_path_tip": "[INFO] 将 {path} 加入 PATH 后即可使用 'git' 命令",
        "_git_ready": "[INFO] Pandaone 可正常使用 git 自动 commit 功能。",
        "log_export_ok": "[OK] 已导出 {n} 条记录到 {path}",
        "log_export_ok_format": "[OK] 已导出 {n} 条记录 ({fmt}) 到 {path}",
        "log_export_err_format": "[ERROR] --output 需要和 --format 一起使用",
        "log_export_err_output": "[ERROR] --format 需要和 --output 一起使用",
        "log_export_no_records": "[INFO] 无匹配记录，未生成导出文件",
        "_log_no_init": "{root} 未初始化 Pandaone 项目或无审计记录",

        # ============ 独立 export 子命令 + log path deprecation ============
        "export_ok": "[OK] 已导出 {n} 条记录为 {fmt}: {path}",
        "export_err_no_format": "[ERROR] 缺少 --format (示例: pandaone export --format html --output report.html)",
        "export_err_no_output": "[ERROR] 缺少 --output (示例: pandaone export --format html --output report.html)",
        "warn_log_export_use_export_subcommand": "[WARN] pandaone log --format/--output 已弃用,推荐: pandaone export --format <fmt> --output <path>",
        "_export_unsupported": '[ERROR] 不支持的格式: "{fmt}"',
        "_export_supported": "[INFO] 支持的格式: {supported}",

        # Bug #26 fix: export 报告标签本地化（html/md/text）
        "export_title": "Pandaone AI Agent 审计报告",
        "export_summary": "记录数: {n}",
        "export_exported_at": "导出时间: {ts}",
        "export_col_time": "时间",
        "export_col_status": "状态",
        "export_col_id": "ID",
        "export_col_file": "文件",
        "export_col_reason": "原因",
        "log_field_file": "文件",
        "log_field_action": "操作",
        "log_field_time": "时间",
        "log_field_session": "session",
        "log_field_reason": "原因",
        "log_field_problem": "问题",
        "log_field_approach": "方法",
        "log_field_size": "大小",
        "log_field_id": "ID",
        "log_action_written": "写入",
        "log_action_rejected": "拒绝",
        "log_action_unauthorized": "非授权",
        "log_field_commit": "commit",
        "log_attempted": "  尝试: reason={reason}, problem={problem}, approach={approach}",
        "log_unauth_detection": "  检测: {detection}",
        "log_unauth_action": "  操作: {action}",

        # ============ v0.7.3: 面板 UI ============
        "panel_file": "文件",
        "panel_commit": "commit",
        "panel_lines": "行数",
        "panel_reason": "原因",
        "panel_problem": "问题",
        "panel_approach": "方法",
        "panel_attempted": "尝试",
        "panel_detection": "检测",
        "panel_action": "操作",
        "panel_diff": "差异",
        "panel_force_write": "⚠ 强制写入已启用（绕过审计门禁）",
        "panel_verbose_hint": "（使用 --verbose 查看完整 diff）",
        "panel_agent_by": "by",
        "panel_no_commit": "(无 commit)",
        # ============ status (v0.7.3 agent stats) ============
        "status_by_agent": "🤖 按 agent 统计活动 / Activity by Agent",
        "status_writes": "次写入 / writes",

        # ============ install-context / uninstall-context ============
        "err_script_not_found": "[ERROR] 脚本不存在: {path}",
        "err_unsupported_platform": "[ERROR] 不支持的平台: {platform}",
        "err_installer_timeout": "[ERROR] installer 超时 (60s 未返回)。可能是 PowerShell 挂死或注册表 provider 阻塞",
        "warn_installer_stderr": "[WARN] installer stderr (exit={code}):",
        "info_os_detected": "[INFO] 检测到平台: {os}",
        "info_running": "[INFO] 执行: {cmd}",


        # ============ v0.7.9: Windows 右键菜单 winreg 集成 (PR #35) ============
        "ctx_subprocess_timeout": "[TIMEOUT] {script} 超过 60 秒",
        "ctx_interp_not_found": "[NOT FOUND] 解释器 {interp} 不在 PATH",
        "ctx_banner_uninstall": "===============================================\nPandaone Windows 右键菜单卸载程序\n===============================================",
        "ctx_banner_install": "===============================================\nPandaone Windows 右键菜单安装程序\n===============================================",
        "ctx_pandaone_ok": "[OK] pandaone: {exe}",
        "ctx_step1": "[1/3] 已清理旧条目",
        "ctx_step2": "[2/3] 已注册右键菜单 (任意文件 / 目录 / 空白处)",
        "ctx_step3": "[3/3] 已注册 4 个子命令 (Init / Lock / Status / Unlock)",
        "ctx_install_done": "[OK] 安装完成！",
        "ctx_test_label": "测试方法：",
        "ctx_test_step1": "  1. 在任意目录空白处点击右键",
        "ctx_test_step2": "  2. 看到「Pandaone 审计工具」级联菜单",
        "ctx_test_step3": "  3. 展开后看到：Init / Lock / Status / Unlock",
        "ctx_uninstall_label": "卸载：",
        "ctx_install_restart_hint": "如果右键菜单没立刻出现，请重启资源管理器：",
        "ctx_uninstall_done": "[OK] 已卸载右键菜单",
        "ctx_uninstall_restart_hint": "如果右键菜单依然残留，请重启资源管理器：",
        "ctx_exe_not_found": "[WARN] 未找到 pandaone 可执行文件！",
        "ctx_install_hint": "请先安装 Pandaone：",
        "ctx_already_installed": "[INFO] Pandaone 右键菜单已存在。使用 --force 重新安装。",
        "ctx_perm_error": "[ERROR] 注册表权限不足: {err}",
        "ctx_perm_hint": "提示: HKCU 通常不需要管理员权限, 如仍报错请检查用户配置",

        # ============ install-git ============
        "git_probe_check": "[INFO] 探测 git ...",
        "git_probe_found": "[OK] git 已安装: {path}",
        "git_probe_missing": "[INFO] 未找到 git",
        "git_not_installed": "[NOT FOUND] git 未安装",
        "git_install_hint": "请通过以下方式之一安装 git：",
        "git_install_hint_url": "  1. 官方下载: https://git-scm.com/download/win",
        "git_install_hint_winget": "  2. winget install Git.Git",
        "git_install_hint_choco": "  3. choco install git",
        "git_install_hint_1": "  1. https://git-scm.com/download/win 下载安装",
        "git_install_hint_2": "  2. winget install Git.Git",
        "git_install_hint_3": "  3. choco install git",
        "git_downloading": "[INFO] 正在下载: {url}",
        "git_target": "[INFO] 目标: {target}",
        "git_size_hint": "[INFO] 文件大小约 50MB，请稍候...",
        "git_download_failed": "[ERROR] 下载失败: {err}",
        "git_extracting": "[INFO] 解压中...",
        "git_extract_failed": "[ERROR] 解压失败: {err}",
        "git_installed": "[OK] git 已安装: {path}",
        "git_path_hint": "[INFO] 将 {path} 加入 PATH",
        "git_powershell_hint": '[INFO] PowerShell: $env:PATH = "{path};" + $env:PATH',
        "git_install_failed": "[ERROR] git 安装失败（未找到 git.exe）",

        # ============ install-hook ============
        "hook_found": "[OK] 已找到 watchdog: {path}",
        "hook_not_found": "[ERROR] 找不到 watchdog: {path}",
        "hook_import_err": "[ERROR] 无法导入 pandaone_guard: {err}",
        "hook_installed": "[OK] pre-commit hook 已安装: {path}",
        "hook_uninstalled": "[OK] pre-commit hook 已卸载",
        "hook_install_running": "  已安装: hook 会在每次 git commit 前自动运行",
        "_hook_no_git": "[ERROR] {root} 不是 git 仓库（.git/hooks 不存在）",
        "_hook_no_git_hint": "[INFO] 请先运行: cd {root} && git init",
        "_hook_no_template": "[ERROR] 模板文件不存在: {template}",
        "_hook_backed_up": "[INFO] 已备份现有 hook: {backup}",
        "_hook_installed": "[OK] pre-commit hook 已安装: {hook_path}",
        "_hook_check_copied": "[OK] pre-commit-check.py 已复制: {path}",
        "_hook_content": "[INFO] 内容: Pandaone L3 防御（强化版：每个 staged 文件必须有 APPROVED 记录）",
        "_hook_not_installed": "[INFO] hook 未安装",
        "_hook_not_ours": "[WARN] {hook_path} 不是 Pandaone 安装的，未删除",
        "_hook_uninstalled": "[OK] pre-commit hook 已卸载",
        "_hook_backup_restored": "[OK] 已恢复备份: {hook_path}",
        "_hook_desc": "安装/卸载 Pandaone pre-commit hook",
        "_hook_root_help": "项目根目录",
        "_hook_uninstall_help": "卸载 hook",
        "_guard_git_checkout_fail": "[WARN] git checkout 失败: {err}",
        "_guard_auto_lock": "[AUTO-LOCK] {name}",
        "_guard_auto_lock_fail": "[WARN] 自动锁定失败 {file}: {err}",
        "_guard_started": "[INFO] watchdog 启动，监控: {root}",
        "_guard_pid": "[INFO] PID: {pid}  PID 文件: {path}",
        "_guard_daemon_hint": "[INFO] 后台运行中... Ctrl+C 停止",
        "_guard_git_found": "[INFO] git 探测成功: {path}",
        "_guard_signaled": "[INFO] 收到终止信号，停止 watchdog...",
        "_guard_no_git": "[WARN] 未找到 git。watchdog 回滚功能可能不可用。",

        # ============ watch ============
        "watch_daemon_started": "[OK] watchdog 已在后台启动",
        "watch_daemon_pid": "  PID: {pid}",
        "watch_daemon_log": "  日志: {path}",
        "watch_stop_win": "  停止: taskkill /F /PID {pid}  (Windows)",
        "watch_stop_unix": "  停止: kill {pid}  (Unix/macOS)",
        "_watch_no_init": "{root} 未初始化 Pandaone 项目",

        # ============ ci ============
        "ci_header": "Pandaone CI 验证 — {root}",
        "ci_baseline_empty": "基线: 无（首次提交，无历史可比）",
        "ci_baseline": "基线: {base}  HEAD: {head}",
        "ci_changed_n": "变更文件: {n} 个",
        "ci_ext_stats": "受保护扩展: 文本 {t} 种 / 二进制 {b} 种",
        "ci_pass_empty": "[OK] PASS — 仓库为空（无变更可审计）",
        "ci_baseline_no_changes": "基线: 当前 tree（首次 commit，无 HEAD~1）— 无变更",
        "ci_reject_no_baseline": "[FAIL] 无法解析 baseline ({base})。首次 commit 请显式指定 --base 或先创建 main 分支",
        "ci_pass_all": "[OK] PASS — 所有变更均有审计记录",
        "ci_pass_json": '{{"status":"PASS","violations":0,"changed":{n}}}',
        "ci_pass_empty_json": '{{"status":"PASS","violations":0,"changed":0,"note":"empty repo"}}',
        "ci_fail_n": "[FAIL] 检测到 {n} 个未审计的变更：",
        "ci_fail_file": "          原因: {reason}",
        "ci_fix_hint": "修复方法：",
        "ci_fix_cmd": "  对每个违规文件执行 pandaone write（带完整 reason/problem/approach）",
        "ci_fail_json": '{{"status":"FAIL","violations":{n},"changed":{m}}}',
        "ci_reject_no_init": '[FAIL] {{"status":"REJECTED","reason":"{root} 未初始化 Pandaone"}}',
        "ci_reject_no_git_repo": '[FAIL] {{"status":"REJECTED","reason":"{root} 不是 git 仓库"}}',
        "ci_reject_no_git": '[FAIL] {{"status":"REJECTED","reason":"git 未安装（找不到 {git}）"}}',
        "ci_reject_diff_fail": '[FAIL] {{"status":"REJECTED","reason":"git diff 失败: {err}"}}',

        # ============ 通用 ============
        "err_unknown_cmd": "[ERROR] 未知子命令: {cmd}",
        "err_format_without_format": "[ERROR] --output 需要和 --format 一起使用",
        "err_format_without_output": "[ERROR] --format 需要和 --output 一起使用",
        # 同步 en 的 version key
        "version": "pandaone v{ver}",
        # ============ desktop_icon (Bug #20 fix) ============
        "desktop_icon_skip": "[SKIP] Platform {platform} is not Windows, skipping icon {action}",
        "desktop_icon_ok": "[OK] Folder icon switched → {state}",
        "desktop_icon_err": "[ERR] Icon {action} failed: {err_type}: {err}",
        "desktop_icon_cleaned": "[OK] Cleaned: {items}",
        "desktop_icon_clean_none": "[OK] No cleanup needed (icon never enabled)",
        "err_no_input": "[Pandaone] 无输入路径，退出。",
        "err_no_target": "[Pandaone] 无可操作目标。",
        "err_user_cancel": "[Pandaone] 用户取消。",
        "_none": "无",

        # ============ 右键菜单（双语静态） ============
        "menu_root": "Pandaone 审计工具 / Audit Tools",
        "menu_init": "初始化此目录 (Init)",
        "menu_lock": "锁定文件 (Lock)",
        "menu_unlock": "解锁文件 (Unlock)",
        "menu_status": "查看状态 (Status)",

        # ============ macOS workflow 弹窗文本 ============
        "macos_choose_prompt": "选择要执行的操作 (Choose action) — 目标 (Target): {path}",
        "macos_no_selection": "没有选中任何文件或文件夹 (No file or folder selected)",
    },

    "en": {
        # ============ Meta ============
        "_lang_name": "English",
        "_lang_self": "English",

        # ============ Startup banner / README ============
        "banner_tagline": "AI Agent Code Audit Gateway · Your code's gentle guardian",
        "readme_header": "Pandaone CLI — README summary (auto-loaded on every startup)",
        "current_phase": "[Current Phase]",
        "completed_steps": "[Completed Steps]",

        # ============ Fingerprint ============
        "info_fp_generated": "[INFO] Generated pandaone fingerprint: {fp}...",
        "ok_fp_updated": "[OK] Fingerprint updated: {fp}...",
        "err_fingerprint_mismatch": "[ERROR] pandaone fingerprint mismatch! Possible tampering.",
        "_stored": "Stored: {stored}...",
        "_current": "Current: {current}...",
        "_check_package_data": "Please ensure pip install includes installer/ (package_data)",
        "_interp_unavailable": "Interpreter unavailable: {interp}",
        "err_fingerprint_hint": "To update legally: pandaone --update-fingerprint 0000",
        "err_password_wrong": "[ERROR] Wrong password, fingerprint not updated",

        # ============ init ============
        "ok_initialized": "[OK] Initialized: {path}",
        # Bug #28 (Solution A): lock auto-init info
        "info_lock_auto_init": "[INFO] First use detected: auto-running init for {root}",
        "init_config": "  config: {path}",
        "init_audit": "  audit:  {path}",
        "init_binary": "  binary_snapshots: {path}",
        "info_snapshot_count": "  [snapshot] Recorded {n} binary file SHA256",
        "info_no_binary": "  (no binary files)",
        "info_existing_dir": "[INFO] {pandaone_dir} already exists, will reuse",
        "info_existing_dir_force": "[INFO] {pandaone_dir} already exists, use --force to regenerate",

        # ============ lock / unlock ============
        "ok_locked_n": "[OK] Locked {n} files (protected extensions: {exts})",
        "ok_unlocked_n": "[OK] Unlocked {n} files (protected extensions: {exts})",
        "warn_lock_failed": "[WARN] {file}: {err}",

        # ============ status ============
        "status_header": "Pandaone AI Agent Status Dashboard — {root}",
        "status_l1": "[L1 File Lock]",
        "status_l1_no_py": "[L1 File Lock]  No protected files",
        "status_total": "  Total protected files: {n}",
        "status_locked_unlocked": "  Locked: {n}  |  Unlocked: {m}",
        "status_extensions": "  Extensions: {exts}",
        "status_warn_unlock": "  [WARN] {n} protected files unlocked, suggest running: pandaone lock",
        "status_l2": "[L2 watchdog]",
        "status_watch_on": "  Status: running  (PID: {pid})",
        "status_watch_off": "  Status: not running (suggest: pandaone watch --daemon)",
        "status_l5": "[L5 Self-fingerprint]",
        "status_fp_ok": "  Status: OK ({fp}...)",
        "status_git_section": "[Git Integration]",
        "status_gitignore_ok": "  .gitignore correctly excludes .pandaone/ + desktop.ini",
        "status_gitignore_missing": "  [WARN] .gitignore missing {miss} → re-run pandaone init to fix",
        "status_git_not_repo": "  Not a git repo, skipping check",
        "gitignore_added": "[OK] .gitignore updated, added: {names}",
        "gitignore_already_ok": "[OK] .gitignore already contains Pandaone entries, no change needed",
        "gitignore_skip": "[SKIP] {root} is not a git repo, skipping .gitignore maintenance",
        "gitignore_write_err": "[ERR] Failed to write .gitignore: {err_type}: {err}",
        "warn_gitignore_failed": "[WARN] .gitignore maintenance failed (does not affect init): {err}",
        "status_fp_mismatch": "  Status: [WARN] mismatch! Stored={stored} Current={current}",
        "status_fp_uninit": "  Status: not generated (will be generated on first run)",
        "status_audit_stats": "[Audit Stats]",
        "status_total_records": "  Total records: {n}",
        "status_recent_3": "[Last 3 records]",
        "status_binary_section": "[Phase 5 Binary Snapshots]",
        "status_binary_tracked": "  Tracked files: {n}",
        "status_binary_ok": "  All tracked files SHA256 OK",
        "status_binary_fail": "  [FAIL] {n} files SHA256 mismatch",
        "_status_binary_disabled": "Binary protection not enabled (used --no-binary or init was before Phase 5)",

        # Bug #17 fix: 审计统计状态计数用本地化标签（不再是裸 APPROVED/REJECTED/UNAUTHORIZED）
        "status_count_approved": "  - Approved: {n}",
        "status_count_rejected": "  - Rejected: {n}",
        "status_count_unauthorized": "  - Unauthorized: {n}",

        # Bug #14 fix: log 输出中硬编码的 id=/file= 标签本地化
        "log_record_header": "[{ts}] {status}  {id_label}={rid}  {file_label}={file_}",
        # v0.7.15: log panel field labels (en)
        "log_label_file": "File",
        "log_label_commit": "Commit",
        "log_label_reason": "Reason",
        "log_label_problem": "Problem",
        "log_label_approach": "Approach",
        "log_label_rejection": "Rejection",
        "log_label_lines": "Lines",
        "log_label_diff": "Diff:",
        "log_not_initialized": "[ERROR] Not initialized: audit log not found at {path}. Run: pandaone init --root <dir>",
        "status_not_initialized": "[ERROR] {root} not initialized as Pandaone project, please run: pandaone init --root {root}",

        # ============ write ============
        "err_write_root_not_init": "[ERROR] {root} not initialized as Pandaone project, please run: pandaone init --root <path>",
        "err_write_rejected": '[ERROR] {{"status":"REJECTED","reason":"{root} not initialized as Pandaone project"}}',
        # Bug #39 fix: cmd_write 4 hardcoded Chinese strings → i18n
        "write_reject_empty_reason": "reason field is empty",
        "write_reject_empty_problem": "problem field is empty",
        "write_reject_empty_approach": "approach field is empty",
        "write_reject_binary_old_new": "Binary file does not support --old/--new mode, use --content-base64 or --from-file instead",
        # Bug #29 fix: init existing config warning
        "warn_init_config_exists": "[WARN] Detected existing config.json ({path}), preserving your customizations",
        # Bug #11 fix: replace hardcoded Chinese with i18n
        "err_readme_missing": "[ERROR] README.md not found, CLI cannot run",
        # Bug #12 fix: replace hardcoded English with i18n
        "warn_icon_toggle_failed": "[WARN] icon toggle failed (lock/unlock still ok): {err}",
        # Bug #10 fix: replace hardcoded Chinese with i18n
        "write_reject_reason_short": "reason length too short (< {n} width units, CJK counts as 2)",
        # Bug #10b fix: chmod restore failure during write
        "warn_chmod_restore_failed": "[WARN] Failed to restore file lock after write {file}: {err} — file may still be writable",
        "write_reject_chmod_restore_failed": "Cannot restore file lock state: {err}",
        "warn_init_config_corrupted": "[WARN] config.json is corrupted: {err}, regenerating default config",
        # Bug #16 fix: friendly error for corrupted JSON configs
        "err_config_corrupted": "[ERROR] config.json corrupted: {err} → please run `pandaone init --force-reset` to fix",
        "err_snapshot_corrupted": "[ERROR] binary_snapshots.json corrupted: {err}",
        "err_file_ext": "{file} is not a protected extension",
        "err_file_notfound": "File not found: {file}",
        "err_file_read": "File locked, please unlock or write first",
        "ok_written": "[OK] Written: {file}",
        "write_reject_target_not_exist": "Target file does not exist: {file}",
        "write_reject_ext_not_allowed": "Only files with text ({text_exts}) or binary ({binary_exts}) extensions are allowed",
        "write_reject_binary_no_patch": "Binary files don't support --old/--new mode, use --content-base64 or --from-file",
        "write_reject_binary_must_use_content": "Binary files must use --from-file or --content-base64",
        "write_reject_old_not_found": "--old string not found",
        "write_reject_readonly_need_force": "File {file} is locked (L1 read-only). Use --force-write or run `pandaone unlock` first",
        "write_reject_must_specify": "Must specify --old/--new or --content",
        "write_reject_from_file_not_found": "--from-file source file not found: {path}",
        "write_reject_b64_decode": "--content-base64 decode failed: {err}",
        "write_reject_problem_short": "problem length < {n}",
        "write_reject_problem_required": "Please provide --problem",
        "write_reject_approach_required": "Please provide --approach",
        "write_reject_reason_required": "Please provide --reason",
        "write_warn_git_add": "[WARN] git add failed: {err}",
        "write_warn_no_git": "[WARN] git not installed, skipping git commit (audit record saved)",
        # Bug #18 fix: subprocess.run(timeout=...) friendly timeout message
        "warn_subprocess_timeout": "[WARN] {cmd} timed out ({timeout}s) — target may be hung, skipping this step",

        # ============ serve (Web dashboard) ============
        "serve_ok_url": "[OK] Pandaone dashboard started: {url}",
        "serve_info_root": "  Project root: {root}",
        "serve_info_watch": "  Watching file: {path}",
        "serve_info_watchdog": "  watchdog: {state}",
        "_serve_wd_on": "enabled",
        "_serve_wd_off": "not installed or audit file missing",
        "serve_info_stop_hint": "  Press Ctrl+C to stop",
        "serve_info_shutdown": "[INFO] Received Ctrl+C, shutting down...",

        # ============ log ============
        "log_header": "Audit history ({n} records total)",
        "log_no_records": "[INFO] No audit records",
        "log_no_records_file": "[INFO] No audit records for this file",
        "log_no_records_session": "[INFO] No audit records for this session",
        "_log_no_commit": "(none)",
        "_status_example": "  Examples (first {n}):",
        "_git_version": "  Version: {ver}",
        "_git_path_tip": "[INFO] Add {path} to PATH to use the 'git' command",
        "_git_ready": "[INFO] Pandaone can now use git auto-commit.",
        "log_export_ok": "[OK] Exported {n} records to {path}",
        "log_export_ok_format": "[OK] Exported {n} records ({fmt}) to {path}",
        "log_export_err_format": "[ERROR] --output requires --format",
        "log_export_err_output": "[ERROR] --format requires --output",
        "log_export_no_records": "[INFO] No matching records, output file not generated",

        # Bug #25 fix: standalone export subcommand + deprecation warning for log path
        "export_ok": "[OK] Exported {n} records as {fmt}: {path}",
        "export_err_no_format": "[ERROR] Missing --format (try: pandaone export --format html --output report.html)",
        "export_err_no_output": "[ERROR] Missing --output (try: pandaone export --format html --output report.html)",
        "warn_log_export_use_export_subcommand": "[WARN] pandaone log --format/--output is deprecated, prefer: pandaone export --format <fmt> --output <path>",

        # Bug #26 fix: export report labels i18n (html/md/text)
        "export_title": "Pandaone AI Agent Audit Report",
        "export_summary": "Records: {n}",
        "export_exported_at": "Exported at: {ts}",
        "export_col_time": "Time",
        "export_col_status": "Status",
        "export_col_id": "ID",
        "export_col_file": "File",
        "export_col_reason": "Reason",
        "_export_unsupported": '[ERROR] Unsupported format: "{fmt}"',
        "_export_supported": "[INFO] Supported: {supported}",
        "_log_no_init": "{root} not initialized as Pandaone project or no audit records",
        "log_field_file": "File",
        "log_field_action": "Action",
        "log_field_time": "Time",
        "log_field_session": "Session",
        "log_field_reason": "Reason",
        "log_field_problem": "Problem",
        "log_field_approach": "Approach",
        "log_field_size": "Size",
        "log_action_written": "write",
        "log_action_rejected": "reject",
        "log_action_unauthorized": "unauthorized",
        "log_field_id": "ID",
        "log_field_commit": "commit",
        "log_attempted": "  Attempted: reason={reason}, problem={problem}, approach={approach}",
        "log_unauth_detection": "  Detection: {detection}",
        "log_unauth_action": "  Action: {action}",

        # ============ v0.7.3: panel UI ============
        "panel_file": "File",
        "panel_commit": "commit",
        "panel_lines": "Lines",
        "panel_reason": "Reason",
        "panel_problem": "Problem",
        "panel_approach": "Approach",
        "panel_attempted": "Attempted",
        "panel_detection": "Detection",
        "panel_action": "Action",
        "panel_diff": "Diff",
        "panel_force_write": "⚠ Force write enabled (audit gateway bypassed)",
        "panel_verbose_hint": "(use --verbose for full diff)",
        "panel_agent_by": "by",
        "panel_no_commit": "(no commit)",
        # ============ status (v0.7.3 agent stats) ============
        "status_by_agent": "🤖 Activity by Agent",
        "status_writes": "writes",

        # ============ install-context / uninstall-context ============
        "err_script_not_found": "[ERROR] Script not found: {path}",
        "err_unsupported_platform": "[ERROR] Unsupported platform: {platform}",
        "err_installer_timeout": "[ERROR] installer timeout (60s). Possible PowerShell hang or registry provider block",
        "warn_installer_stderr": "[WARN] installer stderr (exit={code}):",
        "info_os_detected": "[INFO] Detected platform: {os}",
        "info_running": "[INFO] Running: {cmd}",


        # ============ v0.7.9: Windows Right-Click Menu winreg Integration (PR #35) ============
        "ctx_subprocess_timeout": "[TIMEOUT] {script} timed out after 60 seconds",
        "ctx_interp_not_found": "[NOT FOUND] Interpreter {interp} not in PATH",
        "ctx_banner_uninstall": "===============================================\nPandaone Windows Right-Click Menu Uninstaller\n===============================================",
        "ctx_banner_install": "===============================================\nPandaone Windows Right-Click Menu Installer\n===============================================",
        "ctx_pandaone_ok": "[OK] pandaone: {exe}",
        "ctx_step1": "[1/3] Cleaned up old entries",
        "ctx_step2": "[2/3] Registered right-click menu (any file / directory / background)",
        "ctx_step3": "[3/3] Registered 4 sub-commands (Init / Lock / Status / Unlock)",
        "ctx_install_done": "[OK] Installation complete!",
        "ctx_test_label": "How to test:",
        "ctx_test_step1": "  1. Right-click anywhere in any directory",
        "ctx_test_step2": "  2. Look for the 'Pandaone Audit Tools' cascade menu",
        "ctx_test_step3": "  3. Expand to see: Init / Lock / Status / Unlock",
        "ctx_uninstall_label": "Uninstall:",
        "ctx_install_restart_hint": "If the right-click menu doesn't appear immediately, restart Explorer:",
        "ctx_uninstall_done": "[OK] Right-click menu uninstalled",
        "ctx_uninstall_restart_hint": "If the right-click menu persists, restart Explorer:",
        "ctx_exe_not_found": "[WARN] pandaone executable not found!",
        "ctx_install_hint": "Please install Pandaone first:",
        "ctx_already_installed": "[INFO] Pandaone right-click menu already exists. Use --force to reinstall.",
        "ctx_perm_error": "[ERROR] Insufficient registry permissions: {err}",
        "ctx_perm_hint": "Hint: HKCU usually doesn't require admin. If it fails, check user profile.",

        # ============ install-git ============
        "git_probe_found": "[OK] git installed: {path}",
        "git_probe_check": "[INFO] Probing git ...",
        "git_probe_missing": "[INFO] git not found",
        "git_not_installed": "[NOT FOUND] git not installed",
        "git_install_hint": "Please install git via one of:",
        "git_install_hint_url": "  1. Official download: https://git-scm.com/download/win",
        "git_install_hint_winget": "  2. winget install Git.Git",
        "git_install_hint_choco": "  3. choco install git",
        "git_install_hint_1": "  1. Download from https://git-scm.com/download/win",
        "git_install_hint_2": "  2. winget install Git.Git",
        "git_install_hint_3": "  3. choco install git",
        "git_downloading": "[INFO] Downloading: {url}",
        "git_target": "[INFO] Target: {target}",
        "git_size_hint": "[INFO] File ~50MB, please wait...",
        "git_download_failed": "[ERROR] Download failed: {err}",
        "git_extracting": "[INFO] Extracting...",
        "git_extract_failed": "[ERROR] Extract failed: {err}",
        "git_installed": "[OK] git installed: {path}",
        "git_path_hint": "[INFO] Add {path} to PATH",
        "git_powershell_hint": '[INFO] PowerShell: $env:PATH = "{path};" + $env:PATH',
        "git_install_failed": "[ERROR] git install failed (git.exe not found)",

        # ============ install-hook ============
        "hook_found": "[OK] watchdog found: {path}",
        "hook_not_found": "[ERROR] watchdog not found: {path}",
        "hook_import_err": "[ERROR] Cannot import pandaone_guard: {err}",
        "hook_installed": "[OK] pre-commit hook installed: {path}",
        "hook_uninstalled": "[OK] pre-commit hook uninstalled",
        "hook_install_running": "  Installed: hook will run automatically before each git commit",
        "_hook_no_git": "[ERROR] {root} is not a git repository (.git/hooks not found)",
        "_hook_no_git_hint": "[INFO] Please run first: cd {root} && git init",
        "_hook_no_template": "[ERROR] Template file not found: {template}",
        "_hook_backed_up": "[INFO] Backed up existing hook: {backup}",
        "_hook_installed": "[OK] pre-commit hook installed: {hook_path}",
        "_hook_check_copied": "[OK] pre-commit-check.py copied: {path}",
        "_hook_content": "[INFO] Content: Pandaone L3 defense (strict version: every staged file must have APPROVED record)",
        "_hook_not_installed": "[INFO] Hook not installed",
        "_hook_not_ours": "[WARN] {hook_path} was not installed by Pandaone, not deleted",
        "_hook_uninstalled": "[OK] pre-commit hook uninstalled",
        "_hook_backup_restored": "[OK] Restored backup: {hook_path}",
        "_hook_desc": "Install/uninstall Pandaone pre-commit hook",
        "_hook_root_help": "Project root directory",
        "_hook_uninstall_help": "Uninstall hook",
        "_guard_git_checkout_fail": "[WARN] git checkout failed: {err}",
        "_guard_auto_lock": "[AUTO-LOCK] {name}",
        "_guard_auto_lock_fail": "[WARN] Auto-lock failed {file}: {err}",
        "_guard_started": "[INFO] watchdog started, monitoring: {root}",
        "_guard_pid": "[INFO] PID: {pid}  PID file: {path}",
        "_guard_daemon_hint": "[INFO] Running in background... Ctrl+C to stop",
        "_guard_git_found": "[INFO] git found at: {path}",
        "_guard_signaled": "[INFO] Termination signal received, stopping watchdog...",
        "_guard_no_git": "[WARN] git not found. watchdog rollback may be unavailable.",

        # ============ watch ============
        "watch_daemon_started": "[OK] watchdog started in background",
        "watch_daemon_pid": "  PID: {pid}",
        "watch_daemon_log": "  Log: {path}",
        "watch_stop_win": "  Stop: taskkill /F /PID {pid}  (Windows)",
        "watch_stop_unix": "  Stop: kill {pid}  (Unix/macOS)",
        "_watch_no_init": "{root} not initialized as Pandaone project",

        # ============ ci ============
        "ci_header": "Pandaone CI Verification — {root}",
        "ci_baseline_empty": "Baseline: none (first commit, no history to compare)",
        "ci_baseline": "Baseline: {base}  HEAD: {head}",
        "ci_changed_n": "Changed files: {n}",
        "ci_ext_stats": "Protected extensions: {t} text / {b} binary",
        "ci_pass_empty": "[OK] PASS — repository is empty (no changes to audit)",
        "ci_baseline_no_changes": "Baseline: current tree (first commit, no HEAD~1) — no changes",
        "ci_reject_no_baseline": "[FAIL] cannot resolve baseline ({base}). First commit needs --base or pre-existing main branch",
        "ci_pass_all": "[OK] PASS — all changes have audit records",
        "ci_pass_json": '{{"status":"PASS","violations":0,"changed":{n}}}',
        "ci_pass_empty_json": '{{"status":"PASS","violations":0,"changed":0,"note":"empty repo"}}',
        "ci_fail_n": "[FAIL] Detected {n} unaudited change(s):",
        "ci_fail_file": "          Reason: {reason}",
        "ci_fix_hint": "Fix:",
        "ci_fix_cmd": "  For each violation, run pandaone write (with complete reason/problem/approach)",
        "ci_fail_json": '{{"status":"FAIL","violations":{n},"changed":{m}}}',
        "ci_reject_no_init": '[FAIL] {{"status":"REJECTED","reason":"{root} not initialized"}}',
        "ci_reject_no_git_repo": '[FAIL] {{"status":"REJECTED","reason":"{root} is not a git repository"}}',
        "ci_reject_no_git": '[FAIL] {{"status":"REJECTED","reason":"git not installed (cannot find {git})"}}',
        "ci_reject_diff_fail": '[FAIL] {{"status":"REJECTED","reason":"git diff failed: {err}"}}',

        # ============ General ============
        "err_unknown_cmd": "[ERROR] Unknown command: {cmd}",
        "err_format_without_format": "[ERROR] --output requires --format",
        "err_format_without_output": "[ERROR] --format requires --output",
        "version": "pandaone v{ver}",
        "err_no_input": "[Pandaone] No input path, exiting.",
        # ============ desktop_icon (Bug #20 fix) ============
        "desktop_icon_skip": "[SKIP] Platform {platform} is not Windows, skipping icon {action}",
        "desktop_icon_ok": "[OK] Folder icon switched → {state}",
        "desktop_icon_err": "[ERR] Icon {action} failed: {err_type}: {err}",
        "desktop_icon_cleaned": "[OK] Cleaned: {items}",
        "desktop_icon_clean_none": "[OK] No cleanup needed (icon never enabled)",
        "err_no_target": "[Pandaone] No target.",
        "err_user_cancel": "[Pandaone] User cancelled.",
        "_none": "none",

        # ============ Right-click menu (bilingual static) ============
        "menu_root": "Pandaone 审计工具 / Audit Tools",
        "menu_init": "初始化此目录 (Init)",
        "menu_lock": "锁定文件 (Lock)",
        "menu_unlock": "解锁文件 (Unlock)",
        "menu_status": "查看状态 (Status)",

        # ============ macOS workflow dialog text ============
        "macos_choose_prompt": "选择要执行的操作 (Choose action) — 目标 (Target): {path}",
        "macos_no_selection": "没有选中任何文件或文件夹 (No file or folder selected)",
    },
}


# =========================================================
# 2. 全局当前语言（线程不安全的简化版 — 单线程 CLI 无问题）
# =========================================================

_CURRENT_LANG = "zh-CN"  # 默认


def _persist_path() -> Path:
    """动态获取持久化路径（每次都读 HOME，尊重 monkeypatch）"""
    return Path.home() / ".pandaone" / "config.json"


# =========================================================
# 3. 检测 OS 语言
# =========================================================

def _detect_os_language() -> str:
    """
    自动检测用户语言。
    返回 "zh-CN" 或 "en"。
    优先级：LANG 环境变量 > locale 模块 > 兜底英文。
    """
    # 1. 环境变量 LC_ALL > LANG > LANGUAGE（Unix 标准优先级）
    lang_env = (
        os.environ.get("LC_ALL", "") or
        os.environ.get("LANG", "") or
        os.environ.get("LANGUAGE", "")
    )
    if lang_env:
        lang_lower = lang_env.lower()
        if lang_lower.startswith("zh"):
            return "zh-CN"
        if lang_lower.startswith("en"):
            return "en"

    # 2. locale 模块（Windows + Unix）
    try:
        loc = locale.getdefaultlocale()[0]  # e.g. "zh_CN", "en_US"
        if loc:
            if loc.lower().startswith("zh"):
                return "zh-CN"
            if loc.lower().startswith("en"):
                return "en"
    except Exception:
        pass

    # 3. Windows 特定：GetUserDefaultLocaleName
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            kernel32 = ctypes.windll.kernel32
            kernel32.GetUserDefaultLocaleName(buf, 85)
            win_locale = buf.value  # e.g. "zh-CN", "en-US"
            if win_locale.lower().startswith("zh"):
                return "zh-CN"
            if win_locale.lower().startswith("en"):
                return "en"
        except Exception:
            pass

    # 兜底
    return "en"  # 不是中文就默认英文（国际化软件惯例）


# =========================================================
# 4. 加载/保存用户偏好
# =========================================================

def _load_user_pref() -> Optional[str]:
    """从 ~/.pandaone/config.json 读取 lang 偏好"""
    try:
        pp = _persist_path()
        if pp.exists():
            data = json.loads(pp.read_text(encoding="utf-8"))
            lang = data.get("lang")
            if lang in TRANSLATIONS:
                return lang
    except Exception:
        pass
    return None


def _save_user_pref(lang: str) -> None:
    """保存 lang 偏好到 ~/.pandaone/config.json"""
    try:
        pp = _persist_path()
        pp.parent.mkdir(parents=True, exist_ok=True)
        # 不覆盖其他键
        data = {}
        if pp.exists():
            try:
                data = json.loads(pp.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["lang"] = lang
        pp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass  # 静默失败 — 偏好持久化是 nice-to-have


# =========================================================
# 5. 初始化 / 获取当前语言
# =========================================================

def init(lang: Optional[str] = None) -> str:
    """
    初始化语言环境。
    优先级：传入参数 > PANDAX_LANG 环境变量 > 用户偏好 > OS 自动检测。

    返回最终生效的语言代码。

    PANDAX_LANG 环境变量主要用于测试场景（pytest conftest 强制锁定 zh-CN），
    避免测试断言硬编码中文字符串时受用户/系统设置影响。
    """
    global _CURRENT_LANG

    if lang and lang in TRANSLATIONS:
        # 1. 显式指定（CLI --lang）
        _CURRENT_LANG = lang
        _save_user_pref(lang)
        return lang

    # 2. PANDAX_LANG 环境变量（测试/CI 场景）
    import os as _os
    env_lang = _os.environ.get("PANDAX_LANG")
    if env_lang and env_lang in TRANSLATIONS:
        _CURRENT_LANG = env_lang
        return env_lang

    # 3. 用户偏好
    pref = _load_user_pref()
    if pref:
        _CURRENT_LANG = pref
        return pref

    # 4. OS 自动检测
    detected = _detect_os_language()
    _CURRENT_LANG = detected
    return detected


def get_lang() -> str:
    """获取当前语言代码"""
    return _CURRENT_LANG


def set_lang(lang: str) -> None:
    """运行时切换语言"""
    global _CURRENT_LANG
    if lang in TRANSLATIONS:
        _CURRENT_LANG = lang
        _save_user_pref(lang)


# =========================================================
# 6. 翻译函数 t()（类似 gettext 但极简）
# =========================================================

def t(key: str, **kwargs) -> str:
    """
    翻译字符串。
    用法：t("ok_locked_n", n=3, exts=".py,.json")
    """
    pack = TRANSLATIONS.get(_CURRENT_LANG, TRANSLATIONS["en"])
    template = pack.get(key) or TRANSLATIONS["en"].get(key) or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template  # 占位符缺失时原样返回


def t_bilingual(key_zh: str, key_en: str, sep: str = " · ") -> str:
    """
    双语显示（右键菜单场景）。
    用法：t_bilingual("menu_lock", "menu_lock_en")
    返回：中文 · 英文
    """
    return f"{t(key_zh)}{sep}{t(key_en)}"


# =========================================================
# 7. 列出所有支持的语言
# =========================================================

def available_languages() -> list:
    """返回 [(code, native_name), ...]"""
    return [(code, pack["_lang_name"]) for code, pack in TRANSLATIONS.items()]


# =========================================================
# 8. 翻译覆盖率统计（开发用）
# =========================================================

def coverage_report() -> dict:
    """
    返回各语言包覆盖统计：{lang: {total, present, missing_pct}}
    """
    base_keys = set(TRANSLATIONS["zh-CN"].keys())
    report = {}
    for lang, pack in TRANSLATIONS.items():
        lang_keys = set(pack.keys())
        present = lang_keys & base_keys
        missing = base_keys - lang_keys
        report[lang] = {
            "total": len(base_keys),
            "present": len(present),
            "missing": sorted(missing),
            "missing_pct": round(100 * len(missing) / max(len(base_keys), 1), 1),
        }
    return report