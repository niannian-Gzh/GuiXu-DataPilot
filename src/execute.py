import threading
import duckdb
from guard import SecurityError
from config import setting


def execute_sql(sql: str, db_path: str):
    """执行 SQL。只允许 SELECT。带内存保护和超时保护。"""
    # 这里读配置而不是用模块常量：execute 是热点路径，
    # setting() 走 mtime 缓存，不会每次都读盘
    max_rows = setting("safety.max_rows")
    query_timeout = setting("safety.query_timeout")

    if not sql.strip().lower().startswith("select"):
        raise SecurityError(f"只允许 SELECT 查询，拒绝执行：{sql[:50]}")

    sql_clean = sql.strip().rstrip(";")
    wrapped_sql = f"SELECT * FROM ({sql_clean}) AS _limited LIMIT {max_rows + 1}"

    con = duckdb.connect(db_path, read_only=True)
    timer = threading.Timer(query_timeout, con.interrupt)
    timer.start()

    try:
        df = con.execute(wrapped_sql).fetchdf()
    except Exception as e:
        if "interrupt" in str(e).lower():
            raise TimeoutError(f"SQL 查询超过 {query_timeout} 秒，已中断")
        raise
    finally:
        timer.cancel()
        con.close()

    if len(df) > max_rows:
        df = df.head(max_rows).copy()
        df.attrs["truncated"] = True
    else:
        df.attrs["truncated"] = False

    return df