"""测试 gitignore_helper:确保 .gitignore 自动维护不会污染用户配置。

第一性原则:
  - 只在 git 仓库里操作
  - 幂等:已正确配置的不重复添加
  - 不破坏现有规则:只在末尾追加缺失的
"""
import shutil
import subprocess
from pathlib import Path
import pytest

from pandaone.gitignore_helper import (
    is_git_repo,
    ensure_gitignore,
    check_gitignore,
    REQUIRED_GITIGNORE_ENTRIES,
)


# v0.7.15 fix: 之前硬编码作者机器路径 `D:\软件\Git\cmd\git.exe`，
# 在任何非作者机器（包括 CI 的 Linux runner）上 10 个用例全部 ERROR。
# 改为动态探测 PATH 中的 git，与 conftest.py 的探测策略一致。
GIT_EXE = shutil.which("git") or "git"


def _git(args, cwd):
    """在指定目录运行 git 命令。"""
    return subprocess.run(
        [GIT_EXE] + args, cwd=str(cwd),
        capture_output=True, text=True, timeout=10,
    )


@pytest.fixture
def git_repo(tmp_path: Path):
    """创建临时 git 仓库。"""
    _git(["init", "-q"], tmp_path)
    return tmp_path


class TestIsGitRepo:
    def test_true_when_dot_git_exists(self, git_repo):
        assert is_git_repo(git_repo) is True

    def test_false_when_no_git(self, tmp_path):
        assert is_git_repo(tmp_path) is False


class TestEnsureGitignore:
    def test_creates_gitignore_when_missing(self, git_repo: Path):
        """git 仓库无 .gitignore 时,自动创建并写入 Pandaone AI Agent 条目。"""
        assert not (git_repo / ".gitignore").exists()
        changed, msg = ensure_gitignore(git_repo)
        assert changed is True
        assert "[OK]" in msg
        assert (git_repo / ".gitignore").exists()
        content = (git_repo / ".gitignore").read_text(encoding="utf-8")
        assert ".pandaone/" in content
        assert "desktop.ini" in content

    def test_idempotent_when_already_correct(self, git_repo: Path):
        """已经正确配置的不重复添加。"""
        ensure_gitignore(git_repo)
        original = (git_repo / ".gitignore").read_text(encoding="utf-8")
        changed, msg = ensure_gitignore(git_repo)
        assert changed is False
        assert "已正确" in msg or "已正确包含" in msg or "[OK]" in msg
        # 内容不应变化
        assert (git_repo / ".gitignore").read_text(encoding="utf-8") == original

    def test_preserves_existing_rules(self, git_repo: Path):
        """不能覆盖用户的现有 .gitignore 条目。"""
        existing = "__pycache__/\n*.pyc\nnode_modules/\n"
        (git_repo / ".gitignore").write_text(existing, encoding="utf-8")
        changed, _ = ensure_gitignore(git_repo)
        assert changed is True
        content = (git_repo / ".gitignore").read_text(encoding="utf-8")
        # 用户原有规则全部保留
        assert "__pycache__/" in content
        assert "*.pyc" in content
        assert "node_modules/" in content
        # 新增 Pandaone 条目
        assert ".pandaone/" in content
        assert "desktop.ini" in content

    def test_skip_when_not_git_repo(self, tmp_path: Path):
        """非 git 目录直接跳过,不创建 .gitignore。"""
        assert not is_git_repo(tmp_path)
        changed, msg = ensure_gitignore(tmp_path)
        assert changed is False
        assert "[SKIP]" in msg
        assert not (tmp_path / ".gitignore").exists()

    def test_adds_only_missing_entries(self, git_repo: Path):
        """只添加缺失的,已有 .pandaone/ 时只补 desktop.ini。"""
        (git_repo / ".gitignore").write_text(".pandaone/\n", encoding="utf-8")
        changed, msg = ensure_gitignore(git_repo)
        assert changed is True
        content = (git_repo / ".gitignore").read_text(encoding="utf-8")
        # .pandaone/ 不应重复(只有一处)
        assert content.count(".pandaone/") == 1
        # desktop.ini 应已添加
        assert "desktop.ini" in content


class TestCheckGitignore:
    def test_ok_when_complete(self, git_repo: Path):
        ensure_gitignore(git_repo)
        ok, missing = check_gitignore(git_repo)
        assert ok is True
        assert missing == []

    def test_missing_when_no_file(self, git_repo: Path):
        ok, missing = check_gitignore(git_repo)
        assert ok is False
        assert ".pandaone/" in missing
        assert "desktop.ini" in missing

    def test_partial_missing(self, git_repo: Path):
        (git_repo / ".gitignore").write_text(".pandaone/\n", encoding="utf-8")
        ok, missing = check_gitignore(git_repo)
        assert ok is False
        assert "desktop.ini" in missing
        assert ".pandaone/" not in missing


class TestCmdInitIntegration:
    """cmd_init 末尾集成 gitignore_helper 的端到端测试。"""

    def test_init_creates_gitignore_in_git_repo(self, git_repo: Path, monkeypatch):
        """在 git 仓库里 init 应自动创建 .gitignore。"""
        # 创建一些文件让 init 有事可做
        (git_repo / "main.py").write_text("# main", encoding="utf-8")

        from pandaone.cli import cmd_init
        import argparse
        args = argparse.Namespace(
            root=str(git_repo), ext=None, no_binary=False, force_reset=False,
        )
        rc = cmd_init(args)
        assert rc == 0
        # .gitignore 应已存在并包含 Pandaone 条目
        assert (git_repo / ".gitignore").exists()
        content = (git_repo / ".gitignore").read_text(encoding="utf-8")
        assert ".pandaone/" in content
        assert "desktop.ini" in content

    def test_init_skips_gitignore_in_non_git(self, tmp_path: Path):
        """非 git 目录 init 不创建 .gitignore。"""
        (tmp_path / "main.py").write_text("# main", encoding="utf-8")
        from pandaone.cli import cmd_init
        import argparse
        args = argparse.Namespace(
            root=str(tmp_path), ext=None, no_binary=False, force_reset=False,
        )
        cmd_init(args)
        assert not (tmp_path / ".gitignore").exists()


class TestEndToEndWithRealGit:
    """真实 git 命令验证 desktop.ini 不再被 git 报告。"""

    def test_desktop_ini_ignored_after_init(self, git_repo: Path):
        """init 后,desktop.ini 即使被创建也不应被 git 报告。"""
        # 1. init
        from pandaone.cli import cmd_init
        import argparse
        cmd_init(argparse.Namespace(
            root=str(git_repo), ext=None, no_binary=False, force_reset=False,
        ))

        # 2. lock(创建 desktop.ini)
        from pandaone.cli import cmd_lock
        (git_repo / "main.py").write_text("# main", encoding="utf-8")
        # 重新 init 让 .py 被纳入保护范围(确保 lock 实际有效果)
        cmd_lock(argparse.Namespace(root=str(git_repo), no_auto_init=True))

        # 3. 验证 desktop.ini 被 .gitignore 排除
        result = _git(["status", "--porcelain"], git_repo)
        # 应该没有 desktop.ini 行
        assert "desktop.ini" not in result.stdout
        # 应该没有 .pandaone/ 行
        assert ".pandaone/" not in result.stdout