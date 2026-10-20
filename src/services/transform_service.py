import json
from runner import query_df, transaction
from nl2sql import generate_transform_sql
from guard import check_transform_safety
from audit import log
from services import UserInputRequired, jsonable
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
            {"ok": False, "error": f"生成变换 SQL 失败：{e}", "error_type": "unknown"},
            ensure_ascii=False,
        )

    # 安全检查——不允许非 UPDATE、不带 WHERE、改系统字段
    ok, reason, is_full_table = check_transform_safety(update_sql)
    if not ok:
        return json.dumps(
            {"ok": False, "error": f"变换被拒绝：{reason}", "error_type": "security"},
            ensure_ascii=False,
        )

    # 预览——会改哪些行
    try:
        preview_df = query_df(preview_sql, timeout=setting("safety.query_timeout"))
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": f"预览失败：{e}", "error_type": "unknown"},
            ensure_ascii=False,
        )

    if len(preview_df) == 0:
        return json.dumps(
            {"ok": True, "status": "empty", "message": "没有匹配的记录，未做任何修改"},
            ensure_ascii=False,
        )

    head = preview_df.head(PREVIEW_LIMIT)

    # 卡片的列名走 `_label_for_column`——它会把 `x_before` / `x_after`
    # 还原成「X（改前）」「X（改后）」，其余列取表定义里的中文名
    labels = [_label_for_column(c, ctx.table_name) for c in head.columns]
    card_rows = [[jsonable(v) for v in row] for row in head.values.tolist()]

    pending = {
        "type": "transform",
        "stage": "confirm",
        # —— 卡片字段 ——
        "table": ctx.table_name,
        "columns": labels,
        "records": card_rows,
        "affected": len(preview_df),
        "danger": is_full_table,
        # —— 内部字段 ——
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "update_sql": update_sql,
        "preview_sql": preview_sql,
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"将修改 {len(preview_df)} 条记录，等待用户确认",
        pending_action=pending,
    )



def execute_transform(pending: dict, table_name: str,
                     trace_id: str, user_input: str) -> str:
    """执行变换。事务包裹，失败自动回滚。返回 JSON。

    规则型操作给 `operation`（"干了什么"），不给 `changes`——
    明细型（update）才逐条给改前改后。design 工具层的分法。
    """
    update_sql = pending["update_sql"]
    affected = pending["affected"]

    with transaction() as tx:
        tx.execute(update_sql)

    log("transform", {
        "trace_id": trace_id,
        "user_input": user_input,
        "table": table_name,
        "update_sql": update_sql,
        "affected_count": affected,
    })
    return json.dumps({
        "ok": True,
        "table": table_name,
        "affected": affected,
        "operation": user_input,
    }, ensure_ascii=False)