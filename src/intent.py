from llm import LLM
from guard import check_intent_safety


INTENT_SYSTEM = """你是一个意图判断器。判断用户的问题属于哪一类。

分类定义：

1. QUERY - 明确的数据查询意图。用户想查询项目数据。
   例：张三负责的项目有几个
   例：已下证的项目有哪些
   例：那李四呢
   例：打回次数最多的项目是哪个

2. CLARIFY - 意图模糊，无法确定用户想查什么。用户说的话不能直接翻译成查询。
   例：全没用了
   例：这些都要处理一下
   例：看看情况
   例：帮我搞一下

3. CHITCHAT - 打招呼、闲聊、与数据无关的内容。
   例：你好
   例：你是谁
   例：今天天气怎么样

输出格式（严格按格式，第一行必须是标签）：
- QUERY：只输出一行 QUERY
- CLARIFY：第一行输出 CLARIFY，第二行输出你想问用户的澄清问题
- CHITCHAT：只输出一行 CHITCHAT

注意：不要输出任何其他内容。"""


CHITCHAT_REPLY = (
    "你好，我是 DataPilot。我可以帮你查询项目数据，"
    "试试问我「已下证的项目有哪些」或「张三负责的项目有几个」。"
)


def classify(question: str, llm: LLM) -> dict:
    """判断意图。返回 {"intent": "...", "message": "..."}。

    intent 取值：QUERY / CLARIFY / CHITCHAT / UNSUPPORTED
    """
    # 第一层：规则筛选（写操作直接拒绝，不调 LLM）
    ok, reason = check_intent_safety(question)
    if not ok:
        return {"intent": "UNSUPPORTED", "message": reason}

    # 第二层：LLM 判断
    raw = llm.chat(INTENT_SYSTEM, question).strip()
    lines = [l.strip() for l in raw.split("\n") if l.strip()]

    # 兜底：模型没返回有效内容，默认当查询
    if not lines:
        return {"intent": "QUERY"}

    label = lines[0].upper()

    if label.startswith("QUERY"):
        return {"intent": "QUERY"}

    if label.startswith("CLARIFY"):
        msg = lines[1] if len(lines) > 1 else "能否具体说说你想查询什么？"
        return {"intent": "CLARIFY", "message": msg}

    if label.startswith("CHITCHAT"):
        return {"intent": "CHITCHAT", "message": CHITCHAT_REPLY}

    # 未知标签，兜底当查询
    return {"intent": "QUERY"}


if __name__ == "__main__":
    llm = LLM()

    tests = [
        "张三负责的项目有几个",
        "那李四呢",
        "全没用了",
        "你好",
        "你把项目A删掉",
        "打回次数最多的项目是哪个",
        "这些都要处理一下",
    ]

    for q in tests:
        result = classify(q, llm)
        print(f"{q:20s} → {result}")