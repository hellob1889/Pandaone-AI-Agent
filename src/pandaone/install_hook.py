#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_hook.py
===============
安装 Pandaone AI Agent pre-commit hook 到 .git/hooks/

Phase 10: i18n — 所有 print 走 t()，由 pandaone.i18n 提供。

用法:
  python install_hook.py [--root PATH]
  python install_hook.py --uninstall [--root PATH]
"""
import argparse
import shutil
import stat
import sys
from pathlib import Path

from pandaone.i18n import t, init as i18n_init

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "templates" / "pre-commit-hook"
CHECK_SCRIPT = ROOT / "templates" / "pre-commit-check.py"


def install_hook(root: Path) -> int:
    """安装 pre-commit hook"""
    git_hooks = root / ".git" / "hooks"
    if not git_hooks.exists():
        print(t("_hook_no_git", root=root))
        print(t("_hook_no_git_hint", root=root))
        return 1

    if not TEMPLATE.exists():
        print(t("_hook_no_template", template=TEMPLATE))
        return 1

    # Phase 4.6+: 同时复制 pre-commit-check.py 到 .pandaone/（便于 hook 调用）
    pandaone_dir = root / ".pandaone"
    pandaone_dir.mkdir(parents=True, exist_ok=True)
    if CHECK_SCRIPT.exists():
        shutil.copy(CHECK_SCRIPT, pandaone_dir / "pre-commit-check.py")

    hook_path = git_hooks / "pre-commit"
    if hook_path.exists():
        # 备份现有 hook
        backup = git_hooks / "pre-commit.backup"
        shutil.copy(hook_path, backup)
        print(t("_hook_backed_up", backup=backup))

    # Bug #22 fix: 强制 LF 换行（bash 在 *nix 上不支持 CRLF）
    # 背景：Windows git checkout 会把 .gitattributes 没声明 LF 的模板转成 CRLF，
    #       shutil.copy 会原样保留，导致 hook 完全失效（L3 防御被绕过）。
    #
    # [Fix #49] 同时去除 UTF-8 BOM: PowerShell 5.1 Set-Content -Encoding UTF8
    # 会写入 BOM (EF BB BF). 如果 hook 模板被带 BOM 写入, Git 看到
    # `\xef\xbb\xbf#!/bin/sh` 视作非法 shebang, 报 "cannot spawn" 错误.
    content = TEMPLATE.read_bytes()
    content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    hook_path.write_bytes(content)

    # 添加可执行权限（Unix）
    current = hook_path.stat().st_mode
    hook_path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(t("_hook_installed", hook_path=hook_path))
    print(t("_hook_check_copied", path=pandaone_dir / 'pre-commit-check.py'))
    print(t("_hook_content"))
    return 0


def uninstall_hook(root: Path) -> int:
    """卸载 pre-commit hook"""
    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        print(t("_hook_not_installed"))
        return 0

    # 检查是否是我们安装的
    content = hook_path.read_text(encoding="utf-8", errors="ignore")
    if "Pandaone" not in content:
        print(t("_hook_not_ours", hook_path=hook_path))
        return 1

    hook_path.unlink()
    print(t("_hook_uninstalled"))

    # 恢复备份
    backup = root / ".git" / "hooks" / "pre-commit.backup"
    if backup.exists():
        shutil.move(backup, hook_path)
        print(t("_hook_backup_restored", hook_path=hook_path))
    return 0


def main():
    parser = argparse.ArgumentParser(description=t("_hook_desc"))
    parser.add_argument("--root", default=".", help=t("_hook_root_help"))
    parser.add_argument("--uninstall", action="store_true", help=t("_hook_uninstall_help"))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.uninstall:
        return uninstall_hook(root)
    return install_hook(root)


if __name__ == "__main__":
    sys.exit(main())