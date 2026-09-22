from services import bulk_threshold
from services import delete_service, create_service, update_service, transform_service
from services import import_service, restore_service


def handle_pending(question: str, session, db_path: str, real_table: str, llm=None):
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
    if ptype == "restore":
        return _handle_restore(question, session, pending, db_path, real_table)
    if ptype == "create":
        return _handle_create(question, session, pending, db_path, real_table)
    if ptype == "batch_create":
        return _handle_batch_create(question, session, pending, db_path, real_table)
    if ptype == "update":
        return _handle_update(question, session, pending, db_path, real_table)
    if ptype == "import":
        return _handle_import(question, session, pending, db_path, real_table, llm)
    if ptype == "transform":
        return _handle_transform(question, session, pending, db_path)
    
    return False, ""


def _handle_delete(question, session, pending, db_path, real_table):
    n = len(pending["candidates"])
    if n <= bulk_threshold():
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


def _handle_restore(question, session, pending, db_path, real_table):
    n = len(pending["candidates"])
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = restore_service.execute_restore(
            pending["candidates"], db_path, real_table,
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已恢复 {count} 条记录，它们已重新出现在项目台账里。"
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
    if n <= bulk_threshold():
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
    if n <= bulk_threshold():
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


def _handle_transform(question, session, pending, db_path):
    n = pending["total"]
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = transform_service.execute_transform(
            pending, db_path, pending["table_name"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已修改 {count} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_import(question, session, pending, db_path, real_table, llm):
    scan_result = pending["scan_result"]
    parsed = import_service.parse_user_answer(question, scan_result, llm)

    action = parsed.get("action")

    if action == "cancel":
        session.clear_pending()
        return True, "已取消导入。"

    if action == "show_detail":
        detail_type = parsed.get("detail_type", "")
        msg = import_service.format_detail(scan_result, detail_type)
        msg += "\n\n请继续回答之前的确认问题。"
        return True, msg

    if action == "submit":
        rename_map = parsed.get("rename_map", {})
        deleted_action = parsed.get("deleted_action", "keep")
        conflict_action = parsed.get("conflict_action", "db")

        stats = import_service.execute_import(
            scan_result, rename_map, deleted_action, conflict_action,
            db_path, real_table, pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()

        parts = ["导入完成。\n"]
        if stats["renamed"]:
            parts.append(f"- 改名：{stats['renamed']} 条")
        if stats["restored"]:
            parts.append(f"- 恢复删除：{stats['restored']} 条")
        if stats["inserted"]:
            parts.append(f"- 新增：{stats['inserted']} 条")
        if stats["updated"]:
            parts.append(f"- 更新：{stats['updated']} 条")
        return True, "\n".join(parts)

    return True, "抱歉，我没理解你的回答。请回答之前的问题，或回复「取消」。"


def format_pending_display(pending: dict) -> str:
    """根据 pending 类型，格式化展示消息。"""
    ptype = pending.get("type")

    if ptype == "delete":
        msg = delete_service.format_candidates(pending["candidates"])
        msg += "\n\n" + delete_service.delete_confirm_prompt(pending["candidates"])
        return msg
    if ptype == "restore":
        msg = restore_service.format_candidates(pending["candidates"])
        msg += "\n\n" + restore_service.restore_confirm_prompt(pending["candidates"])
        return msg
    if ptype == "create":
        return create_service.format_create_confirm(pending["record"])
    if ptype == "batch_create":
        return create_service.format_batch_create_confirm(pending["records"])
    if ptype == "update":
        return update_service.format_update_confirm(pending["candidates"], pending["updates"])
    if ptype == "transform":
        return transform_service.format_transform_confirm(
            pending, pending.get("table_name", "")
        )
    if ptype == "import":
        return import_service.format_import_summary(pending["scan_result"])

    return "需要用户确认"