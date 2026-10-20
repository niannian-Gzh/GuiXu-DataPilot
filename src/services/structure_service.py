"""表结构变更：建表 / 加列 / 改列 / 删列 / 删表。

五个动作流程一样：**校验 → 抛确认 → 执行时调 storage**。
放在一个文件里是因为它们同属一组（design 工具层的"对表"），
共用的规则只有一条：**列名和类型由模型给，合法性从表定义判断。**

## 没有业务字段

列名、类型、默认值都是模型传进来的参数。这个文件不知道
"项目名""负责人"是什么——那是用户某张表的结构。

## 破坏性操作先落快照

删表 / 删列 / 改列类型都会动到数据，执行前落一份整表快照
（`snapshot.snapshot`）。加列不动已有数据，不落。

## SQLite 的类型

它没有真正的 VARCHAR / BOOLEAN，建表时写的类型名只决定存储取向。
但**表定义要给人看**——列一堆 `TEXT` 比列一堆乱七八糟的类型名
更容易判断该往里填什么，所以这里仍然收规范类型名再映射。
"""

import json
import re

import snapshot as snapshot_mod
import storage
from audit import record
from runner import transaction, using
from services import UserInputRequired


# 用户传的类型名 → 库里实际落的类型
COLUMN_TYPES = {
    "VARCHAR":   "TEXT",
    "INTEGER":   "INTEGER",
    "BIGINT":    "INTEGER",     # SQLite 的整数是 64 位，与 BIGINT 同宽
    "DOUBLE":    "REAL",
    "BOOLEAN":   "INTEGER",     # 存 0/1
    "TIMESTAMP": "TEXT",        # 'YYYY-MM-DD HH:MM:SS'
    "DATE":      "TEXT",        # 'YYYY-MM-DD'
}

# 系统列——不能被新列名撞上，也不能被改
RESERVED = set(storage.SYSTEM_COLS)


def _check_name(name: str) -> str | None:
    if not name:
        return "列名不能为空"
    if name in RESERVED:
        return f"「{name}」是系统列，不能用作列名"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        return "列名只能用小写字母、数字、下划线，且以字母开头"
    return None


def _card_pending(ptype: str, ctx, rows: list[list], columns: list[str],
                  affected: int, danger: bool, **internal) -> dict:
    return {
        "type": ptype,
        "stage": "confirm",
        "table": ctx.table_name,
        "columns": columns,
        "records": rows,
        "affected": affected,
        "danger": danger,
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
        **internal,
    }


# ============================================================ 建表

def request_create_table(table_name: str, columns: list[dict],
                         unique=None, ctx=None) -> str:
    """建一张表。`columns` 是 [{name, type, nullable?, default?}]。"""
    existing = using(storage.list_tables)
    if table_name in existing:
        return json.dumps(
            {"ok": False, "error": f"表「{table_name}」已经存在", "error_type": "invalid"},
            ensure_ascii=False,
        )

    if not columns:
        return json.dumps(
            {"ok": False, "error": "至少要有一列", "error_type": "invalid"},
            ensure_ascii=False,
        )

    defs, names = [], []
    for c in columns:
        err = _check_name(c.get("name", ""))
        if err:
            return json.dumps(
                {"ok": False, "error": err, "error_type": "invalid"}, ensure_ascii=False
            )
        t = COLUMN_TYPES.get(str(c.get("type", "")).upper())
        if not t:
            return json.dumps(
                {"ok": False, "error": f"不认识的类型：{c.get('type')}。可用：{list(COLUMN_TYPES)}",
                 "error_type": "invalid"},
                ensure_ascii=False,
            )
        piece = f"{storage.quote(c['name'])} {t}"
        if not c.get("nullable", True):
            piece += " NOT NULL"
        if c.get("default") not in (None, ""):
            piece += f" DEFAULT {c['default']}"
        defs.append(piece)
        names.append(c["name"])

    # 主键：模型没给就补一个自增整型主键——软删除靠它定位行
    if "id" not in names:
        defs.insert(0, f"{storage.quote('id')} INTEGER PRIMARY KEY")
        names.insert(0, "id")

    rows = [[c.get("name"), c.get("type"), "可空" if c.get("nullable", True) else "必填"]
            for c in columns]
    raise UserInputRequired(
        question=f"即将建表 {table_name}",
        pending_action=_card_pending(
            "struct", ctx, rows, ["列名", "类型", "约束"], len(columns), False,
            action="create_table", new_table=table_name,
            coldefs=", ".join(defs), unique=unique or [],
        ),
    )


# ============================================================ 加列

def request_add_column(table_name: str, column_name: str, column_type: str,
                       default_value=None, label=None, ctx=None) -> str:
    err = _check_name(column_name)
    if err:
        return json.dumps({"ok": False, "error": err, "error_type": "invalid"},
                          ensure_ascii=False)

    col_type = COLUMN_TYPES.get(str(column_type).upper())
    if not col_type:
        return json.dumps(
            {"ok": False, "error": f"不认识的类型：{column_type}。可用：{list(COLUMN_TYPES)}",
             "error_type": "invalid"}, ensure_ascii=False)

    existing = {c["name"] for c in using(storage.describe, ctx.table_name)["columns"]}
    if column_name in existing:
        return json.dumps(
            {"ok": False, "error": f"列「{column_name}」已经存在", "error_type": "invalid"},
            ensure_ascii=False)

    coldef = f"{storage.quote(column_name)} {col_type}"
    if default_value not in (None, ""):
        coldef += f" DEFAULT {_format_default(default_value, column_type)}"

    raise UserInputRequired(
        question=f"即将加列 {column_name}",
        pending_action=_card_pending(
            "struct", ctx,
            [[column_name, column_type, default_value or "—", label or "—"]],
            ["列名", "类型", "默认值", "中文含义"], 1, False,
            action="add_column", coldef=coldef, label=label,
        ),
    )


# ============================================================ 改列

def request_alter_column(table_name: str, column_name: str, new_type: str,
                         ctx=None) -> str:
    col_type = COLUMN_TYPES.get(str(new_type).upper())
    if not col_type:
        return json.dumps(
            {"ok": False, "error": f"不认识的类型：{new_type}。可用：{list(COLUMN_TYPES)}",
             "error_type": "invalid"}, ensure_ascii=False)

    cols = using(storage.describe, ctx.table_name)["columns"]
    current = next((c for c in cols if c["name"] == column_name), None)
    if not current:
        return json.dumps(
            {"ok": False, "error": f"列「{column_name}」不存在", "error_type": "invalid"},
            ensure_ascii=False)

    raise UserInputRequired(
        question=f"即将把 {column_name} 改成 {new_type}",
        pending_action=_card_pending(
            "struct", ctx,
            [[column_name, current["type"], col_type]],
            ["列名", "原类型", "新类型"], 1, True,   # 改类型要重建表，算破坏性
            action="alter_column", column=column_name, new_type=col_type,
        ),
    )


# ============================================================ 删列

def request_drop_column(table_name: str, column_name: str, ctx=None) -> str:
    cols = using(storage.describe, ctx.table_name)["columns"]
    if column_name not in {c["name"] for c in cols}:
        return json.dumps(
            {"ok": False, "error": f"列「{column_name}」不存在", "error_type": "invalid"},
            ensure_ascii=False)

    raise UserInputRequired(
        question=f"即将删除列 {column_name}",
        pending_action=_card_pending(
            "struct", ctx, [[column_name]], ["列名"], 1, True,
            action="drop_column", column=column_name,
        ),
    )


# ============================================================ 删表

def request_drop_table(table_name: str, ctx=None) -> str:
    if table_name not in using(storage.list_tables):
        return json.dumps(
            {"ok": False, "error": f"表「{table_name}」不存在", "error_type": "invalid"},
            ensure_ascii=False)

    raise UserInputRequired(
        question=f"即将删除表 {table_name}",
        pending_action=_card_pending(
            "struct", ctx, [[table_name, "整张表"]], ["表名", "范围"], 1, True,
            action="drop_table",
        ),
    )


# ============================================================ 回滚

def request_rollback(snapshot_id: int, ctx) -> str:
    """请求把表退回某个快照。

    **回滚本身也是破坏性操作**——`snapshot.rollback` 会先给当前状态
    再落一份，所以回滚错了还能回滚回来（design 数据层第五节）。
    """
    snaps = using(snapshot_mod.list_snapshots)
    target = next((s for s in snaps if s["id"] == snapshot_id), None)
    if not target:
        return json.dumps(
            {"ok": False, "error": f"没有这个快照：{snapshot_id}",
             "error_type": "invalid"},
            ensure_ascii=False,
        )

    raise UserInputRequired(
        question=f"即将回滚 {target['table']}",
        pending_action=_card_pending(
            "struct", ctx.for_table(target["table"]),
            [[target["table"], target["at"], target["label"], target["rows"]]],
            ["表", "时间", "因何产生", "行数"], 1, True,
            action="rollback", snapshot_id=snapshot_id,
            table_name=target["table"],
        ),
    )


# ============================================================ 执行

def execute_structure(pending: dict, trace_id: str, user_input: str) -> str:
    """执行结构变更。销毁性的先落快照——那是唯一还能回头的路。"""
    action = pending["action"]
    table = pending["table_name"]

    try:
        # 整个结构变更 + 审计包在一个事务里：要么都成，要么都不成
        with transaction() as tx:
            if action == "create_table":
                _do_create_table(tx, pending)
            elif action == "add_column":
                storage.add_column(tx, table, pending["coldef"])
                if pending.get("label"):
                    storage.set_note(tx, table, pending["column"], pending["label"])
            elif action == "alter_column":
                snapshot_mod.snapshot(tx, table, "drop_column")
                storage.change_column_type(tx, table, pending["column"], pending["new_type"])
            elif action == "drop_column":
                snapshot_mod.snapshot(tx, table, "drop_column")
                storage.drop_column(tx, table, pending["column"])
            elif action == "drop_table":
                snapshot_mod.drop_table(tx, table)
            elif action == "rollback":
                snapshot_mod.rollback(tx, pending["snapshot_id"])
            else:
                raise ValueError(f"未知的结构动作：{action}")

            record(tx, "structure", {
                "trace_id": trace_id, "user_input": user_input,
                "table": table, "action": action,
            })
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": str(e), "error_type": "constraint"},
            ensure_ascii=False,
        )

    return json.dumps({"ok": True, "table": table, "action": action}, ensure_ascii=False)


def _do_create_table(tx, pending):
    # tx 是事务句柄，有 execute / execute_many——storage 那几个函数
    # 只用到 con.execute，鸭子类型能直接过，不必去摸底层连接
    storage.create_table(
        tx, pending["new_table"], pending["coldefs"],
        unique=tuple(pending.get("unique") or ()),
    )


def _format_default(value, type_name: str) -> str:
    """默认值 → SQL 字面量。"""
    v = str(value).strip()
    t = str(type_name).upper()
    if t in ("INTEGER", "BIGINT", "DOUBLE"):
        float(v)          # 不合法会抛 ValueError，交给调用方
        return v
    if t == "BOOLEAN":
        low = v.lower()
        if low in ("true", "1", "是"):
            return "1"
        if low in ("false", "0", "否"):
            return "0"
        raise ValueError(f"布尔默认值「{v}」不合法，可用 true / false")
    return "'" + v.replace("'", "''") + "'"
