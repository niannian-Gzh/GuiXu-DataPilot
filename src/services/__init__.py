from dataclasses import dataclass
from typing import Any

from config import setting


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


def bulk_threshold() -> int:
    """影响多少条以上时，确认方式升级为手打「删除 N 条」。"""
    return setting("display.bulk_threshold")