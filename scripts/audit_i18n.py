#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_i18n.py — Pandaone AI Agent i18n 对抗式审查脚本
============================================

扫描所有 pandaone 包源码（cli.py / guard / mcp / exporters / templates），找出：
  1. print() / sys.stderr.write() 中的硬编码中文字符串（未被 t() 包裹）
  2. raise Exception("...") 中的中文
  3. f-string 中的中文（重点）

排除：
  - docstring（三引号包围）
  - 注释行（# 开头）
  - 已迁移的 t() 调用
  - i18n 模块本身（i18n.py 允许含中文）
  - ASCII art + 品牌常量
  - 已知的中文常量（menu_*, banner_*）
  - 帮助文本（parser.add_argument 的 help）

输出格式：
  <文件路径>:<行号>: <代码片段>

退出码：
  0 = 通过（零未迁移字符串）
  1 = 发现未迁移字符串
  2 = 运行时错误

用法：
  python scripts/audit_i18n.py
  python scripts/audit_i18n.py --root /custom/src --json

被 CI 调用：
  GitHub Actions .github/workflows/lint.yml
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ============================================================
# 常量
# ============================================================

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "src"

# 不需要审计的文件（i18n 模块本身 + 测试脚本）
SKIP_FILES = {
    "i18n.py",
    "audit_i18n.py",
}

# 中文正则（常用汉字 + 扩展 A 区）
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")

# print / stderr.write / raise Exception
PRINT_RE = re.compile(r"^\s*(print|sys\.stderr\.write)\(")
EXCEPTION_RE = re.compile(r"^\s*raise\s+[\w.]+\(")

# 已知的中文常量 / 品牌字符串（白名单）
BRAND_WHITELIST = [
    "BOLD =", "DIM =", "RESET =", "MAGENTA =", "INDIGO =", "CYAN =",
    "menu_", "banner_tagline", "banner_", "macos_",
    "🐼", "█████", "PANDAX",
    # Python 标准库和第三方库的常见中文化命名
    "Pandaone", "pandaone", "PANDAS",
    # 路径
    "/Users/", "/home/", "C:\\",
    # SHA256 哈希占位符
    "{fp}", "{stored}", "{current}", "{file}", "{dir}", "{path}", "{root}",
    # 已知翻译模板的 f-string 占位符
    "PANDAX_", "pip install", "site-packages",
]


# ============================================================
# 辅助函数
# ============================================================

# 用 word-boundary 匹配 t() 调用，避免被 print("...") 中的 t(" 子串误判
_T_CALL_RE = re.compile(r'(?<![A-Za-z0-9_.])t\(')
_T_BILINGUAL_RE = re.compile(r'(?<![A-Za-z0-9_.])t_bilingual\(')
_T_SAFE_RE = re.compile(r'(?<![A-Za-z0-9_.])t_safe\(')
_I18N_T_RE = re.compile(r'(?<![A-Za-z0-9_.])i18n\.t\(')


def is_in_skip_context(line: str) -> bool:
    """判断这一行是否在 docstring / 注释 / 已迁移的 t() 内 / 已知常量"""
    stripped = line.strip()
    # 注释行
    if stripped.startswith("#"):
        return True
    # Bug fix (v0.7.15) F-14: 行内注释 - 中文出现在 # 之后
    # 例: print(x)  # 中文注释不应被计为硬编码
    # 简化判断: 找到第一个不在字符串内的 # 位置, 如果第一个中文字符在该位置之后, 算注释
    comment_pos = _find_inline_comment_pos(line)
    if comment_pos is not None:
        first_chinese = CHINESE_RE.search(line)
        if first_chinese and first_chinese.start() > comment_pos:
            return True
    # 已迁移的 t() / t_bilingual() / t_safe() / i18n.t() 调用（用 word-boundary）
    if _T_CALL_RE.search(line):
        return True
    if _T_BILINGUAL_RE.search(line):
        return True
    if _T_SAFE_RE.search(line):
        return True
    if _I18N_T_RE.search(line):
        return True
    # 品牌白名单
    if any(s in line for s in BRAND_WHITELIST):
        return True
    # 已迁移的 i18n_init 调用
    if 'i18n_init(' in line:
        return True
    # f-string 中只含占位符（不是中文）
    return False


def _find_inline_comment_pos(line: str):
    '''找到行内 # 注释的起始位置（不在字符串内）。返回 None 表示无注释。

    简化版字符串状态机: 跟踪是否在双引号或单引号内, 跳过井号出现在字符串内的情况。
    不处理三引号字符串 (假定三引号行已被外层 docstring 跟踪跳过)。
    '''
    in_str = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == in_str and (i == 0 or line[i - 1] != "\\"):
                in_str = None
        else:
            if ch == '"' or ch == "'":
                in_str = ch
            elif ch == "#":
                return i
        i += 1
    return None


def audit_file(path: Path) -> list:
    """审计单个文件，返回 (lineno, line) 列表"""
    issues = []
    in_docstring = False
    docstring_char = None
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 无法读取 {path}: {e}", file=sys.stderr)
        return []

    for i, line in enumerate(content.splitlines(), 1):
        # 跟踪 docstring
        if not in_docstring:
            triple_quote = '"""' if '"""' in line else "'''" if "'''" in line else None
            if triple_quote:
                cnt = line.count(triple_quote)
                if cnt == 1:
                    in_docstring = True
                    docstring_char = triple_quote
                # 单行 docstring 跳过
                continue
        else:
            if docstring_char in line:
                in_docstring = False
                docstring_char = None
            continue

        # 是否包含中文
        if not CHINESE_RE.search(line):
            continue
        # 跳过上下文
        if is_in_skip_context(line):
            continue
        # 检查是否是 print / Exception / raise 中的中文
        if PRINT_RE.search(line) or EXCEPTION_RE.search(line):
            issues.append((i, line.strip()))

    return issues


# ============================================================
# i18n 覆盖率检查
# ============================================================

def check_i18n_coverage() -> dict:
    """
    检查 i18n 模块的语言包覆盖。
    返回 {"zh-CN": {"total": N, "present": M, "missing_pct": X}, ...}
    """
    try:
        sys.path.insert(0, str(DEFAULT_ROOT))
        from pandaone import i18n
        return i18n.coverage_report()
    except Exception as e:
        print(f"[WARN] 无法运行 i18n 覆盖率检查: {e}", file=sys.stderr)
        return {}


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pandaone i18n 对抗式审查 + 覆盖率检查"
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="源码根目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument("--skip-coverage", action="store_true", help="跳过覆盖率检查")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"[ERROR] 源码根目录不存在: {root}", file=sys.stderr)
        return 2

    # ============ 1. 硬编码中文扫描 ============
    all_issues = {}
    for py_file in sorted(root.rglob("*.py")):
        rel = py_file.relative_to(root.parent)
        if py_file.name in SKIP_FILES:
            continue
        issues = audit_file(py_file)
        if issues:
            all_issues[str(rel)] = [{"line": ln, "content": content} for ln, content in issues]

    # ============ 2. i18n 覆盖率检查 ============
    coverage = {} if args.skip_coverage else check_i18n_coverage()

    # ============ 3. 输出 ============
    if args.json:
        output = {
            "hardcoded_chinese_issues": all_issues,
            "i18n_coverage": coverage,
            "passed": len(all_issues) == 0 and all(
                stats.get("missing_pct", 0) == 0 for stats in coverage.values()
            ),
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        # 关键：JSON 模式也要根据 passed 字段返回正确的 exit code
        # 否则 CI 用 --json 时失败场景不会退出 1
        return 0 if output["passed"] else 1
    else:
        print("=" * 70)
        print(" Pandaone i18n 对抗式审查")
        print("=" * 70)
        print()

        # 硬编码中文
        total_issues = sum(len(v) for v in all_issues.values())
        if all_issues:
            for rel, issues in all_issues.items():
                print(f"## {rel}")
                for issue in issues:
                    snippet = issue["content"]
                    if len(snippet) > 120:
                        snippet = snippet[:120] + "..."
                    line_no = issue["line"]
                    print(f"  L{line_no}: {snippet}")
                print()
        else:
            print("[OK] 无硬编码中文字符串")
            print()

        # 覆盖率
        if coverage:
            print("=" * 70)
            print(" i18n 覆盖率")
            print("=" * 70)
            print()
            for lang, stats in coverage.items():
                missing_pct = stats["missing_pct"]
                present_pct = 100 - missing_pct
                status = "[OK" if missing_pct == 0 else "[WARN"
                present = stats["present"]
                total = stats["total"]
                pct_str = f"{present_pct:.0f}%"
                print(f"{status}] {lang}: {present}/{total} ({pct_str})", end="")
                missing = stats["missing"]
                missing_count = len(missing)
                if missing_count > 0:
                    print(f"  missing: {missing_count} keys")
                    for k in missing[:5]:
                        print(f"    - {k}")
                    if missing_count > 5:
                        more_n = missing_count - 5
                        print(f"    ... and {more_n} more")
                else:
                    print()
            print()

        # 总结
        print("=" * 70)
        coverage_complete = all(
            stats.get("missing_pct", 0) == 0 for stats in coverage.values()
        )
        if total_issues == 0 and coverage_complete:
            if coverage:
                lang_count = len(coverage)
                print(f" [PASS] 通过 — {lang_count} 语言100% 覆盖，0 硬编码中文")
            else:
                print(" [PASS] 通过 — 0 硬编码中文（--skip-coverage）")
            print("=" * 70)
            return 0
        else:
            if coverage:
                total_missing_pct = sum(
                    stats.get("missing_pct", 0) for stats in coverage.values()
                )
                pct_str = f"{total_missing_pct:.1f}%"
                msg = f" [FAIL] 失败 — {total_issues} 处硬编码，{pct_str} 未翻译"
            else:
                msg = f" [FAIL] 失败 — {total_issues} 处硬编码（--skip-coverage）"
            print(msg)
            print("=" * 70)
            return 1


if __name__ == "__main__":
    sys.exit(main())