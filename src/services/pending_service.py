import re
from services import bulk_threshold
from services import (
    delete_service, create_service, update_service,
    transform_service, add_column_service,
)
from services import import_service, restore_service


def _looks_like_confirm(text: str) -> bool:
    """判断输入看起来像一次"确认"动作。

    用途：pending 已经失效（比如服务重启导致内存丢失），但用户仍以为
    自己在确认某个操作，输入了一个确认词。这时若按新问题交给 agent，
    用户会拿到莫名其妙的回答。改用一个明确的失效提示更清楚。

    只认两种形态：完全等于确认词，或"动词 + 数字 + 条"的批量确认格式
    （如"删除166条"）。两者都是整串匹配，正常提问不会撞上，
    所以不需要再另设长度门槛。
    """
    s = text.strip().lower()
    if not s:
        return False
    if s in delete_service.CONFIRM_WORDS:
        return True
    # 批量确认的典型格式："删除166条" / "修改64条"
    return bool(re.fullmatch(r"(删除|修改|恢复|新增)\s*\d+\s*条", s))


def handle_pending(question: str, session, db_path: str, llm=None):
    """处理待确认操作。返回 (handled: bool, message: str)。

    表名从 pending 里读——不再从参数传。因为"这次确认是针对哪张表"
    在 pending 生成那一刻就定了，重新传参反而容易和 pending 不一致。
    """
    pending = session.get_pending()
    if not pending:
        if _looks_like_confirm(question):
            return True, (
                "你似乎在确认一个操作，但服务端已经没有待确认的记录。\n\n"
                "这通常是因为服务重启，导致待确认状态失效。"
                "请重新发起原始请求。"
            )
        return False, ""

    if delete_service.is_cancel(question):
        session.clear_pending()
        return True, "已取消操作。"

    ptype = pending.get("type")

    if ptype == "delete":
        return _handle_delete(question, session, pending, db_path)
    if ptype == "restore":
        return _handle_restore(question, session, pending, db_path)
    if ptype == "create":
        return _handle_create(question, session, pending, db_path)
    if ptype == "batch_create":
        return _handle_batch_create(question, session, pending, db_path)
    if ptype == "update":
        return _handle_update(question, session, pending, db_path)
    if ptype == "import":
        return _handle_import(question, session, pending, db_path, llm)
    if ptype == "transform":
        return _handle_transform(question, session, pending, db_path)
    if ptype == "add_column":
        return _handle_add_column(question, session, pending, db_path)

    return False, ""


def enrich_pending(pending: dict) -> dict:
    """给 pending 补上确认模式信息，供前端决定渲染形态。

    - simple: 单条或少量，普通确认按钮即可（发送"确认"）
    - typed:  批量操作，需要用户输入包含数量的确认文本（如"修改166条"）
    """
    ptype = pending.get("type")

    if ptype in ("delete", "restore", "update"):
        n = len(pending.get("candidates", []))
        verb = {"delete": "删除", "restore": "恢复", "update": "修改"}[ptype]
    elif ptype == "batch_create":
        n = len(pending.get("records", []))
        verb = "新增"
    elif ptype == "transform":
        n = pending.get("total", 0)
        verb = "修改"
    else:
        # create / add_column / import：不涉及批量，一律 simple
        pending["confirm_mode"] = "simple"
        pending["confirm_hint"] = "确认"
        return pending

    if n <= bulk_threshold():
        pending["confirm_mode"] = "simple"
        pending["confirm_hint"] = "确认"
    else:
        pending["confirm_mode"] = "typed"
        pending["confirm_hint"] = f"{verb}{n}条"

    return pending


def _handle_delete(question, session, pending, db_path):
    n = len(pending["candidates"])
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = delete_service.execute_delete(
            pending["candidates"], db_path, pending["real_table"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已删除 {count} 条记录。7 天内可恢复。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_restore(question, session, pending, db_path):
    n = len(pending["candidates"])
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = restore_service.execute_restore(
            pending["candidates"], db_path, pending["real_table"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已恢复 {count} 条记录，它们已重新出现在项目台账里。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_create(question, session, pending, db_path):
    if delete_service.is_confirm(question):
        create_service.execute_create(
            pending["record"], db_path, pending["real_table"],
            pending["trace_id"], pending["user_input"],
        )
        name = pending["record"]["project_name"]
        session.clear_pending()
        return True, f"已新增项目「{name}」。"
    return True, "请回复「确认」执行新增，或「取消」放弃。"


def _handle_batch_create(question, session, pending, db_path):
    n = len(pending["records"])
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = create_service.execute_batch_create(
            pending["records"], db_path, pending["real_table"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已新增 {count} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_update(question, session, pending, db_path):
    n = len(pending["candidates"])
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = update_service.execute_update(
            pending["candidates"], pending["updates"], db_path, pending["real_table"],
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
            pending, db_path, pending["real_table"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已修改 {count} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_add_column(question, session, pending, db_path):
    if delete_service.is_confirm(question):
        result = add_column_service.execute_add_column(
            pending, db_path, pending["trace_id"], pending["user_input"]
        )
        session.clear_pending()

        msg = f"已加列「{result['column']}」。"
        if result["label_set"]:
            msg += "中文含义已标注。"
        else:
            msg += "你可以在「数据库概览」页标注它的中文含义。"
        return True, msg
    return True, "请回复「确认」执行，或「取消」放弃。"


def _handle_import(question, session, pending, db_path, llm):
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
            db_path, pending["real_table"], pending["trace_id"], pending["user_input"],
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
    if ptype == "add_column":
        return add_column_service.format_add_column_confirm(pending)
    if ptype == "import":
        return import_service.format_import_summary(pending["scan_result"])

    return "需要用户确认"