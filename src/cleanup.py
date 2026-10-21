"""清理过期的软删数据和快照。启动时调用一次。

**跨所有表。** 旧版把 projects 的列名写死在里面
（`project_name` / `delete_trace_id`），换一张表就崩——
而"多表"正是这个项目要去的方向。

SQL 也换了：旧版用 `NOW() - INTERVAL '7 days'`，那是 PG 的语法。
SQLite 写 `datetime('now', '-7 days')`，或者直接拿算好的字符串比——
这里用后者，因为 `deleted_at` 存的就是本地时间字符串，
两边格式一致才能比。

**两种清理的保留期不同**：软删行 7 天，快照 30 天——快照更重，
能回头的时间也该更长。快照那一头还有开关，可以整个关掉。
"""

from datetime import datetime, timedelta

from audit import record
from config import setting
from runner import connect, transaction
from snapshot import cleanup as snapshot_cleanup
from storage import SOFTDEL_SUFFIX, has_soft_delete, list_tables, quote


def cleanup() -> int:
    """物理删掉超过保留期的软删行。返回删了几条。

    **一个事务走完全程**：删除和审计要么一起成，要么一起不成。
    旧版是先写文件审计、再单独删——中间崩了就是假账。

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
    with transaction() as tx:
        for table in list_tables(tx):
            # 裸表没有 `_all`，也没有软删列——它不存在"过期软删行"，
            # 跳过。不跳的话，一张用户手工建的无主键表会让启动清理
            # 抛 no such table，整个应用起不来
            if not has_soft_delete(tx, table):
                continue
            all_name = quote(table + SOFTDEL_SUFFIX)
            n = tx.execute(
                f"SELECT count(*) FROM {all_name} WHERE {condition}", [cutoff]
            ).fetchone()[0]
            if not n:
                continue

            tx.execute(f"DELETE FROM {all_name} WHERE {condition}", [cutoff])
            record(tx, "cleanup", {
                "trigger": "startup",
                "table": table,
                "retention_days": days,
                "deleted_count": int(n),
            })
            total += n

    if total:
        print(f"[清理] 已物理删除 {total} 条过期数据")

    # 文档库的回收站：保留期到了，切片和原文件一起走
    try:
        from rag import service as rag_service
        purged = rag_service.purge_expired()
        if purged:
            print(f"[清理] 已物理删除 {purged} 份过期文档")
    except Exception as e:
        # 文档库清理失败不该拖住数据行清理的收尾
        print(f"[清理] 文档库清理失败：{e}")

    return int(total)


def cleanup_snapshots() -> int:
    """按保留期删快照。开关关掉时直接返回 0。"""
    if setting("safety.snapshot_auto_clean") != "on":
        return 0

    days = setting("safety.snapshot_retention_days")
    con = connect()
    try:
        n = snapshot_cleanup(con, days=days)
    finally:
        con.close()

    if n:
        print(f"[清理] 已删除 {n} 份过期快照")
    return int(n)


if __name__ == "__main__":
    cleanup()
    cleanup_snapshots()
