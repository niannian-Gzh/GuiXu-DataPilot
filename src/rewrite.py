from llm import LLM
from session import Session


REWRITE_SYSTEM = """你是一个查询改写器。你的任务是判断当前问题是否依赖上下文，如果依赖，就补全成独立问题；如果不依赖，原样返回。

判断规则：
1. 只有当问题包含明确指代词时，才需要改写。指代词包括："那...呢"、"还有"、"这个"、"那个"、"也"、"同样"、"他们"等。
2. 如果问题本身语义完整，即使提到历史里出现过的人名、分类、字段，也原样返回，不要添加历史里的信息。
3. 不确定时，原样返回。宁可漏改，不可过度改写。

示例：

历史：
- 张三负责的项目有几个？

当前问题：那李四呢？
输出：李四负责的项目有几个？

历史：
- 张三负责的项目有几个？

当前问题：打回次数最多的项目是哪个？
输出：打回次数最多的项目是哪个？

历史：
- 张三负责的项目有几个？

当前问题：这个人的项目里有多少已下证？
输出：张三负责的项目里有多少已下证？

---

历史问题：
{history}

当前问题：{question}

改写后的完整问题（只返回一行，不要解释）："""

MAX_HISTORY = 3


def rewrite(question: str, session: Session, llm: LLM) -> str:
    """把依赖上下文的问题改写成独立完整的问题。首轮直接返回原问题。"""
    user_msgs = [m["content"] for m in session.get_history() if m["role"] == "user"]

    if not user_msgs:
        return question

    recent = user_msgs[-MAX_HISTORY:]
    history_text = "\n".join(f"- {q}" for q in recent)

    prompt = REWRITE_SYSTEM.format(history=history_text, question=question)
    rewritten = llm.chat("你是一个查询改写器", prompt).strip()

    # 兜底1：结果为空，返回原问题
    if not rewritten:
        return question

    # 兜底2：结果过长（可能是模型在解释而不是改写），返回原问题
    if len(rewritten) > len(question) * 5:
        return question

    # 兜底3：结果包含换行（要求只返回一行），取第一行
    if "\n" in rewritten:
        rewritten = rewritten.split("\n")[0].strip()

    return rewritten


if __name__ == "__main__":

    llm = LLM()
    s = Session()

    # 场景1：首轮，无历史
    print("首轮：", rewrite("张三负责的项目有几个？", s, llm))

    # 场景2：模拟多轮
    s.add_user("张三负责的项目有几个？")
    s.add_assistant("张三负责的项目有64个。")
    print("追问：", rewrite("那李四呢？", s, llm))

    # 场景3：独立问题（改写器不该动它）
    print("独立：", rewrite("打回次数最多的项目是哪个？", s, llm))