"""修改记录。

**不认识业务字段。** 定位用**主键**，改哪些列由模型给。

旧版用 `project_name` 定位——那是软著表的一个列名，换张表就找不到行；
而 `recompute_status_flags`（改状态文本时联动五个布尔字段）更是把
"这张表长什么样"写进了服务层。**那种联动该是数据库触发器的事**：
它属于数据的一致性，不属于某一次业务动作。

唯一保留的"不许改"是系统列（`is_deleted` / `deleted_at`）——
那不是业务限制，是隔离机制的地基。
"""

import json
import sqlite3

import storage
from audit import record
from runner import transaction, using
from services import UserInputRequired, bulk_threshold, card_columns, card_records
from services._filters import find_candidates


def _label_map(ctx) -> tuple[list[str], dict]:
    keys, labels = card_columns(ctx)
    return keys, dict(zip(keys, labels))


def request_update(filter_question: str, updates: dict, ctx) -> str:
    keys, lab = _label_map(ctx)
    known = set(keys)

    blocked = [f for f in updates if f in storage.SYSTEM_COLS]
    if blocked:
        return json.dumps(
            {"ok": False, "error": f"这些是系统列，不能改：{blocked}",
             "error_type": "security"},
            ensure_ascii=False,
        )

    unknown = [f for f in updates if f not in known]
    if unknown:
        return json.dumps(
            {"ok": False, "error": f"表里没有这些列：{unknown}。可用的有：{keys}",
             "error_type": "invalid"},
            ensure_ascii=False,
        )

    if not updates:
        return json.dumps(
            {"ok": False, "error": "没有给出要改成什么", "error_type": "invalid"},
            ensure_ascii=False,
        )

    candidates = find_candidates(filter_question, ctx)
    if not candidates:
        total = using(
            lambda con: con.execute(
                f"SELECT COUNT(*) FROM {storage.quote(ctx.table_name)}"
            ).fetchone()[0]
        )
        return json.dumps(
            {"ok": True, "status": "empty", "table": ctx.table_name,
             "row_count": 0, "total_records_in_table": total},
            ensure_ascii=False,
        )

    n = len(candidates)
    labels, rows = card_records(ctx, candidates)

    # 字段级 diff：前 N 条各不相同的时候，只报"各不相同"，不假装有个统一原值
    changes = [
        {
            "field": lab.get(field, field),
            "before": candidates[0].get(field) if n == 1 else f"（{n} 条各不相同）",
            "after": new,
        }
        for field, new in updates.items()
    ]

    raise UserInputRequired(
        question=f"找到 {n} 条匹配，等待用户确认",
        pending_action={
            "type": "update",
            "stage": "confirm",
            "table": ctx.table_name,
            "columns": labels,
            "records": rows,
            "affected": n,
            "danger": n > bulk_threshold(),
            "changes": changes,
            # —— 内部字段 ——
            "table_name": ctx.table_name,
            "real_table": ctx.real_table,
            "candidates": candidates,
            "updates": updates,
            "user_input": ctx.trace.data["question"],
            "trace_id": ctx.trace.id,
        },
    )


def execute_update(candidates, updates, table_name, trace_id, user_input):
    """按主键更新。返回 JSON——affected 是数据库实际改的行数，不是"找到几行"。"""
    pk = using(storage.pk_of, table_name + storage.SOFTDEL_SUFFIX)
    if not pk:
        return json.dumps(
            {"ok": False, "error": "这张表没有主键，无法精确定位要改的行",
             "error_type": "invalid"},
            ensure_ascii=False,
        )

    ids = [c[pk] for c in candidates]
    set_clause = ", ".join(f"{storage.quote(k)} = ?" for k in updates)
    marks = ", ".join("?" * len(ids))

    try:
        with transaction() as tx:
            before = tx.total_changes
            tx.execute(
                f"UPDATE {storage.quote(table_name)} SET {set_clause} "
                f"WHERE {storage.quote(pk)} IN ({marks})",
                list(updates.values()) + ids,
            )
            affected = tx.total_changes - before
            # 审计和写入在同一个事务里：要么都成，要么都不成
            record(tx, "update", {
                "trace_id": trace_id, "user_input": user_input,
                "table": table_name, "affected_count": affected,
                "changes": updates, "affected_ids": ids,
            })
    except sqlite3.IntegrityError as e:
        err = storage.translate(None, e)
        kind = "duplicate" if isinstance(err, storage.Duplicate) else "constraint"
        return json.dumps(
            {"ok": False, "error": str(err), "error_type": kind}, ensure_ascii=False
        )
    return json.dumps(
        {"ok": True, "table": table_name, "affected": affected,
         "changes": [{"field": k, "to": v} for k, v in updates.items()]},
        ensure_ascii=False,
    )
