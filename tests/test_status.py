"""
test_status.py
==============
RED 测试：pandaone status 命令

第一性原理：
  status 是"项目审计全景仪表盘"。
  应展示：L1 锁状态 / L2 watchdog 状态 / L5 指纹状态 / 审计统计 / 最近事件

测试策略：
  - 准备不同状态的项目（init / lock / 写过审计 / watchdog PID）
  - 调用 status 验证显示内容
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANDAX = ROOT / "pandaone_dev.py"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
    )


def setup(tmp_path: Path) -> Path:
    """建项目 + lock + 写入审计"""
    run(["init", "--root", str(tmp_path)], cwd=tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")
    run(["lock", "--root", str(tmp_path)], cwd=tmp_path)
    return tmp_path


def test_status_subcommand_exists():
    """status 子命令存在"""
    r = subprocess.run(
        [sys.executable, str(PANDAX), "--help"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert "status" in r.stdout


def test_status_after_init(tmp_path):
    """init 后 status 应展示基本状态"""
    setup(tmp_path)

    r = run(["status", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0, f"stderr={r.stderr}"

    # 应展示关键信息
    assert "Pandaone AI Agent" in r.stdout
    assert "L1" in r.stdout or "锁" in r.stdout or "lock" in r.stdout.lower()


def test_status_shows_watchdog_pid(tmp_path):
    """status 应展示 watchdog 状态（PID 存在/不存在）

    v0.7.35: PID 文件在、但进程已经不在 → 这是"跑过但坏了"，
    status 判 FAIL 并**退出 3**（与 doctor 的 L2 同一判据）。
    旧行为是显示"未运行"、退出 0 —— 看起来无害，其实是在说谎：
    看门狗早就没了，用户却以为保护还在生效。
    """
    setup(tmp_path)

    # 模拟 watchdog 写 PID（进程已不存在）
    pid_path = tmp_path / ".pandaone" / ".watchdog_pid"
    pid_path.write_text("12345", encoding="utf-8")

    r = run(["status", "--root", str(tmp_path)], cwd=tmp_path)
    # 看门狗层坏了 → 退出码必须非 0（与 doctor 一致）
    assert r.returncode == 3, f"看门狗层坏了必须非 0 退出:\n{r.stdout}"
    # 应展示 watchdog 状态
    assert "watchdog" in r.stdout.lower() or "L2" in r.stdout
    # 应能看到那个 PID（说明它读到了残留的 pid 文件）
    assert "12345" in r.stdout, f"status 没展示残留 PID:\n{r.stdout}"


def test_status_watchdog_not_running(tmp_path):
    """watchdog PID 不存在时 status 应提示未运行"""
    setup(tmp_path)
    # 不写 PID 文件

    r = run(["status", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0
    # 应提示 watchdog 未运行
    assert ("未运行" in r.stdout) or ("未启动" in r.stdout) or ("stopped" in r.stdout.lower())


def test_status_shows_audit_count(tmp_path):
    """status 应展示审计记录数"""
    setup(tmp_path)

    # 添加 2 条审计记录
    audit_path = tmp_path / ".pandaone" / "pandaone.jsonl"
    records = [
        {"id": "audit_001", "status": "APPROVED", "file": "main.py",
         "reason": "fix", "problem": "p", "approach": "a"},
        {"id": "audit_002", "status": "REJECTED", "file": "utils.py",
         "rejection_reason": "empty"},
    ]
    with audit_path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")

    r = run(["status", "--root", str(tmp_path)], cwd=tmp_path)
    assert r.returncode == 0
    # 应显示审计记录数
    assert "2" in r.stdout or "APPROVED" in r.stdout or "REJECTED" in r.stdout


def test_status_handles_no_init(tmp_path):
    """未 init 的目录 status 应优雅处理"""
    # tmp_path 没有 .pandaone/
    r = run(["status", "--root", str(tmp_path)], cwd=tmp_path)
    # 不应崩溃，rc != 0 + 信息提示
    assert r.returncode != 0
    # i18n: 接受中文 / 英文两种错误消息
    assert any(s in r.stdout for s in [
        "未初始化", "未找到",  # 中文
        "not initialized", "not found",  # 英文
    ])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
