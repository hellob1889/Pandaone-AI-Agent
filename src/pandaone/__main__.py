"""让 `python -m pandaone` 工作.

PR #28 在这里加两件事:
  1. Git gate: 启动时探测 git,L2/L3 防护强依赖它。缺失则尝试自动安装。
  2. Monkey-patch: 注册 `pandaone doctor` 子命令 (cmd_doctor.py)。
     因为 cli.py 84KB 超大,MCP 单次推送限制 ~24KB,改 cli.py 不便。
     这里 monkey-patch 注册避免动 cli.py。

v0.7.23 新增（同样的 monkey-patch 套路，理由同上 —— 不动 cli_chunks 大文件）:
  - `pandaone setup`        (cmd_setup.py)      一键本地部署
  - `pandaone upgrade`      (cmd_upgrade.py)    一键升级
  - `pandaone backup`       (cmd_backup.py)     纯本地备份
  - `pandaone install-mcp`  (cmd_install_mcp.py) 注册 MCP 服务器
  - `pandaone init --with-git`                 顺带初始化本地 git 仓库
"""
import os
import sys

#: v0.7.23 新增的独立子命令模块（每个模块导出 COMMAND_NAME / add_parser / handler）
_EXTRA_COMMAND_MODULES = (
    "cmd_setup",
    "cmd_upgrade",
    "cmd_backup",
    "cmd_install_mcp",
)

_EXTRA_MODULES = None


def _load_extra_modules():
    """加载新增子命令模块（逐个 try，单个失败不影响其它）。"""
    global _EXTRA_MODULES
    if _EXTRA_MODULES is not None:
        return _EXTRA_MODULES
    import importlib

    mods = []
    for name in _EXTRA_COMMAND_MODULES:
        try:
            mods.append(importlib.import_module(f"pandaone.{name}"))
        except ImportError as e:
            print(f"[WARN] failed to load command module {name}: {e}", file=sys.stderr)
    _EXTRA_MODULES = mods
    return mods


def _patch_init_with_git(cli):
    """给 `pandaone init` 加 `--with-git`：顺带初始化本地 git 仓库。

    为什么需要: L2 看门狗的自动回滚依赖 `git checkout`，所以必须有 git 仓库
    和 baseline commit。但 `pandaone init` 不检查也不创建 git 仓库 ——
    用户以为 init 完事，实际 L2 是哑的（doctor 里显示 DISABLED - requires git）。
    """
    if getattr(cli, "_pandaone_init_git_patched", False):
        return
    orig_init = cli.COMMANDS.get("init")
    if orig_init is None:
        return

    def _cmd_init(args):
        rc = orig_init(args)
        if rc == 0 and getattr(args, "with_git", False):
            from pathlib import Path

            from pandaone import git_ops
            from pandaone.i18n import t

            root = Path(getattr(args, "root", ".") or ".").resolve()
            try:
                _created, m1 = git_ops.init_repo(root)
                _wrote, m2 = git_ops.ensure_repo_identity(root)
                _committed, m3 = git_ops.baseline_commit(root)
                print(t("init_with_git_done", msg=" / ".join([m1, m2, m3])))
            except Exception as e:
                print(t("init_with_git_fail", err=str(e)))
        return rc

    cli.COMMANDS["init"] = _cmd_init
    cli._pandaone_init_git_patched = True


def _ensure_doctor_registered():
    """
    Monkey-patch: 注册 doctor 子命令到 cli 模块。
    """
    try:
        # 1. 先注册 i18n_extras (PR #28 doctor/git gate 的翻译 key)
        from pandaone import i18n
        try:
            from pandaone.i18n_extras import register_extras
            register_extras(i18n.TRANSLATIONS)
        except ImportError:
            pass  # i18n_extras 模块缺失 (旧版本),静默跳过

        # 2. 注册 doctor 子命令到 cli
        from pandaone import cli
        from pandaone.cmd_doctor import add_doctor_parser, cmd_doctor
    except ImportError as e:
        # 静默 — 缺 cmd_doctor 不应该阻塞 CLI
        try:
            from pandaone.i18n import t as _t
        except Exception:
            def _t(k, **kw): return k
        print(_t("_doctor_register_failed", err=str(e)), file=sys.stderr)
        return

    # 1. 注册到 COMMANDS dict (dict 引用语义,cli.main() 可见)
    if "doctor" not in cli.COMMANDS:
        cli.COMMANDS["doctor"] = cmd_doctor

    # v0.7.23: 注册新增的独立子命令（setup / upgrade / backup / install-mcp）
    for _mod in _load_extra_modules():
        try:
            name = getattr(_mod, "COMMAND_NAME", None)
            handler = getattr(_mod, "handler", None)
            if name and handler:
                cli.COMMANDS[name] = handler
        except Exception as e:
            print(f"[WARN] failed to register command: {e}", file=sys.stderr)

    # 2. Monkey-patch build_parser,自动加 doctor subparser
    if getattr(cli, "_pandaone_doctor_patched", False):
        return  # 防止重复 patch

    _orig_build_parser = cli.build_parser

    def _patched_build_parser():
        parser = _orig_build_parser()
        # 找 subparsers action
        sub_action = None
        for action in parser._actions:
            if hasattr(action, "choices") and isinstance(action.choices, dict):
                sub_action = action
                break
        if sub_action is not None:
            try:
                add_doctor_parser(sub_action)
            except Exception as e:
                if "conflicting" not in str(e).lower() and "already" not in str(e).lower():
                    raise
            # v0.7.23: 新增子命令的 subparser
            for _mod in _load_extra_modules():
                try:
                    _mod.add_parser(sub_action)
                except Exception as e:
                    if "conflicting" not in str(e).lower() and "already" not in str(e).lower():
                        raise
            # v0.7.23: init --with-git
            try:
                _init_p = sub_action.choices.get("init")
                if _init_p is not None and not getattr(
                    _init_p, "_pandaone_with_git", False
                ):
                    _init_p.add_argument(
                        "--with-git",
                        action="store_true",
                        help="同时初始化本地 git 仓库并创建 baseline commit（L2 回滚依赖它）",
                    )
                    _init_p._pandaone_with_git = True
            except Exception:
                pass
        return parser

    cli.build_parser = _patched_build_parser
    cli._pandaone_doctor_patched = True

    # v0.7.23: init --with-git 的 handler 包装
    _patch_init_with_git(cli)


def _git_gate():
    """L2/L3 防护强依赖 git。缺失则尝试自动安装。

    Escape hatch: PANDAONE_SKIP_GIT_CHECK=1 环境变量 → 跳过 (CI / 测试)
    """
    try:
        from pandaone.i18n import t as _t
    except Exception:
        def _t(k, **kw):
            if "err" in kw:
                return f"[ERR] {kw['err']}"
            return k

    if os.environ.get("PANDAONE_SKIP_GIT_CHECK") == "1":
        return

    try:
        from pandaone.git_installer import (
            is_installed as _git_is_installed,
            install as _git_install,
            GitInstallError,
        )
    except ImportError:
        return

    if _git_is_installed():
        return

    # v0.7.34.0: 机器可读模式（--json）下 stdout 只能是那**一个** JSON 文档。
    #   "git 缺失"提示属于诊断信息 —— 机器可读模式下改走 stderr；
    #   普通模式下行为不变（仍走 stdout，终端里照样看得见）。
    try:
        from pandaone.cli import is_machine_readable_mode as _is_machine_mode
        _machine = _is_machine_mode()
    except Exception:
        _machine = False
    _ui = sys.stderr if _machine else sys.stdout

    try:
        if sys.stdout.isatty():
            print(_t("_gate_git_missing_attempt_install"), file=_ui)
        result = _git_install()
        if sys.stdout.isatty():
            print(_t("_gate_git_installed", ver=result.version, channel=result.channel), file=_ui)
            print(_t("_gate_git_installed_path", path=result.path), file=_ui)
            print(_t("_gate_git_restart_shell"), file=_ui)
    except GitInstallError as e:
        if sys.stdout.isatty():
            print(_t("_gate_git_install_failed", err=str(e)), file=_ui)
            from pandaone.git_installer import get_install_hint
            print(_t("_doctor_manual_hint"), file=_ui)
            print(get_install_hint(), file=_ui)
    except Exception as e:
        if sys.stdout.isatty():
            print(_t("_gate_git_install_unexpected", err_type=type(e).__name__, err=str(e)), file=_ui)


# 模块 import 时立即注册
_ensure_doctor_registered()


def main():
    """CLI 入口: 让 entry point (`pandaone` 命令) 走这里。

    PR #32 fix: 之前 `if __name__ == "__main__":` 保护块只在 `python -m pandaone`
    时跑;entry point `pandaone` (pyproject.toml `pandaone = "pandaone:main"`)
    走 `pandaone/__init__.py:main`,**完全跳过 __main__.py**,导致 monkey-patch
    注册的 doctor 子命令不可用。
    改用顶层 `def main()` + entry point 改 `"pandaone.__main__:main"`,保证 import
    副作用(_ensure_doctor_registered)和 git_gate 都被调用。
    """
    _git_gate()
    from pandaone.cli import main as _cli_main
    sys.exit(_cli_main())


if __name__ == "__main__":
    sys.exit(main())
