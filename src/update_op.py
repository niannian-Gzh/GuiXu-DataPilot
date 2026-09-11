import duckdb
from audit import log
from delete_op import BULK_THRESHOLD


FORBIDDEN_FIELDS = {"is_deleted", "deleted_at", "deleted_by", "delete_trace_id"}


def recompute_status_flags(status_raw: str) -> dict:
    """根据 status_raw 重算五个布尔字段。"""
    return {
        "is_pending": "待提交" in status_raw,
        "is_submitted": "已提交" in status_raw,
        "is_rejected": "已打回" in status_raw,
        "is_settled": "已结算" in status_raw,
        "is_certified": "已下证" in status_raw,
    }


def format_update_confirm(candidates: list, updates: dict) -> str:
    """生成更新确认提示。单条展示 diff，批量展示分布。"""
    n = len(candidates)

    if n == 1:
        record = candidates[0]
        lines = [f"即将修改以下记录：", ""]
        lines.append(f"  项目名称：{record['project_name']}")
        lines.append("")
        lines.append("  修改内容：")
        for field, new_value in updates.items():
            if field in ("is_pending", "is_submitted", "is_rejected", "is_settled", "is_certified"):
                continue
            old_value = record.get(field, "（空）")
            lines.append(f"    {field}: {old_value} → {new_value}")
        lines.append("")
        lines.append("确认修改吗？回复「确认」执行，或「取消」放弃。")
        return "\n".join(lines)

    # 批量
    lines = [f"即将修改 {n} 条记录：", ""]
    lines.append("  修改内容：")
    for field, new_value in updates.items():
        if field in ("is_pending", "is_submitted", "is_rejected", "is_settled", "is_certified"):
            continue
        lines.append(f"    {field} → {new_value}")

    lines.append("")
    lines.append("  改前分布：")
    for field in updates:
        if field in ("is_pending", "is_submitted", "is_rejected", "is_settled", "is_certified"):
            continue
        distribution = {}
        for c in candidates:
            v = c.get(field, "（空）")
            distribution[v] = distribution.get(v, 0) + 1
        for value, count in distribution.items():
            lines.append(f"    {field}={value}: {count} 条")

    lines.append("")
    if n <= BULK_THRESHOLD:
        lines.append(f"确认修改这 {n} 条吗？回复「确认」执行，或「取消」放弃。")
    else:
        lines.append(f"⚠️ 批量修改警告")
        lines.append(f"如确认，请输入「修改{n}条」；或回复「取消」放弃。")
    return "\n".join(lines)


def execute_update(candidates: list, updates: dict, db_path: str, real_table: str,
                   trace_id: str, user_input: str) -> int:
    """执行更新（单条或批量）。返回受影响条数。"""
    if "status_raw" in updates:
        updates = dict(updates)
        updates.update(recompute_status_flags(updates["status_raw"]))

    names = [c["project_name"] for c in candidates]
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    placeholders = ", ".join(["?"] * len(names))

    con = duckdb.connect(db_path)
    con.execute(
        f"UPDATE {real_table} SET {set_clause} "
        f"WHERE project_name IN ({placeholders}) AND is_deleted = false",
        list(updates.values()) + names,
    )
    con.close()

    log("update", {
        "trace_id": trace_id,
        "user_input": user_input,
        "affected_count": len(candidates),
        "changes": updates,
        "affected_records": [c["project_name"] for c in candidates],
    })

    return len(candidates)