import json
from datetime import date
from tools import TOOL_SCHEMAS, build_tool_functions, dispatch, UserInputRequired


SYSTEM_PROMPT = """你是 DataPilot，一个数据助手。你可以调用工具来完成任务。

规则：
1. 需要查询数据时，调用 query_database 工具。
2. 用户要求删除数据时，调用 request_delete，传入 filter_question（自然语言筛选条件）。
3. 用户要求修改数据时，调用 request_update，传入 filter_question 和 updates。
   如果用户没说清楚改什么，追问用户。
4. 如果用户要求新增数据，调用 request_create；用户一次要求新增多条记录时，调用 request_batch_create，传入 records 数组。
5. 不要擅自改变用户请求的性质。如果用户要求修改数据（如改成、更新为、新增、添加），
   但你没有任何修改工具，请明确告知无法完成，不要降级成查询。
6. 如果用户的问题不明确，直接向用户提问，不要猜测。
7. 不要编造数据。所有数据必须来自工具返回。
8. 用简洁的中文回答。
9. 信任工具结果：工具返回中包含 hint 字段时，说明工具已完整执行，
   请信任该结果，不要换问法反复查询同一个问题。
10. 不要陷入自我怀疑：同一个工具连续成功调用 2 次后，
    应当基于已有信息回答用户，或向用户说明情况，而不是继续尝试。
11. 如果工具返回中包含 ambiguous: true 和 branches 字段，
    说明这个查询有两种合理解读，请把两个分支都展示给用户，
    让用户自己判断。

当前日期：{today}"""


READ_TOOL_LIMIT = 3
WRITE_TOOL_LIMIT = 2
WRITE_TOOLS = {"request_create", "request_update", "request_delete", "request_batch_create"}


def _is_success(result_str: str) -> bool:
    """判断工具返回是否成功（无 error 字段）。"""
    try:
        data = json.loads(result_str)
        return "error" not in data
    except json.JSONDecodeError:
        return False


def run_agent(user_input: str, session, llm, db_path: str, table_name: str, trace, max_iterations: int = 10):
    """Agent 主循环。"""
    functions = build_tool_functions(llm, db_path, table_name, trace)

    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())}]
    messages.extend(session.get_history())
    messages.append({"role": "user", "content": user_input})

    # 思维熔断计数：只统计"成功"的工具调用
    success_counts = {}

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

                print(f"  [工具] {name}({tc.function.arguments})")
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                result = dispatch(name, args, functions)

                # 思维熔断：只对"成功"的调用计数
                if _is_success(result):
                    success_counts[name] = success_counts.get(name, 0) + 1
                    limit = WRITE_TOOL_LIMIT if name in WRITE_TOOLS else READ_TOOL_LIMIT

                    if success_counts[name] > limit:
                        return (
                            f"抱歉，我在处理这个请求时反复尝试了多次，"
                            f"工具「{name}」已成功调用 {success_counts[name]} 次，"
                            f"但结果始终未能让流程继续。\n\n"
                            f"最后一次工具返回：{result[:200]}\n\n"
                            f"建议：请确认你的请求是否明确，或换一种说法再试。"
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