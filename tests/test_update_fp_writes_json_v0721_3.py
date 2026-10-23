"""Refactored v0.7.21.3 test — subprocess 模式触发真 cli loader, 不依赖 module-level shared globals.

CI portability fix (v0.7.21.3 hotfix hotfix):
  - 老 commit #6 用 Windows-absolute 路径 (C:\\...\\python.exe, D:\\绿联云办公\\...)
    在 Linux CI runner 上 FileNotFoundError. 改 portable:
    (a) subprocess 用 sys.executable (CI runner 自己 Python interpreter).
    (b) 静态 source check 用 __file__ 相对路径 (tests/test_foo.py -> ../../src/pandaone/cli_chunks/part_006.py),
        不依赖 absolute Windows path.
  - Path.home() 重定向 USERPROFILE/HOME/HOMEDRIVE/HOMEPATH 兼容 Windows + Linux.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# v0.7.21.3 hotfix hotfix: portable subprocess Python interpreter
# (老 commit 用 C:\\...\\Python311\\python.exe 死路径, CI Linux runner 跑失败).
PYTHON = sys.executable
# v0.7.21.3 hotfix hotfix: portable source path
# tests/test_*.py 在 repo root 下 tests/, 目标 src/pandaone/cli_chunks/part_006.py 上推两级.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PART_006 = _REPO_ROOT / "src" / "pandaone" / "cli_chunks" / "part_006.py"


def test_v0721_3_update_fingerprint_writes_json_format(tmp_path):
    """v0.7.21.3: `pandaone --update-fingerprint 0000` 后 FP_PATH 是合法 json {version, hash, stored_at}."""
    fp_path = tmp_path / ".pandaone_fp.txt"
    env = os.environ.copy()
    # Path.home() 重定向到 tmp_path:
    # - Windows: USERPROFILE 优先, fallback HOMEDRIVE+HOMEPATH
    # - Linux/macOS: HOME
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = ""

    r = subprocess.run(
        [PYTHON, "-m", "pandaone", "--update-fingerprint", "0000"],
        cwd=str(tmp_path), capture_output=True, text=True, env=env, timeout=15,
    )
    assert r.returncode == 0, f"pandaone --update-fingerprint failed: rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    assert fp_path.exists(), f"FP_PATH {fp_path} not created. stdout: {r.stdout}\nstderr: {r.stderr}"

    raw = fp_path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        pytest.fail(f"v0.7.21.3 修真未生效: FP_PATH 不是合法 json: {raw!r}\n{e}\nstdout: {r.stdout}")
    assert "version" in data, f"missing 'version' in {list(data.keys())}"
    assert "hash" in data, f"missing 'hash' in {list(data.keys())}"
    assert "stored_at" in data, f"missing 'stored_at' in {list(data.keys())}"
    # v0.7.22: version 必须是**当前运行的这份代码**的版本。
    #   源码树模式 = 源码 pyproject.toml 的版本（v0.7.22 起源码树优先），
    #   已安装模式 = 包元数据的版本。
    #   真正的不变式是 "FP_PATH 里的 version == 运行中的版本"，
    #   而不是 "== 已安装版本" —— 后者在开发模式下本来就是错的：
    #   源码已经改成 0.7.22.0 但装的还是 0.7.21.3 时，两者本就不该相等。
    from pandaone import __version__ as running_version
    assert data["version"] == running_version, (
        f"FP_PATH version {data['version']} != running version {running_version}"
    )
    # hash 应是 64 字符 hex
    assert len(data["hash"]) == 64 and all(c in "0123456789abcdef" for c in data["hash"]), (
        f"hash 不是 64 字符 hex: {data['hash']}"
    )
    # stored_at ISO 8601 UTC
    assert data["stored_at"].endswith("Z"), f"stored_at 应以 Z 结尾: {data['stored_at']}"


def test_v0721_3_trust_default_writes_json_format(tmp_path):
    """v0.7.21.3: --trust-default 触发后 FP_PATH 是合法 json (自动 update-fp 路径)."""
    fp_path = tmp_path / ".pandaone_fp.txt"
    env = os.environ.copy()
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = ""
    env["PANDAX_FP_PASSWORD"] = "0000"

    # 预置裸 hex FP_PATH (模拟 v0.7.21.2 旧装机 user FP_PATH, 应触发 auto-refresh)
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    fp_path.write_text("0" * 64, encoding="utf-8")

    # 跑 status (会触发 fingerprint check), 验证 trust_default 路径自动写 json
    r = subprocess.run(
        [PYTHON, "-m", "pandaone", "status", "--trust-default"],
        cwd=str(tmp_path), capture_output=True, text=True, env=env, timeout=15,
    )
    # trust_default 应该 EXIT 0 (auto-refresh 救回); 可能触发 warning 信息
    assert r.returncode in (0, 1), (
        f"pandaone status --trust-default failed: rc={r.returncode}\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )

    assert fp_path.exists(), "FP_PATH 应存在"
    raw = fp_path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"v0.7.21.3 (trust_default 路径) 修真未生效: FP_PATH 不是合法 json: {raw!r}\n"
            f"stderr: {r.stderr}"
        )
    assert "version" in data
    assert "hash" in data
    assert "stored_at" in data


def test_v0721_3_no_bare_hex_in_part_006():
    """v0.7.21.3: part_006.py 源码不应再出现 `write_text(new_fp` 裸 hex 写入."""
    assert _PART_006.exists(), (
        f"v0.7.21.3 hotfix: _PART_006 not found at {_PART_006}. "
        f"__file__={__file__}, _REPO_ROOT={_REPO_ROOT}"
    )
    text = _PART_006.read_text(encoding="utf-8")
    # v0.7.21.3 fix: 应改 _save_fp 走 json 格式, 不应再 raw write_text(new_fp
    assert "write_text(new_fp" not in text, (
        "v0.7.21.3: part_006.py 含 'write_text(new_fp' 残留 — "
        "应改 _save_fp(_get_pandaone_version(), new_fp) 走 json 格式"
    )
