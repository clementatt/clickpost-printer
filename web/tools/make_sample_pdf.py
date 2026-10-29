#!/usr/bin/env python3
"""Generate a synthetic ClickPost-shaped sheet for the web demo and the tests.

The demo sheet contains no real data: ASCII placeholders only, and the
"barcode"/"QR" areas are decorative blocks.  Geometry mirrors the sheets the
Japan Post site emits: A4, 2 x 2 A6 labels, cut marks running to the paper
edge, each label framed with a 16 pt inset.

    python tools/make_sample_pdf.py public/sample-4up.pdf --up 4
    python tools/make_sample_pdf.py public/sample-1up.pdf --up 1
"""

from __future__ import annotations

import argparse

import pymupdf as fitz

A4 = (595.0, 842.0)
A6 = (297.0, 418.5)


def bars(page, x, y, w, h, seed=1, unit=2.0):
    """Decorative 1D barcode."""
    rng = seed
    pos = x
    while pos < x + w:
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        width = unit if (rng >> 16) % 3 else unit * 2
        if (rng >> 8) % 2:
            page.draw_rect(fitz.Rect(pos, y, min(pos + width, x + w), y + h), color=None, fill=(0, 0, 0))
        pos += width + unit


def qr(page, x, y, size, seed=7, cells=21):
    """Decorative 2D code."""
    step = size / cells
    rng = seed
    page.draw_rect(fitz.Rect(x, y, x + size, y + size), color=(0, 0, 0), width=1.2)
    for row in range(cells):
        for col in range(cells):
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            if (rng >> 13) % 2:
                page.draw_rect(
                    fitz.Rect(x + col * step, y + row * step,
                              x + (col + 1) * step, y + (row + 1) * step),
                    color=None, fill=(0, 0, 0),
                )


def draw_label(page, ox, oy, tracking: str, serial: str, dark_title: bool = True):
    """One A6 ClickPost-like label at (ox, oy)."""
    w, h = A6
    # the real sheets draw the frame as four separate rules, not a rect path
    x0, y0, x1, y1 = ox + 16, oy + 16, ox + w - 16, oy + h - 16
    for a, b in (((x0, y0), (x0, y1)), ((x1, y0), (x1, y1)),
                 ((x0, y0), (x1, y0)), ((x0, y1), (x1, y1))):
        page.draw_line(a, b, width=2)
    if dark_title:
        page.draw_rect(fitz.Rect(ox + 18, oy + 66, ox + w - 18, oy + 100),
                       color=None, fill=(0, 0, 0))
        page.insert_text((ox + 30, oy + 92), "CLICKPOST", fontsize=20, color=(1, 1, 1))
    page.insert_text((ox + 40, oy + 55), "90- 10- 41", fontsize=22)
    bars(page, ox + 190, oy + 30, 70, 34, seed=3)

    # お届け先
    page.draw_rect(fitz.Rect(ox + 26, oy + 110, ox + w - 26, oy + 205), width=1.5)
    page.insert_text((ox + 40, oy + 130), "100-0001", fontsize=11)
    page.insert_text((ox + 40, oy + 146), "TOKYO CHIYODA-KU MARUNOUCHI 1-1-1", fontsize=9)
    page.insert_text((ox + 120, oy + 186), "SAMPLE CORP. SAMA", fontsize=11)

    # tracking barcode + number
    bars(page, ox + 30, oy + 215, 190, 34, seed=11)
    page.insert_text((ox + 36, oy + 262), f"a {tracking} a", fontsize=11)
    page.insert_text((ox + 70, oy + 276), "(postage paid)", fontsize=8)
    qr(page, ox + 210, oy + 212, 56, seed=17)

    # 内容品
    page.draw_rect(fitz.Rect(ox + 26, oy + 286, ox + w - 26, oy + 302), width=1.2)
    page.insert_text((ox + 32, oy + 298), "CONTENTS: SIM CARD", fontsize=8)

    # ご依頼主
    page.draw_rect(fitz.Rect(ox + 26, oy + 308, ox + w - 26, oy + 352), width=1.2)
    page.insert_text((ox + 40, oy + 322), "160-0023", fontsize=9)
    page.insert_text((ox + 40, oy + 334), "TOKYO TAITO-KU YANAGIBASHI 1-16-3 5F", fontsize=8)
    page.insert_text((ox + 130, oy + 348), "Sender Inc.", fontsize=9)

    page.insert_text((ox + 30, oy + 368), "This label is valid until 2026-11-05.", fontsize=7)
    page.insert_text((ox + 30, oy + 380), "Demo sheet: no real recipient data.", fontsize=7)
    page.insert_text((ox + 30, oy + 392), f"serial {serial}", fontsize=7)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--up", type=int, default=4, choices=(1, 4))
    args = ap.parse_args()

    doc = fitz.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    if args.up == 4:
        cx, cy = A4[0] / 2, A4[1] / 2
        page.draw_line((cx, 0), (cx, A4[1]), width=1.5)
        page.draw_line((0, cy), (A4[0], cy), width=1.5)
        n = 0
        for oy in (0, cy):
            for ox in (0, cx):
                n += 1
                draw_label(page, ox, oy, f"6288368{95780 + n}", f"{n}")
    else:
        page.draw_line((A6[0], 0), (A6[0], A6[1]), width=1.5)
        page.draw_line((0, A6[1]), (A6[0], A6[1]), width=1.5)
        draw_label(page, 0, 0, "628836800001", "1")

    doc.save(args.output, deflate=True)
    doc.close()
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
