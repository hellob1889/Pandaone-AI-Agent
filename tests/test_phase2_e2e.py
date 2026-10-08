"""
test_phase2_e2e.py
===================
Phase 2 端到端测试：完整 L1+L2+L3+L5 链路

第一性原理：
  验证所有五层防御协同工作：
    - L5 自指纹保护
    - L1 文件锁
    - L2 watchdog 监控
    - L3 git pre-commit hook
    - 审计日志（贯穿所有层）

测试场景：
  1. 完整 init → git init → 初始 commit
  2. 安装 pre-commit hook
  3. 通过 pandaone write 修改（合法）→ 成功 + 审计
  4. shell bypass 修改 .py → L1 锁阻止，绕过
     → L2 watchdog 检测 → 写 UNAUTHORIZED 审计 + git checkout 回滚
     → L3 hook 阻止 git commit
  5. status 命令显示完整状态（含 UNAUTHORIZED 计数）
  6. log 命令能看到所有记录
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pandaone_guard import PandaXHandler  # noqa: E402

PANDAX = ROOT / "pandaone_dev.py"
INSTALL_HOOK = ROOT / "src" / "pandaone" / "install_hook.py"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # Bug fix (v0.7.15) F-15: 加 errors="replace" + encoding="utf-8" 防止 GBK 崩溃
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=15,
    )


def make_event(src_path: str):
    class FakeEvent:
        pass
    e = FakeEvent()
    e.src_path = src_path
    e.dest_path = src_path
    e.is_directory = False
    return e


def setup_full(tmp_path: Path) -> Path:
    """完整初始化：init + git init + 初始 commit + lock + install-hook"""
    run(["init", "--root", str(tmp_path)], cwd=tmp_path)

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "agent@x"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "agent"], cwd=tmp_path, capture_output=True, text=True)

    (tmp_path / "main.py").write_text('ORIGINAL = "v1"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, text=True)

    run(["lock", "--root", str(tmp_path)], cwd=tmp_path)

    # 安装 pre-commit hook
    r = subprocess.run(
        [sys.executable, str(INSTALL_HOOK), "--root", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert r.returncode == 0

    return tmp_path


def test_full_defense_chain(tmp_path):
    """完整防御链：合法写入 → shell bypass → watchdog 回滚 → hook 阻止 → status 告警"""
    project = setup_full(tmp_path)
    main_py = project / "main.py"

    # ============ Phase 2A: 合法写入（通过 pandaone write）============
    r = run([
        "write",
        "--root", str(project),
        "--file", "main.py",
        "--reason", "优化字符串字面量使用单引号",
        "--problem", "原代码使用双引号不符合PEP8风格指南规范",
        "--approach", "改为单引号并保持语义完全一致",
        "--old", 'ORIGINAL = "v1"',
        "--new", "ORIGINAL = 'v1'",
        "--force-write",  # Bug #12 v2: 锁定文件需显式 force
    ], cwd=project)
    assert r.returncode == 0, f"合法写入失败: {r.stdout}"

    # ============ Phase 2B: shell bypass（攻击者用 chmod 解锁 + 直接改）============
    # 解锁
    main_py.chmod(main_py.stat().st_mode | stat.S_IWUSR)
    main_py.write_text("BYPASS = 'tampered'\n", encoding="utf-8")

    # 模拟 L2 watchdog 检测
    handler = PandaXHandler(project)
    event = make_event(str(main_py))
    handler.on_modified(event)

    # ============ 验证 L2 拦截结果 ============
    # 文件被回滚
    assert "BYPASS" not in main_py.read_text(encoding="utf-8"), "watchdog 未回滚"
    # 审计日志有 UNAUTHORIZED 记录
    audit_path = project / ".pandaone" / "pandaone.jsonl"
    records = [
        json.loads(l) for l in
        audit_path.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    unauthorized = [r for r in records if r["status"] == "UNAUTHORIZED"]
    assert len(unauthorized) >= 1, "watchdog 未写 UNAUTHORIZED 审计"
    assert "main.py" in unauthorized[-1]["file"]

    # ============ Phase 2C: L3 hook 阻止未审计 git commit ============
    # 现在手动 git add + commit（应该被 hook 拒绝）
    subprocess.run(["git", "add", "main.py"], cwd=project, capture_output=True, text=True)
    r = subprocess.run(
        ["git", "commit", "-m", "bypass attempt"],
        cwd=project, capture_output=True, text=True,
    )
    assert r.returncode != 0, "L3 hook 未阻止未审计 commit"
    assert "pandaone" in (r.stdout + r.stderr).lower() or "audit" in (r.stdout + r.stderr).lower()

    # ============ Phase 2D: status 显示告警 ============
    r = run(["status", "--root", str(project)], cwd=project)
    assert r.returncode == 0
    out = r.stdout
    # 应有 L1/L2/L5 标记
    assert "[L1" in out
    assert "[L2" in out
    assert "[L5" in out
    # 审计统计应含 UNAUTHORIZED
    assert "UNAUTHORIZED" in out

    # ============ Phase 2E: log 显示完整记录 ============
    r = run(["log", "--root", str(project)], cwd=project)
    assert r.returncode == 0
    out = r.stdout
    # 应有 APPROVED + UNAUTHORIZED 至少各 1
    assert "APPROVED" in out
    assert "UNAUTHORIZED" in out


def test_l5_fingerprint_protects_pandaone_itself(tmp_path):
    """L5 自指纹：篡改 pandaone.py 后 CLI 应拒绝运行"""
    # 这个测试是间接的：通过 conftest.py 已验证
    # 这里只验证指纹文件存在 + 与 cli.py 一致
    fp_path = Path.home() / ".pandaone_fp.txt"
    assert fp_path.exists(), "指纹文件未生成"

    import hashlib
    expected = hashlib.sha256((ROOT / "src" / "pandaone" / "cli.py").read_bytes()).hexdigest()
    actual = fp_path.read_text(encoding="utf-8").strip()
    assert actual == expected, f"指纹不一致: 存储={actual[:16]}, 期望={expected[:16]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
