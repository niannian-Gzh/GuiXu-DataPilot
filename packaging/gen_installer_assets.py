"""生成安装器自绘位图资源。

所有位图按 2 倍尺寸生成，运行时由 Inno 的 TBitmapImage 拉伸到逻辑尺寸，
在 100% / 200% DPI 下都保持清晰，150% 下只有细线略粗。
"""

from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
MARK = ROOT / "archive" / "brand" / "guixu-mark-1024.png"

SURFACE = (11, 12, 12)        # #0b0c0c 内容区
BRAND = (26, 25, 23)          # #1a1917 左栏
TITLE = (22, 21, 19)          # #161513 标题栏
INK = (242, 241, 238)
BLUE = (61, 125, 255)
LINE = (51, 50, 47)
GRID = (34, 33, 31)
PATH_BG = (7, 7, 6)
CHECK_BORDER = (74, 73, 71)
CHECK_FILL = (17, 26, 41)
CHECK_MARK = (107, 157, 255)


def save(im: Image.Image, name: str) -> None:
    im.save(BASE / name, "BMP")
    print(f"{name}: {im.size[0]}x{im.size[1]}")


def paste_mark(canvas: Image.Image, box: tuple[int, int, int, int]) -> None:
    mark = Image.open(MARK).convert("RGBA")
    x, y, w, h = box
    scaled = mark.resize((w, h), Image.LANCZOS)
    canvas.paste(scaled, (x, y), scaled)


def brand_background() -> None:
    im = Image.new("RGB", (484, 964), BRAND)
    draw = ImageDraw.Draw(im)
    for x in range(0, 484, 48):
        draw.line([(x, 0), (x, 963)], fill=GRID, width=2)
    for y in range(0, 964, 48):
        draw.line([(0, y), (483, y)], fill=GRID, width=2)
    paste_mark(im, (48, 68, 124, 124))
    save(im, "installer-brand-bg.bmp")


def title_logo() -> None:
    im = Image.new("RGB", (30, 30), TITLE)
    paste_mark(im, (0, 0, 30, 30))
    save(im, "installer-logo.bmp")


def checkbox(on: bool) -> None:
    im = Image.new("RGB", (28, 28), SURFACE)
    draw = ImageDraw.Draw(im)
    if on:
        draw.rounded_rectangle([1, 1, 26, 26], radius=6, fill=CHECK_FILL, outline=BLUE, width=2)
        draw.line([(8, 15), (12, 19), (20, 9)], fill=CHECK_MARK, width=3, joint="curve")
        save(im, "installer-check-on.bmp")
    else:
        draw.rounded_rectangle([1, 1, 26, 26], radius=6, outline=CHECK_BORDER, width=2)
        save(im, "installer-check-off.bmp")


def folder_icon() -> None:
    im = Image.new("RGB", (28, 28), PATH_BG)
    draw = ImageDraw.Draw(im)
    draw.line(
        [(3, 9), (3, 22), (25, 22), (25, 11), (12, 11), (10, 9), (3, 9)],
        fill=(106, 105, 101),
        width=2,
        joint="curve",
    )
    save(im, "installer-folder.bmp")


def path_background() -> None:
    im = Image.new("RGB", (924, 84), SURFACE)
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle([1, 1, 922, 82], radius=16, fill=PATH_BG, outline=LINE, width=2)
    save(im, "installer-path-bg.bmp")


def buttons() -> None:
    im = Image.new("RGB", (200, 68), SURFACE)
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle([0, 0, 199, 67], radius=14, fill=BLUE)
    save(im, "installer-btn-primary.bmp")

    im = Image.new("RGB", (124, 68), SURFACE)
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle([1, 1, 122, 66], radius=14, fill=SURFACE, outline=LINE, width=2)
    save(im, "installer-btn-ghost.bmp")

    im = Image.new("RGB", (92, 48), PATH_BG)
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle([1, 1, 90, 46], radius=10, outline=LINE, width=2)
    save(im, "installer-btn-change.bmp")


def main() -> None:
    brand_background()
    title_logo()
    checkbox(False)
    checkbox(True)
    folder_icon()
    path_background()
    buttons()


if __name__ == "__main__":
    main()
