"""评测框架：沙箱、用例登记、断言、运行与报告。

设计只看三条：

1. **每条用例一个干净的库。** 用例之间不共享状态，顺序无关，可以单跑。
2. **任何用例都不许碰真实数据。** 库、会话、trace、导出、报告、上传、
   模型配置全部重定向到 `eval/.sandbox/`，进程退出后删掉。
3. **期望值从 fixture 现算。** 不写死数字——数据换了评测照样成立。

沙箱能成立，靠的是项目里所有"往外写"的路径都是模块常量：
`config.CONFIG_PATH`、`session.ARCHIVE_DIR`、`trace.TRACE_FILE`、
`api.*_DIR`、`config_store.*_PATH`。这里在导入业务模块之后统一替换。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EVAL_DIR = Path(__file__).resolve().parent
SANDBOX_PARENT = EVAL_DIR / ".sandbox"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))


# ============================================================ 用例登记

@dataclass
class Case:
    func: callable
    dim: str
    title: str
    attack: str = ""       # 攻击者视角：这条用例想干什么
    expect: str = ""       # 期望的防御 / 正确行为
    suite: str = "offline"
    slow: bool = False

    @property
    def id(self) -> str:
        return self.func.__name__


CASES: list[Case] = []


def case(dim: str, title: str, attack: str = "", expect: str = "",
         suite: str = "offline", slow: bool = False):
    """登记一条用例。被装饰的函数签名是 `fn(env)`。"""
    def deco(fn):
        CASES.append(Case(fn, dim, title, attack, expect, suite, slow))
        return fn
    return deco


# ============================================================ 断言

class SkipTest(Exception):
    """这条用例在当前环境跑不了（缺 key、缺浏览器等）。"""


def check(cond, message: str):
    if not cond:
        raise AssertionError(message)


def eq(actual, expected, label: str = ""):
    if actual != expected:
        prefix = f"{label}：" if label else ""
        raise AssertionError(f"{prefix}期望 {expected!r}，实际 {actual!r}")


def contains(haystack, needle, label: str = ""):
    if needle not in haystack:
        prefix = f"{label}：" if label else ""
        raise AssertionError(f"{prefix}期望包含 {needle!r}，实际 {str(haystack)[:300]!r}")


def has_keys(data: dict, *keys):
    missing = [k for k in keys if k not in data]
    if missing:
        raise AssertionError(f"返回缺少字段：{missing}，实际：{str(data)[:300]}")


def raises(fn, exc=Exception, label: str = ""):
    """断言调用会抛异常，返回异常对象。"""
    try:
        fn()
    except exc as e:
        return e
    except Exception as e:                 # 类型不对也算失败
        raise AssertionError(f"{label}：期望 {exc.__name__}，实际 {type(e).__name__}: {e}")
    raise AssertionError(f"{label}：期望抛 {exc.__name__}，实际正常返回")


# ============================================================ 沙箱

class Sandbox:
    """把应用的所有输出路径搬到 `eval/.sandbox/run-*` 下。"""

    def __init__(self, keep: bool = False):
        self.keep = keep
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.root = SANDBOX_PARENT / f"run-{stamp}-{os.getpid()}"
        self.db_path = self.root / "guixu.db"
        self._patched: list[tuple[object, str, object]] = []
        self.llm = None

    # -------- 生命周期 --------

    def start(self):
        if self.root.exists():
            shutil.rmtree(self.root)
        for name in ("sessions", "exports", "reports", "uploads", "data"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

        # 业务模块在替换路径之前导入，才能拿到模块对象
        import config
        import config_store
        import session
        import trace
        import api
        import services.export_service as export_service
        import services.report_service as report_service

        self._config = config
        self._config_store = config_store
        self._session = session
        self._trace = trace
        self._api = api
        self._export_service = export_service
        self._report_service = report_service

        # 库：写一份临时 config.yaml。db_path 给绝对路径——
        # config.resolve 拿 PROJECT_ROOT 去拼，Windows 下绝对路径会
        # 直接盖掉左边，落到沙箱里（已实测）
        config.CONFIG_PATH = self.root / "config.yaml"
        config.save_config({"data": {"db_path": str(self.db_path)}})

        self._set(session, "ARCHIVE_DIR", self.root / "sessions")
        self._set(trace, "TRACE_FILE", self.root / "traces.jsonl")
        self._set(export_service, "EXPORT_DIR", self.root / "exports")
        self._set(report_service, "REPORT_DIR", self.root / "reports")

        self._set(api, "PROJECT_ROOT", self.root)
        self._set(api, "ARCHIVE_DIR", self.root / "sessions")
        self._set(api, "UPLOAD_DIR", self.root / "uploads")
        self._set(api, "EXPORT_DIR", self.root / "exports")
        self._set(api, "REPORT_DIR", self.root / "reports")
        self._set(api, "CONFIG_PATH", config.CONFIG_PATH)
        self._set(api, "ENV_PATH", self.root / ".env")
        api._sessions.clear()

        # 模型配置：复制用户当前那两份，评测期间读写都落在副本上。
        # 没有卡片时这里是空的，Agent 套件会整体跳过
        self._set(config_store, "CONFIGS_PATH", self.root / "configs.json")
        self._set(config_store, "SECRETS_PATH", self.root / "secrets.json")
        config_store._cache = {"mtime": None, "data": None}
        for name in ("configs.json", "secrets.json"):
            src = ROOT / name
            if src.exists():
                shutil.copy2(src, self.root / name)

        return self

    def stop(self):
        server = getattr(self, "_server", None)
        if server is not None:
            server.should_exit = True
            self._server = None
        for obj, name, old in reversed(self._patched):
            setattr(obj, name, old)
        self._patched.clear()
        if not self.keep and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def _set(self, obj, name: str, value):
        self._patched.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    # -------- 每条用例前的重建 --------

    def reset(self, empty: bool = False):
        """删库重来。会话、trace、导出、上传、配置也一起复位。"""
        # 用例可能改过设置（比如把超时调短），下一条不能继承
        self._config.save_config({"data": {"db_path": str(self.db_path)}})

        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            if p.exists():
                p.unlink()

        for folder in ("sessions", "exports", "reports", "uploads"):
            d = self.root / folder
            if d.exists():
                for f in d.iterdir():
                    if f.is_file():
                        f.unlink()

        trace_file = self.root / "traces.jsonl"
        if trace_file.exists():
            trace_file.unlink()

        self._api._sessions.clear()

        import storage
        con = storage.connect(self.db_path)
        try:
            if not empty:
                from fixtures.inspection import build
                build(con)
        finally:
            con.close()

    # -------- 便捷入口 --------

    def llm_instance(self):
        """懒初始化。没有可用配置时返回 None。"""
        if self.llm is not None:
            return self.llm
        from llm import LLM
        try:
            llm = LLM()
        except RuntimeError:
            return None
        if getattr(llm, "mock", False):
            return None
        self.llm = llm
        return llm


# ============================================================ 用例环境

class Env:
    """用例手里能用的东西：库、API 模块、fixture 动态期望。"""

    def __init__(self, box: Sandbox):
        self.box = box
        self.sandbox = box

    # 库
    def connect(self):
        import storage
        return storage.connect(self.box.db_path)

    def query(self, sql: str, params=None):
        con = self.connect()
        try:
            return con.execute(sql, params).fetchall() if params is not None \
                else con.execute(sql).fetchall()
        finally:
            con.close()

    def scalar(self, sql: str, params=None):
        rows = self.query(sql, params)
        return rows[0][0] if rows else None

    def count(self, table: str, where: str = "", params=None) -> int:
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.scalar(sql, params))

    def audit_count(self, action: str | None = None) -> int:
        if action:
            return int(self.scalar(
                "SELECT COUNT(*) FROM _gx_audit WHERE action = ?", (action,)
            ))
        return int(self.scalar("SELECT COUNT(*) FROM _gx_audit"))

    def snapshot_count(self) -> int:
        return int(self.scalar("SELECT COUNT(*) FROM _gx_snapshot"))

    def table_exists(self, name: str) -> bool:
        return self.scalar(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (name,)
        ) is not None

    # 期望值：永远从当前库现算，不写死
    def truth(self):
        from fixtures.inspection import Truth
        return Truth(self)

    # API
    @property
    def api(self):
        return self.box._api

    def client(self):
        """FastAPI TestClient。每次新建，避免跨用例的 lifespan 状态。

        `raise_server_exceptions=False`：用例要看的是"接口会不会 500"，
        不是让异常直接炸到评测进程里。
        """
        from fastapi.testclient import TestClient
        return TestClient(self.api.app, raise_server_exceptions=False)

    def serve(self) -> str:
        """起一个真实 HTTP 服务，给 Playwright 用。同一条评测进程只起一次。"""
        if getattr(self.box, "_server_url", None):
            return self.box._server_url

        import socket
        import threading
        import uvicorn

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        server = uvicorn.Server(uvicorn.Config(
            self.api.app, host="127.0.0.1", port=port, log_level="critical",
        ))
        threading.Thread(target=server.run, daemon=True).start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise SkipTest("评测用的 HTTP 服务没起来")

        self.box._server = server
        self.box._server_url = f"http://127.0.0.1:{port}"
        return self.box._server_url


# ============================================================ 运行与报告

def run(cases: list[Case], *, keep: bool = False, verbose: bool = False) -> int:
    box = Sandbox(keep=keep).start()
    results = []
    current_suite = None

    print(f"沙箱：{box.root}")
    print(f"用例：{len(cases)} 条\n")

    try:
        for i, c in enumerate(cases, 1):
            if c.suite != current_suite:
                current_suite = c.suite
                print(f"—— {current_suite} ——")

            box.reset()
            started = time.time()
            env = Env(box)
            try:
                # Agent 套件共用一个 LLM；没 key 时整条用例标 skip
                if c.suite == "agent" and box.llm_instance() is None:
                    raise SkipTest("没有可用的模型配置或 key")
                c.func(env)
                status, detail = "pass", ""
            except SkipTest as e:
                status, detail = "skip", str(e)
            except AssertionError as e:
                status, detail = "fail", str(e)
            except Exception as e:
                status, detail = "error", f"{type(e).__name__}: {e}"
                if verbose:
                    detail += "\n" + traceback.format_exc()
            elapsed = int((time.time() - started) * 1000)

            icon = {"pass": "✓", "fail": "✗", "error": "!", "skip": "-"}[status]
            print(f"  {icon} [{c.dim}] {c.id}  ({elapsed} ms)")
            if status in ("fail", "error") and detail:
                for line in detail.splitlines()[:6]:
                    print(f"      {line}")
            if verbose and c.attack:
                print(f"      攻击：{c.attack}")
            results.append({
                "id": c.id, "dim": c.dim, "title": c.title, "attack": c.attack,
                "expect": c.expect, "suite": c.suite, "status": status,
                "detail": detail, "ms": elapsed,
            })
    finally:
        box.stop()

    return _report(results, cases)


def _report(results: list[dict], cases: list[Case]) -> int:
    passed = sum(r["status"] == "pass" for r in results)
    failed = sum(r["status"] == "fail" for r in results)
    errored = sum(r["status"] == "error" for r in results)
    skipped = sum(r["status"] == "skip" for r in results)

    by_dim: dict[str, dict] = {}
    for r in results:
        d = by_dim.setdefault(r["dim"], {"pass": 0, "fail": 0, "error": 0, "skip": 0})
        d[r["status"]] += 1

    print("\n========== 结果 ==========")
    for dim in sorted(by_dim):
        d = by_dim[dim]
        total = d["pass"] + d["fail"] + d["error"] + d["skip"]
        print(f"  {dim:<16} {d['pass']}/{total} 通过"
              + (f"  {d['fail']} 失败" if d["fail"] else "")
              + (f"  {d['error']} 异常" if d["error"] else "")
              + (f"  {d['skip']} 跳过" if d["skip"] else ""))

    print(f"\n  合计：{passed} 通过 / {failed} 失败 / {errored} 异常 / {skipped} 跳过"
          f"（共 {len(results)} 条）")

    # 对抗面单独一行：D4 越权/D7 诚实性，这是这次重写最该看的一个数
    attacks = [r for r in results
               if r["dim"] in ("D4", "D7") and r["status"] != "skip"]
    if attacks:
        blocked = sum(r["status"] == "pass" for r in attacks)
        print(f"  对抗/诚实用例通过：{blocked}/{len(attacks)}")

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "latest.json"
    out.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {"pass": passed, "fail": failed, "error": errored,
                    "skip": skipped, "total": len(results)},
        "by_dim": by_dim,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  报告：{out}")

    return 0 if failed == 0 and errored == 0 else 1
