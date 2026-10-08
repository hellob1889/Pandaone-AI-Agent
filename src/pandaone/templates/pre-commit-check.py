#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pre-commit-check.py
===================
Pandaone AI Agent pre-commit hook 的 Python 校验逻辑（Phase 4.6+）。

由 .git/hooks/pre-commit 调用（shell 脚本只负责传参）。

Phase 10: i18n — 所有 print 走 t()，由 pandaone.i18n 提供。
注意：pre-commit 脚本运行时可能没有安装 pandaone，因此有 fallback 字符串。

第一性原理：
  shell 在处理多行变量和复杂条件时容易出错。把所有审计逻辑放 Python：
  - 读 config.json 获取保护扩展名
  - 读 git staged 文件
  - 对每个 staged 受保护文件查审计日志的 APPROVED 记录
  - 缺记录就 exit 1（拒绝 commit）
"""
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path


def _is_protected_path(path_str: str, protected_exts: list, exclude_patterns: list = None) -> bool:
    """判断 staged 文件是否需要审计记录（受保护）。

    规则优先级（从高到低）：
      1. exclude_patterns 匹配 → 不保护（允许绕过审计）
      2. 文件名以 '.' 开头（隐藏文件） → 强制保护（无视扩展名）
      3. 后缀名匹配 protected_exts → 保护
      4. 其他 → 不保护

    Args:
        path_str: 相对路径字符串（已用 / 归一化）
        protected_exts: 受保护扩展名列表，如 [".py", ".json"]
        exclude_patterns: 排除模式列表（fnmatch glob），如 ["_tmp_*.py", "*.pyc"]

    Returns:
        True if 文件需要审计记录（拒绝直接 commit）；False if 文件可放行

    Bug 修复背景：
      - Bug #22: pre-commit-check.py:95 用 Path(f).suffix 过滤，.env / .gitignore 等
        隐藏文件 suffix 为空 → 绕过审计门禁（v0.7.14 发现，v0.7.15 修）
      - Bug #22+: exclude_patterns 字段在 config.json 定义但未应用（v0.7.14 发现，v0.7.15 修）
    """
    p = Path(path_str)

    # Rule 1: exclude_patterns 优先（允许临时文件 / 编译产物绕过）
    if exclude_patterns:
        for pattern in exclude_patterns:
            # 兼容 glob（fnmatch）与全名（exact）
            if fnmatch.fnmatch(p.name, pattern) or p.name == pattern:
                return False

    # Rule 2: 隐藏文件强制保护（无论扩展名）
    # .env / .gitignore / .pandaone/* 等通常含敏感配置，必须审计
    if p.name.startswith('.'):
        return True

    # Rule 3: 扩展名匹配
    if p.suffix in protected_exts:
        return True

    # Rule 4: 默认不保护
    return False


def t_safe(key: str, **kwargs) -> str:
    """
    安全翻译函数（fallback）。
    如果 pandaone 未安装，fallback 到内置中文字符串。
    """
    try:
        from pandaone.i18n import t as _t
        i18n_lang = os.environ.get("PANDAX_LANG", "")
        if i18n_lang in ("zh-CN", "en"):
            from pandaone import i18n
            i18n.set_lang(i18n_lang)
        return _t(key, **kwargs)
    except ImportError:
        # Fallback：内置中文（保证 hook 仍然可工作）
        fallback_zh = {
            "_hook_no_config": "[Pandaone] 拒绝提交: .pandaone/config.json 不存在",
            "_hook_init_hint": "请先运行: pandaone init",
            "_hook_cfg_parse_err": "[Pandaone] config.json 解析失败: {e}",
            "_hook_git_diff_err": "[Pandaone] git diff 失败: {stderr}",
            "_hook_git_call_err": "[Pandaone] git 调用失败: {e}",
            "_hook_no_audit": "[Pandaone] 拒绝提交: 审计日志不存在",
            "_hook_should_exist": "应存在: {path}",
            "_hook_audit_read_err": "[Pandaone] 读取审计日志失败: {e}",
            "_hook_reject_no_audit": "[Pandaone] 拒绝提交: 以下文件没有 APPROVED 审计记录",
            "_hook_staged_files": "被 staged 的受保护文件:",
            "_hook_use_pandaone_write": "请使用 pandaone write 命令代替直接 git commit:",
            "_hook_write_example": '  pandaone write --file <FILE> --reason "..." --problem "..." --approach "..."',
            "_hook_bypass_hint": "如果确实要绕过审计 (不推荐), 使用: git commit --no-verify",
        }
        return fallback_zh.get(key, key).format(**kwargs)


def main():
    repo_root = Path.cwd()
    config_path = repo_root / ".pandaone" / "config.json"
    audit_path = repo_root / ".pandaone" / "pandaone.jsonl"

    if not config_path.exists():
        print("")
        print("================================================================")
        print(t_safe("_hook_no_config"))
        print("================================================================")
        print(t_safe("_hook_init_hint"))
        sys.exit(1)

    # 1. 读取受保护扩展名
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        protected_exts = cfg.get("protected_extensions", [".py"])
    except Exception as e:
        print(t_safe("_hook_cfg_parse_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 2. 读取 git staged 文件
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            print(t_safe("_hook_git_diff_err", stderr=r.stderr), file=sys.stderr)
            sys.exit(1)
        staged = [f.strip().replace("\\", "/") for f in r.stdout.splitlines() if f.strip()]
    except Exception as e:
        print(t_safe("_hook_git_call_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 3. 过滤出受保护路径（修复 Bug #22 隐藏文件绕过 + Bug #22+ exclude_patterns 未应用）
    exclude_patterns = cfg.get("exclude_patterns", [])
    protected_staged = [
        f for f in staged
        if _is_protected_path(f, protected_exts, exclude_patterns)
    ]

    if not protected_staged:
        # 没有受保护文件被 staged, 放行
        sys.exit(0)

    # 4. 读取审计日志的 APPROVED 记录
    if not audit_path.exists():
        print("")
        print("================================================================")
        print(t_safe("_hook_no_audit"))
        print("================================================================")
        print(t_safe("_hook_should_exist", path=audit_path))
        sys.exit(1)

    approved_files = set()
    try:
        with audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "APPROVED":
                        f_norm = str(rec.get("file", "")).replace("\\", "/")
                        approved_files.add(f_norm)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(t_safe("_hook_audit_read_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 5. 找出未被审计的文件
    missing = []
    for f in protected_staged:
        f_norm = f.replace("\\", "/")
        if f_norm not in approved_files and f not in approved_files:
            missing.append(f)

    if missing:
        print("")
        print("================================================================")
        print(t_safe("_hook_reject_no_audit"))
        print("================================================================")
        print("")
        print(t_safe("_hook_staged_files"))
        for m in missing:
            print(f"  {m}")
        print("")
        print(t_safe("_hook_use_pandaone_write"))
        print(t_safe("_hook_write_example"))
        print("")
        print(t_safe("_hook_bypass_hint"))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()