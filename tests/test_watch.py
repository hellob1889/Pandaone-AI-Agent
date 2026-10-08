"""
test_watch.py
=============
RED 测试：pandaone watch 命令

第一性原理：
  watch 是 watchdog 的"用户入口"。
  - --daemon：后台启动，立即返回
  - 默认：前台运行，Ctrl+C 停止

测试策略：
  - watch 子命令存在
  - watch --daemon 启动后立即返回 + 写 PID 文件
  - watch --daemon 启动的进程可被检测到（PID 存在）
"""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANDAX = ROOT / "pandaone_dev.py"


def run(args: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess:
    # Bug fix (v0.7.15) F-07: errors="replace" 防止 watchdog 在 Windows GBK 编码下
    # 输出非 UTF-8 字节 (0xcf 等) 时 UnicodeDecodeError → check.stdout=None → TypeError
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=kw.pop("timeout", 15), **kw,
    )


def setup(tmp_path: Path) -> Path:
    """建项目"""
    r = run(["init", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0
    return tmp_path


def kill_watchdog(pid_path: Path):
    """清理 watchdog 进程"""
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
            else:
                os.kill(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError, OSError):
            pass
        try:
            pid_path.unlink()
        except OSError:
            pass


def test_watch_subcommand_exists():
    """watch 子命令存在"""
    r = subprocess.run(
        [sys.executable, str(PANDAX), "--help"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert "watch" in r.stdout


def test_watch_daemon_writes_pid(tmp_path):
    """watch --daemon 应后台启动并写 PID"""
    setup(tmp_path)
    pid_path = tmp_path / ".pandaone" / ".watchdog_pid"

    # 清理可能残留的
    kill_watchdog(pid_path)

    # PATH 探测 git
    env = os.environ.copy()
    if shutil.which("git"):
        env["PATH"] = os.environ["PATH"]

    try:
        r = subprocess.run(
            [sys.executable, str(PANDAX), "watch", "--root", str(tmp_path), "--daemon"],
            cwd=str(tmp_path), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=20, env=env,
        )
        # 应快速返回（rc=0）
        assert r.returncode == 0, f"stderr={r.stderr}"
        # 应输出 PID 信息
        assert "PID" in r.stdout or "watchdog" in r.stdout.lower()

        # PID 文件应被创建
        assert pid_path.exists(), f"PID 文件未创建: {pid_path}"
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        assert pid > 0

        # 进程应真实存在
        time.sleep(0.5)
        if sys.platform == "win32":
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5,
            )
            assert str(pid) in check.stdout, f"watchdog 进程 {pid} 不存在"

    finally:
        kill_watchdog(pid_path)


def test_watch_daemon_creates_log(tmp_path):
    """watch --daemon 应写日志"""
    setup(tmp_path)
    pid_path = tmp_path / ".pandaone" / ".watchdog_pid"

    kill_watchdog(pid_path)

    try:
        r = subprocess.run(
            [sys.executable, str(PANDAX), "watch", "--root", str(tmp_path), "--daemon"],
            cwd=str(tmp_path), capture_output=True, text=True, timeout=20,
        )
        assert r.returncode == 0

        # 给 watchdog 时间写
        time.sleep(1)

        log_path = tmp_path / ".pandaone" / "watchdog.log"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8")
            assert "watchdog" in content.lower()
    finally:
        kill_watchdog(pid_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
