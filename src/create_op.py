import duckdb
from datetime import date
from audit import log
from delete_op import BULK_THRESHOLD


# ============ 单条新增 ============

def format_create_confirm(record: dict) -> str:
    lines = [
        "即将新增以下记录：",
        f"  项目名称：{record['project_name']}",
        f"  负责人：{record['owner']}",
        f"  分类：{record['category']}",
        f"  状态：{record['status_raw']}",
        f"  下发时间：{record['issued_date']}",
        "",
        "确认新增吗？回复「确认」执行，或「取消」放弃。",
    ]
    return "\n".join(lines)


def execute_create(record: dict, db_path: str, real_table: str,
                   trace_id: str, user_input: str) -> int:
    con = duckdb.connect(db_path)
    con.execute(f"""
        INSERT INTO {real_table} (
            project_name, owner, status_raw, issued_date, certified_date,
            category, resubmit_name, reject_date, resubmit_date, reject_count,
            is_pending, is_submitted, is_rejected, is_settled, is_certified,
            is_deleted, deleted_at, deleted_by, delete_trace_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        record["project_name"], record["owner"], record["status_raw"],
        record["issued_date"], record["certified_date"], record["category"],
        record["resubmit_name"], record["reject_date"], record["resubmit_date"],
        record["reject_count"],
        False, True, False, False, False,
        False, None, None, None,
    ])
    con.close()

    log("create", {
        "trace_id": trace_id,
        "user_input": user_input,
        "created_record": record,
    })

    return 1


# ============ 批量新增 ============

def format_batch_create_confirm(records: list) -> str:
    """批量新增的确认提示。"""
    n = len(records)
    if n <= BULK_THRESHOLD:
        lines = [f"即将新增 {n} 条记录：", ""]
        for i, r in enumerate(records, 1):
            lines.append(f"  {i}. {r['project_name']}（{r['owner']}，{r['category']}）")
        lines.append("")
        lines.append(f"确认新增这 {n} 条吗？回复「确认」执行，或「取消」放弃。")
        return "\n".join(lines)
    else:
        lines = [f"即将新增 {n} 条记录，以下是前 10 条：", ""]
        for i, r in enumerate(records[:10], 1):
            lines.append(f"  {i}. {r['project_name']}（{r['owner']}，{r['category']}）")
        lines.append(f"  ...（共 {n} 条）")
        lines.append("")
        lines.append("⚠️ 批量新增警告")
        lines.append(f"如确认，请输入「新增{n}条」；或回复「取消」放弃。")
        return "\n".join(lines)


def execute_batch_create(records: list, db_path: str, real_table: str,
                         trace_id: str, user_input: str) -> int:
    """批量新增。原子性：要么全成，要么全不成。"""
    con = duckdb.connect(db_path)
    try:
        con.execute("BEGIN TRANSACTION")
        for r in records:
            con.execute(f"""
                INSERT INTO {real_table} (
                    project_name, owner, status_raw, issued_date, certified_date,
                    category, resubmit_name, reject_date, resubmit_date, reject_count,
                    is_pending, is_submitted, is_rejected, is_settled, is_certified,
                    is_deleted, deleted_at, deleted_by, delete_trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                r["project_name"], r["owner"], r["status_raw"],
                r["issued_date"], r["certified_date"], r["category"],
                r["resubmit_name"], r["reject_date"], r["resubmit_date"],
                r["reject_count"],
                False, True, False, False, False,
                False, None, None, None,
            ])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        raise
    con.close()

    log("batch_create", {
        "trace_id": trace_id,
        "user_input": user_input,
        "affected_count": len(records),
        "created_records": [r["project_name"] for r in records],
    })

    return len(records)