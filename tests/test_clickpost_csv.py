"""ClickPost まとめ申込 CSV rules (from the official Amazon manual)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dzpost.clickpost_csv import (  # noqa: E402
    COLUMNS,
    Recipient,
    build_csv,
    display_width,
    normalize_zip,
    read_csv,
    validate,
)


def ok_row(**over):
    base = dict(zip_code="9010241", name="株式会社サンプル商事", honorific="御中",
                address=["東京都千代田区千代田1-1"], contents="SIMカード")
    base.update(over)
    return Recipient(**base)


class TestHelpers(unittest.TestCase):
    def test_display_width(self):
        self.assertEqual(display_width("SIMカード"), 3 + 6)  # 3 half + 3 full
        self.assertEqual(display_width("株式会社サンプル商事"), 20)
        self.assertEqual(display_width("abc"), 3)

    def test_normalize_zip(self):
        self.assertEqual(normalize_zip("１００－０００１"), "100-0001")
        self.assertEqual(normalize_zip(" 100 0001 "), "1000001")

    def test_row_shape(self):
        row = ok_row()
        self.assertEqual(len(row.as_row()), len(COLUMNS))
        self.assertEqual(row.as_row()[2], "御中")


class TestValidate(unittest.TestCase):
    def test_good_row(self):
        self.assertEqual(validate([ok_row()]), [])

    def test_hyphenated_zip_ok(self):
        self.assertEqual(validate([ok_row(zip_code="100-0001")]), [])

    def test_bad_zip(self):
        errors = validate([ok_row(zip_code="901024")])
        self.assertTrue(any("郵便番号" in e for e in errors))

    def test_name_must_not_carry_honorific(self):
        errors = validate([ok_row(name="株式会社サンプル商事様")])
        self.assertTrue(any("敬称" in e for e in errors))

    def test_honorific_whitelist(self):
        errors = validate([ok_row(honorific="殿")])
        self.assertTrue(any("敬称" in e for e in errors))

    def test_address_required(self):
        errors = validate([ok_row(address=[])])
        self.assertTrue(any("住所" in e for e in errors))

    def test_address_length_limit(self):
        errors = validate([ok_row(address=["東" * 21])])  # 42 width > 40
        self.assertTrue(any("住所1行目" in e for e in errors))

    def test_contents_required_and_short(self):
        self.assertTrue(validate([ok_row(contents="")]))
        self.assertTrue(validate([ok_row(contents="あ" * 16)]))

    def test_40_row_cap(self):
        rows = [ok_row() for _ in range(41)]
        self.assertTrue(any("40" in e for e in validate(rows)))
        self.assertEqual(validate([ok_row() for _ in range(40)]), [])

    def test_non_cp932_character(self):
        errors = validate([ok_row(name="山田😀")])  # emoji is not in Shift-JIS
        self.assertTrue(any("Shift-JIS" in e for e in errors))


class TestWriteRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_is_shift_jis_crlf_with_fixed_header(self):
        path = build_csv([ok_row()], self.dir / "out.csv")
        raw = path.read_bytes()
        text = raw.decode("cp932")
        self.assertTrue(text.startswith(",".join(COLUMNS)))
        self.assertIn("\r\n", text)
        self.assertNotIn(b"\xef\xbb\xbf", raw)  # no BOM
        self.assertEqual(len(text.strip().splitlines()), 2)

    def test_roundtrip(self):
        rows = [ok_row(), ok_row(name="山田太郎", honorific="様",
                                 address=["東京都新宿区西新宿1-1-1"])]
        path = build_csv(rows, self.dir / "out.csv")
        back = read_csv(path)
        self.assertEqual(len(back), 2)
        self.assertEqual(back[1].name, "山田太郎")
        self.assertEqual(back[1].honorific, "様")

    def test_build_rejects_invalid(self):
        with self.assertRaises(ValueError):
            build_csv([ok_row(zip_code="901")], self.dir / "bad.csv")

    def test_header_mismatch(self):
        path = self.dir / "bad.csv"
        path.write_bytes("a,b\r\n1,2\r\n".encode("cp932"))
        with self.assertRaises(ValueError):
            read_csv(path)

    def test_blank_lines_ignored(self):
        path = build_csv([ok_row()], self.dir / "out.csv")
        raw = path.read_bytes() + "\r\n\r\n".encode("cp932")
        path.write_bytes(raw)
        self.assertEqual(len(read_csv(path)), 1)


if __name__ == "__main__":
    unittest.main()
