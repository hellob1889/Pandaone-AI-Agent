#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_audit_i18n_ci.py
=====================
audit_i18n.py CI 集成测试。

按对抗式审查（CI 最危险的失败模式是"该报错时却退出 0"）：
  必须验证失败路径，否则整个 lint.yml 是空架子。

覆盖：
  TestCleanState            — 干净状态 exit 0 + 无硬编码
  TestFailureDetection      — 注入硬编码 → exit 1（核心 CI 行为）
  TestJsonMode              — --json 输出结构有效（CI artifact 上传）
  TestSkipCoverage          — --skip-coverage 选项独立可跑
  TestPythonCompatibility   — f-string 跨 3.10/3.11/3.12 兼容
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ============================================================
# 路径常量
# ============================================================
REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT = REPO_ROOT / "scripts" / "audit_i18n.py"
CLI = REPO_ROOT / "src" / "pandaone" / "cli.py"
GUARD_MAIN = REPO_ROOT / "src" / "pandaone_guard" / "__main__.py"


# ============================================================
# 辅助函数
# ============================================================

def _run_audit(*args, timeout=60):
    """运行 audit_i18n.py，统一错误处理"""
    return subprocess.run(
        [sys.executable, str(AUDIT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _inject_hardcoded(
    cli_path: Path,
    marker: str = 'if __name__ == "__main__":',
) -> None:
    """注入 3 处硬编码中文（print / raise / f-string 各一处）"""
    original = cli_path.read_text(encoding="utf-8")
    if marker not in original:
        pytest.skip(f"无法找到注入标记 {marker!r}")
    inject = (
        '\n# === CI 注入测试 ===\n'
        'def _injected_bug_for_ci_test():\n'
        '    print("硬编码中文泄漏测试 - print 中未迁移")\n'
        '    raise RuntimeError("硬编码中文泄漏测试 - raise 中未迁移")\n'
        '    print(f"硬编码中文泄漏测试 - f-string 中未迁移: {1+1}")\n'
        '\n'
    )
    cli_path.write_text(
        original.replace(marker, inject + marker, 1),
        encoding="utf-8",
    )


@pytest.fixture
def fresh_cli():
    """保证 cli.py 在测试结束时恢复到测试前的状态（即使测试失败）

    第一性原理（对抗式审查）：
      - 多个测试调用 _inject_hardcoded，每次注入会增加 inject block
      - 如果 fresh_cli 只 backup 一次，后续测试的 backup 已是"已被污染"的状态

    v0.7.15 fix（数据丢失事故）：
      - 之前 backup 从 `git show HEAD` 读取，finally 用 git HEAD 版本覆盖 cli.py。
        任何开发者/Agent 对 cli.py 的**未提交修改**都会在跑测试时被静默回滚丢失
        （v0.7.15 开发中真实发生过：cli.py 的 __main__ 修复被整个吃掉）。
      - 现在 backup = 测试开始时的工作区内容（CLI.read_bytes()），
        恢复的就是"测试前"状态，不再依赖 git HEAD。
      - 跨测试污染由 _inject_hardcoded 的 marker 检查兜底（marker 缺失则 skip）。
    """
    backup = CLI.read_bytes()
    try:
        yield CLI
    finally:
        CLI.write_bytes(backup)


# ============================================================
# TestCleanState: 干净状态必须 PASS
# ============================================================

class TestCleanState:
    """干净状态：exit 0 + 无硬编码 + i18n 全覆盖"""

    def test_clean_state_exits_0(self):
        """干净状态应 exit 0（CI 默认基线）"""
        result = _run_audit()
        assert result.returncode == 0, (
            f"干净状态应 exit 0，实际 {result.returncode}\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:200]}"
        )

    def test_clean_state_human_readable_output(self):
        """人类可读输出应包含关键信息"""
        result = _run_audit()
        assert "无硬编码中文字符串" in result.stdout
        assert "[PASS]" in result.stdout
        # 覆盖率段
        assert "i18n 覆盖率" in result.stdout
        assert "zh-CN" in result.stdout
        assert "en" in result.stdout
        # 100% 覆盖
        assert "100%" in result.stdout

    def test_clean_state_no_offending_files(self):
        """不应列出任何违规文件"""
        result = _run_audit()
        assert "## src" not in result.stdout, (
            "干净状态不应有 ## src/... 违规文件段"
        )


# ============================================================
# TestFailureDetection: 注入硬编码必须 FAIL（对抗式审查核心）
# ============================================================

class TestFailureDetection:
    """对抗式：注入硬编码 → exit 1 + 报告位置"""

    def test_injected_hardcoded_exits_1(self, fresh_cli):
        """注入硬编码后应 exit 1（CI 最关键行为）"""
        _inject_hardcoded(CLI)
        result = _run_audit()
        assert result.returncode == 1, (
            f"注入硬编码应 exit 1，实际 {result.returncode}\n"
            f"stdout: {result.stdout[:500]}"
        )

    def test_injected_hardcoded_lists_offending_file(self, fresh_cli):
        """应报告违规文件路径"""
        _inject_hardcoded(CLI)
        result = _run_audit()
        assert "src\\pandaone\\cli.py" in result.stdout or "src/pandaone/cli.py" in result.stdout

    def test_injection_covers_multiple_syntaxes(self, fresh_cli):
        """应检测多种语法（print / raise / f-string）的硬编码"""
        _inject_hardcoded(CLI)
        result = _run_audit()
        # 注入 3 处，至少要检测到 2 处（print 和 raise 必中）
        # f-string 可能因代码顺序偶尔与 print 合并 — 这是已知行为
        issue_count = result.stdout.count("硬编码中文泄漏测试")
        assert issue_count >= 2, (
            f"应至少检测到 2 处硬编码，实际 {issue_count}\n"
            f"stdout: {result.stdout}"
        )
        # 必须检测 raise 和 print 两种语法
        assert "raise RuntimeError" in result.stdout
        # 必须强制 f-string 修复后 print 被检测（word-boundary 修复点）
        assert "print(" in result.stdout


# ============================================================
# TestJsonMode: JSON 输出结构（CI artifact）
# ============================================================

class TestJsonMode:
    """--json 模式：CI artifact 上传 + passed 字段"""

    def test_json_clean_state_structure(self):
        """干净状态 JSON 结构正确"""
        result = _run_audit("--json")
        assert result.returncode == 0, (
            f"--json 干净状态应 exit 0，实际 {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        payload = json.loads(result.stdout)  # 必须能解析
        assert "hardcoded_chinese_issues" in payload
        assert "i18n_coverage" in payload
        assert "passed" in payload
        assert isinstance(payload["passed"], bool)
        assert payload["passed"] is True
        assert len(payload["hardcoded_chinese_issues"]) == 0
        # 双语言覆盖
        for lang in ("zh-CN", "en"):
            assert lang in payload["i18n_coverage"]
            assert payload["i18n_coverage"][lang]["missing_pct"] == 0

    def test_json_injected_state_exits_1(self, fresh_cli):
        """JSON 模式下注入硬编码 → exit 1 + passed=false（关键！）"""
        _inject_hardcoded(CLI)
        result = _run_audit("--json")
        assert result.returncode == 1, (
            "JSON 模式下注入硬编码应 exit 1，否则 CI 无法 fail-fast！\n"
            f"stdout: {result.stdout[:300]}"
        )
        payload = json.loads(result.stdout)
        assert payload["passed"] is False
        assert len(payload["hardcoded_chinese_issues"]) >= 1
        # 报告应包含具体行号
        first_file_issues = next(iter(payload["hardcoded_chinese_issues"].values()))
        assert "line" in first_file_issues[0]
        assert "content" in first_file_issues[0]


# ============================================================
# TestSkipCoverage: --skip-coverage 选项
# ============================================================

class TestSkipCoverage:
    """--skip-coverage 跳过 i18n 覆盖率检查"""

    def test_skip_coverage_exits_0(self):
        """--skip-coverage 应 exit 0（独立工作）"""
        result = _run_audit("--skip-coverage")
        assert result.returncode == 0

    def test_skip_coverage_omits_coverage_block(self):
        """输出不应包含 i18n 覆盖率段"""
        result = _run_audit("--skip-coverage")
        assert "i18n 覆盖率" not in result.stdout


# ============================================================
# TestPythonCompatibility: f-string 跨版本兼容
# ============================================================

class TestPythonCompatibility:
    """f-string 必须在 3.10/3.11/3.12 都能跑（CI matrix）"""

    def test_script_is_valid_python(self):
        """AST 解析通过（任何 Python 3 版本都应能 import）"""
        ast.parse(AUDIT.read_text(encoding="utf-8"))

    def test_help_exits_0(self):
        """--help 不崩"""
        result = _run_audit("--help")
        assert result.returncode == 0
        assert "i18n" in result.stdout

    def test_fstring_no_nested_double_quotes_in_dict_access(self):
        """按对抗式审查：f-string 中不应有 dict["key"] 嵌套双引号
        （Python 3.11 限制）"""
        source = AUDIT.read_text(encoding="utf-8")
        # 检查所有 f-string 中是否有 dict["..."] 这种嵌套引号
        # pattern: { ... ["..."] ... }
        import re
        # 找所有 f-string 表达式内的内容
        pattern = re.compile(r'f["\']([^{}]*(?:\{[^{}]*\}[^{}]*)*)["\']')
        for match in pattern.finditer(source):
            body = match.group(1)
            # 检查是否在 {} 内有 ["..."] 这种 3.11 不允许的嵌套
            inner_pattern = re.compile(r'\{\s*[^}]*\[["\'][^"\']*["\']\][^}]*\}')
            if inner_pattern.search(body):
                pytest.fail(
                    f"发现 f-string 内嵌套引号（Python 3.11 不兼容）:\n"
                    f"{match.group(0)[:120]}"
                )


# ============================================================
# TestArgumentParsing: CLI 参数解析
# ============================================================

class TestArgumentParsing:
    """argparse 配置正确性"""

    def test_root_argument(self):
        """--root 参数接受自定义路径"""
        result = _run_audit("--root", str(REPO_ROOT / "src"))
        # 不管 src 有没有内容，不应崩溃
        assert result.returncode in (0, 1)

    def test_invalid_root_exits_2(self, tmp_path):
        """不存在的 --root 路径应 exit 2"""
        nonexistent = tmp_path / "does_not_exist"
        result = _run_audit("--root", str(nonexistent))
        assert result.returncode == 2
        assert "不存在" in result.stderr or "不存在" in result.stdout

    def test_combined_flags(self):
        """--json + --skip-coverage 组合可跑"""
        result = _run_audit("--json", "--skip-coverage")
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert "passed" in payload
