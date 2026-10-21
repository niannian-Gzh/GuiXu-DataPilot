"""数据层：归墟面对的世界。

只管「存取」与「理解结构」，**不含业务规则**（那在 services）。
对应 design.md 数据层一至七节，一处实现。

## 三层名字，只有一个约定

    外面认识的：  orders           ← 视图。services、模型写的 SQL、报表都只见它
    内部那一半：  orders_all       ← 底表。真数据在这，带 is_deleted

**露出给外面的名字必须是安全的那张。** 反过来（底表叫 orders、
视图叫 orders_view）就全完了——任何一处顺手写 `orders`
都会绕过软删隔离，而且不报错。

知道 `_all` 的只有三处：建表改结构、垃圾桶的旁路读、视图定义本身。
它们本来就是"特殊"的地方。

## 软删除为什么是视图，不是"改写 SQL"

隔离要的是**绕不过去**。改写依赖"没有路径绕过闸门"，那个前提
会随时间腐坏。视图挂在数据库上，绕不过。

代价是结构变更变复杂了（视图和触发器要跟着重建），
换来的是"任何一条 DELETE 都自动是软删"。

## 系统表

`_gx_` 前缀 = 内部，不出现在数据库概览、给模型的表定义、垃圾桶、导出里。
**枚举表一律走 `list_tables()`**——别处自己查 sqlite_master 迟早会漏。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# 系统列：不进视图，只能由底表的旁路读改（恢复 / 清理）
#
# deleted_at 是**垃圾桶要的**：design 交互层要求每行显示
# "删除时间 · 剩余 N 天"，而倒计时得有个起点。没有它，7 天清理
# 也无从判断——`is_deleted = 1` 只说明"删了"，不说明"多久了"。
SYSTEM_COLS = frozenset({"is_deleted", "deleted_at"})
# 系统表前缀：meta / 快照 / 审计……都不露面。加新的系统表沿用这个前缀
SYSTEM_PREFIX = "_gx_"
# 软删除底表的后缀。外面认识的是它的配套视图
SOFTDEL_SUFFIX = "_all"

META = "_gx_meta"          # 表中文名 + 列的中文说明
REL = "_gx_relation"       # 字段 ↔ 字段的逻辑关联
AUDIT = "_gx_audit"        # 业务凭据：谁、何时、改了什么


# ============================================================ 连接

def connect(path: str | Path) -> sqlite3.Connection:
    """开库。

    `isolation_level=None` 是**故意的**：关掉 Python 那套隐式事务管理，
    由调用方自己 BEGIN/COMMIT。理由是我们有"落快照 + 改结构"这类
    必须整体成败的多步操作，隐式提交会在中间插一脚。
    """
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    ensure_meta(con)
    # 快照表也在"库的完整形状"里。以前它只在 snapshot 自己的自测里建过，
    # 于是全新库第一次删表/删列/看版本历史就报 no such table——而开发机上
    # 那张表是历史运行留下的，谁都没发现。延迟导入是为了避开
    # storage → snapshot → storage 的模块级循环。
    from snapshot import ensure_meta as ensure_snapshot_meta
    ensure_snapshot_meta(con)
    # 文档库的两张系统表同理：新库第一次打开文档库页时不该是 500
    from rag import ensure_meta as ensure_rag_meta
    ensure_rag_meta(con)
    return con


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def columns_of(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({quote(table)})")]


def physical_table(con: sqlite3.Connection, table: str) -> str:
    """业务表实际存数据的表名。

    受软删保护的表，数据在 `xxx_all`（视图只投影活着的行）；用户绕过
    系统建的裸表没有这一层，数据就在它自己身上。**所有"要碰底表"的
    地方都该走这里**，不要自己拼 `_all`——没有主键的裸表不会被
    `repair()` 补保护，拼出来就是一张不存在的表。
    """
    all_name = table + SOFTDEL_SUFFIX
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (all_name,),
    ).fetchone()
    return all_name if exists else table


def has_soft_delete(con: sqlite3.Connection, table: str) -> bool:
    """这张表有没有软删底表。裸表只可能是"没有"。"""
    return physical_table(con, table) != table


def pk_of(con: sqlite3.Connection, table: str) -> str | None:
    """找主键列名。没有就返回 None，**不要退回 rowid**。

    rowid 在底表上有，但视图只投影底表的列——它进不了视图，
    触发器里的 `OLD.rowid` 会直接报 no such column。
    宁可当场说不能办，别给一个坏的。
    """
    for row in con.execute(f"PRAGMA table_info({quote(table)})"):
        if row[5]:              # 第 6 列是 pk 序号，>0 就是主键
            return row[1]
    return None


# ============================================================ 枚举

def list_tables(con: sqlite3.Connection) -> list[str]:
    """库里有哪些【业务表】。

    **唯一该被用来"枚举表"的入口**——数据库概览、给模型的表定义、
    垃圾桶、导出，全都调它。

    有个反直觉的地方，所以这个函数非有不可：**受保护的业务表，
    在 sqlite_master 里是 `view` 不是 `table`**。直查 type='table'
    会一个业务表都捞不到，只捞到底表。

    还有一类要收：用户绕过系统、自己 CREATE TABLE 建的。它没有
    软删除保护，但它就是业务表，得能被发现。
    """
    rows = con.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
        "ORDER BY name"
    ).fetchall()
    out = []
    for name, kind in rows:
        if name.startswith(SYSTEM_PREFIX) or name.startswith("sqlite_"):
            continue
        if kind == "view" or not name.endswith(SOFTDEL_SUFFIX):
            out.append(name)
    return out


# ============================================================ 建表 / 改结构

def _split_defs(coldefs: str) -> list[str]:
    """把 "a INT, b TEXT" 切成 ["a INT", "b TEXT"]。

    只按逗号切——列定义里不该出现逗号（默认值里的逗号要自己加括号，
    这是 SQLite 建表语法本来就有的限制，不是这里引入的）。
    """
    return [p for p in (part.strip() for part in coldefs.split(",")) if p]


def create_table(
    con: sqlite3.Connection,
    name: str,
    coldefs: str,
    unique: tuple | list = (),
    pk: str = "id",
) -> None:
    """建一张受软删保护的表。

    `coldefs` 是业务列定义串（不含 is_deleted）：
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT"
    `unique` 是"哪几列合起来不能重复"，单列写字符串即可：
        unique="name"    或    unique=[("owner", "name")]

    **不要在这两处写 UNIQUE**——见 `create_unique()` 的说明。
    主键是硬要求，软删除靠它定位行，建表时就卡住。
    """
    all_name = f"{name}{SOFTDEL_SUFFIX}"
    cols = [_split_defs(d)[0].split()[0].strip('"`[]') for d in _split_defs(coldefs)]
    if pk not in cols:
        raise ValueError(f"建表必须有主键列，{pk!r} 不在 {cols} 里")

    con.execute(
        f"CREATE TABLE {quote(all_name)} ("
        f"{coldefs}, is_deleted INTEGER NOT NULL DEFAULT 0, deleted_at TEXT)"
    )
    con.execute(
        f"CREATE INDEX {quote(name + '_alive')} "
        f"ON {quote(all_name)} (is_deleted)"
    )
    for spec in (unique,) if isinstance(unique, str) else unique:
        create_unique(con, name, spec)
    rebuild_access(con, name, cols, pk)


def create_unique(con: sqlite3.Connection, table: str, columns) -> None:
    """唯一约束——**部分索引**，只看活着的行。

    这条不能省。普通 UNIQUE 会把软删的行也算进去，于是：

        插入「项目A」→ 删掉它（软删，行还在）→ 再插入「项目A」
        → UNIQUE constraint failed

    用户会莫名其妙：明明删了，怎么还说重复？加上 `WHERE is_deleted = 0`，
    只有活着的行参与判断，已删的不占名字。
    """
    cols = [columns] if isinstance(columns, str) else list(columns)
    idx = f"{table}_uniq_" + "_".join(cols)
    joined = ", ".join(quote(c) for c in cols)
    con.execute(
        f"CREATE UNIQUE INDEX {quote(idx)} "
        f"ON {quote(table + SOFTDEL_SUFFIX)} ({joined}) WHERE is_deleted = 0"
    )


def uniques_of(con: sqlite3.Connection, table: str) -> list[list[str]]:
    """读唯一约束。模型得知道哪些列不能重复，不然它会靠碰壁学习。

    **先 fetchall 再循环。** 直接 `for row in con.execute(...)` 然后在
    循环体里再 `con.execute(...)`，内层会重置外层游标，外层静默中断——
    结果是"索引明明在、这里却读出来空"，而且不报错。
    """
    indexes = con.execute(
        f"PRAGMA index_list({quote(physical_table(con, table))})"
    ).fetchall()
    out = []
    for row in indexes:
        # index_list: (seq, name, unique, origin, partial)
        if not row[2]:
            continue
        cols = [r[2] for r in con.execute(f"PRAGMA index_info({quote(row[1])})")]
        if cols:
            out.append(cols)
    return out


def rebuild_access(
    con: sqlite3.Connection,
    name: str,
    cols: list[str],
    pk: str,
) -> None:
    """视图 + 三个 INSTEAD OF 触发器，一起重建。

    **视图是显式列，不是 `SELECT *`。** `*` 有个好处——加列时自动跟上，
    但它会把 `is_deleted` 一起带出去，那是系统列，不该给模型和用户看见。
    藏住系统列和自动跟列只能选一个，选了前者，所以加列时视图也得重建。

    顺序不能乱：触发器引用视图，先拆触发器。
    """
    view, all_name = quote(name), quote(f"{name}{SOFTDEL_SUFFIX}")

    for suffix in ("ins", "upd", "del"):
        con.execute(f"DROP TRIGGER IF EXISTS {quote(f'{name}_{suffix}')}")
    con.execute(f"DROP VIEW IF EXISTS {view}")

    biz = [c for c in cols if c not in SYSTEM_COLS]
    if not biz:
        raise ValueError(f"{name} 没有业务列")
    quoted = [quote(c) for c in biz]

    con.execute(
        f"CREATE VIEW {view} AS SELECT {', '.join(quoted)} "
        f"FROM {all_name} WHERE is_deleted = 0"
    )

    # **有默认值的列要用 COALESCE 兜一下。**
    # 触发器的列列表是显式的，`INSERT INTO 视图 (只给一部分列)` 时，
    # 没给的列在 NEW 里是 NULL——如果原样传给底表，底表的 DEFAULT
    # 就永远轮不到生效，NOT NULL 会直接失败。
    defaults = {
        r[1]: r[4] for r in con.execute(f"PRAGMA table_info({all_name})")
        if r[4] is not None and r[1] not in SYSTEM_COLS
    }
    new_vals = ", ".join(
        f"COALESCE(NEW.{q}, {defaults[c]})" if c in defaults else f"NEW.{q}"
        for c, q in zip(biz, quoted)
    )
    assignments = ", ".join(f"{q} = NEW.{q}" for q in quoted)

    # 增：写底表，is_deleted 强制为 0
    con.execute(
        f"CREATE TRIGGER {quote(f'{name}_ins')} INSTEAD OF INSERT ON {view} BEGIN "
        f"INSERT INTO {all_name} ({', '.join(quoted)}, is_deleted) "
        f"VALUES ({new_vals}, 0); END"
    )
    # 改：只改业务列。is_deleted 不在 assignments 里——否则用户能借
    # UPDATE 手工"复活"或"伪造删除"，隔离就白做了。
    # （其实外面连这个列都看不见，写这条 SQL 会 no such column。）
    con.execute(
        f"CREATE TRIGGER {quote(f'{name}_upd')} INSTEAD OF UPDATE ON {view} BEGIN "
        f"UPDATE {all_name} SET {assignments} "
        f"WHERE {quote(pk)} = OLD.{quote(pk)}; END"
    )
    # 删：不是 DELETE，是打个标记。**时间一起记**——垃圾桶要显示
    # "剩余 N 天"，那个倒计时得有个起点。（localtime：跟项目别处一致，
    # 库里存的一律是本地时间，不做时区转换。）
    con.execute(
        f"CREATE TRIGGER {quote(f'{name}_del')} INSTEAD OF DELETE ON {view} BEGIN "
        f"UPDATE {all_name} SET is_deleted = 1, "
        f"deleted_at = datetime('now', 'localtime') "
        f"WHERE {quote(pk)} = OLD.{quote(pk)}; END"
    )


def add_column(con: sqlite3.Connection, name: str, coldef: str, pk: str = "id") -> None:
    """加列：ALTER 打底表，视图和触发器跟上。一个事务里的多条 DDL。"""
    con.execute(f"ALTER TABLE {quote(f'{name}{SOFTDEL_SUFFIX}')} ADD COLUMN {coldef}")
    rebuild_access(con, name, columns_of(con, f"{name}{SOFTDEL_SUFFIX}"), pk)


def drop_column(con: sqlite3.Connection, name: str, col: str, pk: str = "id") -> None:
    """删列。

    **必须先拆触发器与视图**——加列和删列在这里不对称：加列时触发器
    不认识新列，不碍事；删列时它认识旧列（`NEW.<col>`），
    SQLite 会因此**拒绝**这条 ALTER。

    改列类型没有——SQLite 不支持 ALTER COLUMN，只能建新表拷数据换名字。
    那条路要连数据一起搬，归 snapshot.py 管。
    """
    for suffix in ("ins", "upd", "del"):
        con.execute(f"DROP TRIGGER IF EXISTS {quote(f'{name}_{suffix}')}")
    con.execute(f"DROP VIEW IF EXISTS {quote(name)}")
    con.execute(
        f"ALTER TABLE {quote(f'{name}{SOFTDEL_SUFFIX}')} DROP COLUMN {quote(col)}"
    )
    rebuild_access(con, name, columns_of(con, f"{name}{SOFTDEL_SUFFIX}"), pk)


def change_column_type(
    con: sqlite3.Connection, name: str, col: str, new_type: str, pk: str = "id"
) -> None:
    """改列类型。SQLite 没有 `ALTER COLUMN`，只能重建表。

    步骤：拆视图和触发器 → 建新表（换类型）→ 拷数据 → 删旧表 →
    换名 → 重建视图和触发器。**整件事必须在一个事务里**，
    不然中途失败会留下一张半成品表。

    **调用方必须先落快照**——这一步连数据一起搬，回滚要连数据回滚
    （design 数据层第五节）。

    类型替换走正则而不是重建 DDL：原建表语句里有主键、NOT NULL、
    默认值、唯一约束，重建时一项一项拼太容易漏；只把那一列的类型
    换掉，其余原样保留。
    """
    import re

    all_name = name + SOFTDEL_SUFFIX
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (all_name,)
    ).fetchone()
    if row is None:
        raise ValueError(f"{name} 不存在")
    ddl = row[0]

    # 只替换目标列的类型——`"col" TYPE` 或 `col TYPE`
    pattern = re.compile(
        rf'((?:"{re.escape(col)}"|{re.escape(col)})\s+)([A-Za-z]+(?:\([^)]*\))?)',
        re.IGNORECASE,
    )
    new_ddl, n = pattern.subn(rf"\g<1>{new_type}", ddl, count=1)
    if n == 0:
        raise ValueError(f"在建表语句里找不到列 {col}")
    new_ddl = new_ddl.replace(f'"{all_name}"', f'"{all_name}_new"', 1)
    if f"{all_name}_new" not in new_ddl:          # 表名没加引号的写法
        new_ddl = new_ddl.replace(all_name, f"{all_name}_new", 1)

    cols = [c for c in columns_of(con, all_name)]
    joined = ", ".join(quote(c) for c in cols)

    # **索引要另存**——CREATE TABLE 的 DDL 里没有它们，而 DROP TABLE
    # 会连带删掉。不存的话，重建出来的表会丢掉唯一约束，而且不报错。
    index_sql = [
        r[0] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
            "AND sql IS NOT NULL", (all_name,)
        )
    ]

    con.execute(new_ddl)
    con.execute(
        f"INSERT INTO {quote(all_name + '_new')} ({joined}) "
        f"SELECT {joined} FROM {quote(all_name)}"
    )
    for suffix in ("ins", "upd", "del"):
        con.execute(f"DROP TRIGGER IF EXISTS {quote(f'{name}_{suffix}')}")
    con.execute(f"DROP VIEW IF EXISTS {quote(name)}")
    con.execute(f"DROP TABLE {quote(all_name)}")
    con.execute(f"ALTER TABLE {quote(all_name + '_new')} RENAME TO {quote(all_name)}")

    for sql in index_sql:                              # 索引按原名重建
        con.execute(sql.replace(all_name, all_name))   # 名字里带的就是它，原样执行

    con.execute(
        f"CREATE INDEX IF NOT EXISTS {quote(name + '_alive')} "
        f"ON {quote(all_name)} (is_deleted)"
    )
    rebuild_access(con, name, columns_of(con, all_name), pk_of(con, all_name))


def repair(con: sqlite3.Connection) -> dict:
    """把没保护的业务表补齐。返回 {fixed, skipped}。由刷新按钮触发。

    谁会绕过系统在库里建表？拿 sqlite3 命令行开库的人。概率低，
    但一旦发生，**那张表上的"删"是真删**——同一个字，两套行为。

    ① 裸表：`foo` 是真表，没 is_deleted 也没视图
       → 先**改名**（foo 这名字得让给视图），再加列、建视图和触发器
    ② 孤儿底表：`foo_all` 在、视图没了（建到一半崩了）
    ③ 正常：什么都不做

    **没主键的不补**，进 skipped——硬补出来的东西会在删除时炸，
    而刷新还显示"已补齐"。
    """
    fixed, skipped = [], []
    tables = [
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]

    for name in tables:
        if name.startswith(SYSTEM_PREFIX) or name.startswith("sqlite_"):
            continue

        if name.endswith(SOFTDEL_SUFFIX):
            base = name[: -len(SOFTDEL_SUFFIX)]
            if con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = ?", (base,)
            ).fetchone():
                continue
            pk = pk_of(con, name)
            if pk is None:
                skipped.append(f"{base}（没有主键，没法定位行）")
                continue
            rebuild_access(con, base, columns_of(con, name), pk)
            fixed.append(f"{base}（补视图与触发器）")

        else:
            pk = pk_of(con, name)
            if pk is None:
                skipped.append(f"{name}（没有主键，没法定位行）")
                continue
            base = name
            con.execute(f"ALTER TABLE {quote(base)} RENAME TO {quote(base + SOFTDEL_SUFFIX)}")
            con.execute(
                f"ALTER TABLE {quote(base + SOFTDEL_SUFFIX)} "
                f"ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
            )
            con.execute(
                f"ALTER TABLE {quote(base + SOFTDEL_SUFFIX)} ADD COLUMN deleted_at TEXT"
            )
            con.execute(
                f"CREATE INDEX {quote(base + '_alive')} "
                f"ON {quote(base + SOFTDEL_SUFFIX)} (is_deleted)"
            )
            rebuild_access(
                con, base, columns_of(con, base + SOFTDEL_SUFFIX),
                pk_of(con, base + SOFTDEL_SUFFIX),
            )
            fixed.append(f"{base}（裸表 → 补上软删保护）")

    return {"fixed": fixed, "skipped": skipped}


# ============================================================ 表定义

def ensure_meta(con: sqlite3.Connection) -> None:
    """建三张系统表。幂等，每次开库都调它。

    **分三张不是一张**：表中文名和列说明是"一段话"，关系是
    "四个坐标"（本端表.列 ↔ 对端表.列 + 基数），审计是"一条流水"。
    硬塞进一张「kind / 谁 / 什么 / 文本」的表里，结构和审计都只能
    压成 JSON 字符串——那就等于把结构又还给了文本。

    审计进库而不是追加文件：**它要和改库在同一个事务里**。
    改成功但审计写失败 = 没账；审计写了但库没改 = 假账。
    """
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {META} ("
        "  tbl  TEXT NOT NULL,"
        "  col  TEXT NOT NULL,"          # 空串表示这一行讲的是表本身
        "  note TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (tbl, col))"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {REL} ("
        "  from_table TEXT NOT NULL, from_column TEXT NOT NULL,"
        "  to_table   TEXT NOT NULL, to_column   TEXT NOT NULL,"
        "  cardinality TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (from_table, from_column, to_table, to_column))"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {AUDIT} ("
        "  id         INTEGER PRIMARY KEY,"
        "  at         TEXT NOT NULL,"
        "  action     TEXT NOT NULL,"
        "  trace_id   TEXT,"
        "  user_input TEXT,"
        "  tbl        TEXT,"
        "  detail     TEXT)"             # 改动明细 / 影响行数，JSON
    )


def structure_of(con: sqlite3.Connection, table: str) -> list[dict]:
    """结构：库原生的事实。表定义里唯一不可编的部分。

    走底表而不是视图——视图会把 is_deleted 藏掉，而这里要的是
    "库里到底有哪些列"。

    PRAGMA table_info 返回 (cid, name, type, notnull, dflt_value, pk)。
    """
    out = []
    for _cid, name, type_, notnull, default, pk in con.execute(
        f"PRAGMA table_info({quote(physical_table(con, table))})"
    ):
        if name in SYSTEM_COLS:
            continue
        out.append({
            "name": name,
            "type": type_ or "",        # SQLite 允许无类型列
            # 主键一律算必填：INTEGER PRIMARY KEY 是 rowid 的别名，
            # PRAGMA 对它报 notnull=0，但"主键可为空"是句废话
            "nullable": (not notnull) and not pk,
            "default": default,
            "pk": bool(pk),
        })
    return out


def set_note(con: sqlite3.Connection, table: str, col: str, note: str) -> None:
    """标一条中文。`col` 给空串 = 标表的中文名。"""
    con.execute(
        f"INSERT INTO {META} (tbl, col, note) VALUES (?, ?, ?) "
        f"ON CONFLICT (tbl, col) DO UPDATE SET note = excluded.note",
        (table, col, note),
    )


def _notes(con: sqlite3.Connection) -> dict[tuple[str, str], str]:
    return {(r[0], r[1]): r[2] for r in con.execute(f"SELECT tbl, col, note FROM {META}")}


def describe(con: sqlite3.Connection, table: str) -> dict:
    """表定义 = 结构（库） + 语义（meta）。合成出来，不落盘。"""
    notes = _notes(con)
    cols = structure_of(con, table)
    for c in cols:
        c["note"] = notes.get((table, c["name"]), "")
    uniq = {tuple(u) for u in uniques_of(con, table)}
    for c in cols:
        c["unique"] = any(u == (c["name"],) for u in uniq)
    return {
        "table": table,
        "note": notes.get((table, ""), ""),
        "columns": cols,
        "relations": [
            {"from_column": r[0], "to_table": r[1], "to_column": r[2], "cardinality": r[3]}
            for r in con.execute(
                f"SELECT from_column, to_table, to_column, cardinality FROM {REL} "
                f"WHERE from_table = ?", (table,)
            )
        ],
    }


# ============================================================ 关系

def add_relation(
    con: sqlite3.Connection,
    from_table: str, from_column: str,
    to_table: str, to_column: str,
    cardinality: str = "",
) -> None:
    """加一条逻辑关联。

    **两端必须真实存在。** 不校验的话，用户填了"流水表.x ↔ 客户表.y"
    而客户表根本不存在，这条关系是假的，还会**误导模型去 JOIN 一张
    不存在的表**——报出来的错还很难查。
    """
    for tbl, col in ((from_table, from_column), (to_table, to_column)):
        if tbl not in list_tables(con):
            raise ValueError(f"表不存在：{tbl}")
        if col not in columns_of(con, physical_table(con, tbl)):
            raise ValueError(f"列不存在：{tbl}.{col}")
    if cardinality not in ("", "1:N", "N:1", "1:1", "M:N"):
        raise ValueError(f"基数只能是 1:N / N:1 / 1:1 / M:N / 空，收到 {cardinality!r}")

    con.execute(
        f"INSERT INTO {REL} VALUES (?, ?, ?, ?, ?) "
        f"ON CONFLICT (from_table, from_column, to_table, to_column) "
        f"DO UPDATE SET cardinality = excluded.cardinality",
        (from_table, from_column, to_table, to_column, cardinality),
    )


def drop_relation(
    con: sqlite3.Connection,
    from_table: str, from_column: str,
    to_table: str, to_column: str,
) -> int:
    cur = con.execute(
        f"DELETE FROM {REL} WHERE from_table = ? AND from_column = ? "
        f"AND to_table = ? AND to_column = ?",
        (from_table, from_column, to_table, to_column),
    )
    return cur.rowcount


# ============================================================ 给模型的文字

def render(con: sqlite3.Connection, tables: list[str] | None = None) -> str:
    """表定义压成一段文本，放进上下文。

    **给模型的是文本不是 JSON**：表定义每轮都在上下文里，所以每个
    字符都乘上对话轮数计价。实测同一张 6 列的表，JSON 是 301 token、
    文本 133——2.26 倍。差在 JSON 的键名每列重复一遍，一个新信息都不带。
    （要结构化的，走 `describe()`，那边是 dict。）

    **空库要明说，不能返回空字符串**：模型看到空白会自己编表名，
    而"库里没有表"本身就是它必须知道的一条事实。
    """
    if tables is None:
        tables = list_tables(con)
    if not tables:
        return "数据库当前没有任何表。用户还没有导入数据，也没有建过表。"

    blocks = []
    for name in tables:
        d = describe(con, name)
        head = f"{name}（{d['note']}）" if d["note"] else name
        lines = [f"[{head}]"]
        for c in d["columns"]:
            bits = [f"{c['name']:<14}", (c["type"] or "任意").upper()]
            bits.append("可空" if c["nullable"] else "必填")
            if c["pk"]:
                bits.append("主键")
            if c["unique"]:
                bits.append("唯一")
            if c["note"]:
                bits.append("· " + c["note"])
            lines.append("  ".join(bits))
        for r in d["relations"]:
            card = f"（{r['cardinality']}）" if r["cardinality"] else ""
            lines.append(f"  关系：{r['from_column']} ↔ {r['to_table']}.{r['to_column']}{card}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ============================================================ 唯一约束冲突

class Duplicate(Exception):
    """唯一约束冲突。带上哪张表哪些列——模型要知道改哪个字段。

    SQLite 原文是 `UNIQUE constraint failed: orders.name`，
    模型看得懂字面，但不知道该怎么办。转成这个再往上抛。
    """

    def __init__(self, table: str, columns: list[str]):
        self.table, self.columns = table, columns
        super().__init__(f"{table} 里 {', '.join(columns)} 已经有一条同样的记录了")


class ConstraintFailed(Exception):
    """别的约束失败（NOT NULL / CHECK / 类型）。跟"重复"分开报——
    `duplicate` 的意思是"换个值再试"，而 NOT NULL 失败是"少给了东西"，
    模型该知道的处置方式完全不同。"""

    def __init__(self, message: str):
        super().__init__(message)


def translate(con: sqlite3.Connection, err: sqlite3.IntegrityError) -> Exception:
    """把 sqlite3 的完整性错误翻译成模型看得懂的话。

    索引名是我们自己起的（`{表}_uniq_{列}` / `{表}_alive`），
    所以能从错误信息里把表和列还原出来。
    """
    text = str(err)
    if "UNIQUE constraint failed" not in text:
        return ConstraintFailed(text)
    target = text.split(":", 1)[-1].strip()          # "orders_all.name"
    for pair in target.split(","):
        parts = pair.strip().split(".")
        if len(parts) == 2:
            table = parts[0]
            if table.endswith(SOFTDEL_SUFFIX):
                table = table[: -len(SOFTDEL_SUFFIX)]
            return Duplicate(table, [parts[1]])
    return err


# ============================================================ 自测

if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    con = connect(":memory:")
    ok = True

    def check(label, passed, detail=""):
        global ok
        ok = ok and passed
        print(f"   {'✓' if passed else '✗'} {label}{'  ' + detail if detail else ''}")

    print("① 建表")
    create_table(
        con, "orders",
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT, count INTEGER DEFAULT 0",
        unique="name",
    )
    check("视图不带 is_deleted",
          "is_deleted" not in columns_of(con, "orders"), f"{columns_of(con, 'orders')}")
    check("list_tables 只给业务表", list_tables(con) == ["orders"], f"{list_tables(con)}")

    print("\n② 增删改走视图")
    con.execute("INSERT INTO orders (name, owner) VALUES ('甲', '张三')")
    con.execute("INSERT INTO orders (name, owner) VALUES ('乙', '李四')")
    con.execute("DELETE FROM orders WHERE name = '甲'")
    check("视图只剩活的", con.execute("SELECT count(*) FROM orders").fetchone()[0] == 1)
    check("底表两条都在", con.execute("SELECT count(*) FROM orders_all").fetchone()[0] == 2)

    print("\n③ 唯一约束——而且是「部分」唯一（关键的这条）")
    try:
        con.execute("INSERT INTO orders (name, owner) VALUES ('乙', '王五')")
        check("重复该被挡", False, "居然插进去了")
    except sqlite3.IntegrityError as e:
        dup = translate(con, e)
        check("被挡住了", isinstance(dup, Duplicate), str(dup))
    con.execute("INSERT INTO orders (name, owner) VALUES ('甲', '赵六')")
    check("软删掉的名字可以再用（普通 UNIQUE 会在这里失败）",
          con.execute("SELECT owner FROM orders WHERE name='甲'").fetchone() == ("赵六",))

    print("\n④ 表定义")
    set_note(con, "orders", "", "订单表")
    set_note(con, "orders", "name", "项目的正式全称，对外报送时用它")
    set_note(con, "orders", "owner", "负责这个项目的同事姓名")
    create_table(
        con, "order_items",
        "id INTEGER PRIMARY KEY, order_no TEXT NOT NULL, reason TEXT",
    )
    set_note(con, "order_items", "", "订单明细表")
    add_relation(con, "order_items", "order_no", "orders", "name", "1:N")
    text = render(con)
    print(text)
    check("中文映射进去了", "对外报送时用它" in text)
    check("唯一列标出来了", "唯一" in text)
    check("关系渲染了", "↔" in text and "1:N" in text)
    check("is_deleted 不出现", "is_deleted" not in text)

    print("\n⑤ 关系校验（假关系会误导模型去 JOIN 不存在的表）")
    for table, col, why in (("不存在表", "x", "表不存在"), ("orders", "不存在列", "列不存在")):
        try:
            add_relation(con, "order_items", "order_no", table, col)
            check(f"{why}该被拒", False, "居然加进去了")
        except ValueError as e:
            check(f"{why}被拒", True, str(e))

    print("\n⑥ 加列 / 删列")
    add_column(con, "orders", "priority TEXT")
    con.execute("INSERT INTO orders (name, owner, priority) VALUES ('丙', '孙七', '高')")
    check("加列后能写", con.execute(
        "SELECT priority FROM orders WHERE name='丙'").fetchone() == ("高",))
    drop_column(con, "orders", "priority")
    check("删列后视图同步", "priority" not in columns_of(con, "orders"))
    check("删列后还能写", (con.execute(
        "INSERT INTO orders (name, owner) VALUES ('丁', '周八')"),
        con.execute("SELECT count(*) FROM orders WHERE name='丁'").fetchone()[0])[1] == 1)

    print("\n⑦ 空库怎么说")
    empty = connect(":memory:")
    check("明说没有表，不是空白", "没有" in render(empty) and len(render(empty)) > 10)
    empty.close()

    print("\n⑧ 裸表补齐")
    con.execute("CREATE TABLE legacy (code TEXT PRIMARY KEY, memo TEXT)")
    con.execute("INSERT INTO legacy VALUES ('A-1', '遗留')")
    result = repair(con)
    check("认出来了", any("legacy" in f for f in result["fixed"]), f"{result}")
    check("数据没丢", con.execute("SELECT count(*) FROM legacy").fetchone()[0] == 1)
    con.execute("DELETE FROM legacy WHERE code = 'A-1'")
    check("补完就是软删了", con.execute("SELECT count(*) FROM legacy").fetchone()[0] == 0)
    check("幂等", repair(con) == {"fixed": [], "skipped": []}, f"{repair(con)}")

    print("\n⑨ 无主键的表不补")
    con.execute("CREATE TABLE noPk (a TEXT, b TEXT)")
    result = repair(con)
    check("进了 skipped", any("noPk" in s for s in result["skipped"]), f"{result}")
    check("原表没被动", con.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='noPk_all'").fetchone()[0] == 0)

    con.close()
    print("\n" + ("全部通过。" if ok else "有失败项。"))
