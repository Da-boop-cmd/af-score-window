"""生成 af-score 的 exe 图标：蓝底白字 AF look。

    python make_icon.py            # 产出 af-score.ico + preview.png
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = r"C:\Windows\Fonts\segoeuib.ttf"      # Segoe UI Bold
BLUE = "#0B5FD0"
WHITE = "#FFFFFF"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def _center_text(draw, box, text, font):
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = x0 + (x1 - x0 - w) / 2 - bbox[0]
    y = y0 + (y1 - y0 - h) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=WHITE)


def render(size: int) -> Image.Image:
    """按目标尺寸渲染：小的图标只放 AF，避免糊成一团。"""
    scale = 4 if size <= 64 else 2
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=BLUE)

    if size >= 32:
        _center_text(d, (0, int(s * 0.14), s, int(s * 0.62)), "AF", _font(int(s * 0.46)))
        _center_text(d, (0, int(s * 0.60), s, int(s * 0.92)), "look", _font(int(s * 0.21)))
    else:
        _center_text(d, (0, 0, s, s), "AF", _font(int(s * 0.52)))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = render(256)
    ico = os.path.join(HERE, "af-score.ico")
    big.save(ico, format="ICO", sizes=[(n, n) for n in sizes])
    big.save(os.path.join(HERE, "preview.png"), format="PNG")
    print("icon:", ico, os.path.getsize(ico), "bytes")
    print("sizes:", sizes)


if __name__ == "__main__":
    main()
