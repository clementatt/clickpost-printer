"""Find the ClickPost label region inside the printed page.

A ClickPost label is A6 (105 x 148 mm) printed on an A4 sheet with cut marks.
The label itself is the postage: it must be reproduced unmodified, so this
module only *locates* the region -- it never edits the artwork.

Detection order:
  1. the page already is label-sized (some services emit A6 directly)
  2. the L-shaped cut marks, i.e. a vertical line starting at the top edge and
     a horizontal line starting at the left edge (this is what OPRO emits)
  3. the registered A6 geometry anchored at the top-left corner
  4. the ink bounding box of the page
"""

from __future__ import annotations

from dataclasses import dataclass

try:  # PyMuPDF >= 1.24 renamed the module
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

__all__ = ["LabelBox", "detect_label_box", "content_box", "MM_PER_PT", "A6_MM"]

MM_PER_PT = 25.4 / 72.0
A6_MM = (105.0, 148.0)  # ClickPost label stock


def mm(v_pt: float) -> float:
    return v_pt * MM_PER_PT


def pt(v_mm: float) -> float:
    return v_mm / MM_PER_PT


@dataclass(frozen=True)
class LabelBox:
    """A crop rectangle in PDF points (top-left origin, y downwards)."""

    x0: float
    y0: float
    x1: float
    y1: float
    source: str = "unknown"

    @property
    def width_pt(self) -> float:
        return self.x1 - self.x0

    @property
    def height_pt(self) -> float:
        return self.y1 - self.y0

    @property
    def width_mm(self) -> float:
        return mm(self.width_pt)

    @property
    def height_mm(self) -> float:
        return mm(self.height_pt)

    @property
    def aspect(self) -> float:
        return self.width_pt / self.height_pt

    @property
    def rect(self) -> "fitz.Rect":
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    def describe(self) -> str:
        return (f"{self.width_mm:.1f} x {self.height_mm:.1f} mm "
                f"(source: {self.source})")


def union(a: "fitz.Rect | None", b: "fitz.Rect") -> "fitz.Rect":
    """Bounding box union.

    PyMuPDF treats zero-width/height rects (single lines) as empty and skips
    them in ``|`` / ``include_rect``, which silently drops every cut mark and
    every rule of a stroked frame -- so do the min/max by hand.
    """
    b = fitz.Rect(b)
    if a is None:
        return b
    return fitz.Rect(min(a.x0, b.x0), min(a.y0, b.y0),
                     max(a.x1, b.x1), max(a.y1, b.y1))


def _lines(page) -> tuple[list, list]:
    """Axis-aligned line drawings, split into verticals and horizontals."""
    w, h = page.rect.width, page.rect.height
    vert, horz = [], []
    for drawing in page.get_drawings():
        r = drawing.get("rect")
        if r is None:
            continue
        if r.width <= 2.0 and r.height >= 0.25 * h:
            vert.append(r)
        elif r.height <= 2.0 and r.width >= 0.25 * w:
            horz.append(r)
    return vert, horz


def _plausible(box: LabelBox, tolerance: float = 0.18) -> bool:
    want = A6_MM[0] / A6_MM[1]
    return (
        55.0 <= box.width_mm <= 145.0
        and 85.0 <= box.height_mm <= 225.0
        and abs(box.aspect - want) <= tolerance * want
    )


def _ink_bbox(page) -> "fitz.Rect | None":
    box = None
    for b in page.get_text("blocks"):
        box = union(box, fitz.Rect(b[:4]))
    for img in page.get_image_info():
        box = union(box, fitz.Rect(img["bbox"]))
    for d in page.get_drawings():
        box = union(box, d["rect"])
    return box


def detect_label_box(page, *, debug: list[str] | None = None) -> LabelBox:
    """Return the label region of ``page`` (PDF points)."""
    W, H = page.rect.width, page.rect.height
    notes = debug if debug is not None else []

    notes.append(f"page {mm(W):.1f} x {mm(H):.1f} mm ({W:.1f} x {H:.1f} pt)")

    # 1. page already is an A6 label
    if abs(mm(W) - A6_MM[0]) < 10 and abs(mm(H) - A6_MM[1]) < 10:
        return LabelBox(0, 0, W, H, "page-is-label")

    # 2. L-shaped cut marks
    vert, horz = _lines(page)
    top_marks = [r for r in vert if abs(r.y0) < 1.5]
    left_marks = [r for r in horz if abs(r.x0) < 1.5]
    notes.append(f"vertical cut candidates: {[f'{r.x0:.1f}' for r in vert]}")
    notes.append(f"horizontal cut candidates: {[f'{r.y0:.1f}' for r in horz]}")
    for v in sorted(top_marks, key=lambda r: -r.height):
        for h in sorted(left_marks, key=lambda r: -r.width):
            cand = LabelBox(0.0, 0.0, v.x0, h.y0, "cut-marks")
            if _plausible(cand):
                notes.append(f"cut marks give {cand.width_pt:.1f} x "
                             f"{cand.height_pt:.1f} pt")
                return cand

    # 3. A6 anchored at the top-left corner
    fallback = LabelBox(0.0, 0.0, min(pt(A6_MM[0]), W), min(pt(A6_MM[1]), H),
                        "a6-default")
    if _plausible(fallback):
        notes.append("no usable cut marks -> registered A6 geometry")
        return fallback

    # 4. ink bounding box
    ink = _ink_bbox(page)
    if ink is not None and ink.width > 1 and ink.height > 1:
        cand = LabelBox(ink.x0, ink.y0, ink.x1, ink.y1, "ink-bbox")
        notes.append(f"ink bbox {cand.describe()}")
        return cand

    return LabelBox(0.0, 0.0, W, H, "whole-page")


_CUT_ANNOTATIONS = ("切り取る", "切取", "切りはなし")


def _is_cut_text(text: str) -> bool:
    flat = text.replace("\u3000", "").replace(" ", "")
    return any(marker in flat for marker in _CUT_ANNOTATIONS)


def _is_long_rule(rect, page_rect) -> bool:
    """Long, thin, page-spanning rules are either the label frame or cut marks."""
    long_v = rect.width <= 3.0 and rect.height >= 0.20 * page_rect.height
    long_h = rect.height <= 3.0 and rect.width >= 0.20 * page_rect.width
    return long_v or long_h


def _touches_edge(rect, bounds: LabelBox, tol: float = 2.0) -> bool:
    """Cut marks start on the paper edge; the label frame does not."""
    return (
        abs(rect.x0 - bounds.x0) < tol
        or abs(rect.x1 - bounds.x1) < tol
        or abs(rect.y0 - bounds.y0) < tol
        or abs(rect.y1 - bounds.y1) < tol
    )


def label_frame(page, bounds: LabelBox) -> "fitz.Rect | None":
    """The printed frame of the label, if the sheet draws one."""
    frame = None
    for drawing in page.get_drawings():
        r = drawing["rect"]
        if not _is_long_rule(r, page.rect) or _touches_edge(r, bounds):
            continue
        frame = union(frame, r)
    if frame is None or frame.width < pt(20) or frame.height < pt(20):
        return None
    return frame


def content_box(page, bounds: LabelBox, *, margin_mm: float = 1.0) -> LabelBox:
    """Shrink ``bounds`` onto the printed artwork (drops the cut marks).

    The A6 sheet has ~6 mm of margin plus ``(切り取る)`` annotations around the
    real label frame; on a 76 mm label that margin costs legibility.  When the
    sheet draws a frame we keep the frame plus a small margin, otherwise we fall
    back to the full cut-line area.  The artwork itself is never modified.
    """
    frame = label_frame(page, bounds)
    ink = fitz.Rect(frame) if frame is not None else fitz.Rect(bounds.rect)

    def keep(r) -> None:
        nonlocal ink
        ink = union(ink, r)

    for block in page.get_text("dict")["blocks"]:
        text = ("".join(span["text"] for line in block["lines"]
                        for span in block["lines"][0].get("spans", []))
                if block["type"] == 0 else "")
        if block["type"] == 0:
            text = "".join(span["text"] for line in block["lines"]
                           for span in line["spans"])
        if _is_cut_text(text):
            continue
        keep(block["bbox"])
    for img in page.get_image_info():
        keep(img["bbox"])
    for drawing in page.get_drawings():
        r = drawing["rect"]
        if _is_long_rule(r, page.rect) and _touches_edge(r, bounds):
            continue
        keep(r)

    pad = pt(margin_mm)
    ink = fitz.Rect(ink.x0 - pad, ink.y0 - pad, ink.x1 + pad, ink.y1 + pad)
    if frame is not None:
        # everything outside the frame is sheet furniture (cut marks, icons)
        allowed = fitz.Rect(frame.x0 - pad, frame.y0 - pad,
                            frame.x1 + pad, frame.y1 + pad)
        ink &= allowed
    clipped = ink & bounds.rect  # plain intersection
    if clipped.is_empty or clipped.width < pt(20) or clipped.height < pt(20):
        return bounds
    return LabelBox(clipped.x0, clipped.y0, clipped.x1, clipped.y1, "content")
