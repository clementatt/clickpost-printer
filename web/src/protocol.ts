// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Derived from dz-print <https://github.com/sb-child/dz-print> (MPL-2.0)
// via src/dzpost/protocol.py.  Only this file is under MPL-2.0; the rest of
// this project stays MIT.

/**
 * DeTong DP-series label printer command stream.
 *
 * Port of the Python encoder in `src/dzpost/protocol.py`; byte-for-byte the
 * same output.  Frame layout (USB and BLE share it):
 *
 *   <group> <type> <varbytes(len)> <payload...> <checksum>
 *
 * Print commands are emitted raw: 1b 40 reset, 1b 4a feed, 1f 2a row,
 * 1f 2b indented row, 1f 2e repeat, 0c form feed.
 */

export const DPI = 300;
export const PRINT_HEAD_DOTS = 960; // DP305P: 81.28 mm at 300 dpi

export const PAPER = {
  ticket: 0x00,
  adhesive: 0x02,
  card: 0x03,
  transparent: 0x04,
} as const;

export type PaperType = keyof typeof PAPER;

/** 1 = black dot. Rows are top to bottom, each `width` entries. */
export interface Bitmap {
  width: number;
  rows: Uint8Array[];
}

export function varbytes(n: number): number[] {
  if (n < 0) throw new Error(`varbytes(${n})`);
  if (n < 192) return [n];
  if (n < 16384) return [0xc0 | (n >> 8), n & 0xff];
  throw new Error(`payload too long: ${n}`);
}

export function mgmt(group: number, type: number, payload: Uint8Array = new Uint8Array()): number[] {
  const body = [group, type, ...varbytes(payload.length), ...payload];
  let sum = 0;
  for (let i = 1; i < body.length; i++) sum += body[i];
  return [...body, ~sum & 0xff];
}

function pushBits(out: number[], row: Uint8Array, start: number, stop: number): void {
  const n = Math.ceil((stop - start) / 8);
  const bits = new Uint8Array(n);
  for (let i = start; i < stop; i++) {
    if (row[i]) bits[(i - start) >> 3] |= 1 << (7 - ((i - start) & 7));
  }
  out.push(...bits);
}

export function imageToCommands(bitmap: Bitmap): Uint8Array {
  const { width, rows } = bitmap;
  const out: number[] = [];
  let prev: Uint8Array | null = null;
  let empty = 0;
  let repeat = 0;

  const flushEmpty = () => {
    while (empty > 0) {
      const n = Math.min(empty, 255);
      out.push(0x1b, 0x4a, n);
      empty -= n;
    }
  };
  const flushRepeat = () => {
    while (repeat > 0) {
      const n = Math.min(repeat, 192);
      out.push(0x1f, 0x2e, n - 1);
      repeat -= n;
    }
  };

  for (const row of rows) {
    let first = -1;
    let last = -1;
    for (let x = 0; x < width; x++) {
      if (row[x]) {
        if (first < 0) first = x;
        last = x;
      }
    }
    if (first < 0) {
      flushRepeat();
      empty += 1;
      prev = null;
      continue;
    }
    flushEmpty();
    if (prev && prev.length === row.length && prev.every((v, i) => v === row[i])) {
      repeat += 1;
      continue;
    }
    flushRepeat();
    prev = Uint8Array.from(row);

    const m = first >> 3;
    if (m > 0 && m <= 191) {
      const n = Math.ceil((last + 1 - m * 8) / 8);
      if (n <= 191) {
        out.push(0x1f, 0x2b, m, n);
        pushBits(out, row, m * 8, last + 1);
        continue;
      }
    }
    const dots = last + 1 - first;
    out.push(0x1f, 0x2a, dots & 0xff, (dots >> 8) & 0xff);
    pushBits(out, row, first, last + 1);
  }
  flushRepeat();
  flushEmpty();
  return Uint8Array.from(out);
}

export interface StreamOptions {
  paper?: PaperType;
  darkness?: number; // device value, 0-based
  speed?: number; // device value, 0-based
}

export function buildStream(bitmap: Bitmap, opts: StreamOptions = {}): Uint8Array {
  const body: number[] = [0x1b, 0x40];
  body.push(...mgmt(0x1f, 0x42, Uint8Array.of(PAPER[opts.paper ?? "adhesive"])));
  if (opts.darkness !== undefined) body.push(...mgmt(0x1f, 0x43, Uint8Array.of(opts.darkness & 0xff)));
  if (opts.speed !== undefined) body.push(...mgmt(0x1f, 0x44, Uint8Array.of(opts.speed & 0xff)));
  body.push(...mgmt(0x1f, 0x80, Uint8Array.of(0x7f))); // unlock commands > 0x80
  body.push(...imageToCommands(bitmap));
  body.push(0x0c); // form feed
  return Uint8Array.from(body);
}
