"""清理过期的软删数据。启动时调用一次。

**跨所有表。** 旧版把 projects 的列名写死在里面
（`project_name` / `delete_trace_id`），换一张表就崩——
而"多表"正是这个项目要去的方向。

SQL 也换了：旧版用 `NOW() - INTERVAL '7 days'`，那是 PG 的语法。
SQLite 写 `datetime('now', '-7 days')`，或者直接拿算好的字符串比——
这里用后者，因为 `deleted_at` 存的就是本地时间字符串，
两边格式一致才能比。
"""

from datetime import datetime, timedelta

from audit import log
from config import setting
from runner import connect
from storage import SOFTDEL_SUFFIX, list_tables, quote


def cleanup() -> int:
    """物理删掉超过保留期的软删行。返回删了几条。

    **自己拿一个连接走完全程**：`storage` 的函数要连接（它是纯函数，
    不管连接的生命周期），而这里要跨表循环，一路开新连接没必要。

    **只删 `deleted_at` 有值的**——那是真的被删过。没有时间的
    （比如手工把 is_deleted 改成 1，或者补裸表时带进来的历史状态）
    不动它：没有起点就谈不上"过期"，删了属于误伤。
    """
    days = setting("safety.retention_days")
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(
        sep=" ", timespec="seconds"
    )
    condition = "is_deleted = 1 AND deleted_at IS NOT NULL AND deleted_at < ?"

    total = 0
    con = connect()
    try:
        for table in list_tables(con):
            all_name = quote(table + SOFTDEL_SUFFIX)
            n = con.execute(
                f"SELECT count(*) FROM {all_name} WHERE {condition}", [cutoff]
            ).fetchone()[0]
            if not n:
                continue

            # 先记审计，再删——顺序反了就查不出"谁被清掉了"
            log("cleanup", {
                "trigger": "startup",
                "table": table,
                "retention_days": days,
                "deleted_count": int(n),
            })

            con.execute(f"DELETE FROM {all_name} WHERE {condition}", [cutoff])
            total += n
    finally:
        con.close()

    if total:
        print(f"[清理] 已物理删除 {total} 条过期数据")
    return int(total)


if __name__ == "__main__":
    cleanup()
