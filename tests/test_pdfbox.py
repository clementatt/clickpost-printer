"""Label region detection tests, built on synthetic ClickPost-like sheets."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf as fitz  # noqa: E402

from dzpost.pdfbox import (  # noqa: E402
    A6_MM,
    LabelBox,
    content_box,
    detect_label_box,
    detect_label_boxes,
    label_frame,
)

A4 = (595.0, 842.0)
CUT_X, CUT_Y = 297.0, 418.5


def make_sheet(path: Path, *, cut_marks=True, frame=True, label_at=(0, 0)):
    doc = fitz.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    ox, oy = label_at
    if cut_marks:
        page.draw_line((ox + CUT_X, oy), (ox + CUT_X, oy + CUT_Y), width=1.5)
        page.draw_line((ox, oy + CUT_Y), (ox + CUT_X, oy + CUT_Y), width=1.5)
    if frame:
        x0, y0, x1, y1 = ox + 15.8, oy + 15.8, ox + 285.8, oy + 405.8
        page.draw_line((x0, y0), (x0, y1), width=2)
        page.draw_line((x1, y0), (x1, y1), width=2)
        page.draw_line((x0, y0), (x1, y0), width=2)
        page.draw_line((x0, y1), (x1, y1), width=2)
    page.insert_text((ox + 40, oy + 60), "CLICKPOST 90-10-41", fontsize=12)
    page.insert_text((ox + 40, oy + 100), "100-0001 TOKYO", fontsize=10)
    doc.save(path)
    doc.close()
    return path


class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cut_marks(self):
        sheet = make_sheet(self.dir / "sheet.pdf")
        doc = fitz.open(sheet)
        box = detect_label_box(doc[0])
        doc.close()
        self.assertEqual(box.source, "cut-marks")
        self.assertAlmostEqual(box.width_pt, CUT_X, places=1)
        self.assertAlmostEqual(box.height_pt, CUT_Y, places=1)
        self.assertAlmostEqual(box.width_mm, 104.8, delta=0.5)
        self.assertAlmostEqual(box.height_mm, 147.6, delta=0.5)
        self.assertAlmostEqual(box.aspect, 105 / 148, delta=0.01)

    def test_fallback_without_cut_marks(self):
        sheet = make_sheet(self.dir / "plain.pdf", cut_marks=False)
        doc = fitz.open(sheet)
        box = detect_label_box(doc[0])
        doc.close()
        self.assertEqual(box.source, "a6-default")
        self.assertAlmostEqual(box.width_mm, A6_MM[0], delta=0.5)
        self.assertAlmostEqual(box.height_mm, A6_MM[1], delta=0.5)

    def test_page_already_label_sized(self):
        doc = fitz.open()
        page = doc.new_page(width=297.6, height=419.5)  # A6 in points
        box = detect_label_box(page)
        doc.close()
        self.assertEqual(box.source, "page-is-label")

    def test_frame_detection(self):
        sheet = make_sheet(self.dir / "sheet.pdf")
        doc = fitz.open(sheet)
        frame = label_frame(doc[0], LabelBox(0, 0, CUT_X, CUT_Y, "cut-marks"))
        doc.close()
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(frame.x0, 15.8, places=1)
        self.assertAlmostEqual(frame.y1, 405.8, places=1)

    def test_content_box_is_tighter_than_cut_box(self):
        sheet = make_sheet(self.dir / "sheet.pdf")
        doc = fitz.open(sheet)
        page = doc[0]
        cut = detect_label_box(page)
        content = content_box(page, cut, margin_mm=1.0)
        doc.close()
        self.assertEqual(content.source, "content")
        self.assertLess(content.width_pt, cut.width_pt)
        self.assertLess(content.height_pt, cut.height_pt)
        self.assertGreater(content.width_mm, 80)
        self.assertLessEqual(content.x1, cut.x1)

    def test_content_box_without_frame_falls_back(self):
        sheet = make_sheet(self.dir / "noframe.pdf", frame=False)
        doc = fitz.open(sheet)
        page = doc[0]
        cut = detect_label_box(page)
        content = content_box(page, cut)
        doc.close()
        # no frame -> the cut box itself is the safest answer
        self.assertLessEqual(content.width_pt, cut.width_pt + 0.01)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- 4-up sheets

def make_4up_sheet(path: Path):
    """A4 sheet with four A6 labels, cut lines running to the paper edge."""
    doc = fitz.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    cx, cy = A4[0] / 2, A4[1] / 2
    page.draw_line((cx, 0), (cx, A4[1]), width=1.5)
    page.draw_line((0, cy), (A4[0], cy), width=1.5)
    for ox, oy in ((0, 0), (cx, 0), (0, cy), (cx, cy)):
        x0, y0 = ox + 15.8, oy + 15.8
        x1, y1 = ox + cx - 15.8, oy + cy - 15.8
        for a, b in (((x0, y0), (x0, y1)), ((x1, y0), (x1, y1)),
                     ((x0, y0), (x1, y0)), ((x0, y1), (x1, y1))):
            page.draw_line(a, b, width=2)
        page.insert_text((ox + 40, oy + 80), "CLICKPOST", fontsize=14)
        page.insert_text((ox + 40, oy + 120), "100-0001 TOKYO", fontsize=10)
    doc.save(path)
    doc.close()
    return path


class TestMultiLabel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_label_sheet(self):
        sheet = make_sheet(self.dir / "one.pdf")
        doc = fitz.open(sheet)
        boxes = detect_label_boxes(doc[0])
        doc.close()
        self.assertEqual(len(boxes), 1)

    def test_four_labels_on_one_sheet(self):
        sheet = make_4up_sheet(self.dir / "four.pdf")
        doc = fitz.open(sheet)
        boxes = detect_label_boxes(doc[0])
        page = doc[0]
        trimmed = [content_box(page, b) for b in boxes]
        doc.close()
        self.assertEqual(len(boxes), 4)
        for box in boxes:
            self.assertAlmostEqual(box.width_mm, 104.9, delta=1.5)
            self.assertAlmostEqual(box.height_mm, 148.5, delta=1.5)
        # reading order: row by row, left to right
        self.assertLess(boxes[0].x0, boxes[1].x0)
        self.assertAlmostEqual(boxes[0].y0, boxes[1].y0, places=1)
        self.assertLess(boxes[0].y0, boxes[2].y0)
        # every cell trims down onto its own frame
        for cut, ink in zip(boxes, trimmed):
            self.assertEqual(ink.source, "content")
            self.assertLess(ink.width_pt, cut.width_pt)
