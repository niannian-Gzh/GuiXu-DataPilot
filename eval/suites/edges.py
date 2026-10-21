"""D5 边界与畸形输入：空、太长、太怪、同时来。

这些不是"攻击"，是**真实用户和模型都会撞上的形状**：
问了个不存在的结果、表名起成系统前缀、值里带引号、
两个请求同时写同一个编号。
"""

from __future__ import annotations

import json
import threading

from harness import case, eq
from services import ServiceContext, UserInputRequired
from services import create_service, query_service
from services.structure_service import request_create_table
from trace import Trace


class _SqlLLM:
    """只会回一句 SQL 的假模型。用来把 query_service 离线跑通。"""
    mock = False
    capabilities = {"context_window": 32000, "reasoning_echo": False}

    def __init__(self, sql: str):
        self.sql = sql

    def chat(self, system, user):
        return self.sql


def _ctx():
    return ServiceContext(llm=None, trace=Trace("评测"))


@case("D5", "空结果是事实，不是失败", "查询没有匹配行",
      "status=empty，并给出表里总行数做参照")
def empty_result_is_fact(env):
    ctx = ServiceContext(
        llm=_SqlLLM("SELECT * FROM devices WHERE fault_count > 100"),
        trace=Trace("空结果"),
    ).for_table("devices")
    data = json.loads(query_service.run("故障超过 100 的设备", ctx))
    eq(data.get("ok"), True)
    eq(data.get("status"), "empty")
    eq(data.get("row_count"), 0)
    eq(data.get("total_records_in_table"), env.truth().count())


@case("D5", "空表查询不崩", "把 devices 清空再查", "status=empty，total=0")
def empty_table(env):
    con = env.connect()
    try:
        con.execute("DELETE FROM devices_all")
    finally:
        con.close()
    ctx = ServiceContext(
        llm=_SqlLLM("SELECT * FROM devices"), trace=Trace("空表"),
    ).for_table("devices")
    data = json.loads(query_service.run("有哪些设备", ctx))
    eq(data.get("status"), "empty")
    eq(data.get("total_records_in_table"), 0)


@case("D5", "系统前缀的表名不能建", "create_table('_gx_evil')",
      "拒绝，否则建出来的表会被所有列表过滤掉")
def edge_table_name_system_prefix(env):
    try:
        out = request_create_table(
            "_gx_evil", [{"name": "title", "type": "TEXT"}], ctx=_ctx(),
        )
    except UserInputRequired:
        raise AssertionError("系统前缀表名进入了确认流程，建出来会从所有列表里消失")
    data = json.loads(out)
    eq(data.get("ok"), False)


@case("D5", "底表后缀的表名不能建", "create_table('devices_all')",
      "拒绝，否则新表会被当成底表藏起来")
def edge_table_name_softdel_suffix(env):
    try:
        out = request_create_table(
            "devices_all", [{"name": "title", "type": "TEXT"}], ctx=_ctx(),
        )
    except UserInputRequired:
        raise AssertionError("底表后缀表名进入了确认流程，建出来会从所有列表里消失")
    data = json.loads(out)
    eq(data.get("ok"), False)


@case("D5", "空表名不能建", "create_table('')", "拒绝，不进确认流程")
def edge_table_name_empty(env):
    try:
        out = request_create_table("", [{"name": "title", "type": "TEXT"}], ctx=_ctx())
    except UserInputRequired:
        raise AssertionError("空表名进入了确认流程")
    data = json.loads(out)
    eq(data.get("ok"), False)


@case("D5", "带引号和分号的值原样存取", "name=O'Reilly; -- \"x\"",
      "存进去是什么，读出来就是什么")
def edge_special_chars(env):
    evil = "O'Reilly; -- \"x\""
    out = json.loads(create_service.execute_create(
        [{"device_code": "D-600", "name": evil}], "devices", "t", "特殊字符",
    ))
    eq(out.get("ok"), True)
    eq(env.scalar("SELECT name FROM devices WHERE device_code = 'D-600'"), evil)


@case("D5", "超长文本能存能取", "note 10000 字符", "原样读回")
def edge_long_text(env):
    long_note = "长" * 10000
    out = json.loads(create_service.execute_create(
        [{"device_id": 1, "inspected_on": "2026-10-01", "result": "正常",
          "score": 80, "note": long_note}],
        "inspections", "t", "长文本",
    ))
    eq(out.get("ok"), True)
    got = env.scalar("SELECT note FROM inspections WHERE inspected_on = '2026-10-01'")
    eq(len(got), 10000)


@case("D5", "NULL 参与排序不炸", "ORDER BY last_inspection", "11 行都在，NULL 不丢")
def edge_null_sort(env):
    rows = env.query("SELECT id FROM devices ORDER BY last_inspection DESC, id")
    eq(len(rows), 11)
    nulls = env.query("SELECT COUNT(*) FROM devices WHERE last_inspection IS NULL")[0][0]
    eq(nulls, 2)


@case("D5", "并发写不同编号都成功", "两个线程同时新增不同 device_code", "两条都进")
def edge_concurrent_insert_different(env):
    results = []
    barrier = threading.Barrier(2)

    def worker(code):
        barrier.wait()
        results.append(create_service.execute_create(
            [{"device_code": code, "name": code}], "devices", "t", "并发",
        ))

    threads = [threading.Thread(target=worker, args=(c,))
               for c in ("D-701", "D-702")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = sum(json.loads(r).get("ok") is True for r in results)
    eq(ok, 2)
    eq(env.scalar("SELECT COUNT(*) FROM devices "
                  "WHERE device_code IN ('D-701', 'D-702')"), 2)


@case("D5", "并发写同一个编号只进一条", "两个线程同时新增 D-703",
      "一个成功一个 duplicate，库里只有一条")
def edge_concurrent_insert_same(env):
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(create_service.execute_create(
            [{"device_code": "D-703", "name": "并发同码"}], "devices", "t", "并发",
        ))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    parsed = [json.loads(r) for r in results]
    eq(sum(p.get("ok") is True for p in parsed), 1, "同码并发写进了不止一条")
    eq(env.scalar("SELECT COUNT(*) FROM devices WHERE device_code = 'D-703'"), 1)
    # 失败那条不能留下半条审计
    eq(env.audit_count("create"), 1)
