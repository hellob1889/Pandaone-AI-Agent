# cli.py chunk 6/6: lines 2069-2351
# Phase 9: OS 右键菜单集成
# ============================================================
# v0.7.21.3 hotfix: 顶部独立 import pathlib.Path (之前依赖 cli.py loader 共享
#   part_001 注入 namespace; 单 import 不走 loader 报 NameError on Path).
from pathlib import Path

# v0.7.22 P0-1 fix: 提到模块级, 让 tests/ 能直接断言这些结构常量
# (之前定义在 _windows_registry_install() 函数体内, 外部取不到, 没法测)。
#
# BASE_KEYS: 三个右键入口 (任意文件 / 目录 / 目录空白处) 的父键。
BASE_KEYS = [
    r"Software\Classes\*\shell\Pandaone",
    r"Software\Classes\Directory\shell\Pandaone",
    r"Software\Classes\Directory\Background\shell\Pandaone",
]
# ExtendedSubCommandsKey 的值相对 base_key 的父级 (shell 层) 解析,
# 即 "Pandaone\Shell" → Software\Classes\<type>\shell\Pandaone\Shell
CASCADE_SUBKEY_REL = r"Pandaone\Shell"
# (注册表 verb 名, 显示名, 对应 pandaone 子命令)
SUB_COMMANDS = [
    ("Init",   "Pandaone Init (init)",   "init"),
    ("Lock",   "Pandaone Lock (lock)",   "lock"),
    ("Status", "Pandaone Status (status)", "status"),
    ("Unlock", "Pandaone Unlock (unlock)", "unlock"),
]


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
    v0.7.9 fix (PR #35): Windows uses Python winreg directly to write registry,
    completely bypassing PowerShell. Fixes 5 accumulated bugs (BOM / #Requires /
    [CmdletBinding()] / $ErrorActionPreference inside function body / PowerShell 7+
    expression-if syntax / parentheses in comments confusing parser).
    Registry structure (v0.7.22 P0-1 fix — 实测验证):
      HKCU\\Software\\Classes\\*\\shell\\Pandaone (right-click on any file)
          MUIVerb                 = "Pandaone 审计工具 / Audit Tools"
          ExtendedSubCommandsKey  = "Pandaone\\Shell"
          \\Shell\\Init\\command   → pandaone init --root "%V"
          \\Shell\\Lock\\command   → pandaone lock --root "%V"
          \\Shell\\Status\\command → pandaone status --root "%V"
          \\Shell\\Unlock\\command → pandaone unlock --root "%V"
      HKCU\\Software\\Classes\\Directory\\shell\\Pandaone (right-click on directory)
      HKCU\\Software\\Classes\\Directory\\Background\\shell\\Pandaone (right-click on background)

    为什么是 ExtendedSubCommandsKey, 不是 SubCommands:
      MS 文档 "How to Create Cascading Menus with the SubCommands Registry Entry"
      要求自定义静态动词实现在
        HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CommandStore\\Shell\\<Verb>\\command
      即 SubCommands 方案依赖 HKLM (要管理员权限), HKCU 用户级注册不进去,
      Explorer 会静默隐藏整个级联菜单 (不报错、不写日志)。
      ExtendedSubCommandsKey 指向 HKCU 内相对路径, 普通用户即可用。

    实测 (Shell.Application 的 item.Verbs() 直接问 Explorer 到底有哪些动词):
        SubCommands + shell\\<name>\\open\\command → 不显示  (v0.7.20 的修复方案, 实测无效)
        SubCommands + shell\\<name>\\command       → 不显示
        SubCommands=<相对路径> + 各种子项位置      → 不显示
        ExtendedSubCommandsKey + <name>\\command    → 显示 ✅

    不要再加 "open" 中间层:
      "open" 是动词名 (系统默认动词就是 shell\\open\\command), 放在 verb 下面
      会被当成子动词, Explorer 反而不认。verb 自己的命令就在 <verb>\\command。
    """
    import winreg

    try:
        if action == "uninstall":
            print(t("ctx_banner_uninstall"))
            for base in BASE_KEYS:
                # v0.7.22: 删当前结构 (<base>\Shell\<name>\command) + 全部历史遗留结构。
                # 从深到浅删, 否则父键非空时 DeleteKey 会抛 OSError。
                for name, _, _ in SUB_COMMANDS:
                    for p in (
                        f"{base}\\Shell\\{name}\\command",
                        f"{base}\\Shell\\{name}",
                        f"{base}\\shell\\{name}\\open\\command",
                        f"{base}\\shell\\{name}\\open",
                        f"{base}\\shell\\{name}\\command",
                        f"{base}\\shell\\{name}",
                    ):
                        try:
                            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
                        except (FileNotFoundError, OSError):
                            pass
                for p in (f"{base}\\Shell", f"{base}\\shell"):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
                    except (FileNotFoundError, OSError):
                        pass
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
                except (FileNotFoundError, OSError):
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

        # 清理旧条目 (幂等)
        # v0.7.21 hotfix: Win11 锁 base_key 也会抛 OSError (PermissionError 子类), 加 catch 跳过
        # v0.7.22: 同时清 v0.7.20 及更早的历史结构, 避免遗留键干扰 Explorer 解析
        for base in BASE_KEYS:
            for name, _, _ in SUB_COMMANDS:
                for p in (
                    f"{base}\\Shell\\{name}\\command",
                    f"{base}\\Shell\\{name}",
                    f"{base}\\shell\\{name}\\open\\command",
                    f"{base}\\shell\\{name}\\open",
                    f"{base}\\shell\\{name}\\command",
                    f"{base}\\shell\\{name}",
                ):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
                    except (FileNotFoundError, OSError):
                        pass
            for p in (f"{base}\\Shell", f"{base}\\shell"):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p)
                except (FileNotFoundError, OSError):
                    pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
            except (FileNotFoundError, OSError):
                pass
        print(t("ctx_step1"))

        icon_value = f'"{pandaone_exe}",0'
        # v0.7.21: try/except per BASE_KEY. Win11 锁 Directory\shell + Directory\Background\shell
        # 报 WinError 5 (PermissionError) 时, log warning + 继续下一个 base_key.
        # 装机用户至少 1/3 base_key (*\shell 文件右键) 能用, 不再 100% 失败.
        base_results = []  # [(base, "OK" | "SKIP", err_msg)]
        for base in BASE_KEYS:
            try:
                # 主菜单 (cascade = submenu)
                # v0.7.22 P0-1 fix: 改用 ExtendedSubCommandsKey。
                #   SubCommands 方案依赖 HKLM 的 CommandStore (需管理员), HKCU 注册
                #   不进去 → Explorer 静默隐藏整个菜单 (v0.7.20 的修复实测无效)。
                #   MUIVerb 提供显示名; 不设 (Default) (MS 文档: CascadeMenu 的 Default 不应设置)。
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
                    winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Pandaone 审计工具 / Audit Tools")
                    winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_value)
                    winreg.SetValueEx(key, "ExtendedSubCommandsKey", 0, winreg.REG_SZ, CASCADE_SUBKEY_REL)
                    # 清掉历史遗留的 SubCommands (空串会让 Explorer 判 0 子菜单 → 隐藏)
                    try:
                        winreg.DeleteValue(key, "SubCommands")
                    except (FileNotFoundError, OSError):
                        pass
                # 4 个 subcommands: <base>\Shell\<name>\command  (不加 open 中间层)
                for name, label, action_cmd in SUB_COMMANDS:
                    sub_path = f"{base}\\Shell\\{name}"
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub_path) as sub_key:
                        winreg.SetValueEx(sub_key, "", 0, winreg.REG_SZ, label)
                        winreg.SetValueEx(sub_key, "Icon", 0, winreg.REG_SZ, icon_value)
                    # v0.7.20 P0-3 fix: 去掉 --trust-default, 避免右键菜单静默关 L5 自校验
                    cmd_path = f"{sub_path}\\command"
                    cmd_value = f'"{pandaone_exe}" --silent {action_cmd} --root "%V"'
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
                        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_value)
                base_results.append((base, "OK", None))
            except PermissionError as e:
                # Win11 锁常见. 跳过, log warning, 继续下一个 base_key.
                base_results.append((base, "SKIP", str(e)))
                print(t("ctx_win11_lock_skip", base=base, err=e), file=sys.stderr)
            except OSError as e:
                # 其他 OS 错 (PERM 也归 OSError 父类), 同样 skip 保持向后兼容
                base_results.append((base, "SKIP", str(e)))
                print(t("ctx_win11_lock_skip", base=base, err=e), file=sys.stderr)

        # v0.7.21: 统计 1+ OK 才算整体成功. 0 OK 仍 fail.
        ok_count = sum(1 for _, s, _ in base_results if s == "OK")
        skip_count = sum(1 for _, s, _ in base_results if s == "SKIP")
        if ok_count == 0:
            # 3 个 base_key 全 fail (极少见, 整 HKCU 写不进去), 报 ERROR
            print(t("ctx_self_check_fail"), file=sys.stderr)
            return 1
        if skip_count > 0:
            # 部分安装, 告诉 user 哪几个 skip
            print(t("ctx_partial_install_summary", ok=ok_count, total=len(BASE_KEYS), fail=skip_count))
        # v0.7.20 P0-1 fix: 装后自检回读, 验证 Explorer 能解析所有 verb
        # 不然写完注册表但 verb 不可调用, 用户右键看不到菜单
        # v0.7.21: 自检只检查 OK 的 base_key, SKIP 的不参与自检
        print(t("ctx_step2"))
        self_check_ok = True
        for base, status, _ in base_results:
            if status != "OK":
                continue  # SKIP 跳过自检
            # v0.7.22: 自检按新结构回读 —— 父键的 ExtendedSubCommandsKey +
            # 每个 verb 的 <base>\Shell\<name>\command 必须真实可读,
            # 否则不能打印 "安装完成" (v0.7.20 的自检查的是 open\command, 恒过, 形同虚设)
            try:
                _pk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)
                _pv, _ = winreg.QueryValueEx(_pk, "ExtendedSubCommandsKey")
                winreg.CloseKey(_pk)
                if _pv != CASCADE_SUBKEY_REL:
                    print(t("ctx_self_check_verb_err", verb_path=f"{base}\\ExtendedSubCommandsKey"), file=sys.stderr)
                    self_check_ok = False
            except FileNotFoundError:
                print(t("ctx_self_check_verb_err", verb_path=f"{base}\\ExtendedSubCommandsKey"), file=sys.stderr)
                self_check_ok = False
            for name, _, _ in SUB_COMMANDS:
                verb_path = f"{base}\\Shell\\{name}\\command"
                try:
                    _k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, verb_path)
                    _v, _ = winreg.QueryValueEx(_k, "")
                    winreg.CloseKey(_k)
                except FileNotFoundError:
                    print(t("ctx_self_check_verb_err", verb_path=verb_path), file=sys.stderr)
                    self_check_ok = False
        if not self_check_ok:
            print(t("ctx_self_check_fail"), file=sys.stderr)
            return 1
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


def is_machine_readable_mode(argv=None) -> bool:
    """当前调用是否处于"机器可读输出"模式（`--json`）。

    第一性原理:
        机器端消费方（CI 脚本 / IDE 插件 / MCP）对 `pandaone doctor --json`
        的做法是 **json.loads(整个 stdout)**。所以 stdout 上**只能**有那一个
        JSON 文档 —— 提示行、装饰行、进度行都会让它直接抛 "Expecting value"。

        人类可读模式（默认）**完全不受影响**：stdout 行为保持原样，
        终端里的可见提示一点不少。

        目前全仓库只有 `doctor --json` 一个机器可读入口（唯一带 --json 的
        子命令），所以按 argv 里是否出现 `--json` 判断即可；
        将来新增带 --json 的子命令自动生效。
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    return "--json" in args


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
    # v0.7.19 fix: --version / --help 跳过 fingerprint check (meta command 不需要)
    _meta_cmds = ("--version", "-V", "--help", "-h")
    _is_meta = any(a in _meta_cmds for a in argv_list)
    if "--update-fingerprint" in argv_list or _is_meta:
        pass
    elif getattr(args, "trust_default", False):
        # v0.7.23: 锁定期间拒绝 --trust-default
        #   (它会自动重写指纹, 是绕过 L5 的一条路, 必须同样受失败锁定约束)
        _locked, _remain = _fp_lock_state()
        if _locked:
            print(t("err_fp_locked", seconds=_remain))
            return 1
        if not check_fingerprint(silent=True):
            new_fp = compute_fingerprint()
            FP_PATH.parent.mkdir(parents=True, exist_ok=True)
            # v0.7.21.3 fix: 走 _save_fp json 格式（含 version + hash + stored_at）,
            #   跟 v0.7.21.2 设计的存储格式一致，文档一致 (README 描述 json).
            _save_fp(_get_pandaone_version(), new_fp)
            # v0.7.19 fix: trust_default 走 audit log 留痕, 避免静默改写指纹
            try:
                _audit_log = FP_PATH.parent / "pandaone.jsonl"
                _audit_log.parent.mkdir(parents=True, exist_ok=True)
                with _audit_log.open("a", encoding="utf-8") as _f:
                    _f.write("{\"event\": \"trust_default_fingerprint_update\", \"new\": \"" + new_fp + "\"}\n")
            except Exception:
                pass  # audit 写失败不影响主流程
    else:
        if not check_fingerprint():
            return 1
    # v0.7.15 UX fix: banner + README summary 只在交互终端 (TTY) 输出。
    #   之前任何命令都强制打印 40+ 行 roadmap backlog 噪音,导致:
    #   - MCP 工具返回被噪音+ANSI 撑爆 (LLM token 浪费)
    #   - 脚本/CI 管道 grep 不到关键输出
    #   - 测试断言被噪音干扰
    #   `--silent` 仍然保留为显式关闭开关 (右键菜单继续使用)。
    #
    # v0.7.34.0: 机器可读模式（--json）下 stdout 只能是那**一个** JSON 文档。
    #   banner + README 摘要合计 100+ 行装饰，实测在 TTY 下会把 doctor --json
    #   的 stdout 撑到 116 行 -> json.loads 必炸（比指纹 INFO 更严重）。
    #   这里让它们改走 stderr：终端里照样看得见（用户可见提示不丢），
    #   但 stdout 不再被污染。非 --json 模式行为**完全不变**。
    _machine = is_machine_readable_mode(argv_list)
    _is_tty = False
    try:
        _is_tty = sys.stdout.isatty()
    except Exception:
        _is_tty = False
    if not getattr(args, "silent", False) and _is_tty:
        _ui = sys.stderr if _machine else sys.stdout
        banner = load_banner()
        for line in banner:
            print(line, file=_ui)
        summary = load_readme_summary()
        for line in summary:
            print(line, file=_ui)
    if getattr(args, "version", False):
        from pandaone import __version__
        print(f"pandaone v{__version__}")
        return 0
    # ================================================================
    # v0.7.23: 指纹密码管理
    #   - 默认密码仍是 "0000"（用户明确要求保留默认值），但用户可自行改密
    #   - 比较走 hmac.compare_digest（常量时间，防时序侧信道）
    #   - 连续输错触发短时锁定，防暴力猜
    # ================================================================
    if getattr(args, "set_fingerprint_password", None) is not None:
        from pandaone.fp_security import FP_MIN_PASSWORD_LENGTH

        new_pwd = args.set_fingerprint_password
        if not new_pwd:
            print(t("err_fp_password_empty"))
            return 1
        if len(new_pwd) < FP_MIN_PASSWORD_LENGTH:
            print(t("err_fp_password_too_short", min_len=FP_MIN_PASSWORD_LENGTH))
            return 1
        try:
            p = _fp_set_password(new_pwd)
        except ValueError:
            print(t("err_fp_password_empty"))
            return 1
        print(t("ok_fp_password_set", path=p))
        return 0

    if getattr(args, "reset_fingerprint_password", False):
        p = _fp_clear_password()
        print(t("ok_fp_password_reset", path=p))
        return 0

    if getattr(args, "reset_fingerprint_lock", False):
        _fp_reset_lock()
        print(t("ok_fp_lock_reset"))
        return 0

    if getattr(args, "update_fingerprint", None):
        from pandaone.fp_security import FP_MAX_FAILURES, FP_LOCK_SECONDS

        pwd = args.update_fingerprint
        # 锁定中 → 即使密码正确也拒绝（防暴力猜）
        locked, remain = _fp_lock_state()
        if locked:
            print(t("err_fp_locked", seconds=remain))
            return 1
        expected = get_fingerprint_password()
        # 常量时间比较（hmac.compare_digest），不用明文 !=
        if not _fp_verify_password(pwd, expected):
            fails = _fp_register_failure()
            print(t("err_password_wrong"))
            if fails >= FP_MAX_FAILURES:
                print(t("err_fp_locked_now", seconds=FP_LOCK_SECONDS))
            return 1
        _fp_clear_failures()
        new_fp = compute_fingerprint()
        # v0.7.21.3 fix: 走 _save_fp json 格式（跟 _load_fp / check_fingerprint 一致）
        _save_fp(_get_pandaone_version(), new_fp)
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
