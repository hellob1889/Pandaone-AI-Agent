# -*- coding: utf-8 -*-
"""
path_conflicts.py — 找出 PATH 里的"影子 pandaone"
=====================================================

为什么需要这个模块（v0.7.28.0，真机实测得出）:
------------------------------------------------
Windows 的 PATH 拼接规则是 **机器级 PATH + 用户级 PATH，机器级在前**。
这带来一个反直觉的结论：

  即使把 exe 版目录 `%LOCALAPPDATA%\\Pandaone` **前置到用户级 PATH 的首位**，
  只要 pip 版 pandaone 装在 `Python\\Scripts\\` 且那个目录在**机器级** PATH 里，
  敲 `pandaone` 命中的仍然是旧 pip 版。

实测（本机）:
  机器级 PATH : ...\\Python\\Python311\\Scripts      <- pip 版 pandaone 0.7.21.3
  用户级 PATH : %LOCALAPPDATA%\\Pandaone              <- exe 版（已前置到用户级首位）
  where pandaone -> Python311\\Scripts\\pandaone.exe  <- 旧 pip 版胜出

也就是说 **"用户级 PATH 前置" 在机制上够不着机器级的同名命令**。
唯一能根治的办法是：让机器级那个不再是 `pandaone`。

设计取舍:
  - 本模块只做**只读**探测：绝不执行外部 exe，绝不改文件。
  - 真正的处置（改名 / 卸载）由调用方决定，避免"探测"带副作用。
  - `shadows()` 只返回**真的会抢占命令**的那些（排在 self 之前的 PATH 项），
    排在后面的只是"存在但不冲突"，单独列出来由调用方提示。
"""
from __future__ import annotations

import os as _os
import shutil as _shutil
import sys as _sys
from pathlib import Path as _Path

#: Windows 上可能充当 `pandaone` 命令的入口
CONSOLE_SCRIPT_NAMES = ("pandaone.exe", "pandaone.cmd", "pandaone.bat")

#: MCP server 的入口（名字不同，通常不冲突，但一起报出来更完整）
MCP_SCRIPT_NAMES = ("pandaone-mcp.exe", "pandaone-mcp.cmd", "pandaone-mcp.bat")


def _norm(path: str) -> str:
    """归一化路径用于比较（大小写不敏感 + 绝对路径）。"""
    try:
        return _os.path.normcase(_os.path.abspath(path))
    except Exception:
        return _os.path.normcase(path or "")


def _path_entries() -> list[str]:
    """按 PATH 顺序返回所有目录（跳过空项与引号包裹）。"""
    raw = _os.environ.get("PATH", "") or ""
    out: list[str] = []
    for d in raw.split(_os.pathsep):
        d = d.strip().strip('"')
        if d and d not in out:
            out.append(d)
    return out


def current_executable() -> str | None:
    """当前正在运行的 pandaone 路径。

    frozen (.exe) 下 `sys.executable` 就是 pandaone.exe 本身；
    源码形态下用 `shutil.which` 找 PATH 里的那个。
    """
    if getattr(_sys, "_MEIPASS", None):
        return _sys.executable
    return _shutil.which("pandaone")


def find_all(exclude: str | None = None) -> list[str]:
    """PATH 里所有 pandaone 入口（排除当前运行的那个）。"""
    self_key = _norm(exclude) if exclude else _norm(current_executable() or "")
    seen: set[str] = set()
    hits: list[str] = []
    for d in _path_entries():
        if not _os.path.isdir(d):
            continue
        for name in CONSOLE_SCRIPT_NAMES + MCP_SCRIPT_NAMES:
            p = _os.path.join(d, name)
            if not _os.path.isfile(p):
                continue
            k = _norm(p)
            if k in seen or (self_key and k == self_key):
                continue
            seen.add(k)
            hits.append(p)
    return hits


def shadows(exclude: str | None = None) -> list[str]:
    """**真的会抢占命令**的那些。

    判据：PATH 里排在 `exclude` **之前**的目录中的 pandaone 入口。
    排在后面的不会被命中（`where` 找不到就继续往后找），
    但仍可能干扰脚本里写死的绝对路径。

    `exclude` 的语义 = "当前正在运行的这个 pandaone 的可执行文件路径"：
      - frozen 形态：自动取 `sys.executable`（就是 pandaone.exe 本身）；
      - 源码形态：自动取 `shutil.which("pandaone")` —— 也就是"用户敲命令会命中谁"。
        此时排在它前面的没有了，所以源码形态**不会**误报 exe/pip 二义性。
      - 显式传入可覆盖推导（测试与特殊场景用）。
    """
    self_exe = exclude if exclude else current_executable()
    if not self_exe:
        return []
    self_dir = _norm(_os.path.dirname(_os.path.abspath(self_exe)))
    out: list[str] = []
    for d in _path_entries():
        d_norm = _norm(d)
        if d_norm == self_dir:
            # 走到自己所在目录就不再有"更靠前"的了
            break
        if not _os.path.isdir(d):
            continue
        # 注意：**MCP 入口也要查**。`pandaone-mcp` 与 pip 版同名，
        # 实测装完 exe 版后它仍被 Python\Scripts 里的旧版抢占。
        # （`pandaone-guard` 连字符 vs exe 版 `pandaone_guard` 下划线 —— 不同名，不冲突）
        for name in CONSOLE_SCRIPT_NAMES + MCP_SCRIPT_NAMES:
            p = _os.path.join(d, name)
            if _os.path.isfile(p):
                out.append(p)
    return out


def describe_conflicts(exclude: str | None = None) -> dict:
    """汇总成给 doctor / setup 用的结构。"""
    shadow = shadows(exclude)
    all_hits = find_all(exclude)
    others = [p for p in all_hits if p not in shadow]
    return {
        "ok": not shadow,
        "shadow": shadow,
        "others": others,
        "note": (
            "conflicting pandaone in PATH: " + "; ".join(shadow)
            if shadow
            else "no conflicting pandaone in PATH"
        ),
    }
