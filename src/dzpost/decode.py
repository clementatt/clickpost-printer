"""Independent decoder for the command stream produced by :mod:`dzpost.protocol`.

Used by the test-suite and by ``dzpost verify``: it rebuilds the dot rows so a
rendered image can be compared against what the printer is actually told to
draw -- the same trick that validated the Rust implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["DecodedStream", "decode_stream", "Row", "unpack_row"]


def unpack_row(bits: bytes) -> list[int]:
    """MSB-first unpack: byte 0 bit 7 is the leftmost dot."""
    out: list[int] = []
    for byte in bits:
        for i in range(8):
            out.append((byte >> (7 - i)) & 1)
    return out


@dataclass
class Row:
    start: int  # first dot column
    bits: bytes  # MSB-first packed dots

    @property
    def dots(self) -> int:
        return len(self.bits) * 8

    def pixels(self) -> list[int]:
        return unpack_row(self.bits)


@dataclass
class DecodedStream:
    lines: list[Row] = field(default_factory=list)  # one entry per printed dot row
    feeds: int = 0
    repeat_commands: int = 0
    mgmt: list[tuple[int, int, bytes]] = field(default_factory=list)
    form_feeds: int = 0
    resets: int = 0
    bad_checksums: list[tuple[int, int]] = field(default_factory=list)
    # ordered playback: ("feed", n) or ("row", Row), so blank and printed rows
    # can be interleaved exactly as the printer will lay them down
    events: list[tuple[str, object]] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.lines) + self.feeds

    def bitmap(self, width: int, height: int | None = None) -> list[list[int]]:
        """Reconstruct a 0/1 image (1 = dot printed) of ``width`` dot columns."""
        rows: list[list[int]] = []
        for kind, item in self.events:
            if kind == "feed":
                rows.extend([[0] * width for _ in range(int(item))])
                continue
            row = item
            line = [0] * width
            for i, v in enumerate(row.pixels()):
                col = row.start + i
                if 0 <= col < width and v:
                    line[col] = 1
            rows.append(line)
        if height is not None:
            while len(rows) < height:
                rows.append([0] * width)
            rows = rows[:height]
        return rows


def decode_stream(stream: bytes) -> DecodedStream:
    out = DecodedStream()
    i, n = 0, len(stream)
    while i < n:
        b = stream[i]
        if b == 0x1B:
            sub = stream[i + 1]
            if sub == 0x40:
                out.resets += 1
                i += 2
            elif sub == 0x4A:
                out.feeds += stream[i + 2]
                out.events.append(("feed", stream[i + 2]))
                i += 3
            else:  # pragma: no cover - not emitted by this project
                raise ValueError(f"unknown 0x1b subcommand 0x{sub:02x} at {i}")
            continue
        if b == 0x0C:
            out.form_feeds += 1
            i += 1
            continue
        if b == 0x1F:
            typ = stream[i + 1]
            if typ == 0x2A:
                dots = stream[i + 2] | (stream[i + 3] << 8)
                nb = (dots + 7) // 8
                row = Row(0, stream[i + 4:i + 4 + nb])
                out.lines.append(row)
                out.events.append(("row", row))
                i += 4 + nb
                continue
            if typ == 0x2B:
                m, cnt = stream[i + 2], stream[i + 3]
                row = Row(m * 8, stream[i + 4:i + 4 + cnt])
                out.lines.append(row)
                out.events.append(("row", row))
                i += 4 + cnt
                continue
            if typ == 0x2E:
                k = stream[i + 2] + 1
                out.repeat_commands += 1
                if not out.lines:
                    raise ValueError(f"repeat before any printed row at {i}")
                out.lines.extend([out.lines[-1]] * k)
                out.events.extend([("row", out.lines[-1])] * k)
                i += 3
                continue
            # management frame: <group> <type> <varbytes len> <data> <checksum>
            hdr = stream[i + 2]
            if hdr & 0xC0 == 0xC0:
                length = ((hdr & 0x3F) << 8) | stream[i + 3]
                nb = 2
            else:
                length = hdr
                nb = 1
            data = stream[i + 2 + nb:i + 2 + nb + length]
            cks = stream[i + 2 + nb + length]
            expected = (~sum(stream[i + 1:i + 2 + nb + length])) & 0xFF
            if cks != expected:
                out.bad_checksums.append((i, cks))
            out.mgmt.append((b, typ, data))
            i += 3 + nb + length
            continue
        raise ValueError(f"unknown command byte 0x{b:02x} at offset {i}")
    return out
