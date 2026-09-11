import sys
sys.path.insert(0, "src")

import duckdb
from config import load_config, resolve
from cleanup import cleanup

cfg = load_config()["data"]
con = duckdb.connect(resolve(cfg["db_path"]))

# 手动把一条数据标记为"8天前删除"
con.execute("""
    UPDATE projects_all 
    SET is_deleted = true, 
        deleted_at = CAST(NOW() AS TIMESTAMP) - INTERVAL '8 days'
    WHERE project_name LIKE '家装%'
""")
con.close()

print("=== 制造了一条 8 天前删除的数据 ===")

# 跑清理
count = cleanup()
print(f"清理了 {count} 条")

# 验证
con = duckdb.connect(resolve(cfg["db_path"]))
n = con.execute("SELECT COUNT(*) FROM projects_all WHERE project_name LIKE '家装%'").fetchone()[0]
print(f"真实表中家装还在吗: {n}（应为 0）")
con.close()