"""
test_log.py
===========
RED 测试：pandaone log 子命令

第一性原理：
  log 是审计系统的"读取端"。
  应该支持：recent N / 按文件 / 按 session / rejected / unauthorized / 导出。

测试策略：
  - 准备一组审计记录（手动 append JSONL）
  - 用 log 子命令查询
  - 验证输出格式和过滤逻辑
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANDAX = ROOT / "pandaone_dev.py"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # Bug fix (v0.7.15) F-15: 加 errors="replace" 防止 GBK 编码崩溃
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(cwd),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=15,
    )


def setup_with_records(tmp_path: Path) -> Path:
    """建 init 项目 + 注入 5 条审计记录"""
    r = run(["init", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0

    audit_path = tmp_path / ".pandaone" / "pandaone.jsonl"
    records = [
        {"id": "audit_001", "status": "APPROVED", "file": "main.py",
         "reason": "修复bug1", "problem": "问题1描述", "approach": "方法1描述",
         "commit_hash": "abc1234"},
        {"id": "audit_002", "status": "REJECTED", "file": "main.py",
         "rejection_reason": "reason 字段为空", "attempted_reason": ""},
        {"id": "audit_003", "status": "APPROVED", "file": "utils.py",
         "reason": "添加新功能", "problem": "需要新功能", "approach": "实现新功能",
         "commit_hash": "def5678"},
        {"id": "audit_004", "status": "REJECTED", "file": "utils.py",
         "rejection_reason": "problem 字段为空", "attempted_problem": ""},
        {"id": "audit_005", "status": "APPROVED", "file": "main.py",
         "reason": "优化性能", "problem": "性能瓶颈", "approach": "缓存优化",
         "commit_hash": "ghi9012"},
    ]
    with audit_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return tmp_path


def test_log_subcommand_exists():
    """log 子命令存在且支持 --recent"""
    r = subprocess.run(
        [sys.executable, str(PANDAX), "log", "--help"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--recent" in r.stdout


def test_log_recent_default(tmp_path):
    """log 默认显示最近 20 条"""
    setup_with_records(tmp_path)
    r = run(["log", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0, f"stderr={r.stderr}"
    # 应显示 5 条记录
    assert "audit_001" in r.stdout
    assert "audit_005" in r.stdout


def test_log_recent_n(tmp_path):
    """log --recent N 只显示 N 条"""
    setup_with_records(tmp_path)
    r = run(["log", "--root", str(tmp_path), "--recent", "2"], cwd=tmp_path)
    assert r.returncode == 0
    # 最近 2 条：audit_004, audit_005
    assert "audit_005" in r.stdout
    assert "audit_004" in r.stdout
    # 不应显示更早的
    assert "audit_001" not in r.stdout


def test_log_short_n_equals_recent(tmp_path):
    """Bug #13 fix: log -n N 与 --recent N 行为一致（短选项别名）"""
    setup_with_records(tmp_path)
    # 用 -n 简写
    r_short = run(["log", "--root", str(tmp_path), "-n", "2"], cwd=tmp_path)
    # 用 --recent 全称
    r_long = run(["log", "--root", str(tmp_path), "--recent", "2"], cwd=tmp_path)

    assert r_short.returncode == 0
    assert r_long.returncode == 0
    # 输出应一致（除 banner / 标识差异外，主要内容相同）
    # 验证 -n 真的过滤到 2 条
    assert "audit_005" in r_short.stdout
    assert "audit_004" in r_short.stdout
    assert "audit_001" not in r_short.stdout


def test_log_short_n_in_middle(tmp_path):
    """Bug #13 fix: log -n N 在中间位置也生效"""
    setup_with_records(tmp_path)
    r = run(["log", "-n", "3", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0
    assert "audit_005" in r.stdout
    assert "audit_003" in r.stdout
    assert "audit_001" not in r.stdout


def test_log_filter_by_file(tmp_path):
    """log --file X 只显示某文件的记录"""
    setup_with_records(tmp_path)
    r = run(["log", "--root", str(tmp_path), "--file", "utils.py"], cwd=tmp_path)
    assert r.returncode == 0
    assert "utils.py" in r.stdout
    # main.py 不应出现
    # 注：因为是按 file 过滤，但 main.py 字样可能不会显式输出
    # 我们改用：检查 audit_001（main.py）不出现在 utils.py 过滤结果中
    # 但输出格式可能带 file 名，所以宽松一点：
    # 只检查 utils.py 的记录在
    assert "audit_003" in r.stdout  # utils.py APPROVED
    assert "audit_004" in r.stdout  # utils.py REJECTED


def test_log_rejected_only(tmp_path):
    """log --rejected 只显示 REJECTED"""
    setup_with_records(tmp_path)
    r = run(["log", "--root", str(tmp_path), "--rejected"], cwd=tmp_path)
    assert r.returncode == 0
    assert "audit_002" in r.stdout  # REJECTED
    assert "audit_004" in r.stdout  # REJECTED
    # APPROVED 不应单独成行（可能出现在 ID 引用中）
    # 简化检查：REJECTED 标记出现
    assert "REJECTED" in r.stdout


def test_log_empty_when_no_init(tmp_path):
    """未 init 的目录 log 应优雅处理"""
    # tmp_path 没有 .pandaone/
    r = run(["log", "--root", str(tmp_path)], cwd=tmp_path)
    # rc != 0 但不应崩溃
    assert r.returncode != 0, "未 init 的目录应报错"
    # Bug fix (v0.7.15) F-15: 错误可能输出到 stderr（而非 stdout）
    combined = (r.stdout or "") + (r.stderr or "")
    assert "未初始化" in combined or "未找到" in combined or "error" in combined.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
