import duckdb
from config import load_config, resolve, resolve_db_url, setting
from audit import log


def cleanup():
    """清理超过保留期的软删除数据。启动时调用一次。"""
    retention_days = setting("safety.retention_days")
    cfg = load_config()["data"]
    real_table = f"{cfg['table_name']}_all"
    con = duckdb.connect(resolve_db_url())

    # 1. 找出要清理的记录
    rows = con.execute(f"""
        SELECT project_name, deleted_at, delete_trace_id
        FROM {real_table}
        WHERE is_deleted = true
          AND deleted_at < CAST(NOW() AS TIMESTAMP)
          - INTERVAL '{retention_days} days'
    """).fetchall()

    if not rows:
        con.close()
        return 0

    # 2. 记录审计日志（先记，再删）
    log("cleanup", {
        "trigger": "startup",
        "retention_days": retention_days,
        "deleted_count": len(rows),
        "deleted_records": [
            {"project_name": r[0], "deleted_at": r[1], "delete_trace_id": r[2]}
            for r in rows
        ],
    })

    # 3. 真正物理删除
    con.execute(f"""
        DELETE FROM {real_table}
        WHERE is_deleted = true
          AND deleted_at < CAST(NOW() AS TIMESTAMP)
          - INTERVAL '{retention_days} days'
    """)

    print(f"[清理] 已物理删除 {len(rows)} 条过期数据")
    return len(rows)


if __name__ == "__main__":
    cleanup()