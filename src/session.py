import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from config import PROJECT_ROOT


ARCHIVE_DIR = PROJECT_ROOT / "logs" / "sessions"

# 会话 id 会成为文件名。**必须只允许安全字符**：Windows 上反斜杠也是
# 路径分隔符，`..\..\secrets` 会拼到会话目录外面去，`save()` 能覆盖
# 任意 `.json`，`load()` 能读任意会话文件。
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def valid_id(session_id: str | None) -> bool:
    return bool(session_id) and bool(SESSION_ID_RE.fullmatch(session_id))


# 打招呼类开头，取标题时跳过
GREETING_PREFIXES = (
    "你好", "您好", "早上好", "中午好", "下午好", "晚上好",
    "在吗", "在不在",
)

# 英文单独走词边界：纯前缀匹配会把 history / high / his 一并吃掉，
# 而表名列名这类词在数据场景里并不罕见，误判又是静默的——
# 标题错了，没人知道是为什么
_GREETING_EN = re.compile(r"^(?:hi|hello|hey)\b", re.IGNORECASE)


def _now() -> str:
    """本地时间，秒级，不带时区。

    界面要给每一轮标一个时刻（见 workbench 原型的 .turn-at），所以每条
    消息都得带一个。用本地时间而不是 UTC：用户看的是自己的表，
    东八区晚上八点后 UTC 会显示成第二天。
    前端在实时那一轮也按这个格式生成（js/utils.js 的 stamp()），两边必须一致。
    """
    return datetime.now().isoformat(timespec="seconds")


class Session:
    """一个会话的两份记录：**存证**和**记忆**。

    - `messages` 是**存证**：完整的对话流水，只增不减，给人回看
    - `summary` + `summary_upto` 是**记忆**：给模型的压缩版

    这两件事的需求是相反的——存证要全，记忆要小。放在一个列表里，
    压缩就会毁掉存证（旧版确实是这样：`compact()` 把旧消息砍了）。
    分开之后，压缩只推进 `summary_upto`，一条消息都不删。
    """

    def __init__(self, session_id: str = None):
        if session_id is not None and not valid_id(session_id):
            raise ValueError("会话 id 只能包含字母、数字、下划线和短横线")
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.messages = []          # 存证：完整，只增不减
        self.summary = None         # 记忆：旧对话的要点
        self.summary_upto = 0       # 摘要覆盖到 messages 的第几条
        self.pending_action = None
        self.prompt_tokens = 0

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text, "gx_at": _now()})

    def add_assistant(self, text: str, tools: list = None, reasonings: list = None,
                      notice: bool = False):
        """tools 是这一轮的工具调用记录，reasonings 是这一轮的思考链，
        都只供界面回看，不发给模型。

        notice=True 表示这句话不是模型说的，是这一轮被迫停下的提示
        （比如跳过提问）。内容照常进历史，但界面把它画成警告，不是正文。
        """
        msg = {"role": "assistant", "content": text, "gx_at": _now()}
        if tools:
            msg["gx_tools"] = tools
        if reasonings:
            msg["gx_reasonings"] = reasonings
        if notice:
            msg["gx_notice"] = True
        self.messages.append(msg)

    def add_confirm(self, record: dict):
        """把一次中断的结局挂到本轮开头那条用户消息上。

        为什么不挂在最终那条 assistant 上：续跑途中又中断时，assistant
        那条还没写（`_end` 要到这一轮真正结束才调），这时刷新页面，
        已经答过的那几张卡会一起消失。挂在用户消息上就没有这个空窗——
        "这一轮里发生过什么"本来就该跟着这一轮的起点走。
        """
        for m in reversed(self.messages):
            if m.get("role") == "user":
                m.setdefault("gx_confirms", []).append(record)
                return

    def get_history(self) -> list:
        """给模型的那一份：摘要 + **尚未被摘要的消息**。

        这是记忆侧，不是存证。`summary_upto` 之前的消息已经被摘要覆盖，
        不再逐条发给模型——但它们还在 `self.messages` 里，前端照样看得见。

        gx_tools 不能原样塞回去（API 不认这个字段），但也不能直接丢掉——
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

        for m in self.messages[self.summary_upto:]:
            tools = m.get("gx_tools")
            # gx_* 一律只给界面回看，不进 prompt：
            #   gx_reasonings 动辄上千字，每轮都带上，成本和噪音都不划算；
            #   gx_at 上游根本不认识这个字段，原样发出去会被 400 掉
            if any(k.startswith("gx_") for k in m):
                m = {k: v for k, v in m.items() if not k.startswith("gx_")}
            if not tools:
                result.append(m)
                continue

            lines = []
            for t in tools:
                if t.get("cancelled"):
                    status = "已取消"
                elif t.get("security"):
                    status = "被安全拒绝"
                elif t.get("ok"):
                    status = "成功"
                else:
                    status = "失败"

                # 参数**全给**，不再按位置截前 3——那样 table_name 会被切掉，
                # 模型看到的是"参数的前三个"，不是"重要的三个"。
                # 只在整串超长时截尾（大数组之类），截的是尾巴不是位置
                arg_text = json.dumps(t.get("args") or {}, ensure_ascii=False)
                if len(arg_text) > 160:
                    arg_text = arg_text[:160] + "…"

                # 结果要点：这一轮到底查到了几行、改了几条、导出了什么。
                # 没有它，模型只知道"调过且成功"，不知道发生过什么
                gist = t.get("gist") or ""
                tail = f"，{gist}" if gist else ""
                lines.append(f"- {t['name']}({arg_text}) → {status}{tail}")

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
        self.summary_upto = 0
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
            "updated_at": _now(),
            "title": self.title(),
            "message_count": len(self.messages),
            "summary": self.summary,
            # 摘要覆盖到第几条。不存它的话，重启后要么把摘要过的
            # 对话再发一遍，要么把没摘要的当成已摘要吞掉
            "summary_upto": self.summary_upto,
            "messages": self.messages,
            # 挂起的中断也一起落盘：它带着断点（这一轮已经发生过的
            # 消息片段），重启后仍能从断在哪继续
            "pending": self.pending_action,
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
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
        # 旧文件没有这个字段：旧版压缩是**删消息**，summary 对应的
        # 那部分本来就不在 messages 里，所以从 0 开始正是对的
        session.summary_upto = int(data.get("summary_upto") or 0)
        # 断点跟着会话一起回来。没有它，重启后 pending 虽然还在，
        # 但模型已经不知道自己断在哪个工具调用上了
        session.pending_action = data.get("pending")
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
        """是否触发压缩。要求**尚未摘要的**至少 20 条，避免早期误触发。

        不能拿 `len(self.messages)` 数：存证只增不减，条数永远够，
        压缩过一次之后每轮都会再压一次。
        """
        pending = len(self.messages) - self.summary_upto
        return self.prompt_tokens >= threshold and pending >= 20

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
        """把旧消息摘要成要点。**一条消息都不删。**

        旧版这里最后一句是 `self.messages = recent_messages`——压缩把
        存证也砍了，用户刷新后早期对话直接消失。现在只推进
        `summary_upto`：模型看到的上下文变小，人看到的记录一点没少。
        """
        keep_count = keep_recent * 2
        end = len(self.messages) - keep_count
        if end <= self.summary_upto:
            return

        parts = []
        if self.summary:
            parts.append(f"【之前摘要】\n{self.summary}")
        for m in self.messages[self.summary_upto:end]:
            role = "用户" if m["role"] == "user" else "助手"
            text = m.get("content", "")
            # 动作凭据也要进摘要的输入。只摘 content 的话，"调过什么、
            # 结果是什么"会被整段丢掉，模型回看时会否认自己做过
            for t in m.get("gx_tools") or []:
                state = "成功" if t.get("ok") else "失败"
                gist = f"，{t['gist']}" if t.get("gist") else ""
                text += f"\n  [{t['name']} → {state}{gist}]"
            parts.append(f"{role}：{text}")

        text = "\n\n".join(parts)

        # **要事实，不要散文。** 散文的信息不可控：该留的被挤掉、
        # 不该留的占地方，而且模型没法逐条核对。要点列表可以
        prompt = f"""请把以下对话历史整理成**要点列表**，不要写成一段散文。

要求：
1. 每条一行，写**事实**：用户要什么、做了哪些操作、结果是什么（关键数字保留）
2. 保留实体名（表名、字段名、文件名、人名）
3. 保留用户的偏好和决定
4. 不要编造，不确定的不写
5. 不超过 500 字

对话历史：

{text}

要点："""

        new_summary = llm.chat("你是一个对话摘要助手", prompt).strip()

        self.summary = new_summary
        self.summary_upto = end
        self.prompt_tokens = 0

    def __len__(self):
        return len(self.messages)