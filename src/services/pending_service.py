from services import BULK_THRESHOLD
from services import delete_service, create_service, update_service


def handle_pending(question: str, session, db_path: str, real_table: str):
    """处理待确认操作。返回 (handled: bool, message: str)。"""
    pending = session.get_pending()
    if not pending:
        return False, ""

    if delete_service.is_cancel(question):
        session.clear_pending()
        return True, "已取消操作。"

    ptype = pending.get("type")

    if ptype == "delete":
        return _handle_delete(question, session, pending, db_path, real_table)
    if ptype == "create":
        return _handle_create(question, session, pending, db_path, real_table)
    if ptype == "batch_create":
        return _handle_batch_create(question, session, pending, db_path, real_table)
    if ptype == "update":
        return _handle_update(question, session, pending, db_path, real_table)

    return False, ""


def _handle_delete(question, session, pending, db_path, real_table):
    n = len(pending["candidates"])
    if n <= BULK_THRESHOLD:
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = delete_service.execute_delete(
            pending["candidates"], db_path, real_table,
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已删除 {count} 条记录。7 天内可恢复。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_create(question, session, pending, db_path, real_table):
    if delete_service.is_confirm(question):
        create_service.execute_create(
            pending["record"], db_path, real_table,
            pending["trace_id"], pending["user_input"],
        )
        name = pending["record"]["project_name"]
        session.clear_pending()
        return True, f"已新增项目「{name}」。"
    return True, "请回复「确认」执行新增，或「取消」放弃。"


def _handle_batch_create(question, session, pending, db_path, real_table):
    n = len(pending["records"])
    if n <= BULK_THRESHOLD:
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = create_service.execute_batch_create(
            pending["records"], db_path, real_table,
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已新增 {count} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_update(question, session, pending, db_path, real_table):
    n = len(pending["candidates"])
    if n <= BULK_THRESHOLD:
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = update_service.execute_update(
            pending["candidates"], pending["updates"], db_path, real_table,
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已修改 {count} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def format_pending_display(pending: dict) -> str:
    """根据 pending 类型，格式化展示消息。"""
    ptype = pending.get("type")

    if ptype == "delete":
        msg = delete_service.format_candidates(pending["candidates"])
        msg += "\n\n" + delete_service.delete_confirm_prompt(pending["candidates"])
        return msg
    if ptype == "create":
        return create_service.format_create_confirm(pending["record"])
    if ptype == "batch_create":
        return create_service.format_batch_create_confirm(pending["records"])
    if ptype == "update":
        return update_service.format_update_confirm(pending["candidates"], pending["updates"])

    return "需要用户确认"