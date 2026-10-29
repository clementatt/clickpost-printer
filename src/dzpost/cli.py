"""Command line interface: ``python -m dzpost`` / ``dzpost``."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from . import __version__
from .decode import decode_stream
from .layout import Canvas, compose
from .pdfbox import LabelBox, content_box, detect_label_box, detect_label_boxes, MM_PER_PT
from .protocol import (
    DPI,
    PAPER_ADHESIVE,
    PAPER_CARD,
    PAPER_TICKET,
    PAPER_TRANSPARENT,
    PRINT_HEAD_DOTS,
    build_stream,
)
from .raster import coverage, to_bilevel
from .render import render_label

PAPER_TYPES = {
    "adhesive": PAPER_ADHESIVE,
    "ticket": PAPER_TICKET,
    "card": PAPER_CARD,
    "transparent": PAPER_TRANSPARENT,
}


@dataclass
class Job:
    index: int
    box: LabelBox
    canvas: Canvas
    gray: object  # PIL.Image.Image composed on the head canvas
    bilevel: object
    stream: bytes

    @property
    def label_dots(self) -> tuple[int, int]:
        """Size of the pasted content (dots), not the head canvas."""
        from PIL import ImageOps
        bbox = ImageOps.invert(self.bilevel.convert("L")).getbbox()
        if not bbox:
            return (0, 0)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _parse_crop(text: str) -> tuple[float, float, float, float]:
    parts = [p for p in text.replace(",", " ").split() if p]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x0,y0,x1,y1 in mm")
    values = tuple(float(p) for p in parts)
    if values[2] <= values[0] or values[3] <= values[1]:
        raise argparse.ArgumentTypeError("crop needs x1 > x0 and y1 > y0")
    return values  # type: ignore[return-value]


def _label_boxes(args) -> tuple[list[LabelBox], list[str], tuple[float, float]]:
    """Detect (or take from --crop) every label on the page, then trim."""
    doc = fitz.open(args.pdf)
    try:
        if not 0 <= args.page < doc.page_count:
            raise SystemExit(f"page {args.page} does not exist "
                             f"(document has {doc.page_count} page(s))")
        page = doc[args.page]
        notes: list[str] = []
        page_size = (page.rect.width * MM_PER_PT, page.rect.height * MM_PER_PT)
        if args.crop:
            x0, y0, x1, y1 = args.crop
            boxes = [LabelBox(x0 / MM_PER_PT, y0 / MM_PER_PT, x1 / MM_PER_PT,
                              y1 / MM_PER_PT, "manual")]
        else:
            boxes = detect_label_boxes(page, debug=notes)
            if args.trim == "ink":
                boxes = [content_box(page, b, margin_mm=args.margin_mm) for b in boxes]
    finally:
        doc.close()
    return boxes, notes, page_size


def _make_job(args, box: LabelBox, index: int) -> Job:
    canvas = Canvas(width_mm=args.width_mm, height_mm=args.height_mm,
                    dpi=args.dpi, head_dots=args.head_dots)
    rendered = render_label(args.pdf, box, width_px=canvas.width_dots,
                            page_index=args.page, supersample=args.supersample)
    x_offset = None if args.x_offset == "auto" else int(args.x_offset)
    gray = compose(rendered.image, canvas, fit=args.fit, x_offset=x_offset,
                   v_align=args.v_align)
    bilevel = to_bilevel(gray, args.threshold)
    stream = build_stream(
        bilevel,
        paper_type=PAPER_TYPES[args.paper],
        darkness=args.darkness - 1 if args.darkness else None,
        speed=args.speed - 1 if args.speed else None,
    )
    return Job(index, box, canvas, gray, bilevel, stream)


def _jobs(args) -> tuple[list[Job], list[LabelBox], list[str]]:
    boxes, notes, _ = _label_boxes(args)
    if args.labels == "all":
        chosen = list(enumerate(boxes))
    else:
        if not 0 <= args.index < len(boxes):
            raise SystemExit(f"--index {args.index} out of range "
                             f"(sheet has {len(boxes)} label(s))")
        chosen = [(args.index, boxes[args.index])]
    return [_make_job(args, box, idx) for idx, box in chosen], boxes, notes


def _report(job: Job) -> None:
    c = job.canvas
    print(f"label #{job.index + 1:<2d}: {job.box.describe()}")
    print(f"  canvas     : {c.width_dots} x {c.height_dots} dots "
          f"({c.width_mm:g} x {c.height_mm:g} mm @ {c.dpi} dpi, "
          f"{c.head_dots}-dot head, x offset {c.auto_offset})")
    print(f"  content    : {job.label_dots[0]} x {job.label_dots[1]} dots "
          f"(scale {100 / (job.box.width_mm / c.width_mm):.0f}% of source)")
    print(f"  ink        : {coverage(job.bilevel) * 100:.1f} %")
    print(f"  stream     : {len(job.stream)} bytes, "
          f"sha256 {hashlib.sha256(job.stream).hexdigest()[:16]}, "
          f"BLE ~{len(job.stream) / 4900:.1f}s")


def _stamp(path: Path, index: int) -> Path:
    return path.with_name(f"{path.stem}-{index + 1}{path.suffix}")


def _write_outputs(jobs: list[Job], args) -> None:
    many = len(jobs) > 1
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        for job in jobs:
            target = _stamp(out, job.index) if many else out
            (job.bilevel if args.bitmap else job.gray).save(target)
            print(f"  preview    : {target}")
    if args.stream:
        out = Path(args.stream)
        out.parent.mkdir(parents=True, exist_ok=True)
        if many:
            # one stream per label; each is self-contained (1b 40 ... 0c)
            for job in jobs:
                target = _stamp(out, job.index)
                target.write_bytes(job.stream)
                print(f"  stream     : {target} ({len(job.stream)} bytes)")
        else:
            out.write_bytes(jobs[0].stream)
            print(f"  stream     : {out} ({len(jobs[0].stream)} bytes)")


def cmd_info(args) -> int:
    jobs, boxes, notes = _jobs(args)
    if args.verbose:
        for line in notes:
            print(f"  {line}", file=sys.stderr)
    if len(boxes) > 1:
        print(f"detected {len(boxes)} label(s) on this sheet")
    for job in jobs:
        _report(job)
    return 0


def cmd_render(args) -> int:
    jobs, boxes, notes = _jobs(args)
    if args.verbose:
        for line in notes:
            print(f"  {line}", file=sys.stderr)
    if len(boxes) > 1:
        print(f"detected {len(boxes)} label(s) on this sheet")
    for job in jobs:
        _report(job)
    _write_outputs(jobs, args)
    return 0


async def _print_ble(jobs: list[Job], args) -> int:
    from .ble import BlePrinter

    printer = BlePrinter(name_hints=tuple(args.device) if args.device
                         else ("dp305", "dp27", "detong", "dt20"))
    await printer.connect()
    try:
        print(f"connected    : {printer.device_name} (MTU {printer.mtu})")
        failures = 0
        for n, job in enumerate(jobs, start=1):
            status = await printer.query(0x70)
            if status:
                print(f"[{n}/{len(jobs)}] status 0x{status[3]:02X}")
            t0 = time.monotonic()
            await printer.send(job.stream, window=args.window)
            dt = time.monotonic() - t0
            code = await printer.wait_idle(timeout=args.timeout)
            ok = code in (None, 0x00)
            failures += 0 if ok else 1
            print(f"[{n}/{len(jobs)}] sent {len(job.stream)} bytes in {dt:.1f}s, "
                  f"status 0x{code:02X}" if code is not None else
                  f"[{n}/{len(jobs)}] sent {len(job.stream)} bytes in {dt:.1f}s")
            if n < len(jobs):
                await asyncio.sleep(args.gap)
        return 0 if failures == 0 else 1
    finally:
        await printer.disconnect()


def _print_usb(jobs: list[Job], args) -> int:
    from .usb import UsbPrinter

    printer = UsbPrinter()
    try:
        for n, job in enumerate(jobs, start=1):
            dt = printer.send(job.stream)
            print(f"[{n}/{len(jobs)}] sent {len(job.stream)} bytes in {dt:.2f}s")
            if n < len(jobs):
                time.sleep(args.gap)
        return 0
    finally:
        printer.close()


def cmd_print(args) -> int:
    jobs, boxes, _ = _jobs(args)
    if len(boxes) > 1 and args.labels != "all":
        print(f"note: this sheet has {len(boxes)} labels; printing #{args.index + 1} "
              f"only (use --all for the whole batch)", file=sys.stderr)
    for job in jobs:
        _report(job)
    if args.dry_run:
        out = Path(args.dry_run)
        out.parent.mkdir(parents=True, exist_ok=True)
        if len(jobs) == 1:
            out.write_bytes(jobs[0].stream)
            print(f"dry-run      : wrote {len(jobs[0].stream)} bytes to {out}")
        else:
            for job in jobs:
                target = _stamp(out, job.index)
                target.write_bytes(job.stream)
                print(f"dry-run      : wrote {len(job.stream)} bytes to {target}")
        return 0
    if args.transport == "ble":
        return asyncio.run(_print_ble(jobs, args))
    return _print_usb(jobs, args)


def cmd_scan(args) -> int:
    from .ble import BlePrinter

    devices = asyncio.run(BlePrinter.scan(args.timeout))
    for name, address in devices:
        print(f"  {name:24s} {address}")
    if not devices:
        print("  (no BLE devices found)")
    return 0


def cmd_verify(args) -> int:
    data = Path(args.stream_file).read_bytes()
    dec = decode_stream(data)
    print(f"bytes        : {len(data)}")
    print(f"rows         : {len(dec.lines)} printed + {dec.feeds} fed = "
          f"{dec.total_rows} dot rows")
    print(f"form feeds   : {dec.form_feeds}, resets: {dec.resets}, "
          f"repeat cmds: {dec.repeat_commands}")
    print(f"settings     : {[(hex(t), d.hex()) for _, t, d in dec.mgmt]}")
    if dec.bad_checksums:
        print(f"CHECKSUMS    : {len(dec.bad_checksums)} BAD")
        return 1
    print("checksums    : ok")
    return 0


def _csv_common(sp) -> None:
    sp.add_argument("file", help="CSV file (Shift-JIS or UTF-8)")


def cmd_csv_validate(args) -> int:
    from .clickpost_csv import read_csv, validate

    rows = read_csv(args.file)
    errors = validate(rows)
    print(f"rows         : {len(rows)}")
    if errors:
        print(f"errors       : {len(errors)}")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("validation   : ok")
    return 0


def cmd_csv_build(args) -> int:
    from .clickpost_csv import build_csv, load_json, read_csv, validate

    if args.input.lower().endswith(".json"):
        rows = load_json(args.input)
    else:
        rows = read_csv(args.input)
    errors = validate(rows)
    if errors:
        print("invalid rows:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        if not args.force:
            return 1
    out = build_csv(rows, args.output, check=not args.force)
    print(f"wrote        : {out} ({len(rows)} row(s), Shift-JIS / CRLF)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dzpost",
        description="Print Japan Post ClickPost labels on a DeTong DP-series "
                    "thermal printer, and build ClickPost batch CSVs.")
    p.add_argument("--version", action="version", version=f"dzpost {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, *, output: bool):
        sp.add_argument("pdf", help="ClickPost PDF exported from Japan Post")
        sp.add_argument("--page", type=int, default=0, help="page index (default 0)")
        sp.add_argument("--crop", type=_parse_crop, metavar="X0,Y0,X1,Y1",
                        help="override the detected region, in mm from the page's "
                             "top-left corner")
        sp.add_argument("--width-mm", type=float, default=76.0,
                        help="label stock width (default 76)")
        sp.add_argument("--height-mm", type=float, default=130.0,
                        help="label stock height (default 130)")
        sp.add_argument("--dpi", type=int, default=DPI, help="printer resolution")
        sp.add_argument("--head-dots", type=int, default=PRINT_HEAD_DOTS,
                        help="print head width in dots (DP305P: 960)")
        sp.add_argument("--trim", choices=("ink", "none"), default="ink",
                        help="'ink' crops the A6 cut marks away and keeps only "
                             "the printed label frame (default); 'none' keeps "
                             "the whole A6 area")
        sp.add_argument("--margin-mm", type=float, default=1.0,
                        help="margin kept around the artwork when --trim ink")
        sp.add_argument("--fit", choices=("contain", "width", "height", "none"),
                        default="contain")
        sp.add_argument("--x-offset", default="auto",
                        help="'auto' centres on the head, or a dot offset")
        sp.add_argument("--v-align", choices=("top", "center"), default="top")
        sp.add_argument("--threshold", type=int, default=128,
                        help="binarisation threshold 0-255 (default 128)")
        sp.add_argument("--supersample", type=int, default=2,
                        help="render scale multiplier before downsampling")
        sp.add_argument("--paper", choices=tuple(PAPER_TYPES), default="adhesive")
        sp.add_argument("--darkness", type=int, default=10,
                        help="1-based darkness, 1..15 (device value = N-1)")
        sp.add_argument("--speed", type=int, default=3,
                        help="1-based speed, 1..5 (device value = N-1)")
        sp.add_argument("--labels", choices=("first", "all"), default="first",
                        help="'all' handles every label on the sheet "
                             "(まとめ申込 4-up PDFs), default 'first'")
        sp.add_argument("--index", type=int, default=0,
                        help="which detected label to use with --labels first")
        sp.add_argument("-v", "--verbose", action="store_true")
        if output:
            sp.add_argument("-o", "--output", help="preview PNG path")
            sp.add_argument("--bitmap", action="store_true",
                            help="save the 1-bit image instead of grayscale")
            sp.add_argument("--stream", help="also write the raw command stream")

    sp = sub.add_parser("info", help="show how the PDF would be cropped")
    common(sp, output=False)
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("render", help="render a preview and/or command stream")
    common(sp, output=True)
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("print", help="render and send to the printer")
    common(sp, output=True)
    sp.add_argument("--transport", choices=("ble", "usb"), default="ble")
    sp.add_argument("--device", action="append",
                    help="BLE name substring to look for (repeatable)")
    sp.add_argument("--window", type=int, default=8,
                    help="BLE credit window (8 measured fastest)")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.add_argument("--gap", type=float, default=2.0,
                    help="seconds between labels in a batch")
    sp.add_argument("--dry-run", metavar="FILE",
                    help="write the command stream instead of printing")
    sp.set_defaults(func=cmd_print)

    sp = sub.add_parser("scan", help="list nearby BLE devices")
    sp.add_argument("--timeout", type=float, default=8.0)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("verify", help="decode a command stream and check it")
    sp.add_argument("stream_file")
    sp.set_defaults(func=cmd_verify)

    csvp = sub.add_parser("csv", help="ClickPost まとめ申込 CSV tools")
    csvsub = csvp.add_subparsers(dest="csv_command", required=True)
    sp = csvsub.add_parser("validate", help="check a CSV against the official rules")
    _csv_common(sp)
    sp.set_defaults(func=cmd_csv_validate)

    sp = csvsub.add_parser("build", help="build a Shift-JIS CSV from JSON / UTF-8 CSV")
    sp.add_argument("input", help="input .json or .csv")
    sp.add_argument("-o", "--output", required=True, help="output CSV (Shift-JIS)")
    sp.add_argument("--force", action="store_true", help="write even if invalid")
    sp.set_defaults(func=cmd_csv_build)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
