from pathlib import Path
import os
import threading
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

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
