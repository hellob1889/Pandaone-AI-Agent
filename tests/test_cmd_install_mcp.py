# -*- coding: utf-8 -*-
"""
test_cmd_install_mcp.py — `pandaone install-mcp` 测试

重点断言（安全约束）：
  - 写前必备份
  - 只合并不覆盖（别的 MCP server 原样保留）
  - 损坏的 JSON 绝不覆盖
  - 装后回读自检
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pandaone import cmd_install_mcp as mcp


# ---------------------------------------------------------------------------
# install_into
# ---------------------------------------------------------------------------

def test_install_into_creates_config(tmp_path):
    path = tmp_path / "mcp.json"
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["error"] is None
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["pandaone"]["command"] == "pandaone-mcp"
    assert data["mcpServers"]["pandaone"]["env"] == {}


def test_install_into_keeps_other_servers(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {"mcpServers": {"other": {"command": "other-cmd"}}, "otherTop": 1},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["error"] is None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"]["command"] == "other-cmd"
    assert data["mcpServers"]["pandaone"]["command"] == "pandaone-mcp"
    assert data["otherTop"] == 1
    assert result["others"] == 1


def test_install_into_backs_up_existing(tmp_path):
    path = tmp_path / "mcp.json"
    original = json.dumps({"mcpServers": {"x": {"command": "y"}}}, ensure_ascii=False)
    path.write_text(original, encoding="utf-8")
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["backup"], "应生成备份"
    bak = Path(result["backup"])
    assert bak.is_file()
    assert bak.read_text(encoding="utf-8") == original


def test_install_into_no_backup_option(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text("{}", encoding="utf-8")
    result = mcp.install_into(path, "pandaone-mcp", do_backup=False)
    assert result["backup"] is None


def test_install_into_refuses_to_overwrite_corrupted(tmp_path):
    path = tmp_path / "mcp.json"
    broken = "{not json at all"
    path.write_text(broken, encoding="utf-8")
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["error"], "损坏配置应报错"
    assert path.read_text(encoding="utf-8") == broken, "损坏配置绝不能被覆盖"


def test_install_into_is_idempotent(tmp_path):
    path = tmp_path / "mcp.json"
    mcp.install_into(path, "pandaone-mcp")
    before = path.read_text(encoding="utf-8")
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["updated"] is False
    assert path.read_text(encoding="utf-8") == before


def test_install_into_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "mcp.json"
    result = mcp.install_into(path, "pandaone-mcp", dry_run=True)
    assert not path.exists()
    assert result["updated"] is True


def test_install_into_updates_existing_pandaone_entry(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"pandaone": {"command": "old-cmd"}}}), encoding="utf-8"
    )
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["updated"] is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["pandaone"]["command"] == "pandaone-mcp"


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def test_verify_ok(tmp_path):
    path = tmp_path / "mcp.json"
    mcp.install_into(path, "pandaone-mcp")
    ok, msg = mcp.verify(path, "pandaone-mcp")
    assert ok is True


def test_verify_detects_missing_entry(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    ok, _ = mcp.verify(path, "pandaone-mcp")
    assert ok is False


def test_verify_detects_command_mismatch(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"pandaone": {"command": "wrong"}}}), encoding="utf-8"
    )
    ok, _ = mcp.verify(path, "pandaone-mcp")
    assert ok is False


# ---------------------------------------------------------------------------
# 配置路径探测
# ---------------------------------------------------------------------------

def test_candidate_configs_contains_known_clients():
    cands = mcp.candidate_configs()
    for name in ("claude", "cursor", "trae"):
        assert name in cands
        assert isinstance(cands[name], Path)


def test_resolve_command_prefers_plain_name_when_on_path(monkeypatch):
    monkeypatch.setattr(mcp.shutil, "which", lambda n: "/usr/bin/pandaone-mcp")
    cmd, fell_back = mcp.resolve_command(False)
    assert cmd == "pandaone-mcp"
    assert fell_back is False


def test_resolve_command_falls_back_to_absolute(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp.shutil, "which", lambda n: None)
    cmd, fell_back = mcp.resolve_command(False)
    # 本机装了就用绝对路径，没装就退回名字
    if fell_back:
        assert Path(cmd).is_absolute()
    else:
        assert cmd == "pandaone-mcp"


# ---------------------------------------------------------------------------
# handler
# ---------------------------------------------------------------------------

def test_handler_dry_run_leaves_files_alone(tmp_path, monkeypatch, capsys):
    target = tmp_path / "cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"mcpServers": {"keep": {"command": "k"}}}), encoding="utf-8")
    original = target.read_text(encoding="utf-8")
    monkeypatch.setattr(
        mcp, "candidate_configs", lambda: {"cursor": target}
    )
    args = SimpleNamespace(client="cursor", dry_run=True, no_backup=False, absolute_command=False)
    rc = mcp.handler(args)
    assert rc == 0
    assert target.read_text(encoding="utf-8") == original


def test_handler_writes_and_verifies(tmp_path, monkeypatch):
    target = tmp_path / "cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    monkeypatch.setattr(mcp, "candidate_configs", lambda: {"cursor": target})
    args = SimpleNamespace(client="cursor", dry_run=False, no_backup=False, absolute_command=False)
    rc = mcp.handler(args)
    assert rc == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "pandaone" in data["mcpServers"]


def test_handler_reports_corrupted_config(tmp_path, monkeypatch, capsys):
    target = tmp_path / "cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(mcp, "candidate_configs", lambda: {"cursor": target})
    args = SimpleNamespace(client="cursor", dry_run=False, no_backup=False, absolute_command=False)
    rc = mcp.handler(args)
    assert rc == 1
    assert target.read_text(encoding="utf-8") == "{broken"


def test_command_is_registered():
    import pandaone.__main__ as m

    m._ensure_doctor_registered()
    from pandaone import cli

    assert "install-mcp" in cli.COMMANDS
    assert cli.COMMANDS["install-mcp"] is mcp.handler


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
