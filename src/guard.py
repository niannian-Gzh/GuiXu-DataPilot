import sqlglot
from sqlglot import exp


class SecurityError(Exception):
    """写操作或危险 SQL 被拒绝时抛出。"""
    pass


FORBIDDEN_TRANSFORM_COLUMNS = {
    "is_deleted", "deleted_at", "deleted_by", "delete_trace_id",
}


def _parse_one(sql: str):
    """解析单条 SQL。返回表达式对象。"""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception as e:
        raise ValueError(f"无法解析 SQL：{e}")
    if len(statements) == 0:
        raise ValueError("SQL 为空")
    if len(statements) > 1:
        raise ValueError("不允许多条语句")
    return statements[0]


def check_sql_safety(sql: str) -> tuple[bool, str]:
    """检查 SQL 是否安全（只允许 SELECT）。返回 (是否安全, 原因)。"""
    try:
        stmt = _parse_one(sql)
    except ValueError as e:
        return False, str(e)

    if not isinstance(stmt, (exp.Select, exp.Union)):
        return False, f"只允许 SELECT 查询，检测到 {type(stmt).__name__}"
    return True, "OK"


def check_transform_safety(sql: str) -> tuple[bool, str, bool]:
    """检查变换 SQL 是否安全。

    返回 (是否安全, 原因, 是否全表操作)。

    规则：
      1. 必须是单条 UPDATE
      2. 不能改系统字段
      3. 全表操作不拒绝——用 is_full_table=True 标记
    """
    try:
        stmt = _parse_one(sql)
    except ValueError as e:
        return False, str(e), False

    if not isinstance(stmt, exp.Update):
        return False, f"变换只允许 UPDATE 语句，检测到 {type(stmt).__name__}", False

    for assignment in stmt.expressions:
        col = assignment.this
        if not isinstance(col, exp.Column):
            return False, f"无法识别的赋值目标：{col}", False
        col_name = col.name.lower()
        if col_name in FORBIDDEN_TRANSFORM_COLUMNS:
            return False, f"不允许修改系统字段：{col_name}", False

    is_full_table = _is_full_table(stmt)
    return True, "OK", is_full_table


def _is_full_table(update_stmt) -> bool:
    """UPDATE 是否是无约束的全表操作。"""
    where = update_stmt.args.get("where")
    if where is None:
        return True
    return _is_always_true(where.this)


def _is_always_true(condition) -> bool:
    """检测条件是否恒真。识别：TRUE、1=1、'x'='x'。"""
    if condition is None:
        return True
    if isinstance(condition, exp.Boolean):
        return condition.this is True
    if isinstance(condition, exp.EQ):
        left, right = condition.this, condition.expression
        if isinstance(left, exp.Literal) and isinstance(right, exp.Literal):
            if left.is_int and right.is_int and left.this == right.this:
                return True
            if left.is_string and right.is_string and left.this == right.this:
                return True
    return False
