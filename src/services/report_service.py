import json
from datetime import datetime
from pathlib import Path
from config import PROJECT_ROOT
from services.report import stats, charts
from services.report.render import render_html, html_to_pdf
from datetime import date


# 品牌名。文件名那里要把它从标题里剥掉，两处必须同源——
# 各写一遍的话，改了标题忘了文件名，导出的 PDF 就带着品牌前缀
BRAND = "数据处理 Agent"


def _period_label(period_type: str, start: str) -> str:
    d = date.fromisoformat(start)
    if period_type == "day":
        return f"{BRAND} · {d.year}年{d.month}月{d.day}日日报"
    if period_type == "week":
        week_num = (d.day - 1) // 7 + 1
        return f"{BRAND} · {d.year}年{d.month}月第{week_num}周周报"
    if period_type == "month":
        return f"{BRAND} · {d.year}年{d.month}月月报"
    return f"{BRAND} · 报告"

REPORT_DIR = PROJECT_ROOT / "data" / "reports"


def _llm_summary(report_data: dict, period_type_label: str, llm) -> str:
    events_text = "\n".join(
        f"- {e['label']}：{e['count']} 条" for e in report_data["events"]
    )
    prompt = f"""请为以下{period_type_label}写一段简短概述（2-3句话，不超过100字）。

统计周期：{report_data['period']['start']} ~ {report_data['period']['end']}

事件统计：
{events_text}

要求：
- 只基于以上数字，不要编造
- 语气客观、简洁
- 不重复列表里的数字罗列，做"概括性"描述"""
    return llm.chat("你是一个数据分析助手", prompt).strip()


def run(period: str, items: list, ctx, custom_start: str = None, custom_end: str = None, offset: int = 0) -> str:
    """生成报告。period: day/week/month；items: ['issued', 'certified', ...]"""
    if not items:
        items = ["issued", "certified", "rejected"]

    if custom_start and custom_end:
        start, end = custom_start, custom_end
        period_label = f"{BRAND} · {start} 至 {end} 的总结报告"
    else:
        start, end = stats.get_period(period, offset)
        period_label = _period_label(period, start)

    report_data = stats.collect(start, end, items, ctx)

    # 画图
    event_chart = charts.event_bar_chart(report_data["events"])
    for e in report_data["events"]:
        e["owner_chart"] = charts.owner_bar_chart(e["by_owner"], f"{e['label']} · 按负责人分布")

    # LLM 概述
    summary = _llm_summary(report_data, period_label, ctx.llm)

    # 渲染
    context = {
        "period_type_label": period_label,
        "period": report_data["period"],
        "events": report_data["events"],
        "event_chart": event_chart,
        "summary": summary,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    html = render_html(context)

    # 输出文件
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 文件名用中文
    if custom_start and custom_end:
        name_part = f"{start}至{end}汇总报告"
    else:
        name_part = _period_label(period, start).replace(f"{BRAND} · ", "")
    filename = f"{name_part}_{timestamp}.pdf"
    file_path = REPORT_DIR / filename
    html_to_pdf(html, file_path)

    return json.dumps({
        "status": "ok",
        "file_path": str(file_path.relative_to(PROJECT_ROOT)),
        "period": report_data["period"],
        "summary": summary,
        "answer": f"{period_label}已生成：{file_path.relative_to(PROJECT_ROOT)}",
    }, ensure_ascii=False)