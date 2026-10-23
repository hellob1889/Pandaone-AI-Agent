# -*- coding: utf-8 -*-
"""
cmd_install_mcp.py — `pandaone install-mcp`：把 MCP 服务器写进 IDE 配置

对应「GitHub 一键下载 → 安装 → 自动注册 MCP → 真实握手」的完整链路里
缺失的最后一环。

为什么需要
----------
装完 pandaone 之后，用户还得手工去改 IDE 的 MCP 配置：
    {"mcpServers": {"pandaone": {"command": "pandaone-mcp", "env": {}}}}
很多人不知道这一步，AI Agent 那条线就断在这里。

安全约束
--------
- **写前必备份**：原文件另存为 ``<file>.bak.<时间戳>``
- **只合并不覆盖**：只动 ``mcpServers.pandaone``，别的 server 原样保留
- **损坏不写**：原配置不是合法 JSON 时直接报错退出，绝不覆盖用户数据
- **装后自检**：写完回读校验，通过才报"安装完成"
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def _t(key: str, **kw) -> str:
    try:
        from pandaone.i18n import t

        return t(key, **kw)
    except Exception:
        return key


COMMAND_NAME = "install-mcp"

#: MCP 服务器在配置里的键名
SERVER_KEY = "pandaone"


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / ".config")


def candidate_configs() -> dict[str, Path]:
    """返回 {客户端名: 配置文件路径}（路径是"应该在哪"，不保证存在）。"""
    home = Path.home()
    appdata = _appdata()
    if sys.platform.startswith("win"):
        claude = appdata / "Claude" / "claude_desktop_config.json"
        trae = appdata / "Trae" / "User" / "mcp.json"
        windsurf = home / ".codeium" / "windsurf" / "mcp.json"
    elif sys.platform == "darwin":
        claude = (
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        )
        trae = (
            home / "Library" / "Application Support" / "Trae" / "User" / "mcp.json"
        )
        windsurf = home / ".codeium" / "windsurf" / "mcp.json"
    else:
        claude = home / ".config" / "Claude" / "claude_desktop_config.json"
        trae = home / ".config" / "Trae" / "User" / "mcp.json"
        windsurf = home / ".codeium" / "windsurf" / "mcp.json"
    return {
        "claude": claude,
        "cursor": home / ".cursor" / "mcp.json",
        "trae": trae,
        "windsurf": windsurf,
    }


def resolve_command(use_absolute: bool = False) -> tuple[str, bool]:
    """决定 MCP 配置里写的 command。

    Returns:
        (command, 是否因为 PATH 里找不到而回退到绝对路径)
    """
    name = "pandaone-mcp"
    if not use_absolute and shutil.which(name):
        return name, False
    # PATH 里找不到 → 用绝对路径，否则 IDE 启动时根本找不到这个可执行文件
    candidate = Path(sys.executable).resolve().parent / (name + ".exe")
    if not candidate.is_file():
        candidate = Path(sys.executable).resolve().parent / name
    if candidate.is_file():
        return str(candidate), True
    return name, False


def _read_config(path: Path) -> dict:
    """读配置；文件不存在返回 {}；损坏抛 ValueError。"""
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"failed to read config: {e}")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"config is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("config root is not an object")
    return data


def _backup(path: Path) -> Path | None:
    """备份原配置。返回备份路径（无原文件时返回 None）。"""
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(path.name + f".bak.{stamp}")
    try:
        shutil.copy2(path, bak)
    except OSError:
        return None
    return bak


def install_into(
    path: Path,
    command: str,
    dry_run: bool = False,
    do_backup: bool = True,
) -> dict:
    """把 MCP 服务器写进一个配置文件。

    Returns:
        {"path", "created", "backup", "updated", "others", "error"}
    """
    result = {
        "path": str(path),
        "created": False,
        "backup": None,
        "updated": False,
        "others": 0,
        "error": None,
    }
    try:
        config = _read_config(path)
    except ValueError as e:
        result["error"] = str(e)
        return result

    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    result["others"] = len([k for k in servers if k != SERVER_KEY])
    existing = servers.get(SERVER_KEY)
    new_entry = {"command": command, "env": {}}
    if existing == new_entry:
        result["updated"] = False
        return result

    if dry_run:
        result["updated"] = True
        return result

    if do_backup:
        bak = _backup(path)
        if bak:
            result["backup"] = str(bak)

    servers[SERVER_KEY] = new_entry
    config["mcpServers"] = servers
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as e:
        result["error"] = str(e)
        return result
    result["created"] = True
    result["updated"] = True
    return result


def verify(path: Path, command: str) -> tuple[bool, str]:
    """装后自检：回读配置，确认 pandaone 条目在且 command 对。"""
    try:
        config = _read_config(path)
    except ValueError as e:
        return False, str(e)
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        return False, _t("mcp_verify_fail", path=str(path))
    entry = servers.get(SERVER_KEY)
    if not isinstance(entry, dict):
        return False, _t("mcp_verify_fail", path=str(path))
    if entry.get("command") != command:
        return False, _t("mcp_verify_cmd_mismatch", got=str(entry.get("command")))
    return True, _t("mcp_verify_ok", path=str(path))


def add_parser(sub) -> None:
    p = sub.add_parser(
        COMMAND_NAME,
        help="把 Pandaone MCP 服务器注册进 IDE 配置（Claude Desktop / Cursor / Trae / Windsurf）",
    )
    p.add_argument(
        "--client",
        default="auto",
        choices=["auto", "claude", "cursor", "trae", "windsurf", "all"],
        help="要写入哪个客户端的配置（auto = 只处理已存在的配置文件）",
    )
    p.add_argument("--dry-run", action="store_true", help="只演示不写盘")
    p.add_argument("--no-backup", action="store_true", help="不备份原配置")
    p.add_argument(
        "--absolute-command",
        action="store_true",
        help="写绝对路径而不是 pandaone-mcp（默认在 PATH 里找不到时才用绝对路径）",
    )


def handler(args) -> int:
    client = getattr(args, "client", "auto") or "auto"
    dry_run = bool(getattr(args, "dry_run", False))
    do_backup = not bool(getattr(args, "no_backup", False))

    command, fell_back = resolve_command(bool(getattr(args, "absolute_command", False)))

    print(_t("mcp_header", command=command))
    if fell_back:
        print(_t("mcp_command_fallback"))

    candidates = candidate_configs()
    if client == "auto":
        targets = {k: v for k, v in candidates.items() if v.is_file()}
        if not targets:
            print(_t("mcp_no_client_found"))
            for name, path in candidates.items():
                print(f"  {name}: {path}")
            return 0
    elif client == "all":
        targets = dict(candidates)
    else:
        targets = {client: candidates[client]}

    rc = 0
    for name, path in targets.items():
        print(_t("mcp_target", client=name, path=str(path)))
        result = install_into(path, command, dry_run=dry_run, do_backup=do_backup)
        if result["error"]:
            print(_t("mcp_write_fail", err=result["error"]))
            rc = 1
            continue
        if result["backup"]:
            print(_t("mcp_backup_ok", path=result["backup"]))
        if not result["updated"]:
            print(_t("mcp_already_ok", client=name))
            continue
        if dry_run:
            # dry-run 没有真的写盘，回读自检必然失败 —— 跳过
            continue
        ok, msg = verify(path, command)
        if not ok:
            print(_t("mcp_write_fail", err=msg))
            rc = 1
            continue
        print(_t("mcp_installed", client=name, path=str(path)))
        if result["others"]:
            print(_t("mcp_others_kept", n=result["others"]))

    if dry_run:
        print(_t("mcp_dry_run_done"))
        return rc
    print(_t("mcp_restart_hint"))
    return rc


if __name__ == "__main__":
    sys.exit(0)
