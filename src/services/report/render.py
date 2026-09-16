import subprocess
import tempfile
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape



EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _find_edge() -> str:
    for p in EDGE_PATHS:
        if Path(p).exists():
            return p
    raise RuntimeError("找不到 Edge 浏览器，请确认已安装 Microsoft Edge")


def html_to_pdf(html_content: str, output_path: Path) -> Path:
    """用 Edge 无头模式把 HTML 转成 PDF。"""
    edge = _find_edge()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as f:
        f.write(html_content)
        html_path = Path(f.name).resolve()

    try:
        subprocess.run(
            [
                edge,
                "--headless",
                "--disable-gpu",
                f"--print-to-pdf={output_path}",
                html_path.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    finally:
        html_path.unlink(missing_ok=True)

    return output_path


def render_html(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("report.html").render(**context)