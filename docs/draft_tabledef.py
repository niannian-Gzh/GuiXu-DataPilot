"""表定义草案：结构从库里读，语义在库里标。

对应 design.md 数据层第二节——**真源在库里，分两半**：

    结构（列名 / 类型 / 必填 / 默认值 / 主键）  ← 库原生，直接读
    语义（表中文名 / 列的中文说明 / 逻辑关系）  ← meta 表，人标

一次写、之后全是读。没有硬编码，没有 JSON 文件，没有第二份。
（现状那三份——`db.describe` / `schema_meta.json` / `nl2sql.TABLE_SCHEMA`
——就是在替这个。）

## 两个设计点

**一、语义分两张表，不是一张。** 表中文名和列说明是"一段话"，
而关系是"四个坐标"（本端表.列 ↔ 对端表.列 + 基数）。硬塞进一张
「kind / 谁 / 什么 / 文本」的表里，关系那几列只能压成 JSON 字符串——
那就等于把结构又还给了文本。

**二、给 LLM 的不是 JSON，是紧凑文本。** 表定义每轮都在上下文里
（design 工具层：它不是工具，是上下文），所以每个字符都按
"乘上对话轮数"计价。

跑一遍看结论：
    python docs/draft-tabledef.py
"""

import sqlite3

META, REL = "_gx_meta", "_gx_relation"

# 系统表：meta / 快照 / 审计……都不该露面。加新的系统表时沿用这个前缀
SYSTEM_PREFIX = "_gx_"
# 软删除底表。外面认识的是它的配套视图（projects），它是内部那一半
SOFTDEL_SUFFIX = "_all"


def list_tables(conn: sqlite3.Connection) -> list[str]:
    """库里有哪些【业务表】。

    **唯一该被用来"枚举表"的入口**——数据库概览、给 LLM 的表定义、
    垃圾桶、导出，全都调它。别在别处自己查 sqlite_master：
    过滤规则一旦散开，将来加系统表（快照、审计）就会漏得到处都是。

    有个反直觉的地方，所以这个函数非有不可：**受保护的业务表，
    在 sqlite_master 里是 `view` 不是 `table`**。直查 type='table'
    会一个业务表都捞不到，只捞到底表。

    还有一类要收：用户绕过系统、自己 CREATE TABLE 建的表。
    它没有软删除保护（没有配套视图），但它就是业务表，得能被发现
    （design 数据字典页那条"发现库里冒出来的新表"）。
    """
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
        "ORDER BY name"
    ).fetchall()
    out = []
    for name, kind in rows:
        if name.startswith(SYSTEM_PREFIX) or name.startswith("sqlite_"):
            continue
        # 视图是外面认识的名字；表只有"不是底表"时才可能是业务表
        if kind == "view" or not name.endswith(SOFTDEL_SUFFIX):
            out.append(name)
    return out


def ensure_meta(conn: sqlite3.Connection) -> None:
    """建两张 meta 表。幂等——每次启动都该调它。"""
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {META} ("
        "  tbl  TEXT NOT NULL,"          # 表名
        "  col  TEXT NOT NULL,"          # 列名；空串表示这一行讲的是表本身
        "  note TEXT NOT NULL DEFAULT '',"
        "  PRIMARY KEY (tbl, col))"
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {REL} ("
        "  from_table TEXT NOT NULL, from_column TEXT NOT NULL,"
        "  to_table   TEXT NOT NULL, to_column   TEXT NOT NULL,"
        "  cardinality TEXT NOT NULL DEFAULT '',"   # '1:N' / 'M:N' / 空
        "  PRIMARY KEY (from_table, from_column, to_table, to_column))"
    )


def read_structure(conn: sqlite3.Connection, table: str) -> list[dict]:
    """结构：库原生的事实。这才是"表定义"里唯一不可编的部分。

    走底表（{table}_all）而不是视图——视图会把 is_deleted 藏掉，
    而这里要的就是"库里到底有哪些列"。

    PRAGMA table_info 返回 (cid, name, type, notnull, dflt_value, pk)。
    """
    rows = conn.execute(f'PRAGMA table_info("{table}_all")').fetchall()
    out = []
    for _cid, name, type_, notnull, default, pk in rows:
        if name == "is_deleted":        # 系统列，不进表定义
            continue
        out.append({
            "name": name,
            "type": type_ or "",       # SQLite 允许无类型列
            # 主键一律算必填：INTEGER PRIMARY KEY 是 rowid 的别名，
            # PRAGMA 对它报 notnull=0（技术上能插 NULL，插了自动生成），
            # 但语义上"主键可为空"是句废话，报给模型只会误导
            "nullable": (not notnull) and not pk,
            "default": default,
            "pk": bool(pk),
        })
    return out


# ---------------------------------------------------------------- 语义的读写

def set_note(conn, tbl: str, col: str, note: str) -> None:
    """标一条。col 给空串 = 标表的中文名。"""
    conn.execute(
        f"INSERT INTO {META} (tbl, col, note) VALUES (?, ?, ?) "
        f"ON CONFLICT (tbl, col) DO UPDATE SET note = excluded.note",
        (tbl, col, note),
    )


def _notes(conn) -> dict[tuple[str, str], str]:
    return {(r[0], r[1]): r[2] for r in conn.execute(f"SELECT tbl, col, note FROM {META}")}


def describe(conn: sqlite3.Connection, table: str) -> dict:
    """表定义 = 结构（库） + 语义（meta）。合成出来，不落盘。"""
    notes = _notes(conn)
    cols = read_structure(conn, table)
    for c in cols:
        c["note"] = notes.get((table, c["name"]), "")
    return {
        "table": table,
        "note": notes.get((table, ""), ""),
        "columns": cols,
        "relations": [
            {"from_column": r[0], "to_table": r[1], "to_column": r[2], "cardinality": r[3]}
            for r in conn.execute(
                f"SELECT from_column, to_table, to_column, cardinality FROM {REL} "
                f"WHERE from_table = ?", (table,)
            )
        ],
    }


# ---------------------------------------------------------------- 给 LLM 的文字

def render(conn: sqlite3.Connection, tables: list[str]) -> str:
    """把表定义压成一段文本，放进上下文。

    空库时返回一句明说——**不能是空字符串**：模型看到空白会自己编表名，
    而"库里没有表"本身就是一条它必须知道的事实。
    """
    if not tables:
        return "数据库当前没有任何表。用户还没有导入数据，也没有建过表。"

    blocks = []
    for name in tables:
        d = describe(conn, name)
        head = f"{name}（{d['note']}）" if d["note"] else name
        lines = [f"[{head}]"]
        for c in d["columns"]:
            bits = [f"  {c['name']:<14}", (c['type'] or '任意').upper()]
            bits.append("必填" if not c["nullable"] else "可空")
            if c["pk"]:
                bits.append("主键")
            if c["note"]:
                bits.append("· " + c["note"])
            lines.append("  ".join(bits))
        for r in d["relations"]:
            card = f"（{r['cardinality']}）" if r["cardinality"] else ""
            lines.append(
                f"  关系：{r['from_column']} ↔ {r['to_table']}.{r['to_column']}{card}"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    import sys

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

    # 手写两张等价于软删除草案的受保护表（底表 + 视图）
    for name, defs in (
        ("projects", "id INTEGER PRIMARY KEY, project_name TEXT NOT NULL, owner TEXT, review_count INTEGER DEFAULT 0"),
        ("reviews", "id INTEGER PRIMARY KEY, project_name TEXT NOT NULL, reason TEXT"),
    ):
        cols = [d.strip().split()[0] for d in defs.split(",")]
        conn.execute(f'CREATE TABLE "{name}_all" ({defs}, is_deleted INTEGER NOT NULL DEFAULT 0)')
        conn.execute(
            f'CREATE VIEW "{name}" AS SELECT {", ".join(cols)} '
            f'FROM "{name}_all" WHERE is_deleted = 0'
        )

    ensure_meta(conn)

    print("① 空库")
    text = render(conn, [])
    print(f"   {text}")
    check("空库有明说，不是空白", len(text) > 10 and "没有" in text)

    print("\n② 只标了结构，还没标中文")
    print(render(conn, ["projects"]))
    check("没标中文也能渲染（留空，不报错）", "owner" in render(conn, ["projects"]))

    print("\n③ 标上中文映射")
    set_note(conn, "projects", "", "项目表")
    set_note(conn, "projects", "project_name", "项目的正式全称，对外报送时用它")
    set_note(conn, "projects", "owner", "负责这个项目的同事姓名")
    set_note(conn, "projects", "review_count", "被上级打回的累计次数")
    set_note(conn, "reviews", "", "打回记录表")
    set_note(conn, "reviews", "reason", "打回时写的原因")
    conn.execute(
        f"INSERT INTO {REL} VALUES ('reviews', 'project_name', 'projects', 'project_name', '1:N')"
    )
    print(render(conn, ["projects", "reviews"]))
    full = render(conn, ["projects", "reviews"])
    check("列说明进去了", "对外报送时用它" in full)
    check("表中文名进去了", "项目表" in full)
    check("关系渲染出来了", "↔" in full and "1:N" in full)

    print("\n④ 改一条标注，覆盖而不是新增")
    set_note(conn, "projects", "owner", "改过的说法")
    n = conn.execute(f"SELECT count(*) FROM {META} WHERE tbl='projects' AND col='owner'").fetchone()[0]
    check("是 upsert，不是插了第二条", n == 1)
    check("取到的是新值", "改过的说法" in render(conn, ["projects"]))

    print("\n⑤ is_deleted 不出现在表定义里")
    check("系统列被挡在外面", "is_deleted" not in render(conn, ["projects"]))

    print("\n⑥ 加了列之后，不用重标")
    conn.execute('ALTER TABLE "projects_all" ADD COLUMN priority TEXT')
    after = render(conn, ["projects"])
    check("新列自动出现（结构是现读的）", "priority" in after)
    check("已标的中文没丢", "对外报送时用它" in after)

    print("\n⑦ 系统表不露面")
    tables = list_tables(conn)
    print(f"   list_tables → {tables}")
    check("只列出业务表", tables == ["projects", "reviews"], f"{tables}")
    check("meta 表被挡住", META not in tables and REL not in tables)
    check("软删除底表被挡住", "projects_all" not in tables)

    conn.close()
    print("\n" + ("全部通过。" if ok else "有失败项。"))
