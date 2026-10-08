# cli.py chunk 6/6: lines 2069-2351
# Phase 9: OS 右键菜单集成
# ============================================================
def _find_installer_dir():
    """定位 installer/ 目录。"""
    return Path(__file__).resolve().parent / "installer"


INSTALLER_DIR = _find_installer_dir()

PLATFORM_HANDLERS = {
    "Windows": {
        "install": "windows/install_context_menu.ps1",
        "uninstall": "windows/uninstall_context_menu.ps1",
        "interpreter": ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"],
    },
    "Darwin": {
        "install": "macos/install_context_menu.sh",
        "uninstall": "macos/uninstall_context_menu.sh",
        "interpreter": ["bash"],
    },
    "Linux": {
        "install": "linux/install_context_menu.sh",
        "uninstall": "linux/uninstall_context_menu.sh",
        "interpreter": ["bash"],
    },
}


def detect_os_key():
    """sys.platform → PLATFORM_HANDLERS key"""
    p = sys.platform
    if p.startswith("win"):
        return "Windows"
    if p.startswith("darwin"):
        return "Darwin"
    if p.startswith("linux") or p.startswith("freebsd"):
        return "Linux"
    return ""


def _run_installer(action, force=False):
    """action: install|uninstall"""
    os_key = detect_os_key()
    if not os_key:
        return 2
    # v0.7.9 fix (PR #35): Windows 用 Python winreg 直接写注册表,
    # bypass PowerShell 完全 (PowerShell 5.1 / 7 兼容问题 + 5 BOM + #Requires + 注释内 () 干扰
    # 等多个 bug 自 v0.7.0 起累积, 用户机器只有 PowerShell 5.1 时右键菜单永远不可用)。
    # macOS / Linux 继续用 .sh 脚本 (无 PowerShell 依赖)。
    if os_key == "Windows":
        return _windows_registry_install(action, force)
    handler = PLATFORM_HANDLERS[os_key]
    script_rel = handler[action]
    interpreter = handler["interpreter"]
    script_path = INSTALLER_DIR / script_rel
    if not script_path.exists():
        return 1
    cmd = interpreter + [str(script_path)]
    env = os.environ.copy()
    try:
        from .i18n import get_lang
        env["PANDAX_LANG"] = get_lang()
    except Exception:
        pass
    try:
        # v0.7.9 fix (PR #35): 暴露 PowerShell stderr 到用户，避免 silent failure
        result = subprocess.run(cmd, check=False, env=env, timeout=60)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(t("ctx_subprocess_timeout", script=script_path), file=sys.stderr)
        return 124
    except FileNotFoundError:
        print(t("ctx_interp_not_found", interp=interpreter[0]), file=sys.stderr)
        return 127


def _find_pandaone_exe_windows():
    """Windows: 定位 pandaone.exe (在 PATH 或 Scripts 目录)"""
    import shutil as _shutil
    exe = _shutil.which("pandaone")
    if exe:
        return exe
    # fallback: 同目录的 python.exe → Scripts\pandaone.exe
    pyexe = _shutil.which("python")
    if pyexe:
        candidate = str(Path(pyexe).resolve().parent / "Scripts" / "pandaone.exe")
        if Path(candidate).exists():
            return candidate
    return None


def _windows_registry_install(action, force=False):
    """
    v0.7.9 fix (PR #35): Windows 直接用 Python winreg 写注册表,
    完全 bypass PowerShell. 修复 5 个累积 bug (BOM / #Requires / [CmdletBinding()]
    函数体内 $ErrorActionPreference / PowerShell 7+ 表达式 if 语法 / 注释内 () 干扰 parser).
    注册表结构与原 PS1 等价:
      HKCU\\Software\\Classes\\*\\shell\\Pandaone (任意文件右键)
          \\shell\\Init\\shell\\open\\command  → pandaone init --root "%V"
          \\shell\\Lock\\shell\\open\\command  → pandaone lock --root "%V"
          \\shell\\Status\\shell\\open\\command → pandaone status --root "%V"
          \\shell\\Unlock\\shell\\open\\command → pandaone unlock --root "%V"
      HKCU\\Software\\Classes\\Directory\\shell\\Pandaone (目录右键)
      HKCU\\Software\\Classes\\Directory\\Background\\shell\\Pandaone (空白处右键)
    """
    import winreg

    BASE_KEYS = [
        r"Software\Classes\*\shell\Pandaone",
        r"Software\Classes\Directory\shell\Pandaone",
        r"Software\Classes\Directory\Background\shell\Pandaone",
    ]
    # Bug fix (v0.7.15) F-03: V2 ExtendedSubCommandsKey 模式 (Win10/11 推荐)
    # 子菜单统一放在此位置（与 BASE_KEYS 分离），主菜单通过 ExtendedSubCommandsKey 引用
    EXT_SHELL_KEY = r"Software\Classes\Pandaone\Shell"
    # Init 子菜单的 ECF_SEPARATORBEFORE 标志 (0x20 = 在子项前加分隔线)
    ECF_SEPARATORBEFORE = 0x20
    SUB_COMMANDS = [
        ("Init",   "初始化 Pandaone (init)", "init"),
        ("Lock",   "锁定文件 (lock)",       "lock"),
        ("Status", "查看状态 (status)",     "status"),
        ("Unlock", "解锁文件 (unlock)",     "unlock"),
    ]

    try:
        if action == "uninstall":
            print(t("ctx_banner_uninstall"))
            for base in BASE_KEYS:
                # 先删子命令，再删主菜单 (顺序避免权限问题)
                for name, _, _ in SUB_COMMANDS:
                    sub_path = f"{base}\\shell\\{name}"
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub_path + "\\command")
                    except FileNotFoundError:
                        pass
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub_path)
                    except FileNotFoundError:
                        pass
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
                except FileNotFoundError:
                    pass
            # Bug fix (v0.7.15) F-03: 同时清理 EXT_SHELL_KEY 下的 V2 子菜单
            for name, _, _ in SUB_COMMANDS:
                ext_sub_path = f"{EXT_SHELL_KEY}\\{name}"
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, ext_sub_path + "\\command")
                except FileNotFoundError:
                    pass
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, ext_sub_path)
                except FileNotFoundError:
                    pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, EXT_SHELL_KEY)
            except FileNotFoundError:
                pass
            print(t("ctx_uninstall_done"))
            print(t("ctx_uninstall_restart_hint"))
            print("  taskkill /f /im explorer.exe && start explorer.exe")
            return 0

        # install
        pandaone_exe = _find_pandaone_exe_windows()
        if not pandaone_exe:
            print(t("ctx_exe_not_found"), file=sys.stderr)
            print(t("ctx_install_hint"))
            print("  pip install pandaone-guard")
            return 1

        # 检查是否已安装
        if not force:
            try:
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, BASE_KEYS[0])
                print(t("ctx_already_installed"))
                return 0
            except FileNotFoundError:
                pass

        print(t("ctx_banner_install"))
        print(t("ctx_pandaone_ok", exe=pandaone_exe))

        # 清理旧条目 (幂等) — 包括 BASE_KEYS 子菜单 + EXT_SHELL_KEY 分离区
        for base in BASE_KEYS:
            for name, _, _ in SUB_COMMANDS:
                sub_path = f"{base}\\shell\\{name}"
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub_path + "\\command")
                except FileNotFoundError:
                    pass
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub_path)
                except FileNotFoundError:
                    pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
            except FileNotFoundError:
                pass
        # 清理 EXT_SHELL_KEY 下的子菜单
        for name, _, _ in SUB_COMMANDS:
            ext_sub_path = f"{EXT_SHELL_KEY}\\{name}"
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, ext_sub_path + "\\command")
            except FileNotFoundError:
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, ext_sub_path)
            except FileNotFoundError:
                pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, EXT_SHELL_KEY)
        except FileNotFoundError:
            pass
        print(t("ctx_step1"))

        icon_value = f'"{pandaone_exe}",0'
        # Bug fix (v0.7.15) F-03: V2 ExtendedSubCommandsKey 模式
        # 主菜单：(Default)="" + MUIVerb + Icon + ExtendedSubCommandsKey 指向 EXT_SHELL_KEY
        # 子菜单：放在 EXT_SHELL_KEY 下 (分离位置, 避免 explorer cache 混乱)
        # Init 子项 CommandFlags=0x20 (ECF_SEPARATORBEFORE) 在 Win10/11 modern menu 中加分隔线
        for base in BASE_KEYS:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")
                winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Pandaone 审计工具 / Audit Tools")
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_value)
                winreg.SetValueEx(key, "ExtendedSubCommandsKey", 0, winreg.REG_SZ, EXT_SHELL_KEY)
        # 子菜单全部放在 EXT_SHELL_KEY 下
        for name, label, action_cmd in SUB_COMMANDS:
            ext_sub_path = f"{EXT_SHELL_KEY}\\{name}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ext_sub_path) as sub_key:
                winreg.SetValueEx(sub_key, "", 0, winreg.REG_SZ, label)
                winreg.SetValueEx(sub_key, "Icon", 0, winreg.REG_SZ, icon_value)
                # Init 子项加 CommandFlags=0x20 (Win10/11 子项前分隔线)
                if name == "Init":
                    winreg.SetValueEx(sub_key, "CommandFlags", 0, winreg.REG_DWORD, ECF_SEPARATORBEFORE)
            cmd_path = f"{ext_sub_path}\\command"
            cmd_value = f'"{pandaone_exe}" --silent --trust-default {action_cmd} --root "%V"'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_value)
        print(t("ctx_step2"))
        print(t("ctx_step3"))

        print()
        print(t("ctx_install_done"))
        print()
        print(t("ctx_test_label"))
        print(t("ctx_test_step1"))
        print(t("ctx_test_step2"))
        print(t("ctx_test_step3"))
        print()
        print(t("ctx_uninstall_label"))
        print("  pandaone uninstall-context")
        print()
        print(t("ctx_install_restart_hint"))
        print("  taskkill /f /im explorer.exe && start explorer.exe")
        return 0

    except PermissionError as e:
        print(t("ctx_perm_error", err=e), file=sys.stderr)
        print(t("ctx_perm_hint"), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def cmd_install_context(args):
    """Phase 9 - 安装 OS 右键菜单"""
    force = getattr(args, "force", False)
    lang = getattr(args, "lang", None)
    if lang:
        i18n_init(lang)
    return _run_installer("install", force=force)


def cmd_uninstall_context(args):
    """Phase 9 - 卸载 OS 右键菜单"""
    return _run_installer("uninstall")


COMMANDS = {
    "init": cmd_init,
    "lock": cmd_lock,
    "unlock": cmd_unlock,
    "write": cmd_write,
    "log": cmd_log,
    "export": cmd_export,
    "install-git": cmd_install_git,
    "install-hook": cmd_install_hook,
    "status": cmd_status,
    "watch": cmd_watch,
    "serve": cmd_serve,
    "ci": cmd_ci,
    "install-context": cmd_install_context,
    "uninstall-context": cmd_uninstall_context,
}


def main(argv=None):
    argv_list = argv if argv is not None else sys.argv[1:]
    import re as _re
    has_trust_default = any(a == "--trust-default" or a.startswith("--trust-default=") for a in argv_list)
    has_silent = any(a == "--silent" or a.startswith("--silent=") for a in argv_list)
    cleaned_argv = []
    lang_override = None
    i = 0
    while i < len(argv_list):
        arg = argv_list[i]
        m_eq = _re.fullmatch(r"--lang=(\S+)", arg)
        if m_eq:
            lang_override = m_eq.group(1)
            i += 1
            continue
        if arg == "--lang" and i + 1 < len(argv_list):
            lang_override = argv_list[i + 1]
            i += 2
            continue
        if arg == "--trust-default" or arg.startswith("--trust-default="):
            i += 1
            continue
        if arg == "--silent" or arg.startswith("--silent="):
            i += 1
            continue
        cleaned_argv.append(arg)
        i += 1
    if has_silent:
        cleaned_argv.insert(0, "--silent")
    if has_trust_default:
        cleaned_argv.insert(0, "--trust-default")
    if lang_override is not None and lang_override not in ("zh-CN", "en"):
        cleaned_argv.append(f"--lang={lang_override}")
        lang_override = None
    parser = build_parser()
    args, _ = parser.parse_known_args(cleaned_argv)
    if lang_override is not None:
        args.lang = lang_override
    i18n_init(args.lang)
    if "--update-fingerprint" in argv_list:
        pass
    elif getattr(args, "trust_default", False):
        if not check_fingerprint(silent=True):
            new_fp = compute_fingerprint()
            FP_PATH.parent.mkdir(parents=True, exist_ok=True)
            FP_PATH.write_text(new_fp, encoding="utf-8")
    else:
        if not check_fingerprint():
            return 1
    # v0.7.15 UX fix: banner + README summary 只在交互终端 (TTY) 输出。
    #   之前任何命令都强制打印 40+ 行 roadmap backlog 噪音,导致:
    #   - MCP 工具返回被噪音+ANSI 撑爆 (LLM token 浪费)
    #   - 脚本/CI 管道 grep 不到关键输出
    #   - 测试断言被噪音干扰
    #   `--silent` 仍然保留为显式关闭开关 (右键菜单继续使用)。
    _is_tty = False
    try:
        _is_tty = sys.stdout.isatty()
    except Exception:
        _is_tty = False
    if not getattr(args, "silent", False) and _is_tty:
        banner = load_banner()
        for line in banner:
            print(line)
        summary = load_readme_summary()
        for line in summary:
            print(line)
    if getattr(args, "version", False):
        from pandaone import __version__
        print(f"pandaone v{__version__}")
        return 0
    if getattr(args, "update_fingerprint", None):
        pwd = args.update_fingerprint
        expected = get_fingerprint_password()
        if pwd != expected:
            print(t("err_password_wrong"))
            return 1
        new_fp = compute_fingerprint()
        FP_PATH.write_text(new_fp, encoding="utf-8")
        print(t("ok_fp_updated", fp=new_fp[:16]))
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    handler = COMMANDS.get(args.command)
    if handler is None:
        print(t("err_unknown_cmd", cmd=args.command))
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
