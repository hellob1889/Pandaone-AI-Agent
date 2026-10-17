"""
test_fingerprint.py
===================
RED 测试：pandaone SHA256 自指纹保护

第一性原理：
  L5 防御 = pandaone 自身的完整性保护。
  如果 agent 修改了 pandaone.py 跳过审计，必须能检测到。

机制：
  - pandaone.py 自身的 SHA256 存到 .pandaone_fp.txt
  - 每次启动比对，篡改则拒绝运行
  - 合法更新需密码（默认 0000）

测试策略：
  - 直接调用 _compute_fingerprint() / _check_fingerprint()
  - 验证指纹文件不存在时自动生成
  - 验证篡改 pandaone.py 后 _check_fingerprint() 失败
  - 验证 --update-fingerprint 默认密码可用
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PANDAX = ROOT / "src" / "pandaone" / "cli.py"  # 真正的 cli.py（不是 wrapper）
FP_PATH = Path.home() / ".pandaone_fp.txt"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PANDAX), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=15,
    )


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_fingerprint() -> str:
    """v0.7.20 P0-2: call new multi-file hash algorithm, fallback to 0.7.19 single-file hash on Exception."""
    try:
        from pandaone.cli_chunks.part_002 import compute_fingerprint as _cfp
        return _cfp()
    except Exception:
        return hashlib.sha256((ROOT / "src" / "pandaone" / "cli.py").read_bytes()).hexdigest()


def test_fingerprint_file_exists_after_run():
    """运行 CLI 后 .pandaone_fp.txt 应被创建"""
    if FP_PATH.exists():
        FP_PATH.unlink()

    run([])  # 无参数启动

    assert FP_PATH.exists(), f"指纹文件未创建: {FP_PATH}"


def test_fingerprint_matches_pandaone_py():
    """指纹文件内容应是 pandaone.py 的 SHA256"""
    if FP_PATH.exists():
        FP_PATH.unlink()
    run([])
    import json as _json
    stored_raw = FP_PATH.read_text(encoding="utf-8").strip()
    # v0.7.21.2: FP_PATH 是 json {version, hash, stored_at}, 取 hash 字段比对
    try:
        stored = _json.loads(stored_raw)["hash"]
    except (ValueError, KeyError):
        # 兼容旧裸 hex 格式
        stored = stored_raw
    expected = compute_fingerprint()
    assert stored == expected, f"指纹不匹配:\n  存储: {stored}\n  期望: {expected}"


def test_fingerprint_detects_tampering(tmp_path):
    """篡改 pandaone.py 后，启动应检测到指纹不匹配"""
    # 先确保指纹存在
    if FP_PATH.exists():
        FP_PATH.unlink()
    run([])
    assert FP_PATH.exists()

    # 备份 pandaone.py
    backup = tmp_path / "pandaone.py.bak"
    shutil.copy(PANDAX, backup)

    try:
        # 篡改：往 pandaone.py 末尾加一行注释
        with PANDAX.open("a", encoding="utf-8") as f:
            f.write("\n# TAMPERED\n")

        # 重跑，期望指纹校验失败
        r = run([])
        assert r.returncode != 0, "篡改后不应允许运行"
        assert ("指纹" in r.stdout) or ("指纹" in r.stderr) or ("TAMPER" in r.stdout) or ("mismatch" in r.stdout.lower())

    finally:
        # 还原
        shutil.copy(backup, PANDAX)
        # 重新生成指纹
        if FP_PATH.exists():
            FP_PATH.unlink()
        run([])


def test_update_fingerprint_with_default_password():
    """默认密码 0000 应能更新指纹"""
    if FP_PATH.exists():
        FP_PATH.unlink()

    r = run(["--update-fingerprint", "0000"])
    assert r.returncode == 0, f"更新失败: stderr={r.stderr}"

    # 指纹应被重写
    import json as _json2
    assert FP_PATH.exists()
    stored_raw2 = FP_PATH.read_text(encoding="utf-8").strip()
    try:
        stored2 = _json2.loads(stored_raw2)["hash"]
    except (ValueError, KeyError):
        stored2 = stored_raw2
    assert compute_fingerprint() == stored2


def test_update_fingerprint_with_wrong_password():
    """错误密码应拒绝"""
    r = run(["--update-fingerprint", "wrong_password"])
    assert r.returncode != 0, "错误密码应被拒绝"
    assert ("密码" in r.stdout) or ("password" in r.stdout.lower())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
