"""构建归墟桌面版。

    uv sync --extra desktop --group build
    uv run python scripts/build_app.py              # 只出 dist/GuiXu/
    uv run python scripts/build_app.py --installer  # 再编译 Inno Setup 安装包
    uv run python scripts/build_app.py --console    # 调试用：带控制台窗口

安装包需要本机装好 Inno Setup 6（ISCC.exe）。没装时只出文件夹版，
脚本会打印下载地址，不会假装安装包已经生成。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "guixu.spec"
ISS = ROOT / "packaging" / "installer.iss"
DIST = ROOT / "dist"
APP_DIR = DIST / "GuiXu"
MODEL = ROOT / "models" / "bge-small-zh-v1.5" / "model.onnx"

sys.path.insert(0, str(ROOT / "src"))
from version import __version__ as RUNTIME_VERSION  # noqa: E402


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _ensure_model() -> None:
    if MODEL.exists():
        return
    print(f"缺少 embedding 权重：{MODEL}")
    print("先运行：uv run python scripts/fetch_model.py")
    raise SystemExit(1)


def _find_iscc() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    found = shutil.which("iscc")
    return Path(found) if found else None


def _size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / 1048576


def main() -> int:
    parser = argparse.ArgumentParser(description="构建归墟桌面版")
    parser.add_argument("--installer", action="store_true",
                        help="编译 Inno Setup 安装包（需要本机有 ISCC.exe）")
    parser.add_argument("--console", action="store_true",
                        help="构建带控制台的调试版")
    args = parser.parse_args()

    _ensure_model()
    if not (ROOT / "archive" / "brand" / "guixu.ico").is_file():
        raise SystemExit("缺少应用图标：archive/brand/guixu.ico")
    if _version() != RUNTIME_VERSION:
        raise SystemExit(
            f"版本号不一致：pyproject={_version()}，src/version.py={RUNTIME_VERSION}。"
            "改版本时两处一起改。"
        )

    env = os.environ.copy()
    if args.console:
        env["GUIXU_CONSOLE"] = "1"

    print(f"构建 v{_version()} → {APP_DIR}")
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            "--distpath", str(DIST),
            "--workpath", str(ROOT / "build" / "pyinstaller"),
            str(SPEC),
        ],
        check=True,
        env=env,
    )
    print(f"文件夹版：{APP_DIR}（{_size_mb(APP_DIR):.0f} MB）")

    if not args.installer:
        print("未编译安装包。加 --installer 可生成 Setup。")
        return 0

    iscc = _find_iscc()
    if iscc is None:
        print("没有找到 Inno Setup 6 的 ISCC.exe。")
        print("安装 Inno Setup 6 后重跑 --installer；或先用文件夹版测试。")
        return 1

    print(f"编译安装包：{ISS}")
    subprocess.run([str(iscc), str(ISS)], check=True)
    print(f"安装包：{DIST / f'GuiXu-Setup-{_version()}.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
