"""
test_protected_extensions.py
============================
Phase 4.6 — 验证 Pandaone AI Agent 保护范围扩展到所有文本文件类型。

第一性原理：
  - 审计系统的"保护范围"必须能覆盖所有可执行/可误导的文件
  - 只保护 .py 等于让 agent 从其他格式侧门绕过

对抗式审查：
  - 攻击：agent 改 .md/.json/.yml 误导未来开发者
  - 缓解：扩展 protected_extensions 默认列表
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

# root 用户不受文件权限位限制（444 文件依然可写），无法模拟 PermissionError。
# 这是环境限制而非产品缺陷，L1 锁对普通用户依然有效。
_ROOT_SKIP = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root 用户不受权限位限制，无法验证 OS 级文件锁",
)


def _run_cli(*args, cwd=None, env_extra=None):
    """运行 pandaone CLI，返回 (rc, stdout, stderr)"""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", "pandaone", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or ROOT_DIR, env=env)
    return r.returncode, r.stdout, r.stderr


# ============================================================
# Step 27: RED 测试
# ============================================================

class TestInitDefaultExtensions:
    """init 默认应包含常见文本格式（不只是 .py）"""

    def test_init_default_includes_md(self, tmp_path):
        """init 默认应保护 .md"""
        rc, out, err = _run_cli("init", "--root", str(tmp_path))
        assert rc == 0, f"init 失败: {err}"
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert ".md" in config["protected_extensions"], f"应包含 .md，实际: {config['protected_extensions']}"

    def test_init_default_includes_json(self, tmp_path):
        """init 默认应保护 .json"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert ".json" in config["protected_extensions"]

    def test_init_default_includes_yaml(self, tmp_path):
        """init 默认应保护 .yaml/.yml"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert ".yaml" in config["protected_extensions"]
        assert ".yml" in config["protected_extensions"]

    def test_init_default_includes_html_css_js(self, tmp_path):
        """init 默认应保护前端文件"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        for ext in [".html", ".css", ".js"]:
            assert ext in config["protected_extensions"], f"应包含 {ext}"

    def test_init_default_includes_shell_scripts(self, tmp_path):
        """init 默认应保护 .sh/.bat/.ps1（可执行脚本）"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        for ext in [".sh", ".bat", ".ps1"]:
            assert ext in config["protected_extensions"], f"应包含 {ext}"

    def test_init_default_still_includes_py(self, tmp_path):
        """init 默认仍应包含 .py（向后兼容）"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert ".py" in config["protected_extensions"]

    def test_init_default_excludes_binary(self, tmp_path):
        """init 默认不应包含纯二进制格式（.png/.exe/.zip）"""
        _run_cli("init", "--root", str(tmp_path))
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        for ext in [".png", ".jpg", ".exe", ".zip"]:
            assert ext not in config["protected_extensions"], f"不应包含 {ext}"


class TestInitCustomExtensions:
    """init 支持 --ext 自定义扩展名"""

    def test_init_accepts_custom_ext(self, tmp_path):
        """init --ext .foo 应只保护 .foo"""
        rc, out, err = _run_cli("init", "--root", str(tmp_path), "--ext", ".foo", ".bar")
        assert rc == 0, f"init --ext 失败: {err}"
        config = json.loads((tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert ".foo" in config["protected_extensions"]
        assert ".bar" in config["protected_extensions"]


class TestLockMultipleExtensions:
    """lock 应覆盖所有 protected_extensions（不只看 .py）"""

    @_ROOT_SKIP
    def test_lock_locks_md_files(self, tmp_path):
        """lock 后 .md 文件应不可写"""
        import os
        _run_cli("init", "--root", str(tmp_path))
        md_file = tmp_path / "README.md"
        md_file.write_text("# Test", encoding="utf-8")

        rc, out, err = _run_cli("lock", "--root", str(tmp_path))
        assert rc == 0, f"lock 失败: {err}"

        # 尝试写应失败（Windows PermissionError / Unix EACCES）
        with pytest.raises((PermissionError, OSError)):
            md_file.write_text("hijack", encoding="utf-8")
        # 恢复权限以便清理
        os.chmod(md_file, 0o666)

    @_ROOT_SKIP
    def test_lock_locks_json_files(self, tmp_path):
        """lock 后 .json 文件应不可写"""
        import os
        _run_cli("init", "--root", str(tmp_path))
        json_file = tmp_path / "config.json"
        json_file.write_text("{}", encoding="utf-8")

        _run_cli("lock", "--root", str(tmp_path))

        with pytest.raises((PermissionError, OSError)):
            json_file.write_text("{}", encoding="utf-8")
        os.chmod(json_file, 0o666)

    @_ROOT_SKIP
    def test_lock_locks_yml_files(self, tmp_path):
        """lock 后 .yml 文件应不可写"""
        import os
        _run_cli("init", "--root", str(tmp_path))
        yml_file = tmp_path / "config.yml"
        yml_file.write_text("a: 1", encoding="utf-8")

        _run_cli("lock", "--root", str(tmp_path))

        with pytest.raises((PermissionError, OSError)):
            yml_file.write_text("a: 2", encoding="utf-8")
        os.chmod(yml_file, 0o666)

    def test_lock_does_not_lock_png(self, tmp_path):
        """lock 不应锁 .png（二进制不在 protected_extensions）"""
        png_path = tmp_path / "image.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        _run_cli("init", "--root", str(tmp_path))
        _run_cli("lock", "--root", str(tmp_path))

        # .png 应仍可写
        png_path.write_bytes(b"new content")
        assert png_path.read_bytes() == b"new content"

    def test_lock_count_includes_all_extensions(self, tmp_path, capsys):
        """lock 输出数量应包含所有受保护扩展"""
        # 准备混合文件
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        (tmp_path / "b.md").write_text("", encoding="utf-8")
        (tmp_path / "c.json").write_text("", encoding="utf-8")
        (tmp_path / "d.yml").write_text("", encoding="utf-8")
        (tmp_path / "e.png").write_bytes(b"")

        _run_cli("init", "--root", str(tmp_path))
        rc, out, err = _run_cli("lock", "--root", str(tmp_path))

        # 应锁 4 个 (.py/.md/.json/.yml)，不包括 .png
        assert "[OK] 锁定 4 个" in out, f"应锁 4 个，实际输出: {out}"


class TestUnlockMultipleExtensions:
    """unlock 应覆盖所有 protected_extensions"""

    def test_unlock_restores_write_to_md(self, tmp_path):
        """lock → unlock 后 .md 应可写"""
        _run_cli("init", "--root", str(tmp_path))
        md_file = tmp_path / "test.md"
        md_file.write_text("original", encoding="utf-8")

        _run_cli("lock", "--root", str(tmp_path))
        rc, out, err = _run_cli("unlock", "--root", str(tmp_path))
        assert rc == 0

        # 现在可写
        md_file.write_text("new", encoding="utf-8")
        assert md_file.read_text(encoding="utf-8") == "new"


class TestWriteMultipleExtensions:
    """write 应支持所有 protected_extensions（不只看 .py）"""

    def test_write_supports_md(self, tmp_path):
        """write 应能写入 .md 文件"""
        (tmp_path / "doc.md").write_text("old content", encoding="utf-8")

        rc, out, err = _run_cli("init", "--root", str(tmp_path))
        assert rc == 0

        rc, out, err = _run_cli(
            "write", "--root", str(tmp_path),
            "--file", "doc.md",
            "--reason", "更新项目文档内容",
            "--problem", "原文档描述有误需要修正",
            "--approach", "修改为正确描述并补充示例",
            "--old", "old content",
            "--new", "new content",
        )
        assert rc == 0, f"write md 失败: {err}\nstdout: {out}"
        assert "APPROVED" in out or "[OK]" in out

    def test_write_rejects_png(self, tmp_path):
        """write 应拒绝 .png（不在 protected_extensions）"""
        (tmp_path / "logo.png").write_bytes(b"old")

        _run_cli("init", "--root", str(tmp_path))

        rc, out, err = _run_cli(
            "write", "--root", str(tmp_path),
            "--file", "logo.png",
            "--reason", "更新图标",
            "--problem", "图标过时",
            "--approach", "替换为新图标",
            "--content", "new binary data",
        )
        # 应被拒绝
        assert rc != 0, f"应拒绝 .png，但 rc={rc}"
        assert "REJECTED" in out or "只允许修改" in out


class TestCustomExtOverDefault:
    """--ext 应覆盖默认（不留旧默认）"""

    @_ROOT_SKIP
    def test_custom_ext_drops_default_py(self, tmp_path):
        """指定 --ext .foo 后，.py 不应再受保护"""
        (tmp_path / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "data.foo").write_text("", encoding="utf-8")

        _run_cli("init", "--root", str(tmp_path), "--ext", ".foo")
        rc, out, err = _run_cli("lock", "--root", str(tmp_path))
        assert rc == 0

        # main.py 不应被锁（不在 .foo 列表中）
        import os
        try:
            (tmp_path / "main.py").write_text("hijack", encoding="utf-8")
            py_writable = True
        except (PermissionError, OSError):
            py_writable = False
        if py_writable is False:
            os.chmod(tmp_path / "main.py", 0o666)
        assert py_writable is True, ".py 不应被 --ext .foo 锁住"

        # data.foo 应被锁
        with pytest.raises((PermissionError, OSError)):
            (tmp_path / "data.foo").write_text("hijack", encoding="utf-8")
        os.chmod(tmp_path / "data.foo", 0o666)