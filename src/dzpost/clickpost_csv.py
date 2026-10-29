"""ClickPost 「まとめ申込」 CSV (Amazon 版) の生成・検証。

仕様（clickpost.jp/create_csv_manual_amazon.pdf）:

    A お届け先郵便番号   必須  ハイフンなし半角7桁 / ハイフンあり半角8桁
    B お届け先氏名      必須  敬称を含めない, 全角20 / 半角40 文字以内
    C お届け先敬称             「様」または「御中」
    D-G お届け先住所1〜4行目   いずれか必須, 各 全角20 / 半角40 文字以内
    H 内容品            必須  全角15 / 半角30 文字以内

    * 文字コード Shift-JIS, CSV テキスト
    * 1 アップロード 40 件まで
    * ヘッダー行は変更しない
"""

from __future__ import annotations

import csv
import io
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "COLUMNS",
    "LIMITS",
    "MAX_ROWS",
    "Recipient",
    "build_csv",
    "read_csv",
    "validate",
    "display_width",
    "normalize_zip",
    "from_json",
]

COLUMNS = [
    "お届け先郵便番号",
    "お届け先氏名",
    "お届け先敬称",
    "お届け先住所1行目",
    "お届け先住所2行目",
    "お届け先住所3行目",
    "お届け先住所4行目",
    "内容品",
]

# 全角 N 文字 = 半角 2N。幅は半角換算で数える。
LIMITS = {
    "お届け先氏名": 40,
    "お届け先住所1行目": 40,
    "お届け先住所2行目": 40,
    "お届け先住所3行目": 40,
    "お届け先住所4行目": 40,
    "内容品": 30,
}
MAX_ROWS = 40
HONORIFICS = {"様", "御中"}


def display_width(text: str) -> int:
    """半角=1 / 全角=2 で数えた表示幅。"""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _halfwidth_digits(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def normalize_zip(text: str) -> str:
    """全角→半角、空白除去。ハイフンはそのまま残す（どちらも受理される）。"""
    return _halfwidth_digits(text).replace(" ", "")


@dataclass
class Recipient:
    zip_code: str
    name: str
    honorific: str = "様"
    address: list[str] = field(default_factory=list)  # 1〜4 行目
    contents: str = ""

    def as_row(self) -> list[str]:
        addr = list(self.address) + [""] * (4 - len(self.address))
        return [normalize_zip(self.zip_code), self.name.strip(),
                self.honorific.strip(), *addr, self.contents.strip()]

    @classmethod
    def from_mapping(cls, data: dict) -> "Recipient":
        address = data.get("address")
        if address is None:
            address = [data.get(f"address{i}", "") for i in range(1, 5)]
        return cls(
            zip_code=str(data.get("zip", data.get("zip_code", ""))),
            name=data.get("name", ""),
            honorific=data.get("honorific", "様"),
            address=[a for a in address],
            contents=data.get("contents", ""),
        )


def validate(rows: list[Recipient]) -> list[str]:
    """全行を検証し、エラーメッセージのリストを返す（空なら OK）。"""
    errors: list[str] = []
    if not rows:
        return ["no rows"]
    if len(rows) > MAX_ROWS:
        errors.append(f"{len(rows)} 行あります（1 回のアップロードは {MAX_ROWS} 件まで）")

    for i, row in enumerate(rows, start=1):
        data = dict(zip(COLUMNS, row.as_row()))
        who = f"{i} 行目"
        z = data["お届け先郵便番号"]
        if not z:
            errors.append(f"{who}: 郵便番号が空です")
        elif not (len(z) == 7 and z.isdigit()) and not (
                len(z) == 8 and z[3] == "-" and z.replace("-", "").isdigit()):
            errors.append(f"{who}: 郵便番号は半角7桁（または 123-4567）: {z!r}")

        name = data["お届け先氏名"]
        if not name:
            errors.append(f"{who}: 氏名が空です")
        elif name.endswith(("様", "御中")):
            errors.append(f"{who}: 氏名に敬称が入っています（C 列に分けてください）: {name!r}")

        hon = data["お届け先敬称"]
        if not hon:
            errors.append(f"{who}: 敬称が空です（様 / 御中）")
        elif hon not in HONORIFICS:
            errors.append(f"{who}: 敬称は「様」か「御中」: {hon!r}")

        address = [data[c] for c in COLUMNS[3:7]]
        if not any(address):
            errors.append(f"{who}: 住所が全部空です")
        for col, value in zip(COLUMNS[3:7], address):
            limit = LIMITS[col]
            if display_width(value) > limit:
                errors.append(
                    f"{who}: {col} が {display_width(value)} 幅（上限 {limit}）: {value!r}")

        contents = data["内容品"]
        if not contents:
            errors.append(f"{who}: 内容品が空です")
        elif display_width(contents) > LIMITS["内容品"]:
            errors.append(f"{who}: 内容品が {display_width(contents)} 幅（上限 30）")

        for col in (COLUMNS[1], *COLUMNS[3:7], "内容品"):
            try:
                data[col].encode("cp932")
            except UnicodeEncodeError:
                errors.append(f"{who}: {col} に Shift-JIS で表せない文字: {data[col]!r}")
    return errors


def build_csv(rows: list[Recipient], path: str | Path, *, check: bool = True) -> Path:
    """Shift-JIS / CRLF の CSV を書き出す。"""
    if check:
        errors = validate(rows)
        if errors:
            raise ValueError("invalid rows:\n  " + "\n  ".join(errors))
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(row.as_row())
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf.getvalue().encode("cp932"))
    return out


def read_csv(path: str | Path) -> list[Recipient]:
    """Shift-JIS / UTF-8(BOM) のどちらでも読む。ヘッダーは照合する。"""
    raw = Path(path).read_bytes()
    for encoding in ("cp932", "utf-8-sig"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise ValueError("cannot decode CSV as Shift-JIS or UTF-8")

    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header != COLUMNS:
        raise ValueError(f"unexpected header: {header}\n"
                         f"expected: {COLUMNS}")
    rows: list[Recipient] = []
    for record in reader:
        if not any(cell.strip() for cell in record):
            continue
        record += [""] * (len(COLUMNS) - len(record))
        rows.append(Recipient(
            zip_code=record[0], name=record[1], honorific=record[2],
            address=record[3:7], contents=record[7]))
    return rows


def from_json(data) -> list[Recipient]:
    """JSON（dict のリスト、または {"recipients": [...]}）から Recipient を作る。"""
    if isinstance(data, dict):
        data = data.get("recipients", [])
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of recipients or {\"recipients\": [...]}")
    return [Recipient.from_mapping(item) for item in data]


def load_json(path: str | Path) -> list[Recipient]:
    return from_json(json.loads(Path(path).read_text(encoding="utf-8")))
