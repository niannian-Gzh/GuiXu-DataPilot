import json
from datetime import datetime
from nl2sql import get_schema, generate_filter_sql
from execute import execute_sql
from services import UserInputRequired, bulk_threshold
from audit import log
from display import format_table
from config import setting
from db import execute


def find_deleted(filter_question: str, ctx) -> list:
    """在已软删除的记录里按自然语言条件筛选。"""
    schema = get_schema(ctx.db_path, ctx.real_table)
    sql = generate_filter_sql(filter_question, ctx.llm, schema, ctx.real_table)
    # 外层强制限定在已删除集合内，无论模型生成了什么条件
    wrapped = (
        f"SELECT * FROM ({sql}) WHERE is_deleted = true "
        f"ORDER BY deleted_at DESC"
    )
    df = execute_sql(wrapped, ctx.db_path)
    return df.to_dict("records")


def request_restore(filter_question: str, ctx) -> str:
    candidates = find_deleted(filter_question, ctx)
    if not candidates:
        return json.dumps(
            {"status": "not_found", "message": "没有找到可恢复的记录"},
            ensure_ascii=False,
        )
    pending = {
        "type": "restore",
        "stage": "confirm",
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "candidates": candidates,
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"找到 {len(candidates)} 条可恢复记录，等待用户确认",
        pending_action=pending,
    )


def _format_deleted_at(value) -> str:
    if value is None or str(value) in ("NaT", "None", ""):
        return "—"
    return str(value)[:16]


def _days_left(value) -> str:
    """距离物理清理还剩几天。"""
    if value is None or str(value) in ("NaT", "None", ""):
        return "—"
    try:
        deleted = datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return "—"
    left = 7 - (datetime.now() - deleted).days
    return f"剩 {max(left, 0)} 天"


def format_candidates(candidates: list) -> str:
    n = len(candidates)
    all_threshold = setting("display.display_all_threshold")
    sample_count = setting("display.display_sample_count")
    shown = candidates if n <= all_threshold else candidates[:sample_count]
    rows = [
        {
            "项目名称": c.get("project_name", ""),
            "负责人": c.get("owner", "") or "",
            "状态": c.get("status_raw", "") or "",
            "删除时间": _format_deleted_at(c.get("deleted_at")),
            "保留期": _days_left(c.get("deleted_at")),
        }
        for c in shown
    ]
    note = "" if n <= all_threshold else f"\n\n（共 {n} 条，此处仅显示前 {sample_count} 条）"
    return f"找到 **{n}** 条可恢复记录：\n\n" + format_table(rows) + note


def restore_confirm_prompt(candidates: list) -> str:
    n = len(candidates)
    if n <= bulk_threshold():
        return (
            f"确认恢复这 {n} 条吗？恢复后它们会重新出现在项目台账里。\n"
            f"回复「确认」执行恢复，或回复「取消」放弃。"
        )
    return (
        f"⚠️ 批量恢复\n"
        f"即将恢复 {n} 条记录。\n"
        f"如确认，请输入「恢复{n}条」；或回复「取消」放弃。"
    )


def execute_restore(candidates, db_path: str, real_table: str, trace_id: str, user_input: str) -> int:
    names = [c["project_name"] for c in candidates]
    placeholders = ",".join(["?"] * len(names))
    execute(
        f"UPDATE {real_table} SET is_deleted = false, "
        f"deleted_at = NULL, deleted_by = NULL, delete_trace_id = NULL "
        f"WHERE project_name IN ({placeholders})",
        names,
    )

    log("restore", {
        "trace_id": trace_id,
        "user_input": user_input,
        "affected_count": len(candidates),
        "affected_records": [
            {"project_name": c["project_name"], "owner": c.get("owner", "")}
            for c in candidates
        ],
    })
    return len(candidates)
