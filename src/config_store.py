"""模型配置的唯一读写入口。

以前只有一套模型配置，散在 config.yaml 的 llm 段里。现在要支持
保存多套随时切换，于是拆成两个文件：

    configs.json —— 配置本身（可进版本库，不含敏感信息）
    secrets.json —— 各配置对应的 key（进 .gitignore）

分开存是因为两者的公开性完全不同：配置可以跟着项目走，
key 一旦提交就等同于泄露。

key 按配置 id 存而不是按供应商名——同一个供应商往往要存好几把
（测试的、生产的、公司的），按供应商名只能留一把。
"""

import json
import os
import threading
import uuid
from pathlib import Path

from config import PROJECT_ROOT, load_config, save_config

CONFIGS_PATH = PROJECT_ROOT / "configs.json"
SECRETS_PATH = PROJECT_ROOT / "secrets.json"

_lock = threading.Lock()
_cache = {"mtime": None, "data": None}

# 新建/更新时接受哪些字段。白名单而不是黑名单：
# 漏掉一个字段顶多是少个功能，放进来一个（比如 id）就是数据损坏
EDITABLE = ("name", "provider", "base_url", "model", "note")


# ---------------- 底层读写 ----------------

def _load() -> dict:
    """读 configs.json。文件坏了当空的处理，别让整个应用起不来。"""
    if not CONFIGS_PATH.exists():
        return {"active_id": None, "configs": []}
    try:
        data = json.loads(CONFIGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active_id": None, "configs": []}
    if not isinstance(data, dict):
        return {"active_id": None, "configs": []}
    data.setdefault("configs", [])
    data.setdefault("active_id", None)
    return data


def _cached() -> dict:
    """带 mtime 缓存的读。和 config.py 一个套路。"""
    try:
        mtime = CONFIGS_PATH.stat().st_mtime
    except OSError:
        return _cache["data"] or _load()

    if _cache["mtime"] != mtime:
        with _lock:
            if _cache["mtime"] != mtime:
                _cache["data"] = _load()
                _cache["mtime"] = mtime
    return _cache["data"]


def _save(data: dict) -> None:
    with _lock:
        CONFIGS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # 直接写缓存，不靠 mtime——时间戳精度在某些盘上只有秒级，
        # 存完紧接着读会拿到旧值
        _cache["data"] = data
        try:
            _cache["mtime"] = CONFIGS_PATH.stat().st_mtime
        except OSError:
            _cache["mtime"] = None


def _read_secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    try:
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_secrets(data: dict) -> None:
    SECRETS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------- 配置 ----------------

def list_configs() -> list:
    """所有配置。不含 key——key 只在 get_key 里按 id 单取。"""
    return list(_cached()["configs"])


def get_active():
    """当前生效的配置，没有则 None。"""
    data = _cached()
    aid = data.get("active_id")
    if not aid:
        return None
    return next((c for c in data["configs"] if c["id"] == aid), None)


def get_config(cid: str):
    """按 id 取配置。"""
    return next((c for c in _cached()["configs"] if c["id"] == cid), None)


def add_config(data: dict) -> dict:
    """新建配置，id 自动生成。返回完整配置。"""
    cfg = _cached()
    item = {"id": uuid.uuid4().hex[:8]}
    for k in EDITABLE:
        item[k] = str(data.get(k) or "").strip()
    item["provider"] = item["provider"] or "custom"
    item["name"] = item["name"] or "未命名配置"

    cfg["configs"].append(item)
    # 第一张自动生效：否则新建完还得再点一次「切换生效」，多一步没道理
    if not cfg["active_id"]:
        cfg["active_id"] = item["id"]
    _save(cfg)
    return item


def update_config(cid: str, data: dict) -> bool:
    """更新配置（不含 key，key 走 set_key）。"""
    cfg = _cached()
    for c in cfg["configs"]:
        if c["id"] != cid:
            continue
        for k in EDITABLE:
            if k in data and data[k] is not None:
                c[k] = str(data[k]).strip()
        c["name"] = c["name"] or "未命名配置"
        c["provider"] = c["provider"] or "custom"
        _save(cfg)
        return True
    return False


def delete_config(cid: str) -> bool:
    """删配置，连带删掉它的 key。

    删的是生效中的那张时，active_id 顺位到列表第一个；列表空了就置 None。
    留一个指向已删除配置的 active_id，会让下次启动初始化 LLM 时拿到空配置，
    报出来的错还跟「删了一张卡片」对不上。
    """
    cfg = _cached()
    before = len(cfg["configs"])
    cfg["configs"] = [c for c in cfg["configs"] if c["id"] != cid]
    if len(cfg["configs"]) == before:
        return False

    if cfg["active_id"] == cid:
        cfg["active_id"] = cfg["configs"][0]["id"] if cfg["configs"] else None
    _save(cfg)

    # key 跟着配置走，别在 secrets.json 里留孤儿条目
    secrets = _read_secrets()
    if secrets.pop(cid, None) is not None:
        _write_secrets(secrets)
    return True


def activate(cid: str) -> bool:
    """切换生效配置。"""
    cfg = _cached()
    if not any(c["id"] == cid for c in cfg["configs"]):
        return False
    cfg["active_id"] = cid
    _save(cfg)
    return True


# ---------------- Key ----------------

def get_key(cid: str):
    """按配置 id 取 key。"""
    return _read_secrets().get(cid) or None


def set_key(cid: str, key: str) -> None:
    """写 key。传空串等于删除。"""
    data = _read_secrets()
    if key:
        data[cid] = key
    else:
        data.pop(cid, None)
    _write_secrets(data)


# ---------------- 首次迁移 ----------------

def migrate_if_needed() -> bool:
    """把 config.yaml 的 llm 段搬成第一张配置卡片。

    只在 configs.json 不存在时执行。做过之后 config.yaml 里就算还留着
    旧的 llm 段也不再看——已经有卡片列表了，以卡片为准。

    返回是否真的做了迁移。
    """
    if CONFIGS_PATH.exists():
        return False

    cfg = load_config()
    old = cfg.get("llm") or {}
    item = {
        "id": uuid.uuid4().hex[:8],
        "name": "默认配置",
        "provider": old.get("provider") or "deepseek",
        "base_url": old.get("base_url") or "",
        "model": old.get("model") or "",
        "note": "由 config.yaml 自动迁移",
    }
    _save({"active_id": item["id"], "configs": [item]})

    # 搬完就把 config.yaml 的 llm 段删掉。留着它会让人以为改那里还管用，
    # 而模型配置已经以 configs.json 为准了——两处都能改、只有一处生效，
    # 是排查起来最费劲的那种局面
    if "llm" in cfg:
        cfg.pop("llm")
        save_config(cfg)

    # 老 key 有两个来路，都要认：
    #   1) .env 里按供应商约定的变量名（DEEPSEEK_API_KEY 之类）
    #   2) secrets.json 里按供应商名存的那份（上一版的数据结构）
    from providers import get_provider

    key = ""
    p = get_provider(item["provider"])
    if p and p.get("env"):
        key = os.getenv(p["env"]) or ""
    if not key:
        key = _read_secrets().get(item["provider"]) or ""
    if key:
        set_key(item["id"], key)

    return True
