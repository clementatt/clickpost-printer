"""Canvas composition tests."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from dzpost.layout import Canvas, compose  # noqa: E402
from dzpost.raster import to_bilevel  # noqa: E402


class TestCanvas(unittest.TestCase):
    def test_dp305p_geometry(self):
        c = Canvas()
        self.assertEqual(c.width_dots, 898)  # 76 mm @ 300 dpi
        self.assertEqual(c.height_dots, 1535)  # 130 mm @ 300 dpi
        self.assertEqual(c.auto_offset, 32)  # byte-aligned centring on the head

    def test_custom_stock(self):
        c = Canvas(width_mm=57, height_mm=40, dpi=203)
        self.assertEqual(c.width_dots, round(57 * 203 / 25.4))


class TestCompose(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas()
        self.content = Image.new("L", (100, 200), 255)

    def test_contain_fits_both(self):
        out = compose(self.content, self.canvas, fit="contain")
        self.assertEqual(out.size, (960, 1535))
        self.assertEqual(out.getpixel((0, 0)), 255)

    def test_content_is_pasted_at_head_offset(self):
        img = Image.new("L", (200, 100), 0)  # black block
        out = compose(img, self.canvas, fit="none")
        x = self.canvas.auto_offset
        self.assertEqual(out.getpixel((x - 1, 0)), 255)  # margin stays white
        self.assertEqual(out.getpixel((x, 0)), 0)  # block starts at the offset
        self.assertEqual(out.getpixel((x + 199, 0)), 0)

    def test_width_fit(self):
        img = Image.new("L", (100, 400), 128)
        out = compose(img, self.canvas, fit="width")
        self.assertEqual(out.size[0], 960)

    def test_bad_offset_raises(self):
        with self.assertRaises(ValueError):
            compose(self.content, self.canvas, x_offset=900)

    def test_vertical_centre(self):
        img = Image.new("L", (898, 100), 0)
        top = compose(img, self.canvas, v_align="top")
        mid = compose(img, self.canvas, v_align="center")
        self.assertEqual(top.getpixel((100, 0)), 0)
        self.assertEqual(mid.getpixel((100, 0)), 255)
        y0 = (self.canvas.height_dots - 100) // 2
        self.assertEqual(mid.getpixel((100, y0)), 0)
        self.assertEqual(mid.getpixel((100, y0 - 1)), 255)


class TestRaster(unittest.TestCase):
    def test_threshold(self):
        img = Image.new("L", (4, 1))
        img.putpixel((0, 0), 0)
        img.putpixel((1, 0), 127)
        img.putpixel((2, 0), 128)
        img.putpixel((3, 0), 255)
        out = to_bilevel(img, 128).convert("L")
        self.assertEqual([out.getpixel((i, 0)) for i in range(4)], [0, 0, 255, 255])


if __name__ == "__main__":
    unittest.main()
