"""结构快照草案：破坏性操作前，先留一条退路。

对应 design.md 数据层第五节。**一个粒度打天下**——覆盖导入 / 删表 /
删列 / 回滚本身，全是整表快照，没有更细的。

## 快照 = 结构 + 数据，缺一不可

`CREATE TABLE snap AS SELECT * FROM t` 只复制**列名和类型**，
约束（主键 / NOT NULL / 默认值 / UNIQUE）一个都不带。所以结构得从
`sqlite_master` 把原始 `CREATE TABLE` 语句抄下来，回滚时拿它重建——
否则回滚出来的是一张没有约束的复印件，而唯一约束正是
design 说的"数据库层面挡住重复"的依据。

## 中文映射不跟着回滚

那是语义层、是人标的，**比数据金贵**。跟着回滚，用户白标的功夫就丢了；
不跟，某列被删了标注也留着——哪天列回来，标注自动复活。
变成孤儿标注也无害：它不显示，也不参与任何判断。

## 规模

整表快照 = 数据复制一份。一万行的表 × 十个快照 = 十万行，SQLite 不当回事。
要担心的是**快照表的数量**（`_gx_snap_*` 会一直长），所以配一个 30 天清理。

跑一遍看结论：
    python docs/draft_snapshot.py
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import draft_softdelete as sd          # 落地时两块会并进同一个模块

META = "_gx_snapshot"
SNAP_PREFIX = "_gx_snap_"

# 因何产生。前端版本历史里显示的就是这个
KINDS = ("import", "drop_table", "drop_column", "rollback")


def ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {META} ("
        "  id         INTEGER PRIMARY KEY,"
        "  created_at TEXT NOT NULL,"
        "  kind       TEXT NOT NULL,"          # 见 KINDS
        "  table_name TEXT NOT NULL,"
        "  rows       INTEGER NOT NULL,"
        "  ddl        TEXT NOT NULL)"          # 原始 CREATE TABLE，带约束
    )


def snapshot(conn: sqlite3.Connection, table: str, kind: str) -> int:
    """给 table（业务名，即视图名）落一份快照，返回快照 id。

    **调用方负责开事务**——落快照和随后那个破坏性操作必须在同一个
    事务里，否则"快照成功但操作失败"会留下一堆没用的快照，
    而"操作成功但快照没落"则是灾难。
    """
    if kind not in KINDS:
        raise ValueError(f"kind 只能是 {KINDS}，收到 {kind!r}")

    all_name = f"{table}{sd.SOFTDEL_SUFFIX}"
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (all_name,)
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} 不存在（找不到 {all_name}）")

    n = conn.execute(f"SELECT count(*) FROM {sd._quote(all_name)}").fetchone()[0]
    cur = conn.execute(
        f"INSERT INTO {META} (created_at, kind, table_name, rows, ddl) "
        f"VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), kind, table, n, row[0]),
    )
    snap_id = cur.lastrowid

    # 数据直接拷一张表，不序列化成 blob——**预览就是查它**，
    # 而且拷贝比序列化快
    conn.execute(
        f"CREATE TABLE {sd._quote(SNAP_PREFIX + str(snap_id))} AS "
        f"SELECT * FROM {sd._quote(all_name)}"
    )
    return snap_id


def list_snapshots(conn: sqlite3.Connection, table: str | None = None) -> list[dict]:
    """倒序（最新在前）。table 给 None 就是全库的。"""
    sql = f"SELECT id, created_at, kind, table_name, rows FROM {META}"
    args: tuple = ()
    if table:
        sql += " WHERE table_name = ?"
        args = (table,)
    sql += " ORDER BY id DESC"
    return [
        {"id": r[0], "at": r[1], "kind": r[2], "table": r[3], "rows": r[4]}
        for r in conn.execute(sql, args)
    ]


def preview(conn: sqlite3.Connection, snap_id: int, limit: int | None = None):
    """看快照里有什么——**是看，不是回滚**（design 第 620 行）。"""
    snap = SNAP_PREFIX + str(snap_id)
    cols = sd._columns(conn, snap)
    sql = f"SELECT * FROM {sd._quote(snap)}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return cols, conn.execute(sql).fetchall()


def rollback(conn: sqlite3.Connection, snap_id: int) -> None:
    """把表退回 snap_id 那一刻。

    **回滚本身也是破坏性操作**——所以第一步是给"现在的样子"再落一份，
    否则回滚错了就再也回不来（design 第 621 行）。
    """
    meta = conn.execute(
        f"SELECT table_name, ddl FROM {META} WHERE id = ?", (snap_id,)
    ).fetchone()
    if meta is None:
        raise ValueError(f"没有这个快照：{snap_id}")
    table, ddl = meta
    all_name = f"{table}{sd.SOFTDEL_SUFFIX}"
    snap_table = SNAP_PREFIX + str(snap_id)

    # 1) 先保命
    snapshot(conn, table, "rollback")

    # 2) 拆掉现在的
    for suffix in ("ins", "upd", "del"):
        conn.execute(f"DROP TRIGGER IF EXISTS {sd._quote(f'{table}_{suffix}')}")
    conn.execute(f"DROP VIEW IF EXISTS {sd._quote(table)}")
    conn.execute(f"DROP TABLE IF EXISTS {sd._quote(all_name)}")

    # 3) 拿原始 ddl 重建——这句自带主键 / NOT NULL / 默认值
    conn.execute(ddl)

    # 4) 数据搬回来
    cols = sd._columns(conn, snap_table)
    joined = ", ".join(sd._quote(c) for c in cols)
    conn.execute(
        f"INSERT INTO {sd._quote(all_name)} ({joined}) "
        f"SELECT {joined} FROM {sd._quote(snap_table)}"
    )

    # 5) 索引和触发器跟上
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {sd._quote(table + '_alive')} "
        f"ON {sd._quote(all_name)} (is_deleted)"
    )
    sd._rebuild(conn, table, sd._columns(conn, all_name), sd._pk_of(conn, all_name))


def cleanup(conn: sqlite3.Connection, days: int = 30) -> int:
    """删掉过期快照，返回删了几份。design 第 626 行：快照留 30 天。"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    old = [r[0] for r in conn.execute(
        f"SELECT id FROM {META} WHERE created_at < ?", (cutoff,)
    )]
    for snap_id in old:
        conn.execute(f"DROP TABLE IF EXISTS {sd._quote(SNAP_PREFIX + str(snap_id))}")
        conn.execute(f"DELETE FROM {META} WHERE id = ?", (snap_id,))
    return len(old)


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    conn = sqlite3.connect(":memory:", isolation_level=None)
    ok = True

    def check(label, passed, detail=""):
        global ok
        ok = ok and passed
        print(f"   {'✓' if passed else '✗'} {label}{'  ' + detail if detail else ''}")

    sd.create_table(
        conn, "projects",
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT, review_count INTEGER DEFAULT 0",
    )
    ensure_meta(conn)

    conn.execute("INSERT INTO projects (name, owner, review_count) VALUES ('甲', '张三', 2)")
    conn.execute("INSERT INTO projects (name, owner, review_count) VALUES ('乙', '李四', 0)")

    print("① 落一份快照")
    conn.execute("BEGIN")
    s1 = snapshot(conn, "projects", "import")
    conn.execute("COMMIT")
    print(f"   snapshot → id={s1}")
    check("元信息记上了",
          conn.execute(f"SELECT kind, rows FROM {META} WHERE id={s1}").fetchone() == ("import", 2))
    check("数据表建出来了",
          conn.execute(f"SELECT count(*) FROM {SNAP_PREFIX}{s1}").fetchone()[0] == 2)

    print("\n② 破坏它：改数据 + 删一列")
    conn.execute("UPDATE projects SET review_count = 99 WHERE name = '甲'")
    conn.execute("DELETE FROM projects WHERE name = '乙'")
    sd.drop_column(conn, "projects", "owner")
    cols_now = sd._columns(conn, "projects")
    print(f"   现在的列：{cols_now}")
    check("owner 没了", "owner" not in cols_now)
    check("乙被软删了", conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 1)

    print("\n③ 回滚到快照")
    conn.execute("BEGIN")
    rollback(conn, s1)
    conn.execute("COMMIT")
    cols_back = sd._columns(conn, "projects")
    rows_back = conn.execute("SELECT name, owner, review_count FROM projects ORDER BY name").fetchall()
    print(f"   回滚后的列：{cols_back}")
    print(f"   回滚后的行：{rows_back}")
    check("列回来了", "owner" in cols_back)
    # 用 sorted 比：SQLite 对中文默认按 UTF-8 字节序排，别指望"甲"在前
    check("数据回来了",
          sorted(rows_back) == sorted([("甲", "张三", 2), ("乙", "李四", 0)]))
    check("被软删的乙复活了", len(rows_back) == 2)

    print("\n④ 结构不只是列名——约束也得回来")
    ddl_now = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'projects_all'"
    ).fetchone()[0]
    print(f"   {ddl_now}")
    check("NOT NULL 在", "NOT NULL" in ddl_now)
    check("默认值在", "DEFAULT 0" in ddl_now)
    check("主键在", "PRIMARY KEY" in ddl_now)

    print("\n⑤ 回滚本身也留了一份（否则回滚错了没得救）")
    snaps = list_snapshots(conn, "projects")
    print(f"   快照链：{[(s['id'], s['kind']) for s in snaps]}")
    check("多了一份 rollback", any(s["kind"] == "rollback" for s in snaps))

    print("\n⑥ 回滚后功能没坏")
    conn.execute("DELETE FROM projects WHERE name = '甲'")
    check("软删仍然生效", conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 1)
    check("底表里两条都在", conn.execute("SELECT count(*) FROM projects_all").fetchone()[0] == 2)

    print("\n⑦ 预览")
    cols, rows = preview(conn, s1)
    print(f"   {cols} / {len(rows)} 行")
    check("预览拿到的是快照那一刻的数据", len(rows) == 2)

    print("\n⑧ 30 天清理")
    conn.execute(
        f"UPDATE {META} SET created_at = '2000-01-01T00:00:00' WHERE id = ?", (s1,)
    )
    n = cleanup(conn, days=30)
    check("删掉了过期的", n == 1, f"删了 {n} 份")
    check("快照表也一起 DROP 了",
          conn.execute(
              "SELECT count(*) FROM sqlite_master WHERE name = ?", (SNAP_PREFIX + str(s1),)
          ).fetchone()[0] == 0)
    check("没过期的留着", len(list_snapshots(conn)) == 1)

    conn.close()
    print("\n" + ("全部通过。" if ok else "有失败项。"))
