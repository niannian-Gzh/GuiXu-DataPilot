"""恢复页背后的查询与动作。

**这一层不经过模型。** 垃圾桶和版本历史是人在页面上直接翻、直接点的——
它是"看数据"，不是"问数据"。执行端全部复用现有服务：

- 恢复一行 → `restore_service.execute_restore`（清软删标记 + 审计）
- 回滚到某个快照 → `structure_service.execute_structure`（事务 + 审计，
  回滚前还会再落一份快照）

这里只管它俩不管的两件事：**列出来**，和**把行摊平成界面要的形状**。
"""

import json
from datetime import datetime

import schema_store
import snapshot
import storage
from config import setting
from runner import connect
from services import restore_service, structure_service


def _cell(v):
    """SQLite 里能存的东西不都能进 JSON。"""
    if isinstance(v, (bytes, bytearray)):
        return f"<二进制 {len(v)} 字节>"
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    return v


def _days_left(deleted_at, days: int, now: datetime):
    """垃圾桶的倒计时。没有删除时间的（手工标记的）不倒数。"""
    if not deleted_at:
        return None
    try:
        t = datetime.fromisoformat(str(deleted_at))
    except ValueError:
        return None
    return max(days - (now - t).days, 0)


def deleted_rows() -> list[dict]:
    """跨所有表列出被软删的行，按表分组。

    **走底表**——已删的行在视图里根本看不见。列名用数据字典里的中文名；
    没标过的退回字段名，界面不会出现空表头。
    """
    days = int(setting("safety.retention_days"))
    now = datetime.now()
    con = connect()
    try:
        out = []
        for name in storage.list_tables(con):
            all_name = name + storage.SOFTDEL_SUFFIX
            cols = [c for c in storage.columns_of(con, all_name)
                    if c not in storage.SYSTEM_COLS]
            if not cols:
                continue

            rows = con.execute(
                f"SELECT {', '.join(storage.quote(c) for c in cols)}, deleted_at "
                f"FROM {storage.quote(all_name)} WHERE is_deleted = 1 "
                f"ORDER BY deleted_at DESC"
            ).fetchall()
            if not rows:
                continue

            meta = schema_store.get_table_schema(name)
            labels = {f["name"]: f["label"] for f in meta["fields"]}
            pk = storage.pk_of(con, all_name)

            out.append({
                "name": name,
                "label": meta["label"],
                "count": len(rows),
                "columns": [labels.get(c) or c for c in cols] + ["删除时间", "剩余天数"],
                "rows": [
                    [_cell(v) for v in r[:-1]]
                    + [r[-1], _days_left(r[-1], days, now)]
                    for r in rows
                ],
                # 没有主键就没法按行恢复——这一组只让看
                "pk_index": cols.index(pk) if pk in cols else None,
            })
        return out
    finally:
        con.close()


def restore(table: str, ids: list) -> dict:
    """按行恢复。和对话里那条恢复走同一个执行端，审计照记。"""
    con = connect()
    try:
        pk = storage.pk_of(con, table + storage.SOFTDEL_SUFFIX)
    finally:
        con.close()

    if not pk:
        return {"ok": False, "error": "这张表没有主键，无法按行恢复"}
    try:
        n = restore_service.execute_restore(
            [{pk: v} for v in ids], table, "ui", "恢复页手动恢复",
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "table": table, "affected": n}


def snapshots() -> list[dict]:
    """按表分组的快照清单。组序跟最新一条走（list_snapshots 本身倒序）。

    `exists` 是给界面提个醒：快照留着，表可能已经删了。删表前那张快照
    存在的意义就是"还能把表变回来"，所以这一类不该藏起来，但要说明白。
    """
    con = connect()
    try:
        items = snapshot.list_snapshots(con)
        groups: dict[str, list] = {}
        for s in items:
            groups.setdefault(s["table"], []).append({
                "id": s["id"],
                "at": s["at"],
                "kind": s["kind"],
                "kind_label": s["label"],
                "rows": s["rows"],
            })
        exists = {
            table: con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table + storage.SOFTDEL_SUFFIX,),
            ).fetchone() is not None
            for table in groups
        }
    finally:
        con.close()

    out = []
    for table, snaps in groups.items():
        meta = schema_store.get_table_schema(table)
        out.append({
            "name": table, "label": meta["label"],
            "exists": exists.get(table, False),
            "snapshots": snaps,
        })
    return out


def preview(snap_id: int, limit: int = 200) -> dict | None:
    """看快照里有什么——**是看，不是回滚**。"""
    con = connect()
    try:
        row = con.execute(
            f"SELECT table_name FROM {snapshot.META} WHERE id = ?", (snap_id,)
        ).fetchone()
        if row is None:
            return None
        cols, rows = snapshot.preview(con, snap_id, limit=limit)
        total = con.execute(
            f"SELECT count(*) FROM {storage.quote(snapshot.SNAP_PREFIX + str(snap_id))}"
        ).fetchone()[0]
        return {
            "ok": True,
            "table": row[0],
            "columns": cols,
            "rows": [[_cell(v) for v in r] for r in rows],
            "total": total,
            "shown": len(rows),
        }
    finally:
        con.close()


def rollback(snap_id: int) -> dict:
    """退回某个快照。执行端会先给当前状态再落一份快照，回滚错了还能回来。"""
    con = connect()
    try:
        row = con.execute(
            f"SELECT table_name FROM {snapshot.META} WHERE id = ?", (snap_id,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return {"ok": False, "error": f"没有这个快照：{snap_id}"}

    return json.loads(structure_service.execute_structure(
        {"action": "rollback", "snapshot_id": snap_id, "table_name": row[0]},
        "ui", "恢复页手动回滚",
    ))


def counts() -> dict:
    """左栏那个读数：还能恢复几行、手上有几份快照。"""
    con = connect()
    try:
        deleted = 0
        for name in storage.list_tables(con):
            if not storage.has_soft_delete(con, name):
                continue
            deleted += con.execute(
                f"SELECT count(*) FROM {storage.quote(name + storage.SOFTDEL_SUFFIX)} "
                f"WHERE is_deleted = 1"
            ).fetchone()[0]
        snaps = len(snapshot.list_snapshots(con))
    finally:
        con.close()
    return {"deleted": int(deleted), "snapshots": snaps}
