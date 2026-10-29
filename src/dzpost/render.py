"""Rasterise a PDF label region at printer resolution.

The label is rendered at ``supersample`` times the target resolution and then
downsampled with Lanczos, which keeps small Japanese glyphs (6-8 pt) far more
legible than a direct 300 dpi render before binarisation.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from .pdfbox import LabelBox

__all__ = ["RenderedLabel", "render_label", "MM_PER_PT"]

MM_PER_PT = 25.4 / 72.0


@dataclass
class RenderedLabel:
    image: Image.Image  # grayscale, at the requested dot resolution
    scale: float  # dots per PDF point of the source
    width_px: int
    height_px: int
    supersample: int

    @property
    def dpi_effective(self) -> float:
        return self.scale * 72.0


def render_label(
    pdf_path: str,
    box: LabelBox,
    *,
    width_px: int,
    page_index: int = 0,
    supersample: int = 2,
) -> RenderedLabel:
    """Render ``box`` of a PDF page so its width is ``width_px`` dots."""
    if width_px <= 0:
        raise ValueError("width_px must be positive")
    if supersample < 1:
        raise ValueError("supersample must be >= 1")

    doc = fitz.open(pdf_path)
    try:
        if not 0 <= page_index < doc.page_count:
            raise ValueError(f"page {page_index} out of range "
                             f"(document has {doc.page_count})")
        page = doc[page_index]
        scale = width_px / box.width_pt  # dots per source point
        zoom = scale * supersample
        pix = page.get_pixmap(
            matrix=fitz.Matrix(zoom, zoom),
            clip=box.rect,
            colorspace=fitz.csGRAY,
            alpha=False,
        )
        big = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()

    height_px = max(1, round(box.height_pt * scale))
    image = big.resize((width_px, height_px), Image.LANCZOS) if big.size != (width_px, height_px) else big
    return RenderedLabel(image, scale, width_px, height_px, supersample)
