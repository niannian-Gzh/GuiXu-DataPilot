# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：归墟桌面版（one-folder）。

为什么是 one-folder 而不是 one-file：
  - 模型 91MB、PyMuPDF/ONNX/FAISS 都有二进制；one-file 每次启动都要
    解压到临时目录，慢且更容易被杀软盯上。
  - Inno Setup 会把整个文件夹压成一个安装包，用户看不到内部结构。
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    get_package_paths,
)

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "src" / "web" / "static"), "src/web/static"),
    (str(ROOT / "models"), "models"),
    (str(ROOT / "src" / "services" / "report" / "templates"),
     "services/report/templates"),
]

binaries = []
hiddenimports = [
    "api",
    # uvicorn 的 loop / protocol / lifespan 都是运行时按名字导入的
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # 桌面壳：Windows 用 WebView2，走 pythonnet
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
    "pythonnet",
    "clr_loader",
    # SQL 方言是 sqlglot 动态加载的
    "sqlglot.dialects.postgres",
    "sqlglot.dialects.sqlite",
    # Python-Markdown 的扩展按名字加载
    "markdown.extensions.tables",
    "markdown.extensions.fenced_code",
    "onnxruntime.capi._pybind_state",
    "tokenizers",
    "faiss.swigfaiss",
]

# 这些包带二进制 / 数据文件 / 动态导入，逐个收全。
# 不收集 playwright：它只用于开发和评测，产品 PDF 走系统 Edge。
for pkg in ("webview", "pythonnet", "onnxruntime", "tokenizers",
            "faiss", "pymupdf", "matplotlib"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("sqlglot.dialects")
hiddenimports += collect_submodules("markdown.extensions")

hookspath = []
try:
    pkg_dir, _ = get_package_paths("pythonnet")
    hookspath = [str(Path(pkg_dir) / "_pyinstaller")]
except Exception:
    pass

a = Analysis(
    [str(ROOT / "src" / "desktop.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hookspath,
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 运行时已经去掉的旧栈和开发工具
        "playwright",
        "duckdb",
        "sqlalchemy",
        "psycopg",
        "psycopg2",
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter",
        "PyQt5",
        "PySide6",
        "PySide2",
        "wx",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GuiXu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=os.environ.get("GUIXU_CONSOLE") == "1",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "archive" / "brand" / "guixu.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GuiXu",
)
