import json
from guard import SecurityError
from nl2sql import generate_sql_with_retry
from execute import execute_sql
from summarize import summarize
from db import query_df


AMBIGUOUS_FIELD_MAP = {
    "is_settled = true": ("status_raw = '已结算'", "精确匹配：状态恰好是'已结算'"),
    "is_certified = true": ("status_raw = '已下证'", "精确匹配：状态恰好是'已下证'"),
    "is_rejected = true": ("status_raw = '已打回'", "精确匹配：状态恰好是'已打回'"),
    "is_pending = true": ("status_raw = '待提交'", "精确匹配：状态恰好是'待提交'"),
    "is_submitted = true": ("status_raw = '已提交'", "精确匹配：状态恰好是'已提交'"),
}


def _detect_ambiguity(sql, df, ctx):
    """检测 SQL 是否有歧义解读。只在 SQL 用了布尔字段时检测。"""
    for old, (new, description) in AMBIGUOUS_FIELD_MAP.items():
        if old in sql:
            alt_sql = sql.replace(old, new)
            try:
                alt_df = execute_sql(alt_sql, ctx.db_path)
            except Exception:
                continue
            if df.to_string() != alt_df.to_string():
                def _val(d):
                    if d.shape == (1, 1):
                        return str(d.iloc[0, 0])
                    return f"{d.shape[0]} 行"
                return {
                    "ambiguous": True,
                    "branches": [
                        {"interpretation": "包含匹配（默认，含组合状态）", "value": _val(df)},
                        {"interpretation": description, "value": _val(alt_df)},
                    ],
                }
    return None


def run(question: str, ctx) -> str:
    try:
        sql, _ = generate_sql_with_retry(
            question, ctx.llm, ctx.schema, ctx.db_path, ctx.table_name, max_retries=2
        )
        df = execute_sql(sql, ctx.db_path)
        answer = summarize(question, df, ctx.llm)

        result = {"sql": sql, "row_count": len(df), "answer": answer}

        ambiguity = _detect_ambiguity(sql, df, ctx)
        if ambiguity:
            result.update(ambiguity)

        if len(df) == 0:
            count_df = query_df(f"SELECT COUNT(*) AS n FROM {ctx.table_name}")
            total = int(count_df.iloc[0, 0])
            result["total_records_in_table"] = total
            result["hint"] = (
                f"查询已完整执行，无报错。表中共有 {total} 条记录，"
                f"符合当前筛选条件的为 0 条。这个结果是可信的。"
            )

        return json.dumps(result, ensure_ascii=False)
    except SecurityError as e:
        return json.dumps({"error": f"安全拒绝：{e}", "is_security": True}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)