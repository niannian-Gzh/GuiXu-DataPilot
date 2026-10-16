"""数据字典——**薄转发层**，真东西已经搬进库里了。

## 它从前是什么

旧版把用户标注的中文含义存在 `schema_meta.json` 一个文件里，
靠 mtime 缓存，还要 `refresh_from_db()` 定期跟库对账——因为
**文件会跟库脱节**。

## 它现在是什么

标注存在库内的 `_gx_meta` 表里（`storage.set_note`），结构**实时读**
（`storage.describe` 每次都走 PRAGMA）。于是"脱节"这件事不存在了，
`refresh_from_db()` 只剩下一个用途：**发现库里冒出来的新表**——
而那正是 `storage.repair()`。

design 那句"没有硬编码、没有 JSON 文件、没有第二份"说的是这个。

## 为什么还留着这个壳

因为调用点有 13 处、散在 8 个文件，其中一半在**上层**
（agent 拼提示词、nl2sql 渲染 schema、services 取字段中文名）。
硬改它们等于提前做"逐层改造"那一轮的活。

留着壳，**这一轮就能独立验证**：换完数据源，上层行为应该
一模一样——不一样，就是数据层换错了，而不是上层也在改。

**死期**：工具层 / 交互层改造时，调用方直接对 `storage` 说话，
这个文件删掉。
"""

from runner import connect, using
import storage
from storage import SOFTDEL_SUFFIX, describe as _describe, list_tables as _list


def load() -> dict:
    """整个字典，**旧形状**（`{"version", "tables": {表: {label, fields}}}`）。

    从库内 meta 现拼。保留旧形状是为了让 api.py 那几处少改。
    """
    def _build(con):
        out = {"version": 1, "tables": {}}
        for name in _list(con):
            d = _describe(con, name)
            out["tables"][name] = {
                "label": d["note"],
                "fields": {c["name"]: c["note"] for c in d["columns"]},
            }
        return out

    return using(_build)


def save(data: dict) -> None:
    """把整个字典写回库。

    逐条 `set_note`——**库内 meta 表就是真源**，没有第二份要同步。
    """
    def _write(con):
        for table, info in (data.get("tables") or {}).items():
            storage.set_note(con, table, "", (info or {}).get("label", ""))
            for field, label in ((info or {}).get("fields") or {}).items():
                storage.set_note(con, table, field, label or "")

    using(_write)


def get_table(table: str) -> dict:
    """取一张表的元数据。不存在时返回空壳。"""
    return load().get("tables", {}).get(table, {"label": "", "fields": {}})


def get_field_label(table: str, field: str) -> str:
    """取字段的中文含义。未标注时回落到字段名。

    回落是**有意的**：给模型看的东西里出现一个空字符串，它不知道
    那是什么意思；出现字段名，它至少知道这是哪个字段。
    """
    info = get_table(table)
    return info.get("fields", {}).get(field, "") or field


def get_table_schema(table: str) -> dict:
    """一张表的结构化 schema——字段名、类型、必填、中文含义。

    **旧形状**（`real_table` / `fields[].label`），给上层那两个
    渲染器（agent 的表单、nl2sql 的 render_schema）继续用。
    """
    def _build(con):
        d = _describe(con, table)
        return {
            "name": table,
            "real_table": table + SOFTDEL_SUFFIX,
            "label": d["note"],
            "fields": [
                {
                    "name": c["name"],
                    "type": c["type"],
                    "nullable": c["nullable"],
                    "label": c["note"],
                }
                for c in d["columns"]
            ],
        }

    return using(_build)


def get_all_tables_schema() -> list:
    """所有业务表的结构化 schema（旧形状）。"""
    return [get_table_schema(t) for t in using(_list)]


def refresh_from_db() -> dict:
    """跟库对账。**新设计里它只剩一件事**：把没保护的裸表补上。

    返回的 key 保持旧形状（api.py 拿它显示"新增了几张表"）。
    以前它还会同步字段增删——现在不需要了：结构是实时读的，
    库里加一列，`describe()` 下一次就看见，字典没有"过期"这回事。
    """
    result = using(storage.repair)
    return {
        "added_tables": [f.split("（")[0] for f in result["fixed"]],
        "added_fields": [],
        "removed_fields": [],
        "skipped": result["skipped"],
    }


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("当前字典：")
    for name, info in load()["tables"].items():
        label = info["label"] or "（未命名）"
        print(f"  {name}（{label}）")
        for field, note in info["fields"].items():
            print(f"    {field:<16} {note}")
    changes = refresh_from_db()
    print(f"\n刷新：{changes}")
