"""归墟的桌面入口。

`api.py` 起 HTTP 服务，但它假设用户自己有一个浏览器。
这个是另一个入口：**它自己就是一个应用窗口。**

三件事，按顺序：
  1. 挑一个空闲端口起 uvicorn（**不用 8000**——那会和开发时正在跑的服务打架）
  2. 等端口真的通了，再去开窗口（不等就会先白屏一下）
  3. 窗口一关就退出

为什么内核是自带的：前端那套（开机动画尤其）是逐帧调过的东西，
把它交给系统浏览器的版本去渲染，等于把作品的呈现交给一个我们控制不了的变量。
代价是包大了几百 MB，这个代价已经算过并接受。
"""

import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

SRC_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"


def pick_port() -> int:
    """让操作系统给一个空闲端口。

    不写死 8000：开发时它多半正被 `uv run uvicorn` 占着，
    两个实例抢端口会得到一句很难懂的报错。绑 0 让内核挑，永远是空的。
    """
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 20.0) -> bool:
    """等服务真的能连上。

    uvicorn 的 start 是异步的：线程起来了不等于端口通了，
    而我们应该在「服务无法启动」时超时并明确报错，
    而不是把一个永远转圈的白窗口端给用户。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.05)
    return False


def serve(port: int) -> None:
    # 开发时把 src/ 放进 sys.path；打包后模块已经在 sys.path 里，
    # 不要再用源码路径。
    if not getattr(sys, "frozen", False):
        if str(SRC_DIR) not in sys.path:
            sys.path.insert(0, str(SRC_DIR))

    # 直接 import app 对象，不用 "api:app" 字符串：
    # PyInstaller 靠静态导入收集模块，字符串它看不见，得另写 hiddenimports。
    from api import app

    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        log_level="warning",
    )
    uvicorn.Server(config).run()


def main() -> int:
    # 打包成窗口程序后没有控制台，stdout/stderr 都是 None；uvicorn 和
    # 项目里的 print 会直接撞 AttributeError。给它们一个日志文件。
    if getattr(sys, "frozen", False):
        from config import DATA_ROOT
        log_dir = DATA_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file

    try:
        import webview
    except ImportError:
        print(
            "缺少桌面依赖。装一次：\n"
            "    uv sync --extra desktop\n"
            "（只需要 pywebview 和它跟系统浏览器内核通话的桥，跟运行服务本身无关）",
            file=sys.stderr,
        )
        return 1

    # 关掉 WebView2 的自动播放限制。
    #
    # Chromium 规定「页面在没有任何用户交互之前不许自动出声」，防的是广告弹窗。
    # 浏览器里没辙 —— 开机动画只能靠一个「按任意键」的闸门骗一次手势。
    # 但桌面应用里我们就是宿主，可以在内核起来之前把这条策略关掉。
    #
    # 必须设在 pywebview 创建内核【之前】，晚了不生效。
    os.environ.setdefault(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--autoplay-policy=no-user-gesture-required",
    )

    port = pick_port()

    # uvicorn 跑在后台线程，窗口必须占主线程 ——
    # Qt 的事件循环只认主线程，反过来的话窗口起不来。
    # daemon=True：窗口一关，进程结束，这个线程跟着走，不用另外收尾。
    threading.Thread(target=serve, args=(port,), daemon=True).start()

    if not wait_for_port(port):
        print(f"服务在 {port} 上没能起来，窗口不开了。", file=sys.stderr)
        return 1

    webview.create_window(
        "归墟 · 数据处理 Agent",
        # desktop=1：告诉前端这是桌面宿主。WebView2 的自动播放限制
        # 已经在上面关掉了，动画可以直接起播，不用再等“按任意键”。
        f"http://{HOST}:{port}/?desktop=1",
        width=1440,
        height=900,
        min_size=(1024, 680),
    )
    # 不指定 gui，让 pywebview 自己挑系统内核：
    # Windows → edgechromium(WebView2) / macOS → cocoa(WKWebView) / Linux → gtk。
    # 写死 gui='qt' 会退回那个 600MB 且显示不了 PDF 的自带内核。
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
