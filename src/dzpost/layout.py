"""Compose a rendered label onto the printer canvas.

The DP305P has a 960-dot (81.28 mm) head but the label stock is 76 mm wide, so
the artwork has to be centred on the head: the paper sits ~31 dots right of the
head's left edge (measured on the real device, rounded to a whole byte because
the compressed row command works in bytes).
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

__all__ = ["Canvas", "compose", "Fit"]

Fit = str  # "contain" | "width" | "height" | "none"


@dataclass(frozen=True)
class Canvas:
    width_mm: float = 76.0
    height_mm: float = 130.0
    dpi: int = 300
    head_dots: int = 960

    @property
    def width_dots(self) -> int:
        return round(self.width_mm * self.dpi / 25.4)

    @property
    def height_dots(self) -> int:
        return round(self.height_mm * self.dpi / 25.4)

    @property
    def auto_offset(self) -> int:
        raw = max(0, self.head_dots - self.width_dots) // 2
        return (raw + 4) // 8 * 8


def _scale_to_fit(
    size: tuple[int, int], target: tuple[int, int], fit: Fit
) -> tuple[int, int]:
    w, h = size
    tw, th = target
    if fit == "none":
        return w, h
    sx, sy = tw / w, th / h
    if fit == "width":
        s = sx
    elif fit == "height":
        s = sy
    else:  # contain
        s = min(sx, sy)
    return max(1, round(w * s)), max(1, round(h * s))


def compose(
    content: Image.Image,
    canvas: Canvas,
    *,
    fit: Fit = "contain",
    x_offset: int | None = None,
    v_align: str = "top",
) -> Image.Image:
    """Return a head-wide, label-tall grayscale canvas with ``content`` pasted."""
    target = (canvas.width_dots, canvas.height_dots)
    if fit not in {"contain", "width", "height", "none"}:
        raise ValueError(f"unknown fit mode: {fit}")

    w, h = _scale_to_fit(content.size, target, fit)
    if (w, h) != content.size:
        content = content.resize((w, h), Image.LANCZOS)

    page = Image.new("L", (canvas.head_dots, canvas.height_dots), 255)
    off = canvas.auto_offset if x_offset is None else int(x_offset)
    if off < 0 or off + w > canvas.head_dots:
        raise ValueError(
            f"x_offset {off} + content width {w} does not fit the "
            f"{canvas.head_dots}-dot head")
    y = 0 if v_align == "top" else (canvas.height_dots - h) // 2
    page.paste(content, (off, max(0, y)))
    return page


def place(content: Image.Image, canvas: Canvas, **kw) -> Image.Image:
    """Alias used by the CLI."""
    return compose(content, canvas, **kw)
