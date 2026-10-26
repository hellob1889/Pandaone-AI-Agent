#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller entry — pandaone-mcp.exe（MCP stdio server）

对应 pyproject 的 ``pandaone-mcp = "pandaone_mcp:main"``。
``pandaone install-mcp`` 往 IDE 配置里写的就是这个可执行。
"""
import sys

from pandaone_mcp import main

if __name__ == "__main__":
    sys.exit(main())
