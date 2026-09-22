import json
import time
from datetime import date
from tools import TOOL_SCHEMAS, build_tool_functions, dispatch
from services import UserInputRequired
from config import setting


WRITE_TOOLS = {
    "request_create", "request_update", "request_delete",
    "request_batch_create", "transform_data", "add_column",
    "request_restore", "request_import",
}

SYSTEM_PROMPT = """你是 DataPilot，一个数据处理 Agent。工具是你与数据世界交互的途径。

原则：
1. 自主组合工具达成目标，这是合理规划，不是降级。
2. 不欺骗用户：目标未达成时，如实告知进展。
3. 不编造数据：所有数据来自工具返回。
4. 不猜测：问题不明确时，直接提问。
5. 信任工具结果，不要反复重试同一个操作。
6. 如果工具返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。

用简洁的中文回答，思考过程也必须用中文。

输出用 Markdown：**加粗**、表格、列表、`行内代码` 都可用。
不要用 *斜体* 和 _下划线_ 做强调——中文句子里这些标记经常识别不出来，
会原样显示成符号，反而更乱。需要强调就用 **加粗**。

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


def _emit(sink, type_: str, **payload):
    """推送一个执行事件。sink 为空时静默，CLI 不受影响。"""
    if sink:
        sink({"type": type_, **payload})


def _finish(sink, text: str) -> str:
    """收尾回答：既作为返回值给 CLI，也作为事件给前端。"""
    _emit(sink, "answer", content=text)
    return text


def run_agent(user_input: str, session, llm, db_path: str, table_name: str, trace,
              max_iterations: int = 10, emit=None):
    """Agent 主循环。emit 是可选的事件接收器，用于把过程推给前端。"""
    # 每轮开始时读一次配置，改完设置不必重启
    loop_timeout = setting("agent.loop_timeout")
    read_limit = setting("agent.read_tool_limit")
    write_limit = setting("agent.write_tool_limit")
    tool_result_limit = setting("agent.tool_result_limit")

    # 压缩检查
    if session.should_compact(setting("agent.compact_threshold")):
        print(f"  [上下文压缩] 归档并压缩历史对话")
        _emit(emit, "compact", message="上下文接近上限，正在归档并压缩历史对话")
        session.archive(reason="token_threshold")
        session.compact(llm, keep_recent=setting("agent.keep_recent_turns"))

    start_time = time.time()
    functions = build_tool_functions(llm, db_path, table_name, trace)

    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())}]
    messages.extend(session.get_history())
    messages.append({"role": "user", "content": user_input})

    success_counts = {}
    failure_counts = {}
    tool_log = []       # 这一轮走过的工具，存进会话供界面回看
    reasoning_log = []  # 这一轮的思考链，同上

    for i in range(max_iterations):
        if time.time() - start_time > loop_timeout:
            return _finish(emit, f"处理超时（超过 {loop_timeout} 秒），请简化请求或稍后重试。")

        _emit(emit, "think", round=i + 1)
        msg, usage, reasoning = llm.chat_messages(messages, tools=TOOL_SCHEMAS)
        if usage:
            session.set_prompt_tokens(usage["prompt_tokens"])
        if reasoning:
            _emit(emit, "reasoning", round=i + 1, text=reasoning)
            reasoning_log.append({"round": i + 1, "text": reasoning})
        if msg.tool_calls:
            assistant_msg = {
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
            }
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            messages.append(assistant_msg)

            for tc in msg.tool_calls:
                name = tc.function.name
                limit = write_limit if name in WRITE_TOOLS else read_limit

                print(f"  [工具] {name}({tc.function.arguments})")
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                _emit(emit, "tool_call", round=i + 1, call_id=tc.id, name=name, args=args)

                tool_start = time.time()
                result = dispatch(name, args, functions)
                elapsed_ms = int((time.time() - tool_start) * 1000)

                _emit(emit, "tool_result",
                      call_id=tc.id, name=name,
                      ok=_is_success(result),
                      security=_is_security_error(result),
                      elapsed_ms=elapsed_ms,
                      raw=result[:tool_result_limit])

                tool_log.append({
                    "round": i + 1,     # 回放时靠它把思考插回原位，否则顺序对不上
                    "name": name,
                    "args": args,
                    "ok": _is_success(result),
                    "security": _is_security_error(result),
                    "ms": elapsed_ms,
                    "raw": result[:tool_result_limit],
                })

                if _is_success(result):
                    # 思维熔断：成功的调用
                    success_counts[name] = success_counts.get(name, 0) + 1
                    if success_counts[name] > limit:
                        return _finish(emit, (
                            f"抱歉，我在处理这个请求时反复尝试了多次，未能完成。\n\n"
                            f"> 工具「{name}」已成功调用 {success_counts[name]} 次，结果始终不理想\n\n"
                            f"**建议**：请确认你的请求是否明确，或换一种说法再试。"
                        ))
                elif _is_security_error(result):
                    # 安全拒绝：不计数，交由 agent 处理
                    pass
                else:
                    # 异常熔断：失败的调用
                    failure_counts[name] = failure_counts.get(name, 0) + 1
                    if failure_counts[name] > limit:
                        return _finish(emit, (
                            f"抱歉，工具「{name}」已连续失败 {failure_counts[name]} 次，无法完成请求。\n\n"
                            f"> 最后一次错误：{result[:200]}\n\n"
                            f"**建议**：请检查请求是否合理，或稍后重试。"
                        ))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        answer = msg.content or ""
        session.add_user(user_input)
        session.add_assistant(answer, tools=tool_log, reasonings=reasoning_log)
        return _finish(emit, answer)

    return _finish(emit, "[达到最大循环次数，强制结束]")