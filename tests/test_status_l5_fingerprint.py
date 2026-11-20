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
    """json 格式的指纹与当前一致 → 必须报 OK，不能误报不匹配。

    v0.7.35: status 与 doctor 现在**共用** health_probe.fingerprint_state，
    判据包含 form 与 version 两道闸：
      - form 不同（source ↔ frozen）→ WARN（合法部署行为，不是篡改）
      - version 不同（升级）→ WARN（CLI 会 auto-refresh 指纹，基线不可比）
      - 同版本同形态但 hash 不同 → FAIL（TAMPERED）
    所以这里必须用**当前版本**写指纹，才能落到"完全一致"这一档。
    """
    root = tmp_path / "proj"
    (root / ".pandaone").mkdir(parents=True)

    fake_fp = tmp_path / "fp.txt"
    _write_fp(fake_fp, cli._get_pandaone_version(), "a" * 64)

    monkeypatch.setattr(cli, "FP_PATH", fake_fp)
    monkeypatch.setattr(cli, "compute_fingerprint", lambda: "a" * 64)

    cli.cmd_status(Namespace(root=str(root)))
    out = capsys.readouterr().out

    assert "不匹配" not in out, f"status 误报指纹不匹配:\n{out}"
    assert "完整 OK" in out, f"status 没报完整 OK:\n{out}"


def test_status_reports_mismatch_when_hash_really_differs(tmp_path, monkeypatch, capsys):
    """**同版本**下 hash 不一致 → 必须报不匹配（不能被修复成永远 True）。"""
    root = tmp_path / "proj"
    (root / ".pandaone").mkdir(parents=True)

    fake_fp = tmp_path / "fp.txt"
    _write_fp(fake_fp, cli._get_pandaone_version(), "a" * 64)

    monkeypatch.setattr(cli, "FP_PATH", fake_fp)
    monkeypatch.setattr(cli, "compute_fingerprint", lambda: "b" * 64)

    cli.cmd_status(Namespace(root=str(root)))
    out = capsys.readouterr().out

    assert "不匹配" in out, f"status 该报不匹配却没报:\n{out}"


def test_status_warns_when_version_changed_not_tampered(tmp_path, monkeypatch, capsys):
    """版本变了（= 升级）→ 基线不可比，报 WARN，**不能**报篡改。

    为什么不能报"不匹配"：CLI 的 check_fingerprint 在版本变化时会 auto-refresh
    指纹基线，此时 hash 对不上是**正常**的，报"不匹配"就是假阳性 ——
    用户会以为工具被篡改而不再信任自检。doctor 早在 v0.7.34.0 就是这个语义，
    v0.7.35 让 status 与它对齐。
    """
    root = tmp_path / "proj"
    (root / ".pandaone").mkdir(parents=True)

    fake_fp = tmp_path / "fp.txt"
    _write_fp(fake_fp, "0.7.21.3", "a" * 64)

    monkeypatch.setattr(cli, "FP_PATH", fake_fp)
    monkeypatch.setattr(cli, "compute_fingerprint", lambda: "b" * 64)

    cli.cmd_status(Namespace(root=str(root)))
    out = capsys.readouterr().out

    assert "TAMPERED" not in out, f"版本变化被误判成篡改:\n{out}"
    assert "不匹配" not in out, f"版本变化被误报成指纹不匹配:\n{out}"
    assert "WARN" in out, f"版本变化应报 WARN:\n{out}"


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
