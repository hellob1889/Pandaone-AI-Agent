# -*- coding: utf-8 -*-
"""
test_health_probe_alignment.py — status / doctor 判据同源 + 故障注入
============================================================================

为什么必须有这个文件
--------------------
`pandaone status` 与 `pandaone doctor` 回答同一组问题（L1 锁 / L2 看门狗 /
L5 指纹 / L6 审计），但历史上**各写各的判据**，已经漂移过三次：

  1. status 的 L1 传空 config → ``config.get("protected_extensions", [".py"])``
     永远拿到默认的 ``[".py"]`` → 631 个受保护文件在仪表盘上完全不可见。
  2. status 的 L2 只查 PID 存活 → 看门狗被强杀后 PID 残留，PID 被系统回收
     复用 → 别的进程拿到同一个 PID → **假绿**。
  3. status 的 L5 直接比 hash、丢掉 form → pip 版与 exe 版共存（合法部署行为）
     时误报"不匹配"。

v0.7.35 的修法不是"再同步一次"，而是把判据下沉到 ``pandaone.health_probe``，
两个命令都从那里取。本文件守住这条不变式。

本文件的核心原则（沿用项目既有门禁理念）：
  **测试通过不算数，要能失败** —— 每一个用例都必须先把环境**弄坏**，
  再断言对应层真的报 FAIL / 退出码非 0。绿而不坏的用例等于没测。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from pandaone import cmd_doctor as _doc  # noqa: E402
from pandaone import health_probe as _hp  # noqa: E402
from pandaone import cli as _cli  # noqa: E402


# ============================================================
# 辅助
# ============================================================

def _init_project(root):
    """用**真实**的 `pandaone init` 建一个项目（不是手工拼 config.json）。"""
    args = SimpleNamespace(root=str(root), ext=None, no_binary=False)
    assert _cli.cmd_init(args) == 0
    return root


def _status(root, capsys=None):
    """跑 cmd_status，返回 (rc, stdout)。"""
    rc = _cli.cmd_status(SimpleNamespace(root=str(root), lang="zh-CN"))
    if capsys is None:
        return rc, ""
    return rc, capsys.readouterr().out


def _number_after(out, label):
    """从 status 输出里取某个标签后面的整数（如 "总受保护文件: 3"）。"""
    for line in out.splitlines():
        if label in line:
            tail = line.split(":", 1)[-1]
            digits = "".join(ch if ch.isdigit() else " " for ch in tail).split()
            if digits:
                return int(digits[0])
    return None


def _spawn_unrelated_process():
    """起一个**明确不是 pandaone** 的长驻进程（用来复现 PID 复用假绿）。

    进程名不能是 python* —— health_probe 对 python 系列的判定是
    "unknown"（源码形态下看门狗就是 python.exe，分不出来），那不会判 FAIL。
    """
    if sys.platform.startswith("win"):
        return subprocess.Popen(
            ["cmd.exe", "/c", "ping -t 127.0.0.1 > nul"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    return subprocess.Popen(
        ["sleep", "30"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ============================================================
# 1. 同源不变式 —— status 与 doctor 必须给出同一个结论
# ============================================================

class TestSameSourceOfTruth:
    """status / doctor 的同层判定必须一致（这是"不再漂移"的守门测试）。"""

    def test_l1_same_verdict(self, tmp_path):
        p = _init_project(tmp_path)
        (p / "a.py").write_text("x = 1\n", encoding="utf-8")
        probe = _hp.file_lock_state(p)
        doc = _doc._check_layer1_file_lock(p)
        assert probe["state"] == "na"          # 没跑过 lock → 未启用
        assert doc.get("na") is True

    def test_l1_same_verdict_after_break(self, tmp_path):
        """把锁弄坏（文件又可写）→ 两个命令都要报 fail。"""
        p = _init_project(tmp_path)
        (p / "a.py").write_text("x = 1\n", encoding="utf-8")
        (p / ".pandaone" / "lock_modes.json").write_text("{}", encoding="utf-8")
        probe = _hp.file_lock_state(p)
        doc = _doc._check_layer1_file_lock(p)
        assert probe["state"] == "fail"
        assert doc["ok"] is False
        assert "writable" in doc["note"]

    def test_l2_same_verdict(self, tmp_path):
        p = _init_project(tmp_path)
        probe = _hp.watchdog_state(p)
        doc = _doc._check_layer2_watchdog(p)
        assert probe["state"] == "na"          # 从没跑过看门狗 → 未启用
        assert doc.get("na") is True

    def test_l6_same_verdict(self, tmp_path):
        p = _init_project(tmp_path)
        (p / ".pandaone" / "pandaone.jsonl").write_text(
            json.dumps({"id": "a1", "status": "UNAUTHORIZED", "file": "a.py"}) + "\n",
            encoding="utf-8",
        )
        probe = _hp.audit_state(p)
        doc = _doc._check_layer6_tamper_detection(p)
        assert probe["state"] == "fail"
        assert doc["ok"] is False
        assert "UNAUTHORIZED" in doc["note"]


# ============================================================
# 2. L1 —— status 终于能看到全部受保护文件（历史 bug）
# ============================================================

class TestStatusL1CountsEverything:
    """status 原来只数 .py（传空 config）—— 631 个文件在仪表盘上不可见。"""

    def test_status_counts_non_py_protected_files(self, tmp_path, capsys):
        p = _init_project(tmp_path)
        (p / "a.py").write_text("x = 1\n", encoding="utf-8")
        (p / "b.json").write_text("{}\n", encoding="utf-8")
        (p / "c.yaml").write_text("k: v\n", encoding="utf-8")
        rc, out = _status(p, capsys)
        n = _number_after(out, "总受保护文件")
        assert n is not None, out
        assert n >= 3, f"status 只数到 {n} 个受保护文件（应含 .py/.json/.yaml）:\n{out}"
        # doctor 与 status 必须数出同一个数
        probe = _hp.file_lock_state(p)
        assert probe["total"] == n

    def test_status_l1_fails_when_lock_broken(self, tmp_path, capsys):
        """跑过 lock、后来文件又可写了 → status 必须报 FAIL 且退出码非 0。"""
        p = _init_project(tmp_path)
        (p / "a.py").write_text("x = 1\n", encoding="utf-8")
        (p / ".pandaone" / "lock_modes.json").write_text("{}", encoding="utf-8")
        # 制造故障：文件可写（等价于锁被解除）
        os.chmod(p / "a.py", 0o644)
        rc, out = _status(p, capsys)
        assert rc == 3, f"层失败时 status 必须退出 3，实际 {rc}:\n{out}"
        assert "[FAIL]" in out
        assert "未锁定" in out or "writable" in out


# ============================================================
# 3. L2 —— PID 复用假绿（故障注入：真的起一个别的进程）
# ============================================================

class TestWatchdogPidReuse:
    """status 原来只查"PID 还活着" → PID 被系统回收复用后假绿。"""

    def test_reused_pid_is_detected(self, tmp_path):
        """PID 指向一个明确不是 pandaone 的进程 → 必须判 fail。"""
        p = _init_project(tmp_path)
        proc = _spawn_unrelated_process()
        try:
            (p / ".pandaone" / ".watchdog_pid").write_text(
                str(proc.pid), encoding="utf-8")
            (p / ".pandaone" / "watchdog.log").write_text("", encoding="utf-8")
            probe = _hp.watchdog_state(p)
            assert probe["state"] == "fail", probe
            assert "reused" in probe["note"]
        finally:
            proc.kill()
            proc.wait(timeout=10)

    def test_reused_pid_fails_status_and_doctor(self, tmp_path, capsys):
        p = _init_project(tmp_path)
        proc = _spawn_unrelated_process()
        try:
            (p / ".pandaone" / ".watchdog_pid").write_text(
                str(proc.pid), encoding="utf-8")
            (p / ".pandaone" / "watchdog.log").write_text("", encoding="utf-8")
            rc, out = _status(p, capsys)
            assert rc == 3, f"PID 复用时 status 必须退出 3，实际 {rc}:\n{out}"
            assert "[FAIL]" in out
            doc = _doc._check_layer2_watchdog(p)
            assert doc["ok"] is False
            assert "reused" in doc["note"]
        finally:
            proc.kill()
            proc.wait(timeout=10)

    def test_dead_pid_is_not_reported_as_running(self, tmp_path, capsys):
        """PID 文件在、进程已经没了 → 绝不能报"运行中"（那是假绿）。"""
        p = _init_project(tmp_path)
        (p / ".pandaone" / ".watchdog_pid").write_text("999999", encoding="utf-8")
        (p / ".pandaone" / "watchdog.log").write_text("", encoding="utf-8")
        probe = _hp.watchdog_state(p)
        assert probe["state"] == "fail", probe
        rc, out = _status(p, capsys)
        assert rc == 3
        assert "运行中" not in out, f"死掉的看门狗被报成运行中:\n{out}"

    def test_never_started_is_na_not_fail(self, tmp_path, capsys):
        """从没跑过看门狗 = 未启用 → 不是失败，退出码仍为 0。"""
        p = _init_project(tmp_path)
        rc, out = _status(p, capsys)
        assert rc == 0, f"未启用不该让 status 变红:\n{out}"


# ============================================================
# 4. L5 —— 自指纹三态
# ============================================================

class TestFingerprintStates:
    def _write_fp(self, tmp_path, monkeypatch, *, form, version, digest):
        from pandaone import fp_security as _fpsec
        fp = tmp_path / "fp.txt"
        fp.write_text(json.dumps({
            "version": version, "hash": digest, "form": form,
            "stored_at": "2026-01-01T00:00:00Z",
        }), encoding="utf-8")
        monkeypatch.setattr(_cli, "FP_PATH", fp)
        monkeypatch.setattr(_fpsec, "fp_form", lambda: form)

    def test_tampered_fingerprint_fails_status_and_doctor(self, tmp_path, monkeypatch, capsys):
        """同版本同形态、hash 变了 = 真篡改 → 两个命令都要报 FAIL。"""
        p = _init_project(tmp_path)
        version = _cli._get_pandaone_version()
        self._write_fp(tmp_path, monkeypatch, form="source",
                       version=version, digest="deadbeef")
        probe = _hp.fingerprint_state()
        assert probe["state"] == "fail", probe
        assert "TAMPERED" in probe["note"]
        doc = _doc._check_layer5_self_fingerprint(p)
        assert doc["ok"] is False
        assert "TAMPERED" in doc["note"]
        rc, out = _status(p, capsys)
        assert rc == 3, f"指纹被篡改时 status 必须退出 3，实际 {rc}:\n{out}"
        assert "TAMPERED" in out

    def test_form_switch_is_warn_not_fail(self, tmp_path, monkeypatch, capsys):
        """pip 版与 exe 版共存是合法部署行为 → 只 WARN，不报篡改。"""
        p = _init_project(tmp_path)
        version = _cli._get_pandaone_version()
        self._write_fp(tmp_path, monkeypatch, form="source",
                       version=version, digest="deadbeef")
        from pandaone import fp_security as _fpsec
        monkeypatch.setattr(_fpsec, "fp_form", lambda: "frozen")
        probe = _hp.fingerprint_state()
        assert probe["state"] == "warn", probe
        doc = _doc._check_layer5_self_fingerprint(p)
        assert doc["ok"] is True
        assert doc.get("warn") is True
        rc, out = _status(p, capsys)
        assert rc == 0, f"形态切换不该让 status 变红:\n{out}"

    def test_missing_fingerprint_is_fail(self, tmp_path, monkeypatch):
        """删掉指纹文件绕过自检 = 基线缺失 → fail（不是"首次运行"）。"""
        from pandaone import fp_security as _fpsec
        monkeypatch.setattr(_cli, "FP_PATH", tmp_path / "absent_fp.txt")
        monkeypatch.setattr(_fpsec, "fp_form", lambda: "source")
        probe = _hp.fingerprint_state()
        assert probe["state"] == "fail", probe
        assert "baseline missing" in probe["note"]


# ============================================================
# 5. install_hook —— 不许谎报"已复制"
# ============================================================

class TestInstallHookNoLying:
    def _git_project(self, tmp_path):
        (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_missing_dependency_fails_without_claiming_success(self, tmp_path, monkeypatch, capsys):
        """模板/依赖缺失 → 必须 return 1，且**不能**打印"已复制"。"""
        from pandaone import install_hook as _ih
        p = self._git_project(tmp_path)
        monkeypatch.setattr(_ih, "CHECK_SCRIPT", tmp_path / "missing-check.py")
        rc = _ih.install_hook(p)
        out = capsys.readouterr().out
        assert rc == 1, f"依赖缺失时必须失败，实际 rc={rc}:\n{out}"
        assert "已复制" not in out, f"没复制却宣称已复制:\n{out}"

    def test_copy_error_fails_without_claiming_success(self, tmp_path, monkeypatch, capsys):
        """复制过程抛 OSError → 必须 return 1，且**不能**打印"已复制"。"""
        from pandaone import install_hook as _ih
        p = self._git_project(tmp_path)

        real_copy = shutil.copy

        def boom(src, dst, *a, **kw):
            raise OSError("disk full")

        class _FakeShutil:
            copy = staticmethod(boom)
            which = staticmethod(shutil.which)

        monkeypatch.setattr(_ih, "shutil", _FakeShutil)
        rc = _ih.install_hook(p)
        out = capsys.readouterr().out
        assert rc == 1, f"复制失败时必须失败，实际 rc={rc}:\n{out}"
        assert "已复制" not in out, f"没复制却宣称已复制:\n{out}"
        assert "复制失败" in out

    def test_success_prints_copied_once_each(self, tmp_path, monkeypatch, capsys):
        """正常路径：两个依赖文件都真的复制成功 → 才打印"已复制"。"""
        from pandaone import install_hook as _ih
        p = self._git_project(tmp_path)
        rc = _ih.install_hook(p)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert (p / ".pandaone" / "pre-commit-check.py").exists()
        assert (p / ".pandaone" / "audit_binding.py").exists()
        assert "已复制" in out


# ============================================================
# 6. 反向验证 —— 修好之后坏状态仍然要报错
# ============================================================

class TestRegressionGuard:
    """守住"这次修好了"而不是"这次把检查关掉了"。"""

    def test_health_probe_is_actually_used_by_status(self):
        """status 的 L1 必须走 health_probe（不是自己又写了一遍）。"""
        import inspect
        src = inspect.getsource(_cli.cmd_status)
        assert "health_probe" in src, "status 没有走共享判据 —— 漂移会重新长出来"

    def test_health_probe_is_actually_used_by_doctor(self):
        """doctor 的 L1/L2/L5/L6 必须走 health_probe。"""
        import inspect
        for fn in (_doc._check_layer1_file_lock, _doc._check_layer2_watchdog,
                   _doc._check_layer5_self_fingerprint, _doc._check_layer6_tamper_detection):
            src = inspect.getsource(fn)
            assert "_hp." in src, f"{fn.__name__} 没有走共享判据"

    def test_protected_file_enumeration_is_shared(self):
        """cli 的 _iter_protected_files 与 health_probe 必须同源。"""
        import inspect
        src = inspect.getsource(_cli._iter_protected_files)
        assert "health_probe" in src, "_iter_protected_files 没有转发到共享枚举"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
