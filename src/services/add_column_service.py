"""加列——改表结构。

只做 PG。DuckDB 分支已不再维护。
"""

import json
import re

from db import execute, describe, rebuild_view
from schema_store import refresh_from_db, load, save
from audit import log
from services import UserInputRequired


# 受控类型清单：用户传的类型名 → PG 实际类型
COLUMN_TYPES = {
    "VARCHAR":   "VARCHAR",
    "INTEGER":   "INTEGER",
    "BIGINT":    "BIGINT",
    "DOUBLE":    "DOUBLE PRECISION",
    "BOOLEAN":   "BOOLEAN",
    "TIMESTAMP": "TIMESTAMP",
    "DATE":      "DATE",
}

# 系统保留列——不能被新列名撞上
RESERVED_COLUMNS = {
    "is_deleted", "deleted_at", "deleted_by", "delete_trace_id",
}

# 列名格式：小写字母开头，只能含小写字母 / 数字 / 下划线，1-63 字符
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _validate_column_name(name: str, existing: set):
    if not name:
        return "列名不能为空"
    if not IDENTIFIER_RE.match(name):
        return (
            f"列名「{name}」不合法。只允许小写字母开头的英文标识符，"
            f"可含数字和下划线（如 priority / due_date / amount_1）"
        )
    if name in RESERVED_COLUMNS:
        return f"列名「{name}」是系统保留列，不能使用"
    if name in existing:
        return f"列「{name}」已存在"
    return None


def _validate_column_type(type_: str):
    if type_ not in COLUMN_TYPES:
        options = " / ".join(COLUMN_TYPES.keys())
        return f"类型「{type_}」不支持。可选：{options}"
    return None


def _format_default(value, type_: str) -> str:
    """把默认值格式化成 SQL 字面量。空值返回空串（表示无 DEFAULT）。"""
    if value is None or str(value).strip() == "":
        return ""

    v = str(value).strip()

    if type_ in ("INTEGER", "BIGINT", "DOUBLE"):
        try:
            float(v)
        except ValueError:
            raise ValueError(f"默认值「{v}」不是合法数字")
        return v

    if type_ == "BOOLEAN":
        low = v.lower()
        if low in ("true", "1", "是"):
            return "TRUE"
        if low in ("false", "0", "否"):
            return "FALSE"
        raise ValueError(f"布尔默认值「{v}」不合法，可用 true / false")

    # VARCHAR / TIMESTAMP / DATE：加单引号，转义内部单引号
    escaped = v.replace("'", "''")
    return f"'{escaped}'"


def request_add_column(column_name: str, column_type: str,
                       default_value=None, label=None, ctx=None) -> str:
    """请求加列。校验 → 生成 SQL → 抛确认。"""
    real_table = ctx.real_table
    existing = {c["name"] for c in describe(real_table)}

    err = _validate_column_name(column_name, existing)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    err = _validate_column_type(column_type)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    try:
        default_clause = _format_default(default_value, column_type)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    pg_type = COLUMN_TYPES[column_type]
    sql = f"ALTER TABLE {real_table} ADD COLUMN {column_name} {pg_type}"
    if default_clause:
        sql += f" DEFAULT {default_clause}"

    pending = {
        "type": "add_column",
        "stage": "confirm",
        "table_name": ctx.table_name,
        "real_table": ctx.real_table,
        "column_name": column_name,
        "column_type": pg_type,
        "default_value": default_value,
        "label": label,
        "sql": sql,
        "user_input": ctx.trace.data["question"],
        "trace_id": ctx.trace.id,
    }
    raise UserInputRequired(
        question=f"即将加列 {column_name}",
        pending_action=pending,
    )


def format_add_column_confirm(pending: dict) -> str:
    lines = [
        f"即将在表「**{pending['real_table']}**」加一列：\n",
        f"- 列名：`{pending['column_name']}`",
        f"- 类型：`{pending['column_type']}`",
    ]
    if pending.get("default_value"):
        lines.append(f"- 默认值：`{pending['default_value']}`")
    if pending.get("label"):
        lines.append(f"- 中文含义：{pending['label']}")
    lines.append("")
    lines.append("**将执行的 SQL：**\n")
    lines.append("```sql")
    lines.append(pending["sql"])
    lines.append("```")
    lines.append("")
    lines.append("确认执行吗？回复「确认」执行，或「取消」放弃。")
    return "\n".join(lines)


def execute_add_column(pending: dict, db_path: str, trace_id: str, user_input: str) -> dict:
    """执行加列。返回 {column, label_set}。"""
    execute(pending["sql"])

    # 重建视图——PG 的视图列在创建时固定，底层表加列后视图不会自动反映
    rebuild_view(pending["table_name"], pending["real_table"])

    # 刷新字典
    refresh_from_db()

    # 如果带了 label，直接写进字典（用户不用再去概览页手填）
    label_set = False
    if pending.get("label"):
        meta = load()
        table_entry = meta.setdefault("tables", {}).setdefault(
            pending["table_name"], {"label": "", "fields": {}}
        )
        table_entry.setdefault("fields", {})[pending["column_name"]] = pending["label"]
        save(meta)
        label_set = True

    log("add_column", {
        "trace_id": trace_id,
        "user_input": user_input,
        "table": pending["real_table"],
        "column": pending["column_name"],
        "type": pending["column_type"],
        "default": pending.get("default_value"),
        "sql": pending["sql"],
    })

    return {"column": pending["column_name"], "label_set": label_set}