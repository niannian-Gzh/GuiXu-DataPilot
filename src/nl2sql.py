import duckdb
import yaml
from datetime import date
from llm import LLM
from execute import execute_sql
from guard import check_sql_safety, SecurityError
import logging
from config import load_config, resolve_db_url


SCHEMA_DESC = {
    "project_name": "项目名称",
    "owner": "负责人姓名（人名，例如张三、李四）",
    "status_raw": (
        "原始状态文本，可能值：'已提交' / '已结算' / '已结算已打回' / "
        "'已结算已下证' / '已打回待提交'。这是组合状态。"
        "【何时用】用户说'仅为/只/精确/恰好/就是'某状态时，用这个字段做精确匹配。"
        "其他情况优先使用下面的布尔字段。"
    ),
    "issued_date": "项目下发时间",
    "certified_date": "项目下证时间（拿到证书的时间，可能为空）",
    "category": "项目分类，取值：web / 嵌入式",
    "resubmit_name": "重提项目时使用的原项目名，不是人名，通常为空",
    "reject_date": "最近一次被打回的时间（可能为空）",
    "resubmit_date": "被打回后重新提交的时间（可能为空）",
    "reject_count": "被打回的次数，整数",
    "is_pending": "是否待提交（布尔）。状态包含'待提交'时为 true",
    "is_submitted": "是否已提交（布尔）。状态包含'已提交'时为 true",
    "is_rejected": "是否被打回（布尔）。状态包含'已打回'时为 true",
    "is_settled": (
        "是否已结算（布尔）。状态包含'已结算'时为 true，"
        "包括'已结算已下证'和'已结算已打回'。"
        "【默认用这个】当用户说'已结算'但没有'仅/只/精确'等修饰词时。"
    ),
    "is_certified": "是否已下证（布尔）。状态包含'已下证'时为 true",
    "is_deleted": "是否已被软删除（布尔）。true 表示这条记录已被删除、等待恢复或等待清理",
    "deleted_at": "删除时间（可能为空）",
    "deleted_by": "执行删除的操作者",
    "delete_trace_id": "删除操作的追踪 ID，同一次删除的记录共享同一个 ID",
}


SYSTEM_PROMPT = """你是一个SQL生成助手。用户会用自然语言提问，你需要生成一条DuckDB兼容的SQL查询语句。

规则：
1. 只返回SQL语句本身，不要解释、不要markdown代码块、不要结尾分号
2. 只生成 SELECT 查询，禁止 DELETE / UPDATE / INSERT / DROP
3. 严格使用下面提供的表名和列名，不要臆造
4. 当前日期是 {today}，如果用户说"上个月""本周"等，以此为基准
5. **状态筛选规则（重要）**：
   - 默认情况：用户说"已结算"、"已下证"、"已打回"、"待提交"、"已提交"时，
     使用对应的布尔字段（is_settled / is_certified / is_rejected / is_pending / is_submitted）。
     这表示"包含匹配"——比如"已结算"包含"已结算已下证"和"已结算已打回"。
   - 精确匹配：当用户说"仅为XX"、"恰好是XX"、"精确等于XX"、"状态就是XX"、
     "状态为'XX'"（带引号）时，使用 status_raw = 'XX' 做精确匹配。
   - 判断依据：有没有"仅/只/精确/恰好/就是"这类限定词。

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
    db_path = resolve_db_url()
    llm = LLM()
    schema = get_schema(db_path, cfg["table_name"])

    question = "打回次数最多的项目是哪个"
    sql, retries = generate_sql_with_retry(
        question, llm, schema, db_path, cfg["table_name"], max_retries=2
    )
    print(f"问题：{question}")
    print(f"SQL：{sql}")
    print(f"重试：{retries} 次")


FILTER_SYSTEM_PROMPT = """你是筛选助手。用户用自然语言描述筛选条件，你需要生成SQL。

表名：{table_name}

表结构：
{schema}

规则：
1. 只返回SQL语句本身，不要解释、不要markdown代码块、不要结尾分号
2. 必须用 SELECT * （返回完整记录）
3. 不能用 COUNT/SUM/AVG 等聚合函数
4. 严格使用下面提供的列名，不要臆造
5. 只生成 SELECT 查询
6. 如果用户说"全部"或类似，就不要加 WHERE 条件

当前日期：{today}"""


def generate_filter_sql(filter_question: str, llm: LLM, schema: str, table_name: str) -> str:
    """生成筛选 SQL，返回所有匹配记录的完整内容。"""
    system = FILTER_SYSTEM_PROMPT.format(
        table_name=table_name,
        schema=schema,
        today=date.today().isoformat(),
    )
    return _clean_sql(llm.chat(system, filter_question))