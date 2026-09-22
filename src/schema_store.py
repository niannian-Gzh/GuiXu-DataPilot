"""数据字典——用户对当前数据源的字段标注。

只存"用户可改的"（中文含义）；类型、必填这些"事实"从 db.describe() 读。
这样数据库变了（加列/改类型），字典不会过期。
"""

import json
import os
import threading
from config import PROJECT_ROOT
import db as db_module


META_PATH = PROJECT_ROOT / "schema_meta.json"

_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def _empty() -> dict:
    return {"version": 1, "tables": {}}


def load() -> dict:
    """读字典。带 mtime 缓存。文件不存在时返回空结构。"""
    if not META_PATH.exists():
        return _empty()

    try:
        mtime = os.path.getmtime(META_PATH)
    except OSError:
        return _cache["data"] or _empty()

    if _cache["mtime"] == mtime and _cache["data"] is not None:
        return _cache["data"]

    with _lock:
        if _cache["mtime"] != mtime:
            try:
                _cache["data"] = json.loads(META_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _cache["data"] = _empty()
            _cache["mtime"] = mtime

    return _cache["data"]


def save(data: dict) -> None:
    """写回字典，并让缓存立即失效。"""
    with _lock:
        META_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _cache["data"] = data
        try:
            _cache["mtime"] = os.path.getmtime(META_PATH)
        except OSError:
            _cache["mtime"] = None


def get_table(table: str) -> dict:
    """取一张表的元数据。不存在时返回空壳。"""
    meta = load()
    return meta.get("tables", {}).get(table, {"label": "", "fields": {}})


def get_field_label(table: str, field: str) -> str:
    """取字段的中文含义。未标注时回落到字段名。"""
    info = get_table(table)
    return info.get("fields", {}).get(field, "") or field


def get_table_schema(table: str) -> dict:
    """返回一张表的结构化 schema——字段名、类型、必填、中文含义。

    table 是视图名（如 projects）。内部按约定转真实表（projects_all）读结构。

    返回：
      {
        "name": "projects",
        "real_table": "projects_all",
        "label": "项目表",
        "fields": [
          {"name": "project_name", "type": "VARCHAR",
           "nullable": False, "label": "项目名称"},
          ...
        ]
      }
    """
    real_table = f"{table}_all"
    cols = db_module.describe(real_table)

    meta = load()
    table_meta = meta.get("tables", {}).get(table, {})
    labels = table_meta.get("fields", {})

    return {
        "name": table,
        "real_table": real_table,
        "label": table_meta.get("label", ""),
        "fields": [
            {
                "name": c["name"],
                "type": c["type"],
                "nullable": c.get("nullable", True),
                "label": labels.get(c["name"], ""),
            }
            for c in cols
        ],
    }


def get_all_tables_schema() -> list:
    """返回数据字典里所有表的结构化 schema。

    来源是 schema_meta 里的 tables——它反映"用户已认知的表"。
    库里存在但用户没标注过的表不出现在这里。
    """
    meta = load()
    return [get_table_schema(t) for t in meta.get("tables", {}).keys()]


def refresh_from_db() -> dict:
    """把库里的表/字段同步进字典。

    规则：
      - 库里有、字典里没有的表 → 加入，字段 label 留空
      - 表已存在 → 补上新字段（label 空）；移除库里已不存在的字段
      - 表的 label（用户起的名字）保留不动
      - 视图不进字典（只收 base table）

    返回 {"added_tables": [...], "added_fields": [...], "removed_fields": [...]}
    """
    meta = load()
    if "tables" not in meta:
        meta["tables"] = {}

    # 视图和真实表在业务上是同一个东西，用视图名做 key
    # （真实表 = 视图名 + "_all"）
    tables_in_db = db_module.list_tables()

    changes = {"added_tables": [], "added_fields": [], "removed_fields": []}

    for real_table in tables_in_db:
        # projects_all → projects
        if real_table.endswith("_all"):
            key = real_table[:-4]
        else:
            key = real_table

        cols = db_module.describe(real_table)
        col_names = [c["name"] for c in cols]

        if key not in meta["tables"]:
            meta["tables"][key] = {
                "label": "",
                "fields": {name: "" for name in col_names},
            }
            changes["added_tables"].append(key)
        else:
            existing = meta["tables"][key].setdefault("fields", {})
            for name in col_names:
                if name not in existing:
                    existing[name] = ""
                    changes["added_fields"].append(f"{key}.{name}")
            for name in list(existing.keys()):
                if name not in col_names:
                    del existing[name]
                    changes["removed_fields"].append(f"{key}.{name}")

    save(meta)
    return changes


if __name__ == "__main__":
    # 手动跑一次刷新
    changes = refresh_from_db()
    print(f"新增表：{changes['added_tables']}")
    print(f"新增字段：{changes['added_fields']}")
    print(f"移除字段：{changes['removed_fields']}")
    print(f"当前字典：{json.dumps(load(), ensure_ascii=False, indent=2)[:200]}...")