#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pandaone.py - 主 CLI

v0.7.7 修复:之前 MCP 推送截断了 cmd_ci/main 部分,导致 pip install 语法错误,Smoke Tests 失败。
v0.7.9 修复 (PR #36):
  - fix v1: 把 __file__ 设到每个 chunk 自己的路径, 否则 part_001.py 里
    `ROOT = Path(__file__).parent.parent` 解析到 cli.py 自己路径
    (因为 _exec_ns["__file__"] 被钉死在 cli.py 绝对路径),导致 ROOT 指错 (site-packages/)
  - fix v2: 循环后恢复 cli.__file__ = cli.py 自己的路径
    否则循环结束后 _exec_ns["__file__"] = 最后一个 chunk (part_006.py), 导致所有
    用 __file__ 算 SHA256 的代码 (compute_fingerprint 等) 算的是 part_006.py 指纹
    跟 docstring "pandaone.py 自身 SHA256" 不符, 也跟 v0.7.8 行为不兼容。
本文件通过 cli_chunks 模块组装,见 cli_chunks/part_*.py。
"""
import sys
from pathlib import Path

_CHUNKS_DIR = Path(__file__).resolve().parent / "cli_chunks"
_chunks = sorted(_CHUNKS_DIR.glob("part_*.py"))
if not _chunks:
    print("ERR: no cli_chunks/part_*.py found", file=sys.stderr)
    sys.exit(1)

# PR #32 fix (cli loader): 用模块 globals() 作为 exec namespace
# v0.7.15 fix: 先保存 "是否作为主程序运行" 标记。
#   之前 _exec_ns["__name__"] = "pandaone.cli" 直接覆写 globals()["__name__"],
#   导致文件末尾 `if __name__ == "__main__"` 永远为 False,
#   `python cli.py` 直接运行时静默 no-op (rc=0 无任何输出),测试与右键菜单全部失效。
_is_main = __name__ == "__main__"
_exec_ns = globals()
_exec_ns["__name__"] = "pandaone.cli"
# v0.7.9 fix v1+v2 (PR #36)
_orig_file = _exec_ns["__file__"]
for chunk in _chunks:
    _exec_ns["__file__"] = str(chunk.resolve())
    code = chunk.read_text(encoding="utf-8")
    exec(compile(code, str(chunk), "exec"), _exec_ns)
_exec_ns["__file__"] = _orig_file  # 恢复, 保持 compute_fingerprint() 等行为正确

if _is_main:
    sys.exit(main())
