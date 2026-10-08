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
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_git_exe():
    """
    Resolve `git` executable absolute path.

    Git for Windows hook sub-shell PATH is nearly empty, so the bare
    command name "git" may not be found. Walk common install locations
    + PATH lookup + GIT_EXECUTABLE env hint. Used by pre-commit-check.py
    to avoid `FileNotFoundError` even when hook PATH is broken.
    """
    candidates = []
    env_hint = os.environ.get("GIT_EXECUTABLE")
    if env_hint:
        candidates.append(env_hint)
    which = shutil.which("git")
    if which:
        candidates.append(which)
    # Common Windows install locations
    for d in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\mingw64\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\mingw64\bin\git.exe",
        r"D:\软件\Git\cmd\git.exe",
        r"D:\软件\Git\mingw64\bin\git.exe",
    ):
        if os.path.exists(d):
            candidates.append(d)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "git"  # 最后兜底：留给 PATH 正常的环境（Linux/macOS）


def t_safe(key: str, **kwargs) -> str:
    """
    安全翻译函数。

    正常路径: 调 pandaone.i18n.t() (含 zh-CN + en 双语, 见 i18n.py 的
    _hook_no_config / _hook_init_hint / ... 等 13 个 key).

    兜底路径: pandaone 未安装 (hook sub-shell PATH 受限时) 用一段极简英文
    占位, 避免再硬编码中文字符串触发 i18n Hardcoded Chinese Audit.
    """
    try:
        from pandaone.i18n import t as _t
        i18n_lang = os.environ.get("PANDAX_LANG", "")
        if i18n_lang in ("zh-CN", "en"):
            from pandaone import i18n
            i18n.set_lang(i18n_lang)
        return _t(key, **kwargs)
    except ImportError:
        # Last-resort fallback: 短英文占位, 真实文案集中在 i18n.py
        return _FALLBACK_EN.get(key, key).format(**kwargs)


# Last-resort English fallback (used only when pandaone.i18n cannot be imported).
# All real strings live in src/pandaone/i18n.py under _hook_* keys.
_FALLBACK_EN = {
    "_hook_no_config": "[Pandaone] Reject commit: .pandaone/config.json not found",
    "_hook_init_hint": "Please run: pandaone init",
    "_hook_cfg_parse_err": "[Pandaone] config.json parse error: {e}",
    "_hook_git_diff_err": "[Pandaone] git diff failed: {stderr}",
    "_hook_git_call_err": "[Pandaone] git call failed: {e}",
    "_hook_no_audit": "[Pandaone] Reject commit: audit log not found",
    "_hook_should_exist": "Expected at: {path}",
    "_hook_audit_read_err": "[Pandaone] read audit log failed: {e}",
    "_hook_reject_no_audit": "[Pandaone] Reject commit: the following files have no APPROVED audit record",
    "_hook_staged_files": "Staged protected files:",
    "_hook_use_pandaone_write": "Please use pandaone write instead of git commit:",
    "_hook_write_example": '  pandaone write --file <FILE> --reason "..." --problem "..." --approach "..."',
    "_hook_bypass_hint": "To bypass audit (not recommended), use: git commit --no-verify",
}


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
            [_resolve_git_exe(), "diff", "--cached", "--name-only", "--diff-filter=AM"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            print(t_safe("_hook_git_diff_err", stderr=r.stderr), file=sys.stderr)
            sys.exit(1)
        staged = [f.strip().replace("\\", "/") for f in r.stdout.splitlines() if f.strip()]
    except Exception as e:
        print(t_safe("_hook_git_call_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 3. 过滤出受保护扩展名
    protected_staged = [f for f in staged if Path(f).suffix in protected_exts]

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