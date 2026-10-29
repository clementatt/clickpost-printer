"""Command stream encoding tests (stdlib unittest, no extra deps)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from dzpost.decode import decode_stream  # noqa: E402
from dzpost.protocol import (  # noqa: E402
    PAPER_ADHESIVE,
    build_stream,
    image_to_commands,
    mgmt,
    usb_reports,
    varbytes,
)


def blank(w=64, h=8):
    return Image.new("L", (w, h), 255)


class TestVarbytes(unittest.TestCase):
    def test_short(self):
        self.assertEqual(varbytes(0), b"\x00")
        self.assertEqual(varbytes(191), b"\xbf")

    def test_two_byte(self):
        self.assertEqual(varbytes(192), b"\xc0\xc0")
        self.assertEqual(varbytes(300), b"\xc1\x2c")
        self.assertEqual(varbytes(16383), b"\xff\xff")

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            varbytes(-1)
        with self.assertRaises(ValueError):
            varbytes(16384)


class TestMgmt(unittest.TestCase):
    def test_known_vector(self):
        # read device name, captured over BLE: 1F 79 00 86
        self.assertEqual(mgmt(0x1F, 0x79).hex(), "1f790086")

    def test_checksum_covers_type_len_payload(self):
        frame = mgmt(0x1F, 0x43, b"\x09")
        self.assertEqual(frame[-1], (~sum(frame[1:-1])) & 0xFF)

    def test_usb_reports(self):
        payload = bytes(range(150))
        reports = list(usb_reports(payload, 62))
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(r[0] == 0x1E for r in reports))
        self.assertEqual(reports[0][1], 62)
        self.assertTrue(all(len(r) == 1 + 1 + 62 for r in reports[:-1]))
        rebuilt = b"".join(r[2:] for r in reports)
        self.assertEqual(rebuilt, payload)


class TestImageCommands(unittest.TestCase):
    def test_blank_image_is_one_feed(self):
        cmds = image_to_commands(blank(64, 300))
        dec = decode_stream(cmds)
        self.assertEqual(dec.lines, [])
        self.assertEqual(dec.feeds, 300)

    def test_roundtrip_dots(self):
        im = blank(32, 6)
        px = im.load()
        for x in range(0, 32, 3):
            for y in (1, 3, 5):
                px[x, y] = 0
        dec = decode_stream(image_to_commands(im))
        rows = dec.bitmap(32, height=6)
        expect = [[1 if px[x, y] == 0 else 0 for x in range(32)] for y in range(6)]
        self.assertEqual(rows, expect)

    def test_repeat_row_compression(self):
        im = blank(32, 10)
        for x in range(4, 12):
            im.putpixel((x, 1), 0)
            for y in range(2, 9):
                im.putpixel((x, y), 0)
        cmds = image_to_commands(im)
        self.assertIn(b"\x1f\x2e", cmds)
        dec = decode_stream(cmds)
        self.assertEqual(len(dec.lines), 8)  # one printed row + 7 repeats
        self.assertEqual(dec.feeds, 2)  # blank first and last row

    def test_leading_margin_uses_compressed_command(self):
        im = blank(64, 2)
        im.putpixel((40, 0), 0)
        cmds = image_to_commands(im)
        self.assertEqual(cmds[0:2], b"\x1f\x2b")  # 1f 2b m n
        dec = decode_stream(cmds)
        self.assertEqual(dec.lines[0].start, 40 // 8 * 8)
        self.assertTrue(any(dec.lines[0].pixels()))

    def test_wide_row_beyond_byte_fit(self):
        im = blank(960, 2)
        for x in range(0, 960, 7):
            im.putpixel((x, 0), 0)
        dec = decode_stream(image_to_commands(im))
        pixels = dec.lines[0].pixels()
        self.assertEqual(len(pixels), 960)
        self.assertEqual(sum(pixels), len(range(0, 960, 7)))


class TestBuildStream(unittest.TestCase):
    def test_structure(self):
        im = blank(64, 4)
        stream = build_stream(im, paper_type=PAPER_ADHESIVE, darkness=9, speed=2)
        self.assertEqual(stream[0:2], b"\x1b\x40")
        self.assertEqual(stream[-1], 0x0C)
        dec = decode_stream(stream)
        self.assertEqual(dec.resets, 1)
        self.assertEqual(dec.form_feeds, 1)
        self.assertEqual(dec.bad_checksums, [])
        types = [t for _, t, _ in dec.mgmt]
        self.assertIn(0x42, types)  # paper type
        self.assertIn(0x43, types)  # darkness
        self.assertIn(0x44, types)  # speed
        self.assertIn(0x80, types)  # activate

    def test_optional_settings_omitted(self):
        stream = build_stream(blank(8, 1), darkness=None, speed=None)
        types = [t for _, t, _ in decode_stream(stream).mgmt]
        self.assertNotIn(0x43, types)
        self.assertNotIn(0x44, types)


class TestDecodeErrors(unittest.TestCase):
    def test_unknown_byte(self):
        with self.assertRaises(ValueError):
            decode_stream(b"\x99\x01")


if __name__ == "__main__":
    unittest.main()
