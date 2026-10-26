# -*- coding: utf-8 -*-
"""
test_fp_security_v0723.py
=========================
v0.7.23: 指纹密码体系 + 全包目录 manifest 指纹 的单元测试。

覆盖：
  1. 默认密码必须是 "0000"（用户明确要求保留默认值）
  2. 环境变量优先级：PANDAONE_FP_PASSWORD > PANDAX_FP_PASSWORD(废弃别名) > 配置文件 > 默认
  3. verify_password 走 hmac.compare_digest（常量时间）
  4. 连续失败锁定 → 锁定期间正确密码也被拒 → reset_lock 解除 → 计数清零
  5. set / clear 自定义密码
  6. compute_fingerprint 覆盖**非 .py** 资源（index.html / templates/）
  7. compute_fingerprint 确定性（改回原样 → hash 复原）
  8. 排除 __pycache__ / *.pyc（否则指纹每次运行都变 = 自我失效）
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone import fp_security as fps


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """把 HOME / USERPROFILE 指到 tmp，避免污染真实的 ~/.pandaone/。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv(fps.ENV_FP_PASSWORD, raising=False)
    monkeypatch.delenv(fps.ENV_FP_PASSWORD_LEGACY, raising=False)
    return home


# ---------------------------------------------------------------------------
# 1) 默认密码
# ---------------------------------------------------------------------------

def test_default_password_is_0000():
    """用户明确要求：默认密码必须是 0000。"""
    assert fps.DEFAULT_FP_PASSWORD == "0000"
    assert fps.get_fingerprint_password() == "0000"


# ---------------------------------------------------------------------------
# 2) 优先级
# ---------------------------------------------------------------------------

def test_new_env_var_wins(monkeypatch):
    monkeypatch.setenv(fps.ENV_FP_PASSWORD, "from_new")
    monkeypatch.setenv(fps.ENV_FP_PASSWORD_LEGACY, "from_legacy")
    assert fps.get_fingerprint_password() == "from_new"


def test_legacy_env_var_still_works(monkeypatch):
    """旧名 PANDAX_FP_PASSWORD 是废弃别名，但必须仍能工作（不打断存量脚本）。"""
    monkeypatch.setenv(fps.ENV_FP_PASSWORD_LEGACY, "from_legacy")
    assert fps.get_fingerprint_password() == "from_legacy"


def test_password_file_used_when_no_env(monkeypatch):
    fps.set_fingerprint_password("from_file")
    assert fps.get_fingerprint_password() == "from_file"


def test_env_beats_password_file(monkeypatch):
    fps.set_fingerprint_password("from_file")
    monkeypatch.setenv(fps.ENV_FP_PASSWORD, "from_env")
    assert fps.get_fingerprint_password() == "from_env"


def test_clear_password_falls_back_to_default():
    fps.set_fingerprint_password("from_file")
    fps.clear_fingerprint_password()
    assert fps.get_fingerprint_password() == "0000"


def test_set_password_writes_file_and_clear_removes():
    p = fps.set_fingerprint_password("abc12345")
    assert p.is_file()
    assert p.read_text(encoding="utf-8") == "abc12345"
    fps.clear_fingerprint_password()
    assert not p.exists()


def test_set_password_rejects_empty():
    with pytest.raises(ValueError):
        fps.set_fingerprint_password("")


# ---------------------------------------------------------------------------
# 3) 常量时间比较
# ---------------------------------------------------------------------------

def test_verify_password_correct_and_wrong():
    assert fps.verify_password("0000", "0000") is True
    assert fps.verify_password("0001", "0000") is False


def test_verify_password_tolerates_non_str():
    assert fps.verify_password(None, "0000") is False
    assert fps.verify_password(1234, "1234") is True


def test_verify_password_uses_hmac_compare_digest(monkeypatch):
    """确保真的走 hmac.compare_digest，而不是明文 !=。"""
    called = {}

    def _fake(a, b):
        called["args"] = (a, b)
        return True

    monkeypatch.setattr(fps.hmac, "compare_digest", _fake)
    assert fps.verify_password("x", "y") is True
    assert called["args"] == (b"x", b"y")


# ---------------------------------------------------------------------------
# 4) 失败锁定
# ---------------------------------------------------------------------------

def test_failure_lockout_triggers_after_max_failures():
    for _ in range(fps.FP_MAX_FAILURES):
        fps.register_failure()
    locked, remain = fps.fp_lock_state()
    assert locked is True
    assert remain > 0


def test_lock_state_clear_after_reset():
    for _ in range(fps.FP_MAX_FAILURES):
        fps.register_failure()
    assert fps.fp_lock_state()[0] is True
    fps.reset_lock()
    assert fps.fp_lock_state()[0] is False


def test_successful_password_clears_failure_count():
    fps.register_failure()
    fps.register_failure()
    fps.clear_failures()
    assert fps.read_lock_state().get("fail_count", 0) == 0
    assert fps.fp_lock_state()[0] is False


def test_lock_state_unlocked_initially():
    assert fps.fp_lock_state() == (False, 0)


# ---------------------------------------------------------------------------
# 5) 指纹覆盖面
# ---------------------------------------------------------------------------

def test_fingerprint_scope_covers_both_packages():
    scope = fps.fingerprint_scope()
    assert scope["file_count"] > 0
    assert "pandaone" in scope["packages"]
    assert "pandaone_guard" in scope["packages"]


def test_fingerprint_is_deterministic():
    assert fps.compute_fingerprint() == fps.compute_fingerprint()


def test_fingerprint_covers_non_py_resource():
    """v0.7.23 核心：改 index.html（非 .py）必须改变指纹。

    v0.7.20~v0.7.22 只哈希 *.py，资源文件被改 → 指纹不变 → L5 被绕过。
    """
    target = SRC / "pandaone" / "index.html"
    if not target.is_file():
        pytest.skip("index.html 不在源码树中")
    before = fps.compute_fingerprint()
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n<!-- probe -->\n")
        assert fps.compute_fingerprint() != before, "改非 .py 资源文件未改变指纹"
    finally:
        target.write_bytes(original)
    assert fps.compute_fingerprint() == before, "还原后指纹未复原（不确定性）"


def test_fingerprint_excludes_pycache():
    """__pycache__ / *.pyc 是运行时产物，纳入会让指纹每次运行都变。"""
    roots = fps.fingerprint_roots()
    assert roots, "未找到任何包目录"
    for root in roots:
        for rel in fps._iter_manifest_files(root):
            assert "__pycache__" not in rel
            assert not rel.endswith(".pyc")
            assert not rel.endswith(".pyo")


def test_fingerprint_roots_are_real_dirs():
    for r in fps.fingerprint_roots():
        assert r.is_dir()
        assert r.name in ("pandaone", "pandaone_guard")


# ---------------------------------------------------------------------------
# 6) 指纹文件读写
# ---------------------------------------------------------------------------

def test_save_and_load_fp_roundtrip(tmp_path):
    p = tmp_path / "fp.txt"
    fps.save_fp("0.7.23.0", "a" * 64, path=p)
    version, h, migrated = fps.load_fp(path=p)
    assert version == "0.7.23.0"
    assert h == "a" * 64
    assert migrated is False


def test_load_fp_migrates_legacy_raw_hex(tmp_path):
    p = tmp_path / "fp.txt"
    p.write_text("b" * 64, encoding="utf-8")
    version, h, migrated = fps.load_fp(path=p)
    assert migrated is True
    assert h == "b" * 64
    assert version == "0.0.0+legacy"


def test_load_fp_rejects_corrupted(tmp_path):
    p = tmp_path / "fp.txt"
    p.write_text("not-a-fingerprint", encoding="utf-8")
    with pytest.raises(ValueError):
        fps.load_fp(path=p)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
