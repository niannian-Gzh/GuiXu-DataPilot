import sys
sys.path.insert(0, "src")

import duckdb
from config import load_config, resolve

cfg = load_config()["data"]
con = duckdb.connect(resolve(cfg["db_path"]))

print("=== 标记家装为已删除 ===")
con.execute("""
    UPDATE projects_all 
    SET is_deleted = true, deleted_at = NOW() 
    WHERE project_name LIKE '家装%'
""")

v1 = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
t1 = con.execute("SELECT COUNT(*) FROM projects_all").fetchone()[0]
v2 = con.execute("SELECT COUNT(*) FROM projects WHERE project_name LIKE '家装%'").fetchone()[0]
t2 = con.execute("SELECT COUNT(*) FROM projects_all WHERE project_name LIKE '家装%'").fetchone()[0]

print(f"视图行数（应少1）: {v1}")
print(f"真实表行数（不变）: {t1}")
print(f"视图中还能看到家装吗: {v2}")
print(f"真实表中家装还在吗: {t2}")

print("\n=== 恢复 ===")
con.execute("""
    UPDATE projects_all 
    SET is_deleted = false, deleted_at = NULL 
    WHERE project_name LIKE '家装%'
""")

v3 = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
print(f"恢复后视图行数: {v3}")

con.close()