import json
from nl2sql import get_schema, render_schema
from schema_store import get_all_tables_schema
from services import ServiceContext
from services import (
    query_service, delete_service, create_service,
    update_service, transform_service, add_column_service,
)
from services import import_service, restore_service
from services import consistency_service
from services import export_service
from services import report_service


# 工具定义里"表名参数"的统一描述——12 处复用
_TABLE_DESC = (
    "要操作的表名（视图名，如 projects）。"
    "从 system prompt 里的『可用表列表』中选一个。"
)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "查询数据。把用户的自然语言问题翻译成SQL并执行，返回自然语言答案。\n"
                "【返回特征——必须遵守】\n"
                "1. 如果返回包含 hint 字段：说明查询已完整执行、结果可信，"
                "直接基于该结果回答，不要换问法反复查询。\n"
                "2. 如果返回包含 ambiguous: true 和 branches 字段："
                "你必须把 branches 里的所有分支都展示给用户，"
                "不能只报一个值。例如展示为：\n"
                "   「有两种理解：\n"
                "    - 包含匹配（默认）：141 个\n"
                "    - 精确匹配：76 个」"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "question": {"type": "string", "description": "要查询的完整自然语言问题"},
                },
                "required": ["table_name", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_delete",
            "description": (
                "请求删除符合条件的记录（软删除，7 天内可恢复）。"
                "filter_question 是模糊筛选条件，系统会做模糊搜索并展示候选，"
                "请用户确认后执行删除。"
                "例：'家装项目'、'所有 web 类项目'、'所有项目'。"
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "filter_question": {"type": "string", "description": "自然语言筛选条件"},
                },
                "required": ["table_name", "filter_question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_restore",
            "description": (
                "恢复之前被软删除的记录。"
                "filter_question 是模糊筛选条件，系统会在已删除的记录里搜索、"
                "展示候选，请用户确认后恢复。"
                "【何时用】用户说'恢复'、'撤销删除'、'把刚才删的找回来'、'还原'时。"
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "filter_question": {
                        "type": "string",
                        "description": (
                            "自然语言筛选条件。用户说'刚才删的/最近删的'时传'最近删除的'；"
                            "说'全部/所有'时传'全部'；也可传项目名或负责人做模糊匹配"
                        ),
                    },
                },
                "required": ["table_name", "filter_question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_create",
            "description": "请求新增一条记录。字段从该表的结构里看。"
            "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "project_name": {"type": "string"},
                    "owner": {"type": "string"},
                    "category": {"type": "string", "description": "web 或 嵌入式"},
                    "status_raw": {"type": "string", "description": "默认'已提交'"},
                    "issued_date": {"type": "string", "description": "YYYY-MM-DD，默认今天"},
                },
                "required": ["table_name", "project_name", "owner", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_update",
            "description": (
                "请求修改符合条件的记录。"
                "filter_question 是模糊筛选条件，系统会搜索匹配记录、"
                "展示改前改后对比、请用户确认。"
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "filter_question": {"type": "string"},
                    "updates": {"type": "object", "description": "要改的字段和值"},
                },
                "required": ["table_name", "filter_question", "updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_batch_create",
            "description": "请求批量新增记录。一次新增多条时使用。"
            "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
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
                "required": ["table_name", "records"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_import",
            "description": (
                "请求从 Excel 文件导入数据到指定表。会扫描文件与数据库的差异，"
                "可能包括：新记录、字段冲突、已删除记录。"
                "系统会展示差异并请求用户确认后执行导入。"
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "file_path": {"type": "string", "description": "Excel 文件路径"},
                },
                "required": ["table_name", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_consistency",
            "description": (
                "检查记录是否存在字段自相矛盾。"
                "检查项包括：状态字段与状态文本不匹配、日期顺序异常。"
                "用于数据质量体检。不检查字段缺失（缺失是允许的）。\n"
                "table_name 不传时检查所有表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": (
                            "要检查的表名。不传则检查所有表。"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_to_excel",
            "description": (
                "把符合条件的记录导出为 Excel 文件。"
                "filter_question 是模糊筛选条件，例如'所有 web 类项目'、'已下证的项目'。"
                "导出是只读操作，不会修改数据，无需用户确认。"
                "返回文件路径和导出的记录数。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "filter_question": {"type": "string", "description": "模糊筛选条件"},
                },
                "required": ["table_name", "filter_question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": (
                "生成日/周/月报（PDF，含图表和明细）。"
                "period：day/week/month；items 是要包含的事件，"
                "取值：issued（下发）/ certified（下证）/ rejected（打回）/ resubmitted（重提）。"
                "如果用户没指定 items，默认用 ['issued', 'certified', 'rejected']。"
                "如果用户说'上个/上次/昨天/上周/上个月'，用 offset=-1；"
                "'上上/前天'用 offset=-2。"
                "如果用户说'对比/环比/跟上周/上月比'，传 compare=true。"
                "如果用户指定了自定义时间段，传 custom_start 和 custom_end（YYYY-MM-DD）。"
                "注意：自定义时间段不支持环比。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "period": {"type": "string", "enum": ["day", "week", "month"]},
                    "items": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["issued", "certified", "rejected", "resubmitted"]},
                    },
                    "custom_start": {"type": "string"},
                    "custom_end": {"type": "string"},
                    "offset": {
                        "type": "integer",
                        "description": "偏移量。0=当前，-1=上一个，-2=上上个。",
                    },
                    "compare": {
                        "type": "boolean",
                        "description": "是否对比上一周期。",
                    },
                },
                "required": ["table_name", "period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transform_data",
            "description": (
                "对已有数据按【规则】批量重塑。\n"
                "【和 request_update 的分界】\n"
                "- request_update：新值由用户明确给出（'把 A 改成 B'）\n"
                "- transform_data：新值由旧值通过规则算出（'所有打回次数加 1'、"
                "'去掉 owner 的首尾空格'、'日期格式统一'）\n"
                "系统会翻译成 UPDATE 语句、展示预览（改哪些行、改前改后）、"
                "请用户确认后执行。\n"
                "【禁止】不能修改系统字段：is_deleted / deleted_at / deleted_by / delete_trace_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "description": {"type": "string", "description": "自然语言的变换规则描述"},
                },
                "required": ["table_name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_column",
            "description": (
                "给表加一个新列。这是改表结构的操作——执行后表的结构会变。\n"
                "【何时用】用户说'加一列 xxx'、'增加字段' 时。\n"
                "- column_name：列名，小写字母开头的英文标识符（如 priority）\n"
                "- column_type：VARCHAR / INTEGER / BIGINT / DOUBLE / BOOLEAN / TIMESTAMP / DATE\n"
                "- default_value（可选）：已有行的默认值\n"
                "- label（可选）：这列的中文含义。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "column_name": {"type": "string", "description": "列名，小写英文标识符"},
                    "column_type": {
                        "type": "string",
                        "enum": ["VARCHAR", "INTEGER", "BIGINT", "DOUBLE",
                                 "BOOLEAN", "TIMESTAMP", "DATE"],
                    },
                    "default_value": {"type": "string", "description": "可选。已有行的默认值"},
                    "label": {"type": "string", "description": "可选。这列的中文含义"},
                },
                "required": ["table_name", "column_name", "column_type"],
            },
        },
    },
]


def build_tool_functions(llm, db_path: str, table_name: str, trace):
    """建工具函数表。

    table_name 参数保留兼容——C1 阶段还不删（agent.py 还在传）。
    C2 会把 agent.py 的调用改掉，那时再删这个参数。
    工具函数内部不再用它——表名由每次工具调用时传入。
    """
    base_ctx = ServiceContext(llm=llm, db_path=db_path, trace=trace)

    def query_database(table_name, question):
        return query_service.run(question, base_ctx.for_table(table_name))

    def request_delete(table_name, filter_question):
        return delete_service.request_delete(filter_question, base_ctx.for_table(table_name))

    def request_restore(table_name, filter_question):
        return restore_service.request_restore(filter_question, base_ctx.for_table(table_name))

    def request_create(table_name, project_name, owner, category,
                       status_raw="已提交", issued_date=None):
        return create_service.request_create(
            project_name, owner, category, status_raw, issued_date,
            base_ctx.for_table(table_name),
        )

    def request_update(table_name, filter_question, updates):
        return update_service.request_update(filter_question, updates, base_ctx.for_table(table_name))

    def request_batch_create(table_name, records):
        return create_service.request_batch_create(records, base_ctx.for_table(table_name))

    def request_import(table_name, file_path):
        return import_service.request_import(file_path, base_ctx.for_table(table_name))

    def check_consistency(table_name=None):
        # 传了表名——检查那一张；不传——检查所有表
        if table_name:
            return consistency_service.run(base_ctx.for_table(table_name))
        return consistency_service.run_all(base_ctx)

    def export_to_excel(table_name, filter_question):
        return export_service.run(filter_question, base_ctx.for_table(table_name))

    def generate_report(table_name, period, items=None,
                        custom_start=None, custom_end=None,
                        offset=0, compare=False):
        return report_service.run(
            period, items or [], base_ctx.for_table(table_name),
            custom_start, custom_end, offset, compare,
        )

    def transform_data(table_name, description):
        return transform_service.request_transform(description, base_ctx.for_table(table_name))

    def add_column(table_name, column_name, column_type, default_value=None, label=None):
        return add_column_service.request_add_column(
            column_name, column_type, default_value, label,
            base_ctx.for_table(table_name),
        )

    return {
        "query_database": query_database,
        "request_delete": request_delete,
        "request_restore": request_restore,
        "request_create": request_create,
        "request_update": request_update,
        "request_batch_create": request_batch_create,
        "request_import": request_import,
        "check_consistency": check_consistency,
        "export_to_excel": export_to_excel,
        "generate_report": generate_report,
        "transform_data": transform_data,
        "add_column": add_column,
    }


def dispatch(name: str, args: dict, functions: dict) -> str:
    func = functions.get(name)
    if not func:
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
    return func(**args)