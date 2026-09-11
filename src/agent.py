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

当前日期：{today}"""


def run_agent(user_input: str, session, llm, db_path: str, table_name: str, trace, max_iterations: int = 10):
    """Agent 主循环。返回最终回答。可能抛 UserInputRequired。"""
    functions = build_tool_functions(llm, db_path, table_name, trace)

    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())}]
    messages.extend(session.get_history())
    messages.append({"role": "user", "content": user_input})

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
                print(f"  [工具] {tc.function.name}({tc.function.arguments})")
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                result = dispatch(tc.function.name, args, functions)

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