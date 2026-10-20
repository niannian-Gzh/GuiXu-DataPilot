import json
import re
from services import bulk_threshold
from services import (
    delete_service, create_service, update_service,
    transform_service, structure_service,
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


def handle_pending(question: str, session, llm=None):
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
        return _handle_delete(question, session, pending)
    if ptype == "restore":
        return _handle_restore(question, session, pending)
    if ptype == "create":
        return _handle_create(question, session, pending)
    if ptype == "batch_create":
        return _handle_batch_create(question, session, pending)
    if ptype == "update":
        return _handle_update(question, session, pending)
    if ptype == "import":
        return _handle_import(question, session, pending, llm)
    if ptype == "transform":
        return _handle_transform(question, session, pending)
    if ptype == "struct":
        return _handle_struct(question, session, pending)

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


def _handle_delete(question, session, pending):
    n = pending["affected"]
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = delete_service.execute_delete(
            pending["candidates"], pending["table_name"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已在「{pending['table']}」删除 {count} 条记录。7 天内可恢复。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_restore(question, session, pending):
    n = pending["affected"]
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        count = restore_service.execute_restore(
            pending["candidates"], pending["table_name"],
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        return True, f"已恢复 {count} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_create(question, session, pending):
    if delete_service.is_confirm(question):
        result = json.loads(create_service.execute_create(
            pending["record"], pending["table_name"],
            pending["trace_id"], pending["user_input"],
        ))
        session.clear_pending()
        if not result.get("ok"):
            return True, f"新增失败：{result.get('error')}"
        return True, f"已在「{pending['table']}」新增 {result['affected']} 条记录。"
    return True, "请回复「确认」执行新增，或「取消」放弃。"


def _handle_batch_create(question, session, pending):
    # 卡片的 records 是二维行，执行数据在 batch_records——两个键不是一回事
    n = pending["affected"]
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        result = json.loads(create_service.execute_batch_create(
            pending["batch_records"], pending["table_name"],
            pending["trace_id"], pending["user_input"],
        ))
        session.clear_pending()
        if not result.get("ok"):
            return True, f"批量新增失败（整批已回滚）：{result.get('error')}"
        return True, f"已在「{pending['table']}」新增 {result['affected']} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_update(question, session, pending):
    n = pending["affected"]
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        result = json.loads(update_service.execute_update(
            pending["candidates"], pending["updates"], pending["table_name"],
            pending["trace_id"], pending["user_input"],
        ))
        session.clear_pending()
        if not result.get("ok"):
            return True, f"修改失败：{result.get('error')}"
        return True, f"已在「{pending['table']}」修改 {result['affected']} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_transform(question, session, pending):
    n = pending["total"]
    if n <= bulk_threshold():
        valid = delete_service.is_confirm(question)
    else:
        valid = delete_service.is_bulk_confirm(question, n)

    if valid:
        result = json.loads(transform_service.execute_transform(
            pending, pending["table_name"],
            pending["trace_id"], pending["user_input"],
        ))
        session.clear_pending()
        if not result.get("ok"):
            return True, f"修改失败：{result.get('error')}"
        return True, f"已在「{pending['table']}」修改 {result['affected']} 条记录。"
    return True, "确认未通过。请重新输入正确的确认信息，或回复「取消」。"


def _handle_struct(question, session, pending):
    """结构变更的执行端。建表 / 加列 / 改列 / 删列 / 删表都走这里。"""
    if delete_service.is_confirm(question):
        result = json.loads(structure_service.execute_structure(
            pending, pending["trace_id"], pending["user_input"]
        ))
        session.clear_pending()
        if not result.get("ok"):
            return True, f"结构修改失败：{result.get('error')}"
        return True, f"已在「{pending['table']}」完成结构修改。"
    return True, "请回复「确认」执行，或「取消」放弃。"


def _handle_import(question, session, pending, llm):
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

        result = json.loads(import_service.execute_import(
            scan_result, rename_map, deleted_action, conflict_action,
            pending["table_name"], pending["trace_id"], pending["user_input"],
        ))
        session.clear_pending()
        if not result.get("ok"):
            return True, f"导入失败：{result.get('error')}"

        parts = ["导入完成。"]
        for label, key in (("新增", "inserted"), ("更新", "updated"), ("恢复删除", "restored")):
            if result.get(key):
                parts.append(f"- {label}：{result[key]} 条")
        return True, "\n".join(parts)

    return True, "抱歉，我没理解你的回答。请回答之前的问题，或回复「取消」。"


