"""软删除隔离草案：视图 + INSTEAD OF 触发器。

**唯一一条要记住的约定**：露在外面的名字（`projects`）必须是安全的那张。
底表叫 `projects_all`，视图叫 `projects`。反过来（底表叫 `projects`、
视图叫 `projects_view`）就全完了——任何一处顺手写 `projects`
都会绕过隔离，而且不报错。

## 视图为什么是显式列，而不是 SELECT *

`SELECT *` 有个好处：加列时视图自动跟上（定义文本都不用改，
`*` 是查询时才展开的）。但它会把 `is_deleted` 一起带出来——
那是系统列，不该给 LLM 和用户看见。

**两件事只能选一件。** 选"藏住系统列"，代价就是加列时视图也要重建。

## 所以结构变更长这样

    BEGIN;
      ALTER TABLE projects_all ADD COLUMN ...;
      DROP VIEW / DROP TRIGGER ×3;
      CREATE VIEW / CREATE TRIGGER ×3;
    COMMIT;

六条 DDL 一个事务。实测 DDL 可回滚，中途失败不会留下
"表加了列但视图没跟上"的残局。

跑一遍看结论：
    python docs/draft-softdelete.py
"""

import sqlite3

# 系统列：视图里不出现，只能由底表的旁路读改（恢复 / 清理）
SYSTEM_COLS = frozenset({"is_deleted"})

# 系统表前缀：meta / 快照 / 审计……都不该露面。（表定义草案里也有这一份，
# 落地时两处会并成同一个模块的常量）
SYSTEM_PREFIX = "_gx_"
# 软删除底表的后缀。外面认识的是它的配套视图（projects）
SOFTDEL_SUFFIX = "_all"


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """读当前列名。重建全靠它——列一变就得重来一遍。"""
    return [row[1] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")]


def _split_defs(coldefs: str) -> list[str]:
    """把 "a INT, b TEXT" 切成 ["a INT", "b TEXT"]。

    只按逗号切——列定义里不该出现逗号（默认值里的逗号要自己加括号，
    这是 SQLite 建表语法本来就有的限制，不是这里引入的）。
    """
    return [p for p in (part.strip() for part in coldefs.split(",")) if p]


def _col_name(coldef: str) -> str:
    return coldef.split()[0].strip('"`[]')


def _rebuild(conn: sqlite3.Connection, name: str, cols: list[str], pk: str) -> None:
    """视图 + 三个触发器，一起重建。

    顺序不能乱：触发器引用视图，所以先拆触发器。`DROP ... IF EXISTS`
    是为了让建表和后续重建走同一个函数。
    """
    view, all_name = _quote(name), _quote(f"{name}_all")

    for suffix in ("ins", "upd", "del"):
        conn.execute(f"DROP TRIGGER IF EXISTS {_quote(f'{name}_{suffix}')}")
    conn.execute(f"DROP VIEW IF EXISTS {view}")

    # 业务列：is_deleted 不在其中，于是它压根不出现在视图里
    biz = [c for c in cols if c not in SYSTEM_COLS]
    quoted = [_quote(c) for c in biz]

    conn.execute(
        f"CREATE VIEW {view} AS SELECT {', '.join(quoted)} "
        f"FROM {all_name} WHERE is_deleted = 0"
    )

    new_vals = ", ".join(f"NEW.{q}" for q in quoted)
    assignments = ", ".join(f"{q} = NEW.{q}" for q in quoted)

    # 增：写进底表，is_deleted 强制为 0
    conn.execute(
        f"CREATE TRIGGER {_quote(f'{name}_ins')} INSTEAD OF INSERT ON {view} BEGIN "
        f"INSERT INTO {all_name} ({', '.join(quoted)}, is_deleted) "
        f"VALUES ({new_vals}, 0); END"
    )
    # 改：只改业务列。is_deleted 不在 assignments 里——
    # 否则用户能借 UPDATE 手工"复活"或"伪造删除"，隔离就白做了
    conn.execute(
        f"CREATE TRIGGER {_quote(f'{name}_upd')} INSTEAD OF UPDATE ON {view} BEGIN "
        f"UPDATE {all_name} SET {assignments} "
        f"WHERE {_quote(pk)} = OLD.{_quote(pk)}; END"
    )
    # 删：不是 DELETE，是打个标记
    conn.execute(
        f"CREATE TRIGGER {_quote(f'{name}_del')} INSTEAD OF DELETE ON {view} BEGIN "
        f"UPDATE {all_name} SET is_deleted = 1 "
        f"WHERE {_quote(pk)} = OLD.{_quote(pk)}; END"
    )


def create_table(
    conn: sqlite3.Connection,
    name: str,
    coldefs: str,
    pk: str = "id",
) -> None:
    """建一张受软删保护的表。

    `coldefs` 是业务列定义串（不含 is_deleted），例如：
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT"

    主键是硬要求——软删除靠它定位行。建表时就卡住，
    总比等到刷新时才发现"这张表补不了"强。
    """
    all_name = _quote(f"{name}_all")
    cols = [_col_name(d) for d in _split_defs(coldefs)]
    if pk not in cols:
        raise ValueError(f"建表必须有主键列，{pk!r} 不在 {cols} 里")

    conn.execute(
        f"CREATE TABLE {all_name} ({coldefs}, is_deleted INTEGER NOT NULL DEFAULT 0)"
    )
    # 软删过滤每次都过这一列
    conn.execute(
        f"CREATE INDEX {_quote(name + '_alive')} ON {all_name} (is_deleted)"
    )
    _rebuild(conn, name, cols, pk)


def add_column(conn: sqlite3.Connection, name: str, coldef: str, pk: str = "id") -> None:
    """加列：ALTER 打底表，视图和触发器跟上。六条 DDL，一个事务。"""
    conn.execute(f"ALTER TABLE {_quote(f'{name}_all')} ADD COLUMN {coldef}")
    _rebuild(conn, name, _columns(conn, f"{name}_all"), pk)


def drop_column(conn: sqlite3.Connection, name: str, col: str, pk: str = "id") -> None:
    """删列。SQLite 3.35+ 才有 DROP COLUMN，且不能删主键、被索引的列等。

    **必须先拆触发器与视图**——加列和删列在这里不对称：
    加列时触发器不认识新列，不碍事；删列时它认识旧列
    （`NEW.<col>`），SQLite 会因此**拒绝**这条 ALTER。

    **改列类型这里没有**——SQLite 不支持 ALTER COLUMN，只能
    建新表 → 拷数据 → 换名字。那条路必须连数据一起搬，
    所以它归"整表快照"管（见 design.md 数据层第五节）。
    """
    for suffix in ("ins", "upd", "del"):
        conn.execute(f"DROP TRIGGER IF EXISTS {_quote(f'{name}_{suffix}')}")
    conn.execute(f"DROP VIEW IF EXISTS {_quote(name)}")
    conn.execute(f"ALTER TABLE {_quote(f'{name}_all')} DROP COLUMN {_quote(col)}")
    _rebuild(conn, name, _columns(conn, f"{name}_all"), pk)


def repair(conn: sqlite3.Connection) -> dict:
    """把没保护的业务表补齐。返回 {fixed: [...], skipped: [...]}。

    谁会用 SQL 在这库里建表？绕过系统的人（拿 sqlite3 命令行开库）。
    概率低，但一旦发生，**那张表上的"删"是真删**——同一个字，
    两套行为。所以发现就补上，别让两种语义混在库里。

    三种情况：
      ① 裸表：`foo` 是张真表，没有 is_deleted 也没有视图
      ② 孤儿底表：`foo_all` 在，视图 `foo` 没了（建到一半崩了）
      ③ 正常：什么都不做

    ① 要先**改名**——`foo` 这个名字得让给视图，因为外面认识的名字
    只能是视图。数据不动，位置不变，只是名字往后挪一格。

    **没主键的表不补**，进 skipped。软删除要一个能唯一定位行的列，
    它没有；硬补出来的东西会在删除时炸，而刷新还显示"已补齐"。
    """
    fixed: list[str] = []
    skipped: list[str] = []
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]

    for name in tables:
        if name.startswith(SYSTEM_PREFIX) or name.startswith("sqlite_"):
            continue

        if name.endswith(SOFTDEL_SUFFIX):
            base = name[: -len(SOFTDEL_SUFFIX)]
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = ?", (base,)
            ).fetchone()
            if exists:
                continue
            pk = _pk_of(conn, name)
            if pk is None:
                skipped.append(f"{base}（没有主键，没法定位行）")
                continue
            _rebuild(conn, base, _columns(conn, name), pk)
            fixed.append(f"{base}（补视图与触发器）")

        else:
            base = name
            pk = _pk_of(conn, name)
            if pk is None:
                skipped.append(f"{base}（没有主键，没法定位行）")
                continue
            conn.execute(
                f"ALTER TABLE {_quote(base)} RENAME TO {_quote(base + SOFTDEL_SUFFIX)}"
            )
            conn.execute(
                f"ALTER TABLE {_quote(base + SOFTDEL_SUFFIX)} "
                f"ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                f"CREATE INDEX {_quote(base + '_alive')} "
                f"ON {_quote(base + SOFTDEL_SUFFIX)} (is_deleted)"
            )
            _rebuild(conn, base, _columns(conn, base + SOFTDEL_SUFFIX), pk)
            fixed.append(f"{base}（裸表 → 补上软删保护）")

    return {"fixed": fixed, "skipped": skipped}


def _pk_of(conn: sqlite3.Connection, table: str) -> str | None:
    """找主键列名。手工建的表多半不叫 id，所以得现读。

    **没有主键就返回 None，不要退回 rowid。** rowid 在底表上有，
    但视图只投影底表的列——它进不了视图，触发器里的 `OLD.rowid`
    会直接报 `no such column`。试过了：repair 会"成功"，
    而那张表上的删除是坏的。**宁可当场说不能补，别给一个坏的。**
    """
    for row in conn.execute(f"PRAGMA table_info({_quote(table)})"):
        if row[5]:              # 第 6 列是 pk 序号，>0 就是主键
            return row[1]
    return None


# ---------------------------------------------------------------- 自测

def _self_test() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"   {'✓' if passed else '✗'} {label}{'  ' + detail if detail else ''}")

    print("① 建表")
    create_table(conn, "projects", "id INTEGER PRIMARY KEY, name TEXT, owner TEXT")
    objects = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'projects%' ORDER BY name"
        )
    )
    print(f"   建出来的：{objects}")
    check("视图不含 is_deleted", "is_deleted" not in _columns(conn, "projects"),
          f"视图列 = {_columns(conn, 'projects')}")

    print("\n② 增删改都走视图")
    conn.execute("INSERT INTO projects (name, owner) VALUES ('甲项目', '张三')")
    conn.execute("INSERT INTO projects (name, owner) VALUES ('乙项目', '李四')")
    conn.execute("UPDATE projects SET owner = '王五' WHERE name = '乙项目'")
    conn.execute("DELETE FROM projects WHERE name = '甲项目'")
    check("视图只剩未删的",
          conn.execute("SELECT name FROM projects").fetchall() == [("乙项目",)],
          f"{conn.execute('SELECT name, owner FROM projects').fetchall()}")
    check("底表里甲项目是被标记，不是没了",
          conn.execute("SELECT is_deleted FROM projects_all WHERE name='甲项目'").fetchone() == (1,))

    print("\n③ 加列")
    add_column(conn, "projects", "priority TEXT")
    check("新列出现在视图里", "priority" in _columns(conn, "projects"),
          f"{_columns(conn, 'projects')}")
    check("is_deleted 仍然藏着", "is_deleted" not in _columns(conn, "projects"))
    conn.execute("INSERT INTO projects (name, owner, priority) VALUES ('丙项目', '赵六', '高')")
    check("插入时新列保住了",
          conn.execute("SELECT priority FROM projects WHERE name='丙项目'").fetchone() == ("高",))
    conn.execute("UPDATE projects SET priority = '中' WHERE name = '丙项目'")
    check("更新新列也通",
          conn.execute("SELECT priority FROM projects WHERE name='丙项目'").fetchone() == ("中",))

    print("\n④ 外面碰不到 is_deleted")
    for sql, label in (
        ("UPDATE projects SET is_deleted = 1 WHERE name = '丙项目'", "伪删"),
        ("UPDATE projects SET is_deleted = 0 WHERE name = '甲项目'", "复活"),
    ):
        try:
            conn.execute(sql)
            check(f"{label}", False, "居然执行了 ✗")
        except sqlite3.OperationalError as e:
            check(f"{label}被拒", "no such column" in str(e), str(e))
    raw = dict(conn.execute("SELECT name, is_deleted FROM projects_all").fetchall())
    check("底表数据没被动过", raw["丙项目"] == 0 and raw["甲项目"] == 1, f"{raw}")
    check("视图行数没变", conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 2)

    print("\n⑤ 旁路读（垃圾桶）看得到已删的行")
    check("能捞出甲项目",
          conn.execute("SELECT name FROM projects_all WHERE is_deleted = 1").fetchall() == [("甲项目",)])

    print("\n⑥ 加列到一半失败")
    conn.execute("BEGIN")
    try:
        add_column(conn, "projects", "tmp TEXT")
        conn.execute("THIS IS NOT SQL")
        conn.execute("COMMIT")
        check("应该抛错", False)
    except sqlite3.OperationalError:
        conn.execute("ROLLBACK")
        cols = _columns(conn, "projects_all")
        trg = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        check("tmp 列被回滚", "tmp" not in cols)
        check("触发器没被拆", trg == 3, f"{trg} 个")
        check("视图还在且能用",
              conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 2)

    print("\n⑦ 补齐裸表（有人拿 sqlite3 在库里自己建的）")
    conn.execute("CREATE TABLE legacy (code TEXT PRIMARY KEY, memo TEXT)")
    conn.execute("INSERT INTO legacy VALUES ('A-1', '遗留数据')")
    conn.execute("INSERT INTO legacy VALUES ('A-2', '第二条')")
    result = repair(conn)
    print(f"   repair → {result}")
    check("识别出裸表", any("legacy" in d for d in result["fixed"]), f"{result}")
    check("没有跳过的", result["skipped"] == [])
    check("数据一条没丢",
          conn.execute("SELECT count(*) FROM legacy").fetchone()[0] == 2)
    conn.execute("DELETE FROM legacy WHERE code = 'A-1'")
    check("现在删是软删（视图里看不到了）",
          conn.execute("SELECT count(*) FROM legacy").fetchone()[0] == 1)
    check("底表里其实两条都还在",
          conn.execute("SELECT count(*) FROM legacy_all").fetchone()[0] == 2)
    del_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'legacy_del'"
    ).fetchone()[0]
    check("自动认出了主键（它不叫 id）", '"code"' in del_sql)

    print("\n⑧ 再刷一次，不重复处理")
    again = repair(conn)
    check("幂等", again["fixed"] == [] and again["skipped"] == [], f"{again}")

    print("\n⑨ 视图被弄丢了，能补回来")
    conn.execute("DROP VIEW legacy")
    result = repair(conn)
    check("认出孤儿底表并重建",
          any("legacy" in d for d in result["fixed"]), f"{result}")
    check("视图又能用了",
          conn.execute("SELECT count(*) FROM legacy").fetchone()[0] == 1)

    print("\n⑨′ 删列（加列和删列不对称，得单独测）")
    drop_column(conn, "projects", "priority")
    check("列没了", "priority" not in _columns(conn, "projects"),
          f"{_columns(conn, 'projects')}")
    conn.execute("INSERT INTO projects (name, owner) VALUES ('丁项目', '孙七')")
    check("删完还能插", conn.execute(
        "SELECT count(*) FROM projects WHERE name = '丁项目'").fetchone()[0] == 1)
    conn.execute("DELETE FROM projects WHERE name = '丁项目'")
    check("软删照常工作", conn.execute(
        "SELECT is_deleted FROM projects_all WHERE name = '丁项目'").fetchone() == (1,))

    print("\n⑩ 没有主键的表：不补，报出来")
    conn.execute("CREATE TABLE noPk (a TEXT, b TEXT)")
    conn.execute("INSERT INTO noPk VALUES ('x', 'y')")
    result = repair(conn)
    check("进了 skipped", any("noPk" in d for d in result["skipped"]), f"{result}")
    check("没被误补", result["fixed"] == [])
    check("原表原封不动",
          conn.execute("SELECT count(*) FROM noPk").fetchone()[0] == 1)
    check("没长出 noPk_all",
          conn.execute(
              "SELECT count(*) FROM sqlite_master WHERE name = 'noPk_all'"
          ).fetchone()[0] == 0)

    conn.close()
    print("\n" + ("全部通过。" if ok else "有失败项。"))


if __name__ == "__main__":
    _self_test()
