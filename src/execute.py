from guard import SecurityError
from config import setting
from runner import query_df


def execute_sql(sql: str):
    """执行 SQL。只允许 SELECT，带内存保护和超时保护。

    从前它收一个 `db_path`——那是"数据源是个要连的东西"时代的遗留，
    里面的注释自己都写着"保留但已不使用"。现在归 runner 统一管库，
    这个参数就彻底没了。
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