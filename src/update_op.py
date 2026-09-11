import duckdb
from audit import log


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


def format_update_confirm(record: dict, updates: dict) -> str:
    """生成更新确认提示，展示改前改后对比。"""
    lines = ["即将修改以下记录：", ""]
    lines.append(f"  项目名称：{record['project_name']}")
    lines.append("")
    lines.append("  修改内容：")
    for field, new_value in updates.items():
        if field in ("is_pending", "is_submitted", "is_rejected", "is_settled", "is_certified"):
            continue  # 联动字段不单独展示
        old_value = record.get(field, "（空）")
        lines.append(f"    {field}: {old_value} → {new_value}")
    lines.append("")
    lines.append("确认修改吗？回复「确认」执行，或「取消」放弃。")
    return "\n".join(lines)


def execute_update(record: dict, updates: dict, db_path: str, real_table: str,
                   trace_id: str, user_input: str) -> int:
    """执行更新。"""
    # 状态联动：如果改了 status_raw，重算五个布尔字段
    if "status_raw" in updates:
        updates = dict(updates)  # 复制，避免改到 pending 里的
        updates.update(recompute_status_flags(updates["status_raw"]))

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [record["project_name"]]

    con = duckdb.connect(db_path)
    con.execute(
        f"UPDATE {real_table} SET {set_clause} "
        f"WHERE project_name = ? AND is_deleted = false",
        values,
    )
    con.close()

    log("update", {
        "trace_id": trace_id,
        "user_input": user_input,
        "target_record": record["project_name"],
        "changes": updates,
    })

    return 1