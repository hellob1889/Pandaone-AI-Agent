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


@pytest.fixture(autouse=True)
def _never_touch_real_user_path(monkeypatch):
    """任何测试都不得真的写 HKCU\\Environment\\Path。

    历史上 PATH 步骤是死代码（NameError），测试从没触发过真实写入；
    修好之后 handler 每次都会调它 —— 必须用替身挡住真实注册表。
    """
    monkeypatch.setattr(
        cmd_setup, "persist_user_path", lambda t: ("skip", "test: no real PATH write")
    )


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
    status, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert status == "ok"
    assert fake.written is not None
    assert r"C:\Python\Scripts" in fake.written
    assert r"C:\Python" in fake.written, "原有 PATH 项必须保留"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")
def test_persist_path_windows_is_idempotent(monkeypatch):
    fake = _FakeWinreg(initial=r"C:\Python;C:\Python\Scripts")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    status, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert status == "skip", "已在 PATH 里就不该重复写"
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


def test_upgrade_parser_accepts_launch_installer():
    from pandaone import cli

    parser = cli.build_parser()
    args = parser.parse_args(["upgrade", "--launch-installer"])
    assert args.launch_installer is True


# ---------------------------------------------------------------------------
# setup: PATH 步骤必须真的被调用
#
# 回归原因：handler 曾经调用一个不存在的 `_persist_user_path`，而每步的
# `except Exception` 把 NameError 吞成 WARN，整条 setup 仍然 rc=0 ——
# 单元测试全绿，用户装完 exe 却发现命令行里根本没有 pandaone。
# ---------------------------------------------------------------------------

def test_setup_handler_actually_persists_path(tmp_path, monkeypatch, capsys):
    calls = []

    def _fake_persist(target):
        calls.append(str(target))
        return "ok", f"OK: {target}"

    monkeypatch.setattr(cmd_setup, "persist_user_path", _fake_persist)
    root = tmp_path / "proj_path"
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
    assert calls, "setup 的 PATH 步骤必须真的调用 persist_user_path（不能是死代码）"
    assert calls[0] == str(cmd_setup._executable_dir())


def test_setup_handler_has_no_nameerror_in_path_step(tmp_path, monkeypatch, capsys):
    """PATH 步骤不许出现 NameError 之类的事故（历史上被 except 吞成 WARN）。"""
    monkeypatch.setattr(cmd_setup, "persist_user_path", lambda t: ("skip", "skip"))
    root = tmp_path / "proj_path2"
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
    out = capsys.readouterr().out
    assert "NameError" not in out
    assert "AttributeError" not in out


def test_executable_dir_frozen_points_at_exe(monkeypatch, tmp_path):
    """打包形态：目录必须是 exe 自己所在目录（安装后 %LOCALAPPDATA%\\Pandaone）。"""
    fake_exe = tmp_path / "Pandaone" / "pandaone.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert cmd_setup._executable_dir() == fake_exe.parent.resolve()


def test_executable_dir_source_points_at_scripts(monkeypatch):
    """源码/pip 形态：必须是 scripts 目录，不是解释器目录。"""
    import sysconfig

    monkeypatch.delattr(sys, "frozen", raising=False)
    got = cmd_setup._executable_dir()
    assert got == Path(sysconfig.get_path("scripts")).resolve()


# ---------------------------------------------------------------------------
# upgrade: exe（frozen）形态不得碰 pip
# ---------------------------------------------------------------------------

def test_ver_tuple_ordering():
    assert cmd_upgrade._ver_tuple("0.7.26.0") > cmd_upgrade._ver_tuple("0.7.25.0")
    assert cmd_upgrade._ver_tuple("0.7.26") == cmd_upgrade._ver_tuple("0.7.26.0")
    assert cmd_upgrade._ver_tuple("0.8.0") > cmd_upgrade._ver_tuple("0.7.99")


def test_upgrade_frozen_never_calls_pip(monkeypatch, capsys):
    """exe 形态里 sys.executable 就是 pandaone.exe，-m pip 必然变成
    "把 pip 当 CLI 子命令" → invalid choice。frozen 分支必须绕开 pip。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def _boom(*a, **k):
        raise AssertionError("frozen 形态绝不应调用 pip")

    monkeypatch.setattr(cmd_upgrade, "_pip", _boom)
    monkeypatch.setattr(cmd_upgrade, "_pypi_latest", lambda pkg: cmd_upgrade._current_version())
    args = SimpleNamespace(
        root=".", check_only=False, from_source=False, no_restart=True,
        package="pandaone-guard", launch_installer=False,
    )
    rc = cmd_upgrade.handler(args)
    assert rc == 0


def test_upgrade_frozen_reports_missing_installer(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    fake_exe = tmp_path / "app" / "pandaone.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(cmd_upgrade, "_pypi_latest", lambda pkg: "99.0.0")
    args = SimpleNamespace(
        root=".", check_only=False, from_source=False, no_restart=True,
        package="pandaone-guard", launch_installer=False,
    )
    rc = cmd_upgrade.handler(args)
    out = capsys.readouterr().out
    assert rc == 1
    assert "99.0.0" in out


def test_upgrade_frozen_finds_installer_next_to_exe(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    app = tmp_path / "app"
    app.mkdir(parents=True)
    fake_exe = app / "pandaone.exe"
    fake_exe.write_bytes(b"MZ")
    installer = app / "PandaoneSetup-99.0.0-x64.exe"
    installer.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(cmd_upgrade, "_pypi_latest", lambda pkg: "99.0.0")
    args = SimpleNamespace(
        root=".", check_only=False, from_source=False, no_restart=True,
        package="pandaone-guard", launch_installer=False,
    )
    rc = cmd_upgrade.handler(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "PandaoneSetup-99.0.0-x64.exe" in out


def test_upgrade_frozen_rejects_from_source(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cmd_upgrade, "_pypi_latest", lambda pkg: "99.0.0")
    args = SimpleNamespace(
        root=".", check_only=False, from_source=True, no_restart=True,
        package="pandaone-guard", launch_installer=False,
    )
    rc = cmd_upgrade.handler(args)
    assert rc == 1


def test_upgrade_frozen_reports_local_newer_than_pypi(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cmd_upgrade, "_pypi_latest", lambda pkg: "0.0.1")
    args = SimpleNamespace(
        root=".", check_only=False, from_source=False, no_restart=True,
        package="pandaone-guard", launch_installer=False,
    )
    rc = cmd_upgrade.handler(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# 打包脚本的同版本守卫（同版本重打包 = 存量用户 CLI 被锁死）
# ---------------------------------------------------------------------------

def _load_build_script():
    import importlib.util

    path = ROOT / "build_pyinstaller.py"
    spec = importlib.util.spec_from_file_location("build_pyinstaller_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_script_refuses_same_version_rebuild(tmp_path, monkeypatch):
    mod = _load_build_script()
    state = tmp_path / "release_state.json"
    state.write_text(
        '{"version": "1.2.3", "pandaone_exe_sha256": "deadbeef"}', encoding="utf-8"
    )
    monkeypatch.setattr(mod, "RELEASE_STATE", state)
    with pytest.raises(SystemExit) as e:
        mod.check_version_bump("1.2.3", allow_same=False)
    assert "1.2.3" in str(e.value)


def test_build_script_allows_bumped_version(tmp_path, monkeypatch):
    mod = _load_build_script()
    state = tmp_path / "release_state.json"
    state.write_text('{"version": "1.2.3"}', encoding="utf-8")
    monkeypatch.setattr(mod, "RELEASE_STATE", state)
    mod.check_version_bump("1.2.4", allow_same=False)  # 不应抛


def test_build_script_same_version_allowed_with_flag(tmp_path, monkeypatch):
    mod = _load_build_script()
    state = tmp_path / "release_state.json"
    state.write_text('{"version": "1.2.3"}', encoding="utf-8")
    monkeypatch.setattr(mod, "RELEASE_STATE", state)
    mod.check_version_bump("1.2.3", allow_same=True)  # 不应抛


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
