import json
from nl2sql import get_schema
from services import ServiceContext
from services import (
    query_service, delete_service, create_service,
    update_service, transform_service, add_column_service,
)
from services import import_service, restore_service
from services import consistency_service
from services import export_service
from services import report_service


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "查询项目数据库。把用户的自然语言问题翻译成SQL并执行，返回自然语言答案。\n"
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
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
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
            "name": "request_restore",
            "description": (
                "恢复之前被软删除的项目记录。"
                "filter_question 是模糊筛选条件，系统会在已删除的记录里搜索、"
                "展示候选，请用户确认后恢复。"
                "【何时用】用户说'恢复'、'撤销删除'、'把刚才删的找回来'、'还原'时。"
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_question": {
                        "type": "string",
                        "description": (
                            "自然语言筛选条件。用户说'刚才删的/最近删的'时传'最近删除的'；"
                            "说'全部/所有'时传'全部'；也可传项目名或负责人做模糊匹配"
                        ),
                    },
                },
                "required": ["filter_question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_create",
            "description": "请求新增一条项目记录。需要项目名、负责人、分类。"
            "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。",
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
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
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
            "description": "请求批量新增项目记录。一次新增多条时使用。"
            "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。",
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
    {
        "type": "function",
        "function": {
            "name": "request_import",
            "description": (
                "请求从 Excel 文件导入项目数据。会扫描文件与数据库的差异，"
                "可能包括：新记录、字段冲突、已删除记录。"
                "系统会展示差异并请求用户确认后执行导入。"
                "【返回特征】如果返回 is_security: true，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Excel 文件路径",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_consistency",
            "description": (
                "检查数据库记录是否存在字段自相矛盾。"
                "检查项包括：状态字段与状态文本不匹配、日期顺序异常（下证早于下发等）。"
                "用于数据质量体检。不检查字段缺失（缺失是允许的）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
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
                    "filter_question": {
                        "type": "string",
                        "description": "模糊筛选条件，描述要导出哪些记录",
                    },
                },
                "required": ["filter_question"],
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
                    "period": {"type": "string", "enum": ["day", "week", "month"]},
                    "items": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["issued", "certified", "rejected", "resubmitted"]},
                    },
                    "custom_start": {"type": "string"},
                    "custom_end": {"type": "string"},
                    "offset": {
                        "type": "integer",
                        "description": "偏移量。0=当前（本周/本月/今天），-1=上一个（上周/上个月/昨天），-2=上上个。"
                    },
                    "compare": {
                        "type": "boolean",
                        "description": (
                            "是否对比上一周期。用户说'对比'、'环比'、'跟上周/上月比'时传 true。"
                            "自定义时间段（custom_start / custom_end）不支持环比。"
                        ),
                    },
                },
                "required": ["period"],
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
                "'去掉 owner 的首尾空格'、'日期格式统一'、'按某条件批量置为某值'）\n"
                "系统会翻译成 UPDATE 语句、展示预览（改哪些行、改前改后）、"
                "请用户确认后执行。\n"
                "【禁止】不能修改系统字段：is_deleted / deleted_at / deleted_by / delete_trace_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "自然语言的变换规则描述",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_column",
            "description": (
                "给表加一个新列。这是改表结构的操作——执行后表的结构会变。\n"
                "【何时用】用户说'加一列 xxx'、'增加字段'、'记一下 xxx' 时。\n"
                "【参数】\n"
                "- column_name：列名，只能是小写字母开头的英文标识符"
                "（如 priority / due_date）\n"
                "- column_type：类型，只能从以下里选："
                "VARCHAR / INTEGER / BIGINT / DOUBLE / BOOLEAN / TIMESTAMP / DATE\n"
                "- default_value（可选）：已有行的默认值\n"
                "- label（可选）：这列的中文含义，例如'优先级'。"
                "给了它之后，后续对话模型就能理解这列是什么。\n"
                "系统会校验列名、类型、生成 SQL、展示给用户确认后执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "column_name": {
                        "type": "string",
                        "description": "列名，小写英文标识符",
                    },
                    "column_type": {
                        "type": "string",
                        "enum": ["VARCHAR", "INTEGER", "BIGINT", "DOUBLE",
                                 "BOOLEAN", "TIMESTAMP", "DATE"],
                    },
                    "default_value": {
                        "type": "string",
                        "description": "可选。已有行的默认值",
                    },
                    "label": {
                        "type": "string",
                        "description": "可选。这列的中文含义，例如'优先级'",
                    },
                },
                "required": ["column_name", "column_type"],
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

    def request_restore(filter_question):
        return restore_service.request_restore(filter_question, ctx)

    def request_create(project_name, owner, category, status_raw="已提交", issued_date=None):
        return create_service.request_create(project_name, owner, category, status_raw, issued_date, ctx)

    def request_update(filter_question, updates):
        return update_service.request_update(filter_question, updates, ctx)

    def request_batch_create(records):
        return create_service.request_batch_create(records, ctx)

    def request_import(file_path):
        return import_service.request_import(file_path, ctx)

    def check_consistency():
        return consistency_service.run(ctx)

    def export_to_excel(filter_question):
        return export_service.run(filter_question, ctx)

    def generate_report(period, items=None, custom_start=None, custom_end=None,
                        offset=0, compare=False):
        return report_service.run(period, items or [], ctx,
                                  custom_start, custom_end, offset, compare)

    def transform_data(description):
        return transform_service.request_transform(description, ctx)
    
    def add_column(column_name, column_type, default_value=None, label=None):
        return add_column_service.request_add_column(
            column_name, column_type, default_value, label, ctx
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