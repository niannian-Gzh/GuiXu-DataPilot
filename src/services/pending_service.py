"""待确认 / 待回答的中断怎么收尾。

**一次中断 = 一次工具挂起。** 用户回应之后，工具从挂起处接着走，
把结果伪装成那次工具调用的返回喂回模型（design 记忆层第五节）。
所以这里返回的不是"给用户的一句话"，而是**工具的续体结果**：

- 确认类：执行结果 JSON（删了多少、改了多少、失败原因）
- `ask_user`：`{ok: true, answer: "..."}`，答案本身就是结果
- 取消确认：`{ok: false, error_type: "cancelled"}`，让模型知道用户拒绝了
- 跳过提问：**不续跑**——模型没有答案，续跑只会凑一段解释。这一轮到此为止

两种例外仍然直接给用户、不续跑：
- **确认没通过**（比如批量删除要求手打「删除 166 条」，用户打错了）——
  这时用户还没给出有效回答，pending 留着等重输，不必惊动模型
- **导入时用户要求看详情**——那是"回答之前先问一句"，看完还要继续答
"""

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


def _cancelled(message: str = "用户取消了操作") -> str:
    return json.dumps(
        {"ok": False, "error_type": "cancelled", "error": message},
        ensure_ascii=False,
    )


def answer_pending(question: str, session, llm=None, answers=None):
    """处理用户对中断的回应。返回 `(action, payload)`。

    - `"none"`   —— 不是对中断的回答，交给 agent 正常跑
    - `"done"`   —— payload 是直接给用户的一句话（不续跑，pending 保留）
    - `"resume"` —— payload 是工具返回的 JSON，调用方用它续跑
    - `"skip"`   —— 用户跳过了提问：这一轮到此为止（清 pending，不调模型）
    """
    pending = session.get_pending()
    if not pending:
        if _looks_like_confirm(question):
            return "done", (
                "你似乎在确认一个操作，但服务端已经没有待确认的记录。\n\n"
                "这通常是因为服务重启，导致待确认状态失效。"
                "请重新发起原始请求。"
            )
        return "none", ""

    # 跳过提问 ≠ 取消操作。取消删除要续跑一句"好的，没删"，模型知道
    # 用户拒绝了；跳过提问时模型手里**没有答案**，续跑只会拿猜测或
    # 一句解释凑一段回答。所以这一轮直接停在这里
    if pending.get("type") == "ask" and delete_service.is_cancel(question):
        return "skip", _cancelled("用户跳过了这次提问")

    if delete_service.is_cancel(question):
        return "resume", _cancelled()

    ptype = pending.get("type")

    if ptype == "delete":
        return _handle_delete(question, pending)
    if ptype == "restore":
        return _handle_restore(question, pending)
    if ptype == "create":
        return _handle_create(question, pending)
    if ptype == "update":
        return _handle_update(question, pending)
    if ptype == "import":
        return _handle_import(question, pending, llm)
    if ptype == "transform":
        return _handle_transform(question, pending)
    if ptype == "struct":
        return _handle_struct(question, pending)
    if ptype == "ask":
        return _handle_ask(question, pending, answers)

    return "none", ""


# 卡片上要留痕的字段。**内部字段一个都不存**——候选 id、扫描结果、
# 断点片段这些是执行时才用的，存进会话文件除了撑大没有别的用处。
# 卡片字段要全留着：设计里那张缩略卡"可点开回看当初的详情"，
# 只留一个数字的话，展开就只剩空壳
_CARD_FIELDS = (
    "type", "table", "columns", "records", "affected",
    "changes", "danger", "question", "options", "questions",
)


def settle(pending: dict, tool_result: str) -> dict:
    """把一次中断的结局固定成可回看的记录。落进这一轮的用户消息（gx_confirms）。

    **结局从工具的续体返回判，不从用户那句话猜**：取消统一是
    `error_type: cancelled`，导入那种由模型解析出来的取消也在里面；
    按输入猜的话，换个说法就漏了。
    """
    try:
        result = json.loads(tool_result)
    except (TypeError, ValueError):
        result = {}

    cancelled = result.get("error_type") == "cancelled"
    if cancelled:
        outcome = "cancelled"
    elif pending.get("type") == "ask":
        outcome = "answered"
    else:
        outcome = "executed"

    record = {k: pending[k] for k in _CARD_FIELDS if k in pending}
    record["outcome"] = outcome
    if outcome == "answered":
        # 新续体是 answers 一串；旧记录只有一个 answer
        got = result.get("answers")
        if not got:
            got = [{
                "question": pending.get("question", ""),
                "answer": result.get("answer") or "",
            }]
        record["answers"] = got
    return record


def enrich_pending(pending: dict) -> dict:
    """给 pending 补上确认模式信息，供前端决定渲染形态。

    - simple: 单条或少量，普通确认按钮即可（发送"确认"）
    - typed:  批量操作，需要用户输入包含数量的确认文本（如"修改166条"）
    """
    ptype = pending.get("type")

    if ptype in ("delete", "restore", "update"):
        n = len(pending.get("candidates", []))
        verb = {"delete": "删除", "restore": "恢复", "update": "修改"}[ptype]
    elif ptype == "create":
        n = pending.get("affected", 1)
        verb = "新增"
    elif ptype == "transform":
        # 卡片的字段叫 affected；total 是旧版本留下的名字，兼容老 pending
        n = pending.get("affected", pending.get("total", 0))
        verb = "修改"
    else:
        # create / struct / import / ask：不涉及批量，一律 simple
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


def _confirm_ok(question, pending, threshold_n=None):
    """这个回答算不算一次有效确认。"""
    n = threshold_n if threshold_n is not None else pending["affected"]
    if n <= bulk_threshold():
        return delete_service.is_confirm(question)
    return delete_service.is_bulk_confirm(question, n)


def _handle_delete(question, pending):
    if not _confirm_ok(question, pending):
        return "done", "确认未通过。请重新输入正确的确认信息，或回复「取消」。"
    count = delete_service.execute_delete(
        pending["candidates"], pending["table_name"],
        pending["trace_id"], pending["user_input"],
    )
    return "resume", json.dumps({
        "ok": True, "table": pending["table"], "affected": count,
    }, ensure_ascii=False)


def _handle_restore(question, pending):
    if not _confirm_ok(question, pending):
        return "done", "确认未通过。请重新输入正确的确认信息，或回复「取消」。"
    try:
        count = restore_service.execute_restore(
            pending["candidates"], pending["table_name"],
            pending["trace_id"], pending["user_input"],
        )
    except ValueError as e:
        # 比如删了 A、又建了一条同名 A，现在恢复旧 A 会撞唯一约束。
        # 这不是系统故障，是用户能理解并处理的一条事实
        return "resume", json.dumps({
            "ok": False, "error_type": "duplicate", "error": str(e),
        }, ensure_ascii=False)
    return "resume", json.dumps({
        "ok": True, "table": pending["table"], "affected": count,
    }, ensure_ascii=False)


def _handle_create(question, pending):
    if not _confirm_ok(question, pending):
        return "done", "确认未通过。请重新输入正确的确认信息，或回复「取消」。"
    # values 是原始记录数组（单条也走数组）；卡片上的 records 是二维行
    return "resume", create_service.execute_create(
        pending["values"], pending["table_name"],
        pending["trace_id"], pending["user_input"],
    )


def _handle_update(question, pending):
    if not _confirm_ok(question, pending):
        return "done", "确认未通过。请重新输入正确的确认信息，或回复「取消」。"
    return "resume", update_service.execute_update(
        pending["candidates"], pending["updates"], pending["table_name"],
        pending["trace_id"], pending["user_input"],
    )


def _handle_transform(question, pending):
    n = pending.get("affected", pending.get("total", 0))
    if not _confirm_ok(question, pending, threshold_n=n):
        return "done", "确认未通过。请重新输入正确的确认信息，或回复「取消」。"
    return "resume", transform_service.execute_transform(
        pending, pending["table_name"],
        pending["trace_id"], pending["user_input"],
    )


def _handle_struct(question, pending):
    """结构变更的执行端。建表 / 加列 / 改列 / 删列 / 删表 / 回滚都走这里。"""
    if not delete_service.is_confirm(question):
        return "done", "请回复「确认」执行，或「取消」放弃。"
    return "resume", structure_service.execute_structure(
        pending, pending["trace_id"], pending["user_input"],
    )


def _handle_ask(question, pending, answers=None):
    """`ask_user` 的续体：用户说什么，就是工具拿到的什么。

    这里不判断内容——选项只是个提示，自由输入永远算数（design 工具层 §二）。

    多问题时答案**带着问题一起回去**：一串光秃秃的字符串，模型没法知道
    哪句答的是哪问。旧记录只有一个 question，也归一成一条。
    """
    qs = pending.get("questions") or [{
        "question": pending.get("question", ""),
    }]
    vals = list(answers) if answers else [question]
    return "resume", json.dumps({
        "ok": True,
        "answers": [
            {
                "question": q.get("question", ""),
                "answer": str(vals[i]) if i < len(vals) else "",
            }
            for i, q in enumerate(qs)
        ],
    }, ensure_ascii=False)


def _handle_import(question, pending, llm):
    scan_result = pending["scan_result"]
    parsed = import_service.parse_user_answer(question, scan_result, llm)

    action = parsed.get("action")

    if action == "cancel":
        return "resume", _cancelled("用户取消了导入")

    if action == "show_detail":
        # 看详情是"回答之前先问一句"，不是回答本身——看完还要接着答，
        # 所以不续跑，pending 留着
        detail_type = parsed.get("detail_type", "")
        msg = import_service.format_detail(scan_result, detail_type)
        msg += "\n\n请继续回答之前的确认问题。"
        return "done", msg

    if action == "submit":
        return "resume", import_service.execute_import(
            scan_result,
            parsed.get("rename_map", {}),
            parsed.get("deleted_action", "keep"),
            parsed.get("conflict_action", "db"),
            pending["table_name"], pending["trace_id"], pending["user_input"],
        )

    return "done", "抱歉，我没理解你的回答。请回答之前的问题，或回复「取消」。"
