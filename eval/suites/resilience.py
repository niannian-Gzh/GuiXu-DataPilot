"""D6 韧性：畸形参数、熔断、超时、重试、压缩。

这一层全用假模型。**假模型不是作弊**——要测的是循环自己的判断，
真模型反而让"第几次停"变得不可复现。
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from agent import run_agent
from config import get_config, save_config
from harness import case, check, eq
from services import ServiceContext
from session import Session
from trace import Trace


class _Msg:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls
        self.content = content


class _Fn:
    def __init__(self, name, args):
        self.name = name
        self.arguments = json.dumps(args, ensure_ascii=False)


class _Call:
    def __init__(self, cid, name, args):
        self.id = cid
        self.type = "function"
        self.function = _Fn(name, args)


class FakeLLM:
    """控制每一次 chat_messages 返回什么。"""

    mock = False
    capabilities = {"context_window": 32000, "reasoning_echo": False,
                    "tool_calling": True}

    def __init__(self, sql="SELECT count(*) FROM devices", calls=None,
                 delay=0.0):
        self.sql = sql
        self.calls = calls or []          # 每轮返回的 tool_calls；用尽后回文字
        self.delay = delay
        self.round = 0

    def chat(self, system, user):
        return self.sql

    def chat_messages(self, messages, tools=None):
        if self.delay:
            time.sleep(self.delay)
        idx = self.round
        self.round += 1
        if idx < len(self.calls):
            return _Msg(tool_calls=[self.calls[idx]]), {
                "prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
            }, None
        return _Msg(content="已经完成。"), None, None


def _set_setting(key: str, value):
    path = key.split(".")
    cfg = get_config()
    node = cfg
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node[path[-1]] = value
    save_config(cfg)


def _new_session(text="数一下设备"):
    s = Session("resilience")
    s.add_user(text)
    return s


# ============================================================ 参数兜底

@case("D6", "未知工具名不击穿整轮", 'dispatch("no_such_tool")', "ok=false, error_type=invalid")
def dispatch_unknown_tool(env):
    from tools import build_tool_functions, dispatch
    funcs = build_tool_functions(FakeLLM(), Trace("dispatch"))
    data = json.loads(dispatch("no_such_tool", {}, funcs))
    eq(data.get("ok"), False)
    eq(data.get("error_type"), "invalid")


@case("D6", "参数不是对象不击穿整轮", "dispatch(..., None)", "invalid_arguments")
def dispatch_non_dict(env):
    from tools import build_tool_functions, dispatch
    funcs = build_tool_functions(FakeLLM(), Trace("dispatch"))
    data = json.loads(dispatch("query_database", None, funcs))
    eq(data.get("error_type"), "invalid_arguments")


@case("D6", "缺参数不击穿整轮", "query_database 少了 question", "invalid_arguments")
def dispatch_missing_arg(env):
    from tools import build_tool_functions, dispatch
    funcs = build_tool_functions(FakeLLM(), Trace("dispatch"))
    data = json.loads(dispatch(
        "query_database", {"table_name": "devices"}, funcs,
    ))
    eq(data.get("error_type"), "invalid_arguments")


@case("D6", "多参数不击穿整轮", "query_database 多给一个字段", "invalid_arguments")
def dispatch_extra_arg(env):
    from tools import build_tool_functions, dispatch
    funcs = build_tool_functions(FakeLLM(), Trace("dispatch"))
    data = json.loads(dispatch(
        "query_database",
        {"table_name": "devices", "question": "有多少", "extra": 1},
        funcs,
    ))
    eq(data.get("error_type"), "invalid_arguments")


# ============================================================ 闸门拒绝的出口

@case("D4", "闸门拒绝要变成工具返回", "模型生成 SELECT * FROM devices_all",
      "query_service 返回 error_type=security，而不是抛异常打翻整轮")
def gate_rejection_is_tool_error(env):
    from services import query_service
    ctx = ServiceContext(
        llm=FakeLLM(sql="SELECT * FROM devices_all"), trace=Trace("越权查询"),
    ).for_table("devices")
    try:
        out = query_service.run("把所有设备列出来", ctx)
    except Exception as e:
        raise AssertionError(
            f"闸门拒绝冒成了 {type(e).__name__}，整轮会被 api 兜底成「出错了」"
        )
    data = json.loads(out)
    eq(data.get("ok"), False)
    eq(data.get("error_type"), "security")


# ============================================================ 熔断

@case("D6", "同一调用反复成功会熔断", "连续 7 次相同的 query_database",
      "第 7 次后强制结束，不再烧模型")
def circuit_breaker_success(env):
    same = {"table_name": "devices", "question": "有多少台"}
    calls = [_Call(f"c{i}", "query_database", same) for i in range(12)]
    llm = FakeLLM(calls=calls)
    s = _new_session()
    reply = run_agent("数一下设备", s, llm, Trace("熔断"), max_iterations=12)

    check("反复尝试" in reply, f"没有触发熔断：{reply[:200]}")
    tools = s.messages[-1].get("gx_tools") or []
    eq(len(tools), 7, "熔断点在 read_tool_limit(6) 之后的第 7 次")
    eq(llm.round, 7, "熔断后又调了模型")


@case("D6", "参数变了不算绕圈", "每次 query_database 的 question 都不同",
      "不触发熔断，正常走完")
def circuit_breaker_parameter_change(env):
    calls = [
        _Call(f"c{i}", "query_database",
              {"table_name": "devices", "question": f"第{i}次统计"})
        for i in range(8)
    ]
    llm = FakeLLM(calls=calls)
    s = _new_session()
    reply = run_agent("多次统计", s, llm, Trace("不熔断"), max_iterations=10)
    check("反复尝试" not in reply, f"换了参数还被当成绕圈：{reply[:200]}")


@case("D6", "到上限强制结束也要回写历史", "max_iterations=2，模型一直调工具",
      "返回强制结束，助手消息落进 session")
def max_iterations_end(env):
    calls = [
        _Call(f"c{i}", "query_database",
              {"table_name": "devices", "question": f"不同问题{i}"})
        for i in range(5)
    ]
    llm = FakeLLM(calls=calls)
    s = _new_session()
    before = len(s.messages)
    reply = run_agent("一直查", s, llm, Trace("上限"), max_iterations=2)
    check("最大循环次数" in reply, f"没有强制结束：{reply[:200]}")
    eq(len(s.messages), before + 1, "强制结束没有回写助手消息")
    eq(s.messages[-1]["role"], "assistant")


# ============================================================ 超时

@case("D6", "单轮超时掐断并回写", "模型每次思考 1.2 秒，超时设 1 秒",
      "第二轮检查时结束，返回超时说明")
def loop_timeout(env):
    _set_setting("agent.loop_timeout", 1)
    llm = FakeLLM(
        calls=[_Call("c1", "query_database",
                     {"table_name": "devices", "question": "有多少"})],
        delay=1.2,
    )
    s = _new_session()
    before = len(s.messages)
    reply = run_agent("数设备", s, llm, Trace("超时"), max_iterations=5)
    check("处理超时" in reply, f"没有触发超时：{reply[:200]}")
    eq(len(s.messages), before + 1, "超时结束没有回写助手消息")


# ============================================================ 重试

@case("D6", "可重试异常按配置重试", "前两次失败、第三次成功", "调用 3 次后返回")
def retry_on_transient(env):
    import llm as llm_mod

    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    old = llm_mod.RETRYABLE_EXCEPTIONS
    llm_mod.RETRYABLE_EXCEPTIONS = (ValueError,)
    try:
        with patch.object(llm_mod.time, "sleep", lambda _s: None):
            out = llm_mod._call_with_retry(fn)
    finally:
        llm_mod.RETRYABLE_EXCEPTIONS = old

    eq(out, "ok")
    eq(len(calls), 3)


# ============================================================ 压缩

class _SummaryLLM:
    def chat(self, system, user):
        return "用户问了设备数量；助手查过 devices。"


@case("D6", "压缩推进指针但一条消息不删", "40 条消息触发 compact",
      "messages 数量不变，summary_upto 前进")
def compaction_keeps_evidence(env):
    s = Session("compact-eval")
    for i in range(20):
        s.add_user(f"问题{i}")
        s.add_assistant(f"回答{i}")
    before = len(s.messages)
    eq(before, 40)

    s.prompt_tokens = 999999
    check(s.should_compact(1000), "到了阈值却没触发压缩")

    s.compact(_SummaryLLM(), keep_recent=6)
    eq(len(s.messages), before, "压缩删掉了存证")
    eq(s.summary_upto, before - 12, "指针该停在保留的最近 12 条之前")
    check(s.summary, "没有生成摘要")
    eq(s.prompt_tokens, 0, "压缩后 token 计数没清零")


@case("D6", "没到阈值不压缩", "prompt_tokens 很低", "should_compact=False")
def compaction_threshold(env):
    s = Session("compact-threshold")
    for i in range(20):
        s.add_user(f"问题{i}")
        s.add_assistant(f"回答{i}")
    s.prompt_tokens = 1
    check(not s.should_compact(1000), "没到阈值却要压缩")


@case("D6", "最近的消息不压", "只有 10 条且 token 超阈值", "pending 不足 20 条，不压")
def compaction_keeps_recent(env):
    s = Session("compact-recent")
    for i in range(5):
        s.add_user(f"问题{i}")
        s.add_assistant(f"回答{i}")
    s.prompt_tokens = 999999
    check(not s.should_compact(1000), "消息太少也触发了压缩")
