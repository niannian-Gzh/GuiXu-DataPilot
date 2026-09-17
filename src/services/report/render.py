from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright


def html_to_pdf(html_content: str, output_path: Path) -> Path:
    """用 Playwright 自带的 Chromium 把 HTML 转成 PDF。

    原先调的是系统 Edge 的 headless，但那条路依赖太多我们控制不了的东西：
    Edge 的版本行为、系统策略、以及「已有 Edge 在跑时命令被转交后立刻返回」
    导致的 0 字节输出。Playwright 的浏览器版本是锁定的，到哪都一样。

    首次使用需要装浏览器：uv run playwright install chromium
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            # 直接灌 HTML，不用再落一个临时文件让浏览器去 file:// 里找
            page.set_content(html_content, wait_until="load")
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            browser.close()

    return output_path


def render_html(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("report.html").render(**context)