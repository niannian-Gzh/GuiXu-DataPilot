"""D4 注入与越权：能想到的入口都从外面打一遍。

判据统一是**负向的**：不是"它返回了错误"，而是
「拒绝了 + 数据没变 + 该保护的还在」。返回 500 不算合格防御。
"""

from __future__ import annotations

import gate as gate_mod
from guard import SecurityError
from harness import case, check, eq, raises, SkipTest


# ============================================================ 闸门

def _deny(env, sql: str, purpose: str):
    con = env.connect()
    try:
        raises(lambda: gate_mod.check(sql, purpose, con), gate_mod.GateError, sql)
    finally:
        con.close()


def _allow(env, sql: str, purpose: str):
    con = env.connect()
    try:
        try:
            gate_mod.check(sql, purpose, con)
        except gate_mod.GateError as e:
            raise AssertionError(f"合法语句被闸门拒绝：{sql}（{e}）")
    finally:
        con.close()


@case("D4", "读底表必须被拒", "SELECT * FROM devices_all", "闸门拒绝，绕过软删视图不成立")
def gate_bottom_table_read(env):
    _deny(env, "SELECT * FROM devices_all", "read")


@case("D4", "写底表必须被拒", "INSERT INTO devices_all ...", "闸门拒绝")
def gate_bottom_table_insert(env):
    _deny(env, "INSERT INTO devices_all (id, device_code) VALUES (99, 'X')", "write")


@case("D4", "系统表不可读", "SELECT * FROM _gx_audit", "闸门拒绝，审计/快照不露面")
def gate_system_table_read(env):
    _deny(env, "SELECT * FROM _gx_audit", "read")


@case("D4", "UNION 夹带底表", "SELECT id FROM devices UNION SELECT id FROM devices_all",
      "整条语句的所有表名都过白名单")
def gate_union_bottom_table(env):
    _deny(env, "SELECT id FROM devices UNION SELECT id FROM devices_all", "read")


@case("D4", "CTE 遮蔽底表", "WITH devices AS (SELECT * FROM devices_all) SELECT * FROM devices",
      "CTE 不改变表名白名单")
def gate_cte_bottom_table(env):
    _deny(env, "WITH devices AS (SELECT * FROM devices_all) SELECT * FROM devices", "read")


@case("D4", "引号包底表", 'SELECT * FROM "devices_all"', "引号不能让底表过白名单")
def gate_quoted_bottom_table(env):
    _deny(env, 'SELECT * FROM "devices_all"', "read")


@case("D4", "读系统列", "SELECT is_deleted FROM devices", "系统列不露给模型")
def gate_system_column_read(env):
    _deny(env, "SELECT is_deleted FROM devices", "read")


@case("D4", "改系统列", "UPDATE devices SET is_deleted = 1", "软删只能走 DELETE 触发器")
def gate_system_column_write(env):
    _deny(env, "UPDATE devices SET is_deleted = 1", "write")


@case("D4", "一次带两条语句", "SELECT 1; DROP TABLE devices", "只允许单条语句")
def gate_multi_statement(env):
    _deny(env, "SELECT 1; DROP TABLE devices", "read")


@case("D4", "PRAGMA 探测", "PRAGMA table_info(devices)", "非 SELECT/写/DDL 一律拒绝")
def gate_pragma(env):
    _deny(env, "PRAGMA table_info(devices)", "read")


@case("D4", "ATTACH 挂外部库", "ATTACH DATABASE 'x.db' AS x", "拒绝挂载")
def gate_attach(env):
    _deny(env, "ATTACH DATABASE 'x.db' AS x", "read")


@case("D4", "写操作伪装成读", "DELETE FROM devices 标成 read", "意图与语句类型必须对得上")
def gate_write_disguised_as_read(env):
    _deny(env, "DELETE FROM devices", "read")


@case("D4", "读操作伪装成写", "SELECT ... 标成 write", "意图与语句类型必须对得上")
def gate_read_disguised_as_write(env):
    _deny(env, "SELECT * FROM devices", "write")


@case("D4", "注释开头夹带写操作", "/* SELECT */ DELETE FROM devices", "看真正的第一个词，不看注释")
def gate_comment_disguise(env):
    _deny(env, "/* SELECT */ DELETE FROM devices", "read")


@case("D4", "正对照：普通查询放行", "SELECT * FROM devices", "不能把正常查询也拦掉")
def gate_legit_select(env):
    _allow(env, "SELECT * FROM devices WHERE status = '在用'", "read")


@case("D4", "正对照：业务视图删除放行", "DELETE FROM devices WHERE id = 1",
      "软删走视图触发器，闸门放行")
def gate_legit_delete(env):
    _allow(env, "DELETE FROM devices WHERE id = 1", "write")


@case("D4", "正对照：字符串里的 delete 不该被拦", "SELECT 'delete' AS x",
      "关键字检查不能误伤字符串字面量")
def gate_string_literal(env):
    _allow(env, "SELECT 'delete' AS x", "read")


@case("D4", "正对照：表名大小写不敏感", "SELECT * FROM DEVICES",
      "SQLite 表名不区分大小写，闸门也不该区分")
def gate_case_insensitive_table(env):
    _allow(env, "SELECT * FROM DEVICES", "read")


# ============================================================ 模型 SQL 入口

def _sql_denied(env, sql: str):
    import execute
    before = env.count("devices")
    e = raises(lambda: execute.execute_sql(sql), (SecurityError, gate_mod.GateError), sql)
    eq(env.count("devices"), before, "被拒的语句不许改数据")
    return e


@case("D4", "模型 SQL 入口不放过多语句", "SELECT 1; DROP TABLE devices",
      "GateError，且 devices 表还在")
def sql_entry_multi_statement(env):
    _sql_denied(env, "SELECT 1; DROP TABLE devices")
    check(env.table_exists("devices_all"), "devices 底表被删了")


@case("D4", "模型 SQL 入口不打底表", "SELECT * FROM devices_all", "GateError")
def sql_entry_bottom_table(env):
    _sql_denied(env, "SELECT * FROM devices_all")


@case("D4", "模型 SQL 入口不读系统表", "SELECT * FROM _gx_audit", "GateError")
def sql_entry_system_table(env):
    _sql_denied(env, "SELECT * FROM _gx_audit")


@case("D4", "模型 SQL 入口只收 SELECT", "DELETE FROM devices", "SecurityError，数据不变")
def sql_entry_non_select(env):
    _sql_denied(env, "DELETE FROM devices")


@case("D4", "正对照：合法查询能跑", "SELECT count(*) FROM devices", "返回 11 行（12 删 1）")
def sql_entry_legit(env):
    import execute
    df = execute.execute_sql("SELECT count(*) AS n FROM devices")
    eq(int(df.iloc[0, 0]), env.truth().count(), "活着的设备数")


# ============================================================ 会话 id 穿越

@case("D4", "会话 id 不能删除目录外文件", "DELETE /sessions/..\\canary",
      "拒绝或 404，canary 必须还在")
def api_session_traversal_delete(env):
    canary = env.box.root / "canary.json"
    canary.write_text('{"canary": true}', encoding="utf-8")

    client = env.client()
    resp = client.delete("/sessions/..%5Ccanary")

    check(canary.exists(), f"session_id 穿越删掉了会话目录外的文件（HTTP {resp.status_code}）")
    check(resp.status_code in (400, 404, 422), f"越界会话 id 应被拒绝，实际 {resp.status_code}")


@case("D4", "会话 id 不能写到目录外", 'Session("..\\evil").save()',
      "文件只能落在 logs/sessions 里")
def api_session_traversal_write(env):
    from session import Session
    try:
        s = Session("..\\evil")
        s.add_user("这条消息不该漏到会话目录外面")
        path = s.save()
    except ValueError:
        # 入口就拒绝了，这正是期望
        check(not (env.box.root / "evil.json").exists(),
              "拒绝之前已经写出了文件")
        return

    expected_dir = env.box.root / "sessions"
    check(path.resolve().parent == expected_dir.resolve(),
          f"会话写到了 {path}，不在 {expected_dir}")
    check(not (env.box.root / "evil.json").exists(), "会话文件逃出了 sessions 目录")


@case("D4", "不存在的会话返回 404", "GET /sessions/does-not-exist", "404，不崩")
def api_session_missing(env):
    resp = env.client().get("/sessions/does-not-exist")
    eq(resp.status_code, 404)


# ============================================================ 文件接口

@case("D4", "上传文件名不能穿越", 'filename="..\\..\\evil.xlsx"',
      "不逃出 uploads；非法名给 4xx，不给 500")
def api_upload_filename_traversal(env):
    client = env.client()
    resp = client.post("/upload", files={
        "file": ("..\\..\\evil.xlsx", b"PK\x03\x04", "application/octet-stream"),
    })
    check(resp.status_code < 500,
          f"恶意文件名把接口打成了 {resp.status_code}")
    escaped = env.box.root / "evil.xlsx"
    check(not escaped.exists(), "上传文件逃出了 uploads 目录")


@case("D4", "正对照：正常上传落进 uploads", "巡检数据.xlsx", "200 且文件在 uploads")
def api_upload_normal(env):
    client = env.client()
    resp = client.post("/upload", files={
        "file": ("巡检数据.xlsx", b"PK\x03\x04", "application/octet-stream"),
    })
    eq(resp.status_code, 200)
    path = resp.json()["path"]
    check(path.startswith("uploads/"), f"上传路径不对：{path}")


@case("D4", "下载接口不能读任意文件", "GET /download?path=../canary.txt", "403")
def api_download_traversal(env):
    (env.box.root / "canary.txt").write_text("secret", encoding="utf-8")
    resp = env.client().get("/download", params={"path": "../canary.txt"})
    eq(resp.status_code, 403)


@case("D4", "下载接口不能收绝对路径", "GET /download?path=<abs canary>", "403")
def api_download_absolute(env):
    canary = env.box.root / "canary.txt"
    canary.write_text("secret", encoding="utf-8")
    resp = env.client().get("/download", params={"path": str(canary)})
    eq(resp.status_code, 403)


@case("D4", "正对照：导出目录里的文件能下载", "GET /download?path=exports/ok.txt", "200")
def api_download_normal(env):
    f = env.box.root / "exports" / "ok.txt"
    f.write_text("ok", encoding="utf-8")
    resp = env.client().get("/download", params={"path": "exports/ok.txt"})
    eq(resp.status_code, 200)


@case("D4", "内联接口不能读任意文件", "GET /raw?path=../canary.txt", "403")
def api_raw_traversal(env):
    (env.box.root / "canary.txt").write_text("secret", encoding="utf-8")
    resp = env.client().get("/raw", params={"path": "../canary.txt"})
    eq(resp.status_code, 403)


@case("D4", "预览接口不能读任意文件", "GET /preview?path=../canary.txt", "403")
def api_preview_traversal(env):
    (env.box.root / "canary.txt").write_text("secret", encoding="utf-8")
    resp = env.client().get("/preview", params={"path": "../canary.txt"})
    eq(resp.status_code, 403)


@case("D4", "删除接口不能删任意文件", "DELETE /files/..\\canary.txt", "403，文件还在")
def api_delete_file_traversal(env):
    canary = env.box.root / "canary.txt"
    canary.write_text("secret", encoding="utf-8")
    resp = env.client().delete("/files/..%5Ccanary.txt")
    eq(resp.status_code, 403)
    check(canary.exists(), "canary 被越界删除了")


@case("D4", "清空文件只动 exports/reports", "DELETE /files",
      "uploads 和项目根的文件不能被清")
def api_clear_files_scope(env):
    (env.box.root / "canary.txt").write_text("keep", encoding="utf-8")
    (env.box.root / "uploads" / "up.txt").write_text("keep", encoding="utf-8")
    (env.box.root / "exports" / "out.txt").write_text("drop", encoding="utf-8")

    resp = env.client().delete("/files")
    eq(resp.status_code, 200)
    check((env.box.root / "canary.txt").exists(), "清空文件删到了项目根")
    check((env.box.root / "uploads" / "up.txt").exists(), "清空文件删到了上传目录")
    check(not (env.box.root / "exports" / "out.txt").exists(), "导出文件没被清掉")


# ============================================================ 设置与字典参数

@case("D4", "设置拒绝未知键", 'PUT /settings {"nope.nope": 1}', "400")
def api_settings_unknown_key(env):
    resp = env.client().put("/settings", json={"values": {"nope.nope": 1}})
    eq(resp.status_code, 400)


@case("D4", "设置拒绝错误类型", '{"display.preview_rows": "abc"}', "400，不写进配置")
def api_settings_bad_type(env):
    resp = env.client().put("/settings", json={"values": {"display.preview_rows": "abc"}})
    eq(resp.status_code, 400)


@case("D4", "设置拒绝越界值", '{"display.preview_rows": -1}', "400")
def api_settings_out_of_range(env):
    resp = env.client().put("/settings", json={"values": {"display.preview_rows": -1}})
    eq(resp.status_code, 400)


@case("D4", "设置拒绝枚举外值", "select 参数塞一个不存在的选项", "400")
def api_settings_bad_enum(env):
    from settings_spec import PARAMS
    p = next(p for p in PARAMS if p["type"] == "select")
    resp = env.client().put("/settings", json={"values": {p["key"]: "不存在的选项"}})
    eq(resp.status_code, 400)


@case("D4", "关系不能指向不存在的表", "POST /schema/relations 假表", "400")
def api_relation_fake_table(env):
    resp = env.client().post("/schema/relations", json={
        "from_table": "devices", "from_column": "id",
        "to_table": "ghost_table", "to_column": "id",
        "cardinality": "1:N",
    })
    eq(resp.status_code, 400)


@case("D4", "关系基数只能是约定值", "cardinality=随便写", "400")
def api_relation_bad_cardinality(env):
    resp = env.client().post("/schema/relations", json={
        "from_table": "devices", "from_column": "id",
        "to_table": "inspections", "to_column": "device_id",
        "cardinality": "一对多",
    })
    eq(resp.status_code, 400)


@case("D4", "恢复接口拒绝畸形 id", "POST /recover/restore ids=[{...}]", "4xx，不 500")
def api_recover_bad_ids(env):
    resp = env.client().post("/recover/restore", json={
        "table": "devices", "ids": [{"id": 1}],
    })
    check(resp.status_code < 500, f"畸形 id 把接口打成了 {resp.status_code}")


@case("D4", "不存在的快照返回 404", "GET /recover/snapshot/9999", "404")
def api_recover_missing_snapshot(env):
    resp = env.client().get("/recover/snapshot/9999")
    eq(resp.status_code, 404)


@case("D4", "回滚不存在的快照不执行", "POST /recover/rollback id=9999", "ok=false，库不变")
def api_recover_missing_rollback(env):
    before = env.count("devices")
    resp = env.client().post("/recover/rollback", json={"id": 9999})
    eq(resp.status_code, 200)
    eq(resp.json().get("ok"), False)
    eq(env.count("devices"), before, "设备数变了")


# ============================================================ 前端 XSS

@case("D4", "模型输出里的 HTML 不执行", '回答里带 <img onerror=...>',
      "对话流渲染后不设置 window.__gx_xss")
def xss_markdown_render(env):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SkipTest("没有 playwright")

    base = env.serve()
    payload = '<img src=x onerror="window.__gx_xss=1">'

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(base + "/", wait_until="domcontentloaded")
            page.add_script_tag(url=base + "/vendor/marked.min.js")
            page.evaluate(
                """async (payload) => {
                    const utils = await import('/js/utils.js');
                    document.body.insertAdjacentHTML('beforeend', utils.md(payload));
                }""",
                payload,
            )
            page.wait_for_timeout(500)
            hit = page.evaluate("window.__gx_xss")
            browser.close()
    except Exception as e:
        raise SkipTest(f"浏览器起不来：{type(e).__name__}: {e}")

    check(hit is None, "Markdown 渲染执行了回答里的 onerror 脚本（XSS）")
