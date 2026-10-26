# -*- coding: utf-8 -*-
"""
test_cmd_backup.py — `pandaone backup` 纯本地备份测试

关键断言：**不碰远程**（不 git remote add、不 push）。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone import cmd_backup, git_ops


def _git_available() -> bool:
    return git_ops.git_exe() is not None


needs_git = pytest.mark.skipif(not _git_available(), reason="git 不可用")


@pytest.fixture
def repo(tmp_path):
    if not _git_available():
        pytest.skip("git 不可用")
    root = tmp_path / "proj"
    root.mkdir()
    git_ops.run_git(["init"], cwd=root)
    git_ops.run_git(["config", "--local", "user.name", "tester"], cwd=root)
    git_ops.run_git(["config", "--local", "user.email", "t@example.com"], cwd=root)
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    git_ops.run_git(["add", "-A"], cwd=root)
    git_ops.run_git(["commit", "-m", "init"], cwd=root)
    return root


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------

@needs_git
def test_backup_creates_bundle(repo, tmp_path, capsys):
    out = tmp_path / "snap.bundle"
    args = SimpleNamespace(root=str(repo), output=str(out), mirror=None, no_bundle=False, status=False)
    rc = cmd_backup.handler(args)
    assert rc == 0
    assert out.is_file()
    assert out.stat().st_size > 0


@needs_git
def test_backup_default_output_uses_timestamp(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(root=str(repo), output=None, mirror=None, no_bundle=False, status=False)
    rc = cmd_backup.handler(args)
    assert rc == 0
    bundles = list(tmp_path.glob("proj-*.bundle"))
    assert bundles, "应按 <项目名>-<时间戳>.bundle 生成默认输出"


@needs_git
def test_backup_does_not_create_remote(repo, tmp_path):
    """纯本地：不设置任何 remote。"""
    out = tmp_path / "snap2.bundle"
    args = SimpleNamespace(root=str(repo), output=str(out), mirror=None, no_bundle=False, status=False)
    cmd_backup.handler(args)
    remotes = git_ops.run_git(["remote", "-v"], cwd=repo).stdout.strip()
    assert remotes == "", f"backup 不应创建 remote，实际: {remotes}"


@needs_git
def test_backup_with_local_mirror(repo, tmp_path):
    mirror = tmp_path / "mirror.git"
    out = tmp_path / "snap3.bundle"
    args = SimpleNamespace(root=str(repo), output=str(out), mirror=str(mirror), no_bundle=False, status=False)
    rc = cmd_backup.handler(args)
    assert rc == 0
    assert mirror.is_dir()
    # 裸仓库布局**跨平台不同**，两种都合法：
    #   - 标准 bare（`git clone --mirror` 成功时）：<mirror>/HEAD + objects/ + refs/
    #   - Windows fallback（缺 git-upload-pack 时复制 .git）：<mirror>/.git/HEAD
    # 真正的不变量是"能被 clone 恢复"，见 test_git_ops.test_mirror_can_be_cloned_back
    git_dir = mirror if (mirror / "HEAD").is_file() else mirror / ".git"
    assert (git_dir / "HEAD").is_file()
    assert out.is_file()


@needs_git
def test_backup_status_only_makes_no_file(repo, tmp_path):
    out = tmp_path / "snap4.bundle"
    args = SimpleNamespace(root=str(repo), output=str(out), mirror=None, no_bundle=False, status=True)
    rc = cmd_backup.handler(args)
    assert rc == 0
    assert not out.exists()


def test_backup_fails_on_non_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    args = SimpleNamespace(root=str(plain), output=None, mirror=None, no_bundle=False, status=False)
    rc = cmd_backup.handler(args)
    assert rc == 1


@needs_git
def test_backup_no_bundle_only_mirror(repo, tmp_path):
    mirror = tmp_path / "m2.git"
    args = SimpleNamespace(root=str(repo), output=None, mirror=str(mirror), no_bundle=True, status=False)
    rc = cmd_backup.handler(args)
    assert rc == 0
    assert mirror.is_dir()
    assert not list(tmp_path.glob("*.bundle"))


# ---------------------------------------------------------------------------
# 命令注册
# ---------------------------------------------------------------------------

def test_backup_command_is_registered():
    import pandaone.__main__ as m

    m._ensure_doctor_registered()
    from pandaone import cli

    assert "backup" in cli.COMMANDS
    assert cli.COMMANDS["backup"] is cmd_backup.handler


def test_backup_parser_arguments():
    import argparse

    from pandaone import cli

    m_parser = cli.build_parser()
    args = m_parser.parse_args(["backup", "--output", "x.bundle", "--mirror", "m.git"])
    assert args.command == "backup"
    assert args.output == "x.bundle"
    assert args.mirror == "m.git"
    assert args.no_bundle is False
    assert args.status is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
