import json
from datetime import date
from tools import TOOL_SCHEMAS, build_tool_functions, dispatch
from services import UserInputRequired


READ_TOOL_LIMIT = 3
WRITE_TOOL_LIMIT = 2
WRITE_TOOLS = {"request_create", "request_update", "request_delete", "request_batch_create"}


SYSTEM_PROMPT = """你是 DataPilot，一个数据助手。你可以调用工具来完成任务。

规则：
1. 需要查询数据时，调用 query_database 工具。
2. 用户明确要求删除数据时，调用 request_delete 工具。
3. 用户明确要求修改数据时，调用 request_update 工具。
4. 用户明确要求新增数据时：
   - 单条用 request_create
   - 多条用 request_batch_create
5. 不要擅自改变用户请求的性质。如果用户要求不支持的操作，明确告知。
6. 如果用户的问题不明确，直接向用户提问，不要猜测。
7. 不要编造数据。所有数据必须来自工具返回。
8. 用简洁的中文回答。
9. 信任工具结果：工具返回中包含 hint 字段时，说明工具已完整执行，
   请信任该结果，不要换问法反复查询同一个问题。
10. 不要陷入自我怀疑：同一个工具连续成功调用 2 次后，
    应当基于已有信息回答用户，或向用户说明情况，而不是继续尝试。
11. 如果工具返回中包含 ambiguous: true 和 branches 字段，
    说明这个查询有两种合理解读，请把两个分支都展示给用户。
12. 如果工具返回 is_security: true，说明这是安全拒绝，不要重试，
    直接告知用户无法完成。

当前日期：{today}"""


def _is_success(result_str: str) -> bool:
    try:
        data = json.loads(result_str)
        return "error" not in data
    except json.JSONDecodeError:
        return False


def _is_security_error(result_str: str) -> bool:
    try:
        data = json.loads(result_str)
        return bool(data.get("is_security", False))
    except json.JSONDecodeError:
        return False


def run_agent(user_input: str, session, llm, db_path: str, table_name: str, trace, max_iterations: int = 10):
    """Agent 主循环。"""
    functions = build_tool_functions(llm, db_path, table_name, trace)

    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())}]
    messages.extend(session.get_history())
    messages.append({"role": "user", "content": user_input})

    success_counts = {}
    failure_counts = {}

    for i in range(max_iterations):
        msg = llm.chat_messages(messages, tools=TOOL_SCHEMAS)

        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                name = tc.function.name
                limit = WRITE_TOOL_LIMIT if name in WRITE_TOOLS else READ_TOOL_LIMIT

                print(f"  [工具] {name}({tc.function.arguments})")
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                result = dispatch(name, args, functions)

                if _is_success(result):
                    # 思维熔断：成功的调用
                    success_counts[name] = success_counts.get(name, 0) + 1
                    if success_counts[name] > limit:
                        return (
                            f"抱歉，我在处理这个请求时反复尝试了多次，"
                            f"工具「{name}」已成功调用 {success_counts[name]} 次，"
                            f"但结果始终未能让流程继续。\n\n"
                            f"最后一次工具返回：{result[:200]}\n\n"
                            f"建议：请确认你的请求是否明确，或换一种说法再试。"
                        )
                elif _is_security_error(result):
                    # 安全拒绝：不计数，交由 agent 处理
                    pass
                else:
                    # 异常熔断：失败的调用
                    failure_counts[name] = failure_counts.get(name, 0) + 1
                    if failure_counts[name] > limit:
                        return (
                            f"抱歉，工具「{name}」已连续失败 {failure_counts[name]} 次，"
                            f"无法完成请求。\n\n"
                            f"最后一次错误：{result[:200]}\n\n"
                            f"建议：请检查请求是否合理，或稍后重试。"
                        )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        answer = msg.content or ""
        session.add_user(user_input)
        session.add_assistant(answer)
        return answer

    return "[达到最大循环次数，强制结束]"