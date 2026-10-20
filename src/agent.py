import json
import time
from datetime import date
from tools import TOOL_SCHEMAS, build_tool_functions, dispatch
from services import UserInputRequired
from config import setting
from runner import using
from storage import render


WRITE_TOOLS = {
    "request_create", "request_update", "request_delete",
    "request_batch_create", "transform_data", "add_column",
    "request_restore", "request_import",
}

SYSTEM_PROMPT = """你是归墟（GuiXu），一个数据处理 Agent。工具是你与数据世界交互的途径。

当前数据源包含以下表：
{tables}

调用工具时，table_name 从这里选一个。

原则：
1. 自主组合工具达成目标，这是合理规划，不是降级。
2. 不欺骗用户：目标未达成时，如实告知进展。
3. 不编造数据：所有数据来自工具返回。
4. 不猜测：问题不明确、或要在几个方向里选时，调用 ask_user 工具提问。
   不要只在回答里反问——那样这一轮就结束了，用户回答后你接不上；
   ask_user 会挂起流程，用户答完你能拿着答案继续做。
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


def run_agent(user_input: str, session, llm, trace,
              max_iterations: int = 10, emit=None,
              resume: dict = None, tool_result: str = ""):
    """Agent 主循环。emit 是可选的事件接收器，用于把过程推给前端。

    **resume 是中断后的续跑入口。** 用户回答中断问题后，把那个回答
    伪装成那次工具调用的返回（`tool_result`），接在这轮对话的断点上
    继续跑——模型始终看到自己调过什么、拿到了什么，不必重新理解一遍。

    断点存在 pending 的 `resume` 里，只管「这一轮已经发生过的消息」，
    system prompt 和更早的历史每次重新组装（它们是可推导的，存下来
    反而会和 session 历史重复，越滚越多）。
    """
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
    functions = build_tool_functions(llm, trace)

    # 库里全部的表定义，完整给——不是只给一个表名清单。
    # design 工具层：查看表结构不是工具，是上下文（Agent 总是看得见）。
    # 空库时 render 会明说"数据库当前没有任何表"，模型不会自己编表名。
    tables_list = using(render)
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(
        today=date.today().isoformat(),
        tables=tables_list,
    )}]
    # 用户那条由 api 在轮次开始时 add_user，get_history() 已经带出来了。
    # **这里不再 append**——以前两处各加一次，同一个问题每轮发两遍
    messages.extend(session.get_history())

    # 断点之后的片段从这一刀开始算。续跑时只接这一截，
    # system 和更早的历史由上面重新组装——它们是可推导的，
    # 存进断点只会和 session 历史重复
    base_len = len(messages)
    segment_start = base_len

    start_round = 0
    if resume:
        start_round = resume.get("round", 0)
        messages.extend(resume.get("messages") or [])
        # 挂起的那个工具，用续体的结果补上它的 tool 返回
        messages.append({
            "role": "tool",
            "tool_call_id": resume["call"]["id"],
            "content": tool_result,
        })
        # 同一批里排在它后面、还没来得及执行的工具：显式说明没执行。
        # 不能直接丢——assistant 的 tool_calls 里列了它们，缺了 API 会报错
        for cid in resume.get("skipped") or []:
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": json.dumps({
                    "ok": False,
                    "error": "因前一个操作需要用户确认，本次未执行",
                    "error_type": "skipped",
                }, ensure_ascii=False),
            })
    # 非续跑时不需要再补 user——上面 get_history() 的最后一条就是它

    success_counts = {}
    failure_counts = {}
    tool_log = list(resume.get("tool_log") or []) if resume else []
    reasoning_log = list(resume.get("reasoning_log") or []) if resume else []

    for i in range(max_iterations):
        round_no = start_round + i + 1
        if time.time() - start_time > loop_timeout:
            return _finish(emit, f"处理超时（超过 {loop_timeout} 秒），请简化请求或稍后重试。")

        _emit(emit, "think", round=round_no)
        msg, usage, reasoning = llm.chat_messages(messages, tools=TOOL_SCHEMAS)
        if usage:
            session.set_prompt_tokens(usage["prompt_tokens"])
        if reasoning:
            _emit(emit, "reasoning", round=round_no, text=reasoning)
            reasoning_log.append({"round": round_no, "text": reasoning})
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

            for ci, tc in enumerate(msg.tool_calls):
                name = tc.function.name
                limit = write_limit if name in WRITE_TOOLS else read_limit

                print(f"  [工具] {name}({tc.function.arguments})")
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                _emit(emit, "tool_call", round=round_no, call_id=tc.id, name=name, args=args)

                tool_start = time.time()
                try:
                    result = dispatch(name, args, functions)
                except UserInputRequired as e:
                    # 工具要求先问用户。把这一轮的对话片段存成断点——
                    # 用户回答后由 run_agent(resume=...) 从这个位置接上，
                    # 回答会伪装成这次工具调用的返回
                    e.pending_action.setdefault("user_input", user_input)
                    e.pending_action.setdefault("trace_id", trace.id)
                    e.pending_action["resume"] = {
                        "messages": messages[segment_start:],
                        "call": {"id": tc.id, "name": name},
                        # 同一批里排在它后面的工具，续跑时补一条「未执行」
                        "skipped": [c.id for c in msg.tool_calls[ci + 1:]],
                        "tool_log": tool_log,
                        "reasoning_log": reasoning_log,
                        "round": round_no,
                    }
                    raise
                elapsed_ms = int((time.time() - tool_start) * 1000)

                _emit(emit, "tool_result",
                      call_id=tc.id, name=name,
                      ok=_is_success(result),
                      security=_is_security_error(result),
                      elapsed_ms=elapsed_ms,
                      raw=result[:tool_result_limit])

                tool_log.append({
                    "round": round_no,  # 回放时靠它把思考插回原位，否则顺序对不上
                    "name": name,
                    "args": args,
                    "ok": _is_success(result),
                    "security": _is_security_error(result),
                    "ms": elapsed_ms,
                    "raw": result[:tool_result_limit],
                })

                if _is_success(result):
                    # 思维熔断：按 (工具名 + 参数) 计数。
                    # 按工具名累计会误杀探索——LLM 换了参数的调用是"新操作"，
                    # 不是绕圈。只有完全相同的调用反复才是真卡住。
                    call_key = f"{name}::{tc.function.arguments}"
                    success_counts[call_key] = success_counts.get(call_key, 0) + 1
                    if success_counts[call_key] > limit:
                        return _finish(emit, (
                            f"抱歉，我在处理这个请求时反复尝试了多次，未能完成。\n\n"
                            f"> 工具「{name}」以相同参数已成功调用 {success_counts[call_key]} 次，"
                            f"结果始终不理想\n\n"
                            f"**建议**：请确认你的请求是否明确，或换一种说法再试。"
                        ))
                elif _is_security_error(result):
                    # 安全拒绝：不计数，交由 agent 处理
                    pass
                else:
                    # 异常熔断：失败也按 (工具名 + 参数) 计数——
                    # 参数不同说明 LLM 在换策略，不该算作重试
                    fail_key = f"{name}::{tc.function.arguments}"
                    failure_counts[fail_key] = failure_counts.get(fail_key, 0) + 1
                    if failure_counts[fail_key] > limit:
                        return _finish(emit, (
                            f"抱歉，工具「{name}」以相同参数已连续失败 "
                            f"{failure_counts[fail_key]} 次，无法完成请求。\n\n"
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
        # 只加助手那条：用户那条在 api.chat() 的一轮开始处就加了，
        # 那样「问」和「答」两个时间戳才分得开
        session.add_assistant(answer, tools=tool_log, reasonings=reasoning_log)
        return _finish(emit, answer)

    return _finish(emit, "[达到最大循环次数，强制结束]")