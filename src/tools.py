import json
from nl2sql import get_schema
from services import ServiceContext
from services import query_service, delete_service, create_service, update_service


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "查询项目数据库。把用户的自然语言问题翻译成SQL并执行，返回自然语言答案。",
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
                "请求删除符合条件的项目记录。"
                "filter_question 是模糊筛选条件，系统会做模糊搜索并展示候选，"
                "请用户确认后执行删除。"
                "例：'家装项目'、'所有 web 类项目'、'所有项目'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_question": {"type": "string", "description": "自然语言筛选条件"},
                },
                "required": ["filter_question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_create",
            "description": "请求新增一条项目记录。需要项目名、负责人、分类。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"},
                    "owner": {"type": "string"},
                    "category": {"type": "string", "description": "web 或 嵌入式"},
                    "status_raw": {"type": "string", "description": "默认'已提交'"},
                    "issued_date": {"type": "string", "description": "YYYY-MM-DD，默认今天"},
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
                "请求修改符合条件的项目记录。"
                "filter_question 是模糊筛选条件，系统会搜索匹配记录、"
                "展示改前改后对比、请用户确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_question": {"type": "string"},
                    "updates": {"type": "object", "description": "要改的字段和值"},
                },
                "required": ["filter_question", "updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_batch_create",
            "description": "请求批量新增项目记录。一次新增多条时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "project_name": {"type": "string"},
                                "owner": {"type": "string"},
                                "category": {"type": "string"},
                                "status_raw": {"type": "string"},
                                "issued_date": {"type": "string"},
                            },
                            "required": ["project_name", "owner", "category"],
                        },
                    },
                },
                "required": ["records"],
            },
        },
    },
]


def build_tool_functions(llm, db_path: str, table_name: str, trace):
    schema = get_schema(db_path, table_name)
    real_table = f"{table_name}_all"
    ctx = ServiceContext(
        llm=llm, db_path=db_path, table_name=table_name,
        real_table=real_table, schema=schema, trace=trace,
    )

    def query_database(question):
        return query_service.run(question, ctx)

    def request_delete(filter_question):
        return delete_service.request_delete(filter_question, ctx)

    def request_create(project_name, owner, category, status_raw="已提交", issued_date=None):
        return create_service.request_create(project_name, owner, category, status_raw, issued_date, ctx)

    def request_update(filter_question, updates):
        return update_service.request_update(filter_question, updates, ctx)

    def request_batch_create(records):
        return create_service.request_batch_create(records, ctx)

    return {
        "query_database": query_database,
        "request_delete": request_delete,
        "request_create": request_create,
        "request_update": request_update,
        "request_batch_create": request_batch_create,
    }


def dispatch(name: str, args: dict, functions: dict) -> str:
    func = functions.get(name)
    if not func:
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
    return func(**args)