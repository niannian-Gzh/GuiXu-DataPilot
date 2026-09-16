import duckdb
import pandas as pd
from datetime import date, timedelta


EVENT_FIELDS = {
    "issued": ("issued_date", "下发"),
    "certified": ("certified_date", "下证"),
    "rejected": ("reject_date", "打回"),
    "resubmitted": ("resubmit_date", "重提"),
}


def _to_date_str(v):
    if v is None or pd.isna(v):
        return None
    return str(v)[:10]


def get_period(period_type: str) -> tuple:
    today = date.today()
    if period_type == "day":
        return today.isoformat(), today.isoformat()
    if period_type == "week":
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), sunday.isoformat()
    if period_type == "month":
        first = today.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        last = next_month - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    raise ValueError(f"未知周期类型：{period_type}")


def count_event(event: str, start: str, end: str, ctx) -> dict:
    field, label = EVENT_FIELDS[event]
    con = duckdb.connect(ctx.db_path, read_only=True)
    df = con.execute(f"""
        SELECT project_name, owner, category, {field} AS event_date
        FROM {ctx.real_table}
        WHERE is_deleted = false
          AND {field} IS NOT NULL
          AND CAST({field} AS DATE) >= CAST(? AS DATE)
          AND CAST({field} AS DATE) <= CAST(? AS DATE)
        ORDER BY {field}
    """, [start, end]).fetchdf()
    con.close()

    details = [
        {
            "project_name": row["project_name"],
            "owner": row["owner"],
            "category": row["category"],
            "date": _to_date_str(row["event_date"]),
        }
        for _, row in df.iterrows()
    ]
    return {"count": len(details), "details": details}


def by_owner(event: str, start: str, end: str, ctx) -> list:
    field, _ = EVENT_FIELDS[event]
    con = duckdb.connect(ctx.db_path, read_only=True)
    df = con.execute(f"""
        SELECT owner, project_name
        FROM {ctx.real_table}
        WHERE is_deleted = false
          AND {field} IS NOT NULL
          AND CAST({field} AS DATE) >= CAST(? AS DATE)
          AND CAST({field} AS DATE) <= CAST(? AS DATE)
    """, [start, end]).fetchdf()
    con.close()

    grouped = {}
    for _, row in df.iterrows():
        grouped.setdefault(row["owner"], []).append(row["project_name"])

    return [
        {"owner": o, "count": len(p), "projects": p}
        for o, p in sorted(grouped.items(), key=lambda x: -len(x[1]))
    ]


def by_category(event: str, start: str, end: str, ctx) -> list:
    field, _ = EVENT_FIELDS[event]
    con = duckdb.connect(ctx.db_path, read_only=True)
    df = con.execute(f"""
        SELECT category, project_name
        FROM {ctx.real_table}
        WHERE is_deleted = false
          AND {field} IS NOT NULL
          AND CAST({field} AS DATE) >= CAST(? AS DATE)
          AND CAST({field} AS DATE) <= CAST(? AS DATE)
    """, [start, end]).fetchdf()
    con.close()

    grouped = {}
    for _, row in df.iterrows():
        cat = row["category"] or "未分类"
        grouped.setdefault(cat, []).append(row["project_name"])

    return [
        {"category": c, "count": len(p), "projects": p}
        for c, p in sorted(grouped.items(), key=lambda x: -len(x[1]))
    ]


def collect(start: str, end: str, items: list, ctx) -> dict:
    """收集指定事件的数据。"""
    result = {"period": {"start": start, "end": end}, "events": []}
    for event in items:
        field, label = EVENT_FIELDS[event]
        result["events"].append({
            "key": event,
            "label": label,
            "count": count_event(event, start, end, ctx)["count"],
            "details": count_event(event, start, end, ctx)["details"],
            "by_owner": by_owner(event, start, end, ctx),
            "by_category": by_category(event, start, end, ctx),
        })
    return result

def get_period(period_type: str, offset: int = 0) -> tuple:
    today = date.today()
    if period_type == "day":
        target = today + timedelta(days=offset)
        return target.isoformat(), target.isoformat()
    if period_type == "week":
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), sunday.isoformat()
    if period_type == "month":
        first = today.replace(day=1)
        if offset:
            # 往前/后推 N 个月
            y, m = first.year, first.month + offset
            while m <= 0:
                y -= 1
                m += 12
            while m > 12:
                y += 1
                m -= 12
            first = date(y, m, 1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        last = next_month - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    raise ValueError(f"未知周期类型：{period_type}")