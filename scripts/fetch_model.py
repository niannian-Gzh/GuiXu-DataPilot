"""下载 RAG 用的 embedding 权重。

设计里 embedding 是**随包**的：打包时 `models/` 会进安装包，用户不该
在第一次提问时才等下载。但这 95MB 不该进版本库——每次 clone 都为一份
二进制付时间，而它又不是代码。

所以：权重放 `models/`（gitignore），克隆后跑一次这个脚本；打包前确认
目录在。

    uv run python scripts/fetch_model.py

只下两个文件：
    onnx/model.onnx   ~95 MB   fp32 导出版
    tokenizer.json    ~0.4 MB

默认走 hf-mirror（国内可达）；`--source huggingface` 换回官方源。
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "models" / "bge-small-zh-v1.5"
REPO = "Xenova/bge-small-zh-v1.5"

FILES = {
    "onnx/model.onnx": "model.onnx",
    "tokenizer.json": "tokenizer.json",
}

SOURCES = {
    "hf-mirror": "https://hf-mirror.com",
    "huggingface": "https://huggingface.co",
}


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    # hf-mirror 会挡 urllib 的默认 UA（403），换成普通浏览器的
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r  {dest.name}  {done / 1048576:.1f}/{total / 1048576:.1f} MB  {pct}%",
                          end="", flush=True)
        print()

    if total and tmp.stat().st_size != total:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{dest.name} 大小不对：{tmp.stat().st_size} != {total}")

    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 RAG embedding 权重")
    parser.add_argument("--source", choices=SOURCES, default="hf-mirror")
    parser.add_argument("--force", action="store_true", help="已存在也重下")
    args = parser.parse_args()

    base = SOURCES[args.source]
    print(f"来源：{base}   目标：{DEST}\n")

    for remote, name in FILES.items():
        dest = DEST / name
        if dest.exists() and not args.force:
            print(f"  已存在，跳过：{name}（{dest.stat().st_size / 1048576:.1f} MB）")
            continue
        url = f"{base}/{REPO}/resolve/main/{remote}"
        print(f"  下载 {remote}")
        try:
            _download(url, dest)
        except Exception as e:
            print(f"\n失败：{type(e).__name__}: {e}")
            print("换一个源试试：--source huggingface")
            return 1

    print("\n完成。目录内容：")
    for p in sorted(DEST.iterdir()):
        print(f"  {p.name:<16} {p.stat().st_size / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
