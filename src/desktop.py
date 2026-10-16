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
    # `app_dir` 是 uvicorn 命令行的开关，Config 里没有这个参数 ——
    # 等价的做法是自己把 src/ 放进 sys.path，再用 "api:app" 这种模块串。
    # （命令行那条路是 uvicorn 自己帮我们插的路径，这里得手动来。）
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))

    config = uvicorn.Config(
        "api:app",
        host=HOST,
        port=port,
        log_level="warning",
    )
    uvicorn.Server(config).run()


def main() -> int:
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
        f"http://{HOST}:{port}",
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
