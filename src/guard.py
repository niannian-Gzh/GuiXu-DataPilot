class SecurityError(Exception):
    """写操作或危险 SQL 被拒绝时抛出。"""
    pass


WRITE_KEYWORDS = ("delete", "update", "insert", "drop", "alter", "truncate", "create")


def check_sql_safety(sql: str) -> tuple[bool, str]:
    """检查 SQL 是否安全。返回 (是否安全, 原因)。"""
    normalized = sql.strip().lower()

    if normalized.startswith("select"):
        return True, "OK"

    for kw in WRITE_KEYWORDS:
        if normalized.startswith(kw):
            return False, f"检测到写操作（{kw.upper()}），当前版本仅支持查询"

    return False, "无法识别的 SQL 类型，已拒绝执行"


FORBIDDEN_TRANSFORM_COLUMNS = {
    "is_deleted", "deleted_at", "deleted_by", "delete_trace_id",
}


def check_transform_safety(sql: str) -> tuple[bool, str]:
    """检查变换 SQL 是否安全。返回 (是否安全, 原因)。

    规则：
      1. 必须以 UPDATE 开头
      2. 必须带 WHERE —— 不允许全表无条件更新
      3. 不能改系统字段（软删除 / 审计相关）
      4. 不能包含多条语句
    """
    s = sql.strip()
    normalized = s.lower()

    # 1. 只允许 UPDATE
    if not normalized.startswith("update"):
        return False, "变换只允许 UPDATE 语句"

    # 2. 必须有 WHERE
    if " where " not in normalized:
        return False, "UPDATE 必须带 WHERE 子句，不允许全表无条件更新"

    # 3. 检查 SET 部分是否动了系统字段
    set_part = normalized.split(" where ", 1)[0]
    if " set " in set_part:
        assignments = set_part.split(" set ", 1)[1]
        for assignment in assignments.split(","):
            lhs = assignment.split("=")[0].strip()
            # 去掉可能的表名前缀
            lhs = lhs.split(".")[-1].strip().strip('"').strip("`")
            if lhs in FORBIDDEN_TRANSFORM_COLUMNS:
                return False, f"不允许修改系统字段：{lhs}"

    # 4. 不允许多条语句
    # 先剥掉末尾分号，再看中间有没有
    body = s.rstrip().rstrip(";").strip()
    if ";" in body:
        return False, "不允许包含多条语句"

    return True, "OK"