import json
import duckdb
from nl2sql import get_schema, generate_sql_with_retry, SCHEMA_DESC
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
                "请求删除符合条件的项目记录。用户可以用自然语言描述筛选条件"
                "（如'家装项目'、'所有 web 类项目'、'所有项目'）。"
                "系统会搜索匹配记录、展示候选、请求确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_question": {
                        "type": "string",
                        "description": "自然语言筛选条件。删除全部时传'所有项目'。",
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
            "name": "request_batch_create",
            "description": (
                "请求批量新增项目记录。当用户一次要求新增多条记录时使用。"
                "系统会校验所有记录（必填字段、分类合法性、内部重复、数据库重复），"
                "任何一条不通过则全部拒绝。校验通过后请求用户确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "description": "要新增的记录列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "project_name": {"type": "string", "description": "项目名称"},
                                "owner": {"type": "string", "description": "负责人姓名"},
                                "category": {"type": "string", "description": "分类，web 或 嵌入式"},
                                "status_raw": {"type": "string", "description": "状态，默认'已提交'"},
                                "issued_date": {"type": "string", "description": "下发时间 YYYY-MM-DD，默认今天"},
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
            "name": "request_update",
            "description": (
                "请求修改符合条件的项目记录。用户可以用自然语言描述筛选条件。"
                "系统会搜索匹配记录，展示改前改后对比，请求用户确认。"
                "注意：多条匹配时会执行批量修改。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_question": {
                        "type": "string",
                        "description": "自然语言筛选条件。",
                    },
                    "updates": {
                        "type": "object",
                        "description": "要修改的字段和值。字段名用英文。",
                    },
                },
                "required": ["filter_question", "updates"],
            },
        },
    },
]

AMBIGUOUS_FIELD_MAP = {
    "is_settled = true": ("status_raw = '已结算'", "精确匹配：状态恰好是'已结算'"),
    "is_certified = true": ("status_raw = '已下证'", "精确匹配：状态恰好是'已下证'"),
    "is_rejected = true": ("status_raw = '已打回'", "精确匹配：状态恰好是'已打回'"),
    "is_pending = true": ("status_raw = '待提交'", "精确匹配：状态恰好是'待提交'"),
    "is_submitted = true": ("status_raw = '已提交'", "精确匹配：状态恰好是'已提交'"),
}


def _detect_ambiguity(sql: str, df, db_path: str):
    """检测 SQL 是否有歧义解读。只在 SQL 用了布尔字段时检测。"""
    for old, (new, description) in AMBIGUOUS_FIELD_MAP.items():
        if old in sql:
            alt_sql = sql.replace(old, new)
            try:
                alt_df = execute_sql(alt_sql, db_path)
            except Exception:
                continue

            if df.to_string() != alt_df.to_string():
                def extract_value(d):
                    if d.shape == (1, 1):
                        return str(d.iloc[0, 0])
                    return f"{d.shape[0]} 行"

                return {
                    "ambiguous": True,
                    "branches": [
                        {
                            "interpretation": f"包含匹配（默认，含组合状态）",
                            "value": extract_value(df),
                        },
                        {
                            "interpretation": description,
                            "value": extract_value(alt_df),
                        },
                    ],
                }
    return None

def build_tool_functions(llm, db_path: str, table_name: str, trace):
    schema = get_schema(db_path, table_name)
    real_table = f"{table_name}_all"

    def query_database(question: str) -> str:
        try:
            sql, _ = generate_sql_with_retry(
                question, llm, schema, db_path, table_name, max_retries=2
            )
            df = execute_sql(sql, db_path)
            answer = summarize(question, df, llm)

            result = {
                "sql": sql,
                "row_count": len(df),
                "answer": answer,
            }

            # A2：检测歧义
            ambiguity = _detect_ambiguity(sql, df, db_path)
            if ambiguity:
                result.update(ambiguity)

            # 空结果
            if len(df) == 0:
                con = duckdb.connect(db_path, read_only=True)
                total = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                con.close()
                result["total_records_in_table"] = total
                result["hint"] = (
                    f"查询已完整执行，无报错。表中共有 {total} 条记录，"
                    f"符合当前筛选条件的为 0 条。这个结果是可信的。"
                )

            return json.dumps(result, ensure_ascii=False)
        except SecurityError as e:
            return json.dumps({"error": f"安全拒绝：{e}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def request_delete(filter_question: str) -> str:
        candidates = find_candidates(filter_question, llm, schema, db_path, table_name)
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

    def request_update(filter_question: str, updates: dict) -> str:
        forbidden = {"is_deleted", "deleted_at", "deleted_by", "delete_trace_id"}
        for field in updates:
            if field in forbidden:
                return json.dumps(
                    {"error": f"字段 {field} 不允许修改"},
                    ensure_ascii=False,
                )

        # 字段名校验：必须在表结构里
        valid_fields = set(SCHEMA_DESC.keys())
        for field in updates:
            if field not in valid_fields:
                return json.dumps(
                    {
                        "error": f"字段 {field} 不存在。可用字段：{sorted(valid_fields)}",
                    },
                    ensure_ascii=False,
                )

        candidates = find_candidates(filter_question, llm, schema, db_path, table_name)
        if not candidates:
            return json.dumps(
                {"status": "not_found", "message": "没有找到匹配的记录"},
                ensure_ascii=False,
            )

        pending = {
            "type": "update",
            "stage": "confirm",
            "candidates": candidates,
            "updates": updates,
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

    def request_batch_create(records: list) -> str:
        if not records:
            return json.dumps({"error": "records 不能为空"}, ensure_ascii=False)

        # 校验每条
        errors = []
        for i, r in enumerate(records, 1):
            if not r.get("project_name"):
                errors.append(f"第{i}条：缺少项目名")
            if not r.get("owner"):
                errors.append(f"第{i}条：缺少负责人")
            if r.get("category") not in ("web", "嵌入式"):
                errors.append(f"第{i}条：分类必须是 web 或 嵌入式，收到：{r.get('category')}")

        if errors:
            return json.dumps({"error": "；".join(errors)}, ensure_ascii=False)

        # 内部重复检查
        names = [r["project_name"] for r in records]
        if len(names) != len(set(names)):
            return json.dumps(
                {"error": "本次新增的记录中存在重复的项目名"},
                ensure_ascii=False,
            )

        # 数据库重复检查
        con = duckdb.connect(db_path)
        placeholders = ",".join(["?"] * len(names))
        existing = con.execute(
            f"SELECT project_name FROM {real_table} "
            f"WHERE project_name IN ({placeholders}) AND is_deleted = false",
            names,
        ).fetchall()
        con.close()

        if existing:
            existing_names = [e[0] for e in existing]
            return json.dumps(
                {"error": f"以下项目已存在，不能重复新增：{existing_names}"},
                ensure_ascii=False,
            )

        # 构造完整记录
        full_records = []
        for r in records:
            full_records.append({
                "project_name": r["project_name"],
                "owner": r["owner"],
                "category": r["category"],
                "status_raw": r.get("status_raw", "已提交"),
                "issued_date": r.get("issued_date") or date.today().isoformat(),
                "certified_date": None,
                "resubmit_name": None,
                "reject_date": None,
                "resubmit_date": None,
                "reject_count": 0,
            })

        pending = {
            "type": "batch_create",
            "stage": "confirm",
            "records": full_records,
            "user_input": trace.data["question"],
            "trace_id": trace.id,
        }
        raise UserInputRequired(
            question=f"待新增 {len(records)} 条，等待用户确认",
            pending_action=pending,
        )


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