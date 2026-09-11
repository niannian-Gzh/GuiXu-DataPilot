import duckdb
from datetime import date
from audit import log


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


def execute_create(record: dict, db_path: str, real_table: str, trace_id: str, user_input: str) -> int:
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
        False, True, False, False, False,   # is_pending=false, is_submitted=true, ...
        False, None, None, None,             # is_deleted, deleted_at, deleted_by, delete_trace_id
    ])
    con.close()

    log("create", {
        "trace_id": trace_id,
        "user_input": user_input,
        "created_record": record,
    })

    return 1