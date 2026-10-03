"""
pandaone_mcp
=============
Phase 6: Model Context Protocol (MCP) server for Pandaone AI Agent.

让 AI Agent 通过标准化协议直接调用 pandaone CLI 的所有功能。

入口:
  - python -m pandaone_mcp
  - pandaone-mcp (通过 console_scripts 入口调用 main)
"""
__version__ = None  # v0.7.15: 动态解析,见下方 _resolve_version(),不再硬编码字面量


def _resolve_version() -> str:
    """版本单一事实源: 优先复用 pandaone 包版本 (来自 pyproject.toml)。"""
    try:
        from pandaone import __version__ as v
        return v
    except Exception:
        try:
            from importlib.metadata import version as _v
            return _v("pandaone-guard")
        except Exception:
            return "0.0.0"


__version__ = _resolve_version()

# v0.7.7 修复（BUG-01）：console_scripts 入口 `pandaone_mcp:main` 要求 `main`
# 必须从 package 的 `__init__.py` 顶层可导入。`main`/`serve_stdio`/`_handle_request`
# 实现在 `__main__.py` 里，必须显式 re-export，否则入口启动时会抛
# `ImportError: cannot import name 'main' from 'pandaone_mcp'`
# （参考 pandaone_guard/__init__.py 的同模式实现）
from .__main__ import main, serve_stdio, _handle_request, TOOLS, HANDLERS

__all__ = ["main", "serve_stdio", "_handle_request", "TOOLS", "HANDLERS", "__version__"]