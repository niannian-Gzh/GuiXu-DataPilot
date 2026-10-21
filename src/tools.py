import json

import snapshot
from guard import SecurityError
from runner import using
from services import ServiceContext, UserInputRequired
from services import (
    query_service, delete_service, create_service,
    update_service, transform_service, structure_service,
)
from services import import_service, restore_service
from services import export_service
from services import report_service
from services import document_service
from rag import service as rag_service


# 工具定义里"表名参数"的统一描述——12 处复用
_TABLE_DESC = (
    "要操作的表名，从上下文里的表定义中选一个。"
)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "在文档库里检索资料。**只用于非结构化内容**：制度、手册、规范、"
                "说明书、报告、资料。结构化表里的数据用 query_database，不要用它。\n"
                "返回最相关的若干切片（原文 + 文档名 + 相似度）。\n"
                "`status: empty` 表示文档库里没有相关内容——如实告诉用户，不要编。\n"
                "query 用完整的问题或一句关键描述，不要只给一个词。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词或完整问题"},
                    "top_k": {
                        "type": "integer",
                        "description": "返回几条。不确定就别传，用设置里的检索条数",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "查询数据。把用户的自然语言问题翻译成 SQL 并执行，"
                "返回**数据本身**：columns（列名）+ rows（二维数组）。\n"
                "拿到数据后自己判断怎么用——统计、对比、排序都可以，不要只复述。\n"
                "`status: \"empty\"` 表示执行成功但没有符合条件的数据，"
                "不是失败；可以看 `total_records_in_table` 判断是表空还是条件太窄。\n"
                "`truncated: true` 表示只给了前 N 行，需要更多就换个更具体的问法。"
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
            "name": "write_document",
            "description": (
                "把内容写成一份可下载的文档，格式可选 PDF / Word(.docx) / "
                "Markdown(.md) / 纯文本(.txt)。\n"
                "content 用 Markdown 写：`#` 标题、`-` 列表、表格都可以。\n"
                "产物会出现在右侧产物栏，用户可以直接预览或下载。\n"
                "**不要用它写数据表**——表格数据用 export_to_excel；"
                "固定版式的统计报告用 generate_report。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "文档标题，也用作文件名"},
                    "content": {"type": "string", "description": "正文，Markdown 格式"},
                    "format": {
                        "type": "string",
                        "enum": ["pdf", "docx", "md", "txt"],
                        "description": "输出格式，默认 docx",
                    },
                    "to_library": {
                        "type": "boolean",
                        "description": (
                            "用户明确说「收进文档库 / 加入资料库」时传 true。"
                            "产物会复制一份进文档库，原文件仍留在产物栏"
                        ),
                    },
                },
                "required": ["title", "content", "format"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_delete",
            "description": (
                "请求删除符合条件的记录（软删除，保留期内可在回收站恢复）。"
                "filter_question 是模糊筛选条件，系统会做模糊搜索并展示候选，"
                "请用户确认后执行删除。"
                "例：'所有已完成的记录'、'某个分类下的记录'。"
                "【返回特征】如果返回 error_type 为 security，说明这是安全拒绝，不要重试，直接告知用户。"
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
                "【返回特征】如果返回 error_type 为 security，说明这是安全拒绝，不要重试，直接告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "filter_question": {
                        "type": "string",
                        "description": (
                            "自然语言筛选条件。用户说'刚才删的/最近删的'时传'最近删除的'；"
                            "说'全部/所有'时传'全部'；也可传某一列的值做模糊匹配"
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
            "description": (
                "请求新增记录。**单条也传数组**（长度 1）——一个工具只有一种形状。\n"
                "每行是一个 {字段名: 值}。字段名必须是该表定义里存在的列；\n"
                "标着「必填」的列不能缺；没给的「可空」列会留空，"
                "有默认值的列由库里填默认值。\n"
                "多条整批要么全进、要么全不进，不会写进去一半。\n"
                "唯一约束由数据库在写入时检查——重复了返回 error_type: duplicate，"
                "那不是失败，是提示你换一个值。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "records": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "要新增的行。只有一条也要放进数组：[{字段名: 值}]",
                    },
                },
                "required": ["table_name", "records"],
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
                "【返回特征】如果返回 error_type 为 security，说明这是安全拒绝，不要重试，直接告知用户。"
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
            "name": "request_import",
            "description": (
                "请求从 Excel 文件导入数据到指定表。会扫描文件与数据库的差异，"
                "可能包括：新记录、字段冲突、已删除记录。"
                "系统会展示差异并请求用户确认后执行导入。"
                "【返回特征】如果返回 error_type 为 security，说明这是安全拒绝，不要重试，直接告知用户。"
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
            "name": "ask_user",
            "description": (
                "向用户提问，等回答后再继续。**问题不明确、需要在几个方向里选、"
                "或缺关键信息时用它，不要猜。**\n"
                "一次可以问 1-3 个问题；每个问题可以给最多 3 个方向（options），"
                "不给就是纯澄清。只问一个也传数组。\n"
                "用户永远可以自由输入——选项只是省事，不是限制。\n"
                "这个工具会挂起当前流程；用户回答后你会拿到 answers，"
                "按顺序一条一条对应问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "要问用户的问题，一句话说清楚缺什么",
                                },
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "可选的方向，最多 3 个。不给就是纯澄清",
                                },
                            },
                            "required": ["question"],
                        },
                        "description": "要问的问题，一次 1-3 个。只问一个也传数组",
                    },
                },
                "required": ["questions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_to_excel",
            "description": (
                "把符合条件的记录导出为 Excel 文件。"
                "filter_question 是模糊筛选条件，例如'所有已完成的记录'、'某个分类下的记录'。"
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
                "把整理好的内容渲染成 PDF 报告。**它只排版，不做统计。**\n"
                "正确顺序：先用 query_database 把数据查出来、自己算清楚，"
                "再把结果按 sections 交给它。标题、概述、每一节的文字/表格/图表"
                "都由你组织——它不知道任何业务字段。\n"
                "图表给 labels + values，会自动画成柱状图；表格给 columns + rows（二维数组）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "报告标题"},
                    "intro": {
                        "type": "string",
                        "description": "开头的概述，2-3 句话。不写就不放概述块",
                    },
                    "sections": {
                        "type": "array",
                        "description": "报告的节。一节一个标题，可带文字、表格、图表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string", "description": "这一节的标题"},
                                "body": {"type": "string", "description": "这一节的说明文字"},
                                "table": {
                                    "type": "object",
                                    "properties": {
                                        "columns": {"type": "array", "items": {"type": "string"}},
                                        "rows": {
                                            "type": "array",
                                            "items": {"type": "array"},
                                            "description": "二维数组，每行与 columns 对齐",
                                        },
                                    },
                                    "required": ["columns", "rows"],
                                },
                                "chart": {
                                    "type": "object",
                                    "properties": {
                                        "labels": {"type": "array", "items": {"type": "string"}},
                                        "values": {"type": "array", "items": {"type": "number"}},
                                        "title": {"type": "string"},
                                    },
                                    "required": ["labels", "values"],
                                },
                            },
                            "required": ["heading"],
                        },
                    },
                },
                "required": ["title", "sections"],
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
                "- transform_data：新值由旧值通过规则算出（'所有计数加 1'、"
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
    {
        "type": "function",
        "function": {
            "name": "create_table",
            "description": (
                "新建一张表。\n"
                "columns 是列定义：每项 {name, type, nullable?, default?}。\n"
                "- name：小写字母开头的英文标识符\n"
                "- type：VARCHAR / INTEGER / BIGINT / DOUBLE / BOOLEAN / TIMESTAMP / DATE\n"
                "- nullable：默认 true；给 false 就是必填\n"
                "- default：默认值（SQL 字面量，字符串不用自己加引号）\n"
                "不给主键时自动补一个自增整型 id。\n"
                "unique：哪几列合起来不能重复，比如 [\"order_no\"]。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "新表的名字"},
                    "columns": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "列定义列表",
                    },
                    "unique": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "唯一列（可选）",
                    },
                },
                "required": ["table_name", "columns"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alter_column",
            "description": (
                "改一个列的类型。这是破坏性操作——表会被重建，"
                "执行前自动落快照。已有数据按新类型重新解释。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "column_name": {"type": "string"},
                    "new_type": {
                        "type": "string",
                        "enum": ["VARCHAR", "INTEGER", "BIGINT", "DOUBLE",
                                 "BOOLEAN", "TIMESTAMP", "DATE"],
                    },
                },
                "required": ["table_name", "column_name", "new_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drop_column",
            "description": (
                "删掉一个列。破坏性操作——执行前自动落快照，"
                "之后可以从版本历史回滚。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                    "column_name": {"type": "string"},
                },
                "required": ["table_name", "column_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_deleted",
            "description": (
                "列出这张表里被删掉、还能恢复的行（软删除的那些）。\n"
                "只读，不需要确认。用户问'我删过什么''刚才删的还在吗'时用它。\n"
                "要恢复其中某几条，再调 request_restore。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_snapshots",
            "description": (
                "列出某张表的历史快照（做覆盖导入 / 删表 / 删列 / 回滚之前自动留下的）。\n"
                "只读。用户问'有没有之前的版本''能退回去吗'时用它。\n"
                "返回的 id 交给 rollback_version 用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "表名。不给就是全库的。",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_version",
            "description": (
                "把一张表退回某个快照。**破坏性操作**——执行前会自动给"
                "当前状态再落一份快照，所以回滚错了还能回滚回来。\n"
                "snapshot_id 从 list_snapshots 拿。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "integer", "description": "快照 id"},
                },
                "required": ["snapshot_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drop_table",
            "description": (
                "删掉整张表。**破坏性最强**——执行前自动落快照，"
                "之后可以从版本历史回滚。问清楚是哪张表再动手。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": _TABLE_DESC},
                },
                "required": ["table_name"],
            },
        },
    },
]


def build_tool_functions(llm, trace):
    """建工具函数表。

    **没有"默认表"这个参数。** 表名由每次工具调用时传入——
    那是多表的前提：模型自己决定操作哪张表，而不是启动时绑死一张。
    （旧版有两个死参数 `db_path` / `table_name`，一路传到底没人读。）
    """
    base_ctx = ServiceContext(llm=llm, trace=trace)

    def query_database(table_name, question):
        return query_service.run(question, base_ctx.for_table(table_name))

    def request_delete(table_name, filter_question):
        return delete_service.request_delete(filter_question, base_ctx.for_table(table_name))

    def request_restore(table_name, filter_question):
        return restore_service.request_restore(filter_question, base_ctx.for_table(table_name))

    def request_create(table_name, records):
        return create_service.request_create(records, base_ctx.for_table(table_name))

    def request_update(table_name, filter_question, updates):
        return update_service.request_update(filter_question, updates, base_ctx.for_table(table_name))

    def request_import(table_name, file_path):
        return import_service.request_import(file_path, base_ctx.for_table(table_name))

    def ask_user(questions):
        """向用户提问——工具挂起，不碰数据。

        **单问题也传数组**：一个工具一种参数形状，不让模型猜这次是哪种
        （和 create 合并单条/批量是同一条账）。

        它和确认卡片走同一条路：抛 UserInputRequired，用户回答后
        由 pending_service 的续体把它伪装成这次调用的返回。
        区别只在续体：这里是「答案就是结果」，确认卡片是「执行完才算结果」。
        """
        items = []
        for q in (questions or []):
            # 模型偶尔把数组写成字符串数组，统一收成对象，不因此击穿一轮
            if isinstance(q, str):
                q = {"question": q}
            text = str(q.get("question") or "").strip()
            if not text:
                continue
            items.append({
                "question": text,
                # options 只是提示，最多 3 个；自由输入永远在
                "options": [str(o) for o in (q.get("options") or [])][:3],
            })

        if not items:
            return json.dumps(
                {"ok": False, "error": "questions 至少要有一个问题",
                 "error_type": "invalid_arguments"},
                ensure_ascii=False,
            )
        if len(items) > 3:
            return json.dumps(
                {"ok": False, "error": "一次最多问 3 个问题，请拆开或合并",
                 "error_type": "invalid_arguments"},
                ensure_ascii=False,
            )

        raise UserInputRequired(
            question=items[0]["question"],
            pending_action={
                "type": "ask",
                "stage": "confirm",
                "questions": items,
                # 旧形状留着：老会话里的 pending 只有 question / options
                "question": items[0]["question"],
                "options": items[0]["options"],
                "user_input": base_ctx.trace.data.get("question", ""),
                "trace_id": base_ctx.trace.id,
            },
        )

    def export_to_excel(table_name, filter_question):
        return export_service.run(filter_question, base_ctx.for_table(table_name))

    def generate_report(title, sections, intro=""):
        # 不绑定表：报告是把已经取好的数据排版，统计在 query 那一步就完成了
        return report_service.run(title, intro, sections)

    def transform_data(table_name, description):
        return transform_service.request_transform(description, base_ctx.for_table(table_name))

    def add_column(table_name, column_name, column_type, default_value=None, label=None):
        return structure_service.request_add_column(
            table_name, column_name, column_type, default_value, label,
            base_ctx.for_table(table_name),
        )

    def create_table(table_name, columns, unique=None):
        return structure_service.request_create_table(
            table_name, columns, unique, base_ctx.for_table(table_name)
        )

    def alter_column(table_name, column_name, new_type):
        return structure_service.request_alter_column(
            table_name, column_name, new_type, base_ctx.for_table(table_name)
        )

    def drop_column(table_name, column_name):
        return structure_service.request_drop_column(
            table_name, column_name, base_ctx.for_table(table_name)
        )

    def drop_table(table_name):
        return structure_service.request_drop_table(
            table_name, base_ctx.for_table(table_name)
        )

    def list_deleted(table_name):
        return restore_service.list_deleted(table_name, base_ctx.for_table(table_name))

    def list_snapshots(table_name=None):
        return json.dumps(
            {"ok": True, "snapshots": using(snapshot.list_snapshots, table_name)},
            ensure_ascii=False,
        )

    def rollback_version(snapshot_id):
        return structure_service.request_rollback(snapshot_id, base_ctx)

    def search_documents(query, top_k=None):
        # 默认必须是 None，不能写成 4：写死数字会让设置里的
        # `rag.top_k` 永远轮不到生效——"没指定"和"指定 4"是两回事
        return rag_service.search_json(query, top_k)

    def write_document(title, content, format="docx", to_library=False):
        try:
            return json.dumps(
                document_service.write(title, content, format, to_library),
                ensure_ascii=False,
            )
        except ValueError as e:
            return json.dumps(
                {"ok": False, "error": str(e), "error_type": "invalid"},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps(
                {"ok": False, "error": str(e), "error_type": "unknown"},
                ensure_ascii=False,
            )

    return {
        "search_documents": search_documents,
        "write_document": write_document,
        "query_database": query_database,
        "request_delete": request_delete,
        "request_restore": request_restore,
        "request_create": request_create,
        "request_update": request_update,
        "request_import": request_import,
        "ask_user": ask_user,
        "export_to_excel": export_to_excel,
        "generate_report": generate_report,
        "transform_data": transform_data,
        "add_column": add_column,
        "create_table": create_table,
        "alter_column": alter_column,
        "drop_column": drop_column,
        "drop_table": drop_table,
        "list_deleted": list_deleted,
        "list_snapshots": list_snapshots,
        "rollback_version": rollback_version,
    }


def dispatch(name: str, args: dict, functions: dict) -> str:
    """按名字调工具。

    **参数错了不能击穿整轮。** 模型多给一个字段、少给一个必填、或者
    把对象写成字符串，`func(**args)` 都会抛 TypeError，一路冒到 api
    变成"出错了"——用户只看到一句话，而模型失去了换一种调用方式的机会。
    在这里拦下来，用和工具返回同一套形状告诉它哪里不对。

    `UserInputRequired` 必须继续冒泡——那是中断，不是错误。
    """
    func = functions.get(name)
    if not func:
        return json.dumps(
            {"ok": False, "error": f"未知工具：{name}", "error_type": "invalid"},
            ensure_ascii=False,
        )
    if not isinstance(args, dict):
        return json.dumps(
            {"ok": False, "error": "参数必须是一个对象",
             "error_type": "invalid_arguments"},
            ensure_ascii=False,
        )
    try:
        return func(**args)
    except UserInputRequired:
        raise
    except SecurityError as e:
        # 安全拒绝也是**工具返回的一种**，不是异常：模型看懂之后
        # 可以换一条路，整轮不用崩
        return json.dumps(
            {"ok": False, "error": f"安全拒绝：{e}", "error_type": "security"},
            ensure_ascii=False,
        )
    except TypeError as e:
        # 只把"参数形状不对"认成模型的问题；工具内部写错的 TypeError
        # 继续冒泡——那不是模型能修的，藏起来只会让 bug 更难找
        msg = str(e)
        if "argument" in msg or "keyword" in msg:
            return json.dumps(
                {"ok": False, "error": f"参数不对：{msg}",
                 "error_type": "invalid_arguments"},
                ensure_ascii=False,
            )
        raise