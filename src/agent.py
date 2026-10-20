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
    "transform_data", "add_column",
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
6. 如果工具返回 error_type: "security"，说明这是安全拒绝，不要重试，直接告知用户。

用简洁的中文回答，思考过程也必须用中文。

输出用 Markdown：**加粗**、表格、列表、`行内代码` 都可用。
不要用 *斜体* 和 _下划线_ 做强调——中文句子里这些标记经常识别不出来，
会原样显示成符号，反而更乱。需要强调就用 **加粗**。

当前日期：{today}"""


def _is_success(result_str: str) -> bool:
    """**只看 `ok`。** 不能靠"有没有 error 这个键"去猜——
    那样 `{"status": "not_found"}` 这种没有 error 的返回会被判成成功，
    模型于是以为事情办成了。工具层现在统一带 `ok`，这里照它读。
    """
    try:
        data = json.loads(result_str)
        return data.get("ok") is True
    except (json.JSONDecodeError, AttributeError):
        return False


def _is_security_error(result_str: str) -> bool:
    """安全拒绝。工具层记在 `error_type` 里，不再是早年的 `is_security`。

    提示词里那句"如果返回 is_security: true"是旧版留下的，工具从来没
    返回过这个字段——安全拒绝一直被当成普通失败，既会计入熔断，
    又会让模型以为是自己写错了 SQL。
    """
    try:
        data = json.loads(result_str)
        return data.get("error_type") == "security" or bool(data.get("is_security"))
    except (json.JSONDecodeError, AttributeError):
        return False


def _tool_evidence(result_str: str) -> dict:
    """从工具返回里抽**回放时要看的东西**，不存整段 raw。

    raw 是 8000 字符的截断版，一轮几个工具就是几十 KB，而它九成
    是模型当轮已经看过的数据。留下的是回看时真正会看的：一句结果
    要点、模型写过的 SQL、产出的文件、前几行数据。

    规则抽取，不调 LLM——这些字段本来就是结构化的，问模型一遍
    既费钱又不准。
    """
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}

    if data.get("error_type") == "cancelled":
        # 取消不是失败。模型回看时看到「失败」会以为自己写错了什么；
        # 状态栏已经写着「已取消」，要点就不用再重复一遍
        gist = ""
    elif data.get("ok") is False:
        gist = "失败：" + str(data.get("error") or "")[:60]
    else:
        bits = []
        if data.get("status") == "empty":
            bits.append("空结果")
        if data.get("row_count") is not None:
            bits.append(f"{data['row_count']} 行")
        if data.get("affected") is not None:
            bits.append(f"影响 {data['affected']} 条")
        if data.get("file_path"):
            bits.append(str(data["file_path"]).replace("\\", "/").rsplit("/", 1)[-1])
        if data.get("snapshots") is not None:
            bits.append(f"{len(data['snapshots'])} 个快照")
        gist = "，".join(bits)

    rows = data.get("rows")
    evidence = {
        "gist": gist,
        "sql": data.get("sql") or "",
        "file_path": data.get("file_path") or "",
        "preview": rows[:3] if isinstance(rows, list) else None,
    }
    # 空值不落盘：每条都带一堆 "" 和 null，文件平白多一截
    return {k: v for k, v in evidence.items() if v not in ("", None)}


def resume_entry(resume: dict, tool_result: str) -> dict:
    """续跑时补上**挂起的那次工具调用**。

    它在 dispatch 返回之前就挂了，`tool_log.append` 永远走不到。实时
    界面上那一行是前端把「待确认」改成「成功 / 已取消」画出来的，
    刷新之后就没了——同一轮里卡片还在，工具行却少一条。
    """
    try:
        cancelled = json.loads(tool_result).get("error_type") == "cancelled"
    except (json.JSONDecodeError, TypeError, AttributeError):
        cancelled = False

    entry = {
        "round": resume.get("round", 0),
        "name": resume["call"]["name"],
        "args": resume.get("args") or {},
        "ok": _is_success(tool_result),
        "security": _is_security_error(tool_result),
        **_tool_evidence(tool_result),
    }
    # 用户取消不是「失败」：回放时画成灰色「已取消」，不是红色错误
    if cancelled:
        entry["cancelled"] = True
    return entry


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
    keep_recent = setting("agent.keep_recent_turns")

    # 压缩阈值 = 模型窗口 × 比例。以前是硬编码 500000，换个小窗口的
    # 模型直接撞上限——压缩还没触发，请求先 400 了
    caps = getattr(llm, "capabilities", {}) or {}
    compact_threshold = int(
        (caps.get("context_window") or 32000) * setting("agent.compact_ratio")
    )

    start_time = time.time()
    functions = build_tool_functions(llm, trace)

    # 库里全部的表定义，完整给——不是只给一个表名清单。
    # design 工具层：查看表结构不是工具，是上下文（Agent 总是看得见）。
    # 空库时 render 会明说"数据库当前没有任何表"，模型不会自己编表名。
    tables_list = using(render)
    system_msg = {"role": "system", "content": SYSTEM_PROMPT.format(
        today=date.today().isoformat(),
        tables=tables_list,
    )}
    messages = [system_msg]
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
    if resume and resume.get("call"):
        # 挂起的那次调用，结局就是这次的续体结果
        tool_log.append(resume_entry(resume, tool_result))
    reasoning_log = list(resume.get("reasoning_log") or []) if resume else []

    def _end(text: str) -> str:
        """这一轮结束——**不管怎么结束，都要回写历史。**

        超时、熔断、到上限以前都是直接返回一句话，历史里什么都没有。
        用户看到"处理超时了"，下一轮再问，模型完全不知道自己刚才
        做过什么——"答了却不记得"。
        """
        session.add_assistant(text, tools=tool_log, reasonings=reasoning_log)
        return _finish(emit, text)

    for i in range(max_iterations):
        round_no = start_round + i + 1

        # 压缩检查放进循环：单轮巨任务（一路调十几个工具）也可能把
        # 上下文撑爆，只在循环外查一次等于放过它们
        if session.should_compact(compact_threshold):
            print("  [上下文压缩] 归档并压缩历史对话")
            _emit(emit, "compact", message="上下文接近上限，正在归档并压缩历史对话")
            session.archive(reason="token_threshold")
            session.compact(llm, keep_recent=keep_recent)
            # 前缀变了，断点的起点跟着挪——否则中断时切出来的片段里
            # 会混进已经摘要过的旧消息
            prefix = [system_msg, *session.get_history()]
            messages[:base_len] = prefix
            base_len = len(prefix)
            segment_start = base_len

        if time.time() - start_time > loop_timeout:
            return _end(f"处理超时（超过 {loop_timeout} 秒），请简化请求或稍后重试。")

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
            # 回传 reasoning 前先问能力清单。不认这个字段的服务端会 400，
            # 而 reasoning 本身照常推给界面、记进日志——限制的只是回传
            if reasoning and caps.get("reasoning_echo"):
                assistant_msg["reasoning_content"] = reasoning
            messages.append(assistant_msg)

            for ci, tc in enumerate(msg.tool_calls):
                name = tc.function.name
                limit = write_limit if name in WRITE_TOOLS else read_limit

                print(f"  [工具] {name}({tc.function.arguments})")
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    # 参数不是合法 JSON：明确告诉模型，而不是让它拿空参数
                    # 去撞"缺少必填字段"，那会把它引向一个错误的方向
                    args = None

                _emit(emit, "tool_call", round=round_no, call_id=tc.id, name=name,
                      args=args or {})

                tool_start = time.time()
                if args is None:
                    result = json.dumps({
                        "ok": False,
                        "error": "arguments 不是合法的 JSON",
                        "error_type": "invalid_arguments",
                    }, ensure_ascii=False)
                else:
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
                            # 参数也存下来：续跑后要把它补进工具记录，
                            # 没有参数那一行回放出来就是空的
                            "args": args or {},
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
                    "args": args or {},  # 全量。以前按位置截前 3，会把 table_name 切掉
                    "ok": _is_success(result),
                    "security": _is_security_error(result),
                    "ms": elapsed_ms,
                    # 动作记忆：一句结果要点 + 回放要看的结构化字段。
                    # 不再存 raw——raw 只在这一轮的界面事件里出现
                    **_tool_evidence(result),
                })

                # 熔断按 (工具名 + **规范化参数**) 计数。不能直接用原始
                # arguments 字符串——同样的调用换个键序就是另一个 key，
                # 模型把参数重新序列化一遍就绕过了熔断
                call_key = f"{name}::{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"

                if _is_success(result):
                    # 思维熔断：按 (工具名 + 参数) 计数。
                    # 按工具名累计会误杀探索——LLM 换了参数的调用是"新操作"，
                    # 不是绕圈。只有完全相同的调用反复才是真卡住。
                    success_counts[call_key] = success_counts.get(call_key, 0) + 1
                    if success_counts[call_key] > limit:
                        return _end(
                            f"抱歉，我在处理这个请求时反复尝试了多次，未能完成。\n\n"
                            f"> 工具「{name}」以相同参数已成功调用 {success_counts[call_key]} 次，"
                            f"结果始终不理想\n\n"
                            f"**建议**：请确认你的请求是否明确，或换一种说法再试。"
                        )
                elif _is_security_error(result):
                    # 安全拒绝：不计数，交由 agent 处理
                    pass
                else:
                    # 异常熔断：失败也按 (工具名 + 参数) 计数——
                    # 参数不同说明 LLM 在换策略，不该算作重试
                    failure_counts[call_key] = failure_counts.get(call_key, 0) + 1
                    if failure_counts[call_key] > limit:
                        return _end(
                            f"抱歉，工具「{name}」以相同参数已连续失败 "
                            f"{failure_counts[call_key]} 次，无法完成请求。\n\n"
                            f"> 最后一次错误：{result[:200]}\n\n"
                            f"**建议**：请检查请求是否合理，或稍后重试。"
                        )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        # 只加助手那条：用户那条在 api.chat() 的一轮开始处就加了，
        # 那样「问」和「答」两个时间戳才分得开
        return _end(msg.content or "")

    return _end("[达到最大循环次数，强制结束]")