#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller entry — pandaone.exe

为什么不直接拿 ``src/pandaone/__main__.py`` 当 entry：
PyInstaller 会把 entry 当成 ``__main__`` 模块执行，于是
``pandaone/__main__.py`` 同时以 ``__main__`` 和 ``pandaone.__main__``
两个身份被加载一遍 → ``_ensure_doctor_registered()`` 的 monkey-patch
跑两次、``cli.build_parser`` 被二次包装。

这里用一层薄壳，只 import 一次 ``pandaone.__main__``，行为与
``python -m pandaone`` / ``pandaone`` 命令完全一致。
"""
import sys

from pandaone.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
