from guard import SecurityError
from config import setting
from runner import query_df


def execute_sql(sql: str, system: bool = False):
    """执行 SQL。只允许 SELECT，带内存保护和超时保护。

    `system=True` 给「恢复 / 列出已删」用：它们要打底表、要看 is_deleted，
    是设计里明写了的特权旁路。旁路只跳过表名和系统列检查，
    语句类型（只许 SELECT）照查。
    """
    max_rows = setting("safety.max_rows")
    query_timeout = setting("safety.query_timeout")

    if not sql.strip().lower().startswith("select"):
        raise SecurityError(f"只允许 SELECT 查询，拒绝执行：{sql[:50]}")

    sql_clean = sql.strip().rstrip(";")
    wrapped_sql = f"SELECT * FROM ({sql_clean}) AS _limited LIMIT {max_rows + 1}"

    df = query_df(wrapped_sql, timeout=query_timeout, system=system)

    if len(df) > max_rows:
        df = df.head(max_rows).copy()
        df.attrs["truncated"] = True
    else:
        df.attrs["truncated"] = False

    return df