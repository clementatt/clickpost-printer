import { test } from "node:test";
import assert from "node:assert/strict";

import { mgmtFrame } from "./ble.ts";

test("management frames match the captured device replies", () => {
  // read device name, captured over BLE: 1F 79 00 86
  assert.equal(Buffer.from(mgmtFrame(0x79)).toString("hex"), "1f790086");
  // set darkness to 9 (device value), captured: 1F 43 01 09 B2
  assert.equal(Buffer.from(mgmtFrame(0x43, Uint8Array.of(0x09))).toString("hex"), "1f430109b2");
});

test("status query frame", () => {
  assert.equal(Buffer.from(mgmtFrame(0x70)).toString("hex"), "1f70008f");
});
