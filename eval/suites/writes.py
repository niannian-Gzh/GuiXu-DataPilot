"""D2 写操作：增、删、改、恢复、变换、导入、结构变更。

每条都断言三件事里的两件以上：**目标数据变了、别处没变、审计记了**。
只断言"返回 ok"是不够的——这个项目出过"返回成功但实际没写"的坑。
"""

from __future__ import annotations

import json

from harness import case, check, eq
from services import create_service, delete_service, restore_service
from services import update_service, transform_service, structure_service
from services import import_service


def _ok(result: str) -> dict:
    data = json.loads(result)
    check(data.get("ok") is True, f"操作没成功：{result[:300]}")
    return data


# ============================================================ 新增

@case("D2", "新增一条：进库、可见、有审计", "create 一条新设备", "视图 +1，审计 create +1")
def create_one(env):
    before = env.count("devices")
    audit = env.audit_count("create")
    _ok(create_service.execute_create(
        [{"device_code": "D-100", "name": "新设备", "status": "在用"}],
        "devices", "t-create", "新增一台",
    ))
    eq(env.count("devices"), before + 1)
    eq(env.scalar("SELECT name FROM devices WHERE device_code = 'D-100'"), "新设备")
    eq(env.audit_count("create"), audit + 1)


@case("D2", "批量新增：整批一个事务", "create 两条", "两条都进，审计一条")
def create_batch(env):
    before = env.count("devices")
    audit = env.audit_count("create")
    _ok(create_service.execute_create(
        [
            {"device_code": "D-101", "name": "批量甲", "status": "在用"},
            {"device_code": "D-102", "name": "批量乙", "status": "停用"},
        ],
        "devices", "t-batch", "批量新增",
    ))
    eq(env.count("devices"), before + 2)
    eq(env.audit_count("create"), audit + 1)


@case("D2", "唯一冲突被数据库挡住", "新增一个已存在的 device_code", "ok=false，数据不变，审计不增")
def create_duplicate(env):
    before = env.count("devices")
    audit = env.audit_count("create")
    data = json.loads(create_service.execute_create(
        [{"device_code": "D-001", "name": "撞码设备"}],
        "devices", "t-dup", "撞码",
    ))
    eq(data.get("ok"), False)
    eq(env.count("devices"), before)
    eq(env.audit_count("create"), audit)


@case("D2", "缺必填被拒且不落半条", "device_code 没给", "ok=false，数据不变")
def create_missing_required(env):
    before = env.count("devices")
    data = json.loads(create_service.execute_create(
        [{"name": "没编号的设备"}], "devices", "t-miss", "缺字段",
    ))
    eq(data.get("ok"), False)
    eq(env.count("devices"), before)


# ============================================================ 修改

@case("D2", "修改只动目标行", "把 id=1 的 owner 改成孙工", "只有第一行变")
def update_target_only(env):
    before_other = env.scalar("SELECT owner FROM devices WHERE id = 2")
    _ok(update_service.execute_update(
        [{"id": 1}], {"owner": "孙工"}, "devices", "t-upd", "改负责人",
    ))
    eq(env.scalar("SELECT owner FROM devices WHERE id = 1"), "孙工")
    eq(env.scalar("SELECT owner FROM devices WHERE id = 2"), before_other)
    eq(env.audit_count("update"), 1)


@case("D2", "改成重复值被拒", "把 D-001 的编号改成 D-002", "ok=false，值不变")
def update_duplicate(env):
    data = json.loads(update_service.execute_update(
        [{"id": 1}], {"device_code": "D-002"}, "devices", "t-dup", "改编号",
    ))
    eq(data.get("ok"), False)
    eq(env.scalar("SELECT device_code FROM devices WHERE id = 1"), "D-001")


# ============================================================ 删除与恢复

@case("D2", "删除是软删：视图看不到、底表还在", "删 id=1", "视图 -1，底表 is_deleted=1")
def delete_soft(env):
    before = env.count("devices")
    audit = env.audit_count("soft_delete")
    eq(delete_service.execute_delete([{"id": 1}], "devices", "t-del", "删一台"), 1)
    eq(env.count("devices"), before - 1)
    eq(env.scalar("SELECT is_deleted FROM devices_all WHERE id = 1"), 1)
    eq(env.audit_count("soft_delete"), audit + 1)


@case("D2", "恢复把行放回视图", "先删再恢复 id=1", "视图 +1，deleted_at 清空")
def restore_row(env):
    delete_service.execute_delete([{"id": 1}], "devices", "t-del", "先删")
    before = env.count("devices")
    audit = env.audit_count("restore")
    restore_service.execute_restore([{"id": 1}], "devices", "t-res", "再恢复")
    eq(env.count("devices"), before + 1)
    eq(env.scalar("SELECT deleted_at FROM devices_all WHERE id = 1"), None)
    eq(env.audit_count("restore"), audit + 1)


@case("D2", "恢复撞唯一约束要干净失败", "删 D-001 → 新建 D-001 → 恢复旧的",
      "不裸抛异常；新行和旧行都不能丢")
def restore_conflict(env):
    delete_service.execute_delete([{"id": 1}], "devices", "t-del", "先删")
    _ok(create_service.execute_create(
        [{"device_code": "D-001", "name": "新占位"}], "devices", "t-new", "占名",
    ))

    # 用户能走到的是恢复页/对话这条路径，不是直接调 execute_restore
    from services import recover_service
    out = recover_service.restore("devices", [1])
    eq(out.get("ok"), False, "撞了唯一约束却报告恢复成功")

    eq(env.scalar(
        "SELECT COUNT(*) FROM devices WHERE device_code = 'D-001'"
    ), 1, "活着的 D-001 应该只有新占位那条")
    eq(env.scalar(
        "SELECT name FROM devices WHERE device_code = 'D-001'"
    ), "新占位", "新行被旧行覆盖了")
    eq(env.scalar("SELECT is_deleted FROM devices_all WHERE id = 1"), 1,
       "旧行不该被恢复")


# ============================================================ 规则变换

@case("D2", "按规则改值，只动命中行", "fault_count = fault_count + 1 WHERE id=1",
      "第一行 +1，第二行不变，审计 transform")
def transform_apply(env):
    before = env.scalar("SELECT fault_count FROM devices WHERE id = 2")
    audit = env.audit_count("transform")
    out = transform_service.execute_transform(
        {"update_sql": "UPDATE devices SET fault_count = fault_count + 1 WHERE id = 1",
         "affected": 1},
        "devices", "t-tr", "故障次数加一",
    )
    _ok(out)
    eq(env.scalar("SELECT fault_count FROM devices WHERE id = 1"), 1)
    eq(env.scalar("SELECT fault_count FROM devices WHERE id = 2"), before)
    eq(env.audit_count("transform"), audit + 1)


@case("D4", "规则变换不能改系统表", "guard 收到 UPDATE _gx_audit SET action=...",
      "check_transform_safety 必须拒绝")
def transform_system_table_blocked(env):
    from guard import check_transform_safety
    ok, reason, _ = check_transform_safety(
        "UPDATE _gx_audit SET action = 'tampered'"
    )
    check(not ok, f"规则变换可以改审计表（{reason}）")


@case("D4", "规则变换不能改系统列", "UPDATE devices SET is_deleted = 1",
      "check_transform_safety 拒绝")
def transform_system_column_blocked(env):
    from guard import check_transform_safety
    ok, reason, _ = check_transform_safety("UPDATE devices SET is_deleted = 1")
    check(not ok, f"规则变换可以改系统列（{reason}）")


# ============================================================ 结构变更

@case("D2", "加列：视图跟上、旧数据不动", "给 devices 加 priority TEXT",
      "列存在，11 行还在，审计 structure")
def structure_add_column(env):
    before = env.count("devices")
    audit = env.audit_count("structure")
    _ok(structure_service.execute_structure({
        "action": "add_column", "table_name": "devices",
        "coldef": '"priority" TEXT', "column": "priority", "label": "优先级",
    }, "t-add", "加一列"))
    eq(env.scalar("SELECT COUNT(*) FROM pragma_table_info('devices_all') "
                  "WHERE name = 'priority'"), 1, "列没加上")
    eq(env.count("devices"), before)
    eq(env.audit_count("structure"), audit + 1)


@case("D2", "删列前先落快照，数据其余列不动", "删 devices.is_critical",
      "列没了，行数不变，快照 +1")
def structure_drop_column(env):
    before = env.count("devices")
    snap = env.snapshot_count()
    _ok(structure_service.execute_structure({
        "action": "drop_column", "table_name": "devices", "column": "is_critical",
    }, "t-drop-col", "删列"))
    eq(env.scalar("SELECT COUNT(*) FROM pragma_table_info('devices_all') "
                  "WHERE name = 'is_critical'"), 0)
    eq(env.count("devices"), before)
    eq(env.snapshot_count(), snap + 1)
    # 视图能正常查询，说明触发器重建过了
    eq(env.scalar("SELECT COUNT(*) FROM devices"), before)


@case("D2", "改列类型后唯一约束还在", "fault_count INTEGER → TEXT", "唯一索引仍能挡重复")
def structure_alter_column(env):
    _ok(structure_service.execute_structure({
        "action": "alter_column", "table_name": "devices",
        "column": "fault_count", "new_type": "TEXT",
    }, "t-alt", "改类型"))
    eq(env.count("devices"), 11)
    # 唯一约束还在的最硬证据：插重复编号必须失败
    data = json.loads(create_service.execute_create(
        [{"device_code": "D-002", "name": "撞码"}], "devices", "t", "撞码",
    ))
    eq(data.get("ok"), False, "改列类型后唯一约束丢了")


@case("D2", "建表：视图、底表、触发器齐全", "建一张备件表", "能插能查")
def structure_create_table(env):
    _ok(structure_service.execute_structure({
        "action": "create_table", "table_name": "spare_parts",
        "new_table": "spare_parts",
        "coldefs": '"id" INTEGER PRIMARY KEY, "part_code" TEXT NOT NULL, "qty" INTEGER',
        "unique": [],
    }, "t-create-tbl", "建表"))
    check(env.table_exists("spare_parts") and env.table_exists("spare_parts_all"),
          "视图或底表没建出来")
    _ok(create_service.execute_create(
        [{"part_code": "P-1", "qty": 3}], "spare_parts", "t", "加备件",
    ))
    eq(env.scalar("SELECT qty FROM spare_parts WHERE part_code = 'P-1'"), 3)


@case("D2", "删表：视图底表关系一起清，快照留着", "删 inspections",
      "表没了、关系没了、快照还在")
def structure_drop_table(env):
    snap = env.snapshot_count()
    _ok(structure_service.execute_structure({
        "action": "drop_table", "table_name": "inspections",
    }, "t-drop-tbl", "删表"))
    check(not env.table_exists("inspections_all"), "底表还在")
    eq(env.scalar("SELECT COUNT(*) FROM _gx_relation WHERE "
                  "from_table = 'inspections' OR to_table = 'inspections'"), 0)
    eq(env.snapshot_count(), snap + 1, "删表前没落快照")


# ============================================================ 导入

@case("D2", "导入新记录", "scan 里一条新设备", "inserted=1，审计 import")
def import_new(env):
    before = env.count("devices")
    audit = env.audit_count("import")
    out = import_service.execute_import(
        {"key_column": "device_code",
         "new_records": [{"device_code": "D-200", "name": "导入甲", "status": "在用"}],
         "conflicts": [], "deleted_in_db": []},
        {}, "keep", "db", "devices", "t-imp", "导入",
    )
    _ok(out)
    eq(env.count("devices"), before + 1)
    eq(env.audit_count("import"), audit + 1)


@case("D2", "冲突按 Excel 为准更新", "D-002 的 status 改成停用", "库里跟着变")
def import_conflict_excel(env):
    out = import_service.execute_import(
        {"key_column": "device_code", "new_records": [],
         "conflicts": [{"key": "D-002", "excel_data": {
             "device_code": "D-002", "name": "冷却塔-B", "status": "停用"}}],
         "deleted_in_db": []},
        {}, "keep", "excel", "devices", "t-imp", "导入",
    )
    _ok(out)
    eq(env.scalar("SELECT status FROM devices WHERE device_code = 'D-002'"), "停用")


@case("D2", "导入恢复已删行", "D-012 在 Excel 里重新出现", "恢复，视图 +1")
def import_restore_deleted(env):
    before = env.count("devices")
    out = import_service.execute_import(
        {"key_column": "device_code", "new_records": [], "conflicts": [],
         "deleted_in_db": [{"key": "D-012"}]},
        {}, "restore", "db", "devices", "t-imp", "导入",
    )
    _ok(out)
    eq(env.count("devices"), before + 1)
    eq(env.scalar("SELECT deleted_at FROM devices_all WHERE id = 12"), None)


@case("D2", "导入整批失败要全回滚", "两条新记录，第二条撞唯一", "一条都不进，审计不增")
def import_rollback(env):
    before = env.count("devices")
    audit = env.audit_count("import")
    out = json.loads(import_service.execute_import(
        {"key_column": "device_code",
         "new_records": [
             {"device_code": "D-300", "name": "甲"},
             {"device_code": "D-001", "name": "撞码乙"},
         ],
         "conflicts": [], "deleted_in_db": []},
        {}, "keep", "db", "devices", "t-imp", "导入",
    ))
    eq(out.get("ok"), False, "整批失败却报告成功")
    eq(out.get("error_type"), "duplicate")
    eq(env.count("devices"), before, "第一批记录没有回滚")
    eq(env.audit_count("import"), audit, "失败事务写了审计")


# ============================================================ 软删隔离

@case("D8", "软删行不出现在任何业务读路径", "查视图 / 导出 / 统计",
      "11 行，D-012 不露面")
def soft_delete_isolation(env):
    eq(env.count("devices"), 11)
    eq(env.scalar("SELECT COUNT(*) FROM devices WHERE device_code = 'D-012'"), 0)
    eq(env.scalar("SELECT COUNT(*) FROM devices_all WHERE device_code = 'D-012'"), 1)
    eq(env.scalar("SELECT COUNT(*) FROM inspections"), 19)
