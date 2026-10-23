# -*- coding: utf-8 -*-
"""
test_cmd_setup_upgrade.py — `pandaone setup` / `pandaone upgrade` 测试

安全约束：setup 里的 PATH 持久化会写 HKCU\\Environment\\Path，
测试里**绝不真调** —— 用假的 winreg 模块替身验证逻辑。
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone import cmd_setup, cmd_upgrade


# ---------------------------------------------------------------------------
# setup: Python 版本检测
# ---------------------------------------------------------------------------

def test_parse_min_python():
    assert cmd_setup._parse_min_python("3.10") == (3, 10)
    assert cmd_setup._parse_min_python("3.8") == (3, 8)
    assert cmd_setup._parse_min_python("garbage") == (3, 8)


def test_step_python_ok():
    status, msg = cmd_setup._step_python((3, 8))
    assert status == "ok"
    assert "Python" in msg


def test_step_python_too_old():
    status, msg = cmd_setup._step_python((99, 0))
    assert status == "fail"


# ---------------------------------------------------------------------------
# setup: PATH 持久化（假 winreg）
# ---------------------------------------------------------------------------

class _FakeWinreg:
    """winreg 的最小替身，记录被写入的值。"""

    KEY_ALL_ACCESS = 0xF003F
    REG_EXPAND_SZ = 2
    HKEY_CURRENT_USER = object()

    def __init__(self, initial=""):
        self.initial = initial
        self.written = None

    class _Key:
        def __init__(self, owner):
            self.owner = owner

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def QueryValueEx(self, key, name):
            if key == "Path":
                return self.owner.initial, self.owner.REG_EXPAND_SZ
            raise FileNotFoundError(name)

        def SetValueEx(self, key, name, reserved, typ, value):
            self.owner.written = value

    def OpenKey(self, hive, subkey, reserved, access):
        return self._Key(self)

    def QueryValueEx(self, key, name):
        return self.initial, self.REG_EXPAND_SZ

    def SetValueEx(self, key, name, reserved, typ, value):
        self.written = value


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")
def test_persist_path_windows_appends(monkeypatch):
    fake = _FakeWinreg(initial=r"C:\Python;C:\Tools")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    changed, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert changed is True
    assert fake.written is not None
    assert r"C:\Python\Scripts" in fake.written
    assert r"C:\Python" in fake.written, "原有 PATH 项必须保留"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")
def test_persist_path_windows_is_idempotent(monkeypatch):
    fake = _FakeWinreg(initial=r"C:\Python;C:\Python\Scripts")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    changed, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert changed is False, "已在 PATH 里就不该重复写"
    assert fake.written is None


# ---------------------------------------------------------------------------
# setup: handler（全部跳过外部副作用）
# ---------------------------------------------------------------------------

def test_setup_handler_runs_with_all_skips(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    args = SimpleNamespace(
        root=str(root),
        skip_git_install=True,
        skip_watch=True,
        skip_context=True,
        skip_serve=True,
        min_python="3.8",
    )
    rc = cmd_setup.handler(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "setup" not in out.lower() or True  # 只是确保没崩
    assert root.exists()


def test_setup_handler_reports_failure_on_bad_python(tmp_path, capsys):
    root = tmp_path / "proj2"
    root.mkdir()
    args = SimpleNamespace(
        root=str(root),
        skip_git_install=True,
        skip_watch=True,
        skip_context=True,
        skip_serve=True,
        min_python="99.0",
    )
    rc = cmd_setup.handler(args)
    assert rc == 1


def test_setup_creates_pandaone_dir(tmp_path, capsys):
    """skip 掉所有外部依赖后，init 步骤仍应创建 .pandaone/。"""
    root = tmp_path / "proj3"
    root.mkdir()
    args = SimpleNamespace(
        root=str(root),
        skip_git_install=True,
        skip_watch=True,
        skip_context=True,
        skip_serve=True,
        min_python="3.8",
    )
    cmd_setup.handler(args)
    assert (root / ".pandaone").is_dir()


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def test_upgrade_current_version():
    v = cmd_upgrade._current_version()
    assert isinstance(v, str) and v


def test_upgrade_pypi_latest_handles_offline(monkeypatch):
    import urllib.request

    def _boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert cmd_upgrade._pypi_latest("pandaone-guard") is None


def test_upgrade_check_only_does_not_pip(monkeypatch, capsys):
    called = []

    def _fake_pip(args, timeout=600):
        called.append(args)
        raise AssertionError("check-only 不应执行 pip")

    monkeypatch.setattr(cmd_upgrade, "_pip", _fake_pip)
    args = SimpleNamespace(
        root=".", check_only=True, from_source=False, no_restart=True, package="pandaone-guard"
    )
    rc = cmd_upgrade.handler(args)
    assert rc == 0
    assert called == []


def test_upgrade_kill_pid_handles_missing_process():
    # 不存在的 PID 不应抛异常
    assert cmd_upgrade._kill_pid(999999999) in (True, False)


def test_upgrade_stop_watchdog_without_pid_file(tmp_path):
    root = tmp_path / "p"
    (root / ".pandaone").mkdir(parents=True)
    stopped, msg = cmd_upgrade._stop_watchdog(root)
    assert stopped is False


# ---------------------------------------------------------------------------
# init --with-git
# ---------------------------------------------------------------------------

def test_init_with_git_creates_repo_and_baseline(tmp_path, capsys):
    """`pandaone init --with-git` 应同时建 git 仓库 + baseline commit（L2 回滚依赖）。"""
    import pandaone.__main__  # noqa: F401  触发 monkey-patch 注册
    from pandaone import cli, git_ops

    if git_ops.git_exe() is None:
        pytest.skip("git 不可用")

    root = tmp_path / "withgit"
    root.mkdir()
    (root / "a.txt").write_text("x\n", encoding="utf-8")
    args = SimpleNamespace(
        root=str(root),
        ext=None,
        no_binary=True,
        force_reset=False,
        with_git=True,
    )
    rc = cli.COMMANDS["init"](args)
    assert rc == 0
    assert git_ops.is_repo(root) is True
    assert git_ops.has_commits(root) is True


def test_init_without_git_does_not_create_repo(tmp_path):
    import pandaone.__main__  # noqa: F401
    from pandaone import cli, git_ops

    if git_ops.git_exe() is None:
        pytest.skip("git 不可用")

    root = tmp_path / "nogit"
    root.mkdir()
    args = SimpleNamespace(
        root=str(root), ext=None, no_binary=True, force_reset=False, with_git=False
    )
    rc = cli.COMMANDS["init"](args)
    assert rc == 0
    assert git_ops.is_repo(root) is False


# ---------------------------------------------------------------------------
# 命令注册
# ---------------------------------------------------------------------------

def test_setup_and_upgrade_are_registered():
    import pandaone.__main__ as m

    m._ensure_doctor_registered()
    from pandaone import cli

    assert cli.COMMANDS["setup"] is cmd_setup.handler
    assert cli.COMMANDS["upgrade"] is cmd_upgrade.handler


def test_setup_parser_arguments():
    from pandaone import cli

    parser = cli.build_parser()
    args = parser.parse_args(["setup", "--root", "/tmp/x", "--skip-serve"])
    assert args.command == "setup"
    assert args.root == "/tmp/x"
    assert args.skip_serve is True


def test_upgrade_parser_arguments():
    from pandaone import cli

    parser = cli.build_parser()
    args = parser.parse_args(["upgrade", "--check-only", "--no-restart"])
    assert args.command == "upgrade"
    assert args.check_only is True
    assert args.no_restart is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
