# -*- coding: utf-8 -*-
"""
test_status_l5_fingerprint.py — P0 回归测试：pandaone status 的 L5 指纹比较

背景 (v0.7.22 修复):
  v0.7.21.2 把 FP_PATH 从"裸 hex"改成 json {version, hash, stored_at}，
  cmd_doctor.py 跟着改了（会用 _load_fp() 解析），但 cmd_status 没改 —— 它还在拿
  整段 json 文本去跟 hex digest 比：

      stored = FP_PATH.read_text(...).strip()   # → '{"version": "...", "hash": "..."}'
      current = compute_fingerprint()           # → 64 位 hex
      if stored == current:                    # → 永远 False

  结果：只要装过 0.7.21.2 及以上，`pandaone status` 永远报"指纹不匹配"，
  而实际文件是好的 —— 又一个"报假警报"的假阳性。

同一个事实（文件是否被篡改）在 doctor 和 status 两个入口给出两个答案，
这正是 report 抱怨的 P0-3 那类问题：防护看起来坏了，用户以为被篡改。
"""
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pandaone import cli  # noqa: E402


def _write_fp(fp_path: Path, version: str, hash_hex: str) -> None:
    fp_path.write_text(
        json.dumps(
            {"version": version, "hash": hash_hex, "stored_at": "2026-10-24T00:00:00Z"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_status_reports_ok_when_json_fingerprint_matches(tmp_path, monkeypatch, capsys):
    """json 格式的指纹与当前一致 → 必须报 OK，不能误报不匹配。"""
    root = tmp_path / "proj"
    (root / ".pandaone").mkdir(parents=True)

    fake_fp = tmp_path / "fp.txt"
    _write_fp(fake_fp, "0.7.21.3", "a" * 64)

    monkeypatch.setattr(cli, "FP_PATH", fake_fp)
    monkeypatch.setattr(cli, "compute_fingerprint", lambda: "a" * 64)

    cli.cmd_status(Namespace(root=str(root)))
    out = capsys.readouterr().out

    assert "不匹配" not in out, f"status 误报指纹不匹配:\n{out}"
    assert "完整 OK" in out, f"status 没报完整 OK:\n{out}"


def test_status_reports_mismatch_when_hash_really_differs(tmp_path, monkeypatch, capsys):
    """json 格式的指纹与当前不一致 → 必须报不匹配（不能被修复成永远 True）。"""
    root = tmp_path / "proj"
    (root / ".pandaone").mkdir(parents=True)

    fake_fp = tmp_path / "fp.txt"
    _write_fp(fake_fp, "0.7.21.3", "a" * 64)

    monkeypatch.setattr(cli, "FP_PATH", fake_fp)
    monkeypatch.setattr(cli, "compute_fingerprint", lambda: "b" * 64)

    cli.cmd_status(Namespace(root=str(root)))
    out = capsys.readouterr().out

    assert "不匹配" in out, f"status 该报不匹配却没报:\n{out}"


def test_status_still_supports_legacy_plain_hex(tmp_path, monkeypatch, capsys):
    """旧版裸 hex 格式的指纹文件要继续能读（向后兼容）。"""
    root = tmp_path / "proj"
    (root / ".pandaone").mkdir(parents=True)

    fake_fp = tmp_path / "fp.txt"
    fake_fp.write_text("c" * 64, encoding="utf-8")

    monkeypatch.setattr(cli, "FP_PATH", fake_fp)
    monkeypatch.setattr(cli, "compute_fingerprint", lambda: "c" * 64)

    cli.cmd_status(Namespace(root=str(root)))
    out = capsys.readouterr().out

    assert "不匹配" not in out, f"旧格式指纹被误判:\n{out}"
    assert "完整 OK" in out
