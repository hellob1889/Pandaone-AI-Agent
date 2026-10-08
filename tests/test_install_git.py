"""
test_install_git.py
===================
RED 测试：pandaone install-git 子命令

第一性原理：
  - git 是 Pandaone AI Agent 自动 commit 的依赖
  - 用户可能没装 git，CLI 应能自动安装
  - 设计：默认便携版 git（解压即用，免安装）

测试策略：
  - 子进程调用 pandaone install-git
  - 至少做到：探测 + 报告，不强制下载
  - 详细测试用 --probe-only 跳过下载阶段
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANDAX = ROOT / "pandaone_dev.py"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_install_git_subcommand_exists():
    """install-git 子命令必须存在"""
    r = subprocess.run(
        [sys.executable, str(PANDAX), "--help"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert "install-git" in r.stdout, "install-git 子命令未注册"


def test_install_git_probe_finds_existing():
    """--probe-only 在 git 存在时报告路径，不下载"""
    if not shutil.which("git"):
        pytest.skip("git 不在 PATH 中")

    r = run(["install-git", "--probe-only"])
    assert r.returncode == 0, f"stderr={r.stderr}"
    # 应输出 git 路径
    assert "git" in r.stdout.lower()
    assert ("已安装" in r.stdout) or ("found" in r.stdout.lower()) or (".exe" in r.stdout)


def test_install_git_probe_reports_status():
    """无论 git 是否存在，--probe-only 都应给出明确报告"""
    r = run(["install-git", "--probe-only"])
    assert r.returncode == 0
    # 应有明确的 OK 或 NOT FOUND 报告
    out = r.stdout
    assert len(out) > 20, "输出太短，可能没真正探测"


def test_install_git_handles_missing_git_gracefully(monkeypatch):
    """Bug fix (v0.7.15) F-15: 如果 git 不存在但又不下载，应优雅处理

    用 monkeypatch 移除 shutil.which 和常见路径探测，让 git 真正不可用。
    """
    # 模拟 git 不可用
    monkeypatch.setattr(shutil, "which", lambda x: None)
    # 屏蔽常见的绝对路径探测（按本机实际路径调整）
    real_exists = Path.exists

    def fake_exists(self):
        path_str = str(self)
        if "git" in path_str.lower() and ("cmd" in path_str.lower() or "bin" in path_str.lower()):
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    env = os.environ.copy()
    env["PATH"] = ""

    r = subprocess.run(
        [sys.executable, str(PANDAX), "install-git", "--probe-only"],
        cwd=str(ROOT), capture_output=True, text=True, env=env,
        timeout=10,
    )

    # 不应崩溃
    assert r.returncode in (0, 1), f"应优雅处理: rc={r.returncode}"

    # 输出应有意义（探测结果）。阈值与上方 probe 测试对齐为 >20：
    # i18n 下中文输出（如"[NOT FOUND] git 未安装"）比英文短，>50 是按英文硬编码的过时阈值
    assert len(r.stdout) > 20, f"输出太短: {r.stdout}"
    # 至少包含 git 状态信息
    assert "git" in r.stdout.lower() or "探测" in r.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
