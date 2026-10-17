#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exporters.py — 多格式审计记录导出

支持的格式:
  - text   (默认表格)
  - csv    (CSV 表格)
  - json   (JSON Array)
  - md     (Markdown 表格)
  - html   (HTML 表格，dark theme)
  - xlsx   (Excel 工作簿，含样式)
  - docx   (Word 文档，含样式)

第一性原理:
  - 审计结果要"易消费"，不同受众用不同格式
  - 数据 → list[dict] 是通用中间表示；其他格式都是它的映射
  - 每个导出器是独立函数，方便单测和替换

用法:
  from exporters import export_records, FORMATTERS
  export_records(records, fmt="xlsx", path=Path("report.xlsx"))
"""
import csv
import html  # v0.7.3: for safe HTML escaping in card layout
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .i18n import t
from . import __version__

# ============================================================
# 通用工具
# ============================================================

# 导出时统一使用的列（顺序固定）
EXPORT_COLUMNS = [
    "id",
    "timestamp",
    "status",
    "file",
    "reason",
    "problem",
    "approach",
    "rejection_reason",
    "detection",
    "action",
    "commit_hash",
]


def _row_to_dict(rec: dict) -> dict:
    """把审计记录转成导出行的 dict（只含 EXPORT_COLUMNS）"""
    return {col: rec.get(col, "") for col in EXPORT_COLUMNS}


def _records_to_rows(records: list[dict]) -> list[dict]:
    return [_row_to_dict(r) for r in records]


# ============================================================
# CSV
# ============================================================

def export_csv(records: list[dict], path: Path):
    rows = _records_to_rows(records)
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig 给 Excel
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# JSON
# ============================================================

def export_json(records: list[dict], path: Path):
    payload = {
        "metadata": {
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(records),
            "source": "pandaone",
        },
        "records": records,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# Markdown
# ============================================================

def export_markdown(records: list[dict], path: Path):
    # Bug #26 fix: 标题/导出时间/记录数 走 t()
    lines = []
    lines.append(f"# {t('export_title')}")
    lines.append("")
    lines.append(f"- {t('export_exported_at', ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}")
    lines.append(f"- {t('export_summary', n=len(records))}")
    lines.append("")
    # 表头
    lines.append("| " + " | ".join(EXPORT_COLUMNS) + " |")
    lines.append("| " + " | ".join(["---"] * len(EXPORT_COLUMNS)) + " |")
    # 数据行
    for rec in records:
        row = _row_to_dict(rec)
        cells = [str(row[col]).replace("|", "\\|").replace("\n", " ") for col in EXPORT_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# HTML（dark theme）
# ============================================================

def export_html(records: list[dict], path: Path):
    # v0.7.3: 每条记录用卡片式布局，diff 字段可折叠展开
    cards = []
    for r in records:
        status = r.get("status", "?")
        color = {
            "APPROVED": "#3fb950",
            "REJECTED": "#f85149",
            "UNAUTHORIZED": "#d29922",
        }.get(status, "#8b949e")
        agent = r.get("agent", "user:anonymous")
        # diff 块（仅 APPROVED 且有 old/new）
        diff_block = ""
        if status == "APPROVED" and (r.get("old_content") or r.get("new_content")):
            old_lines = (r.get("old_content") or "").splitlines()
            new_lines = (r.get("new_content") or "").splitlines()
            old_html = "".join(
                f"<div style='color:#f85149;background:#3d1f1f;padding:2px 6px;font-family:monospace;'>- {html.escape(line)}</div>"
                for line in old_lines
            )
            new_html = "".join(
                f"<div style='color:#3fb950;background:#1f3d2b;padding:2px 6px;font-family:monospace;'>+ {html.escape(line)}</div>"
                for line in new_lines
            )
            diff_block = (
                f"<details style='margin-top:8px;'><summary style='cursor:pointer;color:#58a6ff;'>"
                f"{t('panel_diff')} (v0.7.3)</summary>"
                f"<div style='margin-top:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:6px;'>"
                f"{old_html}{new_html}"
                f"</div></details>"
            )
        # 卡片
        reason = r.get("reason") or r.get("rejection_reason") or r.get("detection") or ""
        problem = r.get("problem") or ""
        approach = r.get("approach") or ""
        commit = r.get("commit_hash", "")[:12]
        cards.append(
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:6px;"
            f"padding:12px;margin-bottom:12px;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<div><span style='color:{color};font-weight:bold;font-size:14px;'>{status}</span> "
            f"<span style='color:#8b949e;'>{r.get('id', '')}</span> "
            f"<span style='color:#8b949e;font-size:12px;'>{r.get('timestamp', '')}</span></div>"
            f"<div style='color:#58a6ff;font-size:12px;'>🤖 {html.escape(agent)}</div>"
            f"</div>"
            f"<div style='margin-top:8px;font-size:13px;'>"
            f"<div><strong>{t('panel_file')}:</strong> <code>{html.escape(r.get('file', ''))}</code> "
            f"<strong>{t('panel_commit')}:</strong> <code>{commit or '—'}</code></div>"
            f"<div style='margin-top:4px;'><strong>{t('panel_reason')}:</strong> {html.escape(reason)}</div>"
            + (f"<div><strong>{t('panel_problem')}:</strong> {html.escape(problem)}</div>" if problem else "")
            + (f"<div><strong>{t('panel_approach')}:</strong> {html.escape(approach)}</div>" if approach else "")
            + diff_block
            + f"</div></div>"
        )

    body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{t("export_title")}</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
h1 {{ color: #f0f6fc; }}
</style></head>
<body>
<h1>{t("export_title")}</h1>
<p>{t("export_exported_at", ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} | {t("export_summary", n=len(records))}</p>
{''.join(cards)}
</body></html>"""
    path.write_text(body, encoding="utf-8")


# ============================================================
# Excel (xlsx) — 含样式
# ============================================================

def export_xlsx(records: list[dict], path: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "审计记录"

    # 标题行
    headers = ["ID", "时间", "状态", "文件", "原因", "问题", "方法",
               "拒绝原因", "检测方式", "动作", "Commit"]
    ws.append(headers)

    # 样式
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    status_colors = {
        "APPROVED": "C6EFCE",     # 绿
        "REJECTED": "FFC7CE",     # 红
        "UNAUTHORIZED": "FFEB9C", # 黄
    }
    center = Alignment(horizontal="center", vertical="center")

    # 表头样式
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    # 数据行
    for rec in records:
        row = _row_to_dict(rec)
        ws.append([row[col] for col in EXPORT_COLUMNS])
        # 状态列染色
        status_cell = ws.cell(row=ws.max_row, column=3)  # status 是第 3 列
        status_cell.fill = PatternFill(
            start_color=status_colors.get(rec.get("status", ""), "FFFFFF"),
            end_color=status_colors.get(rec.get("status", ""), "FFFFFF"),
            fill_type="solid",
        )

    # 列宽
    widths_px = [12, 20, 14, 30, 30, 30, 30, 30, 30, 30, 12]
    for i, w in enumerate(widths_px, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    # 冻结表头
    ws.freeze_panes = "A2"

    wb.save(str(path))


# ============================================================
# Word (docx) — 含样式
# ============================================================

def export_docx(records: list[dict], path: Path):
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # 标题
    title = doc.add_heading("Pandaone AI Agent 审计报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 元数据
    meta = doc.add_paragraph()
    meta.add_run(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n").bold = True
    meta.add_run(f"记录数：{len(records)}\n")

    # 表格
    table = doc.add_table(rows=1, cols=len(EXPORT_COLUMNS))
    table.style = "Light Grid Accent 1"

    # 表头
    hdr = table.rows[0].cells
    for i, col in enumerate(EXPORT_COLUMNS):
        cell = hdr[i]
        cell.text = col
        # 加粗表头
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True

    # 数据行
    for rec in records:
        row = _row_to_dict(rec)
        cells = table.add_row().cells
        for i, col in enumerate(EXPORT_COLUMNS):
            cells[i].text = str(row[col])

    doc.save(str(path))


# ============================================================
# PDF (reportlab) — 单页 A4 横向表格
# ============================================================

def export_pdf(records: list[dict], path: Path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    # 尝试注册中文字体（避免方块字）
    font_name = "Helvetica"
    try:
        # 尝试找系统中文字体
        for fname in [
            r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
            r"C:\Windows\Fonts\simhei.ttf",     # 黑体
            r"C:\Windows\Fonts\simsun.ttc",     # 宋体
            "/System/Library/Fonts/PingFang.ttc",  # macOS
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux
        ]:
            if Path(fname).exists():
                pdfmetrics.registerFont(TTFont("CJK", fname))
                font_name = "CJK"
                break
    except Exception:
        pass

    doc = SimpleDocTemplate(
        str(path), pagesize=landscape(A4),
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    style_title = styles["Title"]
    style_title.fontName = font_name
    style_normal = styles["Normal"]
    style_normal.fontName = font_name

    elements = []
    elements.append(Paragraph("Pandaone 审计报告", style_title))
    elements.append(Paragraph(
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"记录数：{len(records)}",
        style_normal,
    ))
    elements.append(Spacer(1, 0.5 * cm))

    # 表格数据
    data = [EXPORT_COLUMNS]
    for rec in records:
        row = _row_to_dict(rec)
        data.append([str(row[c])[:50] for c in EXPORT_COLUMNS])  # 截断长字段

    # 列宽
    col_widths = [3 * cm, 4 * cm, 2.5 * cm, 3.5 * cm, 4 * cm, 4 * cm,
                  4 * cm, 3 * cm, 3 * cm, 3 * cm, 2 * cm]

    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F8F9FA")]),
    ]))

    # 状态列染色
    status_colors_pdf = {
        "APPROVED": colors.HexColor("#C6EFCE"),
        "REJECTED": colors.HexColor("#FFC7CE"),
        "UNAUTHORIZED": colors.HexColor("#FFEB9C"),
    }
    for i, rec in enumerate(records, 1):
        color = status_colors_pdf.get(rec.get("status", ""), colors.white)
        table.setStyle(TableStyle([
            ("BACKGROUND", (2, i), (2, i), color),
        ]))

    elements.append(table)
    doc.build(elements)


# ============================================================
# YAML
# ============================================================

def export_yaml(records: list[dict], path: Path):
    import yaml
    payload = {
        "metadata": {
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(records),
            "source": "pandaone",
            "version": __version__,
        },
        "records": records,
    }
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True,
                       default_flow_style=False, indent=2)


# ============================================================
# SQLite — 可查询数据库
# ============================================================

def export_sqlite(records: list[dict], path: Path):
    import sqlite3

    # 删旧表（如果有）
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(str(path))
    cur = conn.cursor()

    # 主表：所有审计记录
    cur.execute("""
        CREATE TABLE audit_records (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            status TEXT,
            file TEXT,
            reason TEXT,
            problem TEXT,
            approach TEXT,
            rejection_reason TEXT,
            detection TEXT,
            action TEXT,
            commit_hash TEXT
        )
    """)

    # 元数据表
    cur.execute("""
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 插入数据
    for rec in records:
        row = _row_to_dict(rec)
        cur.execute(
            "INSERT INTO audit_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row[c] for c in EXPORT_COLUMNS),
        )

    # 插入元数据
    cur.execute("INSERT INTO metadata VALUES (?, ?)",
                ("exported_at", datetime.now().isoformat()))
    cur.execute("INSERT INTO metadata VALUES (?, ?)", ("count", str(len(records))))
    cur.execute("INSERT INTO metadata VALUES (?, ?)", ("source", "pandaone"))

    # 索引
    cur.execute("CREATE INDEX idx_status ON audit_records(status)")
    cur.execute("CREATE INDEX idx_file ON audit_records(file)")
    cur.execute("CREATE INDEX idx_timestamp ON audit_records(timestamp)")

    conn.commit()
    conn.close()


# ============================================================
# reStructuredText (RST)
# ============================================================

def export_rst(records: list[dict], path: Path):
    lines = []
    lines.append("=" * 78)
    lines.append("Pandaone 审计报告")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f":导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f":记录数: {len(records)}")
    lines.append("")
    lines.append("审计记录")
    lines.append("--------")
    lines.append("")
    # RST 网格表：每行字段
    lines.append(".. list-table:: 审计记录")
    lines.append("   :header-rows: 1")
    lines.append("   :widths: 15 15 10 15 20 20 20 20 20 20 15")
    lines.append("")
    lines.append("   * - " + "\n     - ".join(EXPORT_COLUMNS))
    for rec in records:
        row = _row_to_dict(rec)
        cells = [str(row[c]).replace("\n", " ").replace("|", "\\|") for c in EXPORT_COLUMNS]
        lines.append("   * - " + "\n     - ".join(cells))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# TSV (Tab 分隔)
# ============================================================

def export_tsv(records: list[dict], path: Path):
    import csv
    rows = _records_to_rows(records)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS,
                                delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# AsciiDoc
# ============================================================

def export_asciidoc(records: list[dict], path: Path):
    lines = []
    lines.append("= Pandaone 审计报告")
    lines.append(f":doctype: article")
    lines.append(f":toc: left")
    lines.append(f":exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f":records-count: {len(records)}")
    lines.append("")
    lines.append("== 概览")
    lines.append("")
    lines.append(f"* 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"* 记录数：{len(records)}")
    lines.append("")
    lines.append("== 审计记录")
    lines.append("")
    lines.append("[cols=\"" + ",".join(["1"] * len(EXPORT_COLUMNS)) + "\"")
    lines.append("       ,options=\"header\"]")
    lines.append("|===")
    lines.append("| " + " | ".join(EXPORT_COLUMNS))
    for rec in records:
        row = _row_to_dict(rec)
        cells = [str(row[c]).replace("|", "\\|").replace("\n", " ") for c in EXPORT_COLUMNS]
        lines.append("| " + " | ".join(cells))
    lines.append("|===")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# 注册表
# ============================================================

FORMATTERS: dict[str, Callable[[list[dict], Path], None]] = {
    "text": lambda recs, path: export_text(recs, path),
    "txt": lambda recs, path: export_text(recs, path),
    "csv": export_csv,
    "json": export_json,
    "md": export_markdown,
    "markdown": export_markdown,
    "html": export_html,
    "xlsx": export_xlsx,
    "excel": export_xlsx,
    "docx": export_docx,
    "word": export_docx,
    # 新增格式
    "pdf": export_pdf,
    "yaml": export_yaml,
    "yml": export_yaml,
    "sqlite": export_sqlite,
    "db": export_sqlite,
    "rst": export_rst,
    "tsv": export_tsv,
    "asciidoc": export_asciidoc,
    "adoc": export_asciidoc,
}


def export_text(records: list[dict], path: Path):
    """text 格式：写入文件（不是 stdout）"""
    # Bug #26 fix: 标题/导出时间本地化（保持 record 行的 id=/file= 后续 #14 单独处理）
    lines = []
    lines.append("=" * 80)
    lines.append(f"{t('export_title')} ({len(records)} records)")
    lines.append(f"{t('export_exported_at', ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}")
    lines.append("=" * 80)
    for rec in records:
        lines.append("")
        lines.append(f"[{rec.get('timestamp', '?')}] {rec.get('status', '?')}  "
                     f"id={rec.get('id', '?')}  file={rec.get('file', '?')}")
        if rec.get("status") == "APPROVED":
            lines.append(f"  reason:   {rec.get('reason', '')}")
            lines.append(f"  problem:  {rec.get('problem', '')}")
            lines.append(f"  approach: {rec.get('approach', '')}")
            lines.append(f"  commit:   {rec.get('commit_hash', '')}")
        elif rec.get("status") == "REJECTED":
            lines.append(f"  reason:   {rec.get('rejection_reason', '')}")
        elif rec.get("status") == "UNAUTHORIZED":
            lines.append(f"  detection: {rec.get('detection', '')}")
            lines.append(f"  action:    {rec.get('action', '')}")
    lines.append("")
    lines.append("=" * 80)
    path.write_text("\n".join(lines), encoding="utf-8")


def export_records(records: list[dict], fmt: str, path: Path) -> bool:
    """
    按 fmt 导出 records 到 path。
    返回 True 成功 / False 失败。
    """
    formatter = FORMATTERS.get(fmt.lower())
    if formatter is None:
        supported = ", ".join(sorted(set(FORMATTERS.keys())))
        print(t("_export_unsupported", fmt=fmt))
        print(t("_export_supported", supported=supported))
        return False
    formatter(records, path)
    return True


SUPPORTED_FORMATS = sorted(set(FORMATTERS.keys()))