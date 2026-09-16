from nl2sql import generate_filter_sql
from execute import execute_sql


def find_candidates(filter_question: str, ctx) -> list:
    """按自然语言筛选条件查找候选记录。返回 dict 列表。"""
    sql = generate_filter_sql(filter_question, ctx.llm, ctx.schema, ctx.table_name)
    df = execute_sql(sql, ctx.db_path)
    return df.to_dict("records")