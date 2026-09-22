from db import describe
import yaml
from datetime import date
from llm import LLM
from execute import execute_sql
from guard import check_sql_safety, SecurityError
import logging
from config import load_config, resolve_db_url


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
    """拼装表结构描述：字段名 + 类型 + 必填/可空 + 中文含义。

    类型和必填是"事实"——从库读（describe）。
    中文含义是"标注"——从 schema_store 读（用户可编辑）。
    """
    from schema_store import get_field_label

    rows = describe(table_name)

    lines = []
    for r in rows:
        col_name = r["name"]
        col_type = r["type"]
        nullable = r.get("nullable", True)
        tag = "可空" if nullable else "必填"
        desc = get_field_label(table_name, col_name)
        lines.append(f"  - {col_name} ({col_type}, {tag}): {desc}")
    return "\n".join(lines)


def render_schema(schema: dict) -> str:
    """把结构化的表 schema 渲染成给模型看的文本。

    输入是 schema_store.get_table_schema() 的返回。
    这是"schema 对象 → prompt 文本"的唯一转换点——
    要改格式只改这里。
    """
    lines = []
    for f in schema["fields"]:
        tag = "可空" if f["nullable"] else "必填"
        desc = f["label"] or ""
        lines.append(f"  - {f['name']} ({f['type']}, {tag}): {desc}")
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


TRANSFORM_SYSTEM_PROMPT = """你是数据变换助手。用户描述一个变换规则，你把它翻译成 SQL。

规则：
1. 生成两段 SQL，用单独一行 `---` 分隔：
   - 第一段：UPDATE 语句（真正执行）
   - 第二段：SELECT 语句（预览：会改哪些行、改前改后）
2. UPDATE 必须带 WHERE 子句——绝不允许全表无条件更新。
   如果用户意图是"全部数据"，也要用 `WHERE 1=1`（明确表达"全部"），不要省略 WHERE。
3. 只允许 UPDATE，禁止 DELETE / DROP / INSERT / ALTER
4. 不能改这几个系统字段：is_deleted / deleted_at / deleted_by / delete_trace_id
5. 严格使用下面提供的表名和列名，不要臆造
6. 当前日期是 {today}
7. 不要解释、不要 markdown 代码块、不要结尾分号

表名（真实表）：{table_name}
（这是底层存储表。视图 projects 只是它的过滤视图，写操作一律用真实表。）

表结构：
{schema}

输出示例：
UPDATE projects_all SET reject_count = reject_count + 1 WHERE owner = '关梓鹤';
---
SELECT project_name, reject_count FROM projects_all WHERE owner = '关梓鹤';
"""


def _build_transform_system(schema: str, table_name: str) -> str:
    return TRANSFORM_SYSTEM_PROMPT.format(
        schema=schema,
        today=date.today().isoformat(),
        table_name=table_name,
    )


def generate_transform_sql(question: str, llm: LLM, schema: str, table_name: str) -> tuple:
    """生成数据变换 SQL。返回 (update_sql, preview_sql)。

    模型输出两段 SQL 用 `---` 分隔。第一段是 UPDATE，第二段是 SELECT。
    这里只负责解析成两段——执行与确认由 transform_service 负责。
    """
    real_table = f"{table_name}_all"
    raw = llm.chat(_build_transform_system(schema, real_table), question).strip()

    # 剥 markdown 代码块
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.startswith("```")]
        raw = "\n".join(lines).strip()

    # 按 --- 分割
    parts = [p.strip() for p in raw.split("---") if p.strip()]
    if len(parts) < 2:
        raise ValueError(
            f"模型没有按约定输出两段 SQL（需要 UPDATE 和 SELECT，用 --- 分隔）。"
            f"实际输出：\n{raw[:300]}"
        )

    update_sql = _clean_sql(parts[0])
    preview_sql = _clean_sql(parts[1])
    return update_sql, preview_sql