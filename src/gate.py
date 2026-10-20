"""执行前闸门：**所有 SQL 出门前都过这里。**

以前安全检查卡在 `nl2sql` 里——只罩得住「模型写 SQL」这一条路，
服务自己拼的 UPDATE / DELETE 全绕过去了。闸门下沉到 `runner` 之后，
不管 SQL 从哪来，都要先过这一关。

## 三种意图

| 意图 | 放行 | 检查 |
|---|---|---|
| `read` | SELECT / UNION | 表名白名单 · 系统列 |
| `write` | INSERT / UPDATE / DELETE | 表名白名单 · 系统列 |
| `ddl`  | CREATE / DROP / ALTER | 只验语句类型（建表本来就没有"已有表"可查） |

`system=True` 是**特权旁路**：恢复已删行、清理回收站、快照回滚这些
操作本来就要碰底表和系统列。旁路只跳过表名和系统列，语句类型照查。

## 解析失败不再一律拒绝

早年的判据是「解析不了 = 不安全」，于是一个合法的复杂 SELECT
会被「无法解析」拦掉（真发生过）。现在解析失败时看关键字兜底：
开头对得上、且不含禁用词，就放行。**判据是「这条语句想干什么」，
不是「解析器认不认识它」。**
"""

import re

import sqlglot
from sqlglot import exp

import storage
from guard import SecurityError


class GateError(SecurityError):
    """SQL 被闸门拦下。

    **继承 `SecurityError`**：工具层和查询服务早就在按这个类型分流
    （安全拒绝不重试、不计入熔断）。闸门以前是独立异常，拒绝会一路
    冒到 api 的兜底 except，或者被归成 `unknown`——同一件事有两副面孔。
    """


# 每种意图允许的语句类型
ALLOWED = {
    "read": (exp.Select, exp.Union),
    "write": (exp.Insert, exp.Update, exp.Delete),
    "ddl": (exp.Create, exp.Drop, exp.Alter),
}

# 解析器不认时，按开头词兜底
HEAD_KEYWORDS = {
    "read": ("select", "with"),
    "write": ("insert", "update", "delete", "replace"),
    "ddl": ("create", "drop", "alter"),
}

# 读操作里出现这些词就不放行。它们出现在子查询里也可能改变数据
FORBIDDEN_IN_READ = (
    "insert", "update", "delete", "replace", "drop", "alter", "create",
    "attach", "detach", "pragma", "vacuum", "reindex",
)


def check(sql: str, purpose: str, con, system: bool = False):
    """过闸门。不合规抛 GateError。

    con 用来读表名白名单——闸门要知道"库里现在有哪些表"，
    而那是数据层的事实，不该在这里缓存一份。
    """
    if purpose not in ALLOWED:
        raise GateError(f"未知的执行意图：{purpose}")

    stmts = _parse(sql)
    if stmts is None:
        _check_by_keywords(sql, purpose)
        return

    if len(stmts) != 1:
        raise GateError("一次只能执行一条语句")

    stmt = stmts[0]

    if not isinstance(stmt, ALLOWED[purpose]):
        raise GateError(
            f"这次是「{purpose}」操作，但语句是 {type(stmt).__name__}"
        )

    if system:
        return

    if purpose in ("read", "write"):
        _check_tables(stmt, con)

    # 系统列：读和写都不许直接碰。写操作里的 INSERT 带列名，
    # UPDATE 带赋值目标；DELETE 不涉及列
    if purpose == "read" or isinstance(stmt, (exp.Update, exp.Insert)):
        bad = {
            c.name for c in stmt.find_all(exp.Column)
            if c.name.lower() in storage.SYSTEM_COLS
        }
        if bad:
            raise GateError(f"这些是系统列，不能直接读写：{sorted(bad)}")


def _parse(sql: str):
    """解析成语句列表。解析器不认识时返回 None——交给关键字兜底。"""
    try:
        return [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except Exception:
        return None


def _check_tables(stmt, con):
    """表名必须在数据源里。这是为了**拦住绕过视图直接打底表**——
    `orders_all` 是物理表，SQLite 不会替你拦，闸门要拦。

    **比较不区分大小写。** SQLite 的表名本来就不区分：`SELECT * FROM
    DEVICES` 和 `devices` 是同一条语句。白名单按原样比较的话，模型
    把表名写成大写就会被"表不在数据源里"拦掉——防的不是越权，
    是误伤。
    """
    known = {t.lower() for t in storage.list_tables(con)}
    ctes = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    used = {
        t.name for t in stmt.find_all(exp.Table)
        if t.name and t.name.lower() not in ctes
    }
    unknown = {t for t in used if t.lower() not in known}
    if unknown:
        raise GateError(
            f"这些表不在数据源里：{sorted(unknown)}。可用的有：{sorted(known)}"
        )


def _check_by_keywords(sql: str, purpose: str):
    """解析失败时的兜底：看开头词和禁用词。"""
    head = _strip_comments(sql).strip().lower()
    first = head.split(None, 1)[0] if head else ""
    if first not in HEAD_KEYWORDS[purpose]:
        raise GateError(
            f"无法解析，且不像「{purpose}」操作（开头是「{first[:20]}」）"
        )
    if purpose == "read":
        for word in FORBIDDEN_IN_READ:
            if re.search(rf"\b{word}\b", head):
                raise GateError(f"读操作里出现了「{word}」")


def _strip_comments(sql: str) -> str:
    """去掉开头的注释，让关键字检查看得到真正的第一个词。"""
    s = sql
    while True:
        stripped = s.lstrip()
        if stripped.startswith("--"):
            nl = stripped.find("\n")
            s = stripped[nl + 1:] if nl >= 0 else ""
            continue
        if stripped.startswith("/*"):
            end = stripped.find("*/")
            s = stripped[end + 2:] if end >= 0 else ""
            continue
        return stripped
