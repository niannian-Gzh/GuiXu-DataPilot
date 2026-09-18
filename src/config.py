from pathlib import Path
import json
import os
import threading
import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "secrets.json"

# 这里加载一次，get_api_key 回落到 .env 时才读得到。
# 默认不覆盖已有的环境变量，所以和 api.py 里的 override=True 不冲突
load_dotenv()

_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def load_config() -> dict:
    """直接读文件，不走缓存。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_config() -> dict:
    """带 mtime 缓存的读配置。

    改完 config.yaml 不用重启进程：文件时间戳一变就重新读。
    缓存是为了让热点路径（比如每次 SQL 执行都要读超时值）
    不必反复读盘——那点 IO 单看不值一提，摊到每次查询上就不该有。
    """
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        # 文件读不到时退回上次的缓存，别让整个程序崩在配置上
        return _cache["data"] or load_config()

    if _cache["mtime"] != mtime:
        with _lock:
            if _cache["mtime"] != mtime:      # 双检：并发时只读一次盘
                _cache["data"] = load_config()
                _cache["mtime"] = mtime
    return _cache["data"]


def get(path: str, default=None):
    """按点号路径取值，如 get("llm.model")。缺失时返回 default。

    所有可配置参数都该走这里，而不是模块级常量——
    常量在 import 时就固化了，改配置文件必须重启才生效。
    """
    node = get_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return default if node is None else node


_registry_defaults = None


def setting(key: str):
    """读一个可配置参数；配置文件里没有就用注册表里的默认值。

    各模块一律用这个，不要在模块顶层写常量——
    常量在 import 时就固化了，改完配置文件必须重启才生效。
    默认值只在 settings_spec.py 里定义一次，这里不重复数字。
    """
    global _registry_defaults
    if _registry_defaults is None:
        from settings_spec import defaults as _spec_defaults
        _registry_defaults = _spec_defaults()
    return get(key, _registry_defaults.get(key))


def save_config(data: dict) -> None:
    """写回 config.yaml，并让缓存立即失效。"""
    with _lock:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data, f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        # 直接写进缓存，不靠 mtime 比对——文件系统的时间戳精度
        # 在某些盘上只有秒级，紧接着的读请求会拿到旧值
        _cache["data"] = data
        try:
            _cache["mtime"] = os.path.getmtime(CONFIG_PATH)
        except OSError:
            _cache["mtime"] = None


def resolve(relative_path: str) -> str:
    """把配置里的相对路径，解析成基于项目根的绝对路径字符串。"""
    return str(PROJECT_ROOT / relative_path)


# ============ API Key ============

def read_secrets() -> dict:
    """读 secrets.json。文件不存在或坏了都当空的处理。

    坏了当空的，好过抛异常——密钥文件被编辑器占用或写坏时，
    整个应用不该连启动都做不到。
    """
    if not SECRETS_PATH.exists():
        return {}
    try:
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_api_key(provider: str):
    """按供应商取 key。secrets.json 优先，回落到 .env 里的老变量。

    回落是为了不打断已有的配置：只写过 .env 的用户，在没动设置页之前
    一切照旧。两者都没有时返回 None，让调用方自己决定怎么提示。
    """
    key = read_secrets().get(provider)
    if key:
        return key

    from providers import get_provider
    p = get_provider(provider)
    if p and p.get("env"):
        return os.getenv(p["env"]) or None
    return None


def set_api_key(provider: str, key: str) -> None:
    """写入 secrets.json。只动这一家，别家的原样保留。"""
    data = read_secrets()
    if key:
        data[provider] = key
    else:
        # 传空串表示清除，别在文件里留个空键
        data.pop(provider, None)
    SECRETS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
