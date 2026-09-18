import sys
sys.path.insert(0, "src")

from config import load_config, resolve, resolve_db_url
from llm import LLM
from trace import Trace
from services import ServiceContext
from services import import_service

cfg = load_config()["data"]
ctx = ServiceContext(
    llm=None, db_path=resolve_db_url(),
    table_name=cfg["table_name"], real_table=f"{cfg['table_name']}_all",
    schema=None, trace=None,
)

result = import_service.scan("data/软著项目申报管理系统.xlsx", ctx)
print(f"新记录：{len(result['new_records'])}")
print(f"软删除：{len(result['deleted_in_db'])}")
print(f"冲突：{len(result['conflicts'])}")
print(f"无变化：{len(result['unchanged'])}")
print(f"Excel缺失：{len(result['missing_from_excel'])}")
