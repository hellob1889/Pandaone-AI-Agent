# -*- coding: utf-8 -*-
"""v0.7.21.2: 指纹存版本号 + default auto-refresh 测试.

老八 v0.7.21.2 实施: check_fingerprint 改 json 格式 {version, hash, stored_at}.
默认 mismatch + version 变 → auto-refresh (True). strict=True → 锁传统 (False).
旧裸 hex 自动迁移. 验 5 项.
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from pandaone import i18n
from pandaone.cli_chunks import part_001, part_002


def test_v0721_2_info_fp_auto_refreshed_exists_zh():
    """v0.7.21.2: info_fp_auto_refreshed key 存在 (zh)."""
    zh = i18n.TRANSLATIONS["zh-CN"]
    assert "info_fp_auto_refreshed" in zh
    assert "{old_version}" in zh["info_fp_auto_refreshed"]
    assert "{new_version}" in zh["info_fp_auto_refreshed"]
    assert "{hash}" in zh["info_fp_auto_refreshed"]


def test_v0721_2_info_fp_auto_refreshed_exists_en():
    """v0.7.21.2: info_fp_auto_refreshed key 存在 (en)."""
    en = i18n.TRANSLATIONS["en"]
    assert "info_fp_auto_refreshed" in en
    assert "{old_version}" in en["info_fp_auto_refreshed"]
    assert "{new_version}" in en["info_fp_auto_refreshed"]
    assert "{hash}" in en["info_fp_auto_refreshed"]


def test_v0721_2_err_fp_strict_mismatch_exists():
    """v0.7.21.2: err_fp_strict_mismatch key 存在 (zh + en)."""
    for lang in ("zh-CN", "en"):
        d = i18n.TRANSLATIONS[lang]
        assert "err_fp_strict_mismatch" in d, f"missing in {lang}"
        assert "{old_hash}" in d["err_fp_strict_mismatch"]
        assert "{new_hash}" in d["err_fp_strict_mismatch"]


def test_v0721_2_check_fingerprint_default_auto_refresh_on_version_change():
    """v0.7.21.2: 默认模式 hash mismatch + version 变 → auto-refresh (True)."""
    with tempfile.TemporaryDirectory() as tmp:
        fp_path = Path(tmp) / ".pandaone_fp.txt"
        # FP_PATH + t() 都在 part_001, cli.py loader 共享 namespace.
        # 测试直接 import part_002 没 part_001 globals, 用 create=True 注入.
        with mock.patch.object(part_002, "FP_PATH", fp_path, create=True), \
             mock.patch.object(part_002, "t", i18n.t, create=True):
            fp_path.write_text(
                json.dumps({
                    "version": "0.7.20",
                    "hash": "0" * 64,
                    "stored_at": "2026-10-17T00:00:00Z",
                }),
                encoding="utf-8",
            )
            with mock.patch.object(part_002, "compute_fingerprint", return_value="f" * 64), \
                 mock.patch.object(part_002, "_get_pandaone_version", return_value="0.7.21.2"):
                result = part_002.check_fingerprint()
                assert result is True
                new_data = json.loads(fp_path.read_text(encoding="utf-8"))
                assert new_data["version"] == "0.7.21.2"
                assert new_data["hash"] == "f" * 64


def test_v0721_2_check_fingerprint_strict_blocks_version_change():
    """v0.7.21.2: strict=True 模式任何 mismatch 都报 ERROR (False)."""
    with tempfile.TemporaryDirectory() as tmp:
        fp_path = Path(tmp) / ".pandaone_fp.txt"
        with mock.patch.object(part_002, "FP_PATH", fp_path, create=True), \
             mock.patch.object(part_002, "t", i18n.t, create=True):
            fp_path.write_text(
                json.dumps({
                    "version": "0.7.20",
                    "hash": "0" * 64,
                    "stored_at": "2026-10-17T00:00:00Z",
                }),
                encoding="utf-8",
            )
            with mock.patch.object(part_002, "compute_fingerprint", return_value="f" * 64), \
                 mock.patch.object(part_002, "_get_pandaone_version", return_value="0.7.21.2"):
                result = part_002.check_fingerprint(strict=True)
                assert result is False
