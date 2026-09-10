import duckdb
import pandas as pd
import yaml
from config import load_config, resolve

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

    # 7. 写入 DuckDB
    con = duckdb.connect(resolve(cfg["db_path"]))
    con.execute(f"DROP TABLE IF EXISTS {cfg['table_name']}")
    con.register("df", df)
    con.execute(f"CREATE TABLE {cfg['table_name']} AS SELECT * FROM df")
    con.close()

    print(f"✅ 导入 {len(df)} 行 → {cfg['db_path']}")
    print(f"   列：{list(df.columns)}")


if __name__ == "__main__":
    ingest()