# -*- coding: utf-8 -*-
"""
pre-commit hook 的 git 路径解析 —— 跨平台回归测试。

背景（v0.7.31.0 之后的真机实测结论）
====================================
pre-commit hook 运行在 Git for Windows 的 MSYS 环境里，那里 PATH 会被
重写成 MSYS 风格，且**含非 ASCII 字符的目录项会被转码成 mojibake**
（典型：D:\\软件\\Git\\cmd -> D:\\鏉瀄ue...\\Git\\cmd）。后果是：

  - ``shutil.which("git")`` 返回 None（它按 Windows 语义拼 PATH）；
  - 从 ``GIT_EXEC_PATH`` 反推出来的候选**同样带 mojibake**，isfile 必假；
  - 兜底的裸命令 ``"git"`` 在 hook 环境里同样找不到 -> WinError 2。

也就是说：hook 里凡是需要"找到 git"的地方，**只有在安装时刻**（一个 PATH
完好的普通进程）才能拿到未损坏的路径。所以 ``install-hook`` 解析一次并
固化到 ``.pandaone/git_exe.txt``，运行时只读文件。

本文件守住这条链路，防止再退化成"在作者那台机器上碰巧能用"。
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "src" / "pandaone" / "templates" / "pre-commit-check.py"


def _load_check_module():
    """按文件路径加载 pre-commit-check.py 模板（它不是可导入的包模块）。"""
    spec = importlib.util.spec_from_file_location("_pandaone_pre_commit_check", TEMPLATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_available() -> bool:
    try:
        from pandaone.git_installer import _find_git_executable

        if _find_git_executable():
            return True
    except Exception:
        pass
    return shutil.which("git") is not None


@pytest.fixture(scope="module")
def check_mod():
    return _load_check_module()


def _write_hint(root: Path, value: str) -> None:
    pandaone_dir = root / ".pandaone"
    pandaone_dir.mkdir(parents=True, exist_ok=True)
    (pandaone_dir / "git_exe.txt").write_text(value, encoding="utf-8")


def test_install_hook_writes_git_exe_hint(tmp_path):
    """安装 hook 时必须把 git 绝对路径固化下来。"""
    from pandaone.install_hook import install_hook

    if not _git_available():
        pytest.skip("git not installed on this machine")

    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    assert install_hook(tmp_path) == 0

    hint_file = tmp_path / ".pandaone" / "git_exe.txt"
    assert hint_file.is_file(), "install-hook did not write git_exe.txt"
    value = hint_file.read_text(encoding="utf-8").strip()
    assert value, "git_exe.txt is empty"
    assert Path(value).is_file(), f"git_exe.txt points to a missing file: {value}"


def test_resolve_prefers_installed_hint(check_mod, tmp_path, monkeypatch):
    """安装时固化的 hint 优先于 PATH 查找等其它来源。"""
    fake = tmp_path / "git.exe"
    fake.write_text("stub", encoding="utf-8")
    _write_hint(tmp_path, str(fake))

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PANDAONE_GIT_EXE", raising=False)
    assert check_mod._resolve_git_exe() == str(fake)


def test_resolve_survives_broken_env(check_mod, tmp_path, monkeypatch):
    """PATH 残缺 + GIT_EXEC_PATH mojibake 时，仍能靠安装时 hint 定位 git。

    这是 v0.7.31.0 引入的真实回归形态：删掉模板里的硬编码路径后，
    Windows 上 hook 找不到 git，pre-commit 门禁直接失效（放行不了也拦不住）。
    """
    fake = tmp_path / "git.exe"
    fake.write_text("stub", encoding="utf-8")
    _write_hint(tmp_path, str(fake))

    # 复刻真实 hook 环境：PATH 是 MSYS 风格，中文段已被转码破坏
    mojibake = "D:/" + "软件".encode("utf-8").decode("gbk", errors="replace")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "/mingw64/libexec/git-core:/usr/bin")
    monkeypatch.setenv("GIT_EXEC_PATH", mojibake + "/Git/mingw64/libexec/git-core")
    monkeypatch.delenv("PANDAONE_GIT_EXE", raising=False)
    monkeypatch.delenv("GIT_EXECUTABLE", raising=False)

    resolved = check_mod._resolve_git_exe()
    assert resolved == str(fake), f"broken env did not fall back to the installed hint: {resolved}"


def test_resolve_never_raises(check_mod, tmp_path, monkeypatch):
    """任何环境下都不抛异常 —— hook 崩了等于门禁被绕过。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("PANDAONE_GIT_EXE", raising=False)
    monkeypatch.delenv("GIT_EXECUTABLE", raising=False)
    monkeypatch.delenv("GIT_EXEC_PATH", raising=False)

    resolved = check_mod._resolve_git_exe()
    assert isinstance(resolved, str) and resolved


def test_exec_path_candidates_walk_up_to_install_root(check_mod):
    """GIT_EXEC_PATH 反推必须能一路回溯到安装根（Git for Windows 布局）。"""
    exec_path = r"D:\Git\mingw64\libexec\git-core"
    candidates = check_mod._git_candidates_from_exec_path(exec_path)
    assert r"D:\Git\cmd\git.exe" in candidates
    assert r"D:\Git\mingw64\bin\git.exe" in candidates
