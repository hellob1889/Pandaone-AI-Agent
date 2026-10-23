# -*- coding: utf-8 -*-
"""
cmd_upgrade.py — `pandaone upgrade`：一条命令完成升级

对应外部建议书「建议 1.3」。

为什么需要
----------
现在的升级流程是：
    pip install --upgrade pandaone-guard
    pandaone --update-fingerprint 0000      # ← 少了这步，整个 CLI 全废
第二步不能漏：漏了之后所有子命令全部 exit 1，连 `pandaone --version`
都看不到（指纹校验发生在 --version 分支之前）。用户看到的现象是
"命令坏了"，但完全不知道原因。

upgrade 做的事
--------------
    pip 升级 → 自动刷新指纹（版本号变更即合法变更，不当成"篡改"）
    → 重启看门狗 → 重启仪表盘 → 打印版本对比

指纹为什么能自动刷新
--------------------
指纹文件存的是 ``{version, hash}``。升级后版本号变了 → 指纹按
"版本感知"逻辑自动重算（不再需要手工 --update-fingerprint）。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def _t(key: str, **kw) -> str:
    try:
        from pandaone.i18n import t

        return t(key, **kw)
    except Exception:
        return key


COMMAND_NAME = "upgrade"


def add_parser(sub) -> None:
    p = sub.add_parser(
        COMMAND_NAME,
        help="一键升级（pip 升级 → 刷新指纹 → 重启看门狗 → 重启仪表盘）",
    )
    p.add_argument("--root", default=".", help="项目根目录路径（默认当前目录）")
    p.add_argument(
        "--check-only",
        action="store_true",
        help="只检查当前版本与 PyPI 最新版本，不实际升级",
    )
    p.add_argument(
        "--from-source",
        action="store_true",
        help="从本地源码升级（pip install -e .），而不是从 PyPI",
    )
    p.add_argument("--no-restart", action="store_true", help="不重启看门狗/仪表盘")
    p.add_argument(
        "--package",
        default="pandaone-guard",
        help="要升级的包名（默认 pandaone-guard）",
    )


def _current_version() -> str:
    try:
        from pandaone import __version__

        return __version__
    except Exception:
        return "unknown"


def _pip(args, timeout: int = 600):
    """跑 pip（用当前解释器，避免"装到了另一个 Python"）。"""
    cmd = [sys.executable, "-m", "pip"] + list(args)
    env = dict(os.environ)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"pip timed out: {' '.join(args)}") from e
    except Exception as e:
        raise RuntimeError(f"pip execution failed: {e}") from e


def _pypi_latest(package: str) -> str | None:
    """查 PyPI 上的最新版本（失败返回 None，不阻塞升级）。"""
    try:
        import json
        import urllib.request

        url = f"https://pypi.org/pypi/{package}/json"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("info", {}).get("version") or "") or None
    except Exception:
        return None


def _kill_pid(pid: int, timeout: float = 5.0) -> bool:
    """结束一个进程（跨平台）。"""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _stop_watchdog(root: Path) -> tuple[bool, str]:
    """停掉当前看门狗守护进程。"""
    pid_file = root / ".pandaone" / ".watchdog_pid"
    if not pid_file.is_file():
        return False, _t("upgrade_watch_not_running")
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False, _t("upgrade_watch_not_running")
    if pid <= 0:
        return False, _t("upgrade_watch_not_running")
    if not _kill_pid(pid):
        return False, _t("upgrade_watch_stop_fail", pid=pid)
    try:
        pid_file.unlink()
    except OSError:
        pass
    return True, _t("upgrade_watch_stopped", pid=pid)


def _start_watchdog(root: Path) -> tuple[bool, str]:
    """重新启动看门狗。"""
    try:
        from pandaone.cli import cmd_watch
    except Exception as e:
        return False, _t("upgrade_watch_start_fail", err=str(e))
    try:
        rc = cmd_watch(SimpleNamespace(root=str(root), daemon=True))
    except Exception as e:
        return False, _t("upgrade_watch_start_fail", err=str(e))
    if rc != 0:
        return False, _t("upgrade_watch_start_fail", err=f"exit={rc}")
    return True, _t("upgrade_watch_started")


def _pids_on_port(port: int) -> list[int]:
    """找监听指定端口的进程 PID（尽力而为，失败返回空）。"""
    pids: list[int] = []
    try:
        if sys.platform.startswith("win"):
            proc = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20
            )
            for line in proc.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.append(int(parts[-1]))
        else:
            proc = subprocess.run(
                ["lsof", "-t", f"-i:{port}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20
            )
            for line in proc.stdout.splitlines():
                if line.strip().isdigit():
                    pids.append(int(line.strip()))
    except Exception:
        pass
    return pids


def _restart_serve(root: Path) -> tuple[bool, str]:
    """重启仪表盘（尽力而为）。"""
    try:
        from pandaone.pandaone_serve import _find_free_port

        port = _find_free_port()
    except Exception:
        port = 8765
    stopped = False
    for pid in _pids_on_port(port):
        if _kill_pid(pid):
            stopped = True
    if not stopped:
        # 没找到在跑的仪表盘 —— 直接起一个新的
        pass
    cmd = [sys.executable, "-m", "pandaone", "serve", "--root", str(root)]
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs
        )
    except Exception as e:
        return False, _t("upgrade_serve_fail", err=str(e))
    url = f"http://127.0.0.1:{port}"
    for _ in range(25):
        time.sleep(0.4)
        try:
            import socket

            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True, _t("upgrade_serve_ok", url=url)
        except OSError:
            continue
    return True, _t("upgrade_serve_ok", url=url)


def handler(args) -> int:
    root = Path(getattr(args, "root", ".") or ".").resolve()
    package = getattr(args, "package", "pandaone-guard") or "pandaone-guard"

    before = _current_version()
    print(_t("upgrade_header", package=package))
    print(_t("upgrade_current", version=before))

    latest = _pypi_latest(package)
    if latest:
        print(_t("upgrade_latest", version=latest))
        if latest == before:
            print(_t("upgrade_already_latest"))
    else:
        print(_t("upgrade_latest_unknown"))

    if getattr(args, "check_only", False):
        print(_t("upgrade_check_only"))
        return 0

    print(_t("upgrade_pip_running"))
    try:
        if getattr(args, "from_source", False):
            proc = _pip(["install", "-e", "."])
        else:
            proc = _pip(["install", "--upgrade", package])
    except RuntimeError as e:
        print(_t("upgrade_pip_fail", err=str(e)))
        return 1
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        print(_t("upgrade_pip_fail", err=tail[-1] if tail else f"exit={proc.returncode}"))
        return 1
    print(_t("upgrade_pip_ok"))

    # 指纹：升级后版本号变了 → 下次运行会自动刷新（版本感知逻辑）。
    # 这里显式提示，避免用户以为还要手工 --update-fingerprint。
    print(_t("upgrade_fp_note"))

    after = _current_version()
    print(_t("upgrade_version_compare", before=before, after=after))
    if after != before:
        print(_t("upgrade_version_changed"))
    else:
        print(_t("upgrade_version_same"))

    if not getattr(args, "no_restart", False):
        stopped, msg = _stop_watchdog(root)
        print(f"  {msg}")
        if stopped:
            ok, msg = _start_watchdog(root)
            print(f"  {msg}")
        ok, msg = _restart_serve(root)
        print(f"  {msg}")

    print(_t("upgrade_done"))
    return 0


if __name__ == "__main__":
    sys.exit(0)
