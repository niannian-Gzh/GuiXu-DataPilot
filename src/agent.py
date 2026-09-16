import json
import time
from datetime import date
from tools import TOOL_SCHEMAS, build_tool_functions, dispatch
from services import UserInputRequired


READ_TOOL_LIMIT = 3
WRITE_TOOL_LIMIT = 2
WRITE_TOOLS = {"request_create", "request_update", "request_delete", "request_batch_create"}
LOOP_TIMEOUT = 240     # Agent Loop 总超时（秒）
COMPACT_THRESHOLD = 500_000    # 50% of 1M
KEEP_RECENT_TURNS = 6


SYSTEM_PROMPT = """你是 DataPilot，一个数据助手。工具是你与数据世界交互的途径。

原则：
1. 自主组合工具达成目标，这是合理规划，不是降级。
2. 不欺骗用户：目标未达成时，如实告知进展。
3. 不编造数据：所有数据来自工具返回。
4. 不猜测：问题不明确时，直接提问。
5. 信任工具结果，不要反复重试同一个操作。
6. 如果工具返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。

用简洁的中文回答。

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
    # 压缩检查
    if session.should_compact(COMPACT_THRESHOLD):
        print(f"  [上下文压缩] 归档并压缩历史对话")
        session.archive(reason="token_threshold")
        session.compact(llm, keep_recent=KEEP_RECENT_TURNS)

    start_time = time.time()
    functions = build_tool_functions(llm, db_path, table_name, trace)

    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())}]
    messages.extend(session.get_history())
    messages.append({"role": "user", "content": user_input})

    success_counts = {}
    failure_counts = {}

    for i in range(max_iterations):
        if time.time() - start_time > LOOP_TIMEOUT:
            return f"处理超时（超过 {LOOP_TIMEOUT} 秒），请简化请求或稍后重试。"

        msg, usage = llm.chat_messages(messages, tools=TOOL_SCHEMAS)
        if usage:
            session.set_prompt_tokens(usage["prompt_tokens"])

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
                            f"抱歉，我在处理这个请求时反复尝试了多次，未能完成。\n\n"
                            f"> 工具「{name}」已成功调用 {success_counts[name]} 次，结果始终不理想\n\n"
                            f"**建议**：请确认你的请求是否明确，或换一种说法再试。"
                        )
                elif _is_security_error(result):
                    # 安全拒绝：不计数，交由 agent 处理
                    pass
                else:
                    # 异常熔断：失败的调用
                    failure_counts[name] = failure_counts.get(name, 0) + 1
                    if failure_counts[name] > limit:
                        return (
                            f"抱歉，工具「{name}」已连续失败 {failure_counts[name]} 次，无法完成请求。\n\n"
                            f"> 最后一次错误：{result[:200]}\n\n"
                            f"**建议**：请检查请求是否合理，或稍后重试。"
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