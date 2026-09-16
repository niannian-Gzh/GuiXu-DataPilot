from dataclasses import dataclass
from typing import Any


class UserInputRequired(Exception):
    """需要用户输入才能继续。"""
    def __init__(self, question: str, pending_action: dict):
        super().__init__(question)
        self.question = question
        self.pending_action = pending_action


@dataclass
class ServiceContext:
    """服务层共享的依赖。"""
    llm: Any
    db_path: str
    table_name: str
    real_table: str
    schema: str
    trace: Any


BULK_THRESHOLD = 20