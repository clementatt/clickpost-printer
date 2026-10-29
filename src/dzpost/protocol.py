"""DeTong DP-series label printer command stream.

Everything here was reverse-engineered against a DeTong DP305P
(``3533:5C32``, 300 dpi, 960-dot head) and is byte-compatible with the
reference implementation in ``dz-print`` (MIT).

Two layers of framing exist on the wire:

1. management command frame (queries, paper type, darkness, speed ...)::

       <group:u8> <type:u8> <varbytes(data_len)> <data...> <checksum:u8>

   ``checksum = (~sum(frame[1:])) & 0xFF`` (0x88 when checksumming is disabled).

2. print commands, which are emitted raw with no length/checksum wrapper::

       1b 40               reset, start of a label
       1b 4a <n>           feed n blank lines
       1f 2a <nL> <nH> <d> print one row of ``nL | nH << 8`` dots
       1f 2b <m> <n> <d>   print one row, ``m`` bytes of leading zero dots
       1f 2e <k>           repeat the previous row ``k + 1`` times
       0c                  form feed, commit the label

The same byte stream is used on USB (HID interrupt OUT, endpoint 0x02 of
interface 1) and on BLE (GATT ``ff02``).  The *only* difference is that USB
wraps every HID report with ``1e <varbytes(payload_len)>`` -- ``0x1e`` is the
HID report id advertised in the device's report descriptor.  See
:func:`usb_reports`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

from PIL import Image

__all__ = [
    "varbytes",
    "mgmt",
    "image_to_commands",
    "build_stream",
    "usb_reports",
    "PRINT_HEAD_DOTS",
    "DPI",
]

DPI = 300
PRINT_HEAD_DOTS = 960  # DP305P: 81.28 mm at 300 dpi

# paper types (command 1f 42)
PAPER_TICKET = 0x00
PAPER_ADHESIVE = 0x02
PAPER_CARD = 0x03
PAPER_TRANSPARENT = 0x04


def varbytes(n: int) -> bytes:
    """Variable length integer used by the management command header."""
    if 0 <= n < 192:
        return bytes([n])
    if 192 <= n < 16384:
        return bytes([0xC0 | (n >> 8), n & 0xFF])
    raise ValueError(f"payload too long for varbytes: {n}")


def mgmt(group: int, typ: int, payload: bytes = b"") -> bytes:
    """A management command frame: group/type/varbytes/payload/checksum."""
    body = bytes([group, typ]) + varbytes(len(payload)) + bytes(payload)
    return body + bytes([(~sum(body[1:])) & 0xFF])


def _row_bits(row: list[int] | bytes, start: int, stop: int) -> bytes:
    """Pack ``row[start:stop]`` (0/1 per dot, 1 = black) into MSB-first bytes."""
    n = (stop - start + 7) // 8
    bits = bytearray(n)
    for i in range(start, stop):
        if row[i]:
            bits[(i - start) >> 3] |= 1 << (7 - ((i - start) & 7))
    return bytes(bits)


def image_to_commands(im: Image.Image) -> bytes:
    """Encode a 1-bit/grayscale image (already at device resolution) as print commands.

    Blank rows become ``1b 4a`` feed commands, runs of identical rows become
    ``1f 2e`` repeats, and rows with a wide leading margin use the compressed
    ``1f 2b`` form.  This mirrors ``dz-print/src/image_proc/cmd_parser.rs``.
    """
    im = im.convert("1", dither=Image.Dither.NONE)
    w, h = im.size
    px = im.load()
    out = bytearray()

    prev: bytes | None = None
    empty = 0
    repeat = 0

    def flush_empty() -> None:
        nonlocal empty
        while empty > 0:
            out.extend((0x1B, 0x4A, min(empty, 255)))
            empty -= min(empty, 255)

    def flush_repeat() -> None:
        nonlocal repeat
        while repeat > 0:
            n = min(repeat, 192)
            out.extend((0x1F, 0x2E, n - 1))
            repeat -= n

    for y in range(h):
        row = [1 if px[x, y] == 0 else 0 for x in range(w)]
        if not any(row):
            flush_repeat()
            empty += 1
            prev = bytes(w)
            continue
        flush_empty()
        packed = bytes(row)
        if prev is not None and packed == prev:
            repeat += 1
            continue
        flush_repeat()
        prev = packed
        first = row.index(1)
        last = w - 1 - row[::-1].index(1)
        m = first // 8
        if m > 0 and m <= 191:
            n = (last + 1 - m * 8 + 7) // 8
            if n <= 191:
                out.extend((0x1F, 0x2B, m, n))
                out.extend(_row_bits(row, m * 8, last + 1))
                continue
        n = (last + 1 - first + 7) // 8
        out.extend((0x1F, 0x2A, (last + 1 - first) & 0xFF, (last + 1 - first) >> 8))
        out.extend(_row_bits(row, first, last + 1))

    flush_repeat()
    flush_empty()
    return bytes(out)


def build_stream(
    im: Image.Image,
    *,
    paper_type: int = PAPER_ADHESIVE,
    darkness: int | None = None,
    speed: int | None = None,
    activate: bool = True,
) -> bytes:
    """Full print job: settings + row commands + form feed.

    ``darkness`` and ``speed`` are the *device* values (0-based); the CLI takes
    1-based user values and subtracts one, matching the stock app.
    """
    body = bytearray()
    body += bytes([0x1B, 0x40])  # reset / start label
    body += mgmt(0x1F, 0x42, bytes([paper_type]))
    if darkness is not None:
        body += mgmt(0x1F, 0x43, bytes([darkness & 0xFF]))
    if speed is not None:
        body += mgmt(0x1F, 0x44, bytes([speed & 0xFF]))
    if activate:
        body += mgmt(0x1F, 0x80, b"\x7f")  # unlock commands > 0x80
    body += image_to_commands(im)
    body += bytes([0x0C])  # form feed
    return bytes(body)


def usb_reports(stream: bytes, payload: int = 62) -> Iterator[bytes]:
    """Split a command stream into USB HID reports (``1e <len> <data>``).

    62 bytes of payload per 64-byte report: the device's report descriptor
    declares report id 0x1e and a 64-byte report including that id.
    """
    for off in range(0, len(stream), payload):
        chunk = stream[off:off + payload]
        yield b"\x1e" + varbytes(len(chunk)) + chunk
