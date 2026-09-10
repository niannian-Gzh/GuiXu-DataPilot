import json
import uuid
from datetime import datetime
from pathlib import Path
from config import PROJECT_ROOT


TRACE_FILE = PROJECT_ROOT / "logs" / "traces.jsonl"


class Trace:
    def __init__(self, question: str):
        self.data = {
            "trace_id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "standalone": None,
            "sql": None,
            "retries": None,
            "row_count": None,
            "answer_len": None,
            "answer_head": None,
            "elapsed_ms": None,
            "error": None,
        }
        self._start = datetime.now()

    def set(self, key, value):
        self.data[key] = value

    def mark_end(self):
        self.data["elapsed_ms"] = int(
            (datetime.now() - self._start).total_seconds() * 1000
        )

    def save(self):
        Path(TRACE_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.data, ensure_ascii=False) + "\n")

    @property
    def id(self):
        return self.data["trace_id"]