import json
import duckdb
from datetime import date
from services import UserInputRequired, BULK_THRESHOLD
from audit import log


def _validate_record(record):
    """校验单条记录。返回错误列表。"""
    errors = []
    if not record.get("project_name"):
        errors.append("缺少项目名")
    if not record.get("owner"):
        errors.append("缺少负责人")
    if record.get("category") not in ("web", "嵌入式"):
        errors.append(f"分类必须是 web 或 嵌入式，收到：{record.get('category')}")
    return errors


def request_create(project_name, owner, category, status_raw, issued_date, ctx):
    errors = _validate_record({
        "project_name": project_name, "owner": owner, "category": category,
    })
    if errors:
        return json.dumps({"error": "；".join(errors)}, ensure_ascii=False)

    con = duckdb.connect(ctx.db_path)
    exists = con.execute(
        f"SELECT COUNT(*) FROM {ctx.real_table} "
        f"WHERE project_name = ? AND is_deleted = false",
        [project_name],
    ).fetchone()[0]
    con.close()
    if exists > 0:
        return json.dumps(
            {"error": f"项目「{project_name}」已存在，不能重复新增"},
            ensure_ascii=False,
        )

    record = {
        "project_name": project_name, "owner": owner, "category": category,
        "status_raw": status_raw, "issued_date": issued_date or date.today().isoformat(),
        "certified_date": None, "resubmit_name": None, "reject_date": None,
        "resubmit_date": None, "reject_count": 0,
    }
    pending = {
        "type": "create", "stage": "confirm", "record": record,
        "user_input": ctx.trace.data["question"], "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"等待用户确认新增项目「{project_name}」",
        pending_action=pending,
    )


def request_batch_create(records: list, ctx):
    if not records:
        return json.dumps({"error": "records 不能为空"}, ensure_ascii=False)

    errors = []
    for i, r in enumerate(records, 1):
        errs = _validate_record(r)
        for e in errs:
            errors.append(f"第{i}条：{e}")
    if errors:
        return json.dumps({"error": "；".join(errors)}, ensure_ascii=False)

    names = [r["project_name"] for r in records]
    if len(names) != len(set(names)):
        return json.dumps(
            {"error": "本次新增的记录中存在重复的项目名"},
            ensure_ascii=False,
        )

    con = duckdb.connect(ctx.db_path)
    placeholders = ",".join(["?"] * len(names))
    existing = con.execute(
        f"SELECT project_name FROM {ctx.real_table} "
        f"WHERE project_name IN ({placeholders}) AND is_deleted = false",
        names,
    ).fetchall()
    con.close()
    if existing:
        return json.dumps(
            {"error": f"以下项目已存在：{[e[0] for e in existing]}"},
            ensure_ascii=False,
        )

    full_records = [{
        "project_name": r["project_name"], "owner": r["owner"], "category": r["category"],
        "status_raw": r.get("status_raw", "已提交"),
        "issued_date": r.get("issued_date") or date.today().isoformat(),
        "certified_date": None, "resubmit_name": None, "reject_date": None,
        "resubmit_date": None, "reject_count": 0,
    } for r in records]

    pending = {
        "type": "batch_create", "stage": "confirm", "records": full_records,
        "user_input": ctx.trace.data["question"], "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"待新增 {len(records)} 条，等待用户确认",
        pending_action=pending,
    )


def format_create_confirm(record: dict) -> str:
    return "\n".join([
        "即将新增以下记录：",
        f"  项目名称：{record['project_name']}",
        f"  负责人：{record['owner']}",
        f"  分类：{record['category']}",
        f"  状态：{record['status_raw']}",
        f"  下发时间：{record['issued_date']}",
        "",
        "确认新增吗？回复「确认」执行，或「取消」放弃。",
    ])


def format_batch_create_confirm(records: list) -> str:
    n = len(records)
    if n <= BULK_THRESHOLD:
        lines = [f"即将新增 {n} 条记录：", ""]
        for i, r in enumerate(records, 1):
            lines.append(f"  {i}. {r['project_name']}（{r['owner']}，{r['category']}）")
        lines.append("")
        lines.append(f"确认新增这 {n} 条吗？回复「确认」执行，或「取消」放弃。")
        return "\n".join(lines)
    lines = [f"即将新增 {n} 条记录，以下是前 10 条：", ""]
    for i, r in enumerate(records[:10], 1):
        lines.append(f"  {i}. {r['project_name']}（{r['owner']}，{r['category']}）")
    lines.append(f"  ...（共 {n} 条）")
    lines.append("")
    lines.append("⚠️ 批量新增警告")
    lines.append(f"如确认，请输入「新增{n}条」；或回复「取消」放弃。")
    return "\n".join(lines)


def _insert_one(con, real_table, r):
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


def execute_create(record, db_path, real_table, trace_id, user_input):
    con = duckdb.connect(db_path)
    _insert_one(con, real_table, record)
    con.close()
    log("create", {
        "trace_id": trace_id, "user_input": user_input, "created_record": record,
    })
    return 1


def execute_batch_create(records, db_path, real_table, trace_id, user_input):
    con = duckdb.connect(db_path)
    try:
        con.execute("BEGIN TRANSACTION")
        for r in records:
            _insert_one(con, real_table, r)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        con.close()
        raise
    con.close()
    log("batch_create", {
        "trace_id": trace_id, "user_input": user_input,
        "affected_count": len(records),
        "created_records": [r["project_name"] for r in records],
    })
    return len(records)