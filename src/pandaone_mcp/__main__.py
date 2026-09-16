#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pandaone_mcp.server
===================
MCP (Model Context Protocol) server — stdio JSON-RPC 2.0 transport。

第一性原理：
  - MCP 是让 AI Agent "发现工具 → 调用工具" 的标准化协议
  - JSON-RPC 2.0 over stdio（无网络暴露，最小攻击面）
  - 每个工具 = 一个 CLI 子命令的封装，复用现有 pandaone.py

设计：
  - 单进程：stdio 读写循环
  - 工具注册表：TOOLS dict 描述每个工具的 name / description / inputSchema
  - handler：调用 subprocess 执行 CLI，捕获输出返回

对抗式审查：
  - 攻击：恶意 stdin 注入
    缓解：JSON-RPC 严格校验，只接受 json.loads 成功的请求
  - 攻击：handler 阻塞
    缓解：subprocess.run 带 timeout，异常时返回 -32603
  - 攻击：进程作为攻击面
    缓解：stdio-only，不监听端口，进程由 IDE 管理生命周期
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# ============================================================
# 路径常量
# ============================================================
ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT.parent  # src/


# ============================================================
# 工具定义（MCP tools/list 返回的 schema）
# ============================================================
TOOLS = [
    {
        "name": "pandaone_init",
        "description": "在指定目录初始化 Pandaone AI Agent（创建 .pandaone/、config.json、pandaone.jsonl、可选 binary_snapshots.json）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "项目根目录路径", "default": "."},
                "ext": {"type": "array", "items": {"type": "string"},
                        "description": "自定义受保护扩展名（如 ['.py', '.md']）"},
                "no_binary": {"type": "boolean", "default": False,
                              "description": "禁用二进制 SHA256 快照保护"},
            },
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": False,         # creates .pandaone/ + config.json + jsonl
            "destructiveHint": False,      # doesn't destroy existing files
            "idempotentHint": False,       # each run mutates state (new jsonl entries)
            "openWorldHint": False,        # only touches its own .pandaone/ subdir
        },
    },
    {
        "name": "pandaone_lock",
        "description": "锁定所有受保护扩展名的文件（attrib +r / chmod -w）",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "default": "."}},
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": False,         # mutates file attrs (attrib +r / chmod -w)
            "destructiveHint": False,      # reversible via pandaone_unlock
            "idempotentHint": True,        # lock-twice = same state as lock-once
            "openWorldHint": False,        # only touches files under root
        },
    },
    {
        "name": "pandaone_unlock",
        "description": "解锁所有受保护扩展名的文件",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "default": "."}},
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": False,         # mutates file attrs (attrib -r / chmod +w)
            "destructiveHint": False,      # reverses pandaone_lock
            "idempotentHint": True,        # unlock-twice = same state as unlock-once
            "openWorldHint": False,        # only touches files under root
        },
    },
    {
        "name": "pandaone_write",
        "description": "审计写入（核心命令）：reason/problem/approach 必填；文本用 --old/--new 或 --content；二进制用 --from-file 或 --content-base64",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "."},
                "file": {"type": "string", "description": "目标文件路径（相对 root）"},
                "reason": {"type": "string", "minLength": 5,
                           "description": "改动原因（必填，至少 5 字符）"},
                "problem": {"type": "string", "minLength": 10,
                            "description": "解决的问题（必填，至少 10 字符）"},
                "approach": {"type": "string", "minLength": 10,
                             "description": "采用的方法（必填，至少 10 字符）"},
                "old": {"type": "string", "description": "原字符串（仅文本）"},
                "new": {"type": "string", "description": "新字符串（仅文本）"},
                "content": {"type": "string", "description": "整文件文本内容"},
                "content_base64": {"type": "string",
                                   "description": "整文件二进制内容（base64）"},
                "from_file": {"type": "string",
                              "description": "原文件路径（用于二进制）"},
            },
            "required": ["file", "reason", "problem", "approach"],
        },
        "annotations": {
            "readOnlyHint": False,         # overwrites target file content
            "destructiveHint": True,       # may overwrite untracked / pre-audit content
            "idempotentHint": False,       # each call appends an audit record (state changes)
            "openWorldHint": False,        # only touches files under root
        },
    },
    {
        "name": "pandaone_log",
        "description": "查看审计日志（按文件/recent/格式过滤）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "."},
                "recent": {"type": "integer", "description": "最近 N 条"},
                "file": {"type": "string", "description": "按文件路径过滤"},
                "format": {"type": "string", "enum": ["text", "json", "csv", "tsv", "yaml", "md", "html", "xlsx", "docx", "pdf"]},
                "output": {"type": "string", "description": "导出文件路径"},
                "rejected": {"type": "boolean", "default": False, "description": "只看被拒绝的变更"},
                "unauthorized": {"type": "boolean", "default": False, "description": "只看未授权的变更"},
            },
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": True,          # read-only (only writes optional export file)
            "destructiveHint": False,      # never destructive
            "idempotentHint": True,        # log query is pure function of .pandaone/pandaone.jsonl
            "openWorldHint": False,        # only reads .pandaone/ under root
        },
    },
    {
        "name": "pandaone_status",
        "description": "查看 Pandaone 状态（保护文件 / 审计次数 / 锁定状态等）",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "default": "."}},
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": True,          # pure read
            "destructiveHint": False,
            "idempotentHint": True,        # pure read
            "openWorldHint": False,        # only reads .pandaone/ under root
        },
    },
    {
        "name": "pandaone_install_hook",
        "description": "安装/卸载 pre-commit hook",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "."},
                "uninstall": {"type": "boolean", "default": False,
                              "description": "True 则卸载"},
            },
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": False,         # writes .git/hooks/pre-commit
            "destructiveHint": False,      # writes a new file; uninstall removes it
            "idempotentHint": True,        # install-hook twice = same as once
            "openWorldHint": False,        # only touches .git/ under root
        },
    },
    {
        "name": "pandaone_watch",
        "description": "启动 watchdog 守护进程（监控文件改动）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "."},
                "daemon": {"type": "boolean", "default": False, "description": "后台守护模式"},
            },
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": False,         # starts a long-running daemon process
            "destructiveHint": False,      # watchdog only observes + prompts, doesn't mutate
            "idempotentHint": False,       # starts a NEW process each call (may need dedup)
            "openWorldHint": False,        # observes filesystem under root only
        },
    },
    {
        "name": "pandaone_install_git",
        "description": "安装便携版 git（用于项目内 git hook，无需全局 git）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_only": {"type": "boolean", "default": True, "description": "只探测，不下载"},
                "auto_download": {"type": "boolean", "default": False, "description": "自动下载缺失的 git"},
            },
        },
        "annotations": {
            "readOnlyHint": False,         # writes bundled git to a known cache dir
            "destructiveHint": False,      # downloads to its own cache; doesn't touch user files
            "idempotentHint": True,        # probe is pure; download dedupes by sha256
            "openWorldHint": True,         # downloads portable git from GitHub releases
        },
    },
    {
        "name": "pandaone_fingerprint_update",
        "description": "更新密码指纹（用于 watch 守护进程鉴权）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "password": {"type": "string", "description": "新密码"},
            },
            "required": ["password"],
        },
        "annotations": {
            "readOnlyHint": False,         # writes password hash to .pandaone/
            "destructiveHint": False,      # overwrites previous hash but reversible
            "idempotentHint": True,        # same password → same hash → same state
            "openWorldHint": False,        # only touches .pandaone/ under root
        },
    },
    {
        "name": "pandaone_ci",
        "description": "CI 审计验证：对比 base..head 的所有改动，确认每条变更都通过 pandaone write 审计",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "."},
                "base": {"type": "string", "description": "基线分支", "default": "origin/main"},
                "head": {"type": "string", "description": "对比分支", "default": "HEAD"},
            },
            "required": ["root"],
        },
        "annotations": {
            "readOnlyHint": True,          # pure verification — never mutates repo
            "destructiveHint": False,
            "idempotentHint": True,        # same base/head → same report
            "openWorldHint": False,        # only reads git refs + .pandaone/ under root
        },
    },
]


def _args_from(params, mapping):
    """从 JSON-RPC 参数 dict 提取 --key value 对。mapping: list of (param_key, --flag)"""
    out = []
    for k, flag in mapping:
        v = params.get(k)
        if v is None:
            continue
        if isinstance(v, bool):
            if v:
                out.append(flag)
        elif isinstance(v, list):
            for item in v:
                out.extend([flag, str(item)])
        else:
            out.extend([flag, str(v)])
    return out


def _run_cli(args, timeout=10):
    """调用 pandaone CLI，捕获 stdout/stderr/returncode"""
    try:
        r = subprocess.run(
            ["pandaone"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


HANDLERS = {
    "pandaone_init": lambda p: _run_cli(["init", *_args_from(p, [
        ("root", "--root"), ("ext", "--ext"), ("no_binary", "--no-binary")])], timeout=60),
    "pandaone_lock": lambda p: _run_cli(["lock", *_args_from(p, [("root", "--root")])]),
    "pandaone_unlock": lambda p: _run_cli(["unlock", *_args_from(p, [("root", "--root")])]),
    "pandaone_write": lambda p: _run_cli(["write", *_args_from(p, [
        ("root", "--root"), ("file", "--file"),
        ("reason", "--reason"), ("problem", "--problem"), ("approach", "--approach"),
        ("old", "--old"), ("new", "--new"),
        ("content", "--content"), ("content_base64", "--content-base64"),
        ("from_file", "--from-file")])], timeout=30),
    "pandaone_log": lambda p: _run_cli(["log", *_args_from(p, [
        ("root", "--root"), ("recent", "--recent"),
        ("file", "--file"), ("format", "--format"), ("output", "--output"),
    ])] + (["--rejected"] if p.get("rejected") else []) +
       (["--unauthorized"] if p.get("unauthorized") else []), timeout=30),
    "pandaone_status": lambda p: _run_cli(["status", *_args_from(p, [("root", "--root")])]),
    "pandaone_install_hook": lambda p: _run_cli(
        ["install-hook", *_args_from(p, [("root", "--root"), ("uninstall", "--uninstall")])]),
    "pandaone_watch": lambda p: _run_cli(
        ["watch", *_args_from(p, [("root", "--root"), ("daemon", "--daemon")])],
        timeout=5),
    "pandaone_install_git": lambda p: _run_cli(
        ["install-git",
         *(["--probe-only"] if not p.get("auto_download") else []),
         *(["--auto-download"] if p.get("auto_download") else [])]),
    "pandaone_fingerprint_update": lambda p: _run_cli(
        ["--update-fingerprint", p.get("password", "0000")]),
    "pandaone_ci": lambda p: _run_cli(["ci", *_args_from(p, [
        ("root", "--root"), ("base", "--base"), ("head", "--head")])], timeout=30),
}


# ============================================================
# JSON-RPC 2.0 dispatcher
# ============================================================
def _make_response(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _make_error(id_, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def _handle_request(req: dict) -> dict | None:
    """处理一条 JSON-RPC 请求，返回响应 dict（或 None 表示通知）"""
    if not isinstance(req, dict):
        return _make_error(None, -32600, "Invalid Request")
    method = req.get("method")
    params = req.get("params", {}) or {}
    id_ = req.get("id")
    is_notification = id_ is None

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pandaone", "version": "0.7.7"},  # v0.7.7: 同步 pandaone-guard 版本
        }
        return _make_response(id_, result) if not is_notification else None

    elif method == "notifications/initialized":
        return None

    elif method == "tools/list":
        result = {"tools": TOOLS}
        return _make_response(id_, result) if not is_notification else None

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        if tool_name not in HANDLERS:
            return _make_error(id_, -32602, f"Unknown tool: {tool_name}")

        try:
            handler_result = HANDLERS[tool_name](arguments)
            rc = handler_result.get("returncode", 0)
            stdout = handler_result.get("stdout", "")
            stderr = handler_result.get("stderr", "")

            content = []
            if stdout:
                content.append({"type": "text", "text": stdout})
            if stderr:
                content.append({"type": "text", "text": f"[stderr] {stderr}"})

            result = {
                "content": content,
                "isError": rc != 0,
            }
            return _make_response(id_, result) if not is_notification else None
        except Exception as e:
            return _make_error(id_, -32603, f"Internal error: {e}")

    elif method == "ping":
        return _make_response(id_, {}) if not is_notification else None

    else:
        return _make_error(id_, -32601, f"Method not found: {method}")


# ============================================================
# stdio 主循环
# ============================================================
def serve_stdio():
    """stdio JSON-RPC 2.0 服务器主循环"""
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            err_resp = _make_error(None, -32700, "Parse error", str(e))
            sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    serve_stdio()


if __name__ == "__main__":
    main()