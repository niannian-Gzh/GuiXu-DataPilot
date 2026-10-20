import json
import re

import storage
from services import UserInputRequired, bulk_threshold, card_records
from services._filters import find_candidates
from audit import log
from runner import execute, using


CONFIRM_WORDS = {"确认", "确定", "是", "对", "好", "可以", "删", "删除", "删吧", "yes", "y", "ok"}
CANCEL_WORDS = {"取消", "不", "不要", "算了", "放弃", "no", "n", "cancel"}


def request_delete(filter_question: str, ctx) -> str:
    candidates = find_candidates(filter_question, ctx)
    if not candidates:
        return json.dumps(
            {"status": "not_found", "message": "没有找到匹配的记录"},
            ensure_ascii=False,
        )
    labels, records = card_records(ctx, candidates)
    pending = {
        "type": "delete",
        "stage": "confirm",
        # —— 卡片字段（前端只读这几个）——
        "table": ctx.table_name,
        "columns": labels,
        "records": records,
        "affected": len(candidates),
        "danger": len(candidates) > bulk_threshold(),
        # —— 内部字段（执行时要用，前端忽略）——
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


def is_confirm(text: str) -> bool:
    return text.strip().lower() in CONFIRM_WORDS


def is_cancel(text: str) -> bool:
    return text.strip().lower() in CANCEL_WORDS


def is_bulk_confirm(text: str, expected_count: int) -> bool:
    nums = re.findall(r"\d+", text)
    return str(expected_count) in nums


def execute_delete(candidates, table_name, trace_id, user_input):
    """软删除。**走视图的 DELETE 触发器**——不手写 `SET is_deleted = 1`。

    旧版自己拼 `UPDATE … SET is_deleted = true, deleted_at = NOW(), …`，
    三个毛病叠在一起：`NOW()` 是 PG 语法、`delete_trace_id` / `deleted_by`
    这两列根本不存在、以及用 `project_name` 定位行（换张表就找不到）。
    现在一句 DELETE，隔离层负责其余。
    """
    pk = using(storage.pk_of, table_name + storage.SOFTDEL_SUFFIX)
    if not pk:
        return 0
    ids = [c[pk] for c in candidates]
    marks = ",".join("?" * len(ids))
    affected = execute(
        f"DELETE FROM {storage.quote(table_name)} "
        f"WHERE {storage.quote(pk)} IN ({marks})",
        ids,
    )

    log("soft_delete", {
        "trace_id": trace_id,
        "user_input": user_input,
        "table": table_name,
        "affected_count": affected,
        "affected_ids": ids,
    })
    return affected