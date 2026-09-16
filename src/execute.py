import threading
import duckdb
from guard import SecurityError


MAX_ROWS = 1_000_000     # 内存保护：防极端情况，不限制正常使用
QUERY_TIMEOUT = 30


def execute_sql(sql: str, db_path: str):
    """执行 SQL。只允许 SELECT。带内存保护和超时保护。"""
    if not sql.strip().lower().startswith("select"):
        raise SecurityError(f"只允许 SELECT 查询，拒绝执行：{sql[:50]}")

    sql_clean = sql.strip().rstrip(";")
    wrapped_sql = f"SELECT * FROM ({sql_clean}) AS _limited LIMIT {MAX_ROWS + 1}"

    con = duckdb.connect(db_path, read_only=True)
    timer = threading.Timer(QUERY_TIMEOUT, con.interrupt)
    timer.start()

    try:
        df = con.execute(wrapped_sql).fetchdf()
    except Exception as e:
        if "interrupt" in str(e).lower():
            raise TimeoutError(f"SQL 查询超过 {QUERY_TIMEOUT} 秒，已中断")
        raise
    finally:
        timer.cancel()
        con.close()

    if len(df) > MAX_ROWS:
        df = df.head(MAX_ROWS).copy()
        df.attrs["truncated"] = True
    else:
        df.attrs["truncated"] = False

    return df