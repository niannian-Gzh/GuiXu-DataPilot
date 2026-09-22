import json
from services import UserInputRequired, bulk_threshold
from services._filters import find_candidates
from db import describe
from audit import log
from display import format_table
from db import execute


FORBIDDEN_FIELDS = {"is_deleted", "deleted_at", "deleted_by", "delete_trace_id"}


def recompute_status_flags(status_raw: str) -> dict:
    return {
        "is_pending": "待提交" in status_raw,
        "is_submitted": "已提交" in status_raw,
        "is_rejected": "已打回" in status_raw,
        "is_settled": "已结算" in status_raw,
        "is_certified": "已下证" in status_raw,
    }


def request_update(filter_question: str, updates: dict, ctx) -> str:
    for field in updates:
        if field in FORBIDDEN_FIELDS:
            return json.dumps(
                {"error": f"字段 {field} 不允许修改", "is_security": True},
                ensure_ascii=False,
            )

    valid_fields = {c["name"] for c in describe(ctx.real_table)}
    for field in updates:
        if field not in valid_fields:
            return json.dumps(
                {"error": f"字段 {field} 不存在。可用字段：{sorted(valid_fields)}"},
                ensure_ascii=False,
            )
        
    candidates = find_candidates(filter_question, ctx)
    if not candidates:
        return json.dumps(
            {"status": "not_found", "message": "没有找到匹配的记录"},
            ensure_ascii=False,
        )

    pending = {
        "type": "update", "stage": "confirm", "candidates": candidates,
        "updates": updates,
        "user_input": ctx.trace.data["question"], "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"找到 {len(candidates)} 条匹配，等待用户确认",
        pending_action=pending,
    )


def format_update_confirm(candidates: list, updates: dict) -> str:
    n = len(candidates)
    skip = {"is_pending", "is_submitted", "is_rejected", "is_settled", "is_certified"}

    if n == 1:
        record = candidates[0]
        rows = []
        for field, new_value in updates.items():
            if field in skip:
                continue
            rows.append({
                "字段": field,
                "原值": str(record.get(field, "") or "（空）"),
                "新值": str(new_value),
            })
        text = f"即将修改记录「**{record['project_name']}**」：\n\n"
        text += format_table(rows)
        text += "\n\n确认修改吗？回复「确认」执行，或「取消」放弃。"
        return text

    # 批量
    dist_rows = []
    for field in updates:
        if field in skip:
            continue
        dist = {}
        for c in candidates:
            v = str(c.get(field, "") or "（空）")
            dist[v] = dist.get(v, 0) + 1
        for value, count in dist.items():
            dist_rows.append({"字段": field, "当前值": value, "条数": count})

    text = f"即将修改 **{n}** 条记录。\n\n**修改内容：**\n\n"
    for field, new_value in updates.items():
        if field in skip:
            continue
        text += f"- {field} → {new_value}\n"

    text += "\n**改前分布：**\n\n" + format_table(dist_rows)

    if n <= bulk_threshold():
        text += f"\n\n确认修改这 {n} 条吗？回复「确认」执行，或「取消」放弃。"
    else:
        text += "\n\n**⚠️ 批量修改警告**\n如确认，请输入「修改{n}条」；或回复「取消」放弃。"
    return text


def execute_update(candidates, updates, db_path, real_table, trace_id, user_input):
    if "status_raw" in updates:
        updates = dict(updates)
        updates.update(recompute_status_flags(updates["status_raw"]))

    names = [c["project_name"] for c in candidates]
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    placeholders = ", ".join(["?"] * len(names))

    execute(
        f"UPDATE {real_table} SET {set_clause} "
        f"WHERE project_name IN ({placeholders}) AND is_deleted = false",
        list(updates.values()) + names,
    )

    log("update", {
        "trace_id": trace_id, "user_input": user_input,
        "affected_count": len(candidates),
        "changes": updates,
        "affected_records": names,
    })
    return len(candidates)