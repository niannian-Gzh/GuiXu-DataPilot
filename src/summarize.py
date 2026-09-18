
from config import setting
from llm import LLM


SUMMARIZE_PROMPT = """你是一个数据助手。请根据用户问题和查询结果，用简洁的中文回答问题。

规则：
1. 只基于提供的数据回答，不要添加数据中没有的信息
2. 不要编造任何项目名、人名、数字
3. 用自然语言或列表表达，不要输出 markdown 表格

用户问题：{question}

查询结果（共 {total} 行）：
{data}
"""

BIG_RESULT_PROMPT = """用户的问题是：{question}

查询结果共 {total} 行，以下是前 {shown} 行：
{data}

请用一两句话总结这个查询结果。不要列举所有数据，只做概括性的描述。"""

EMPTY_ANSWER = """没有找到符合条件的数据。

可能的原因：
- 数据中不存在符合该条件的记录
- 查询条件描述可能有歧义，请尝试换一种说法"""



def summarize(question: str, df, llm: LLM) -> str:
    total = len(df)

    # 情况1：空结果 → 固定模板
    if total == 0:
        return EMPTY_ANSWER

    # 情况2：1-20 行 → LLM 组织语言
    if total <= setting("display.max_llm_rows"):
        data_str = df.to_string(index=False)
        prompt = SUMMARIZE_PROMPT.format(
            question=question, total=total, data=data_str
        )
        return llm.chat("你是一个数据助手", prompt)

    # 情况3：>20 行 → 程序截断 + LLM 一句总结
    preview = df.head(setting("display.max_llm_rows")).to_string(index=False)
    prompt = BIG_RESULT_PROMPT.format(
        question=question, total=total, shown=setting("display.max_llm_rows"), data=preview
    )
    summary = llm.chat("你是一个数据助手", prompt)
    return (
        f"{summary}\n\n"
        f"（共 {total} 条记录，此处仅显示前 {setting("display.max_llm_rows")} 条。"
        f"如需完整数据，请缩小查询范围。）"
    )


if __name__ == "__main__":
    import duckdb
    import yaml
    from config import load_config, resolve, resolve_db_url

    cfg = load_config()["data"]
    db_path = resolve_db_url()

    con = duckdb.connect(db_path, read_only=True)
    df = con.execute(
        f"SELECT project_name, owner, reject_count FROM {cfg['table_name']} "
        "WHERE is_certified = true LIMIT 5"
    ).fetchdf()
    con.close()

    llm = LLM()

    print("=== 测试1：小结果 ===")
    print(summarize("已下证的项目有哪些？", df, llm))

    print("\n=== 测试2：空结果 ===")
    print(summarize("不存在的人的项目", df.head(0), llm))