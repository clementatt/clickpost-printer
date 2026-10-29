import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { buildStream, mgmt, varbytes, type Bitmap } from "./protocol.ts";

test("varbytes matches the device framing", () => {
  assert.deepEqual(varbytes(0), [0x00]);
  assert.deepEqual(varbytes(191), [0xbf]);
  assert.deepEqual(varbytes(192), [0xc0, 0xc0]);
  assert.deepEqual(varbytes(300), [0xc1, 0x2c]);
  assert.throws(() => varbytes(16384));
});

test("mgmt checksums like the captured device replies", () => {
  // read device name, captured over BLE: 1F 79 00 86
  assert.equal(Buffer.from(mgmt(0x1f, 0x79)).toString("hex"), "1f790086");
  const frame = mgmt(0x1f, 0x43, Uint8Array.of(0x09));
  const expected =
    ~frame.slice(1, -1).reduce((a, b) => a + b, 0) & 0xff;
  assert.equal(frame[frame.length - 1], expected);
});

test("encoder output is byte-identical to the Python implementation", () => {
  const fixture = JSON.parse(
    readFileSync(new URL("./__fixtures__/parity.json", import.meta.url), "utf8"),
  ) as { width: number; height: number; rows: string[]; stream_hex: string };

  const bitmap: Bitmap = {
    width: fixture.width,
    rows: fixture.rows.map((r) => Uint8Array.from([...r], (c) => (c === "1" ? 1 : 0))),
  };
  const stream = buildStream(bitmap, { paper: "adhesive", darkness: 9, speed: 2 });
  assert.equal(Buffer.from(stream).toString("hex"), fixture.stream_hex);
});

test("blank rows become feed commands and repeated rows compress", () => {
  const width = 32;
  const blank = new Uint8Array(width);
  const line = Uint8Array.from(blank);
  line[4] = 1;
  const rows = [blank, blank, line, line, line, line, blank];
  const stream = buildStream({ width, rows }, {});
  // 2 blank rows -> 1b 4a 02, then a row, then repeat x3 -> 1f 2e 03, then feed
  const hex = Buffer.from(stream).toString("hex");
  assert.ok(hex.includes("1b4a02"), hex);
  assert.ok(hex.includes("1f2e02"), hex); // first row + 3 repeats -> k = 2
  assert.ok(hex.endsWith("0c"));
});
