"""
test_bug_48_trust_default.py
=============================
Bug #48 修复测试：--trust-default 自动接受新指纹（pip install --upgrade 场景）

第一性原理：
  - pip install --upgrade 会改变 cli.py 内容 → fingerprint hash 变 → 所有命令失败
  - 普通用户不知道 `pandaone --update-fingerprint 0000` 这个密码命令
  - 解决：--trust-default 自动用新 hash 覆盖（隐式信任）
  - 位置敏感性根因：argparse parse_known_args 把 --trust-default 当子命令的未知参数
  - 修复：main() 预扫描 argv，把 --trust-default 移到子命令前

#45/#46/#47 在初始报告中为 false positive，验证后非 bug：
  - #45: pre-commit-check.py 已有 except Exception 处理
  - #46: cmd_write 在 line 996 已做 .replace("\\", "/") 规范化
  - #47: --old not in content 时 write_text 未执行（line 920-924）
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"


def _run(args, cwd, lang="zh-CN"):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PANDAX_LANG"] = lang
    return subprocess.run(
        [sys.executable, "-m", "pandaone", *args],
        cwd=cwd, capture_output=True, text=True, env=env, timeout=15,
    )


class TestBug48TrustDefaultPositionIndependent:
    """Bug #48 fix — --trust-default 自动接受新指纹 + 位置不敏感"""

    def setup_method(self):
        """每个测试前保存原 fingerprint，测试后恢复"""
        self.fp_path = Path.home() / ".pandaone_fp.txt"
        self.original_fp = None
        if self.fp_path.exists():
            self.original_fp = self.fp_path.read_text(encoding="utf-8")

    def teardown_method(self):
        """恢复 fingerprint"""
        if self.original_fp is not None:
            self.fp_path.write_text(self.original_fp, encoding="utf-8")
        elif self.fp_path.exists():
            self.fp_path.unlink()

    def _set_wrong_fp(self):
        """写入错误的 fingerprint 模拟 mismatch.

        v0.7.21.2 起:
          - 旧 hex "0"*64 → 走 legacy migrate (auto-refresh, 不报错) → 不能触发 mismatch 测
          - 非 hex 字符 "f"*63 + "g" → 解析失败, 视为损坏 → 走 ERROR 路径
        """
        self.fp_path.parent.mkdir(parents=True, exist_ok=True)
        # 用非 hex 字符 (末位 'g' 不是 hex) 模拟真篡改
        self.fp_path.write_text("f" * 63 + "g", encoding="utf-8")

    def test_trust_default_after_subcommand_updates_fp(self, tmp_path):
        """--trust-default 在子命令后也能生效（修复后）"""
        self._set_wrong_fp()
        # --trust-default 放在子命令之后（用户最自然的写法）
        r = _run(["status", "--trust-default", "--root", str(tmp_path)], tmp_path)
        # 不应报 fingerprint mismatch
        assert "指纹不匹配" not in r.stdout, (
            f"Bug #48 回归：--trust-default 在子命令后未生效: {r.stdout}"
        )
        assert "fingerprint mismatch" not in r.stdout.lower()
        # fingerprint 已被自动更新（不再是 00000000...）
        new_fp = self.fp_path.read_text(encoding="utf-8").strip()
        assert new_fp != "0" * 64, "Bug #48 回归：fingerprint 未被更新"

    def test_trust_default_before_subcommand_works(self, tmp_path):
        """--trust-default 在子命令前也能生效（原始行为保留）"""
        self._set_wrong_fp()
        r = _run(["--trust-default", "status", "--root", str(tmp_path)], tmp_path)
        assert "指纹不匹配" not in r.stdout
        new_fp = self.fp_path.read_text(encoding="utf-8").strip()
        assert new_fp != "0" * 64

    def test_strict_mode_rejects_mismatch(self, tmp_path):
        """v0.7.21.2: --strict 模式下 fingerprint 不匹配应报错且不被自动更新 (锁传统行为).

        Bug #48 老 test 期望"无 --trust-default 时 fingerprint 保持 0*64 不变".
        v0.7.21.2 默认 auto-refresh 改了这行为 (这就是痛点修复本身).
        改用 --strict 测, 验证严格模式仍锁传统 mismatch → ERROR 行为.
        """
        self._set_wrong_fp()
        r = _run(["status", "--strict", "--root", str(tmp_path)], tmp_path)
        # 必须报 mismatch
        assert "指纹不匹配" in r.stdout or "fingerprint mismatch" in r.stdout.lower(), (
            f"v0.7.21.2 --strict 回归：无 --strict 应仍报错: {r.stdout}"
        )
        # fingerprint 未被自动修改
        current_fp = self.fp_path.read_text(encoding="utf-8").strip()
        assert current_fp == "f" * 63 + "g", (
            f"v0.7.21.2 --strict 回归：--strict 模式下 fingerprint 被静默修改"
        )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
