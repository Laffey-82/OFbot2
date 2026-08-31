"""文本转图片工具（Pillow 可选依赖）：用于长消息/帮助的图片化展示。"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/PingFang.ttc",
]


def _find_font() -> str | None:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def render_text_image(
    text: str,
    out_dir: str | Path,
    *,
    title: str = "",
    width: int = 900,
    font_size: int = 24,
    padding: int = 24,
) -> Path:
    """把文本渲染为 PNG 图片并返回路径；Pillow 缺失时抛出 ImportError。"""
    from PIL import Image, ImageDraw, ImageFont

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    font_path = _find_font()
    font = (
        ImageFont.truetype(font_path, font_size)
        if font_path
        else ImageFont.load_default()
    )
    max_chars = max(10, int(width / max(1, font_size * 1.0)))
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        lines.extend(textwrap.wrap(raw, width=max_chars) or [""])
    line_height = int(font_size * 1.6)
    title_height = int(font_size * 2.2) if title else 0
    height = padding * 2 + len(lines) * line_height + title_height
    image = Image.new("RGB", (width, max(120, height)), "#ffffff")
    draw = ImageDraw.Draw(image)
    y = padding
    if title:
        title_font = (
            ImageFont.truetype(font_path, int(font_size * 1.3))
            if font_path
            else font
        )
        draw.text((padding, y), title, fill="#111111", font=title_font)
        y += title_height
    for line in lines:
        draw.text((padding, y), line, fill="#111111", font=font)
        y += line_height
    path = out_dir / f"text_{int(time.time() * 1000)}.png"
    image.save(path, "PNG")
    return path


class TextImageService:
    def __init__(self, out_dir: str | Path) -> None:
        self.out_dir = Path(out_dir)

    def render(self, text: str, **kwargs) -> Path:
        return render_text_image(text, self.out_dir, **kwargs)
