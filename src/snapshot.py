"""结构快照：破坏性操作前，先留一条退路。

对应 design.md 数据层第五节。

## 快照 = 结构 + 数据，缺一不可

`CREATE TABLE snap AS SELECT * FROM t` 只复制**列名和类型**，
约束（主键 / NOT NULL / 默认值 / UNIQUE）一个都不带。所以结构得从
`sqlite_master` 把原始 `CREATE TABLE` 语句抄下来，回滚时拿它重建——
否则回滚出来的是一张没有约束的复印件。

## 中文映射不跟着回滚

那是语义层、是人标的，**比数据金贵**。跟着回滚，用户白标的功夫就丢了；
不跟，某列被删了标注也留着——哪天列回来，标注自动复活。
变成孤儿标注也无害：它不显示，也不参与任何判断。

## 一个粒度打天下

覆盖导入 / 删表 / 删列 / 回滚本身，全是整表快照，没有更细的。
「删一行」不走这里，走软删除。

## 规模

整表快照 = 数据复制一份。一万行的表 × 十个快照 = 十万行，SQLite 不当回事。
要担心的是**快照表的数量**（`_gx_snap_*` 会一直长），所以配一个 30 天清理。
"""

import sqlite3
from datetime import datetime, timedelta

import storage

META = "_gx_snapshot"
SNAP_PREFIX = "_gx_snap_"

# 因何产生。界面上的「版本历史」显示的就是它
KINDS = ("import", "drop_table", "drop_column", "rollback")
KIND_LABEL = {
    "import": "覆盖导入前",
    "drop_table": "删表前",
    "drop_column": "删列前",
    "rollback": "回滚前",
}


def ensure_meta(con: sqlite3.Connection) -> None:
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {META} ("
        "  id         INTEGER PRIMARY KEY,"
        "  created_at TEXT NOT NULL,"
        "  kind       TEXT NOT NULL,"
        "  table_name TEXT NOT NULL,"
        "  rows       INTEGER NOT NULL,"
        "  ddl        TEXT NOT NULL,"      # 原始 CREATE TABLE，带约束
        "  indexes    TEXT NOT NULL)"      # 原始 CREATE INDEX，带唯一约束
    )


def snapshot(con: sqlite3.Connection, table: str, kind: str) -> int:
    """给 table（业务名，即视图名）落一份快照，返回快照 id。

    **调用方负责开事务**——落快照和随后那个破坏性操作必须攥在一起，
    否则会留下"有快照没操作"或更糟的"有操作没快照"。
    """
    if kind not in KINDS:
        raise ValueError(f"kind 只能是 {KINDS}，收到 {kind!r}")

    all_name = table + storage.SOFTDEL_SUFFIX
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (all_name,)
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} 不存在（找不到 {all_name}）")

    n = con.execute(f"SELECT count(*) FROM {storage.quote(all_name)}").fetchone()[0]

    # 索引也得存。**表 ddl 里没有索引**——唯一约束建的是独立的部分索引，
    # 只存表的话，回滚重建出来会是一张没有唯一约束的表，而且不报错。
    indexes = [
        r[0] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
            "AND sql IS NOT NULL", (all_name,)
        )
    ]
    ddl = row[0]
    for idx_sql in indexes:                 # 表 ddl 里补上索引，回滚时一起执行
        ddl += ";\n" + idx_sql

    cur = con.execute(
        f"INSERT INTO {META} (created_at, kind, table_name, rows, ddl, indexes) "
        f"VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), kind, table, n, ddl,
         "\n".join(indexes)),
    )
    snap_id = cur.lastrowid

    # 数据直接拷一张表，不序列化成 blob——**预览就是查它**，而且拷贝比序列化快
    con.execute(
        f"CREATE TABLE {storage.quote(SNAP_PREFIX + str(snap_id))} AS "
        f"SELECT * FROM {storage.quote(all_name)}"
    )
    return snap_id


def list_snapshots(con: sqlite3.Connection, table: str | None = None) -> list[dict]:
    """倒序（最新在前）。table 给 None 就是全库的。"""
    sql = f"SELECT id, created_at, kind, table_name, rows FROM {META}"
    args: tuple = ()
    if table:
        sql += " WHERE table_name = ?"
        args = (table,)
    sql += " ORDER BY id DESC"
    return [
        {
            "id": r[0], "at": r[1], "kind": r[2], "label": KIND_LABEL.get(r[2], r[2]),
            "table": r[3], "rows": r[4],
        }
        for r in con.execute(sql, args)
    ]


def preview(con: sqlite3.Connection, snap_id: int, limit: int | None = None):
    """看快照里有什么——**是看，不是回滚**（design 第 620 行）。

    展示时挡掉系统列：存快照要忠实（`is_deleted` 得留着，回滚才能
    把"哪些已删"一起还原），但给人看的出口不该露它。
    """
    snap = storage.quote(SNAP_PREFIX + str(snap_id))
    cols = [c for c in storage.columns_of(con, SNAP_PREFIX + str(snap_id))
            if c not in storage.SYSTEM_COLS]
    sql = f"SELECT {', '.join(storage.quote(c) for c in cols)} FROM {snap}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return cols, con.execute(sql).fetchall()


def rollback(con: sqlite3.Connection, snap_id: int) -> None:
    """把表退回 snap_id 那一刻。

    **回滚本身也是破坏性操作**——所以第一步是给"现在的样子"再落一份，
    否则回滚错了就再也回不来（design 第 621 行）。
    """
    meta = con.execute(
        f"SELECT table_name, ddl FROM {META} WHERE id = ?", (snap_id,)
    ).fetchone()
    if meta is None:
        raise ValueError(f"没有这个快照：{snap_id}")
    table, ddl = meta
    all_name = table + storage.SOFTDEL_SUFFIX
    snap_table = SNAP_PREFIX + str(snap_id)

    snapshot(con, table, "rollback")                    # 1) 先保命

    for suffix in ("ins", "upd", "del"):                # 2) 拆掉现在的
        con.execute(f"DROP TRIGGER IF EXISTS {storage.quote(f'{table}_{suffix}')}")
    con.execute(f"DROP VIEW IF EXISTS {storage.quote(table)}")
    con.execute(f"DROP TABLE IF EXISTS {storage.quote(all_name)}")

    # 3) 原始 ddl 重建。它自带表约束；索引拼在同一条里（见 snapshot()）
    for stmt in (s.strip() for s in ddl.split(";") if s.strip()):
        con.execute(stmt)

    cols = storage.columns_of(con, snap_table)          # 4) 数据搬回来
    joined = ", ".join(storage.quote(c) for c in cols)
    con.execute(
        f"INSERT INTO {storage.quote(all_name)} ({joined}) "
        f"SELECT {joined} FROM {storage.quote(snap_table)}"
    )

    con.execute(                                        # 5) 存活索引与触发器跟上
        f"CREATE INDEX IF NOT EXISTS {storage.quote(table + '_alive')} "
        f"ON {storage.quote(all_name)} (is_deleted)"
    )
    storage.rebuild_access(
        con, table, storage.columns_of(con, all_name), storage.pk_of(con, all_name)
    )


def replace_all(
    con: sqlite3.Connection,
    table: str,
    columns: list[str],
    rows: list[tuple],
) -> int:
    """整表覆盖——重复导入走这条。返回灌进去多少行。

    **真删不是软删**：覆盖就是覆盖，不留痕。退路由快照负责。
    新导入的行 `is_deleted` 都是 0（默认值）。
    """
    snapshot(con, table, "import")
    all_name = storage.quote(table + storage.SOFTDEL_SUFFIX)
    con.execute(f"DELETE FROM {all_name}")
    if rows:
        qs = ", ".join(storage.quote(c) for c in columns)
        marks = ", ".join("?" * len(columns))
        con.executemany(f"INSERT INTO {all_name} ({qs}) VALUES ({marks})", rows)
    return len(rows)


def cleanup(con: sqlite3.Connection, days: int = 30) -> int:
    """删掉过期快照，返回删了几份。design 第 626 行：快照留 30 天。"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    old = [r[0] for r in con.execute(
        f"SELECT id FROM {META} WHERE created_at < ?", (cutoff,)
    )]
    for snap_id in old:
        con.execute(f"DROP TABLE IF EXISTS {storage.quote(SNAP_PREFIX + str(snap_id))}")
        con.execute(f"DELETE FROM {META} WHERE id = ?", (snap_id,))
    return len(old)


def drop_table(con: sqlite3.Connection, table: str) -> None:
    """删表。先落快照（这就是 design 说的"删表前"）。"""
    snapshot(con, table, "drop_table")
    for suffix in ("ins", "upd", "del"):
        con.execute(f"DROP TRIGGER IF EXISTS {storage.quote(f'{table}_{suffix}')}")
    con.execute(f"DROP VIEW IF EXISTS {storage.quote(table)}")
    con.execute(f"DROP TABLE IF EXISTS {storage.quote(table + storage.SOFTDEL_SUFFIX)}")
    for index in (table + "_alive",):
        con.execute(f"DROP INDEX IF EXISTS {storage.quote(index)}")
    # 中文映射跟着删——表没了，标注无处可挂
    con.execute(f"DELETE FROM {storage.META} WHERE tbl = ?", (table,))
    con.execute(f"DELETE FROM {storage.REL} WHERE from_table = ? OR to_table = ?",
                (table, table))


# ============================================================ 自测

if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    con = storage.connect(":memory:")
    ensure_meta(con)
    ok = True

    def check(label, passed, detail=""):
        global ok
        ok = ok and passed
        print(f"   {'✓' if passed else '✗'} {label}{'  ' + detail if detail else ''}")

    storage.create_table(
        con, "orders",
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, customer TEXT, count INTEGER DEFAULT 0",
        unique="name",
    )
    con.execute("INSERT INTO orders (name, customer, count) VALUES ('甲', '张三', 2)")
    con.execute("INSERT INTO orders (name, customer, count) VALUES ('乙', '李四', 0)")

    print("① 落一份快照")
    con.execute("BEGIN")
    s1 = snapshot(con, "orders", "import")
    con.execute("COMMIT")
    check("元信息记上了",
          con.execute(f"SELECT kind, rows FROM {META} WHERE id={s1}").fetchone() == ("import", 2))
    check("数据表建出来了",
          con.execute(f"SELECT count(*) FROM {SNAP_PREFIX}{s1}").fetchone()[0] == 2)

    print("\n② 破坏它：改数据 + 删一列")
    con.execute("UPDATE orders SET count = 99 WHERE name = '甲'")
    con.execute("DELETE FROM orders WHERE name = '乙'")
    storage.drop_column(con, "orders", "customer")
    check("customer 没了", "customer" not in storage.columns_of(con, "orders"))
    check("乙被软删", con.execute("SELECT count(*) FROM orders").fetchone()[0] == 1)

    print("\n③ 回滚")
    con.execute("BEGIN")
    rollback(con, s1)
    con.execute("COMMIT")
    cols_back = storage.columns_of(con, "orders")
    rows_back = con.execute("SELECT name, customer, count FROM orders").fetchall()
    print(f"   列：{cols_back}")
    print(f"   行：{sorted(rows_back)}")
    check("列回来了", "customer" in cols_back)
    check("数据回来了",
          sorted(rows_back) == sorted([("甲", "张三", 2), ("乙", "李四", 0)]))
    check("被软删的乙复活了", len(rows_back) == 2)

    print("\n④ 结构不只是列名——约束也得回来")
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='orders_all'").fetchone()[0]
    print(f"   {ddl}")
    check("NOT NULL 在", "NOT NULL" in ddl)
    check("默认值在", "DEFAULT 0" in ddl)
    check("主键在", "PRIMARY KEY" in ddl)

    print("\n⑤ 回滚本身也留了一份")
    kinds = [s["kind"] for s in list_snapshots(con, "orders")]
    check("多了一份 rollback", "rollback" in kinds, f"{kinds}")
    check("label 给界面用", list_snapshots(con, "orders")[0]["label"] == "回滚前")

    print("\n⑥ 覆盖导入")
    con.execute("BEGIN")
    n = replace_all(con, "orders", ["id", "name", "customer", "count"],
                    [(1, "丙", "王五", 0), (2, "丁", "赵六", 3), (3, "戊", "孙七", 1)])
    con.execute("COMMIT")
    rows = con.execute("SELECT name FROM orders").fetchall()
    print(f"   灌进去 {n} 行，现在有 {[r[0] for r in rows]}")
    check("旧数据被覆盖了", ("甲",) not in rows and ("乙",) not in rows)
    check("新数据都在", len(rows) == 3)
    check("覆盖前留了快照",
          list_snapshots(con, "orders")[0]["kind"] == "import")
    check("新行是活的（没被继承软删状态）",
          con.execute("SELECT count(*) FROM orders_all WHERE is_deleted = 0").fetchone()[0] == 3)

    print("\n⑦ 部分唯一索引在覆盖后仍然生效")
    try:
        con.execute("INSERT INTO orders (name, customer) VALUES ('丙', '重复')")
        check("重名该被挡", False, "居然插进去了")
    except sqlite3.IntegrityError:
        check("重名被挡", True)

    print("\n⑧ 预览挡掉系统列")
    cols, rows = preview(con, s1)
    print(f"   {cols} / {len(rows)} 行")
    check("is_deleted 不露面", "is_deleted" not in cols)
    check("拿到的是那一刻的数据", len(rows) == 2)
    snapshot_now = list_snapshots(con, "orders")[-1]
    check("最早的快照是那次 import", snapshot_now["id"] == s1)

    print("\n⑨ 删表")
    con.execute("BEGIN")
    drop_table(con, "orders")
    con.execute("COMMIT")
    check("表没了", "orders" not in storage.list_tables(con))
    check("底表也没了", con.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='orders_all'").fetchone()[0] == 0)
    check("中文映射跟着删了", con.execute(
        f"SELECT count(*) FROM {storage.META} WHERE tbl='orders'").fetchone()[0] == 0)
    check("但快照还在（这就是删表前的退路）",
          len(list_snapshots(con, "orders")) >= 3)

    print("\n⑩ 30 天清理")
    con.execute(f"UPDATE {META} SET created_at = '2000-01-01T00:00:00'")
    n = cleanup(con, days=30)
    check("删掉了过期的", n > 0, f"删了 {n} 份")
    # 用 GLOB 不用 LIKE：LIKE 里的下划线是通配符，会把 `_gx_snapshot`
    # （元信息表本身）也算进来——它第 9 位的 s 正好被通配符吃掉
    leftover = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name GLOB '_gx_snap_[0-9]*'"
    )]
    check("快照表也一起 DROP", leftover == [], f"{leftover}")
    check("元信息清空", con.execute(f"SELECT count(*) FROM {META}").fetchone()[0] == 0)

    con.close()
    print("\n" + ("全部通过。" if ok else "有失败项。"))
