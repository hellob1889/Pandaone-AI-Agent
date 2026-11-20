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
# v0.7.35: 内容绑定判定模块（hook 与 pandaone ci 共用）。
# hook 模板是独立副本, 不能 import 主包 -> 把同一份模块一起拷到 .pandaone/
BINDING_MODULE = ROOT / "audit_binding.py"


def _write_git_exe_hint(pandaone_dir: Path) -> None:
    """把 git 的绝对路径固化到 .pandaone/git_exe.txt。

    为什么必须"安装时"做这件事：
      pre-commit hook 运行在 Git for Windows 的 MSYS 环境里，PATH 中**含非
      ASCII 字符**的目录项（典型：D:\\软件\\Git\\cmd）会被转码成 mojibake，
      hook 内部既找不到 git，也没法从 GIT_EXEC_PATH 反推（GIT_EXEC_PATH
      同样是 mojibake）。

      唯一能拿到**未损坏**路径的时刻是安装时刻——一个 PATH 完好的普通
      进程。于是这里解析一次、固化到 hook 旁边，运行时就只需要读文件。
      （不写死任何人的机器路径：写的是**这台机器**上真实存在的 git。）
    """
    git_exe = None
    try:
        from pandaone.git_installer import _find_git_executable

        git_exe = _find_git_executable()
    except Exception:
        git_exe = None
    if not git_exe:
        git_exe = shutil.which("git")
    if not git_exe:
        return
    try:
        (pandaone_dir / "git_exe.txt").write_text(git_exe, encoding="utf-8")
    except OSError:
        pass


def install_hook(root: Path) -> int:
    """安装 pre-commit hook

    v0.7.35: **复制是硬门禁**。
      原来复制是条件执行（``if CHECK_SCRIPT.exists():``），打印却是无条件 ——
      模板缺失时用户照样看到"[OK] pre-commit-check.py 已复制"，而文件根本没
      拷过去。那不是显示瑕疵，是**谎报**：用户会以为 L3 门禁已就位，实际 hook
      一跑就 ImportError / FileNotFoundError。现在复制失败一律 return 1。
    """
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
    try:
        pandaone_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(t("_hook_copy_failed", path=pandaone_dir, err=e))
        return 1

    # v0.7.35: 共享判定模块一起拷贝（hook 模板按同目录 import 它）
    # 两个文件都是 hook 的**运行时依赖**：缺任何一个，hook 跑起来就会炸，
    # 所以缺一即失败（不再"跳过还报成功"）。
    if not CHECK_SCRIPT.exists():
        print(t("_hook_copy_failed", path=CHECK_SCRIPT, err="source file missing"))
        return 1
    if not BINDING_MODULE.exists():
        print(t("_hook_copy_failed", path=BINDING_MODULE, err="source file missing"))
        return 1
    try:
        shutil.copy(CHECK_SCRIPT, pandaone_dir / "pre-commit-check.py")
    except OSError as e:
        print(t("_hook_copy_failed", path=pandaone_dir / "pre-commit-check.py", err=e))
        return 1
    try:
        shutil.copy(BINDING_MODULE, pandaone_dir / "audit_binding.py")
    except OSError as e:
        print(t("_hook_copy_failed", path=pandaone_dir / "audit_binding.py", err=e))
        return 1

    # 固化 git 绝对路径：hook 运行时的 PATH 不可信（MSYS 转码会破坏中文路径）
    _write_git_exe_hint(pandaone_dir)

    hook_path = git_hooks / "pre-commit"
    if hook_path.exists():
        # 备份现有 hook
        backup = git_hooks / "pre-commit.backup"
        try:
            shutil.copy(hook_path, backup)
        except OSError as e:
            print(t("_hook_copy_failed", path=backup, err=e))
            return 1
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
    try:
        hook_path.write_bytes(content)
    except OSError as e:
        print(t("_hook_copy_failed", path=hook_path, err=e))
        return 1

    # 添加可执行权限（Unix）
    current = hook_path.stat().st_mode
    hook_path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(t("_hook_installed", hook_path=hook_path))
    # 只有**真的复制成功**才打印"已复制"
    print(t("_hook_check_copied", path=pandaone_dir / "pre-commit-check.py"))
    print(t("_hook_binding_copied", path=pandaone_dir / "audit_binding.py"))
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