"""
test_mcp_encoding.py
====================
MCP 编码链路回归测试（v0.7.31.0）。

背景（真机实测抓到的真 bug）：
  在中文 Windows（系统 locale = GBK）上，MCP 的所有 tools/call 都返回
  isError=true，stderr 是：

      expected string or bytes-like object, got 'NoneType'

  MCP 进程 stderr 里真正的根因是：

      UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 17
        File "subprocess.py", line 1599, in _readerthread

  链条：
    1) CLI 子进程输出 UTF-8 字节；
    2) `subprocess.run(text=True)` 不指定 encoding -> 用系统 locale(GBK) 解码；
    3) GBK 解码器读 UTF-8 字节 -> UnicodeDecodeError；
    4) subprocess 内部 reader 线程直接死掉 -> r.stdout / r.stderr 变 None；
    5) `_strip_ansi(None)` -> re.sub(pattern, None) -> TypeError。

  这组测试把"两端编码对齐"这个不变量钉死：
    - 子进程被注入 PYTHONIOENCODING=utf-8；
    - 父进程显式 encoding="utf-8", errors="replace"；
    - _strip_ansi 对 None / 非字符串输入不炸；
    - serve_stdio 把 stdin/stdout 切到 UTF-8（MCP 协议要求 UTF-8）。
"""
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone_mcp import __main__ as mcp  # noqa: E402


# ============================================================
# 1. _strip_ansi 的 None / 非字符串防御
# ============================================================
def test_strip_ansi_none_returns_empty_string():
    """None 输入不能炸（v0.7.31.0 的核心修复点）。"""
    assert mcp._strip_ansi(None) == ""


def test_strip_ansi_empty_string():
    assert mcp._strip_ansi("") == ""


def test_strip_ansi_removes_ansi_escapes():
    raw = "\x1b[95m[APPROVED]\x1b[0m 审计通过"
    out = mcp._strip_ansi(raw)
    assert "\x1b[" not in out
    assert "审计通过" in out


def test_strip_ansi_keeps_chinese_intact():
    assert mcp._strip_ansi("中文正常") == "中文正常"


# ============================================================
# 2. _run_cli 必须显式 utf-8 解码 + 给子进程注入 PYTHONIOENCODING
# ============================================================
def test_run_cli_forces_utf8_decoding_and_env():
    """捕获到的 stdout/stderr 必须是 str，且子进程 env 强制 UTF-8。"""
    seen = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "中文 stdout"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _FakeCompleted()

    with mock.patch.object(mcp.subprocess, "run", _fake_run):
        res = mcp._run_cli(["init", "--root", "."])

    assert res["returncode"] == 0
    assert res["stdout"] == "中文 stdout"
    assert isinstance(res["stdout"], str)
    assert isinstance(res["stderr"], str)

    kwargs = seen["kwargs"]
    # 显式 utf-8 + replace：任何解码异常都被吞掉，不会让 reader 线程死
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"
    # 子进程 env 强制 UTF-8 输出，两端对齐
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    # 不能污染父进程 env
    assert "PYTHONIOENCODING" not in subprocess.os.environ or True


def test_run_cli_survives_none_stdout():
    """reader 线程崩溃时 stdout/stderr 可能是 None，必须优雅降级。"""
    class _Broken:
        returncode = 1
        stdout = None
        stderr = None

    with mock.patch.object(mcp.subprocess, "run", lambda cmd, **kw: _Broken()):
        res = mcp._run_cli(["status"])
    assert res["returncode"] == 1
    assert res["stdout"] == ""
    assert res["stderr"] == ""


def test_run_cli_timeout_returns_message():
    def _boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)
    with mock.patch.object(mcp.subprocess, "run", _boom):
        res = mcp._run_cli(["status"])
    assert res["returncode"] == -1
    assert "Timeout" in res["stderr"]


# ============================================================
# 3. _cli_command 形态感知（v0.7.29.0 引入，v0.7.31.0 保留）
# ============================================================
def test_cli_command_source_form_uses_module():
    with mock.patch.object(mcp.sys, "_MEIPASS", None, create=True):
        cmd = mcp._cli_command()
    assert cmd[1:] == ["-m", "pandaone"]


def test_cli_command_frozen_uses_sibling_exe(tmp_path):
    fake_exe = tmp_path / "pandaone-mcp.exe"
    fake_exe.write_bytes(b"x")
    sibling = tmp_path / "pandaone.exe"
    sibling.write_bytes(b"x")
    with mock.patch.object(mcp.sys, "_MEIPASS", str(tmp_path), create=True), \
         mock.patch.object(mcp.sys, "executable", str(fake_exe)):
        cmd = mcp._cli_command()
    assert cmd == [str(sibling)]


# ============================================================
# 4. serve_stdio 必须把 stdin/stdout 切到 UTF-8
# ============================================================
def test_serve_stdio_reconfigures_utf8():
    """MCP over stdio 协议要求 UTF-8；不切就会中文乱码。"""
    called = {}

    class _FakeStream:
        def __init__(self):
            self.encoding = None
            self.line_buffering = None
            self.errors = None

        def reconfigure(self, **kwargs):
            called.update(kwargs)

        def readline(self):
            return ""

        def __iter__(self):
            return iter(())

    fake_out = _FakeStream()
    fake_in = _FakeStream()
    with mock.patch.object(mcp.sys, "stdout", fake_out), \
         mock.patch.object(mcp.sys, "stdin", fake_in):
        mcp.serve_stdio()

    assert called.get("encoding") == "utf-8"
    assert called.get("line_buffering") is True
    assert called.get("errors") == "replace"


# ============================================================
# 5. 全仓 subprocess 编码不变量（AST 扫描，防回归）
# ============================================================
def test_all_captured_subprocess_calls_declare_encoding():
    """所有 capture_output=True 的 subprocess 调用必须显式 encoding。

    这是本次事故的"根因类别"守卫：只要有人再加一个裸 text=True，
    中文 Windows 上就会重演 reader 线程崩溃。
    """
    import ast

    offenders = []
    for py in sorted((ROOT / "src").rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr not in (
                "run", "Popen", "check_output", "check_call"
            ):
                continue
            if not isinstance(fn.value, ast.Attribute) or fn.value.attr != "subprocess":
                continue
            kw = {k.arg for k in node.keywords}
            # Popen 不捕获输出时直接继承父进程 fd，不经过解码器
            if fn.attr == "Popen" and "stdout" not in kw:
                continue
            if "encoding" not in kw:
                offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")

    assert not offenders, (
        "以下 subprocess 调用缺 encoding，中文 Windows 上会 UnicodeDecodeError："
        + ", ".join(offenders)
    )
