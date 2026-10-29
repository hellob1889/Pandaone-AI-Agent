# -*- coding: utf-8 -*-
"""
test_serve_port_coordination.py — serve 实际端口的落盘与调用方协调

背景（v0.7.34.1 修的真实缺陷）
--------------------------------
`pandaone setup` / `pandaone upgrade` 启动后台看板服务时，用的是**探测出来的
端口**（`_find_free_port()`：bind 完立刻 close），而服务实际监听的是**另一个
端口**（serve 有自己的默认端口，被占时还会**原子顺延**）：

  - setup:   轮询探测端口 → 12 秒空等 → 返回一个打不开的 URL
  - upgrade: 按探测端口 `_pids_on_port()` → `_kill_pid()`
             → 探测端口可能是**别的无关程序**在用 → **杀掉无关进程**

修复后的不变量（本文件逐条锁死）：
  1. serve 把**实际**端口写进 `<root>/.pandaone/serve_port.txt`
  2. 端口被占而顺延时，文件里记的是**顺延后**的端口，不是期望端口
  3. setup 读到 / 返回的是**实际**端口
  4. upgrade 没有端口文件时**一个进程都不杀**
  5. upgrade 有端口文件时，按**文件里记的端口**找进程，且只停 pid 对得上的
  6. setup / upgrade **再也不调用** `_find_free_port()`

注意：本文件**不断言中文文案**（CI 的系统语言可能是英文）——
      要断言消息内容时，把被测模块的 `_t` 换成"返回 key"的替身。
"""
import ast
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone import cmd_setup, cmd_upgrade, pandaone_serve


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _make_project(tmp_path, name="proj") -> Path:
    """造一个最小可 serve 的项目目录。"""
    root = tmp_path / name
    (root / ".pandaone").mkdir(parents=True)
    (root / ".pandaone" / "config.json").write_text("{}", encoding="utf-8")
    (root / ".pandaone" / "pandaone.jsonl").touch()
    return root


def _port_file(root: Path) -> Path:
    return root / ".pandaone" / pandaone_serve.SERVE_PORT_FILENAME


def _write_port_file(root: Path, port: int, pid=None, host="127.0.0.1",
                     version=None) -> Path:
    """手工造一个端口文件（模拟"上一次 serve 留下的"）。"""
    if version is None:
        version = pandaone_serve.SERVE_PORT_FILE_VERSION
    payload = {"version": version, "host": host, "port": port, "pid": pid}
    path = _port_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def _occupy_port():
    """占住一个端口（模拟"期望端口被别人用了"）。返回 (sock, port)。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def _url_port(msg: str):
    """从消息里抠出 URL 的端口（文案可能是中文也可能是英文）。"""
    m = re.search(r"http://([^:/]+):(\d+)", msg)
    assert m is not None, f"消息里没有 URL: {msg!r}"
    return m.group(1), int(m.group(2))


def _key_t(monkeypatch, module):
    """把模块的 `_t` 换成"返回 key"的替身 —— 与系统语言无关。"""
    monkeypatch.setattr(module, "_t", lambda key, **kw: key)


# ---------------------------------------------------------------------------
# serve 侧：端口文件
# ---------------------------------------------------------------------------

def test_start_server_writes_actual_port(tmp_path):
    """serve 写进端口文件的必须是**实际**监听端口（真起一个 server，不 mock）。"""
    root = _make_project(tmp_path)
    port = pandaone_serve._find_free_port(21300)
    server, monitor = pandaone_serve.start_server(root, port=port, open_browser=False)
    try:
        actual = server.server_address[1]
        info = pandaone_serve.read_serve_port(root)
        assert info is not None, "serve 启动后必须写端口文件"
        assert info["port"] == actual, f"文件里的端口 {info['port']} != 实际 {actual}"
        assert info["host"] == "127.0.0.1"
        assert info["pid"] == os.getpid()
        # 文件原文也要能读出端口 + 版本标记
        raw = json.loads(_port_file(root).read_text(encoding="utf-8"))
        assert raw["port"] == actual
        assert raw["version"] == pandaone_serve.SERVE_PORT_FILE_VERSION
    finally:
        monitor.stop()
        server.shutdown()
        server.server_close()


def test_start_server_writes_shifted_port_not_requested(tmp_path):
    """端口被占 → serve 原子顺延 → 文件里必须是**顺延后**的端口。"""
    root = _make_project(tmp_path)
    blocker, busy_port = _occupy_port()
    server = monitor = None
    try:
        server, monitor = pandaone_serve.start_server(
            root, port=busy_port, open_browser=False
        )
        actual = server.server_address[1]
        assert actual != busy_port, "被占用的端口不该被拿到"
        info = pandaone_serve.read_serve_port(root)
        assert info is not None
        assert info["port"] == actual, f"必须记顺延后的 {actual}，实际记了 {info['port']}"
        assert info["port"] != busy_port
    finally:
        if monitor is not None:
            monitor.stop()
        if server is not None:
            server.shutdown()
            server.server_close()
        blocker.close()


def test_start_server_overwrites_stale_port_file(tmp_path):
    """新服务启动必须**覆盖**旧端口文件（不能留着上一次的）。"""
    root = _make_project(tmp_path)
    _write_port_file(root, 21999, pid=999999)
    port = pandaone_serve._find_free_port(21400)
    server, monitor = pandaone_serve.start_server(root, port=port, open_browser=False)
    try:
        info = pandaone_serve.read_serve_port(root)
        assert info["port"] == server.server_address[1]
        assert info["pid"] == os.getpid(), "必须是**当前** serve 进程的 pid"
    finally:
        monitor.stop()
        server.shutdown()
        server.server_close()


def test_start_server_survives_port_file_write_failure(monkeypatch, tmp_path):
    """端口文件写失败**不能**影响 serve 正常启动。"""
    root = _make_project(tmp_path)
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        pandaone_serve,
        "serve_port_path",
        lambda r: blocker / "serve_port.txt",
    )
    port = pandaone_serve._find_free_port(21450)
    server, monitor = pandaone_serve.start_server(root, port=port, open_browser=False)
    try:
        assert server.server_address[1] == port, "写端口文件失败不该影响绑定"
        assert server.socket.fileno() != -1
    finally:
        monitor.stop()
        server.shutdown()
        server.server_close()


def test_read_serve_port_rejects_missing_corrupt_and_unknown_version(tmp_path):
    """读不到 / 损坏 / 版本不认识 → 一律返回 None（宁可不知道，也不能给错端口）。"""
    root = _make_project(tmp_path)
    assert pandaone_serve.read_serve_port(root) is None
    _port_file(root).write_text("not json at all", encoding="utf-8")
    assert pandaone_serve.read_serve_port(root) is None
    _write_port_file(root, 8765, pid=1,
                     version=pandaone_serve.SERVE_PORT_FILE_VERSION + 1)
    assert pandaone_serve.read_serve_port(root) is None, "不认识的版本必须当作没有端口信息"
    _write_port_file(root, 8765, pid=1)
    info = pandaone_serve.read_serve_port(root)
    assert info is not None
    assert info["port"] == 8765
    assert info["pid"] == 1


def test_clear_serve_port_only_deletes_own_pid(tmp_path):
    """清端口文件时**只删自己 pid 的那份**（同机可能有另一个 serve 实例）。"""
    root = _make_project(tmp_path)
    _write_port_file(root, 8765, pid=111)
    assert pandaone_serve.clear_serve_port(root, pid=222) is False
    assert _port_file(root).exists(), "别人的端口文件不能删"
    assert pandaone_serve.clear_serve_port(root, pid=111) is True
    assert not _port_file(root).exists()


# ---------------------------------------------------------------------------
# setup 侧
# ---------------------------------------------------------------------------

def test_step_serve_reports_actual_port_when_expected_busy(monkeypatch, tmp_path):
    """期望端口被占 → setup 必须报**实际**端口（顺延后的），不是期望端口。"""
    root = _make_project(tmp_path)
    blocker, busy_port = _occupy_port()
    holder = {}

    def _fake_popen(cmd, **kwargs):
        # 模拟真的 serve 起来：期望端口被占 → 原子顺延 → 写实际端口
        want = int(cmd[cmd.index("--port") + 1])

        def _run():
            srv, mon = pandaone_serve.start_server(
                root, port=want, open_browser=False
            )
            holder["server"] = srv
            holder["monitor"] = mon

        threading.Thread(target=_run, daemon=True).start()
        return SimpleNamespace()

    monkeypatch.setattr(cmd_setup, "SERVE_EXPECTED_PORT", busy_port)
    monkeypatch.setattr(cmd_setup.subprocess, "Popen", _fake_popen)
    try:
        status, msg = cmd_setup._step_serve(root, timeout=10.0)
    finally:
        blocker.close()

    assert status == "ok", msg
    actual = holder["server"].server_address[1]
    assert actual != busy_port
    host, port = _url_port(msg)
    assert port == actual, f"URL 端口必须是实际端口 {actual}，实际是 {port}"
    assert port != busy_port, f"URL 端口不能是期望端口 {busy_port}"


def test_step_serve_timeout_does_not_invent_a_port(monkeypatch, tmp_path):
    """超时文案**不能**编造端口（之前会返回探测端口的假 URL）。"""
    root = _make_project(tmp_path)
    captured = {}

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return SimpleNamespace()

    monkeypatch.setattr(cmd_setup.subprocess, "Popen", _fake_popen)
    _key_t(monkeypatch, cmd_setup)
    status, msg = cmd_setup._step_serve(root, timeout=0.6)
    assert status == "warn"
    assert msg == "setup_serve_pending"
    assert "http" not in msg, f"超时文案不该带 URL: {msg!r}"
    assert "--port" in captured["cmd"], "启动 serve 必须显式传 --port"


def test_step_serve_clears_stale_port_file(monkeypatch, tmp_path):
    """上一次残留的端口文件不能被当成本次服务的端口。"""
    root = _make_project(tmp_path)
    _write_port_file(root, 21987, pid=999999)
    captured = {}

    def _fake_popen(cmd, **kwargs):
        captured["port_file_exists"] = _port_file(root).exists()
        return SimpleNamespace()

    monkeypatch.setattr(cmd_setup.subprocess, "Popen", _fake_popen)
    _key_t(monkeypatch, cmd_setup)
    status, msg = cmd_setup._step_serve(root, timeout=0.6)
    assert captured["port_file_exists"] is False, "启动前必须清掉残留的端口文件"
    assert status == "warn"


# ---------------------------------------------------------------------------
# upgrade 侧
# ---------------------------------------------------------------------------

def test_restart_serve_without_port_file_kills_nothing(monkeypatch, tmp_path):
    """**没有**端口文件 → 一个进程都不能杀（绝不能按探测端口乱杀）。"""
    root = _make_project(tmp_path)
    killed = []
    monkeypatch.setattr(
        cmd_upgrade, "_kill_pid", lambda pid, **kw: killed.append(pid) or True
    )
    monkeypatch.setattr(cmd_upgrade.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    _key_t(monkeypatch, cmd_upgrade)
    ok, msg = cmd_upgrade._restart_serve(root, timeout=0.6)
    assert killed == [], f"没有端口文件时不应杀任何进程，实际杀了 {killed}"
    assert "upgrade_serve_no_port" in msg, msg


def test_restart_serve_kills_process_on_recorded_port(monkeypatch, tmp_path):
    """有端口文件 → 按**文件里记的端口**找进程，并停掉它。"""
    root = _make_project(tmp_path)
    recorded_port = 21555
    recorded_pid = 4242
    _write_port_file(root, recorded_port, pid=recorded_pid)
    asked = []
    killed = []

    def _fake_pids_on_port(port):
        asked.append(port)
        return [recorded_pid]

    monkeypatch.setattr(cmd_upgrade, "_pids_on_port", _fake_pids_on_port)
    monkeypatch.setattr(
        cmd_upgrade, "_kill_pid", lambda pid, **kw: killed.append(pid) or True
    )
    monkeypatch.setattr(cmd_upgrade.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    _key_t(monkeypatch, cmd_upgrade)
    ok, msg = cmd_upgrade._restart_serve(root, timeout=0.6)
    assert asked == [recorded_port], f"必须按文件里记的端口找进程: {asked}"
    assert killed == [recorded_pid], f"应该停掉端口文件记录的进程: {killed}"
    assert "upgrade_serve_stopped" in msg, msg


def test_restart_serve_does_not_kill_unrelated_process(monkeypatch, tmp_path):
    """端口上的监听进程**不是**我们的 serve → 绝不能杀。"""
    root = _make_project(tmp_path)
    recorded_port = 21556
    recorded_pid = 4242
    unrelated_pid = 9999
    _write_port_file(root, recorded_port, pid=recorded_pid)
    killed = []
    monkeypatch.setattr(cmd_upgrade, "_pids_on_port", lambda port: [unrelated_pid])
    monkeypatch.setattr(
        cmd_upgrade, "_kill_pid", lambda pid, **kw: killed.append(pid) or True
    )
    monkeypatch.setattr(cmd_upgrade.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    _key_t(monkeypatch, cmd_upgrade)
    ok, msg = cmd_upgrade._restart_serve(root, timeout=0.6)
    assert killed == [], f"不能停端口文件里没记的进程: {killed}"
    assert "upgrade_serve_no_owner" not in msg  # 文件里有 pid，不该报"无法确认归属"


def test_restart_serve_without_pid_in_file_kills_nothing(monkeypatch, tmp_path):
    """端口文件里没有 pid → 无法确认归属 → **不杀任何进程**。"""
    root = _make_project(tmp_path)
    _write_port_file(root, 21558, pid=None)
    killed = []
    monkeypatch.setattr(cmd_upgrade, "_pids_on_port", lambda port: [1234])
    monkeypatch.setattr(
        cmd_upgrade, "_kill_pid", lambda pid, **kw: killed.append(pid) or True
    )
    monkeypatch.setattr(cmd_upgrade.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    _key_t(monkeypatch, cmd_upgrade)
    ok, msg = cmd_upgrade._restart_serve(root, timeout=0.6)
    assert killed == [], f"无法确认归属时不应杀任何进程: {killed}"
    assert "upgrade_serve_no_owner" in msg, msg


def test_restart_serve_returns_new_actual_port(monkeypatch, tmp_path):
    """启动后等端口文件更新 → 返回**新**实际端口的 URL。"""
    root = _make_project(tmp_path)
    _write_port_file(root, 21557, pid=111)          # 旧服务
    new_sock, new_port = _occupy_port()             # 新服务监听的端口

    def _fake_popen(cmd, **kwargs):
        def _run():
            time.sleep(0.05)
            _write_port_file(root, new_port, pid=222)
        threading.Thread(target=_run, daemon=True).start()
        return SimpleNamespace()

    monkeypatch.setattr(cmd_upgrade, "_pids_on_port", lambda port: [])
    monkeypatch.setattr(cmd_upgrade.subprocess, "Popen", _fake_popen)
    ok, msg = cmd_upgrade._restart_serve(root, timeout=5.0)
    new_sock.close()
    host, port = _url_port(msg)
    assert port == new_port, f"必须返回新服务实际端口 {new_port}，实际 {port}"


# ---------------------------------------------------------------------------
# 核心不变量：_find_free_port 不得再被 setup / upgrade 调用
# ---------------------------------------------------------------------------

def test_setup_and_upgrade_never_call_find_free_port(monkeypatch, tmp_path):
    """核心不变量：setup / upgrade **不再**调用 _find_free_port()。"""

    def _boom(*a, **k):
        raise AssertionError("setup/upgrade 绝不能再调用 _find_free_port()")

    monkeypatch.setattr(pandaone_serve, "_find_free_port", _boom)
    root = _make_project(tmp_path)
    monkeypatch.setattr(cmd_setup.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(cmd_upgrade.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    _key_t(monkeypatch, cmd_setup)
    _key_t(monkeypatch, cmd_upgrade)
    cmd_setup._step_serve(root, timeout=0.6)
    cmd_upgrade._restart_serve(root, timeout=0.6)


def test_setup_and_upgrade_sources_do_not_reference_find_free_port():
    """源码级锁死（AST）：cmd_setup.py / cmd_upgrade.py 的**代码**里不得引用它。

    用 AST 而不是字符串匹配 —— 注释/文档字符串里可以写"以前用过它"，
    但**代码**里再出现就是回归。
    """
    for name in ("cmd_setup.py", "cmd_upgrade.py"):
        path = SRC / "pandaone" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "_find_free_port":
                pytest.fail(f"{name}:{node.lineno} 代码里仍在引用 _find_free_port")
            if isinstance(node, ast.Attribute) and node.attr == "_find_free_port":
                pytest.fail(f"{name}:{node.lineno} 代码里仍在引用 _find_free_port")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
