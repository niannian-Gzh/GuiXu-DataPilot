import duckdb
import pandas as pd
from config import load_config, resolve, resolve_db_url, get
from db import get_engine, rebuild_view


COLUMN_MAP = {
    "项目名称": "project_name",
    "负责人": "owner",
    "状态": "status_raw",
    "项目下发时间": "issued_date",
    "项目下证时间": "certified_date",
    "分类": "category",
    "重提项目名": "resubmit_name",
    "（最新）打回时间": "reject_date",
    "（打回）提交时间": "resubmit_date",
    "打回次数": "reject_count",
}


# 表的完整 schema：(列名, SQL 类型, 是否 NOT NULL)
# 这是"必填"的唯一真源——改这里，重建表即生效
TABLE_SCHEMA = [
    # 业务字段
    ("project_name", "VARCHAR", True),
    ("owner", "VARCHAR", True),
    ("status_raw", "VARCHAR", True),
    ("issued_date", "TIMESTAMP", True),
    ("certified_date", "TIMESTAMP", False),
    ("category", "VARCHAR", True),
    ("resubmit_name", "VARCHAR", False),
    ("reject_date", "TIMESTAMP", False),
    ("resubmit_date", "TIMESTAMP", False),
    ("reject_count", "BIGINT", True),
    # 状态派生布尔字段
    ("is_pending", "BOOLEAN", True),
    ("is_submitted", "BOOLEAN", True),
    ("is_rejected", "BOOLEAN", True),
    ("is_settled", "BOOLEAN", True),
    ("is_certified", "BOOLEAN", True),
    # 软删除与审计
    ("is_deleted", "BOOLEAN", True),
    ("deleted_at", "TIMESTAMP", False),
    ("deleted_by", "VARCHAR", False),
    ("delete_trace_id", "VARCHAR", False),
]

# 需要在导入前对 Excel 校验的必填项（派生列由代码保证，不查）
REQUIRED_INPUT_COLUMNS = [
    ("project_name", "项目名称"),
    ("owner", "负责人"),
    ("status_raw", "状态"),
    ("category", "分类"),
    ("issued_date", "项目下发时间"),
]


def _is_pg() -> bool:
    url = get("data.db_url") or ""
    return url.startswith("postgresql://") or url.startswith("postgresql+psycopg2://")


def _read_and_clean_excel(excel_path: str) -> pd.DataFrame:
    """读 Excel + 清洗 + 派生列。两个后端共用这一份。"""
    df = pd.read_excel(excel_path)
    df.columns = df.columns.str.strip()
    df = df[list(COLUMN_MAP.keys())].rename(columns=COLUMN_MAP)

    df["project_name"] = (
        df["project_name"]
        .astype(str)
        .str.replace("<br>", "", regex=False)
        .str.strip()
    )

    df["is_pending"] = df["status_raw"].str.contains("待提交", na=False)
    df["is_submitted"] = df["status_raw"].str.contains("已提交", na=False)
    df["is_rejected"] = df["status_raw"].str.contains("已打回", na=False)
    df["is_settled"] = df["status_raw"].str.contains("已结算", na=False)
    df["is_certified"] = df["status_raw"].str.contains("已下证", na=False)

    df["reject_count"] = df["reject_count"].fillna(0).astype(int)

    df["is_deleted"] = False
    df["deleted_at"] = pd.Series([pd.NaT] * len(df), dtype="datetime64[ns]")
    df["deleted_by"] = pd.Series([None] * len(df), dtype="object")
    df["delete_trace_id"] = pd.Series([None] * len(df), dtype="object")

    return df


def _validate_required(df: pd.DataFrame):
    """检查必填字段是否为空。有则抛出，附行号。

    Excel 行号 = pandas index + 2（第 1 行是表头）。
    """
    problems = []
    for col, label in REQUIRED_INPUT_COLUMNS:
        if col not in df.columns:
            problems.append(f"缺少列「{label}」")
            continue
        series = df[col]
        mask = series.isna()
        if series.dtype == object:
            # 对象列额外检查空字符串（Excel 里可能填了空格）
            mask = mask | (series.astype(str).str.strip() == "")
        if mask.any():
            rows = df.index[mask].tolist()
            shown = "、".join(f"第 {i + 2} 行" for i in rows[:5])
            suffix = f" 等 {len(rows)} 处" if len(rows) > 5 else ""
            problems.append(f"「{label}」为空：{shown}{suffix}")

    if problems:
        raise ValueError(
            "以下必填字段为空，无法导入：\n  - "
            + "\n  - ".join(problems)
            + "\n\n请修改 Excel 后重试。"
        )


def _create_table_ddl(table: str) -> str:
    """按 TABLE_SCHEMA 生成 CREATE TABLE 语句。"""
    cols = []
    for name, type_, not_null in TABLE_SCHEMA:
        cols.append(f"  {name} {type_}{' NOT NULL' if not_null else ''}")
    return f"CREATE TABLE {table} (\n" + ",\n".join(cols) + "\n)"


def _column_names() -> str:
    return ", ".join(c[0] for c in TABLE_SCHEMA)


def _drop_old_objects_duckdb(con, view_name: str, real_table: str):
    """DuckDB：try/except 就够——它没有"事务中毒"这回事。"""
    for stmt in [
        f"DROP VIEW IF EXISTS {view_name}",
        f"DROP TABLE IF EXISTS {view_name}",
        f"DROP VIEW IF EXISTS {real_table}",
        f"DROP TABLE IF EXISTS {real_table}",
    ]:
        try:
            con.execute(stmt)
        except Exception:
            pass


def _drop_old_objects_pg(conn, view_name: str, real_table: str):
    """PG：每次尝试用 SAVEPOINT 隔离。

    PG 事务是"一旦语句失败就中毒"的——后续所有语句都被拒绝。
    这里"每个名字都试 DROP VIEW / DROP TABLE 各一遍"，
    必然有语句失败——必须用 SAVEPOINT 圈住，否则事务就废了。
    """
    from sqlalchemy import text

    for stmt in [
        f"DROP VIEW IF EXISTS {view_name}",
        f"DROP TABLE IF EXISTS {view_name}",
        f"DROP VIEW IF EXISTS {real_table}",
        f"DROP TABLE IF EXISTS {real_table}",
    ]:
        conn.execute(text("SAVEPOINT sp"))
        try:
            conn.execute(text(stmt))
            conn.execute(text("RELEASE SAVEPOINT sp"))
        except Exception:
            conn.execute(text("ROLLBACK TO SAVEPOINT sp"))


def _ingest_to_duckdb(df: pd.DataFrame, view_name: str, real_table: str):
    con = duckdb.connect(resolve_db_url())
    try:
        _drop_old_objects_duckdb(con, view_name, real_table)

        # 显式建表（带 NOT NULL），而非 CREATE TABLE AS SELECT
        con.execute(_create_table_ddl(real_table))

        con.register("df", df)
        con.execute(f"""
            INSERT INTO {real_table} ({_column_names()})
            SELECT
                project_name, owner, status_raw, issued_date, certified_date,
                category, resubmit_name, reject_date, resubmit_date, reject_count,
                is_pending, is_submitted, is_rejected, is_settled, is_certified,
                is_deleted,
                CAST(deleted_at AS TIMESTAMP),
                CAST(deleted_by AS VARCHAR),
                CAST(delete_trace_id AS VARCHAR)
            FROM df
        """)

        con.execute(f"""
            CREATE VIEW {view_name} AS
            SELECT * FROM {real_table} WHERE is_deleted = false
        """)
    finally:
        con.close()


def _ingest_to_pg(df: pd.DataFrame, view_name: str, real_table: str):
    from sqlalchemy import text

    engine = get_engine()

    with engine.begin() as conn:
        _drop_old_objects_pg(conn, view_name, real_table)
        conn.execute(text(_create_table_ddl(real_table)))

    # 表已建好，往里面追加。列名按 TABLE_SCHEMA 对齐
    df_for_pg = df[[c[0] for c in TABLE_SCHEMA]].copy()
    df_for_pg.to_sql(real_table, engine, if_exists="append", index=False)

    # 建视图——走 db.rebuild_view，不再自己写 CREATE VIEW
    rebuild_view(view_name, real_table)


def ingest():
    cfg = load_config()["data"]
    real_table = f"{cfg['table_name']}_all"

    df = _read_and_clean_excel(resolve(cfg["excel_path"]))

    # 导入前校验必填字段——不通过直接抛，不进数据库
    _validate_required(df)

    if _is_pg():
        _ingest_to_pg(df, cfg["table_name"], real_table)
    else:
        _ingest_to_duckdb(df, cfg["table_name"], real_table)

    print(f"✅ 导入 {len(df)} 行 → {resolve_db_url()}")
    print(f"   真实表：{real_table}")
    print(f"   视图：{cfg['table_name']}（已自动过滤 is_deleted）")
    # 导入完成后同步数据字典——新表/新字段进字典
    try:
        import schema_store
        schema_store.refresh_from_db()
    except Exception:
        pass


if __name__ == "__main__":
    ingest()