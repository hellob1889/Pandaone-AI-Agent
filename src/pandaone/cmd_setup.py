# -*- coding: utf-8 -*-
"""
cmd_setup.py — `pandaone setup`：一条命令完成本地部署

对应外部建议书「建议 1.1」。

为什么需要
----------
`pip install` 只装了 Python 包，本地部署还得用户自己一步步拼：
    1. pip install --upgrade pandaone-guard   # 装包（但 git 不在 PATH，工具不完整）
    2. 手工修 User PATH
    3. git init + git config + 首次提交        # L2 回滚依赖它，但用户不知道
    4. pandaone init --root .                  # 7 层防护
    5. pandaone watch --root . --daemon        # 看门狗
    6. pandaone install-context                # 右键菜单
    7. pandaone serve                          # 仪表盘
这 7 步没有任何一步是 pip 自动做的，README 里也没有明确的引导顺序，
用户第一次装完会有"到底还差什么"的困惑。

setup 做的事（全部本地完成，不设任何 remote，不推送任何东西）
--------------------------------------------------------------
    检测 Python → 检测/引导安装 git → 持久化 PATH → 初始化本地 git 仓库
    → pandaone init（7 层防护 + 二进制快照）→ 启动看门狗 → 注册右键菜单
    → 启动仪表盘 → 打印体检报告

设计约束
--------
- 任何一步失败都**不中断**后续步骤（尽力而为 + 最后汇总），
  避免"git 装不上 → 连 init 都做不了"。
- 全程不碰远程：不 git remote add、不 push、不需要 GitHub 账号。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _t(key: str, **kw) -> str:
    """取 i18n 文本；i18n 不可用时退回 key 本身。"""
    try:
        from pandaone.i18n import t

        return t(key, **kw)
    except Exception:
        return key


#: setup 启动仪表盘时的**期望**端口。
#: 注意：serve 的端口被占时会**原子顺延**到下一个可用端口，
#: 所以"期望端口"未必等于"实际端口" —— 实际端口以
#: `<root>/.pandaone/serve_port.txt` 为准（唯一真值来源）。
SERVE_EXPECTED_PORT = 8765


def _python_version() -> tuple[int, int]:
    return sys.version_info[0], sys.version_info[1]


def _parse_min_python(spec: str) -> tuple[int, int]:
    try:
        parts = str(spec).split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 3, 8


def _executable_dir() -> Path:
    """pandaone 可执行文件所在目录。

    frozen（.exe 安装包形态）：exe 自己所在的目录，即 %LOCALAPPDATA%\\Pandaone。
    源码 / pip 安装形态：解释器的 scripts 目录（pandaone.exe 真正落地的位置）。

    注意：源码形态下 ``Path(sys.executable).parent`` 是**解释器**目录
    （如 C:\\Python311），不是 scripts 目录；把它写进 PATH 等于白写。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    try:
        import sysconfig

        scripts = sysconfig.get_path("scripts")
        if scripts:
            return Path(scripts).resolve()
    except Exception:
        pass
    return Path(sys.executable).resolve().parent


# ---------------------------------------------------------------------------
# PATH 持久化
# ---------------------------------------------------------------------------

def persist_user_path(target: str | Path) -> tuple[str, str]:
    """把 target 目录写进**用户级** PATH（不动系统级）。

    Windows: 写 HKCU\\Environment\\Path
    POSIX:   追加 export PATH 到 ~/.bashrc / ~/.zshrc

    Returns:
        (状态, 说明文本)，状态 ∈ ok / skip / warn
    """
    target = str(Path(target).expanduser().resolve())
    try:
        if sys.platform.startswith("win"):
            return _persist_path_windows(target)
        return _persist_path_posix(target)
    except Exception as e:
        return "warn", _t("setup_path_failed", err=str(e))


def _broadcast_env_change() -> None:
    """通知 Explorer 环境变量已变（新开的终端立刻生效）。失败不影响主流程。"""
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, None,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PATH 冲突清理
# ---------------------------------------------------------------------------

def _shadow_backup_name(path: Path) -> Path:
    """冲突 exe 的备份名：pandaone.exe -> pandaone.exe.bak-pandaone-<ver>"""
    ver = "unknown"
    try:
        from pandaone import __version__ as v
        ver = str(v)
    except Exception:
        pass
    return path.with_name(f"{path.name}.bak-pandaone-{ver}")


def clean_path_conflicts(dry_run: bool = False, exclude: str | None = None) -> tuple[str, str]:
    """把**抢占命令**的旧 pandaone 改名备份，让当前这个版本胜出。

    为什么是"改名"而不是"删除"或"pip uninstall":
      - 改名：不碰 pip 的包元数据、不删用户文件，**可逆**（改回去即可）；
      - 删除：不可逆，删错了没法恢复；
      - pip uninstall：要机器上有 python + pip，还可能连带影响别的依赖。

    前提（实测）：Windows 的 PATH 是「机器级 + 用户级」拼接，机器级在前。
    用户级 PATH 前置**够不着**机器级的同名命令 —— 只能让那个不再是 pandaone。

    Args:
        dry_run: 只报告不改动。
        exclude: "当前运行的这个 pandaone" 的可执行文件路径（内部自动推导）。

    Returns:
        (状态, 说明文本)，状态 ∈ ok / skip / warn
    """
    try:
        from pandaone import path_conflicts as _pc
    except Exception as e:
        return "warn", _t("setup_conflict_check_failed", err=str(e))

    try:
        shadows = _pc.shadows(exclude)
    except Exception as e:
        return "warn", _t("setup_conflict_check_failed", err=str(e))

    if not shadows:
        return "skip", _t("setup_conflict_none")

    renamed: list[str] = []
    failed: list[str] = []
    for s in shadows:
        src = Path(s)
        if not src.exists():
            continue
        dst = _shadow_backup_name(src)
        if dst.exists():
            failed.append(str(src))
            continue
        if dry_run:
            renamed.append(f"{src} -> {dst.name}")
            continue
        try:
            src.rename(dst)
            renamed.append(f"{src} -> {dst.name}")
        except Exception:
            failed.append(str(src))

    if failed and not renamed:
        return "warn", _t("setup_conflict_failed", paths="; ".join(failed))
    if failed:
        return "warn", _t("setup_conflict_partial", done="; ".join(renamed),
                          failed="; ".join(failed))
    return "ok", _t("setup_conflict_renamed", paths="; ".join(renamed))


def _persist_path_windows(target: str) -> tuple[str, str]:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
    ) as key:
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""
        parts = [p for p in str(current).split(";") if p.strip()]
        norm = target.rstrip("\\/").lower()
        # 已在最前 —— 无需动
        if parts and parts[0].rstrip("\\/").lower() == norm:
            return "skip", _t("setup_path_present", target=target)
        existed = any(p.rstrip("\\/").lower() == norm for p in parts)
        # 去掉所有等价项（大小写 / 尾部反斜杠差异，或重复出现多次）
        parts = [p for p in parts if p.rstrip("\\/").lower() != norm]
        # v0.7.27.0: **前置**而非追加。
        #   理由：Windows 上 pip 版 pandaone 装在 Python\Scripts\，通常排在 PATH 靠前。
        #   追加的话，装完 exe 版后 `pandaone` 仍然命中旧 pip 版 —— 用户体感"装了没生效"。
        #   posix 分支本来就是前置（export PATH="{target}:$PATH"），这里对齐跨平台语义。
        parts.insert(0, target)
        new_value = ";".join(parts)
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_value)
    _broadcast_env_change()
    if existed:
        return "ok", _t("setup_path_moved", target=target)
    return "ok", _t("setup_path_added", target=target)


def _persist_path_posix(target: str) -> tuple[str, str]:
    home = Path.home()
    for rc_name in (".bashrc", ".zshrc", ".profile"):
        rc = home / rc_name
        if not rc.exists():
            continue
        try:
            text = rc.read_text(encoding="utf-8")
        except OSError:
            continue
        if target in text:
            return "skip", _t("setup_path_present", target=target)
        try:
            with rc.open("a", encoding="utf-8") as f:
                f.write(f'\nexport PATH="{target}:$PATH"\n')
        except OSError as e:
            return "warn", _t("setup_path_failed", err=str(e))
        return "ok", _t("setup_path_posix_added", target=target, rc=rc_name)
    return "warn", _t("setup_path_no_rc")


# ---------------------------------------------------------------------------
# 各步骤
# ---------------------------------------------------------------------------

def _step_python(min_py: tuple[int, int]) -> tuple[str, str]:
    """检测 Python 版本。返回 (状态, 说明)，状态 ∈ ok/warn/fail。"""
    cur = _python_version()
    ver = f"{cur[0]}.{cur[1]}.{sys.version_info[2]}"
    if cur < min_py:
        return "fail", _t(
            "setup_python_old", ver=ver, min=f"{min_py[0]}.{min_py[1]}"
        )
    return "ok", _t("setup_python_ok", ver=ver, min=f"{min_py[0]}.{min_py[1]}")


def _step_git(allow_install: bool) -> tuple[str, str]:
    """检测 git；缺失时按需自动安装。"""
    try:
        from pandaone import git_installer
    except ImportError as e:
        return "warn", _t("setup_git_failed", err=str(e))
    try:
        if git_installer.is_installed():
            return "ok", _t(
                "setup_git_ok",
                ver=git_installer.version() or "?",
                path=git_installer.path() or "?",
            )
    except Exception:
        pass
    if not allow_install:
        return "warn", _t("setup_git_missing")
    try:
        result = git_installer.install()
    except Exception as e:
        return "warn", _t("setup_git_failed", err=str(e))
    return "ok", _t(
        "setup_git_installed",
        ver=getattr(result, "version", "?") or "?",
        path=getattr(result, "path", "?") or "?",
    )


def _step_git_repo(root: Path) -> tuple[str, str]:
    """初始化本地 git 仓库 + 仓库级身份 + 首次 baseline commit。"""
    try:
        from pandaone import git_ops
    except ImportError as e:
        return "warn", _t("setup_git_failed", err=str(e))
    try:
        created, msg = git_ops.init_repo(root)
        _, id_msg = git_ops.ensure_repo_identity(root)
        committed, c_msg = git_ops.baseline_commit(root)
    except git_ops.GitOpsError as e:
        return "warn", _t("setup_git_failed", err=str(e))
    parts = [msg, id_msg, c_msg]
    return "ok", " / ".join(p for p in parts if p)


def _step_init(root: Path) -> tuple[str, str]:
    """跑 pandaone init（7 层防护 + 二进制快照）。"""
    try:
        from pandaone.cli import cmd_init
    except ImportError as e:
        return "warn", _t("setup_git_failed", err=str(e))
    args = SimpleNamespace(
        root=str(root),
        ext=None,
        no_binary=False,
        force_reset=False,
        with_git=False,
    )
    try:
        rc = cmd_init(args)
    except Exception as e:
        return "warn", _t("setup_git_failed", err=str(e))
    if rc != 0:
        return "warn", _t("setup_git_failed", err=f"init exit={rc}")
    return "ok", _t("setup_init", path=str(root / ".pandaone"))


def _step_watch(root: Path) -> tuple[str, str]:
    """启动看门狗（守护进程）。"""
    try:
        from pandaone.cli import cmd_watch
    except ImportError as e:
        return "warn", _t("setup_git_failed", err=str(e))
    args = SimpleNamespace(root=str(root), daemon=True)
    try:
        rc = cmd_watch(args)
    except Exception as e:
        return "warn", _t("setup_watch_fail", err=str(e))
    if rc != 0:
        return "warn", _t("setup_watch_fail", err=f"exit={rc}")
    pid = ""
    pid_file = root / ".pandaone" / ".watchdog_pid"
    if pid_file.is_file():
        try:
            pid = pid_file.read_text(encoding="utf-8").strip()
        except OSError:
            pid = ""
    return "ok", _t("setup_watch_ok", pid=pid or "?")


def _step_context() -> tuple[str, str]:
    """注册 OS 右键菜单。"""
    if not sys.platform.startswith("win"):
        return "skip", _t("setup_context_skip_platform")
    try:
        from pandaone.cli import cmd_install_context
    except ImportError as e:
        return "warn", _t("setup_context_fail", err=str(e))
    args = SimpleNamespace(force=True, lang=None)
    try:
        rc = cmd_install_context(args)
    except Exception as e:
        return "warn", _t("setup_context_fail", err=str(e))
    if rc not in (0, None):
        return "warn", _t("setup_context_fail", err=f"exit={rc}")
    return "ok", _t("setup_context_ok")


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_frozen() -> bool:
    """当前是否运行在 PyInstaller 打包形态（.exe）。"""
    return bool(getattr(sys, "_MEIPASS", None))


def _read_serve_port(root: Path):
    """读回 serve **实际**端口（None = 还没起来 / 读不到）。

    端口文件由 serve 侧写入（见 pandaone_serve.write_serve_port）。
    """
    try:
        from pandaone.pandaone_serve import read_serve_port
    except Exception:
        return None
    try:
        return read_serve_port(root)
    except Exception:
        return None


def _clear_serve_port_file(root: Path) -> None:
    """删掉**上一次**残留的端口文件（启动新 serve 前调用）。"""
    try:
        from pandaone.pandaone_serve import clear_serve_port
    except Exception:
        return
    try:
        clear_serve_port(root)
    except Exception:
        pass


def _step_serve(root: Path, timeout: float = 12.0) -> tuple[str, str]:
    """后台启动仪表盘并打印本地访问地址。

    v0.7.34.1：**不再**用探测式的 `_find_free_port()` 决定端口。
      旧实现有三个硬伤：
        1. 启动 serve 时**没有传 --port** —— serve 用自己的默认端口，
           和这里轮询的探测端口**根本不是同一个**；
        2. 探测（bind 完立刻 close）和真正 bind 之间有 TOCTOU 窗口；
        3. 期望端口被占时 serve 会**原子顺延**，旧实现还在死等期望端口
           → 12 秒空等 → 返回一个打不开的 URL。
      现在：启动时显式传 `--port`（期望端口），serve 起来后把**实际**端口写进
      `<root>/.pandaone/serve_port.txt`；这里等该文件出现且端口可连，
      再用**实际**端口拼 URL。
    """
    host = "127.0.0.1"
    expected_port = SERVE_EXPECTED_PORT
    # v0.7.29.0: 形态感知 —— 与 cmd_upgrade._restart_serve 同一个坑。
    #   frozen 形态下 sys.executable 就是 pandaone.exe 本身，
    #   `pandaone.exe -m pandaone serve` 会被当成子命令 -> "invalid choice: '-m'"。
    #   （v0.7.26.0 只在 upgrade 里修了，setup 这条路漏了，一直没被发现。）
    if _is_frozen():
        cmd = [
            sys.executable, "serve", "--root", str(root),
            "--port", str(expected_port),
        ]
    else:
        cmd = [
            sys.executable, "-m", "pandaone", "serve", "--root", str(root),
            "--port", str(expected_port),
        ]
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    # 先删掉**上一次**残留的端口文件 —— 否则可能把旧服务的端口当成新服务的，
    # 报一个"已就绪"但实际根本没起起来的假 URL。
    _clear_serve_port_file(root)
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception as e:
        return "warn", _t("setup_serve_fail", err=str(e))
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = _read_serve_port(root)
        if info is not None:
            actual_host = info.get("host") or host
            actual_port = int(info["port"])
            if _port_open(actual_host, actual_port):
                return "ok", _t(
                    "setup_serve", url=f"http://{actual_host}:{actual_port}"
                )
        time.sleep(0.4)
    # 超时：**不给**一个编造的端口 —— 实际端口未知就是未知。
    return "warn", _t("setup_serve_pending")


def _step_doctor(root: Path) -> tuple[str, str]:
    """跑一遍体检，输出 8 层防护状态。"""
    try:
        from pandaone.cmd_doctor import cmd_doctor, _collect_report
    except ImportError as e:
        return "skip", _t("setup_git_failed", err=str(e))
    args = SimpleNamespace(root=str(root))
    try:
        rc = cmd_doctor(args)
    except Exception as e:
        return "warn", _t("setup_git_failed", err=str(e))
    if rc == 0:
        return "ok", _t("setup_doctor", rc=rc)
    # v0.7.34.0 S6: exit 3 = 有防护层处于 fail 态（层坏了，不是安装失败）
    #   → 仍然是 warn（层失败不等于安装失败），但 note 里必须说清是**哪几层**失败，
    #   否则用户只看到 "exit=3" 一头雾水，不知道该去修哪一层。
    failed = []
    try:
        report = _collect_report(root)
        failed = list(report.get("failed_layers") or [])
    except Exception:
        failed = []
    if failed:
        return "warn", _t("setup_doctor_failed", layers=", ".join(failed), rc=rc)
    return "warn", _t("setup_doctor", rc=rc)


# ---------------------------------------------------------------------------
# 子命令注册
# ---------------------------------------------------------------------------

COMMAND_NAME = "setup"


def add_parser(sub) -> None:
    p = sub.add_parser(
        COMMAND_NAME,
        help="一键完成本地部署（依赖检测 → git 仓库 → 7 层防护 → 看门狗 → 右键菜单 → 仪表盘）",
    )
    p.add_argument("--root", default=".", help="项目根目录路径（默认当前目录）")
    p.add_argument(
        "--skip-git-install",
        action="store_true",
        help="git 缺失时不自动安装，只提示",
    )
    p.add_argument("--skip-watch", action="store_true", help="不启动看门狗")
    p.add_argument("--skip-context", action="store_true", help="不注册右键菜单")
    p.add_argument("--skip-serve", action="store_true", help="不启动仪表盘")
    p.add_argument(
        "--no-clean-conflicts",
        action="store_true",
        help="不清理 PATH 里抢占命令的旧版 pandaone（默认会改名备份）",
    )
    p.add_argument(
        "--min-python",
        default="3.8",
        help="最低 Python 版本要求（默认 3.8，与 pyproject requires-python 一致）",
    )


_STATUS_MARK = {"ok": "[OK]", "skip": "[SKIP]", "warn": "[WARN]", "fail": "[ERROR]"}


def handler(args) -> int:
    """setup 主流程。返回进程退出码。"""
    root = Path(getattr(args, "root", ".") or ".").resolve()
    min_py = _parse_min_python(getattr(args, "min_python", "3.8"))

    print(_t("setup_header", root=str(root)))

    steps = [
        ("Python", lambda: _step_python(min_py)),
        ("git", lambda: _step_git(not getattr(args, "skip_git_install", False))),
        ("PATH", lambda: persist_user_path(_executable_dir())),
        ("git 仓库", lambda: _step_git_repo(root)),
        ("Pandaone init", lambda: _step_init(root)),
    ]
    # PATH 冲突清理：机器级 PATH 里的旧 pip 版会抢占 `pandaone` 命令，
    # 光靠"用户级 PATH 前置"解决不了（实测），只能把旧的改名备份。
    if not getattr(args, "no_clean_conflicts", False):
        steps.append(("PATH 冲突", lambda: clean_path_conflicts()))
    if not getattr(args, "skip_watch", False):
        steps.append(("看门狗", lambda: _step_watch(root)))
    if not getattr(args, "skip_context", False):
        steps.append(("右键菜单", lambda: _step_context()))
    if not getattr(args, "skip_serve", False):
        steps.append(("仪表盘", lambda: _step_serve(root)))
    steps.append(("体检", lambda: _step_doctor(root)))

    total = len(steps)
    results = []
    for idx, (name, fn) in enumerate(steps, start=1):
        print(_t("setup_step", n=idx, total=total, name=name))
        try:
            status, msg = fn()
        except Exception as e:  # 单步失败不中断整体
            status, msg = "warn", f"{type(e).__name__}: {e}"
        results.append((name, status, msg))
        print(f"  {_STATUS_MARK.get(status, '[?]')} {msg}")

    print("")
    print(_t("setup_summary"))
    for name, status, _ in results:
        print(f"  {name}: {status}")
    print("")
    print(_t("setup_done"))

    failed = [r for r in results if r[1] == "fail"]
    return 1 if failed else 0
