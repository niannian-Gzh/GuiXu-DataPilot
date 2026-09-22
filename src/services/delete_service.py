import json
import re
from services import UserInputRequired, bulk_threshold
from services._filters import find_candidates
from audit import log
from display import format_table
from config import setting
from db import execute


CONFIRM_WORDS = {"确认", "确定", "是", "对", "好", "可以", "删", "删除", "删吧", "yes", "y", "ok"}
CANCEL_WORDS = {"取消", "不", "不要", "算了", "放弃", "no", "n", "cancel"}


def request_delete(filter_question: str, ctx) -> str:
    candidates = find_candidates(filter_question, ctx)
    if not candidates:
        return json.dumps(
            {"status": "not_found", "message": "没有找到匹配的记录"},
            ensure_ascii=False,
        )
    pending = {
        "type": "delete",
        "stage": "confirm",
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "candidates": candidates,
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"找到 {len(candidates)} 条匹配，等待用户确认",
        pending_action=pending,
    )


def format_candidates(candidates: list) -> str:
    n = len(candidates)
    all_threshold = setting("display.display_all_threshold")
    sample_count = setting("display.display_sample_count")
    if n <= all_threshold:
        shown = candidates
        note = ""
    else:
        shown = candidates[:sample_count]
        note = f"\n\n（共 {n} 条，此处仅显示前 {sample_count} 条）"

    rows = [
        {
            "项目名称": c.get("project_name", ""),
            "负责人": c.get("owner", "") or "",
            "状态": c.get("status_raw", "") or "",
        }
        for c in shown
    ]
    return f"找到 **{n}** 条匹配：\n\n" + format_table(rows) + note


def delete_confirm_prompt(candidates: list) -> str:
    n = len(candidates)
    if n <= bulk_threshold():
        return (
            f"确认删除这 {n} 条吗？\n"
            f"删除后 7 天内可恢复，之后永久清理。\n"
            f"回复「确认」执行删除，或回复「取消」放弃。"
        )
    return (
        f"⚠️ 批量删除警告\n"
        f"即将删除 {n} 条记录。删除后 7 天内可恢复，之后永久清理。\n"
        f"如确认，请输入「删除{n}条」；或回复「取消」放弃。"
    )


def is_confirm(text: str) -> bool:
    return text.strip().lower() in CONFIRM_WORDS


def is_cancel(text: str) -> bool:
    return text.strip().lower() in CANCEL_WORDS


def is_bulk_confirm(text: str, expected_count: int) -> bool:
    nums = re.findall(r"\d+", text)
    return str(expected_count) in nums


def execute_delete(candidates, db_path, real_table, trace_id, user_input):
    names = [c["project_name"] for c in candidates]
    placeholders = ",".join(["?"] * len(names))
    execute(
        f"UPDATE {real_table} SET is_deleted = true, "
        f"deleted_at = CAST(NOW() AS TIMESTAMP), "
        f"delete_trace_id = ?, deleted_by = 'local_user' "
        f"WHERE project_name IN ({placeholders})",
        [trace_id] + names,
    )

    log("soft_delete", {
        "trace_id": trace_id,
        "user_input": user_input,
        "affected_count": len(candidates),
        "affected_records": [
            {"project_name": c["project_name"], "owner": c.get("owner", "")}
            for c in candidates
        ],
    })
    return len(candidates)