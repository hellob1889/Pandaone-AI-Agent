"""
test_pre_commit_hook.py
=======================
Phase 4.6+ — pre-commit hook 强化版验证。

第一性原理：
  旧 hook 只检查 .py 文件，新版从 config.json 读保护扩展名列表。
  必须严格检查每个 staged 受保护文件都有 APPROVED 记录——否则绕过。
"""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
HOOK_SRC = ROOT_DIR / "src" / "pandaone" / "templates" / "pre-commit-hook"

import shutil as _shutil

# v0.7.15 fix: 之前硬编码作者机器路径 `D:\软件\Git\cmd\git.exe`，
# 在任何非作者机器上全部失败。改为动态探测 PATH。
GIT_CANDIDATES = [_shutil.which("git")] if _shutil.which("git") else []


def _git_exe():
    for c in GIT_CANDIDATES:
        if c:
            return c
    pytest.skip("git not found")


def _setup_git_project(tmp_path):
    """建项目 + init + 装 hook + 初始 commit"""
    import json as _json
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    git = _git_exe()
    env["PATH"] = str(Path(git).parent) + os.pathsep + env.get("PATH", "")

    # init pandaone
    r = subprocess.run([sys.executable, "-m", "pandaone", "init", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True)
    assert r.returncode == 0

    # 简化 config（只保护 .py 和 .md，避免太多默认扩展）
    cfg_path = tmp_path / ".pandaone" / "config.json"
    cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["protected_extensions"] = [".py", ".md"]
    cfg_path.write_text(_json.dumps(cfg, indent=2), encoding="utf-8")

    # git init
    for cmd in [["init"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"], ["add", "-A"], ["commit", "-m", "init"]]:
        subprocess.run([git] + cmd, cwd=str(tmp_path), env=env, capture_output=True)

    # 装 hook（通过 install-hook 自动复制 check.py）
    r = subprocess.run([sys.executable, "-m", "pandaone", "install-hook", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"install-hook 失败: {r.stderr}"

    return tmp_path, env, git


def _run_git(args, cwd, env, git):
    return subprocess.run([git] + args, cwd=cwd, env=env,
                          capture_output=True, text=True)


def _add_approved_record(audit_path: Path, file: str):
    """模拟 pandaone write 添加 APPROVED 记录"""
    import json as _json
    record = {
        "id": f"audit_{file.replace('/', '_').replace('.', '_')}",
        "timestamp": "2026-09-04 12:00:00",
        "status": "APPROVED",
        "file": file,
    }
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(record, ensure_ascii=False) + "\n")


class TestPreCommitHookBypassProtection:
    """Phase 4.6+: hook 应严格拒绝绕过"""

    def test_hook_rejects_unapproved_py(self, tmp_path):
        """未通过 write 的 .py 文件应被 hook 拒绝"""
        project, env, git = _setup_git_project(tmp_path)
        # 模拟直接编辑 .py（不通过 write）
        py_file = project / "main.py"
        py_file.write_text("UNAUTHORIZED = True\n", encoding="utf-8")
        # 给文件加写权限（绕过 L1）
        py_file.chmod(py_file.stat().st_mode | stat.S_IWUSR)
        _run_git(["add", "main.py"], project, env, git)

        # git commit 应被拒绝
        r = _run_git(["commit", "-m", "bypass"], project, env, git)
        assert r.returncode != 0, f"hook 未拦截: rc={r.returncode}, out={r.stdout}, err={r.stderr}"
        combined = r.stdout + r.stderr
        assert any(s in combined for s in [
            "未审计", "Pandaone AI Agent", "拒绝",  # 中文
            "reject", "no APPROVED", "Pandaone",  # 英文（pre-commit-check 的 t_safe fallback 也是中文，但允许英文）
        ]), f"hook 输出应包含拒绝信息: {combined[:300]}"

    def test_hook_rejects_unapproved_md(self, tmp_path):
        """未通过 write 的 .md 文件应被 hook 拒绝（Phase 4.6 扩展）"""
        project, env, git = _setup_git_project(tmp_path)
        # 创建 README.md（不被默认保护，但要把它加入 config）
        md_file = project / "README.md"
        md_file.write_text("# Hijacked\n", encoding="utf-8")
        md_file.chmod(md_file.stat().st_mode | stat.S_IWUSR)
        _run_git(["add", "README.md"], project, env, git)

        r = _run_git(["commit", "-m", "bypass md"], project, env, git)
        assert r.returncode != 0, "未审计的 .md 应被 hook 拒绝"

    def test_hook_allows_approved_py(self, tmp_path):
        """通过 write 的 .py 应允许 commit"""
        project, env, git = _setup_git_project(tmp_path)
        py_file = project / "main.py"
        py_file.write_text("UNAUTHORIZED = True\n", encoding="utf-8")
        py_file.chmod(py_file.stat().st_mode | stat.S_IWUSR)
        # 添加 APPROVED 记录（模拟 write 已完成）
        audit_path = project / ".pandaone" / "pandaone.jsonl"
        _add_approved_record(audit_path, "main.py")
        _run_git(["add", "main.py"], project, env, git)

        r = _run_git(["commit", "-m", "approved"], project, env, git)
        assert r.returncode == 0, f"已审计的 .py 应通过: rc={r.returncode}, err={r.stderr}"

    def test_hook_allows_non_protected_files(self, tmp_path):
        """未在保护列表中的扩展名应允许 commit"""
        project, env, git = _setup_git_project(tmp_path)
        # 创建 .txt 文件（不在 .py .md 列表中）
        txt_file = project / "notes.txt"
        txt_file.write_text("just notes\n", encoding="utf-8")
        _run_git(["add", "notes.txt"], project, env, git)

        r = _run_git(["commit", "-m", "add notes"], project, env, git)
        assert r.returncode == 0, f".txt 不受保护应允许: rc={r.returncode}, err={r.stderr}"

    def test_no_verify_can_bypass(self, tmp_path):
        """--no-verify 应能绕过 hook（合法逃生通道）"""
        project, env, git = _setup_git_project(tmp_path)
        py_file = project / "main.py"
        py_file.write_text("UNAUTHORIZED = True\n", encoding="utf-8")
        py_file.chmod(py_file.stat().st_mode | stat.S_IWUSR)
        _run_git(["add", "main.py"], project, env, git)

        r = _run_git(["commit", "--no-verify", "-m", "force bypass"], project, env, git)
        assert r.returncode == 0, f"--no-verify 应允许: rc={r.returncode}, err={r.stderr}"