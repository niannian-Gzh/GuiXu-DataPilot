import json
from nl2sql import get_schema, generate_sql_with_retry
from execute import execute_sql
from summarize import summarize
from guard import SecurityError
from delete_op import find_candidates


class UserInputRequired(Exception):
    """需要用户输入才能继续。"""
    def __init__(self, question: str, pending_action: dict):
        super().__init__(question)
        self.question = question
        self.pending_action = pending_action


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "查询项目数据库。把用户的自然语言问题翻译成SQL并执行，"
                "返回自然语言答案。适用于任何查询类请求。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要查询的完整自然语言问题"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_delete",
            "description": (
                "请求删除符合关键词的项目记录。系统会搜索匹配记录并向用户展示候选、"
                "请求确认。调用此工具后，操作会暂停等待用户确认。"
                "注意：只有当用户明确要求删除时才调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "项目名关键词。删除全部时传空字符串。",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
]


def build_tool_functions(llm, db_path: str, table_name: str, trace):
    schema = get_schema(db_path, table_name)
    real_table = f"{table_name}_all"

    def query_database(question: str) -> str:
        try:
            sql, retries = generate_sql_with_retry(
                question, llm, schema, db_path, table_name, max_retries=2
            )
            df = execute_sql(sql, db_path)
            answer = summarize(question, df, llm)
            return json.dumps(
                {"sql": sql, "row_count": len(df), "answer": answer},
                ensure_ascii=False,
            )
        except SecurityError as e:
            return json.dumps({"error": f"安全拒绝：{e}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def request_delete(keyword: str) -> str:
        candidates = find_candidates(keyword, db_path, real_table)
        if not candidates:
            return json.dumps(
                {"status": "not_found", "message": "没有找到匹配的记录"},
                ensure_ascii=False,
            )

        pending = {
            "type": "delete",
            "stage": "confirm",
            "candidates": candidates,
            "user_input": trace.data["question"],
            "trace_id": trace.id,
        }
        raise UserInputRequired(
            question=f"找到 {len(candidates)} 条匹配，等待用户确认",
            pending_action=pending,
        )

    return {
        "query_database": query_database,
        "request_delete": request_delete,
    }


def dispatch(name: str, args: dict, functions: dict) -> str:
    func = functions.get(name)
    if not func:
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
    return func(**args)