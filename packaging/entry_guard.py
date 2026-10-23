#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller entry — pandaone_guard.exe（看门狗 / 文件监听守护进程）

对应 pyproject 的 ``pandaone-guard = "pandaone_guard:main"``。
"""
import sys

from pandaone_guard import main

if __name__ == "__main__":
    sys.exit(main())
