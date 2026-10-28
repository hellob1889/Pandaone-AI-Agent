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


# ---------------------------------------------------------------------------
# v0.7.25.0 回归：沙盒端到端挖出的两个真 bug
#   1) 既有 pandaone 条目里的 env 被整条替换清空（用户数据丢失）
#   2) 打包形态下写进配置的 command 是裸名，PATH 命中旧版 MCP（版本错配）
# ---------------------------------------------------------------------------

def test_install_into_merges_existing_env(tmp_path):
    """既有 pandaone 条目里的 env 必须保留（只补不缺，不删已有键）。"""
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"pandaone": {
        "command": "old-cmd", "env": {"KEEP_ME": "1", "API_KEY": "secret"}}}}),
        encoding="utf-8")
    result = mcp.install_into(path, "pandaone-mcp")
    assert result["updated"] is True
    entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["pandaone"]
    assert entry["env"]["KEEP_ME"] == "1"
    assert entry["env"]["API_KEY"] == "secret"
    assert entry["command"] == "pandaone-mcp"   # command 照旧更新


def test_install_into_preserves_existing_args(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"pandaone": {
        "command": "old-cmd", "args": ["--flag", "value"]}}}), encoding="utf-8")
    mcp.install_into(path, "pandaone-mcp")
    entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["pandaone"]
    assert entry["args"] == ["--flag", "value"]


def test_resolve_command_prefers_sibling_exe_in_frozen_build(monkeypatch, tmp_path):
    """打包形态：即便 PATH 里有旧的 pandaone-mcp，也必须锁同目录的绝对路径。"""
    sibling = tmp_path / "pandaone-mcp.exe"
    sibling.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pandaone.exe"))
    monkeypatch.setattr(mcp.shutil, "which", lambda n: r"C:\old\Scripts\pandaone-mcp.exe")
    cmd, fell_back = mcp.resolve_command(False)
    assert Path(cmd) == sibling.resolve()
    assert Path(cmd).is_absolute()
    assert fell_back is True


def test_resolve_command_absolute_flag_does_not_consult_path(monkeypatch, tmp_path):
    """绝对路径模式不应该去查 PATH —— 否则会锁到旧版 MCP。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    calls = []

    def _which(name):
        calls.append(name)
        return r"C:\old\Scripts\pandaone-mcp.exe"

    monkeypatch.setattr(mcp.shutil, "which", _which)
    mcp.resolve_command(True)
    assert calls == [], "absolute mode must not consult PATH"
    mcp.resolve_command(False)
    assert calls == ["pandaone-mcp"], "normal mode should consult PATH"


def test_auto_registers_installed_ide_without_existing_config(tmp_path, monkeypatch):
    """装了 IDE 但还没配置文件时，--client auto 也要把配置建出来。"""
    target = tmp_path / "cursor" / "mcp.json"
    monkeypatch.setattr(mcp, "candidate_configs", lambda: {"cursor": target})
    monkeypatch.setattr(mcp, "_ide_installed", lambda name: name == "cursor")
    monkeypatch.setattr(mcp, "resolve_command", lambda absolute=False: ("pandaone-mcp", False))
    args = SimpleNamespace(client="auto", dry_run=False, no_backup=False, absolute_command=False)
    rc = mcp.handler(args)
    assert rc == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "pandaone" in data["mcpServers"]


# ---------------------------------------------------------------------------
# v0.7.34.0 (R1) 回归：老版本写进 IDE 配置的**裸名**必须被纠正成绝对路径
#
# 背景：0.7.21.3 时代写进 IDE 配置的 command 是裸名 `pandaone-mcp`（走
#       shutil.which 分支）。0.7.25.0 引入 --absolute-command 写绝对路径，
#       但只有 install-mcp **真的执行**时才会生效。安装器静默安装时
#       跳过了 install-mcp -> 裸名一直留着 -> IDE 按 PATH 命中旧 pip 版
#       MCP -> 0.7.31.0 修的 GBK/UTF-8 编码 bug 对用户继续生效。
#
# 这里锁死 install_into 的语义：**总是**改写 command（不是"仅新建时写"），
# 否则老用户的配置永远得不到纠正。
# ---------------------------------------------------------------------------

def test_absolute_command_rewrites_legacy_bare_name(tmp_path, monkeypatch):
    """配置已存在且 command 是裸名时，--absolute-command 必须把它改成绝对路径。"""
    appdir = tmp_path / "Pandaone"
    appdir.mkdir()
    (appdir / "pandaone-mcp.exe").write_bytes(b"MZ")
    # 打包形态：同目录的绝对路径优先于 PATH 里的旧 pip 版
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(appdir), raising=False)
    monkeypatch.setattr(sys, "executable", str(appdir / "pandaone.exe"))
    monkeypatch.setattr(mcp.shutil, "which", lambda n: r"C:\old\Scripts\pandaone-mcp.exe")

    target = tmp_path / "cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    # 0.7.21.3 时代写进去的老配置：command 是裸名
    target.write_text(
        json.dumps({"mcpServers": {"pandaone": {"command": "pandaone-mcp", "env": {}}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mcp, "candidate_configs", lambda: {"cursor": target})
    args = SimpleNamespace(client="cursor", dry_run=False, no_backup=False, absolute_command=True)
    rc = mcp.handler(args)
    assert rc == 0

    entry = json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["pandaone"]
    expected = str((appdir / "pandaone-mcp.exe").resolve())
    assert entry["command"] == expected, (
        f"老配置里的裸名必须被改写成绝对路径，实际: {entry['command']!r}"
    )
    assert Path(entry["command"]).is_absolute()


def test_absolute_command_keeps_user_env_while_rewriting_command(tmp_path, monkeypatch):
    """改写 command 的同时不能清掉用户自己配的 env（API key 等）。"""
    appdir = tmp_path / "Pandaone"
    appdir.mkdir()
    (appdir / "pandaone-mcp.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(appdir), raising=False)
    monkeypatch.setattr(sys, "executable", str(appdir / "pandaone.exe"))

    target = tmp_path / "cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"mcpServers": {"pandaone": {
            "command": "pandaone-mcp",
            "env": {"PANDAONE_FP_PASSWORD": "secret"}}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mcp, "candidate_configs", lambda: {"cursor": target})
    args = SimpleNamespace(client="cursor", dry_run=False, no_backup=False, absolute_command=True)
    rc = mcp.handler(args)
    assert rc == 0

    entry = json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["pandaone"]
    assert entry["command"] == str((appdir / "pandaone-mcp.exe").resolve())
    assert entry["env"]["PANDAONE_FP_PASSWORD"] == "secret", "用户 env 不能被清空"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
