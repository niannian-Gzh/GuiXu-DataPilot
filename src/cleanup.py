import db
from config import load_config, resolve_db_url, setting
from audit import log


def cleanup():
    """清理超过保留期的软删除数据。启动时调用一次。"""
    retention_days = setting("safety.retention_days")
    cfg = load_config()["data"]
    real_table = f"{cfg['table_name']}_all"

    # 1. 找出要清理的记录
    df = db.query_df(f"""
        SELECT project_name, deleted_at, delete_trace_id
        FROM {real_table}
        WHERE is_deleted = true
          AND deleted_at < CAST(NOW() AS TIMESTAMP)
          - INTERVAL '{retention_days} days'
    """)

    if len(df) == 0:
        return 0

    # 2. 记录审计日志（先记，再删）
    # 显式转成字符串——DataFrame 里可能是 Timestamp 对象，json 序列化会崩
    deleted_records = [
        {
            "project_name": str(row[0]),
            "deleted_at": str(row[1]) if row[1] is not None else None,
            "delete_trace_id": str(row[2]) if row[2] is not None else None,
        }
        for row in df.values.tolist()
    ]

    log("cleanup", {
        "trigger": "startup",
        "retention_days": retention_days,
        "deleted_count": len(df),
        "deleted_records": deleted_records,
    })

    # 3. 真正物理删除
    db.execute(f"""
        DELETE FROM {real_table}
        WHERE is_deleted = true
          AND deleted_at < CAST(NOW() AS TIMESTAMP)
          - INTERVAL '{retention_days} days'
    """)

    print(f"[清理] 已物理删除 {len(df)} 条过期数据")
    return len(df)


if __name__ == "__main__":
    cleanup()