import json
from datetime import datetime
from pathlib import Path
from config import PROJECT_ROOT


AUDIT_FILE = PROJECT_ROOT / "logs" / "audit.jsonl"


def log(action: str, detail: dict):
    """写一条审计日志。action 是操作类型，detail 是详情。"""
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        **detail,
    }
    Path(AUDIT_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")