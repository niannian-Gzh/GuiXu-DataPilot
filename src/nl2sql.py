import duckdb
import yaml
from datetime import date
from llm import LLM
from execute import execute_sql
from guard import check_sql_safety, SecurityError
import logging
from config import load_config


SCHEMA_DESC = {
    "project_name": "项目名称",
    "owner": "负责人姓名（人名，例如张三、李四）",
    "status_raw": "原始状态文本，可能是：已提交 / 已结算 / 已结算已打回 / 已结算已下证 / 已打回待提交",
    "issued_date": "项目下发时间",
    "certified_date": "项目下证时间（拿到证书的时间，可能为空）",
    "category": "项目分类，取值：web / 嵌入式",
    "resubmit_name": "重提项目时使用的原项目名，不是人名，通常为空",
    "reject_date": "最近一次被打回的时间（可能为空）",
    "resubmit_date": "被打回后重新提交的时间（可能为空）",
    "reject_count": "被打回的次数，整数",
    "is_pending": "是否待提交（布尔值 true/false）",
    "is_submitted": "是否已提交",
    "is_rejected": "是否被打回",
    "is_settled": "是否已结算",
    "is_certified": "是否已下证",
}


SYSTEM_PROMPT = """你是一个SQL生成助手。用户会用自然语言提问，你需要生成一条DuckDB兼容的SQL查询语句。

规则：
1. 只返回SQL语句本身，不要解释、不要markdown代码块、不要结尾分号
2. 只生成 SELECT 查询，禁止 DELETE / UPDATE / INSERT / DROP
3. 严格使用下面提供的表名和列名，不要臆造
4. 当前日期是 {today}，如果用户说"上个月""本周"等，以此为基准

表名：{table_name}

表结构：
{schema}
"""

FIX_PROMPT = """你上次生成的SQL执行失败了，请修正。

原始问题：{question}

上次生成的SQL：
{sql}

数据库报错：
{error}

请返回修正后的SQL。只返回SQL，不要解释。"""



def get_schema(db_path: str, table_name: str) -> str:
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute(f"DESCRIBE {table_name}").fetchall()
    con.close()

    lines = []
    for r in rows:
        col_name, col_type = r[0], r[1]
        desc = SCHEMA_DESC.get(col_name, "")
        lines.append(f"  - {col_name} ({col_type}): {desc}")
    return "\n".join(lines)


def _clean_sql(sql: str) -> str:
    sql = sql.strip()
    if sql.startswith("```"):
        lines = [l for l in sql.split("\n") if not l.startswith("```")]
        sql = "\n".join(lines).strip()
    return sql.rstrip(";").strip()


def _build_system(schema: str, table_name: str) -> str:
    return SYSTEM_PROMPT.format(
        schema=schema,
        today=date.today().isoformat(),
        table_name=table_name,
    )


def generate_sql(question: str, llm: LLM, schema: str, table_name: str) -> str:
    return _clean_sql(llm.chat(_build_system(schema, table_name), question))


def fix_sql(question: str, bad_sql: str, error: str, llm: LLM, schema: str, table_name: str) -> str:
    prompt = FIX_PROMPT.format(question=question, sql=bad_sql, error=error)
    return _clean_sql(llm.chat(_build_system(schema, table_name), prompt))


def generate_sql_with_retry(
    question: str, llm: LLM, schema: str, db_path: str, table_name: str, max_retries: int = 2
):
    """返回 (sql, 重试次数)。写操作直接拒绝，不走自修正。"""
    sql = generate_sql(question, llm, schema, table_name)

    # 安全检查：写操作直接拒绝，不进入重试
    ok, reason = check_sql_safety(sql)
    if not ok:
        raise SecurityError(f"{reason}。生成的 SQL：{sql}")

    for attempt in range(max_retries + 1):
        try:
            execute_sql(sql, db_path)
            return sql, attempt
        except Exception as e:
            if attempt == max_retries:
                raise RuntimeError(f"重试 {max_retries} 次后仍失败。最后一次报错：{e}")
            logging.warning(f"[重试 {attempt + 1}] SQL 执行失败：{e}")
            sql = fix_sql(question, sql, str(e), llm, schema, table_name)

            # 修正后再次安全检查（防止 fix_sql 生成写操作）
            ok, reason = check_sql_safety(sql)
            if not ok:
                raise SecurityError(f"修正后的 SQL 仍不安全：{reason}")


if __name__ == "__main__":
    cfg = load_config()["data"]
    llm = LLM()
    schema = get_schema(cfg["db_path"], cfg["table_name"])

    question = "打回次数最多的项目是哪个"
    sql, retries = generate_sql_with_retry(
        question, llm, schema, cfg["db_path"], cfg["table_name"], max_retries=2
    )
    print(f"问题：{question}")
    print(f"SQL：{sql}")
    print(f"重试：{retries} 次")