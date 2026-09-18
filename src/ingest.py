import duckdb
import pandas as pd
from config import load_config, resolve, resolve_db_url

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


def ingest():
    cfg = load_config()["data"]

    # 1. 读 Excel（唯一读 Excel 的地方）
    df = pd.read_excel(resolve(cfg["excel_path"]))

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

    # 8. 写入 DuckDB：真实表 + 过滤视图
    real_table = f"{cfg['table_name']}_all"
    con = duckdb.connect(resolve_db_url())

    # 清理旧对象：可能是表，也可能是视图（迁移期间两种都可能存在）
    for stmt in [
        f"DROP VIEW IF EXISTS {cfg['table_name']}",
        f"DROP TABLE IF EXISTS {cfg['table_name']}",
        f"DROP VIEW IF EXISTS {real_table}",
        f"DROP TABLE IF EXISTS {real_table}",
    ]:
        try:
            con.execute(stmt)
        except Exception:
            pass

    # 建真实表
    con.register("df", df)
    con.execute(f"""
        CREATE TABLE {real_table} AS
        SELECT
            project_name,
            owner,
            status_raw,
            issued_date,
            certified_date,
            category,
            resubmit_name,
            reject_date,
            resubmit_date,
            reject_count,
            is_pending,
            is_submitted,
            is_rejected,
            is_settled,
            is_certified,
            is_deleted,
            CAST(deleted_at AS TIMESTAMP) AS deleted_at,
            CAST(deleted_by AS VARCHAR) AS deleted_by,
            CAST(delete_trace_id AS VARCHAR) AS delete_trace_id
        FROM df
    """)

    # 建视图：自动过滤已删除
    con.execute(f"""
        CREATE VIEW {cfg['table_name']} AS
        SELECT * FROM {real_table} WHERE is_deleted = false
    """)
    con.close()

    print(f"✅ 导入 {len(df)} 行 → {cfg['db_path']}")
    print(f"   真实表：{real_table}")
    print(f"   视图：{cfg['table_name']}（已自动过滤 is_deleted）")


if __name__ == "__main__":
    ingest()