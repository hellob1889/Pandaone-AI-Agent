# -*- coding: utf-8 -*-
"""
i18n_extras.py — Pandaone AI Agent i18n 扩展包 (PR #28)
=====================================================

把 i18n.py 中较新/较少使用的 key 独立出来,便于:
  1. 减小 i18n.py 体积(避免 MCP push 超过 24KB 限制)
  2. 新功能(doctor / git gate)的 key 集中管理

使用方式:
  from pandaone import i18n
  from pandaone.i18n_extras import register_extras
  register_extras(i18n.TRANSLATIONS)

这样 t() 函数无需改动,所有调用点保持向后兼容。

第一性原理:
  - i18n.py 是历史文件,大量双语字符串累积,接近 GitHub Contents API 单次推送上限
  - 拆分会增加 import 依赖,但解耦清晰、PR diff 干净
  - register_extras() 显式注册(非自动),调用方可控

对抗式审查:
  - Q: 为什么不让 i18n.py 自动 import i18n_extras?
    A: 显式 > 隐式。自动 import 会让 i18n.py 行为难追踪。
  - Q: 多模块 TRANSLATIONS 合并会不会冲突?
    A: 后注册覆盖先注册(标准 dict.update 语义),但 PR #28 的 key 都是新加的,
       不与 i18n.py 既有 key 重名。
"""
from __future__ import annotations


EXTRANSLATIONS = {
    "zh-CN": {
        "_doctor_title": "Pandaone Doctor — 系统健康检查",
        "_doctor_layer_header": "[8 层防护状态]",
        "_doctor_all_ok": "[OK] 所有检查通过,防护完整可用",
        "_doctor_action_needed": "[WARN] 有项目需要处理:",
        "_doctor_run_install_git": "  → 运行 `pandaone doctor --install-git` 自动装 git",
        "_doctor_upgrade_python": "  → 请升级 Python 到 {required}",
        "_doctor_path_conflict": "  [WARN] PATH 里还有另一个 pandaone: {path}",
        "_doctor_path_conflict_hint": "        → 它会抢占 `pandaone` 命令，卸载旧版: pip uninstall pandaone",
        "_doctor_git_installed_via": "[OK] git 通过 {channel} 安装成功",
        "_doctor_git_version": "  版本: {ver}",
        "_doctor_restart_shell_hint": "[INFO] 新开终端即可使用 'git' 命令 (PATH 已更新)",
        "_doctor_git_install_failed": "[ERROR] git 自动安装失败",
        "_doctor_manual_hint": "[INFO] 手动安装指引:",
        "_doctor_register_failed": "[WARN] doctor 子命令注册失败: {err}",
        "_gate_git_missing_attempt_install": "[WARN] git 未安装,L2/L3 防护降级。正在尝试自动安装...",
        "_gate_git_installed": "[OK] git {ver} 安装成功 (via {channel})",
        "_gate_git_installed_path": "[INFO] 路径: {path}",
        "_gate_git_restart_shell": "[INFO] 新开终端即可使用 'git' 命令",
        "_gate_git_install_failed": "[ERROR] git 自动安装失败:\n{err}",
        "_gate_git_install_unexpected": "[ERROR] git 安装异常: {err_type}: {err}",
    },
    "en": {
        "_doctor_title": "Pandaone Doctor — System Health Check",
        "_doctor_layer_header": "[8-Layer Defense Status]",
        "_doctor_all_ok": "[OK] All checks passed, defenses fully operational",
        "_doctor_action_needed": "[WARN] Action needed:",
        "_doctor_run_install_git": "  → Run `pandaone doctor --install-git` to auto-install git",
        "_doctor_upgrade_python": "  → Please upgrade Python to {required}",
        "_doctor_path_conflict": "  [WARN] Another pandaone found in PATH: {path}",
        "_doctor_path_conflict_hint": "        → It shadows the `pandaone` command; uninstall the old one: pip uninstall pandaone",
        "_doctor_git_installed_via": "[OK] git installed via {channel}",
        "_doctor_git_version": "  Version: {ver}",
        "_doctor_restart_shell_hint": "[INFO] Open a new terminal to use 'git' (PATH updated)",
        "_doctor_git_install_failed": "[ERROR] git auto-install failed",
        "_doctor_manual_hint": "[INFO] Manual install instructions:",
        "_doctor_register_failed": "[WARN] doctor subcommand registration failed: {err}",
        "_gate_git_missing_attempt_install": "[WARN] git not installed, L2/L3 defenses degraded. Attempting auto-install...",
        "_gate_git_installed": "[OK] git {ver} installed (via {channel})",
        "_gate_git_installed_path": "[INFO] path: {path}",
        "_gate_git_restart_shell": "[INFO] Open a new terminal to use 'git'",
        "_gate_git_install_failed": "[ERROR] git auto-install failed:\n{err}",
        "_gate_git_install_unexpected": "[ERROR] git install exception: {err_type}: {err}",
    },
}


def register_extras(translations_dict: dict) -> None:
    """把 EXTRANSLATIONS 合并到主 translations_dict (PR #28)。"""
    for lang, pack in EXTRANSLATIONS.items():
        if lang not in translations_dict:
            translations_dict[lang] = {}
        for key, value in pack.items():
            translations_dict[lang].setdefault(key, value)
