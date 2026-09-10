import duckdb
from guard import SecurityError


def execute_sql(sql: str, db_path: str):
    if not sql.strip().lower().startswith("select"):
        raise SecurityError(f"只允许 SELECT 查询，拒绝执行：{sql[:50]}")
    
    con = duckdb.connect(db_path, read_only=True)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()