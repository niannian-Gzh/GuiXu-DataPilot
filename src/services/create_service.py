"""新增记录。

**这个模块不认识任何业务字段。** 它只认三样东西：

  ① 表定义（`storage.describe`）——哪些列必填、哪列是唯一键
  ② 模型给的 `record`——一张「字段名 → 值」的表
  ③ 数据库——唯一约束由**部分唯一索引**在写入那一刻挡住

旧版把软著表的 19 列硬编码在 `_INSERT_COLUMNS` 里，参数顺序也写死，
连"分类必须是 web 或 嵌入式"都写在代码里。**那是测试数据的结构，
不是产品的知识。**

## 为什么不在这里查重

旧版先 `SELECT COUNT(*) WHERE project_name = ?` 再插入——那是
**先查后写**，中间有窗口期，而且再加一个唯一列就要多写一遍。
现在唯一性是**建表时声明**的（`storage.create_unique`），数据库在
INSERT 那一刻挡住，**并发也拦得住**（design 数据层第七节）。
"""

import json
import sqlite3

import storage
from audit import log
from runner import transaction, using
from services import UserInputRequired, bulk_threshold, card_records


def _columns_meta(ctx) -> tuple[dict, list[str]]:
    """(列名 → 列元信息, 错误)。"""
    d = using(storage.describe, ctx.table_name)
    return {c["name"]: c for c in d["columns"]}, []


def _prepare(record: dict, ctx) -> tuple[dict | None, list[str]]:
    """校验模型给的 record。返回 (补全后的记录, 错误列表)。

    **只做两件事：字段存在吗、必填给了吗。**
    默认值不在这里补——INSERT 时省略那一列，数据库的 DEFAULT 自然生效。
    在 Python 里再写一遍默认值，等于把同一件事说两遍，迟早漂移。
    """
    known, _ = _columns_meta(ctx)
    errors = []

    for name in record:
        if name not in known:
            errors.append(f"表里没有「{name}」这一列")

    for name, meta in known.items():
        if name in record:
            continue
        if meta["pk"] and (meta["type"] or "").upper() == "INTEGER":
            # 整型主键是 rowid 的别名，SQLite 会自动生成——新增时不该要求给
            continue
        if meta["default"] is not None:
            # **有默认值的列不算必填**：NOT NULL + DEFAULT 的意思是
            # "你不给就用默认值"，不是"你必须给"。
            continue
        if not meta["nullable"]:
            errors.append(f"缺少必填字段「{meta['note'] or name}」")

    if errors:
        return None, errors
    return {k: v for k, v in record.items() if v is not None}, []


def request_create(records: list, ctx) -> str:
    """请求新增。**单条也走数组**——一个工具只有一种参数形状。

    design 工具层把 `create` 和 `batch_create` 合成一个：确认形态、
    输入、执行、返回四项全同，只差条数。分成两个工具，只会让模型在
    "这次算单条还是批量"上多猜一次，还多一处会漂移的实现。

    **表名从 ctx 来**（`ctx.for_table(name)` 已经表达了"绑定到哪张表"），
    不再单独收一个参数——那样同一个信息会出现在两个地方，迟早不一致。
    """
    if not records:
        return json.dumps(
            {"ok": False, "error": "records 不能为空", "error_type": "invalid"},
            ensure_ascii=False,
        )

    filled, errors = [], []
    for i, r in enumerate(records, 1):
        item, errs = _prepare(r, ctx)
        # 只有一条时不必标"第 1 条"——那不是信息，是噪音
        prefix = f"第 {i} 条：" if len(records) > 1 else ""
        errors += [prefix + e for e in errs]
        if item:
            filled.append(item)

    if errors:
        return json.dumps(
            {"ok": False, "error": "；".join(errors), "error_type": "invalid"},
            ensure_ascii=False,
        )

    n = len(filled)
    labels, rows = card_records(ctx, filled)
    raise UserInputRequired(
        question=f"待新增 {n} 条，等待用户确认",
        pending_action={
            "type": "create",
            "stage": "confirm",
            "table": ctx.table_name,
            "columns": labels,
            "records": rows,
            "affected": n,
            "danger": n > bulk_threshold(),
            # —— 内部字段（执行时用，前端忽略）——
            "table_name": ctx.table_name,
            "real_table": ctx.real_table,
            # 卡片上的 records 是二维行，这里存原始记录数组——两个键不是一回事
            "values": filled,
            "user_input": ctx.trace.data["question"],
            "trace_id": ctx.trace.id,
        },
    )


def execute_create(records, table_name, trace_id, user_input):
    """写入。**整批一个事务**——要么全进，要么全不进。

    单条也走同一个事务：对一行没有额外代价，但省掉一条分支。
    分支少了，"单条和批量行为不一致"这类毛病就没有地方长出来。
    """
    try:
        with transaction() as tx:
            for r in records:
                cols = list(r)
                sql = (
                    f"INSERT INTO {storage.quote(table_name)} "
                    f"({', '.join(storage.quote(c) for c in cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})"
                )
                tx.execute(sql, [r[c] for c in cols])
    except sqlite3.IntegrityError as e:
        err = storage.translate(None, e)
        kind = "duplicate" if isinstance(err, storage.Duplicate) else "constraint"
        return json.dumps(
            {"ok": False, "error": str(err), "error_type": kind},
            ensure_ascii=False,
        )

    log("create", {
        "trace_id": trace_id, "user_input": user_input,
        "table": table_name, "affected_count": len(records),
    })
    return json.dumps(
        {"ok": True, "table": table_name, "affected": len(records)},
        ensure_ascii=False,
    )
