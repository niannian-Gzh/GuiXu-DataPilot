"""从几何参数，生成归墟的全套品牌资产。

    uv run python docs/brand/build.py

**唯一真源是 `src/web/static/js/mark.js` 里那六个常数**（外加中心光点半径）。
几何改了，这里的常数跟着改，重跑一次，下面这些东西全部重来：

    guixu-mark.svg · guixu-mark-dark.svg     矢量源（深底用 / 浅底用）
    guixu-mark-{128,256,512,1024}.png        透明底 + 暖白
    guixu-mark-dark-{128,256,512,1024}.png   透明底 + 深色
    guixu-mark-tile-{460,512,1024}.png       深底 + 暖白——头像位直接用
    guixu.ico                                应用图标（7 档尺寸）

为什么走 Chromium 渲染而不是 Pillow：图标的形状靠贝塞尔曲线，小尺寸下
的抗锯齿质量就是"它还认不认得出"的分界。Chromium 的渲染器是现成的、
而且项目本来就装了（报告 PDF 用它），不引入新依赖。

小尺寸没有单独简化——实测 16px 会糊，但放射状的轮廓保住了，仍读得出
是八瓣；而 16px 只出现在小列表视图，任务栏和桌面走的是 32 / 48 / 64。
"""

import struct
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# ---- 几何：与 src/web/static/js/mark.js 必须一致 ----
N = 8           # 八瓣
R_OUT = 21.5    # 外尖
R_IN = 6.5      # 内尖：让出一圈空腔给光点
R_MID = 15.5    # 最宽处。靠外 ⇒ 读作「流进去」，不是「散出去」
C = 25          # 画布中心
D = 8.4         # 贝塞尔控制点偏移：t = .5 处正好等于半宽
CORE_R = 2.6    # 中心光点

# ---- 颜色：取自 css/app.css 的令牌 ----
INK = "#f2f1ee"    # --ink   工作台的暖白
DARK = "#161513"   # --raise 浅底上用的深色
BG = "#0c0c0b"     # --bg    工作台面色，深底版用它

SIZES = (128, 256, 512, 1024)
TILE_SIZES = (460, 512, 1024)   # 460 = GitHub 头像的最小要求
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

HERE = Path(__file__).parent

PETAL = (
    f"M{C} {C - R_OUT}"
    f" Q{C + D} {C - R_MID} {C} {C - R_IN}"
    f" Q{C - D} {C - R_MID} {C} {C - R_OUT} Z"
)


def svg(fill: str, size: int = 512) -> str:
    """八片是同一个母题的八次重复，不是八个零件——所以合成一条 <g>。"""
    petals = "".join(
        f'    <path d="{PETAL}" transform="rotate({i * 360 / N:g} {C} {C})"/>\n'
        for i in range(N)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50" '
        f'width="{size}" height="{size}" fill="none">\n'
        f'  <g fill="{fill}">\n{petals}  </g>\n'
        f'  <circle cx="{C}" cy="{C}" r="{CORE_R}" fill="{fill}"/>\n'
        "</svg>\n"
    )


def render(browser, fill: str, size: int, background: str | None) -> bytes:
    """一张图：给定填充色、边长，（可选）底色。底色为 None 就是透明底。"""
    bg = background or "transparent"
    body = svg(fill, size)
    page = browser.new_page(viewport={"width": size, "height": size})
    page.set_content(f'<body style="margin:0;background:{bg}">{body}</body>')
    shot = page.screenshot(omit_background=background is None)
    page.close()
    return shot


def pack_ico(paths: list[Path], out: Path) -> None:
    """拼 ICO：头 + 目录 + 各尺寸数据。

    Vista 以后的 ICO 允许每一档直接内嵌 PNG，所以这里不做二次缩放——
    每档用的都是 Chromium 单独渲染的那一张，16px 就是照 16px 画的。
    """
    blobs = [p.read_bytes() for p in paths]
    sizes = [int(p.stem.rsplit("_", 1)[1]) for p in paths]

    head = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for size, blob in zip(sizes, blobs):
        dim = 0 if size >= 256 else size      # 256 在目录里记作 0
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)

    out.write_bytes(head + entries + b"".join(blobs))


def main() -> None:
    # 矢量源
    (HERE / "guixu-mark.svg").write_text(svg(INK), encoding="utf-8")
    (HERE / "guixu-mark-dark.svg").write_text(svg(DARK), encoding="utf-8")

    made: list[str] = ["guixu-mark.svg", "guixu-mark-dark.svg"]
    tmp: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for size in SIZES:
            (HERE / f"guixu-mark-{size}.png").write_bytes(render(browser, INK, size, None))
            (HERE / f"guixu-mark-dark-{size}.png").write_bytes(render(browser, DARK, size, None))
            made += [f"guixu-mark-{size}.png", f"guixu-mark-dark-{size}.png"]

        for size in TILE_SIZES:
            (HERE / f"guixu-mark-tile-{size}.png").write_bytes(render(browser, INK, size, BG))
            made.append(f"guixu-mark-tile-{size}.png")

        # ICO 的各档先落到临时文件，拼完就删——它们不是产物，是零件
        for size in ICO_SIZES:
            path = HERE / f"_ico_{size}.png"
            path.write_bytes(render(browser, INK, size, BG))
            tmp.append(path)

        browser.close()

    pack_ico(tmp, HERE / "guixu.ico")
    for path in tmp:
        path.unlink()
    made.append(f"guixu.ico（{len(ICO_SIZES)} 档）")

    print(f"写出 {len(made)} 个文件到 {HERE}:")
    for name in made:
        print(f"  {name}")


if __name__ == "__main__":
    # Windows 控制台默认不是 UTF-8 代码页，中文输出会变乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
