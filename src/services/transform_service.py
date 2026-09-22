import json
from db import query_df, transaction
from nl2sql import generate_transform_sql
from guard import check_transform_safety
from audit import log
from display import format_table
from services import UserInputRequired
from config import setting


PREVIEW_LIMIT = 20      # 表格里最多展示多少行
PREVIEW_SAMPLE = 10     # 超过 PREVIEW_LIMIT 时，只展示前 N 行


def _short_label(label: str, max_len: int = 12) -> str:
    """把完整说明压成短标签。

    说明文本是给 LLM 的——"被打回的次数，整数"、"是否已下证（布尔）..."
    表格里要短——"被打回的次数"、"是否已下证"。

    截断位置：所有分隔符里出现最早的那个。
    如果直接按固定顺序遍历，会漏掉"（"比"，"更靠前的情况。
    """
    if not label:
        return ""

    separators = ("，", ",", "。", "（", "(", "：", ":")
    positions = [label.find(s) for s in separators if label.find(s) > 0]
    if positions:
        label = label[:min(positions)]

    if len(label) > max_len:
        label = label[:max_len]
    return label

def _label_for_column(col: str, table_name: str) -> str:
    """列名 → 表格里的短标签。"""
    from schema_store import get_field_label

    if col.endswith("_before"):
        return f"{_short_label(get_field_label(table_name, col[:-7]))}（改前）"
    if col.endswith("_after"):
        return f"{_short_label(get_field_label(table_name, col[:-6]))}（改后）"
    return _short_label(get_field_label(table_name, col))

def request_transform(description: str, ctx) -> str:
    """用户描述一个变换规则。

    流程：
      1. 生成两段 SQL（UPDATE + 预览 SELECT）
      2. 安全检查 UPDATE
      3. 执行预览 SELECT —— 看会改哪些行
      4. 空结果 → not_found
      5. 抛 UserInputRequired，等用户确认
    """
    try:
        update_sql, preview_sql = generate_transform_sql(
            description, ctx.llm, ctx.schema, ctx.table_name
        )
    except Exception as e:
        return json.dumps(
            {"error": f"生成变换 SQL 失败：{e}"},
            ensure_ascii=False,
        )

    # 安全检查——不允许非 UPDATE、不带 WHERE、改系统字段
    ok, reason = check_transform_safety(update_sql)
    if not ok:
        return json.dumps(
            {"error": f"变换被拒绝：{reason}", "is_security": True},
            ensure_ascii=False,
        )

    # 预览——会改哪些行
    try:
        preview_df = query_df(preview_sql, timeout=setting("safety.query_timeout"))
    except Exception as e:
        return json.dumps(
            {"error": f"预览失败：{e}"},
            ensure_ascii=False,
        )

    if len(preview_df) == 0:
        return json.dumps(
            {"status": "no_match", "message": "没有匹配的记录，未做任何修改"},
            ensure_ascii=False,
        )

    limit = PREVIEW_LIMIT
    records = preview_df.head(limit).to_dict("records")

    pending = {
        "type": "transform",
        "stage": "confirm",
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "update_sql": update_sql,
        "preview_sql": preview_sql,
        "columns": list(preview_df.columns),
        "rows": records,
        "total": len(preview_df),
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"将修改 {len(preview_df)} 条记录，等待用户确认",
        pending_action=pending,
    )


def format_transform_confirm(pending: dict, table_name: str) -> str:
    """渲染确认卡片：预览表格 + 待执行的 SQL + 提示。"""
    total = pending["total"]
    cols = pending["columns"]
    rows = pending["rows"]

    # 列名 → 中文
    headers = {c: _label_for_column(c, table_name) for c in cols}
    table_rows = [
        {headers[c]: r.get(c, "") for c in cols}
        for r in rows
    ]

    lines = [f"即将执行数据变换，影响 **{total}** 条记录。\n"]
    lines.append(format_table(table_rows))
    if total > len(rows):
        lines.append(f"\n（共 {total} 条，此处仅显示前 {len(rows)} 条）")

    lines.append("")
    lines.append("**将执行的 SQL：**\n")
    lines.append("```sql")
    lines.append(pending["update_sql"])
    lines.append("```")
    lines.append("")
    lines.append("确认执行吗？回复「确认」执行，或「取消」放弃。")

    return "\n".join(lines)

def execute_transform(pending: dict, db_path: str, table_name: str,
                     trace_id: str, user_input: str) -> int:
    """执行变换。事务包裹，失败自动回滚。

    影响行数用 pending["total"]——那是预览 SELECT 的行数，
    和 UPDATE 的 WHERE 条件一致，等于真实受影响行数。
    """
    update_sql = pending["update_sql"]
    count = pending["total"]

    with transaction() as tx:
        tx.execute(update_sql)

    log("transform", {
        "trace_id": trace_id,
        "user_input": user_input,
        "update_sql": update_sql,
        "affected_count": count,
    })
    return count