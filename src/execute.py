from guard import SecurityError
from config import setting
from db import query_df


def execute_sql(sql: str, db_path: str):
    """执行 SQL。只允许 SELECT。带内存保护和超时保护。

    注意：db_path 参数保留，但已经不使用——数据源现在由 db.py 统一管理。
    留着是为了不破坏调用方签名（agent / tools 还在传它）。
    """
    max_rows = setting("safety.max_rows")
    query_timeout = setting("safety.query_timeout")

    if not sql.strip().lower().startswith("select"):
        raise SecurityError(f"只允许 SELECT 查询，拒绝执行：{sql[:50]}")

    sql_clean = sql.strip().rstrip(";")
    wrapped_sql = f"SELECT * FROM ({sql_clean}) AS _limited LIMIT {max_rows + 1}"

    df = query_df(wrapped_sql, timeout=query_timeout)

    if len(df) > max_rows:
        df = df.head(max_rows).copy()
        df.attrs["truncated"] = True
    else:
        df.attrs["truncated"] = False

    return df