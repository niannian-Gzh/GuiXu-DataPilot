import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from config import PROJECT_ROOT


ARCHIVE_DIR = PROJECT_ROOT / "logs" / "sessions"

# 打招呼类开头，取标题时跳过
GREETING_PREFIXES = (
    "你好", "您好", "早上好", "中午好", "下午好", "晚上好",
    "在吗", "在不在",
)

# 英文单独走词边界：纯前缀匹配会把 history / high / his 一并吃掉，
# 而表名列名这类词在数据场景里并不罕见，误判又是静默的——
# 标题错了，没人知道是为什么
_GREETING_EN = re.compile(r"^(?:hi|hello|hey)\b", re.IGNORECASE)


class Session:
    def __init__(self, session_id: str = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.messages = []
        self.pending_action = None
        self.summary = None
        self.prompt_tokens = 0

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str, tools: list = None, reasonings: list = None):
        """tools 是这一轮的工具调用记录，reasonings 是这一轮的思考链，
        都只供界面回看，不发给模型。"""
        msg = {"role": "assistant", "content": text}
        if tools:
            msg["dp_tools"] = tools
        if reasonings:
            msg["dp_reasonings"] = reasonings
        self.messages.append(msg)

    def get_history(self) -> list:
        """返回带摘要的完整历史（摘要为 system 角色）。

        dp_tools 不能原样塞回去（API 不认这个字段），但也不能直接丢掉——
        丢掉的话，模型回看历史时只看到自己说过「已生成 xxx.pdf」，
        却找不到任何工具调用过的凭据。一旦用户追问，它会据此判定
        自己在编造，把真做过的事说成假的。所以折中：转成一行文字补回去。
        """
        result = []
        if self.summary:
            result.append({
                "role": "system",
                "content": f"【历史摘要】\n{self.summary}",
            })

        for m in self.messages:
            tools = m.get("dp_tools")
            # dp_reasonings 只给界面回看，必须剥掉：这里原样 append 的话，
            # 纯对话轮（没有 dp_tools）的思考链会跟着进 prompt——
            # 动辄上千字，每轮都带上，成本和噪音都不划算
            if "dp_reasonings" in m:
                m = {k: v for k, v in m.items() if k != "dp_reasonings"}
            if not tools:
                result.append(m)
                continue

            lines = []
            for t in tools:
                if t.get("security"):
                    status = "被安全拒绝"
                elif t.get("ok"):
                    status = "成功"
                else:
                    status = "失败"
                args = t.get("args") or {}
                arg_text = "，".join(
                    f"{k}={v}" for k, v in list(args.items())[:3]
                )
                lines.append(f"- {t['name']}({arg_text}) → {status}")

            result.append({
                "role": m["role"],
                "content": "【上一条回复前，实际调用过这些工具】\n"
                           + "\n".join(lines)
                           + "\n\n" + m["content"],
            })
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

    def title(self) -> str:
        """会话标题取第一条有实际意图的用户消息，跳过打招呼类。

        全打招呼时回退到第一条，而不是返回「新会话」——
        那样列表里会堆一片同名的「新会话」，比看到「早上好」还难认。
        """
        fallback = None
        for m in self.messages:
            if m["role"] != "user":
                continue
            text = m["content"].strip()
            if fallback is None:
                fallback = text[:30]
            if text.startswith(GREETING_PREFIXES) or _GREETING_EN.match(text):
                continue
            return text[:30]
        return fallback or "新会话"

    def save(self) -> Path:
        """把会话落盘，供 webui 的会话列表读回。"""
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        path = ARCHIVE_DIR / f"{self.session_id}.json"
        path.write_text(json.dumps({
            "session_id": self.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "title": self.title(),
            "message_count": len(self.messages),
            "summary": self.summary,
            "messages": self.messages,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, session_id: str) -> "Session":
        """从磁盘读回会话。文件不存在时返回一个空会话。"""
        session = cls(session_id)
        path = ARCHIVE_DIR / f"{session_id}.json"
        if not path.exists():
            return session
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return session
        session.messages = data.get("messages", [])
        session.summary = data.get("summary")
        return session

    @staticmethod
    def list_saved() -> list:
        """列出已落盘的会话，按更新时间倒序。"""
        if not ARCHIVE_DIR.exists():
            return []
        items = []
        for path in ARCHIVE_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            items.append({
                "session_id": data.get("session_id", path.stem),
                "title": data.get("title", "新会话"),
                "message_count": data.get("message_count", 0),
                "updated_at": data.get("updated_at", ""),
            })
        return sorted(items, key=lambda x: x["updated_at"], reverse=True)

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