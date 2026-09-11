import re
import duckdb
from audit import log


BULK_THRESHOLD = 20
SAMPLE_COUNT = 10

CONFIRM_WORDS = {"确认", "确定", "是", "对", "好", "可以", "删", "删除", "删吧", "yes", "y", "ok"}
CANCEL_WORDS = {"取消", "不", "不要", "算了", "放弃", "no", "n", "cancel"}


def find_candidates(keyword: str, db_path: str, real_table: str) -> list:
    """模糊匹配 project_name。keyword 为空则匹配全部未删除记录。"""
    con = duckdb.connect(db_path)
    if keyword:
        rows = con.execute(
            f"SELECT project_name, owner, status_raw FROM {real_table} "
            f"WHERE is_deleted = false AND project_name LIKE ?",
            [f"%{keyword}%"],
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT project_name, owner, status_raw FROM {real_table} "
            f"WHERE is_deleted = false"
        ).fetchall()
    con.close()
    return [{"project_name": r[0], "owner": r[1], "status_raw": r[2]} for r in rows]


def format_candidates(candidates: list) -> str:
    """格式化候选列表。≤20 条列全部，>20 条列前 10 条 + 总数。"""
    n = len(candidates)
    if n <= BULK_THRESHOLD:
        lines = [f"找到 {n} 条匹配："]
        for i, c in enumerate(candidates, 1):
            lines.append(f"  {i}. {c['project_name']}（{c['owner']}，{c['status_raw']}）")
        return "\n".join(lines)
    else:
        lines = [f"找到 {n} 条匹配，以下是前 {SAMPLE_COUNT} 条："]
        for i, c in enumerate(candidates[:SAMPLE_COUNT], 1):
            lines.append(f"  {i}. {c['project_name']}（{c['owner']}，{c['status_raw']}）")
        lines.append(f"  ...（共 {n} 条）")
        return "\n".join(lines)


def delete_confirm_prompt(candidates: list) -> str:
    """生成第二轮删除确认的提示。"""
    n = len(candidates)
    if n <= BULK_THRESHOLD:
        return (
            f"确认删除这 {n} 条吗？\n"
            f"删除后 7 天内可恢复，之后永久清理。\n"
            f"回复「确认」执行删除，或回复「取消」放弃。"
        )
    else:
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
    """检查用户是否输入了正确的批量确认（必须包含正确数字）。"""
    nums = re.findall(r"\d+", text)
    return str(expected_count) in nums


def execute_delete(
    candidates: list, db_path: str, real_table: str, trace_id: str, user_input: str
) -> int:
    """执行软删除。返回删除条数。"""
    names = [c["project_name"] for c in candidates]

    con = duckdb.connect(db_path)
    placeholders = ",".join(["?"] * len(names))
    con.execute(
        f"UPDATE {real_table} "
        f"SET is_deleted = true, "
        f"    deleted_at = CAST(NOW() AS TIMESTAMP), "
        f"    delete_trace_id = ?, "
        f"    deleted_by = 'local_user' "
        f"WHERE project_name IN ({placeholders})",
        [trace_id] + names,
    )
    con.close()

    log("soft_delete", {
        "trace_id": trace_id,
        "user_input": user_input,
        "affected_count": len(candidates),
        "affected_records": [
            {"project_name": c["project_name"], "owner": c["owner"]}
            for c in candidates
        ],
    })

    return len(candidates)