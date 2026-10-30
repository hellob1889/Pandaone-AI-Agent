# cli.py chunk 1/6: lines 1-324
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pandaone.py
============
Pandaone AI Agent — AI Agent 代码审计门禁系统（CLI 主程序）

设计核心：
  - 每次启动必读 README.md 并显示当前阶段 / 已完成步骤
  - 文件锁（attrib +r）+ 审计写入（reason/problem/approach 必填）+ git 自动提交
  - 五层防御：L1 文件锁 / L2 监控 / L3 git hook / L4 启动校验 / L5 自指纹

实施状态：Phase 1 CLI MVP
  - [x] Step 2: 框架 + 启动读 README
  - [ ] Step 3: init
  - [ ] Step 4: lock / unlock
  - [ ] Step 5: write（核心）
  - [ ] Step 6: log
  - [ ] Step 7: SHA256 自指纹
"""
import argparse
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# README summary 用的分组正则
_RE_GROUP = re.compile(r"^(P[0-3]|UX)(?:\b| )")
_RE_STEP = re.compile(r"\*\*([^*]+)\*\*")

# Phase 10: i18n（国际化）— t() 函数 + 语言包
from pandaone import i18n as _i18n
from pandaone.i18n import t, t_bilingual, init as i18n_init

# 修复 Windows GBK 编码问题（PyInstaller 打包后默认 GBK）
# 确保 stdout/stderr 支持 UTF-8，中文不乱码
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
# 路径常量
# ============================================================
ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
# 指纹文件放用户目录（避免 pip 安装后被覆盖）
FP_PATH = Path.home() / ".pandaone_fp.txt"


# ============================================================
# README 摘要（启动必读）
# ============================================================
def load_banner():
    """
    加载并返回 ASCII 启动 banner（带品牌色 ANSI 转义）

    第一性原理:
      - CLI 是产品的"门面"——第一印象决定专业度
      - banner 用 ANSI 颜色，Windows CMD 需先 reconfigure UTF-8
      - 文件读取失败时降级为纯文本（不阻断启动）
      - tagline 走 i18n（zh-CN / en）
    """
    try:
        from pathlib import Path
        banner_path = Path(__file__).parent / "banner.txt"
        if not banner_path.exists():
            return []
        text = banner_path.read_text(encoding="utf-8")
        # i18n: 替换 tagline 占位符
        text = text.replace("__TAGLINE__", t("banner_tagline"))
        # ANSI 颜色：Pandaone 用紫色主题（与品牌色一致）
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RESET = "\033[0m"
        MAGENTA = "\033[95m"
        INDIGO = "\033[94m"
        CYAN = "\033[96m"
        colored_lines = []
        for line in text.splitlines():
            if "█████" in line:
                colored_lines.append(f"{MAGENTA}{BOLD}{line}{RESET}")
            elif "🐼" in line:
                colored_lines.append(f"{CYAN}{line}{RESET}")
            elif "───" in line:
                colored_lines.append(f"{INDIGO}{DIM}{line}{RESET}")
            else:
                colored_lines.append(line)
        return colored_lines
    except Exception:
        return []


def load_readme_summary():
    """
    解析 README.md，输出：
      - 当前阶段段落
      - 已完成步骤（[x] 标记行）

    第一性原理：
      README 的"当前阶段"段落用 `- [x]` 标记已完成步骤，
      所以"已完成"是从阶段段落里提取，不是从"实施步骤记录"段落里。
    """
    if not README_PATH.exists():
        # v0.7.22 P2-1 + P2-4 fix:
        #   P2-1 之前这里写死 "CLI 无法运行", 但调用方只是把它当普通行 print 掉,
        #         命令照常执行并正常退出 —— 文案与行为直接矛盾, 误导用户。
        #   P2-4 之前是硬编码中文字符串, 英文用户永远看到中文; i18n 里的
        #         err_readme_missing 中英各有一份却从未被调用。现在统一走 i18n。
        return [t("err_readme_missing")]

    text = README_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    out = []
    out.append("=" * 64)
    out.append(t("readme_header"))
    out.append("=" * 64)
    out.append("")

    phase_lines = []      # 当前阶段段落的所有有效行
    completed_steps = []  # 已完成的 [x] Step 行（带 P0/P1/P2/P3 分组前缀）
    section = None
    current_group = None  # 当前 H3 分组标题（如 "P0 安全 (5)"），用于附加到 step 行

    for line in lines:
        stripped = line.strip()

        # v0.7.7 修复（BUG-04b）：README 既可能是纯中文标题 `## 当前阶段`，
        # 也可能是中英对照标题 `## 当前阶段 / Current Phase`（便于国际贡献者）。
        # 之前严格相等匹配，中英对照标题会让 phase_lines 永远为空，
        # 进而 `pandaone status` 显示"未设置阶段"。
        if stripped == "## 当前阶段" or stripped == "## 当前阶段 / Current Phase":
            section = "phase"
            continue

        # 任何其他 ## 标题结束"当前阶段"
        if stripped.startswith("## ") and section == "phase":
            section = None

        if section == "phase" and stripped:
            phase_lines.append(stripped)
            if stripped.startswith("### "):
                group_raw = stripped[4:].strip()
                m_grp = _RE_GROUP.match(group_raw)
                current_group = m_grp.group(1) if m_grp else None
            elif "[x]" in stripped and current_group:
                step_line = stripped.lstrip()
                m_step = _RE_STEP.search(step_line)
                if m_step:
                    rest = step_line.split("—", 1)[1].strip() if "—" in step_line else step_line
                    new_step = f"{current_group} {m_step.group(1).strip()} — {rest}"
                    completed_steps.append(new_step)
                else:
                    completed_steps.append(step_line)
            elif "[x]" in stripped:
                completed_steps.append(stripped.lstrip())

    # 输出【当前阶段】
    # Bug #4 fix: 取最后一个 **Phase 行（最新活跃阶段），而不是第一个
    # 第一性原则：README 段落里会列多个已完成 Phase + 当前进行中 Phase。
    # 当前活跃阶段 = 最后出现的 "**Phase X" 标题（README 维护者按时间顺序写）
    out.append(t("current_phase"))
    last_phase_line = None
    for ln in phase_lines:
        if ln.startswith("**Phase"):
            last_phase_line = ln
    if last_phase_line:
        out.append("  " + last_phase_line)
    else:
        # 兼容：README 段落里没有 **Phase 标题（罕见），回退到第一个有效行
        for ln in phase_lines:
            if ln:
                out.append("  " + ln)
                break

    # 输出【已完成步骤】
    if completed_steps:
        out.append("")
        out.append(t("completed_steps"))
        for step in completed_steps:
            out.append("  " + step)
    else:
        out.append(f"{t('completed_steps')}（{t('_none')}）")

    out.append("")
    out.append("=" * 64)
    return out


# ============================================================
# CLI 框架
# ============================================================
def build_parser():
    parser = argparse.ArgumentParser(
        prog="pandaone",
        description="Pandaone — AI Agent 代码审计门禁系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="store_true", help="显示版本")
    parser.add_argument("--update-fingerprint", metavar="PASSWORD",
                        help="更新 pandaone 自身 SHA256 指纹（默认密码 0000，可用 --set-fingerprint-password 自定义）")
    # v0.7.23: 指纹密码可自定义（默认值 0000 保留）
    parser.add_argument("--set-fingerprint-password", metavar="NEWPASSWORD",
                        help="设置自指纹更新密码（默认仍是 0000；自定义后存于 ~/.pandaone/fp_password）")
    parser.add_argument("--reset-fingerprint-password", action="store_true",
                        help="清除自定义指纹密码，回落到默认 0000")
    parser.add_argument("--reset-fingerprint-lock", action="store_true",
                        help="解除指纹密码的失败锁定（连续输错触发）")
    # Phase 9+: 无声 + 默认信任（右键场景一键到底）
    parser.add_argument("--silent", action="store_true",
                        help="静默模式：跳过 banner 和 README 摘要（右键菜单调用建议带上）")
    parser.add_argument("--trust-default", action="store_true",
                        help="使用默认密码 0000 自动更新/初始化指纹（会静默重写指纹基线；右键菜单禁用，见 v0.7.20 P0-3）")
    # Phase 10: i18n 语言切换
    parser.add_argument("--lang", choices=["zh-CN", "en"], default=None,
                        help="界面语言：zh-CN（简体中文，默认）/ en（英文）。不指定则自动检测 OS 语言")

    sub = parser.add_subparsers(dest="command", help="子命令")

    # 子命令占位（按 Step 顺序实现）
    init_p = sub.add_parser("init", help="在当前文件夹初始化 Pandaone")
    init_p.add_argument("--root", default=".", help="项目根目录路径（默认当前目录）")
    init_p.add_argument("--ext", nargs="+", default=None,
                        help="自定义受保护扩展名（如 --ext .py .md .json）。不指定则用 17 种默认文本格式")
    init_p.add_argument("--no-binary", action="store_true",
                        help="禁用二进制保护（不创建 SHA256 快照）")
    # Bug #29 fix: 强制覆盖现有 config（默认保留用户自定义）
    init_p.add_argument("--force-reset", action="store_true",
                       help="强制重置 config.json（覆盖所有用户自定义字段，谨慎使用）")
    lock_p = sub.add_parser("lock", help="锁定所有受保护扩展名的文件")
    lock_p.add_argument("--root", default=".", help="项目根目录路径")
    # Bug #28 (方案 A): lock 自动 init 开关（默认开 = 首次使用友好；高级用户可关）
    lock_p.add_argument("--no-auto-init", action="store_true",
                       help="禁用自动 init（默认: 未初始化时自动调用 init）")
    unlock_p = sub.add_parser("unlock", help="解锁所有受保护扩展名的文件")
    unlock_p.add_argument("--root", default=".", help="项目根目录路径")
    log_p = sub.add_parser("log", help="查看审计历史")
    log_p.add_argument("--root", default=".", help="项目根目录路径")
    # Bug #13 fix: -n 是 --recent 的短选项别名，方便 `pandaone log -n 5`
    log_p.add_argument("-n", "--recent", type=int, default=20,
                       help="最近 N 条（默认 20）。短选项 -n 仅 log 命令可用")
    log_p.add_argument("--file", default="", help="按文件过滤")
    log_p.add_argument("--session", default="", help="按 session 过滤")
    log_p.add_argument("--rejected", action="store_true", help="只看拒绝记录")
    log_p.add_argument("--unauthorized", action="store_true", help="只看非授权写入")
    log_p.add_argument("--export", default="", help="[已废弃] 导出为 HTML 报告，请用 --format html --output PATH")
    log_p.add_argument("--format", default="",
                      help="导出格式: text(csv, tsv, json, yaml, md, html, xlsx, docx, pdf, sqlite, rst, asciidoc). 也可用 txt/sql/db/yml/adoc 别名")
    log_p.add_argument("--output", "-o", default="", help="导出文件路径（与 --format 一起使用）")
    log_p.add_argument("--from", dest="from_date", default="", help="起始日期 YYYY-MM-DD")
    log_p.add_argument("--to", dest="to_date", default="", help="截止日期 YYYY-MM-DD")
    # v0.7.3: agent 过滤 + verbose diff
    log_p.add_argument("--agent", default="", help="按 agent 过滤（claude-code / cursor / trae 等）")
    log_p.add_argument("--verbose", "-V", action="store_true", help="显示完整 diff 内容（默认仅首行）")
    # Bug #25 fix: 独立 export 子命令（语义清晰，不再借用 log）
    export_p = sub.add_parser(
        "export",
        help="导出审计记录为文件（支持 html/json/csv/md/xlsx/docx/pdf/rst/asciidoc 等）",
    )
    export_p.add_argument("--root", default=".", help="项目根目录路径")
    export_p.add_argument("--format", "-f", required=True,
                         help="导出格式: html, json, csv, md, xlsx, docx, pdf, text, yaml, sqlite, rst, asciidoc")
    export_p.add_argument("--output", "-o", required=True, help="导出文件路径")
    export_p.add_argument("--file", default="", help="按文件过滤")
    export_p.add_argument("--session", default="", help="按 session 过滤")
    export_p.add_argument("--rejected", action="store_true", help="只看拒绝记录")
    export_p.add_argument("--unauthorized", action="store_true", help="只看非授权写入")
    export_p.add_argument("--from", dest="from_date", default="", help="起始日期 YYYY-MM-DD")
    export_p.add_argument("--to", dest="to_date", default="", help="截止日期 YYYY-MM-DD")
    install_git_p = sub.add_parser("install-git", help="探测/安装 git")
    install_git_p.add_argument("--probe-only", action="store_true", help="只探测不下载")
    install_git_p.add_argument("--auto-download", action="store_true", help="自动下载 portable git")
    install_hook_p = sub.add_parser("install-hook", help="安装 pre-commit hook")
    install_hook_p.add_argument("--root", default=".", help="项目根目录")
    install_hook_p.add_argument("--uninstall", action="store_true", help="卸载 hook")
    status_p = sub.add_parser("status", help="查看状态")
    status_p.add_argument("--root", default=".", help="项目根目录路径")
    watch_p = sub.add_parser("watch", help="启动 watchdog 监控")
    watch_p.add_argument("--root", default=".", help="项目根目录路径")
    watch_p.add_argument("--daemon", action="store_true", help="后台运行")

    serve_p = sub.add_parser("serve", help="启动 Web 仪表盘(浏览器访问,实时推送)")
    serve_p.add_argument("--root", default=".", help="项目根目录路径")
    serve_p.add_argument("--port", type=int, default=8765, help="HTTP 端口(默认 8765)")

    # Phase 7: CI 子命令（GitHub Actions 集成）
    ci_p = sub.add_parser("ci", help="CI 验证：检查 PR 所有变更都有审计")
    ci_p.add_argument("--root", default=".", help="项目根目录")
    ci_p.add_argument("--base", default="", help="基线分支（默认 main）")
    ci_p.add_argument("--head", default="HEAD", help="当前 HEAD（默认 HEAD）")

    # write 子命令参数
    write_p = sub.add_parser("write", help="审计写入（核心）")
    write_p.add_argument("--root", default=".", help="项目根目录路径")
    write_p.add_argument("--file", required=True, help="目标 .py 文件路径")
    write_p.add_argument("--reason", default="", help="改动原因（必填）")
    write_p.add_argument("--problem", default="", help="解决的问题（必填）")
    write_p.add_argument("--approach", default="", help="采用的方法（必填）")
    write_p.add_argument("--old", default="", help="原字符串（模式 1，仅文本文件）")
    write_p.add_argument("--new", default="", help="新字符串（模式 1，仅文本文件）")
    write_p.add_argument("--content", default="", help="整文件文本内容（模式 2）")
    write_p.add_argument("--content-base64", default="", help="整文件二进制内容（base64 编码）")
    write_p.add_argument("--from-file", default="", help="从本地文件读取内容（二进制或文本均可）")
    write_p.add_argument(
        "--force-write",
        action="store_true",
        help=(
            "允许覆盖 L1 锁定的文件（默认拒绝 ReadOnly 文件以确保审计门禁，"
            "加此标志走完整 unlock-write-lock 流程并审计记录 force_write=true）"
        ),
    )
    # v0.7.3: 记录调用 agent 身份
    write_p.add_argument(
        "--agent",
        default="user:anonymous",
        help="调用方身份（claude-code/cursor/trae/user:name 等，默认 user:anonymous）",
    )

    # Phase 9: OS 右键菜单集成
    ic_p = sub.add_parser("install-context", help="安装 OS 右键菜单（自动检测 Windows / macOS / Linux）")
    ic_p.add_argument("--force", action="store_true", help="强制重新安装（仅 Windows 生效）")
    ic_p.add_argument("--lang", choices=["zh-CN", "en"], default=None,
                      help="右键菜单 UI 语言（默认跟随 pandaone 当前语言）")
    uc_p = sub.add_parser("uninstall-context", help="卸载 OS 右键菜单（自动检测平台）")

    return parser


# ============================================================
