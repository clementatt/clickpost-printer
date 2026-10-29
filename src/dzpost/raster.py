"""Grayscale -> 1-bit conversion for the thermal head."""

from __future__ import annotations

from PIL import Image

__all__ = ["to_bilevel", "coverage"]


def to_bilevel(im: Image.Image, threshold: int = 128) -> Image.Image:
    """Hard threshold (no dithering): 1-bit is what the head can physically print,
    and ordered dithering makes small text and barcodes fall apart."""
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be 0..255")
    lut = [0 if v < threshold else 255 for v in range(256)]
    return im.convert("L").point(lut, "1")


def coverage(im: Image.Image) -> float:
    """Fraction of black dots in a 1-bit image."""
    im = im.convert("1")
    w, h = im.size
    if not w or not h:
        return 0.0
    black = sum(im.point(lambda v: 255 if v == 0 else 0).histogram()[255:])
    return black / (w * h)
