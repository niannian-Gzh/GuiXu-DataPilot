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

WRITE_INTENT_KEYWORDS = (
    "删除", "删掉", "去掉", "移除", "清除",
    "修改", "改成", "改为", "更新", "调整",
    "新增", "添加", "增加", "插入", "新建",
    "导入", "写入", "上传",
)


def check_intent_safety(question: str) -> tuple[bool, str]:
    """检查用户问题是否包含写操作意图。

    注意：这是当前阶段（仅支持查询）的策略。
    未来支持 CRUD 后，本函数应改为返回"需要确认"而非"拒绝"。
    """
    for kw in WRITE_INTENT_KEYWORDS:
        if kw in question:
            return False, f"检测到写操作意图（{kw}），当前版本仅支持查询"
    return True, "OK"