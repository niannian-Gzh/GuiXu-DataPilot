import json
from datetime import datetime

import storage
from nl2sql import get_schema, generate_filter_sql
from execute import execute_sql
from services import UserInputRequired, bulk_threshold, card_columns, card_records
from audit import log
from runner import execute, using


def find_deleted(filter_question: str, ctx) -> list:
    """在已软删除的记录里按自然语言条件筛选。

    schema 用**业务名**读（`get_schema` 走的是表定义），而 SQL 打**底表**——
    已删的行只在底表里看得见。
    """
    schema = get_schema(ctx.table_name)
    sql = generate_filter_sql(filter_question, ctx.llm, schema, ctx.real_table)
    # 外层强制限定在已删除集合内，无论模型生成了什么条件
    wrapped = (
        f"SELECT * FROM ({sql}) WHERE is_deleted = true "
        f"ORDER BY deleted_at DESC"
    )
    df = execute_sql(wrapped)
    return df.to_dict("records")


def request_restore(filter_question: str, ctx) -> str:
    candidates = find_deleted(filter_question, ctx)
    if not candidates:
        return json.dumps(
            {"ok": True, "status": "empty", "message": "没有找到可恢复的记录"},
            ensure_ascii=False,
        )
    labels, rows = card_records(ctx, candidates)
    pending = {
        "type": "restore",
        "stage": "confirm",
        # —— 卡片字段 ——
        "table": ctx.table_name,
        "columns": labels,
        "records": rows,
        "affected": len(candidates),
        "danger": False,
        # —— 内部字段 ——
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


def list_deleted(table_name: str, ctx) -> str:
    """列出这张表里被删掉、还能恢复的行。

    **只读，不用确认。** 跟"恢复"分开：恢复要用户看着记录点头，
    而"我删过哪些"是一个问题，模型答得上就行。

    走底表——已删的行在视图里根本看不见。多带一列「删除时间」，
    它是垃圾桶的倒计时起点，模型回答时也用得上。
    """
    keys, labels = card_columns(ctx)
    all_name = table_name + storage.SOFTDEL_SUFFIX
    biz = [k for k in keys if k not in storage.SYSTEM_COLS]

    def _read(con):
        cols = storage.columns_of(con, all_name)
        keep = [c for c in biz if c in cols]
        return con.execute(
            f"SELECT {', '.join(storage.quote(c) for c in keep)}, deleted_at "
            f"FROM {storage.quote(all_name)} WHERE is_deleted = 1 "
            f"ORDER BY deleted_at DESC"
        ).fetchall(), keep

    rows, keep = using(_read)
    keep_labels = [lab for k, lab in zip(keys, labels) if k in keep]

    return json.dumps({
        "ok": True,
        "status": "empty" if not rows else "ok",
        "table": table_name,
        "columns": keep_labels + ["删除时间"],
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
    }, ensure_ascii=False)


def execute_restore(candidates, table_name: str, trace_id: str, user_input: str) -> int:
    """恢复。**走底表的特权旁路**——视图里根本看不见已删的行。

    只清两个系统列，其余不动。`deleted_by` / `delete_trace_id` 是旧版
    留下的列名，早就不存在了，这里也不该再提。
    """
    pk = using(storage.pk_of, table_name + storage.SOFTDEL_SUFFIX)
    if not pk:
        return 0

    ids = [c[pk] for c in candidates]
    marks = ",".join("?" * len(ids))
    execute(
        f"UPDATE {storage.quote(table_name + storage.SOFTDEL_SUFFIX)} "
        f"SET is_deleted = 0, deleted_at = NULL "
        f"WHERE {storage.quote(pk)} IN ({marks})",
        ids,
    )

    log("restore", {
        "trace_id": trace_id,
        "user_input": user_input,
        "table": table_name,
        "affected_count": len(ids),
        "affected_ids": ids,
    })
    return len(ids)
