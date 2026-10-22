"""D8 可观测与完整性：审计、快照、回滚、关系、恢复页。

这一层不测"功能能不能用"，测的是**出事之后还找不找得回来**：
写操作有没有凭据、快照能不能把结构和约束一起复原、
删表之后版本历史还认不认得它。
"""

from __future__ import annotations

import json

import storage
import snapshot as snapshot_mod
from harness import case, check, eq, raises
from cleanup import cleanup as run_cleanup
from services import create_service, recover_service


# ============================================================ 审计

@case("D8", "写操作和审计同一个事务", "create 成功", "审计 +1，字段完整")
def audit_atomic_success(env):
    audit = env.audit_count("create")
    create_service.execute_create(
        [{"device_code": "D-400", "name": "留痕设备"}], "devices", "t-a", "留痕",
    )
    eq(env.audit_count("create"), audit + 1)
    row = env.query(
        "SELECT trace_id, tbl, detail FROM _gx_audit WHERE action = 'create' "
        "ORDER BY id DESC LIMIT 1"
    )[0]
    eq(row[0], "t-a")
    eq(row[1], "devices")
    check("留痕设备" in row[2] or "affected_count" in row[2], f"审计内容不对：{row[2]}")


@case("D8", "失败事务不写审计", "update 撞唯一约束", "审计 0 新增")
def audit_atomic_failure(env):
    audit = env.audit_count("update")
    create_service.execute_create(
        [{"device_code": "D-401", "name": "占位"}], "devices", "t-a", "占位",
    )
    from services import update_service
    result = json.loads(update_service.execute_update(
        [{"id": 1}], {"device_code": "D-401"}, "devices", "t-fail", "撞码",
    ))
    eq(result.get("ok"), False)
    eq(env.audit_count("update"), audit)


# ============================================================ 快照与回滚

@case("D8", "快照把唯一索引一起存下来", "给 devices 落快照", "ddl 里能看到 UNIQUE INDEX")
def snapshot_keeps_unique(env):
    con = env.connect()
    try:
        con.execute("BEGIN")
        sid = snapshot_mod.snapshot(con, "devices", "import")
        con.execute("COMMIT")
        ddl = con.execute(
            "SELECT ddl FROM _gx_snapshot WHERE id = ?", (sid,)
        ).fetchone()[0]
    finally:
        con.close()
    check("CREATE UNIQUE INDEX" in ddl.upper(), f"快照没存唯一索引：{ddl[:300]}")


@case("D8", "回滚把数据、约束、触发器一起复原", "快照后改数据删行，再回滚",
      "数据回来、唯一约束还在、视图能用")
def rollback_restores_everything(env):
    con = env.connect()
    try:
        con.execute("BEGIN")
        sid = snapshot_mod.snapshot(con, "devices", "import")
        con.execute("COMMIT")

        # 破坏：改值、软删一行、删一列
        con.execute("UPDATE devices_all SET is_deleted = 1, "
                    "deleted_at = '2026-10-01 09:00:00' WHERE id = 2")
        con.execute("UPDATE devices_all SET fault_count = 99 WHERE id = 1")
        storage.drop_column(con, "devices", "is_critical")
    finally:
        con.close()

    con = env.connect()
    try:
        con.execute("BEGIN")
        snapshot_mod.rollback(con, sid)
        con.execute("COMMIT")
    finally:
        con.close()

    eq(env.scalar("SELECT fault_count FROM devices WHERE id = 1"), 0, "数据没回滚")
    eq(env.count("devices"), 11, "被删的行没回来")
    eq(env.scalar("SELECT COUNT(*) FROM pragma_table_info('devices_all') "
                  "WHERE name = 'is_critical'"), 1, "被删的列没回来")

    # 唯一约束还在：插重复必须失败
    out = json.loads(create_service.execute_create(
        [{"device_code": "D-001", "name": "撞码"}], "devices", "t", "撞码",
    ))
    eq(out.get("ok"), False, "回滚后唯一约束丢了")

    # 触发器还在：新增能进视图
    out = json.loads(create_service.execute_create(
        [{"device_code": "D-777", "name": "回滚后新增"}], "devices", "t", "新增",
    ))
    eq(out.get("ok"), True, "回滚后视图触发器坏了")


@case("D8", "回滚前先给当前状态落快照", "恢复页回滚一个快照", "快照数 +1，最新一条是 rollback")
def rollback_safety_snapshot(env):
    con = env.connect()
    try:
        con.execute("BEGIN")
        sid = snapshot_mod.snapshot(con, "devices", "import")
        con.execute("COMMIT")
    finally:
        con.close()

    before = env.snapshot_count()
    out = recover_service.rollback(sid)
    eq(out.get("ok"), True)
    eq(env.snapshot_count(), before + 1)
    eq(env.scalar("SELECT kind FROM _gx_snapshot ORDER BY id DESC LIMIT 1"), "rollback")


@case("D8", "快照预览只发前 200 行", "262 行的表落快照后预览", "shown=200，total=262")
def snapshot_preview_limit(env):
    create_service.execute_create(
        [{"device_code": f"D-{9000 + i}", "name": f"压测设备{i}"} for i in range(250)],
        "devices", "t", "灌 250 行",
    )
    con = env.connect()
    try:
        con.execute("BEGIN")
        sid = snapshot_mod.snapshot(con, "devices", "import")
        con.execute("COMMIT")
        total = con.execute(
            f"SELECT COUNT(*) FROM {storage.quote(snapshot_mod.SNAP_PREFIX + str(sid))}"
        ).fetchone()[0]
    finally:
        con.close()
    eq(total, 262, "快照该有 12 原始行 + 250 新行")
    data = recover_service.preview(sid)
    eq(data["shown"], 200)
    eq(data["total"], 262)


@case("D8", "删表后快照还认得它", "删 inspections 再翻版本历史", "exists=false，快照还在")
def snapshot_survives_drop(env):
    from services import structure_service
    structure_service.execute_structure(
        {"action": "drop_table", "table_name": "inspections"}, "t", "删表",
    )
    groups = recover_service.snapshots()
    row = next((g for g in groups if g["name"] == "inspections"), None)
    check(row is not None, "删表后版本历史里找不到这张表")
    eq(row["exists"], False, "表已删，exists 还是 true")
    check(len(row["snapshots"]) >= 1, "删表前的快照没留下")


# ============================================================ 恢复页

@case("D8", "垃圾桶读底表，带上倒计时", "GET 恢复页数据", "能看到 D-012，剩余天数是数字")
def recover_deleted_listing(env):
    groups = recover_service.deleted_rows()
    row = next((g for g in groups if g["name"] == "devices"), None)
    check(row is not None, "垃圾桶里没有 devices")
    eq(row["count"], 1)
    eq(row["pk_index"], 0)
    check("删除时间" in row["columns"] and "剩余天数" in row["columns"],
          f"列名不完整：{row['columns']}")
    check(row["rows"][0][-1] is not None, "剩余天数没算出来")


@case("D8", "恢复页恢复走同一套执行端", "恢复 D-012", "视图 +1，审计 restore +1")
def recover_restore(env):
    before = env.count("devices")
    audit = env.audit_count("restore")
    out = recover_service.restore("devices", [12])
    eq(out.get("ok"), True)
    eq(env.count("devices"), before + 1)
    eq(env.audit_count("restore"), audit + 1)


@case("D8", "没有主键的表不给恢复入口", "构造一张无主键表", "pk_index=null，恢复返回错误")
def recover_requires_pk(env):
    con = env.connect()
    try:
        con.execute("CREATE TABLE loose (name TEXT, note TEXT)")
        con.execute("INSERT INTO loose VALUES ('甲', '无主键')")
    finally:
        con.close()
    groups = recover_service.deleted_rows()
    row = next((g for g in groups if g["name"] == "loose"), None)
    check(row is None, "没有软删列的表不该出现在垃圾桶")
    out = recover_service.restore("loose", [1])
    eq(out.get("ok"), False)


@case("D8", "无主键裸表不拖垮启动清理", "手工建一张没有 _all 的表再跑清理",
      "跳过它，清理不抛异常，概览与恢复读数照常")
def cleanup_skips_bare_table(env):
    # 先把 fixture 自带的过期行清掉，后面的读数才只反映这张裸表
    run_cleanup()
    before = env.client().get("/overview").json()["source"]["rows"]
    deleted = env.scalar("SELECT COUNT(*) FROM devices_all WHERE is_deleted = 1")
    con = env.connect()
    try:
        con.execute("CREATE TABLE loose (name TEXT, note TEXT)")
        con.execute("INSERT INTO loose VALUES ('甲', '乙')")
    finally:
        con.close()

    run_cleanup()                  # 修之前这里抛 no such table: loose_all
    eq(env.count("loose"), 1, "裸表不该被清理动到")
    after = env.client().get("/overview").json()["source"]["rows"]
    eq(after, before + 1, "概览没把裸表的行算进去")
    eq(recover_service.counts()["deleted"], int(deleted), "恢复读数被裸表拖垮")


@case("D8", "裸表在数据字典里照常可读", "手工建裸表后 GET /schema",
      "字段可见，real_table 指向它自己")
def bare_table_schema(env):
    con = env.connect()
    try:
        con.execute("CREATE TABLE loose (name TEXT, note TEXT)")
    finally:
        con.close()

    data = env.client().get("/schema").json()
    t = next((x for x in data["tables"] if x["name"] == "loose"), None)
    check(t is not None, "裸表没被列出来")
    eq(t["real_table"], "loose", "real_table 指向了不存在的 loose_all")
    eq([f["name"] for f in t["fields"]], ["name", "note"], "字段读不出来")
    eq(t["pk"], None, "无主键表不该报主键")


# ============================================================ 数据字典与关系

@case("D8", "字典的约束从库里现读", "GET /schema", "pk=id，唯一约束对得上")
def schema_constraints(env):
    data = env.client().get("/schema").json()
    tables = {t["name"]: t for t in data["tables"]}
    check("devices" in tables and "inspections" in tables, "表不全")
    eq(tables["devices"]["pk"], "id")
    check(["device_code"] in tables["devices"]["uniques"],
          f"devices 唯一约束不对：{tables['devices']['uniques']}")
    check(["device_id", "inspected_on"] in tables["inspections"]["uniques"],
          f"组合唯一不对：{tables['inspections']['uniques']}")


@case("D8", "关系一端声明、两端都显示", "GET /schema", "devices 出、inspections 入")
def schema_relations_both_sides(env):
    data = env.client().get("/schema").json()
    tables = {t["name"]: t for t in data["tables"]}
    out = [r for r in tables["devices"]["relations"] if r["dir"] == "out"]
    into = [r for r in tables["inspections"]["relations"] if r["dir"] == "in"]
    check(len(out) >= 1, "devices 没有出向关系")
    check(len(into) >= 1, "inspections 没有入向关系")
    eq(out[0]["to_table"], "inspections")
    eq(into[0]["from_table"], "devices")


@case("D8", "加关系立即落库，删关系立即消失", "POST 再 DELETE", "GET /schema 跟着变")
def relation_roundtrip(env):
    client = env.client()
    resp = client.post("/schema/relations", json={
        "from_table": "inspections", "from_column": "id",
        "to_table": "devices", "to_column": "id", "cardinality": "N:1",
    })
    eq(resp.status_code, 200)
    data = client.get("/schema").json()
    tables = {t["name"]: t for t in data["tables"]}
    check(any(r["from_table"] == "inspections" and r["to_table"] == "devices"
              for r in tables["inspections"]["relations"]), "新关系没出现")

    resp = client.delete("/schema/relations", params={
        "from_table": "inspections", "from_column": "id",
        "to_table": "devices", "to_column": "id",
    })
    eq(resp.status_code, 200)
    data = client.get("/schema").json()
    tables = {t["name"]: t for t in data["tables"]}
    check(not any(r["from_table"] == "inspections" and r["to_table"] == "devices"
                  for r in tables["inspections"]["relations"]), "关系没删掉")


@case("D8", "自关联只显示一条", "devices.id → devices.id", "不出左右两条")
def relation_self_once(env):
    env.client().post("/schema/relations", json={
        "from_table": "devices", "from_column": "id",
        "to_table": "devices", "to_column": "id", "cardinality": "1:N",
    })
    data = env.client().get("/schema").json()
    tables = {t["name"]: t for t in data["tables"]}
    self_rels = [r for r in tables["devices"]["relations"]
                 if r["from_table"] == "devices" and r["to_table"] == "devices"]
    eq(len(self_rels), 1, "自关联被画成了两条")


# ============================================================ trace

@case("D8", "trace 每轮落一条", "写一条 trace", "traces.jsonl 多一行且字段完整")
def trace_written(env):
    from trace import Trace
    t = Trace("评测用问题")
    t.set("sql", "SELECT 1")
    t.mark_end()
    t.save()
    path = env.box.root / "traces.jsonl"
    check(path.exists(), "trace 文件没生成")
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    eq(row["question"], "评测用问题")
    check(row["elapsed_ms"] is not None, "elapsed_ms 没填")


# ============================================================ 结构升级

@case("D8", "旧库升级：先备份，版本升到 1，数据不动",
      "把库标成 user_version=0 再打开", "备份存在，行数不变")
def schema_upgrade_backup(env):
    import sqlite3

    from migrations import schema_version

    before = env.count("devices_all")
    raw = sqlite3.connect(env.box.db_path)
    try:
        raw.execute("PRAGMA user_version = 0")
        raw.commit()
    finally:
        raw.close()

    con = env.connect()
    try:
        eq(schema_version(con), 1)
        eq(con.execute("SELECT COUNT(*) FROM devices_all").fetchone()[0], before)
    finally:
        con.close()

    backups = list((env.box.root / "backups").glob("guixu-v0-*.db"))
    check(backups, "升级前没有留备份")


@case("D8", "库比程序新时拒绝打开", "把 user_version 改成 99",
      "抛 SchemaTooNewError，不碰表")
def schema_too_new_refused(env):
    import sqlite3

    from migrations import SchemaTooNewError

    raw = sqlite3.connect(env.box.db_path)
    try:
        raw.execute("PRAGMA user_version = 99")
        raw.commit()
    finally:
        raw.close()

    try:
        raises(lambda: env.connect(), SchemaTooNewError)
    finally:
        raw = sqlite3.connect(env.box.db_path)
        try:
            raw.execute("PRAGMA user_version = 1")
            raw.commit()
        finally:
            raw.close()
