import { test } from "node:test";
import assert from "node:assert/strict";

import { CSV_COLUMNS, guessTracking, nowStamp, toCsv, type PrintLogEntry } from "./printlog.ts";

const sample: PrintLogEntry = {
  at: "2026-10-29T21:00:00+09:00",
  file: "628836895783.pdf",
  page: 1,
  label: 1,
  tracking: "628836895783",
  widthMm: 99.4,
  heightMm: 140.9,
  bytes: 88853,
  sha256: "8ab3092cd73b8235",
  status: "ready (0x00)",
};

test("tracking number comes from the file name", () => {
  assert.equal(guessTracking("628836895783.pdf"), "628836895783");
  assert.equal(guessTracking("clickpost_628836895783_2.pdf"), "628836895783");
  assert.equal(guessTracking("label.pdf"), null);
});

test("timestamp keeps the local offset", () => {
  const stamp = nowStamp(new Date("2026-10-29T12:00:00Z"));
  assert.match(stamp, /^2026-10-29T\d{2}:00:00[+-]\d{2}:\d{2}$/);
});

test("csv has the documented header and one row per label", () => {
  const csv = toCsv([sample, { ...sample, label: 2, tracking: null }]);
  const lines = csv.trimEnd().split("\r\n");
  assert.equal(lines.length, 3);
  assert.deepEqual(lines[0].split(","), [...CSV_COLUMNS]);
  assert.ok(lines[1].includes("628836895783"));
  assert.ok(lines[2].includes("99.4"));
});

test("csv quotes values that contain separators", () => {
  const csv = toCsv([{ ...sample, file: 'weird,"name".pdf' }]);
  assert.ok(csv.includes('"weird,""name"".pdf"'));
});
