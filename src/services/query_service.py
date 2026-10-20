import datetime
import json
import math

import pandas as pd

from guard import SecurityError
from nl2sql import generate_sql_with_retry
from execute import execute_sql
from runner import query_df


# 旧版这里有一个 AMBIGUOUS_FIELD_MAP：检测"布尔列 vs 状态文本"的两种理解。
# 那是软著表的结构（派生布尔字段 + 组合状态字符串），别的表不长这样——
# 它把一张测试数据的 schema 固化进了产品。删掉。
#
# 如果将来真需要"同一查询的两种理解"，那该由**表定义**驱动
# （比如声明"这列由那列派生"），而不是写死五个中文状态词。


def _jsonable(v):
    """DataFrame 里的值转成 JSON 能吃的。

    `df.values.tolist()` 给出来的是 numpy 标量（int64 / float64）和
    pandas Timestamp——它们 `json.dumps` 会直接抛 TypeError。
    日期统一成 ISO 字符串，跟库里存的格式一致。
    """
    if v is None:
        return None
    if isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, (pd.Timestamp, datetime.date, datetime.datetime)):
        return v.isoformat(sep=" ") if isinstance(v, pd.Timestamp) else v.isoformat()
    if isinstance(v, float) and math.isnan(v):
        return None
    # numpy 标量有 .item()；拿不到的走 str
    return v.item() if hasattr(v, "item") else str(v)


def run(question: str, ctx) -> str:
    """查数据。**返回数据本身，不返回"答案"。**

    design 工具层第一条：工具返回只给模型，不给用户。
    旧版在这里调 `summarize()` 把 DataFrame 翻成一段人话——模型拿到的是
    成品文字，想去重、想画图、想再筛一遍都无从下手。
    现在给的是 columns / rows，模型手里有数据，怎么用是它的事。
    """
    try:
        sql, _ = generate_sql_with_retry(
            question, ctx.llm, ctx.schema, ctx.table_name, max_retries=2
        )
        df = execute_sql(sql)

        result = {
            "ok": True,
            "status": "empty" if len(df) == 0 else "ok",
            "table": ctx.table_name,
            "columns": [str(c) for c in df.columns],
            "rows": [[_jsonable(v) for v in row] for row in df.values.tolist()],
            "row_count": len(df),
            "truncated": bool(df.attrs.get("truncated")),
            "sql": sql,
        }

        if len(df) == 0:
            # 空结果是**事实**，不是失败。给一个参照物：表里一共多少行——
            # 模型才能说出"表里有 166 条，符合条件的是 0 条"这种话。
            total = int(query_df(f"SELECT COUNT(*) AS n FROM {ctx.table_name}").iloc[0, 0])
            result["total_records_in_table"] = total

        return json.dumps(result, ensure_ascii=False)
    except SecurityError as e:
        return json.dumps(
            {"ok": False, "error": f"安全拒绝：{e}", "error_type": "security"},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": str(e), "error_type": "unknown"}, ensure_ascii=False
        )