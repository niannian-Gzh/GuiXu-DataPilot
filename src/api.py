from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import json
import math
import queue
import shutil
import threading
import uuid
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from llm import LLM
from session import Session
from agent import run_agent
from trace import Trace
from config import load_config, resolve, PROJECT_ROOT, setting, get_config, save_config
from settings_spec import PARAMS, GROUPS, param_by_key, defaults as spec_defaults
from cleanup import cleanup
from services import UserInputRequired
from services import pending_service

from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import duckdb
import pandas as pd

from session import ARCHIVE_DIR



UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
EXPORT_DIR = PROJECT_ROOT / "data" / "exports"
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"


_state = {
    "llm": None,
    "db_path": None,
    "table_name": None,
    "real_table": None,
}

_sessions: dict[str, Session] = {}


def _load_session(session_id: str) -> Session:
    """优先取内存里的会话，其次从磁盘读回，都没有就新建。"""
    if session_id in _sessions:
        return _sessions[session_id]
    session = Session.load(session_id)
    _sessions[session_id] = session
    return session


def _json_default(obj):
    """SSE 序列化兜底。候选记录里的 pandas 类型转字符串，NaT 转 null。"""
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)


def _sanitize(obj):
    """递归把 NaN / Infinity 换成 None。

    json.dumps 默认会把它们输出成裸的 NaN、Infinity 字面量，
    而那不是合法 JSON —— 浏览器的 JSON.parse 会直接抛错，
    整个事件就此丢掉。表现是「工具一直转圈、确认卡片不出现」，
    因为承载候选记录的 pending 事件没了。

    走不到 _json_default：float('nan') 是原生类型，
    dumps 会直接序列化，不会去问 default。
    """
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()["data"]
    _state["llm"] = LLM()
    _state["db_path"] = resolve(cfg["db_path"])
    _state["table_name"] = cfg["table_name"]
    _state["real_table"] = f"{cfg['table_name']}_all"
    cleanup()
    yield
    _sessions.clear()


app = FastAPI(title="DataPilot 数据处理 Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端拆成了外部 css/js，需要静态文件服务
app.mount("/css", StaticFiles(directory=STATIC_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=STATIC_DIR / "js"), name="js")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ============ 数据模型 ============

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class FileInfo(BaseModel):
    name: str
    path: str
    size: int
    mtime: str
    type: str


# ============ 基础接口 ============

@app.get("/health")
def health():
    return {"status": "ok"}


# ============ 对话接口 ============

@app.post("/chat")
def chat(req: ChatRequest):
    """流式对话。以 SSE 逐步推送 agent 的执行过程。

    事件类型：start / think / tool_call / tool_result / compact /
    answer / pending / error / done
    """
    session_id = req.session_id or uuid.uuid4().hex[:12]
    session = _load_session(session_id)
    trace = Trace(req.question)

    events: "queue.Queue[dict]" = queue.Queue()

    def sink(event: dict):
        events.put(event)

    def run():
        try:
            sink({"type": "start", "session_id": session_id, "question": req.question})

            handled, msg = pending_service.handle_pending(
                req.question, session,
                _state["db_path"], _state["real_table"],
                _state["llm"],
            )
            if handled:
                sink({"type": "answer", "content": msg})
            else:
                run_agent(
                    req.question, session, _state["llm"],
                    _state["db_path"], _state["table_name"], trace,
                    emit=sink,
                )

        except UserInputRequired as e:
            pending = e.pending_action
            session.set_pending(pending)
            sink({
                "type": "pending",
                "pending": pending,
                "message": pending_service.format_pending_display(pending),
            })

        except Exception as e:
            trace.set("error", str(e))
            sink({"type": "error", "message": str(e)})

        finally:
            trace.mark_end()
            trace.save()
            # 空会话不落盘。走 pending 分支时不会经过 run_agent，
            # 一轮下来 messages 仍是空的，存下去只会在列表里堆垃圾
            if session.messages:
                session.save()
            sink({
                "type": "done",
                "session_id": session_id,
                "elapsed_ms": trace.data["elapsed_ms"],
            })

    def stream():
        threading.Thread(target=run, daemon=True).start()
        while True:
            event = events.get()
            try:
                # 先清洗 NaN/Inf（它们不是合法 JSON），再处理 pandas 类型
                payload = json.dumps(_sanitize(event),
                                     ensure_ascii=False, default=_json_default)
            except Exception as e:
                # 一个事件序列化失败不该拖垮整条流——那样前端只会看到
                # 「连接中断」，而真正的原因（哪个字段有问题）全部丢失
                payload = json.dumps({
                    "type": "error",
                    "message": f"事件序列化失败：{e}",
                }, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            if event["type"] == "done":
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============ 设置接口 ============

ENV_PATH = PROJECT_ROOT / ".env"


class SettingsUpdate(BaseModel):
    values: dict


def _mask_secret(s: str) -> str:
    """只回传掩码，明文永不进浏览器。

    即便是本地工具也不该破这个例：浏览器有历史、有开发者工具、
    有截图，任何一处泄出去就等于 key 泄了。
    """
    if not s:
        return ""
    if len(s) <= 8:
        return "****"
    return s[:4] + "****" + s[-4:]


def _read_env(name: str) -> str:
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _write_env(name: str, value: str) -> None:
    """只改目标那一行，其余内容原样保留。"""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{name}="):
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _current_value(p: dict):
    if p.get("source") == "env":
        return _mask_secret(_read_env(p["env_name"]))
    node = get_config()
    for part in p["key"].split("."):
        if not isinstance(node, dict) or part not in node:
            return p["default"]
        node = node[part]
    return p["default"] if node is None else node


def _readonly_info() -> dict:
    """只读信息：这些不是偏好，改错会让系统崩或数据看起来丢了，所以只给看。"""
    cfg = get_config().get("data", {})
    db_path = cfg.get("db_path", "")

    total = None
    try:
        con = duckdb.connect(resolve(db_path), read_only=True)
        total = con.execute(f"SELECT COUNT(*) FROM {cfg.get('table_name')}").fetchone()[0]
        con.close()
    except Exception:
        pass

    return {
        "数据库文件": str(resolve(db_path)),
        "数据表": cfg.get("table_name", ""),
        "在册记录": total,
        "初始数据源": str(resolve(cfg.get("excel_path", ""))),
        "导出目录": str(EXPORT_DIR),
        "报告目录": str(REPORT_DIR),
        "上传目录": str(UPLOAD_DIR),
        "日志目录": str(PROJECT_ROOT / "logs"),
    }


@app.get("/settings")
def get_settings():
    """返回参数注册表 + 当前值 + 只读信息。"""
    items = []
    for p in PARAMS:
        cur = _current_value(p)
        item = dict(p)
        item["value"] = cur
        item["is_default"] = (cur == p["default"])
        items.append(item)

    return {
        "groups": GROUPS,
        "params": items,
        "info": _readonly_info(),
    }


@app.put("/settings")
def update_settings(req: SettingsUpdate):
    """写回配置。config.yaml 走 mtime 缓存自动重载，改完立即生效。"""
    incoming = req.values or {}

    unknown = [k for k in incoming if param_by_key(k) is None]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知的配置项：{', '.join(unknown)}")

    cfg = get_config()

    for key, raw in incoming.items():
        p = param_by_key(key)

        # --- 校验 ---
        if p["type"] == "number":
            # JSON 里的数字要保持浮点，不能一律 int()——
            # 那会把 temperature 的 0.7 悄悄截成 0，而且不报错
            if isinstance(raw, bool):
                raise HTTPException(status_code=400, detail=f"「{p['label']}」需要一个数字")
            if isinstance(raw, (int, float)):
                val = raw
            else:
                try:
                    s = str(raw).strip()
                    val = float(s) if ("." in s or "e" in s.lower()) else int(s)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"「{p['label']}」需要一个数字")

            if p.get("min") is not None and val < p["min"]:
                raise HTTPException(status_code=400, detail=f"「{p['label']}」不能小于 {p['min']}")
            if p.get("max") is not None and val > p["max"]:
                raise HTTPException(status_code=400, detail=f"「{p['label']}」不能大于 {p['max']}")

            # 整数型参数去掉小数尾巴（比如前端传 4096.0）
            if isinstance(p["default"], int) and isinstance(val, float) and val.is_integer():
                val = int(val)
        else:
            val = "" if raw is None else str(raw)

        # --- 落盘 ---
        if p.get("source") == "env":
            # 空值表示"不修改"，避免用户没动这一栏就把 key 清空了
            if val.strip() == "":
                continue
            _write_env(p["env_name"], val.strip())
        else:
            path = p["key"].split(".")
            node = cfg
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = val

    save_config(cfg)

    # .env 改过之后要重新灌进进程环境，否则 LLM 还是拿着旧 key。
    # override=True 是必须的：默认模式不会覆盖已存在的环境变量
    load_dotenv(override=True)

    # LLM 实例在 __init__ 里固化了 model / base_url / temperature / api_key，
    # 配置一变就得重建，否则改了设置却没有任何效果
    _state["llm"] = LLM()

    return {"status": "ok", "message": "已保存并生效"}


# ============ 会话接口 ============

@app.get("/sessions")
def list_sessions():
    """历史会话列表，按更新时间倒序。"""
    return {"sessions": Session.list_saved()}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    """读回一个会话的完整消息。"""
    path = ARCHIVE_DIR / f"{session_id}.json"
    if session_id not in _sessions and not path.exists():
        raise HTTPException(status_code=404, detail="会话不存在")

    session = _load_session(session_id)
    return {
        "session_id": session_id,
        "title": session.title(),
        "messages": session.messages,
        "has_pending": session.get_pending() is not None,
    }


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """删除一个会话（内存 + 磁盘）。"""
    _sessions.pop(session_id, None)
    path = ARCHIVE_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
    return {"status": "ok"}


# ============ 文件接口 ============

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传 Excel 文件。返回可用的路径。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls 文件")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name

    # 边写边量：不能先整个落盘再判断大小，那样限制就没意义了
    max_mb = setting("safety.max_upload_mb")
    max_bytes = max_mb * 1024 * 1024
    written = 0
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    f.close()
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {max_mb} MB 上限",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"写入失败：{e}")

    rel_path = file_path.relative_to(PROJECT_ROOT)
    return {
        "status": "ok",
        "filename": file.filename,
        "path": str(rel_path).replace("\\", "/"),
        "message": f"已上传：{file.filename}",
    }


def _is_safe_path(path_str: str) -> bool:
    """只允许下载 data/exports/ 和 data/reports/ 下的文件。"""
    try:
        p = Path(path_str).resolve()
        if not p.exists() or not p.is_file():
            return False
        for allowed in (EXPORT_DIR, REPORT_DIR):
            try:
                p.relative_to(allowed.resolve())
                return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


@app.get("/download")
def download_file(path: str = Query(..., description="相对项目根的路径")):
    """下载导出或报告文件。"""
    full_path = PROJECT_ROOT / path

    if not _is_safe_path(str(full_path)):
        raise HTTPException(status_code=403, detail="文件不存在或不允许下载")

    return FileResponse(
        full_path,
        filename=full_path.name,
        media_type="application/octet-stream",
    )


# 能交给浏览器直接渲染的类型
INLINE_MEDIA_TYPES = {
    ".pdf":  "application/pdf",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
    ".txt":  "text/plain; charset=utf-8",
    ".csv":  "text/csv; charset=utf-8",
}


@app.get("/raw")
def raw_file(path: str = Query(..., description="相对项目根的路径")):
    """内联返回文件，供浏览器直接打开。

    与 /download 的唯一区别是 Content-Disposition 用 inline 而非 attachment。
    少了这一条，浏览器拿到 PDF 只会往下载目录里塞，不会渲染。
    """
    full_path = PROJECT_ROOT / path
    if not _is_safe_path(str(full_path)):
        raise HTTPException(status_code=403, detail="文件不存在或不允许访问")

    media_type = INLINE_MEDIA_TYPES.get(full_path.suffix.lower(), "application/octet-stream")
    # 文件名走 RFC 5987，中文名才不会让 header 编码出错
    disposition = "inline; filename*=UTF-8''" + quote(full_path.name)

    return FileResponse(
        full_path,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@app.get("/files")
def list_files():
    """列出可下载的文件（exports + reports）。"""
    files = []

    for d, ftype in [(EXPORT_DIR, "export"), (REPORT_DIR, "report")]:
        if not d.exists():
            continue
        for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not f.is_file():
                continue
            stat = f.stat()
            files.append(FileInfo(
                name=f.name,
                path=str(f.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                size=stat.st_size,
                mtime=__import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                type=ftype,
            ))

    return {"files": files}

@app.get("/preview")
def preview_file(path: str = Query(...)):
    """查看文件内容。Excel 返回表格数据，PDF 返回文件 URL。"""
    full_path = PROJECT_ROOT / path
    if not _is_safe_path(str(full_path)):
        raise HTTPException(status_code=403, detail="文件不存在或不允许访问")

    suffix = full_path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(full_path)
        total = len(df)
        preview_df = df.head(setting("display.preview_rows"))
        return {
            "type": "excel",
            "columns": [str(c) for c in preview_df.columns],
            "rows": [[str(v) if pd.notna(v) else "" for v in row]
                     for row in preview_df.values.tolist()],
            "total_rows": total,
            "shown_rows": len(preview_df),
        }

    if suffix == ".pdf":
        return {
            "type": "pdf",
            # 必须走 /raw：/download 会带 attachment，浏览器只会下载不会渲染
            "url": f"/raw?path={quote(path)}",
        }

    return {
        "type": "other",
        "url": f"/download?path={path}",
    }


@app.delete("/files/{file_path:path}")
def delete_file(file_path: str):
    """删除一个文件。"""
    full_path = PROJECT_ROOT / file_path
    if not _is_safe_path(str(full_path)):
        raise HTTPException(status_code=403, detail="文件不存在或不允许删除")
    full_path.unlink()
    return {"status": "ok"}


@app.delete("/files")
def clear_all_files():
    """清空所有导出和报告文件。"""
    count = 0
    for d in (EXPORT_DIR, REPORT_DIR):
        if d.exists():
            for f in d.iterdir():
                if f.is_file():
                    f.unlink()
                    count += 1
    return {"status": "ok", "deleted": count}