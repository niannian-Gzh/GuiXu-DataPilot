from dataclasses import dataclass
from typing import Any

from config import setting


class UserInputRequired(Exception):
    """需要用户输入才能继续。"""
    def __init__(self, question: str, pending_action: dict):
        super().__init__(question)
        self.question = question
        self.pending_action = pending_action


@dataclass
class ServiceContext:
    """服务层共享的依赖。

    表相关的三个字段（table_name / real_table / schema）由 for_table()
    动态填充——这样工具层能按"每次调用传入的表名"获得针对该表的上下文，
    而不是启动时绑定一张表。
    """
    llm: Any
    trace: Any
    # 表相关——for_table() 填充
    table_name: str = ""
    real_table: str = ""
    schema: str = ""

    def for_table(self, table: str) -> "ServiceContext":
        """返回一个绑定到指定表的 context 副本。

        table 是视图名（如 projects）。内部自动转真实表、读结构、渲染 schema。
        """
        from schema_store import get_table_schema
        from nl2sql import render_schema

        s = get_table_schema(table)
        return ServiceContext(
            llm=self.llm,
            trace=self.trace,
            table_name=s["name"],
            real_table=s["real_table"],
            schema=render_schema(s),
        )


def bulk_threshold() -> int:
    """影响多少条以上时，确认方式升级为手打「删除 N 条」。"""
    return setting("display.bulk_threshold")


def card_columns(ctx) -> tuple[list[str], list[str]]:
    """(英文字段名, 中文显示名)。

    卡片要显示中文列名，而后端只知道英文字段——这层翻译放在这里，
    免得 7 个 service 各写一份。没标中文的回落到字段名：
    **显示一个英文列名，也胜过显示一个空白。**
    """
    from runner import using
    from storage import describe

    d = using(describe, ctx.table_name)
    return (
        [c["name"] for c in d["columns"]],
        [c["note"] or c["name"] for c in d["columns"]],
    )


def card_records(ctx, rows: list[dict]) -> tuple[list[str], list[list]]:
    """对象数组 → 卡片的 (中文列名, 二维行)。

    **列名和数据必须一路给出去**，前端才画得出通用表格——
    它不认识任何业务字段，只认识"第几列叫什么"。
    """
    keys, labels = card_columns(ctx)
    return labels, [[r.get(k) for k in keys] for r in rows]