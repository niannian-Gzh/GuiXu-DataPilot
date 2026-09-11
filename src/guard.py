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