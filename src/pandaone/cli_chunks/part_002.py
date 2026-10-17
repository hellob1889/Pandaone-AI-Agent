# cli.py chunk 2/6: lines 325-728
# 子命令处理（逐步实现）
# PR #36 (v0.7.9): cli.py loader 现在 _exec_ns = globals() 直接共享,
# 之前 _exec_ns 复制 cli globals (包括所有 stdlib import).
# 现在 exec 时只能用 chunk 自己的 imports, 不能依赖 cli globals 已有 imports.
import sys
import os
import json
import hashlib
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone
# ============================================================
# ============================================================
# 自指纹保护（L5 防御）
# ============================================================
# 默认密码(本地使用)。生产/CI 可通过环境变量 PANDAX_FP_PASSWORD 覆盖
# ——源码不再含权威明文。
_DEFAULT_FP_PASSWORD = 0000


def get_fingerprint_password() -> str:
    "读取