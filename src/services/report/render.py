"""HTML → PDF：调系统 Edge 的无头模式，不随包浏览器。

**为什么不用 Playwright 了。** 设计文档里写的是「Python 依赖（去掉
playwright）」，但代码一直还在用它——实现没跟上设计。打包时这 108MB
的驱动 + 可能的浏览器二进制，正好是「不内置浏览器内核」要避免的东西。

**为什么不用 `msedge --headless --print-to-pdf` 的老写法。** 老写法踩过
「已有 Edge 在跑时命令被转交后立刻返回，输出 0 字节」。根因不是 headless
本身，而是它复用了默认的用户数据目录。这里每次渲染给一个**独立的临时
`--user-data-dir`**，进程不会把命令交给已经开着的 Edge；渲染完再检查
输出文件存在且非空，失败就报清楚，不假装成功。

代价是 PDF 依赖系统 Edge（Windows 10/11 自带）。找不到就明确报错，
让用户知道是环境缺了东西，而不是「生成成功但文件是空的」。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _edge_path() -> Path:
    """按常见安装位置找 msedge.exe。"""
    bases = [
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA"),
    ]
    for base in bases:
        if not base:
            continue
        candidate = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.is_file():
            return candidate

    for name in ("msedge", "msedge.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)

    raise RuntimeError(
        "没有找到 Microsoft Edge。报告和 PDF 文档需要系统 Edge"
        "（Windows 10/11 自带）；如果被卸载了，请先重新安装 Edge。"
    )


def _wait_for_pdf(path: Path, timeout: float = 30.0) -> None:
    """等 Edge 的渲染进程把文件写完。

    Edge 的启动器会先返回 0，PDF 由后面的进程异步写出。**不能**在
    `subprocess.run` 返回时就判断失败，更不能马上删临时目录——那会把
    还没写完的 HTML/profile 一起删掉，输出永远为空。
    """
    deadline = time.monotonic() + timeout
    last_size = -1
    stable = 0
    while time.monotonic() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == last_size:
                stable += 1
                if stable >= 2:      # 连续两次大小一致，认为写完了
                    return
            else:
                stable = 0
                last_size = size
        time.sleep(0.15)


def html_to_pdf(html_content: str, output_path: Path) -> Path:
    """用系统 Edge 把 HTML 打成 PDF。

    每次渲染一个临时 profile，避开「已有 Edge 接管命令行」的 0 字节问题。
    输出为空或进程非 0 都算失败——不在没有文件的情况下返回成功。
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 同名文件可能是上一次留下的；先删掉，避免把旧文件当成这次的成功
    output_path.unlink(missing_ok=True)
    edge = _edge_path()

    # TemporaryDirectory 自己负责清理；Edge 退出后句柄会释放。
    # ignore_cleanup_errors：Windows 上偶尔还有句柄没放，不能因此让
    # 一次已经成功的渲染在收尾时炸掉。
    with tempfile.TemporaryDirectory(
        prefix="gx-pdf-", ignore_cleanup_errors=True,
    ) as tmp:
        tmp_dir = Path(tmp)
        html_path = tmp_dir / "index.html"
        profile_dir = tmp_dir / "edge-profile"
        html_path.write_text(html_content, encoding="utf-8")

        args = [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={profile_dir}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output_path}",
            html_path.resolve().as_uri(),
        ]

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Edge 渲染 PDF 超时（60 秒）") from e
        except OSError as e:
            raise RuntimeError(f"启动 Edge 失败：{e}") from e

        # 启动器已经返回，但渲染进程还在写。等文件稳定后再离开
        # TemporaryDirectory，否则 HTML/profile 会被提前删掉。
        _wait_for_pdf(output_path)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(
            f"Edge 渲染 PDF 失败（退出码 {proc.returncode}）"
            + (f"：{detail}" if detail else "")
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(
            "Edge 没有生成 PDF（输出为空）"
            + (f"：{detail}" if detail else "")
        )

    return output_path


def render_html(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("report.html").render(**context)
