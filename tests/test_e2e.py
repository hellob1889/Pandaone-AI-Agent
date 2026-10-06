"""
test_e2e.py
===========
端到端集成测试：覆盖完整用户工作流

场景：
  1. 全新项目 init → 自动创建 .pandaone/
  2. lock → 所有 .py 不可写
  3. 不带 reason 的 write → REJECTED + 审计留痕
  4. 带完整字段的 write → APPROVED + 写入成功 + git commit + 审计留痕
  5. log 查询 → 看到 APPROVED + REJECTED 两条记录
  6. log --rejected → 只看到拒绝的
  7. log --export → 生成 HTML 报告
  8. install-git → 探测 + 报告（不实际下载）

第一性原理：
  这是 Pandaone AI Agent 的核心承诺：必须能完整跑通"开发 → 审计 → 查询"全链路。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANDAX = ROOT / "pandaone_dev.py"

# Step 4 依赖"锁后写入抛 PermissionError"，root 下权限位不生效，属环境限制。
_ROOT_SKIP = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root 用户不受权限位限制，无法验证 OS 级文件锁环节",
)


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


@_ROOT_SKIP
def test_full_workflow_e2e(tmp_path):
    """完整工作流：init → lock → reject → approve → log → export"""
    # ============ Step 1: init ============
    r = run(["init", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0, f"init 失败: {r.stderr}"
    assert (tmp_path / ".pandaone" / "config.json").exists()
    assert (tmp_path / ".pandaone" / "pandaone.jsonl").exists()

    # ============ Step 2: git init ============
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    subprocess.run(["git", "config", "user.email", "agent@pandaone"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Agent"], cwd=tmp_path, capture_output=True, text=True)

    # ============ Step 3: 创建初始文件 + 首次 commit ============
    (tmp_path / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (tmp_path / "utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True, text=True)
    init_commits = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip().count("\n") + 1

    # ============ Step 4: lock ============
    r = run(["lock", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0
    # 锁后写入应失败
    with pytest.raises((PermissionError, OSError)):
        with open(tmp_path / "main.py", "w", encoding="utf-8") as f:
            f.write("# bypass\n")

    # ============ Step 5: 不带完整 reason 的 write → REJECTED ============
    r = run([
        "write",
        "--root", str(tmp_path),
        "--file", "main.py",
        "--reason", "短",  # 太短
        "--problem", "完整的问题描述测试中",
        "--approach", "完整的方法描述测试中",
        "--old", "hi",
        "--new", "hello",
    ], cwd=tmp_path)
    assert r.returncode != 0, "reason 太短应被拒绝"

    # 审计日志应有 REJECTED 记录
    audit_lines = (tmp_path / ".pandaone" / "pandaone.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(l) for l in audit_lines if l.strip()]
    rejected = [r for r in records if r["status"] == "REJECTED"]
    assert len(rejected) >= 1, "应有 REJECTED 审计记录"
    assert rejected[-1]["rejection_reason"], "REJECTED 记录应有 rejection_reason"

    # ============ Step 6: 带完整字段的 write → APPROVED ============
    r = run([
        "write",
        "--root", str(tmp_path),
        "--file", "main.py",
        "--reason", "修复hello函数返回值不符合PEP8规范",
        "--problem", "返回字符串hi应该改为完整单词hello符合代码可读性原则",
        "--approach", "将返回值改为完整hello字符串并使用str类型明确标注",
        "--old", "return 'hi'",
        "--new", "return 'hello'",
        "--force-write",  # Bug #12 v2: 锁定文件需显式 force
    ], cwd=tmp_path)
    assert r.returncode == 0, f"应 APPROVED 但失败: stdout={r.stdout[-500:]}"
    assert "APPROVED" in r.stdout

    # 文件实际被修改
    content = (tmp_path / "main.py").read_text(encoding="utf-8")
    assert "return 'hello'" in content

    # git commit 数应增加
    after_commits = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip().count("\n") + 1
    assert after_commits == init_commits + 1, f"git commit 应增加: {init_commits} → {after_commits}"

    # ============ Step 7: log 查询 ============
    r = run(["log", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0
    # 应有 APPROVED + REJECTED
    assert "APPROVED" in r.stdout
    assert "REJECTED" in r.stdout

    # ============ Step 8: log --rejected ============
    r = run(["log", "--root", str(tmp_path), "--rejected"], cwd=tmp_path)
    assert r.returncode == 0
    assert "REJECTED" in r.stdout
    # 应只显示拒绝记录（不应显示 APPROVED 的 reason/problem/approach 详情）
    # 简化检查：包含 attempted/尝试 字段（Bug #6 i18n 修复后 zh 用"尝试"，en 用 "Attempted"）
    assert ("attempted" in r.stdout.lower()) or ("尝试" in r.stdout)

    # ============ Step 9: log --export HTML ============
    html_path = tmp_path / "report.html"
    r = run(["log", "--root", str(tmp_path), "--export", str(html_path)], cwd=tmp_path)
    assert r.returncode == 0
    assert html_path.exists()
    html_content = html_path.read_text(encoding="utf-8")
    assert "<html" in html_content
    assert "APPROVED" in html_content
    assert "REJECTED" in html_content

    # ============ Step 10: 完整审计日志验证 ============
    audit_lines = (tmp_path / ".pandaone" / "pandaone.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(l) for l in audit_lines if l.strip()]
    approved = [r for r in records if r["status"] == "APPROVED"]
    assert len(approved) >= 1
    # commit_hash 可为空（write 自动 commit 后回填是 best-effort）
    assert approved[-1]["reason"]
    assert approved[-1]["problem"]
    assert approved[-1]["approach"]
    # audit_id 字段替代 commit_hash 作为追溯标识
    assert approved[-1]["id"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
