import duckdb
import pandas as pd
from config import load_config, resolve, resolve_db_url, get
from db import get_engine


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


def _is_pg() -> bool:
    """当前数据源是不是 PG。"""
    url = get("data.db_url") or ""
    return url.startswith("postgresql://") or url.startswith("postgresql+psycopg2://")


def _read_and_clean_excel(excel_path: str) -> pd.DataFrame:
    """读 Excel + 清洗 + 派生列。两个后端共用这一份。"""
    # 1. 读 Excel（唯一读 Excel 的地方）
    df = pd.read_excel(excel_path)

    # 2. 列名去空格
    df.columns = df.columns.str.strip()

    # 3. 选列 + 重命名
    df = df[list(COLUMN_MAP.keys())].rename(columns=COLUMN_MAP)

    # 4. 清理项目名：去掉 <br> 和前后空格
    df["project_name"] = (
        df["project_name"]
        .astype(str)
        .str.replace("<br>", "", regex=False)
        .str.strip()
    )

    # 5. 拆分状态为五个布尔字段（保留原文）
    df["is_pending"] = df["status_raw"].str.contains("待提交", na=False)
    df["is_submitted"] = df["status_raw"].str.contains("已提交", na=False)
    df["is_rejected"] = df["status_raw"].str.contains("已打回", na=False)
    df["is_settled"] = df["status_raw"].str.contains("已结算", na=False)
    df["is_certified"] = df["status_raw"].str.contains("已下证", na=False)

    # 6. 打回次数空值填 0
    df["reject_count"] = df["reject_count"].fillna(0).astype(int)

    # 7. 新增软删除与审计列（显式指定类型，避免 pandas 推断错误）
    df["is_deleted"] = False
    df["deleted_at"] = pd.Series([pd.NaT] * len(df), dtype="datetime64[ns]")
    df["deleted_by"] = pd.Series([None] * len(df), dtype="object")
    df["delete_trace_id"] = pd.Series([None] * len(df), dtype="object")

    return df


def _ingest_to_duckdb(df: pd.DataFrame, view_name: str, real_table: str):
    """DuckDB 后端：register + CTAS，显式 CAST 关键列类型。"""
    con = duckdb.connect(resolve_db_url())

    # 清理旧对象：可能是表，也可能是视图（迁移期间两种都可能存在）
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

    con.register("df", df)
    con.execute(f"""
        CREATE TABLE {real_table} AS
        SELECT
            project_name, owner, status_raw, issued_date, certified_date,
            category, resubmit_name, reject_date, resubmit_date, reject_count,
            is_pending, is_submitted, is_rejected, is_settled, is_certified,
            is_deleted,
            CAST(deleted_at AS TIMESTAMP) AS deleted_at,
            CAST(deleted_by AS VARCHAR) AS deleted_by,
            CAST(delete_trace_id AS VARCHAR) AS delete_trace_id
        FROM df
    """)
    con.execute(f"""
        CREATE VIEW {view_name} AS
        SELECT * FROM {real_table} WHERE is_deleted = false
    """)
    con.close()


def _ingest_to_pg(df: pd.DataFrame, view_name: str, real_table: str):
    """PG 后端：to_sql + 显式 dtype，再建视图。

    两个关键点：
    1. 先 DROP 视图再 DROP 表——PG 里表被视图依赖时，DROP TABLE 会报错
    2. dtype 显式指定那三个"全是 None"的列——否则 to_sql 会猜错类型
    """
    from sqlalchemy import text, types as sqla_types

    engine = get_engine()

    # 清旧对象
    with engine.begin() as conn:
        for stmt in [
            f"DROP VIEW IF EXISTS {view_name}",
            f"DROP TABLE IF EXISTS {view_name}",
            f"DROP VIEW IF EXISTS {real_table}",
            f"DROP TABLE IF EXISTS {real_table}",
        ]:
            conn.execute(text(stmt))

    # 显式类型——这三个列整列都是空值，不指定会推断成错的类型
    dtype = {
        "deleted_at": sqla_types.TIMESTAMP,
        "deleted_by": sqla_types.VARCHAR,
        "delete_trace_id": sqla_types.VARCHAR,
    }
    df.to_sql(real_table, engine, if_exists="replace", index=False, dtype=dtype)

    # 建视图
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE VIEW {view_name} AS "
            f"SELECT * FROM {real_table} WHERE is_deleted = false"
        ))


def ingest():
    cfg = load_config()["data"]
    real_table = f"{cfg['table_name']}_all"

    df = _read_and_clean_excel(resolve(cfg["excel_path"]))

    if _is_pg():
        _ingest_to_pg(df, cfg["table_name"], real_table)
    else:
        _ingest_to_duckdb(df, cfg["table_name"], real_table)

    print(f"✅ 导入 {len(df)} 行 → {resolve_db_url()}")
    print(f"   真实表：{real_table}")
    print(f"   视图：{cfg['table_name']}（已自动过滤 is_deleted）")


if __name__ == "__main__":
    ingest()