# -*- coding: utf-8 -*-
"""
test_git_ops.py — git_ops 本地 git 操作层测试

全部在 tmp_path 里建真仓库跑真 git（不 mock subprocess），
因为这里要验证的就是"真 git 的行为"，mock 掉就没意义了。
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone import git_ops


def _git_available() -> bool:
    return git_ops.git_exe() is not None


needs_git = pytest.mark.skipif(not _git_available(), reason="git 不可用")


@pytest.fixture
def repo(tmp_path):
    """一个带一次提交的临时 git 仓库。"""
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
# 基础探测
# ---------------------------------------------------------------------------

@needs_git
def test_is_repo_true_for_real_repo(repo):
    assert git_ops.is_repo(repo) is True


@needs_git
def test_is_repo_false_for_plain_dir(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_ops.is_repo(plain) is False


@needs_git
def test_has_commits(repo, tmp_path):
    assert git_ops.has_commits(repo) is True
    empty = tmp_path / "empty"
    empty.mkdir()
    git_ops.run_git(["init"], cwd=empty)
    assert git_ops.has_commits(empty) is False


# ---------------------------------------------------------------------------
# init / identity / baseline
# ---------------------------------------------------------------------------

@needs_git
def test_init_repo_is_idempotent(tmp_path):
    root = tmp_path / "new"
    root.mkdir()
    created, msg = git_ops.init_repo(root)
    assert created is True
    assert git_ops.is_repo(root) is True
    created2, msg2 = git_ops.init_repo(root)
    assert created2 is False, "重复 init 不应再新建"
    assert "跳过" in msg2 or "skip" in msg2.lower()


@needs_git
def test_init_repo_does_not_touch_global_config(tmp_path, monkeypatch):
    """绝不写 git config --global（避免污染用户全局设置）。"""
    root = tmp_path / "new2"
    root.mkdir()
    git_ops.init_repo(root)
    # 仓库级 core.autocrlf 存在，但不该出现仓库级 user.name（那是 ensure 的职责）
    p = git_ops.run_git(["config", "--local", "--get", "user.name"], cwd=root, check=False)
    assert p.returncode != 0, "init_repo 不应设置提交身份"


@needs_git
def test_ensure_repo_identity_sets_local_only(tmp_path):
    root = tmp_path / "idtest"
    root.mkdir()
    git_ops.init_repo(root)
    wrote, msg = git_ops.ensure_repo_identity(root)
    assert wrote is True
    name = git_ops.run_git(["config", "--local", "--get", "user.name"], cwd=root).stdout.strip()
    email = git_ops.run_git(["config", "--local", "--get", "user.email"], cwd=root).stdout.strip()
    assert name and email
    # 全局配置里不该有我们写的值
    g = git_ops.run_git(["config", "--global", "--get", "user.name"], cwd=root, check=False)
    assert g.stdout.strip() != name or g.returncode != 0


@needs_git
def test_baseline_commit(repo, tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    git_ops.init_repo(second)
    (second / "x.txt").write_text("x\n", encoding="utf-8")
    ok, msg = git_ops.baseline_commit(second)
    assert ok is True
    assert git_ops.has_commits(second) is True
    # 已有提交的仓库再跑一次 → 跳过
    ok2, _ = git_ops.baseline_commit(second)
    assert ok2 is False


@needs_git
def test_baseline_commit_requires_repo(tmp_path):
    plain = tmp_path / "plain2"
    plain.mkdir()
    with pytest.raises(git_ops.GitOpsError):
        git_ops.baseline_commit(plain)


# ---------------------------------------------------------------------------
# bundle / mirror
# ---------------------------------------------------------------------------

@needs_git
def test_create_bundle(repo, tmp_path):
    out = tmp_path / "snap.bundle"
    result = git_ops.create_bundle(repo, out)
    assert result.is_file()
    assert result.stat().st_size > 0
    # bundle 能被 git 验证
    p = git_ops.run_git(["bundle", "verify", str(result)], cwd=repo, check=False)
    assert p.returncode == 0, p.stderr


@needs_git
def test_create_bundle_rejects_empty_repo(tmp_path):
    empty = tmp_path / "empty2"
    empty.mkdir()
    git_ops.run_git(["init"], cwd=empty)
    with pytest.raises(git_ops.GitOpsError):
        git_ops.create_bundle(empty, tmp_path / "x.bundle")


@needs_git
def test_create_bundle_rejects_non_repo(tmp_path):
    plain = tmp_path / "plain3"
    plain.mkdir()
    with pytest.raises(git_ops.GitOpsError):
        git_ops.create_bundle(plain, tmp_path / "y.bundle")


@needs_git
def test_create_mirror(repo, tmp_path):
    dest = tmp_path / "mirror.git"
    target = git_ops.create_mirror(repo, dest)
    assert target.is_dir()
    # 镜像是本地仓库布局（.git/ 子目录），信息完整（含 objects / refs / logs）
    assert (target / ".git" / "HEAD").is_file()
    assert (target / ".git" / "objects").is_dir()
    assert (target / ".git" / "refs").is_dir()
    # 零传输验证：git 能直接读出镜像里的历史（不经过任何传输层）
    head = git_ops.run_git(["rev-parse", "HEAD"], cwd=target).stdout.strip()
    src_head = git_ops.run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    assert head == src_head
    # 提交数一致
    n_mirror = git_ops.run_git(["rev-list", "--count", "HEAD"], cwd=target).stdout.strip()
    n_src = git_ops.run_git(["rev-list", "--count", "HEAD"], cwd=repo).stdout.strip()
    assert n_mirror == n_src


@needs_git
def test_bundle_can_be_restored_anywhere(repo, tmp_path):
    """bundle 是跨平台零依赖的恢复载体（不走传输层，不需要 git-upload-pack）。

    Windows 上 git clone <本地路径> 会走 smart transport 调
    git-upload-pack，在含中文路径的 Git 安装下必然失败；
    但 bundle 是 git 自己读的归档，clone 一定成功。
    """
    out = tmp_path / "restore.bundle"
    git_ops.create_bundle(repo, out)
    back = tmp_path / "restored"
    git_ops.run_git(["clone", str(out), str(back)], cwd=tmp_path)
    assert (back / "a.txt").is_file()
    head = git_ops.run_git(["rev-parse", "HEAD"], cwd=back).stdout.strip()
    src_head = git_ops.run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    assert head == src_head


@needs_git
def test_create_mirror_refuses_non_empty_target(repo, tmp_path):
    dest = tmp_path / "busy"
    dest.mkdir()
    (dest / "something").write_text("x", encoding="utf-8")
    with pytest.raises(git_ops.GitOpsError):
        git_ops.create_mirror(repo, dest)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

@needs_git
def test_repo_summary(repo):
    s = git_ops.repo_summary(repo)
    assert s["is_repo"] is True
    assert s["has_commits"] is True
    assert s["commit_count"] >= 1
    assert s["head"]
    assert s["remotes"] == []


@needs_git
def test_repo_summary_plain_dir(tmp_path):
    plain = tmp_path / "plain4"
    plain.mkdir()
    s = git_ops.repo_summary(plain)
    assert s["is_repo"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
