"""End-to-end CLI tests: no printer required."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from dzpost.cli import main  # noqa: E402
from dzpost.decode import decode_stream  # noqa: E402

from test_pdfbox import make_sheet  # noqa: E402


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.sheet = make_sheet(self.dir / "sheet.pdf")

    def tearDown(self):
        self.tmp.cleanup()

    def test_info(self):
        code, out, _ = run(["info", str(self.sheet)])
        self.assertEqual(code, 0)
        self.assertIn("label region", out)
        self.assertIn("content", out)  # default --trim ink keeps the label frame

    def test_info_without_trim_uses_cut_box(self):
        code, out, _ = run(["info", str(self.sheet), "--trim", "none"])
        self.assertEqual(code, 0)
        self.assertIn("cut-marks", out)

    def test_render_writes_png_and_stream(self):
        png = self.dir / "preview.png"
        stream = self.dir / "label.bin"
        code, out, _ = run(["render", str(self.sheet), "-o", str(png),
                            "--stream", str(stream), "--bitmap"])
        self.assertEqual(code, 0)
        im = Image.open(png)
        self.assertEqual(im.size, (960, 1535))
        dec = decode_stream(stream.read_bytes())
        self.assertEqual(dec.form_feeds, 1)
        self.assertEqual(dec.bad_checksums, [])
        self.assertGreater(len(dec.lines), 0)

    def test_verify(self):
        stream = self.dir / "label.bin"
        run(["render", str(self.sheet), "--stream", str(stream)])
        code, out, _ = run(["verify", str(stream)])
        self.assertEqual(code, 0)
        self.assertIn("checksums    : ok", out)

    def test_manual_crop(self):
        code, out, _ = run(["info", str(self.sheet), "--crop", "0,0,105,148"])
        self.assertEqual(code, 0)
        self.assertIn("manual", out)

    def test_print_dry_run_does_not_touch_hardware(self):
        dry = self.dir / "dry.bin"
        code, out, _ = run(["print", str(self.sheet), "--dry-run", str(dry)])
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)
        self.assertTrue(dry.exists())

    def test_missing_page_is_reported(self):
        with self.assertRaises(SystemExit):
            run(["info", str(self.sheet), "--page", "5"])


if __name__ == "__main__":
    unittest.main()
