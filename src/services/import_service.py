"""Excel 导入：扫差异 → 确认 → 写入。

**不认识业务字段。** 三件事都从表定义推：

| 靠什么 | 从哪来 |
|---|---|
| Excel 的列 → 表字段 | 表定义的中文名（没标就用字段名） |
| 判断"这条是新增还是更新" | 表上的**单列唯一约束** |
| 比哪些列 | Excel 里有、表里也存在的列 |

旧版把软著的 10 个中文列名、9 个比较列、以及"由状态文本派生五个布尔列"
全写在这里——那是**一张表的结构**，不是导入这件事本身。

## 匹配键为什么只能是唯一列

自增主键不行——Excel 里根本没有那一列。**没有唯一列就没法判断
"这条是新增还是更新"**，重复导入的判定需要一个依据。所以这种情况
明确报错，而不是硬猜（猜错的后果是把整批数据导重）。

## 三阶段确认保留

扫描 → 展示差异 → 用户确认口径（新增 / 冲突 / 已删除各自怎么处理）→ 执行。
追问详情也保留：用户可以问"冲突都有哪些"，系统把全量摊开。
"""

import json

import pandas as pd

import storage
from audit import log
from services import UserInputRequired, card_columns, card_records
from runner import query_df, transaction, using


def _match_key(table_name: str) -> str | None:
    """导入的匹配键：表上的**单列**唯一约束。"""
    uniq = using(storage.uniques_of, table_name + storage.SOFTDEL_SUFFIX)
    for cols in uniq:
        if len(cols) == 1:
            return cols[0]
    return None


def _map_columns(df: pd.DataFrame, ctx) -> tuple[pd.DataFrame, list[str]]:
    """Excel 的列名 → 表字段名。

    匹配顺序：字段的中文名 → 字段名本身。对不上的列**丢掉并报告**——
    悄悄丢列比整批失败好，但用户得知道少了什么。
    """
    keys, labels = card_columns(ctx)
    by_label = {lab: k for k, lab in zip(keys, labels)}
    by_key = {k: k for k in keys}

    mapping, dropped = {}, []
    for col in df.columns:
        name = str(col).strip()
        if name in by_label:
            mapping[col] = by_label[name]
        elif name in by_key:
            mapping[col] = name
        else:
            dropped.append(name)

    out = df[list(mapping)].rename(columns=mapping)
    out.columns = [str(c) for c in out.columns]
    return out, dropped


def _clean(v):
    """Excel 单元格 → 能写库的值。NaN / NaT 统一成 None。"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ") if hasattr(v, "hour") else v.isoformat()
    return v


def _row_to_dict(row) -> dict:
    return {str(k): _clean(v) for k, v in row.items()}


def scan(file_path: str, ctx) -> dict:
    """扫一遍差异。返回四种情况 + 被丢弃的列。"""
    key = _match_key(ctx.table_name)
    if not key:
        return {"error": "这张表没有单列唯一约束，导入无法判断哪条是重复的。"
                         "先在表定义里给一个唯一列（比如订单号）。"}

    raw = pd.read_excel(file_path)
    raw.columns = raw.columns.astype(str).str.strip()
    df, dropped = _map_columns(raw, ctx)

    if key not in df.columns:
        label = key
        return {"error": f"Excel 里必须有「{label}」这一列——导入靠它判断重复。"}

    df_db = query_df(f"SELECT * FROM {ctx.real_table}")
    db_by_key = {r[key]: r for _, r in df_db.iterrows()}
    excel_keys = set(df[key])
    db_keys = set(db_by_key)

    compare = [c for c in df.columns if c != key and c in df_db.columns]

    new_records, conflicts, unchanged, deleted_in_db = [], [], [], []

    for _, row in df.iterrows():
        k = row[key]
        if k not in db_by_key:
            new_records.append(_row_to_dict(row))
            continue

        db_row = db_by_key[k]
        if db_row.get("is_deleted"):
            deleted_in_db.append({
                "key": str(k),
                "excel_data": _row_to_dict(row),
                "db_data": _row_to_dict(db_row),
            })
            continue

        changes = {}
        for field in compare:
            excel_val, db_val = _clean(row.get(field)), _clean(db_row.get(field))
            if str(excel_val) != str(db_val):
                changes[field] = {"db": db_val, "excel": excel_val}

        if changes:
            conflicts.append({
                "key": str(k), "changes": changes, "excel_data": _row_to_dict(row),
            })
        else:
            unchanged.append(str(k))

    missing = [
        {"key": str(k), "data": _row_to_dict(db_by_key[k])}
        for k in (db_keys - excel_keys)
        if not db_by_key[k].get("is_deleted")
    ]

    return {
        "key_column": key,
        "dropped_columns": dropped,
        "compared_columns": compare,
        "new_records": new_records,
        "deleted_in_db": deleted_in_db,
        "conflicts": conflicts,
        "unchanged": unchanged,
        "missing_from_excel": missing,
    }


def request_import(file_path: str, ctx) -> str:
    result = scan(file_path, ctx)
    if result.get("error"):
        return json.dumps(
            {"ok": False, "error": result["error"], "error_type": "invalid"},
            ensure_ascii=False,
        )

    has_diff = bool(
        result["new_records"] or result["deleted_in_db"] or result["conflicts"]
    )
    if not has_diff:
        return json.dumps({
            "ok": True, "status": "no_change",
            "message": f"扫描完成，{len(result['unchanged'])} 条无变化，无需导入。",
            "dropped_columns": result["dropped_columns"],
        }, ensure_ascii=False)

    # 卡片：四类差异各一行，用户一眼看清各有多少
    rows = [
        ["新增", len(result["new_records"]), "文件里有、库里没有"],
        ["字段冲突", len(result["conflicts"]), "同一个键，字段对不上"],
        ["已删除待恢复", len(result["deleted_in_db"]), "库里是删除态、文件里又出现"],
        ["文件缺失", len(result["missing_from_excel"]), "库里有、文件里没有（不影响）"],
    ]

    raise UserInputRequired(
        question="导入需要用户确认",
        pending_action={
            "type": "import",
            "stage": "awaiting",
            "table": ctx.table_name,
            "columns": ["类别", "条数", "说明"],
            "records": rows,
            "affected": len(result["new_records"]),
            "danger": False,
            # —— 内部字段 ——
            "table_name": ctx.table_name,
            "real_table": ctx.real_table,
            "scan_result": result,
            "file_path": file_path,
            "user_input": ctx.trace.data["question"],
            "trace_id": ctx.trace.id,
        },
    )


def format_detail(scan_result: dict, detail_type: str) -> str:
    """把某一类差异全量摊开。给"追问详情"用。"""
    key = scan_result.get("key_column", "键")
    if detail_type == "conflicts":
        items = scan_result["conflicts"]
        lines = [f"**全部冲突（共 {len(items)} 条）**", ""]
        for c in items:
            lines.append(f"- `{c['key']}`")
            for field, d in c["changes"].items():
                lines.append(f"    {field}：库内 `{d['db']}` → Excel `{d['excel']}`")
        return "\n".join(lines)

    if detail_type == "new":
        items = scan_result["new_records"]
        cols = scan_result.get("compared_columns", [])[:3]
        lines = [f"**全部新记录（共 {len(items)} 条）**", ""]
        for r in items:
            preview = "，".join(f"{c}={r.get(c)}" for c in cols)
            lines.append(f"- `{r.get(key, '')}`  {preview}")
        return "\n".join(lines)

    if detail_type == "deleted":
        items = scan_result["deleted_in_db"]
        return "\n".join(
            [f"**全部已删除（共 {len(items)} 条）**", ""]
            + [f"- `{d['key']}`" for d in items]
        )

    items = scan_result["missing_from_excel"]
    return "\n".join(
        [f"**库里有、Excel 没有（共 {len(items)} 条）**", ""]
        + [f"- `{m['key']}`" for m in items]
    )


def parse_user_answer(user_input: str, scan_result: dict, llm) -> dict:
    """把用户的确认话解析成口径。"""
    key = scan_result.get("key_column", "键")
    context = {
        "键列": key,
        "新记录": [r.get(key) for r in scan_result["new_records"]][:30],
        "数据库有但Excel没有": [r["key"] for r in scan_result["missing_from_excel"]][:30],
        "已删除记录": [r["key"] for r in scan_result["deleted_in_db"]][:30],
        "冲突记录": [r["key"] for r in scan_result["conflicts"]][:30],
    }

    prompt = f"""用户正在回答导入确认问题。请解析用户输入，返回 JSON。

当前导入扫描结果：
{json.dumps(context, ensure_ascii=False, indent=2)}

用户的回答：{user_input}

请判断用户是"追问详情"还是"做出决策"，返回以下 JSON 之一：

追问详情：
{{"action": "show_detail", "detail_type": "conflicts"}}
detail_type 取值：conflicts / new / deleted / missing

做出决策：
{{"action": "submit", "rename_map": {{"旧键值": "新键值"}},
  "deleted_action": "keep", "conflict_action": "excel"}}
- deleted_action："keep"（保持删除）或 "restore"（重新导入）
- conflict_action："excel"（以 Excel 为准）或 "db"（不更新）

取消：
{{"action": "cancel"}}

只返回 JSON，不要其他内容。"""

    raw = llm.chat("你是一个解析助手", prompt).strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```")).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"action": "unknown"}


def _write_rows(con, table_name: str, rows: list[dict]) -> None:
    """按每行自己的键集合生成 INSERT——列不写死。"""
    for r in rows:
        cols = [c for c in r if r[c] is not None]
        if not cols:
            continue
        sql = (
            f"INSERT INTO {storage.quote(table_name)} "
            f"({', '.join(storage.quote(c) for c in cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})"
        )
        con.execute(sql, [r[c] for c in cols])


def _update_row(con, table_name: str, key: str, key_value, data: dict) -> None:
    """按匹配键更新——SET 的列按 data 的键动态生成。"""
    cols = [c for c in data if c != key and data[c] is not None]
    if not cols:
        return
    sets = ", ".join(f"{storage.quote(c)} = ?" for c in cols)
    con.execute(
        f"UPDATE {storage.quote(table_name)} SET {sets} "
        f"WHERE {storage.quote(key)} = ?",
        [data[c] for c in cols] + [key_value],
    )


def execute_import(scan_result, rename_map, deleted_action, conflict_action,
                   table_name, trace_id, user_input):
    """执行导入。整批一个事务——要么全进，要么全不进。"""
    key = scan_result["key_column"]
    rename_map = rename_map or {}

    def _rename(record):
        k = record.get(key)
        if k in rename_map:
            record = dict(record)
            record[key] = rename_map[k]
        return record

    inserted = updated = restored = 0
    with transaction() as tx:
        for r in scan_result["new_records"]:
            _write_rows(tx, table_name, [_rename(r)])
            inserted += 1

        for c in scan_result["conflicts"]:
            if conflict_action == "excel":
                _update_row(tx, table_name, key, c["key"], c["excel_data"])
                updated += 1

        if deleted_action == "restore":
            for d in scan_result["deleted_in_db"]:
                tx.execute(
                    f"UPDATE {storage.quote(table_name + storage.SOFTDEL_SUFFIX)} "
                    f"SET is_deleted = 0, deleted_at = NULL "
                    f"WHERE {storage.quote(key)} = ?",
                    [d["key"]],
                )
                restored += 1

    log("import", {
        "trace_id": trace_id, "user_input": user_input, "table": table_name,
        "inserted": inserted, "updated": updated, "restored": restored,
    })
    return json.dumps({
        "ok": True, "table": table_name,
        "inserted": inserted, "updated": updated, "restored": restored,
        "affected": inserted + updated + restored,
    }, ensure_ascii=False)
