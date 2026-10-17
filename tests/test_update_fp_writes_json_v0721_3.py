# -*- coding: utf-8 -*-
"""v0.7.21.3: --update-fingerprint handler 写 json 格式 (修 cosmetic bug).

老八 v0.7.21.2 实施 check_fingerprint 改 json 格式 {version, hash, stored_at}, 但
part_006.py 的 2 处 `FP_PATH.write_text(new_fp, encoding="utf-8")` (在
--update-fingerprint handler 和 trust_default 路径) 漏改, 仍写裸 hex.

v0.7.21.3 修真: 改 2 处走 _save_fp (json 格式).

本测试验证: 模拟 --update-fingerprint trigger 后, FP_PATH 内容是合法 json
且含 required keys (version, hash, stored_at).
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from pandaone import i18n
from pandaone.cli_chunks import part_001, part_002, part_006


def test_v0721_3_update_fingerprint_writes_json_format(tmp_path):
    """v0.7.21.3: --update-fingerprint 后 FP_PATH 是 json {version, hash, stored_at}."""
    fp_path = tmp_path / ".pandaone_fp.txt"
    fp_hash = "a" * 64
    fake_version = "0.7.21.3"

    # part_006 main() 走 cli.py loader 共享 namespace, 直接 import 需注入
    # 必要的全局 (FP_PATH / t() / compute_fingerprint / get_fingerprint_password /
    # _save_fp / _get_pandaone_version / check_fingerprint / COMMANDS 等).
    with mock.patch.object(part_006, "FP_PATH", fp_path, create=True), \
         mock.patch.object(part_006, "t", i18n.t, create=True), \
         mock.patch.object(part_006, "compute_fingerprint", return_value=fp_hash, create=True), \
         mock.patch.object(part_006, "_get_pandaone_version", return_value=fake_version, create=True), \
         mock.patch.object(part_006, "_save_fp", wraps=part_002._save_fp, create=True), \
         mock.patch.object(part_006, "get_fingerprint_password", return_value="0000", create=True):
        # 模拟 --update-fingerprint 0000 触发 handler
        rc = part_006.main(argv=["--update-fingerprint", "0000"])
        assert rc == 0, f"main() 退出码 {rc}, 期望 0"
        assert fp_path.exists(), f"FP_PATH {fp_path} 未创建"

        # 读 FP_PATH 内容必须是合法 json 且含 required keys
        raw = fp_path.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            pytest.fail(f"v0.7.21.3: FP_PATH 不是合法 json: {raw!r}\n{e}")

        assert "version" in data, f"missing 'version' key, got keys: {list(data.keys())}"
        assert "hash" in data, f"missing 'hash' key, got keys: {list(data.keys())}"
        assert "stored_at" in data, f"missing 'stored_at' key, got keys: {list(data.keys())}"
        assert data["version"] == fake_version
        assert data["hash"] == fp_hash
        # stored_at 是 ISO 8601 UTC 字符串
        assert data["stored_at"].endswith("Z"), f"stored_at 应以 Z 结尾: {data['stored_at']}"


def test_v0721_3_trust_default_writes_json_format(tmp_path):
    """v0.7.21.3: trust_default 自动 update-fp 后 FP_PATH 是 json 格式."""
    fp_path = tmp_path / ".pandaone_fp.txt"
    fp_hash = "b" * 64
    fake_version = "0.7.21.3"

    # 预置旧 json 触发 check_fingerprint, force mismatch + version 变 → trust_default
    # 路径会重新 compute + 写新 hash.
    with mock.patch.object(part_006, "FP_PATH", fp_path, create=True), \
         mock.patch.object(part_006, "t", i18n.t, create=True), \
         mock.patch.object(part_006, "compute_fingerprint", return_value=fp_hash, create=True), \
         mock.patch.object(part_006, "_get_pandaone_version", return_value=fake_version, create=True), \
         mock.patch.object(part_006, "_save_fp", wraps=part_002._save_fp, create=True), \
         mock.patch.object(part_006, "get_fingerprint_password", return_value="0000", create=True):
        # 提前写入旧 json (低版本 + 错 hash), 触发 check_fingerprint mismatch
        fp_path.parent.mkdir(parents=True, exist_ok=True)
        fp_path.write_text(
            json.dumps({
                "version": "0.7.20",
                "hash": "0" * 64,
                "stored_at": "2026-10-17T00:00:00Z",
            }),
            encoding="utf-8",
        )
        # 触发 check_fingerprint 在 silent=True 模式下因 mismatch 返回 False
        # (因为 version 变)  — 但 trust_default 不允许 silent. 改用普通调用.
        # 实际 trust_default 走: check_fingerprint(silent=True) → False → compute + 写
        # 我们直接 mock check_fingerprint 返回 False 模拟 mismatch 已检测到.
        with mock.patch.object(part_006, "check_fingerprint", return_value=False, create=True):
            rc = part_006.main(argv=["--trust-default"])
            assert rc is None or isinstance(rc, int), f"unexpected rc: {rc}"

        assert fp_path.exists()

        raw = fp_path.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            pytest.fail(f"v0.7.21.3 (trust_default): FP_PATH 不是合法 json: {raw!r}\n{e}")
        assert data["version"] == fake_version
        assert data["hash"] == fp_hash


def test_v0721_3_no_bare_hex_in_part_006():
    """v0.7.21.3: part_006.py 不应再出现 `write_text(new_fp` 裸 hex 写入."""
    src = Path(r"D:\绿联云办公\项目 水龙头项目 CodeAudit_项目文档\src\pandaone\cli_chunks\part_006.py")
    text = src.read_text(encoding="utf-8")
    # v0.7.21.3 fix: 应改 _save_fp 走 json 格式, 不应再 raw write_text
    assert "write_text(new_fp" not in text, (
        "v0.7.21.3: part_006.py 含 'write_text(new_fp' 残留 — "
        "应改 _save_fp(_get_pandaone_version(), new_fp)"
    )
