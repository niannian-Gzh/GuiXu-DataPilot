import json
import duckdb
from nl2sql import get_schema, generate_sql_with_retry
from execute import execute_sql
from summarize import summarize
from guard import SecurityError
from delete_op import find_candidates
from datetime import date
from update_op import recompute_status_flags


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
        {
        "type": "function",
        "function": {
            "name": "request_create",
            "description": (
                "请求新增一条项目记录。需要提供项目名（project_name）、"
                "负责人（owner）、分类（category）。其他字段可选。"
                "系统会校验必填字段、检查重复，然后请求用户确认。"
                "注意：只有当用户明确要求新增时才调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string", "description": "项目名称"},
                    "owner": {"type": "string", "description": "负责人姓名"},
                    "category": {"type": "string", "description": "分类，web 或 嵌入式"},
                    "status_raw": {"type": "string", "description": "状态，默认'已提交'"},
                    "issued_date": {"type": "string", "description": "下发时间，格式 YYYY-MM-DD，默认今天"},
                },
                "required": ["project_name", "owner", "category"],
            },
        },
    },
        {
        "type": "function",
        "function": {
            "name": "request_update",
            "description": (
                "请求修改一条项目记录。需要提供 keyword 定位记录，"
                "以及 updates 指明要改哪些字段和值。"
                "系统会校验字段、展示改前改后对比，请求用户确认。"
                "注意：只能修改唯一匹配的记录。如果匹配到多条，工具会返回错误，"
                "你需要追问用户具体要改哪一条。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "用于定位记录的项目名关键词",
                    },
                    "updates": {
                        "type": "object",
                        "description": (
                            "要修改的字段和值。字段名用英文，"
                            "例如 owner, status_raw, category, issued_date 等。"
                        ),
                    },
                },
                "required": ["keyword", "updates"],
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

    def request_create(project_name: str, owner: str, category: str,
                       status_raw: str = "已提交", issued_date: str = None):
        if category not in ("web", "嵌入式"):
            return json.dumps(
                {"error": f"分类必须是 web 或 嵌入式，收到：{category}"},
                ensure_ascii=False,
            )

        con = duckdb.connect(db_path)
        exists = con.execute(
            f"SELECT COUNT(*) FROM {real_table} "
            f"WHERE project_name = ? AND is_deleted = false",
            [project_name],
        ).fetchone()[0]
        con.close()

        if exists > 0:
            return json.dumps(
                {"error": f"项目「{project_name}」已存在，不能重复新增"},
                ensure_ascii=False,
            )

        new_record = {
            "project_name": project_name,
            "owner": owner,
            "category": category,
            "status_raw": status_raw,
            "issued_date": issued_date or date.today().isoformat(),
            "certified_date": None,
            "resubmit_name": None,
            "reject_date": None,
            "resubmit_date": None,
            "reject_count": 0,
        }

        pending = {
            "type": "create",
            "stage": "confirm",
            "record": new_record,
            "user_input": trace.data["question"],
            "trace_id": trace.id,
        }
        raise UserInputRequired(
            question=f"等待用户确认新增项目「{project_name}」",
            pending_action=pending,
        )

    def request_update(keyword: str, updates: dict) -> str:
        # 检查禁用字段
        forbidden = {"is_deleted", "deleted_at", "deleted_by", "delete_trace_id"}
        for field in updates:
            if field in forbidden:
                return json.dumps(
                    {"error": f"字段 {field} 不允许修改"},
                    ensure_ascii=False,
                )

        # 找候选
        candidates = find_candidates(keyword, db_path, real_table)
        if not candidates:
            return json.dumps(
                {"status": "not_found", "message": "没有找到匹配的记录"},
                ensure_ascii=False,
            )
        if len(candidates) > 1:
            names = [c["project_name"] for c in candidates]
            return json.dumps(
                {
                    "status": "multiple_matches",
                    "message": f"找到 {len(candidates)} 条匹配，请用户明确指定要修改哪一条",
                    "candidates": names[:10],
                },
                ensure_ascii=False,
            )

        # 单条匹配：读完整记录
        target_name = candidates[0]["project_name"]
        con = duckdb.connect(db_path)
        row = con.execute(
            f"SELECT * FROM {real_table} "
            f"WHERE project_name = ? AND is_deleted = false",
            [target_name],
        ).fetchdf()
        con.close()

        record = row.iloc[0].to_dict()

        pending = {
            "type": "update",
            "stage": "confirm",
            "record": record,
            "updates": updates,
            "user_input": trace.data["question"],
            "trace_id": trace.id,
        }
        raise UserInputRequired(
            question=f"等待用户确认修改「{target_name}」",
            pending_action=pending,
        )

    return {
        "query_database": query_database,
        "request_delete": request_delete,
        "request_create": request_create,
        "request_update": request_update,
    }


def dispatch(name: str, args: dict, functions: dict) -> str:
    func = functions.get(name)
    if not func:
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
    return func(**args)