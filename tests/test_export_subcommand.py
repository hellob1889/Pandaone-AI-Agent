"""
test_export_subcommand.py
==========================
Bug #25 RED 测试：pandaone export 应该是独立子命令，不再借用 log。

第一性原理：
  之前用户只能 `pandaone log --format html --output report.html` 导出，
  但 "log" 语义是"查看历史"，借用来做"导出"语义混乱。
  修复：新增独立子命令 `pandaone export --format <fmt> --output <path>`。
  旧 log --format/--output 仍可用但打印 deprecation warning。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"


def _run(args, cwd, env_extra=None, lang="zh-CN"):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PANDAX_LANG"] = lang
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pandaone", *args],
        cwd=cwd, capture_output=True, text=True, env=env, timeout=15,
    )


def _setup_with_audit(tmp_path):
    """初始化项目 + 注入 1 条 audit 记录"""
    r = _run(["init", "--root", str(tmp_path), "--force"], tmp_path)
    assert r.returncode == 0, f"init failed: {r.stderr}"
    audit_path = tmp_path / ".pandaone" / "pandaone.jsonl"
    rec = {
        "id": "audit_001",
        "timestamp": "2026-01-01 12:00:00",
        "status": "APPROVED",
        "file": "main.py",
        "reason": "test reason",
        "problem": "test problem",
        "approach": "test approach",
        "commit_hash": "abc12345",
    }
    audit_path.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    return tmp_path


# ============================================================
# Bug #25: export 独立子命令
# ============================================================

class TestExportSubcommand:
    """Bug #25 — `pandaone export` 应作为独立子命令存在"""

    @staticmethod
    def _cli_source() -> str:
        """v0.7.15 fix: cli.py 是 chunk loader，实际代码在 cli_chunks/part_*.py"""
        chunks = sorted((SRC_DIR / "pandaone" / "cli_chunks").glob("part_*.py"))
        return "\n".join(p.read_text(encoding="utf-8") for p in chunks)

    def test_export_subcommand_exists_in_argparse(self):
        """静态验证：argparse 中有 export_p = sub.add_parser('export', ...)"""
        cli_src = self._cli_source()
        assert re.search(
            r'sub\.add_parser\(\s*"export"', cli_src,
        ), "Bug #25 回归：argparse 中没有 export 子命令"

    def test_export_registered_in_commands_dict(self):
        """静态验证：COMMANDS 字典中 export 映射到 cmd_export"""
        cli_src = self._cli_source()
        # COMMANDS = { ... "export": cmd_export ... }
        m = re.search(r'COMMANDS\s*=\s*\{[^}]*"export"\s*:\s*(\w+)', cli_src, re.DOTALL)
        assert m, "Bug #25 回归：COMMANDS 中找不到 'export' 键"
        # 该函数应实际存在
        assert f"def {m.group(1)}(" in cli_src, f"导出函数 {m.group(1)} 未定义"

    def test_pandaone_help_lists_export(self, tmp_path):
        """E2E：pandaone --help 输出应包含 export"""
        r = _run(["--help"], tmp_path)
        assert r.returncode == 0
        assert "export" in r.stdout.lower(), (
            f"Bug #25 回归：--help 输出没有 export 子命令: {r.stdout[:500]}"
        )

    def test_export_help_includes_format_output_args(self, tmp_path):
        """E2E：pandaone export --help 应列出 --format 和 --output"""
        r = _run(["export", "--help"], tmp_path)
        assert r.returncode == 0
        assert "--format" in r.stdout or "-f" in r.stdout
        assert "--output" in r.stdout or "-o" in r.stdout

    # ----- 实际功能 -----

    def test_export_html_en(self, tmp_path):
        """pandaone export --format html --output FILE --lang en 应生成英文 HTML"""
        project = _setup_with_audit(tmp_path)
        out = project / "report.html"
        r = _run(
            ["export", "--format", "html", "--output", str(out), "--lang", "en"],
            project,
        )
        assert r.returncode == 0, f"export failed: {r.stderr}"
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Pandaone AI Agent Audit Report" in content
        # Bug #26 同时验证（i18n 已修复）
        assert "审计报告" not in content

    def test_export_json(self, tmp_path):
        """pandaone export --format json --output FILE 应生成 JSON 结构"""
        project = _setup_with_audit(tmp_path)
        out = project / "data.json"
        r = _run(["export", "--format", "json", "--output", str(out)], project)
        assert r.returncode == 0, f"export failed: {r.stderr}"
        data = json.loads(out.read_text(encoding="utf-8"))
        # 实际格式: {"metadata": {...}, "records": [...]}（exporters.py 现有格式）
        assert "records" in data
        assert isinstance(data["records"], list)
        assert data["records"][0]["id"] == "audit_001"

    def test_export_csv_filter_by_file(self, tmp_path):
        """pandaone export --format csv --file main.py 应只导出 main.py 记录"""
        project = _setup_with_audit(tmp_path)
        # 再添加一条其他文件的记录
        audit_path = project / ".pandaone" / "pandaone.jsonl"
        rec2 = {
            "id": "audit_002",
            "timestamp": "2026-01-02 12:00:00",
            "status": "APPROVED",
            "file": "other.py",
            "reason": "r", "problem": "p", "approach": "a", "commit_hash": "x",
        }
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec2, ensure_ascii=False) + "\n")

        out = project / "main_only.csv"
        r = _run(
            ["export", "--format", "csv", "--output", str(out), "--file", "main.py"],
            project,
        )
        assert r.returncode == 0
        lines = out.read_text(encoding="utf-8").splitlines()
        # 第一行是表头，第二行是 main.py 记录
        assert len(lines) >= 2
        assert "main.py" in lines[1]
        assert "other.py" not in out.read_text(encoding="utf-8")

    def test_export_missing_format_returns_error(self, tmp_path):
        """不传 --format 应报错（required=True）"""
        project = _setup_with_audit(tmp_path)
        r = _run(["export", "--output", str(project / "x.txt")], project)
        # argparse 会以 exit 2 退出 + stderr
        assert r.returncode != 0
        assert "format" in (r.stderr + r.stdout).lower()

    def test_export_missing_output_returns_error(self, tmp_path):
        """不传 --output 应报错"""
        project = _setup_with_audit(tmp_path)
        r = _run(["export", "--format", "html"], project)
        assert r.returncode != 0
        assert "output" in (r.stderr + r.stdout).lower()


# ============================================================
# 旧 log --format/--output 兼容性 + 弃用警告
# ============================================================

class TestLegacyLogExportDeprecation:
    """旧 log --format/--output 仍可用，但应打印 WARN 推荐新子命令"""

    def test_log_format_output_still_works_with_warning(self, tmp_path):
        """pandaone log --format html --output FILE 应仍能导出 + 打印 deprecation"""
        project = _setup_with_audit(tmp_path)
        out = project / "legacy.html"
        r = _run(["log", "--format", "html", "--output", str(out)], project, lang="en")
        assert r.returncode == 0, f"legacy path failed: {r.stderr}"
        assert out.exists()
        # deprecation warning 应输出
        combined = r.stdout + r.stderr
        assert "deprecated" in combined.lower() or "WARN" in combined, (
            f"Bug #25 回归：旧 log --format/--output 未打印 deprecation 警告: {combined}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
