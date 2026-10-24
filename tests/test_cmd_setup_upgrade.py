# -*- coding: utf-8 -*-
"""
test_cmd_setup_upgrade.py — `pandaone setup` / `pandaone upgrade` 测试

安全约束：setup 里的 PATH 持久化会写 HKCU\\Environment\\Path，
测试里**绝不真调** —— 用假的 winreg 模块替身验证逻辑。
"""
import sys
import os
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
def test_persist_path_windows_prepends(monkeypatch):
    r"""v0.7.27.0: PATH 必须**前置**而非追加。

    背景：pip 版 pandaone 装在 Python\Scripts\，通常排在用户 PATH 靠前。
    追加的话，装完 exe 版后 `pandaone` 仍命中旧 pip 版 -> 体感"装了没生效"。
    """
    fake = _FakeWinreg(initial=r"C:\Python;C:\Tools")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    status, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert status == "ok"
    assert fake.written is not None
    parts = fake.written.split(";")
    assert parts[0] == r"C:\Python\Scripts", "新目录必须在 PATH 首位"
    assert r"C:\Python" in parts, "原有 PATH 项必须保留"
    assert r"C:\Tools" in parts, "原有 PATH 项必须保留"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")
def test_persist_path_windows_moves_existing_to_front(monkeypatch):
    """已存在但排在中间 -> 前移到首位，且不出现重复项。"""
    fake = _FakeWinreg(initial=r"C:\Python;C:\Tools;C:\Python\Scripts")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    status, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert status == "ok"
    parts = fake.written.split(";")
    assert parts[0] == r"C:\Python\Scripts", "已存在的目录要前移到首位"
    assert parts.count(r"C:\Python\Scripts") == 1, "不能出现重复项"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")
def test_persist_path_windows_dedupes_case_insensitive(monkeypatch):
    """大小写 / 尾部反斜杠差异也算同一条，不能重复写入。"""
    fake = _FakeWinreg(initial=r"C:\Python;C:\python\scripts\;C:\Tools")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    status, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert status == "ok"
    parts = fake.written.split(";")
    assert parts[0] == r"C:\Python\Scripts"
    assert len([p for p in parts if p.lower().rstrip("\\") == r"c:\python\scripts"]) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")
def test_persist_path_windows_is_idempotent(monkeypatch):
    """已经在首位 -> skip，不再写注册表。"""
    fake = _FakeWinreg(initial=r"C:\Python\Scripts;C:\Python")
    monkeypatch.setitem(sys.modules, "winreg", fake)
    status, msg = cmd_setup._persist_path_windows(r"C:\Python\Scripts")
    assert status == "skip", "已在 PATH 首位就不该重复写"
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


# ---------------------------------------------------------------------------
# 安装器模板（codeaudit.iss）：PATH 必须前置 + 卸载要清理
# ---------------------------------------------------------------------------

def _read_iss_template() -> str:
    p = ROOT / "src" / "pandaone" / "installer" / "codeaudit.iss"
    assert p.exists(), f"安装器模板缺失: {p}"
    return p.read_text(encoding="utf-8")


def test_iss_path_is_prepended_not_appended():
    """v0.7.27.0: 安装器把 {app} 前置到 PATH 首位。

    追加（`{olddata};{app}`）会让 pip 版 pandaone 继续抢占 `pandaone` 命令，
    装完 exe 版却像"没生效" —— 这里锁死前置语义，防止改回去。
    """
    text = _read_iss_template()
    path_lines = [
        ln for ln in text.splitlines()
        if 'ValueName: "Path"' in ln
    ]
    assert path_lines, "安装器模板里找不到 PATH 的 Registry 行"
    for ln in path_lines:
        assert "{app};{olddata}" in ln, f"PATH 必须是前置语义，实际: {ln.strip()}"
        assert "{olddata};{app}" not in ln, "不能把 {app} 追加到 PATH 末尾"


def test_iss_has_uninstall_path_cleanup():
    """卸载时要把 {app} 从 PATH 摘掉，否则留下指向已删目录的坏路径。"""
    text = _read_iss_template()
    assert "procedure RemoveAppFromPath" in text
    assert "procedure CurUninstallStepChanged" in text
    assert "usUninstall" in text


def test_iss_broadcasts_env_change():
    """装完要让已打开的终端立刻拿到新 PATH -> 广播 WM_SETTINGCHANGE。"""
    text = _read_iss_template()
    assert "SendMessageTimeout" in text
    assert "BroadcastEnvChange" in text


def test_iss_runs_conflict_cleanup_after_install():
    """安装后必须清理抢占命令的旧版 —— 静默安装也要跑（不能 skipifsilent）。"""
    text = _read_iss_template()
    assert "doctor --clean-conflicts" in text
    # 找到那一行，确认没带 skipifsilent
    lines = [ln for ln in text.splitlines() if "clean-conflicts" in ln]
    assert lines, "安装器里没有调用 doctor --clean-conflicts"
    for ln in lines:
        assert "skipifsilent" not in ln, f"清理冲突不能被静默跳过: {ln.strip()}"


# ---------------------------------------------------------------------------
# path_conflicts: PATH 抢占检测
# ---------------------------------------------------------------------------

#: Entry file names produced by pip/setuptools on each platform.
#: Windows: suffixed (pandaone.exe / pandaone.cmd / pandaone.bat).
#: POSIX: a suffix-less executable script (pandaone).
#: Hardcoding .exe makes the whole PATH-conflict suite silently
#: meaningless off Windows (it never errors, it just always reports
#: "no conflict"). Found by 4 red cases on the Ubuntu CI.
_IS_WIN = sys.platform == "win32"
CONSOLE_ENTRY = "pandaone.exe" if _IS_WIN else "pandaone"
MCP_ENTRY = "pandaone-mcp.exe" if _IS_WIN else "pandaone-mcp"


def _make_path_tree(tmp_path, dirs_with_pandaone):
    """构造若干目录，部分目录里放 pandaone entry。返回 (root, 目录列表)。"""
    root = tmp_path / "pathtree"
    root.mkdir()
    made = []
    for i, has_exe in enumerate(dirs_with_pandaone):
        d = root / f"d{i}"
        d.mkdir()
        if has_exe:
            (d / CONSOLE_ENTRY).write_bytes(b"MZ")
        made.append(str(d))
    return root, made


def test_path_conflicts_shadows_detects_earlier_entry(tmp_path, monkeypatch):
    """frozen 形态：当前跑的是 self_dir 里的那个，排在它前面的是影子。"""
    from pandaone import path_conflicts as pc

    root, dirs = _make_path_tree(tmp_path, [True, True])
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", os.pathsep.join(dirs + [str(self_dir)]))
    shadows = pc.shadows(str(self_dir / CONSOLE_ENTRY))
    assert shadows, "排在 self 之前的 pandaone 必须被检出"
    assert shadows[0] == str(root / "d0" / CONSOLE_ENTRY)


def test_path_conflicts_shadows_also_covers_mcp_entry(tmp_path, monkeypatch):
    """`pandaone-mcp` 与 pip 版同名 —— 实测装完 exe 版后它仍被旧版抢占。"""
    from pandaone import path_conflicts as pc

    root = tmp_path / "mcpc"
    old_dir = root / "old"
    old_dir.mkdir(parents=True)
    (old_dir / MCP_ENTRY).write_bytes(b"MZ")
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / MCP_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", f"{old_dir}{os.pathsep}{self_dir}")
    shadows = pc.shadows(str(self_dir / MCP_ENTRY))
    assert shadows == [str(old_dir / MCP_ENTRY)], \
        "MCP 入口同名冲突必须被检出"


def test_path_conflicts_shadows_ignores_later_entry(tmp_path, monkeypatch):
    """排在 self **之后**的不会抢占命令，不该报。"""
    from pandaone import path_conflicts as pc

    root, dirs = _make_path_tree(tmp_path, [False, True])
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", os.pathsep.join([str(self_dir)] + dirs))
    assert pc.shadows(str(self_dir / CONSOLE_ENTRY)) == [], "排在后面的不算冲突"


def test_path_conflicts_find_all_lists_everything(tmp_path, monkeypatch):
    from pandaone import path_conflicts as pc

    root, dirs = _make_path_tree(tmp_path, [True, True])
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", os.pathsep.join(dirs + [str(self_dir)]))
    hits = pc.find_all(str(self_dir / CONSOLE_ENTRY))
    assert len(hits) == 2, "两处都该被列出来"
    assert all("self" not in h for h in hits), "当前运行的那个要排除"


def test_path_conflicts_describe_conflicts_shape(tmp_path, monkeypatch):
    from pandaone import path_conflicts as pc

    root, dirs = _make_path_tree(tmp_path, [True])
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", os.pathsep.join(dirs + [str(self_dir)]))
    d = pc.describe_conflicts(str(self_dir / CONSOLE_ENTRY))
    assert d["ok"] is False
    assert d["shadow"]
    assert "conflicting pandaone" in d["note"]


def test_clean_path_conflicts_renames_and_is_reversible(tmp_path, monkeypatch):
    """改名备份：文件还在（可逆），但不再叫 pandaone entry。"""
    from pandaone import cmd_setup

    root, dirs = _make_path_tree(tmp_path, [True])
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", os.pathsep.join(dirs + [str(self_dir)]))
    status, msg = cmd_setup.clean_path_conflicts(
        exclude=str(self_dir / CONSOLE_ENTRY))
    assert status == "ok", msg

    old = root / "d0" / CONSOLE_ENTRY
    assert not old.exists(), "原来的 pandaone entry 应该被改名"
    backups = list((root / "d0").glob(f"{CONSOLE_ENTRY}.bak-pandaone-*"))
    assert backups, "应该留下可逆的备份文件"
    assert backups[0].read_bytes() == b"MZ", "备份内容必须完整"


def test_clean_path_conflicts_noop_when_clean(tmp_path, monkeypatch):
    from pandaone import cmd_setup

    root = tmp_path / "clean"
    root.mkdir()
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")
    monkeypatch.setenv("PATH", str(self_dir))

    status, msg = cmd_setup.clean_path_conflicts(
        exclude=str(self_dir / CONSOLE_ENTRY))
    assert status == "skip"
    assert (self_dir / CONSOLE_ENTRY).exists(), "没冲突时不能动任何文件"


def test_clean_path_conflicts_dry_run_changes_nothing(tmp_path, monkeypatch):
    from pandaone import cmd_setup

    root, dirs = _make_path_tree(tmp_path, [True])
    self_dir = root / "self"
    self_dir.mkdir()
    (self_dir / CONSOLE_ENTRY).write_bytes(b"MZ")

    monkeypatch.setenv("PATH", os.pathsep.join(dirs + [str(self_dir)]))
    status, msg = cmd_setup.clean_path_conflicts(
        dry_run=True, exclude=str(self_dir / CONSOLE_ENTRY))
    assert status == "ok", msg
    assert (root / "d0" / CONSOLE_ENTRY).exists(), "dry-run 不能动文件"


# ---------------------------------------------------------------------------
# frozen 形态的命令构造（v0.7.29.0 挖出 setup 漏了形态感知）
# ---------------------------------------------------------------------------

def test_setup_serve_uses_frozen_command_shape(monkeypatch, tmp_path):
    """frozen 形态：sys.executable 就是 pandaone.exe，不能再拼 `-m pandaone`。

    `pandaone.exe -m pandaone serve` 会被当成子命令 -> "invalid choice: '-m'"。
    v0.7.26.0 只在 cmd_upgrade 修了，cmd_setup 这条路漏了。
    """
    from pandaone import cmd_setup

    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd

    monkeypatch.setattr(cmd_setup, "_is_frozen", lambda: True)
    monkeypatch.setattr(cmd_setup.subprocess, "Popen", _FakePopen)
    cmd_setup._step_serve(tmp_path)
    assert "-m" not in captured["cmd"], f"frozen 下不能带 -m: {captured['cmd']}"
    assert captured["cmd"][1] == "serve"


def test_setup_serve_uses_source_command_shape(monkeypatch, tmp_path):
    """源码形态：`python -m pandaone serve` 保持不变。"""
    from pandaone import cmd_setup

    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd

    monkeypatch.setattr(cmd_setup, "_is_frozen", lambda: False)
    monkeypatch.setattr(cmd_setup.subprocess, "Popen", _FakePopen)
    cmd_setup._step_serve(tmp_path)
    assert captured["cmd"][1:3] == ["-m", "pandaone"]


def test_mcp_cli_command_does_not_depend_on_path(monkeypatch):
    """MCP 调 CLI 不能靠 PATH 里的裸 `pandaone` 命令。

    旧写法 `subprocess.run(["pandaone", ...])`：机器上没装 pip 版时
    整体报 [WinError 2]；装了两版时可能调到旧版。
    """
    from pandaone_mcp import __main__ as mcp_main

    monkeypatch.setattr(mcp_main.sys, "_MEIPASS", None, raising=False)
    cmd = mcp_main._cli_command()
    assert cmd[1:3] == ["-m", "pandaone"], f"源码形态应走 python -m: {cmd}"


def test_mcp_cli_command_frozen_uses_sibling_exe(monkeypatch, tmp_path):
    """frozen 形态：调同目录的 pandaone.exe，保证 MCP 与 CLI 同版本。"""
    from pandaone_mcp import __main__ as mcp_main

    fake_exe = tmp_path / "pandaone-mcp.exe"
    fake_exe.write_bytes(b"MZ")
    (tmp_path / "pandaone.exe").write_bytes(b"MZ")

    monkeypatch.setattr(mcp_main.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(mcp_main.sys, "executable", str(fake_exe))
    cmd = mcp_main._cli_command()
    assert cmd == [str(tmp_path / "pandaone.exe")], f"frozen 应走同目录 exe: {cmd}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
