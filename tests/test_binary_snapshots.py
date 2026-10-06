"""
test_binary_snapshots.py
========================
Phase 5 — 二进制文件 SHA256 快照机制。

第一性原理：
  文本文件可用 --old/--new 做语义化审计；二进制必须用整文件替换 + 完整性校验。
  所以二进制走"快照模式"（SHA256 字典），文本走"语法模式"（protected_extensions）。

对抗式审查：
  - 攻击：agent 直接覆盖 .png/.exe 篡改资源/二进制
    缓解：snapshot 记录 SHA256，watchdog 检测变化即告警
  - 攻击：snapshot 文件本身被篡改
    缓解：snapshot 在 .pandaone/，被外层审计体系保护
"""
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"


def _run_cli(*args, cwd=None, env_extra=None):
    """运行 pandaone CLI"""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", "pandaone", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or ROOT_DIR, env=env)
    return r.returncode, r.stdout, r.stderr


def _git(*args, cwd, env_extra=None):
    """运行 git 命令"""
    import os
    import shutil
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    git_exe = shutil.which("git")
    if not git_exe:
        pytest.skip("git not found")  # v0.7.15: 移除作者机器路径硬编码，直接跳过
    r = subprocess.run([git_exe, *args], cwd=cwd, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ============================================================
# Step 33: RED 测试
# ============================================================

class TestInitBinarySnapshots:
    """init 应为二进制文件创建 SHA256 快照"""

    def test_init_creates_binary_snapshots_file(self, tmp_path):
        """init 在有二进制文件的目录应创建 .pandaone/binary_snapshots.json"""
        # 准备二进制文件
        (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4\nFAKE")

        rc, out, err = _run_cli("init", "--root", str(tmp_path))
        assert rc == 0, f"init 失败: {err}"

        snap_path = tmp_path / ".pandaone" / "binary_snapshots.json"
        assert snap_path.exists(), "应创建 binary_snapshots.json"

    def test_init_snapshot_records_correct_sha256(self, tmp_path):
        """snapshot 应是每个文件的真实 SHA256"""
        png_data = b"\x89PNG\r\n\x1a\nORIGINAL_PNG"
        pdf_data = b"%PDF-1.4\nORIGINAL_PDF"
        (tmp_path / "logo.png").write_bytes(png_data)
        (tmp_path / "report.pdf").write_bytes(pdf_data)

        _run_cli("init", "--root", str(tmp_path))

        snap = json.loads((tmp_path / ".pandaone" / "binary_snapshots.json").read_text(encoding="utf-8"))
        assert snap["logo.png"] == _sha256(png_data)
        assert snap["report.pdf"] == _sha256(pdf_data)

    def test_init_default_includes_binary_extensions(self, tmp_path):
        """config 应默认包含二进制扩展名列表"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert "binary_protected_extensions" in config
        exts = config["binary_protected_extensions"]
        # 应包含常见格式
        for ext in [".png", ".pdf", ".exe", ".zip"]:
            assert ext in exts, f"默认二进制保护应包含 {ext}"

    def test_init_with_disable_binary_flag(self, tmp_path):
        """init --no-binary 应跳过 snapshot 创建"""
        (tmp_path / "logo.png").write_bytes(b"\x89PNG")

        _run_cli("init", "--root", str(tmp_path), "--no-binary")

        snap_path = tmp_path / ".pandaone" / "binary_snapshots.json"
        assert not snap_path.exists(), "--no-binary 时不应创建 snapshot"

        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert config["binary_protected_extensions"] == []


class TestWriteBinaryFile:
    """write 应支持二进制文件（用 --from-file 或 --content-base64）"""

    def test_write_binary_with_from_file(self, tmp_path):
        """write --from-file 应能替换二进制文件"""
        # 准备：init + git + lock + 初始文件
        original_data = b"\x89PNG\r\n\x1a\nORIGINAL"
        (tmp_path / "logo.png").write_bytes(original_data)
        _run_cli("init", "--root", str(tmp_path))
        _git("init", cwd=tmp_path)
        _git("config", "user.email", "t@t", cwd=tmp_path)
        _git("config", "user.name", "t", cwd=tmp_path)
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-m", "init", cwd=tmp_path)
        _run_cli("lock", "--root", str(tmp_path))

        # 准备新文件
        new_file = tmp_path / "new_logo.png"
        new_data = b"\x89PNG\r\n\x1a\nNEW_VERSION"
        new_file.write_bytes(new_data)

        # 用 --from-file 写入
        rc, out, err = _run_cli(
            "write", "--root", str(tmp_path),
            "--file", "logo.png",
            "--reason", "更新 logo 为新设计",
            "--problem", "原 logo 已过时",
            "--approach", "替换为新版 logo",
            "--from-file", str(new_file),
        )
        assert rc == 0, f"write binary 失败: rc={rc}, err={err}, out={out[-500:]}"

        # 文件应被替换
        assert (tmp_path / "logo.png").read_bytes() == new_data

        # snapshot 应更新为新 SHA256
        snap = json.loads((tmp_path / ".pandaone" / "binary_snapshots.json").read_text(encoding="utf-8"))
        assert snap["logo.png"] == _sha256(new_data)

    def test_write_binary_with_content_base64(self, tmp_path):
        """write --content-base64 应能内联二进制内容"""
        original_data = b"\x89PNG\r\n\x1a\nORIG"
        (tmp_path / "logo.png").write_bytes(original_data)
        _run_cli("init", "--root", str(tmp_path))
        _git("init", cwd=tmp_path)
        _git("config", "user.email", "t@t", cwd=tmp_path)
        _git("config", "user.name", "t", cwd=tmp_path)
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-m", "init", cwd=tmp_path)

        new_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nNEW_INLINE").decode()
        rc, out, err = _run_cli(
            "write", "--root", str(tmp_path),
            "--file", "logo.png",
            "--reason", "更新 logo 图标",
            "--problem", "原 logo 图标已过时需要替换",
            "--approach", "用 base64 内联替换为新版本 logo",
            "--content-base64", new_b64,
        )
        assert rc == 0, f"write base64 失败: {err}"
        assert (tmp_path / "logo.png").read_bytes() == b"\x89PNG\r\n\x1a\nNEW_INLINE"

    def test_write_binary_rejects_old_new(self, tmp_path):
        """二进制文件 write 时不应接受 --old/--new（语义化替换对二进制无意义）"""
        (tmp_path / "logo.png").write_bytes(b"\x89PNG")
        _run_cli("init", "--root", str(tmp_path))
        _git("init", cwd=tmp_path)
        _git("config", "user.email", "t@t", cwd=tmp_path)
        _git("config", "user.name", "t", cwd=tmp_path)
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-m", "init", cwd=tmp_path)

        rc, out, err = _run_cli(
            "write", "--root", str(tmp_path),
            "--file", "logo.png",
            "--reason", "尝试用 old/new 改二进制",
            "--problem", "不应该被允许",
            "--approach", "应拒绝",
            "--old", "abc", "--new", "def",
        )
        assert rc != 0, "二进制 write 不应接受 --old/--new"
        assert "REJECTED" in out or "二进制" in out


class TestWatchdogBinary:
    """watchdog 应通过 SHA256 对比检测未授权二进制修改"""

    def test_watchdog_detects_binary_modification_without_token(self, tmp_path):
        """修改二进制文件但无令牌时，watchdog 应记录 UNAUTHORIZED"""
        # 准备：init + git + lock
        png_data = b"\x89PNG\r\n\x1a\nORIGINAL"
        (tmp_path / "logo.png").write_bytes(png_data)
        _run_cli("init", "--root", str(tmp_path))
        _git("init", cwd=tmp_path)
        _git("config", "user.email", "t@t", cwd=tmp_path)
        _git("config", "user.name", "t", cwd=tmp_path)
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-m", "init", cwd=tmp_path)
        _run_cli("lock", "--root", str(tmp_path))

        # 模拟攻击（无令牌修改）
        import os
        import stat
        png_path = tmp_path / "logo.png"
        png_path.chmod(png_path.stat().st_mode | stat.S_IWUSR)
        png_path.write_bytes(b"\x89PNG\r\n\x1a\nHIJACKED")

        # 直接实例化 handler 触发 on_modified
        sys.path.insert(0, str(ROOT_DIR))
        from pandaone_guard import PandaXHandler
        handler = PandaXHandler(tmp_path)

        class FakeEvent:
            def __init__(self, p):
                self.src_path = p
                self.dest_path = p
                self.is_directory = False
        handler.on_modified(FakeEvent(str(png_path)))

        # 应有 UNAUTHORIZED 记录
        audit_path = tmp_path / ".pandaone" / "pandaone.jsonl"
        records = [
            json.loads(line) for line in
            audit_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        unauthorized = [r for r in records if r["status"] == "UNAUTHORIZED"]
        assert len(unauthorized) >= 1, "应有 UNAUTHORIZED 记录"
        assert "logo.png" in unauthorized[-1]["file"]
        assert "binary" in unauthorized[-1].get("detection", "").lower() or "snapshot" in unauthorized[-1].get("detection", "").lower()


class TestStatusBinary:
    """status 应显示二进制快照信息"""

    def test_status_shows_binary_snapshot_count(self, tmp_path):
        """status 应报告 binary_snapshots.json 中的文件数"""
        (tmp_path / "a.png").write_bytes(b"a")
        (tmp_path / "b.pdf").write_bytes(b"b")
        (tmp_path / "c.png").write_bytes(b"c")
        _run_cli("init", "--root", str(tmp_path))

        rc, out, err = _run_cli("status", "--root", str(tmp_path))
        # status 输出应包含 binary 数量信息
        assert "binary" in out.lower() or "snapshot" in out.lower(), f"status 应包含 binary 信息: {out}"