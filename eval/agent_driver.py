"""Agent 层驱动：跑一问、处理中断、把确认卡片走完。

评测里没有真人点按钮，所以这个 driver 就是那个"人"：
- 确认卡片 → 按 `confirm_hint` 回答「确认」或「删除 N 条」
- ask_user → 给预设答案（用例可以覆盖）
- 取消 → 回「取消」，确认分支续跑，提问分支整轮结束

它只做 api.chat() 做过的事：落结局、清挂起、续跑。**不碰业务逻辑**——
否则测的就不是产品，是这个 driver 了。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from agent import run_agent
from services import UserInputRequired, pending_service
from session import Session
from trace import Trace


@dataclass
class AgentRun:
    question: str
    session: Session
    reply: str = ""
    events: list = field(default_factory=list)
    pendings: list = field(default_factory=list)
    skipped: bool = False

    @property
    def tool_calls(self) -> list[dict]:
        return [e for e in self.events if e.get("type") == "tool_call"]

    @property
    def tool_names(self) -> list[str]:
        return [t.get("name") for t in self.tool_calls]

    def used(self, *names: str) -> bool:
        return any(n in self.tool_names for n in names)

    def final_text(self) -> str:
        """最后一条不是系统警告的助手消息。"""
        for m in reversed(self.session.messages):
            if m.get("role") == "assistant" and not m.get("gx_notice"):
                text = m.get("content") or ""
                if text:
                    return text
        return self.reply


def _default_answer(pending: dict) -> tuple[str, list | None]:
    """模拟一个配合的用户。"""
    ptype = pending.get("type")

    if ptype == "ask":
        questions = pending.get("questions") or [
            {"question": pending.get("question", "")}
        ]
        answers = []
        for q in questions:
            options = q.get("options") or []
            answers.append(options[0] if options else "按你说的来")
        return answers[0] if answers else "按你说的来", answers

    if ptype == "import":
        return "确认导入", None

    # 批量操作会要求「删除 N 条」这种打字确认，enrich_pending 已经算好了
    return pending.get("confirm_hint") or "确认", None


def run_question(env, question: str, plan=None, max_steps: int = 6,
                 max_iterations: int = 10) -> AgentRun:
    """跑一轮问答，自动处理所有中断。"""
    llm = env.box.llm_instance()
    if llm is None:
        from harness import SkipTest
        raise SkipTest("没有可用的模型配置或 key")

    run = AgentRun(question=question, session=Session(f"eval-{uuid.uuid4().hex[:8]}"))
    run.session.add_user(question)
    trace = Trace(question)

    try:
        run.reply = run_agent(
            question, run.session, llm, trace,
            max_iterations=max_iterations, emit=run.events.append,
        )
    except UserInputRequired as e:
        pending = pending_service.enrich_pending(e.pending_action)
        run.session.set_pending(pending)

    steps = 0
    retried_done = False
    while run.session.get_pending() is not None:
        if steps >= max_steps:
            raise AssertionError(f"中断超过 {max_steps} 次还没走完，可能是模型在原地打转")
        steps += 1

        pending = run.session.get_pending()
        run.pendings.append(pending)
        text, answers = (plan or _default_answer)(pending)

        action, payload = pending_service.answer_pending(
            text, run.session, llm, answers=answers,
        )

        if action == "skip":
            run.session.add_confirm(pending_service.settle(pending, payload))
            run.session.clear_pending()
            run.skipped = True
            run.reply = payload
            break

        if action == "resume":
            # 和 api.chat 一样：结局先落盘，再续跑
            run.session.add_confirm(pending_service.settle(pending, payload))
            run.session.clear_pending()
            try:
                run.reply = run_agent(
                    question, run.session, llm, trace,
                    max_iterations=max_iterations, emit=run.events.append,
                    resume=pending.get("resume"), tool_result=payload,
                )
            except UserInputRequired as e:
                run.session.set_pending(pending_service.enrich_pending(e.pending_action))
            continue

        # done：直接给用户的一句话（确认没通过 / 导入看详情）
        run.session.add_assistant(payload)
        run.reply = payload
        if run.session.get_pending() is not None and not retried_done:
            # 确认没通过之类的情况：再明确回一次，别让用例死在"没听懂"
            retried_done = True
            continue
        run.session.clear_pending()
        break

    return run


def tool_args(run: AgentRun, name: str) -> list[dict]:
    return [t.get("args") or {} for t in run.tool_calls if t.get("name") == name]
