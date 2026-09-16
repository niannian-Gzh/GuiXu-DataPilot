import json
import uuid
from datetime import datetime
from pathlib import Path
from config import PROJECT_ROOT


ARCHIVE_DIR = PROJECT_ROOT / "logs" / "sessions"


class Session:
    def __init__(self, session_id: str = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.messages = []
        self.pending_action = None
        self.summary = None
        self.prompt_tokens = 0

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self.messages.append({"role": "assistant", "content": text})

    def get_history(self) -> list:
        """返回带摘要的完整历史（摘要为 system 角色）。"""
        result = []
        if self.summary:
            result.append({
                "role": "system",
                "content": f"【历史摘要】\n{self.summary}",
            })
        result.extend(self.messages)
        return result

    def clear(self):
        self.messages.clear()
        self.summary = None
        self.prompt_tokens = 0

    def set_pending(self, action: dict):
        self.pending_action = action

    def get_pending(self) -> dict:
        return self.pending_action

    def clear_pending(self):
        self.pending_action = None

    def set_prompt_tokens(self, n: int):
        self.prompt_tokens = n

    def should_compact(self, threshold: int) -> bool:
        """是否触发压缩。要求至少 20 条消息，避免早期误触发。"""
        return self.prompt_tokens >= threshold and len(self.messages) >= 20

    def archive(self, reason: str = "auto") -> Path:
        """归档完整对话到文件。"""
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.session_id}_{timestamp}.jsonl"
        file_path = ARCHIVE_DIR / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "archive_start",
                "session_id": self.session_id,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "reason": reason,
                "message_count": len(self.messages),
                "existing_summary": self.summary,
            }, ensure_ascii=False) + "\n")

            for m in self.messages:
                f.write(json.dumps({
                    "type": "message",
                    "role": m["role"],
                    "content": m["content"],
                }, ensure_ascii=False) + "\n")

            f.write(json.dumps({
                "type": "archive_end",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False) + "\n")

        index_path = ARCHIVE_DIR / "index.jsonl"
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "session_id": self.session_id,
                "archived_at": datetime.now().isoformat(timespec="seconds"),
                "reason": reason,
                "message_count": len(self.messages),
                "file": filename,
            }, ensure_ascii=False) + "\n")

        return file_path

    def compact(self, llm, keep_recent: int = 6):
        """把旧消息摘要成一段，保留最近 N 轮。"""
        keep_count = keep_recent * 2
        if len(self.messages) <= keep_count:
            return

        old_messages = self.messages[:-keep_count]
        recent_messages = self.messages[-keep_count:]

        parts = []
        if self.summary:
            parts.append(f"【之前摘要】\n{self.summary}")

        for m in old_messages:
            role = "用户" if m["role"] == "user" else "助手"
            parts.append(f"{role}：{m['content']}")

        text = "\n\n".join(parts)

        prompt = f"""请把以下对话历史压缩成一段简洁的摘要。

要求：
1. 保留关键信息：已确认的事实、正在进行的操作、项目名/人名等关键实体
2. 保留用户的偏好和决策
3. 不要编造
4. 不超过 500 字
5. 用第三人称叙述

对话历史：

{text}

摘要："""

        new_summary = llm.chat("你是一个对话摘要助手", prompt).strip()

        self.summary = new_summary
        self.messages = recent_messages
        self.prompt_tokens = 0

    def __len__(self):
        return len(self.messages)