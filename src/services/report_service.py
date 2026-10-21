"""生成报告。**只管排版和落文件，不统计。**

旧版把软著表的四个日期列、负责人、分类硬编码在 `report/stats.py` 里——
换一张表就没有报告可生成。那不是一个数据工具的"报告"能力，
是那套测试数据的业务功能。

现在统计交给模型：它先用 `query_database` 取数、自己算清楚，
再把结果按 `sections` 交给这里。**文字、表格、图表都由模型给形状，
这里只负责画和排版。** 这也正是「产出类工具」的定位——读数据、
落文件，不改数据。
"""

import json
from datetime import datetime

from config import PROJECT_ROOT
from services import stamped_filename
from services.report import charts
from services.report.render import render_html, html_to_pdf


REPORT_DIR = PROJECT_ROOT / "data" / "reports"

# 再多就不像报告了，像导出
MAX_SECTIONS = 12


def _normalize_section(raw: dict) -> dict:
    """把模型给的一节摊平。

    chart 在这一步就画成 base64——模板不该知道怎么调 matplotlib；
    table 保证是二维行（列名 + 每行一个数组），前端和模板都按这个读。
    """
    table = raw.get("table") or {}
    chart = raw.get("chart") or {}
    labels = chart.get("labels") or []

    return {
        "heading": str(raw.get("heading") or ""),
        "body": str(raw.get("body") or ""),
        "chart_src": charts.bar_chart(
            labels, chart.get("values") or [], str(chart.get("title") or ""),
        ) if labels else "",
        "table": {
            "columns": [str(c) for c in (table.get("columns") or [])],
            "rows": [list(r) for r in (table.get("rows") or [])],
        } if table.get("columns") else None,
    }


def run(title: str, intro: str, sections: list) -> str:
    """把一段整理好的内容渲染成 PDF。

    `sections` 每项：`{heading, body?, table?: {columns, rows}, chart?: {labels, values, title?}}`
    """
    title = (title or "").strip()
    if not title:
        return json.dumps(
            {"ok": False, "error": "标题不能为空", "error_type": "invalid"},
            ensure_ascii=False,
        )
    if not sections:
        return json.dumps(
            {"ok": False, "error": "至少要有一节（sections 为空）",
             "error_type": "invalid"},
            ensure_ascii=False,
        )
    if len(sections) > MAX_SECTIONS:
        return json.dumps(
            {"ok": False, "error": f"最多 {MAX_SECTIONS} 节，收到 {len(sections)} 节",
             "error_type": "invalid"},
            ensure_ascii=False,
        )

    prepared = [_normalize_section(s) for s in sections]
    html = render_html({
        "title": title,
        "intro": (intro or "").strip(),
        "sections": prepared,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = stamped_filename(
        title, "pdf", max_len=60, fallback="报告", unique=True,
    )
    file_path = REPORT_DIR / filename
    html_to_pdf(html, file_path)

    return json.dumps({
        "ok": True,
        "file_path": str(file_path.relative_to(PROJECT_ROOT)),
        "section_count": len(prepared),
    }, ensure_ascii=False)
