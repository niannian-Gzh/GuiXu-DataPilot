import json
import pandas as pd
from services import UserInputRequired
from display import format_table
from audit import log
from config import setting
from db import query_df, transaction



COLUMN_MAP = {
    "项目名称": "project_name",
    "负责人": "owner",
    "状态": "status_raw",
    "项目下发时间": "issued_date",
    "项目下证时间": "certified_date",
    "分类": "category",
    "重提项目名": "resubmit_name",
    "（最新）打回时间": "reject_date",
    "（打回）提交时间": "resubmit_date",
    "打回次数": "reject_count",
}

COMPARE_FIELDS = [
    "owner", "status_raw", "issued_date", "certified_date",
    "category", "resubmit_name", "reject_date", "resubmit_date",
    "reject_count",
]


def _normalize_excel(file_path: str) -> pd.DataFrame:
    df = pd.read_excel(file_path)
    df.columns = df.columns.str.strip()
    df = df[list(COLUMN_MAP.keys())].rename(columns=COLUMN_MAP)

    df["project_name"] = (
        df["project_name"].astype(str)
        .str.replace("<br>", "", regex=False)
        .str.strip()
    )

    df["is_pending"] = df["status_raw"].str.contains("待提交", na=False)
    df["is_submitted"] = df["status_raw"].str.contains("已提交", na=False)
    df["is_rejected"] = df["status_raw"].str.contains("已打回", na=False)
    df["is_settled"] = df["status_raw"].str.contains("已结算", na=False)
    df["is_certified"] = df["status_raw"].str.contains("已下证", na=False)

    df["reject_count"] = df["reject_count"].fillna(0).astype(int)

    def _clean_date(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        s = str(v).strip()
        if not s or s.lower() in ("nan", "nat", "none"):
            return None
        return s[:10]

    for col in ["issued_date", "certified_date", "reject_date", "resubmit_date"]:
        df[col] = df[col].apply(_clean_date).astype(object)

    return df


def _db_value(v):
    if pd.isna(v) or v is None:
        return None
    return str(v)[:10] if hasattr(v, "year") else str(v)


def scan(file_path: str, ctx) -> dict:
    df_excel = _normalize_excel(file_path)

    df_db = query_df(f"SELECT * FROM {ctx.real_table}")

    db_by_name = {row["project_name"]: row for _, row in df_db.iterrows()}
    excel_names = set(df_excel["project_name"])
    db_names = set(db_by_name.keys())

    new_records = []
    conflicts = []
    unchanged = []
    deleted_in_db = []

    for _, excel_row in df_excel.iterrows():
        name = excel_row["project_name"]
        if name not in db_by_name:
            new_records.append(_row_to_dict(excel_row))
            continue

        db_row = db_by_name[name]

        if db_row.get("is_deleted"):
            deleted_in_db.append({
                "project_name": name,
                "excel_data": _row_to_dict(excel_row),
                "db_data": _row_to_dict(db_row),
            })
            continue

        changes = {}
        for field in COMPARE_FIELDS:
            excel_val = _db_value(excel_row.get(field))
            db_val = _db_value(db_row.get(field))
            if excel_val != db_val:
                changes[field] = {"db": db_val, "excel": excel_val}

        if changes:
            conflicts.append({
                "project_name": name,
                "changes": changes,
                "excel_data": _row_to_dict(excel_row),
            })
        else:
            unchanged.append(name)

    missing_from_excel = [
        {"project_name": n, "owner": db_by_name[n].get("owner")}
        for n in (db_names - excel_names)
        if not db_by_name[n].get("is_deleted")
    ]

    return {
        "new_records": new_records,
        "deleted_in_db": deleted_in_db,
        "conflicts": conflicts,
        "unchanged": unchanged,
        "missing_from_excel": missing_from_excel,
    }


def request_import(file_path: str, ctx) -> str:
    result = scan(file_path, ctx)

    has_diff = bool(result["new_records"] or result["deleted_in_db"] or result["conflicts"])
    if not has_diff:
        return json.dumps({
            "status": "no_change",
            "message": f"扫描完成，共 {len(result['unchanged'])} 条记录无变化，无需导入。",
        }, ensure_ascii=False)

    pending = {
        "type": "import",
        "stage": "awaiting",
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "scan_result": result,
        "file_path": file_path,
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question="导入需要用户确认",
        pending_action=pending,
    )


def format_import_summary(scan_result: dict) -> str:
    parts = ["扫描完成，发现以下需要确认的情况：\n"]
    idx = 1

    new_records = scan_result["new_records"]
    if new_records:
        shown = new_records[:setting("display.conflict_sample_count")]
        rows = [{"项目名称": r["project_name"], "负责人": r["owner"], "分类": r["category"]} for r in shown]
        parts.append(f"## {idx}. 新记录 {len(new_records)} 条\n")
        parts.append(format_table(rows))
        if len(new_records) > setting("display.conflict_sample_count"):
            parts.append(f"\n（共 {len(new_records)} 条，此处仅显示前 {setting("display.conflict_sample_count")} 条）")
        parts.append("")
        idx += 1

    deleted = scan_result["deleted_in_db"]
    if deleted:
        shown = deleted[:setting("display.conflict_sample_count")]
        rows = [{"项目名称": r["project_name"]} for r in shown]
        parts.append(f"## {idx}. 已删除记录 {len(deleted)} 条（数据库中为软删除状态）\n")
        parts.append(format_table(rows))
        if len(deleted) > setting("display.conflict_sample_count"):
            parts.append(f"\n（共 {len(deleted)} 条）")
        parts.append("")
        idx += 1

    conflicts = scan_result["conflicts"]
    if conflicts:
        shown = conflicts[:setting("display.conflict_sample_count")]
        rows = []
        for c in shown:
            for field, change in c["changes"].items():
                rows.append({
                    "项目名称": c["project_name"],
                    "字段": field,
                    "数据库当前值": change["db"] or "（空）",
                    "Excel值": change["excel"] or "（空）",
                })
        parts.append(f"## {idx}. 字段冲突 {len(conflicts)} 条\n")
        parts.append(format_table(rows))
        if len(conflicts) > setting("display.conflict_sample_count"):
            parts.append(f"\n（共 {len(conflicts)} 条，此处仅显示前 {setting("display.conflict_sample_count")} 条的字段变化）")
        parts.append("")

    missing = scan_result["missing_from_excel"]
    if missing and new_records:
        shown = missing[:setting("display.conflict_sample_count")]
        rows = [{"项目名称": r["project_name"]} for r in shown]
        parts.append(f"## 数据库中以下 {len(missing)} 条记录未出现在 Excel 中\n")
        parts.append("（如果其中有改名，请一并指出）\n")
        parts.append(format_table(rows))
        if len(missing) > setting("display.conflict_sample_count"):
            parts.append(f"\n（共 {len(missing)} 条）")
        parts.append("")

    parts.append("---\n")
    parts.append("请回答：\n")
    q_idx = 1
    if new_records:
        parts.append(f"{q_idx}. 新记录中有没有改名？（格式：旧名 → 新名，或回复\"都是新的\"）")
        q_idx += 1
    if deleted:
        parts.append(f"{q_idx}. 已删除的 {len(deleted)} 条怎么处理？（\"保持删除\" 或 \"重新导入\"）")
        q_idx += 1
    if conflicts:
        parts.append(f"{q_idx}. 冲突的 {len(conflicts)} 条以谁为准？（\"以Excel为准\" 或 \"不更新\"）")

    return "\n".join(parts)


def format_detail(scan_result: dict, detail_type: str) -> str:
    if detail_type == "conflicts":
        conflicts = scan_result["conflicts"]
        if not conflicts:
            return "没有冲突记录。"
        rows = []
        for c in conflicts:
            for field, change in c["changes"].items():
                rows.append({
                    "项目名称": c["project_name"],
                    "字段": field,
                    "数据库当前值": change["db"] or "（空）",
                    "Excel值": change["excel"] or "（空）",
                })
        return f"**全部冲突记录（共 {len(conflicts)} 条）：**\n\n" + format_table(rows)

    if detail_type == "new":
        records = scan_result["new_records"]
        if not records:
            return "没有新记录。"
        rows = [{"项目名称": r["project_name"], "负责人": r["owner"], "分类": r["category"]} for r in records]
        return f"**全部新记录（共 {len(records)} 条）：**\n\n" + format_table(rows)

    if detail_type == "deleted":
        records = scan_result["deleted_in_db"]
        if not records:
            return "没有已删除记录。"
        rows = [{"项目名称": r["project_name"]} for r in records]
        return f"**全部已删除记录（共 {len(records)} 条）：**\n\n" + format_table(rows)

    if detail_type == "missing":
        records = scan_result["missing_from_excel"]
        if not records:
            return "没有缺失记录。"
        rows = [{"项目名称": r["project_name"]} for r in records]
        return f"**数据库中存在但 Excel 中没有的记录（共 {len(records)} 条）：**\n\n" + format_table(rows)

    return "未识别的查询类型。"


def parse_user_answer(user_input: str, scan_result: dict, llm) -> dict:
    new_records = scan_result["new_records"]
    deleted = scan_result["deleted_in_db"]
    conflicts = scan_result["conflicts"]
    missing = scan_result["missing_from_excel"]

    context = {
        "新记录": [r["project_name"] for r in new_records][:30],
        "数据库有但Excel没有": [r["project_name"] for r in missing][:30],
        "已删除记录": [r["project_name"] for r in deleted][:30],
        "冲突记录": [r["project_name"] for r in conflicts][:30],
        "是否有新记录": bool(new_records),
        "是否有已删除": bool(deleted),
        "是否有冲突": bool(conflicts),
    }

    prompt = f"""用户正在回答导入确认问题。请解析用户输入，返回 JSON。

当前导入扫描结果：
{json.dumps(context, ensure_ascii=False, indent=2)}

用户的回答：{user_input}

请判断用户是"追问详情"还是"做出决策"，返回以下 JSON 之一：

追问详情：
{{"action": "show_detail", "detail_type": "conflicts"}}
detail_type 取值：conflicts（全部冲突）/ new（全部新记录）/ deleted（全部已删除）/ missing（数据库有Excel没有）

做出决策：
{{"action": "submit", "rename_map": {{"旧名": "新名"}}, "deleted_action": "keep", "conflict_action": "excel"}}
- rename_map：改名映射，没有改名时为空对象 {{}}
- deleted_action："keep"（保持删除）或 "restore"（重新导入）
- conflict_action："excel"（以Excel为准）或 "db"（不更新）

取消：
{{"action": "cancel"}}

只返回 JSON，不要其他内容。"""

    raw = llm.chat("你是一个解析助手", prompt).strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"action": "unknown"}


def _update_all_fields(con, real_table, name, data):
    con.execute(f"""
        UPDATE {real_table} SET
            owner = ?, status_raw = ?, issued_date = ?,
            certified_date = ?, category = ?,
            resubmit_name = ?, reject_date = ?, resubmit_date = ?,
            reject_count = ?,
            is_pending = ?, is_submitted = ?, is_rejected = ?,
            is_settled = ?, is_certified = ?
        WHERE project_name = ?
    """, [
        data["owner"], data["status_raw"], data["issued_date"],
        data["certified_date"], data["category"],
        data["resubmit_name"], data["reject_date"], data["resubmit_date"],
        data["reject_count"],
        data["is_pending"], data["is_submitted"], data["is_rejected"],
        data["is_settled"], data["is_certified"],
        name,
    ])


def _row_to_dict(row) -> dict:
    """把 Series 转成 dict，NaN / NaT 统一转 None。"""
    result = {}
    for k, v in row.items():
        if v is None:
            result[k] = None
            continue
        try:
            if pd.isna(v):
                result[k] = None
                continue
        except (TypeError, ValueError):
            pass
        result[k] = v
    return result


def execute_import(scan_result, rename_map, deleted_action, conflict_action,
                   db_path, real_table, trace_id, user_input):
    stats = {"renamed": 0, "restored": 0, "inserted": 0, "updated": 0}

    with transaction() as tx:
        # 1. 改名
        for old_name, new_name in rename_map.items():
            tx.execute(
                f"UPDATE {real_table} SET project_name = ? WHERE project_name = ?",
                [new_name, old_name],
            )
            stats["renamed"] += 1

        # 2. 恢复软删除
        if deleted_action == "restore":
            for rec in scan_result["deleted_in_db"]:
                tx.execute(f"""
                    UPDATE {real_table} SET
                        is_deleted = false, deleted_at = NULL,
                        deleted_by = NULL, delete_trace_id = NULL
                    WHERE project_name = ?
                """, [rec["project_name"]])
                _update_all_fields(tx, real_table, rec["project_name"], rec["excel_data"])
                stats["restored"] += 1

        # 3. 新增
        rename_targets = set(rename_map.values())
        for rec in scan_result["new_records"]:
            if rec["project_name"] in rename_targets:
                continue

            tx.execute(f"""
                INSERT INTO {real_table} (
                    project_name, owner, status_raw, issued_date, certified_date,
                    category, resubmit_name, reject_date, resubmit_date, reject_count,
                    is_pending, is_submitted, is_rejected, is_settled, is_certified,
                    is_deleted, deleted_at, deleted_by, delete_trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                rec["project_name"], rec["owner"], rec["status_raw"],
                rec["issued_date"], rec["certified_date"], rec["category"],
                rec["resubmit_name"], rec["reject_date"], rec["resubmit_date"],
                rec["reject_count"],
                rec["is_pending"], rec["is_submitted"], rec["is_rejected"],
                rec["is_settled"], rec["is_certified"],
                False, None, None, None,
            ])
            stats["inserted"] += 1

        # 4. 冲突
        if conflict_action == "excel":
            for rec in scan_result["conflicts"]:
                _update_all_fields(tx, real_table, rec["project_name"], rec["excel_data"])
                stats["updated"] += 1

    log("import", {
        "trace_id": trace_id,
        "user_input": user_input,
        "stats": stats,
    })
    return stats