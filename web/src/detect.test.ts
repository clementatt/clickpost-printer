import { test } from "node:test";
import assert from "node:assert/strict";

import { cutGridPositions, detectLabels, frameOf, type Box } from "./detect.ts";
import type { Segment } from "./pdfgeom.ts";

const PAGE = { width: 595, height: 842 };

const line = (x0: number, y0: number, x1: number, y1: number): Segment => ({ x0, y0, x1, y1 });

/** Four rules forming the printed frame of a label. */
function frame(x0: number, y0: number, x1: number, y1: number): Segment[] {
  return [line(x0, y0, x0, y1), line(x1, y0, x1, y1), line(x0, y0, x1, y0), line(x0, y1, x1, y1)];
}

function content(ox: number, oy: number): Segment[] {
  // a few short rules so the cell is not mistaken for blank paper
  return [
    line(ox + 30, oy + 120, ox + 200, oy + 120),
    line(ox + 30, oy + 200, ox + 220, oy + 200),
    line(ox + 30, oy + 300, ox + 120, oy + 300),
    line(ox + 40, oy + 124, ox + 40, oy + 190),
  ];
}

function fourUp(): Segment[] {
  return [
    line(297, 0, 297, 842), // vertical cut, full height
    line(0, 421, 595, 421), // horizontal cut, full width
    ...frame(16, 16, 281, 405),
    ...content(0, 0),
    ...frame(313, 16, 578, 405),
    ...content(297, 0),
    ...frame(16, 437, 281, 826),
    ...content(0, 421),
    ...frame(313, 437, 578, 826),
    ...content(297, 421),
  ];
}

test("cut marks give the 2x2 grid", () => {
  const { xs, ys } = cutGridPositions(fourUp(), PAGE);
  assert.deepEqual(xs, [0, 297, 595]);
  assert.deepEqual(ys, [0, 421, 842]);
});

test("frame rules are not mistaken for cut marks", () => {
  const onlyFrames = fourUp().filter((s) => !(s.y0 === 0 || s.x0 === 0) || s.x1 - s.x0 > 500);
  const { xs } = cutGridPositions(onlyFrames, PAGE);
  assert.equal(xs.length, 2, "page edges only");
});

test("2x2 sheet yields four labels in reading order", () => {
  const boxes = detectLabels(fourUp(), PAGE);
  assert.equal(boxes.length, 4);
  for (const box of boxes) {
    const w = ((box.x1 - box.x0) * 25.4) / 72;
    const h = ((box.y1 - box.y0) * 25.4) / 72;
    assert.ok(w > 85 && w < 105, `width ${w.toFixed(1)}`);
    assert.ok(h > 125 && h < 145, `height ${h.toFixed(1)}`);
  }
  assert.ok(boxes[0].x0 < boxes[1].x0);
  assert.ok(boxes[0].y0 < boxes[2].y0);
});

test("blank quadrant is dropped", () => {
  const segs = fourUp().filter(
    (s) => !(Math.min(s.x0, s.x1) > 300 && Math.min(s.y0, s.y1) > 430),
  );
  const boxes = detectLabels(segs, PAGE);
  assert.equal(boxes.length, 3);
});

test("single A6 label on an A4 sheet", () => {
  const segs = [
    line(297, 0, 297, 419),
    line(0, 418.5, 297, 418.5),
    ...frame(16, 16, 281, 403),
    ...content(0, 0),
  ];
  const boxes = detectLabels(segs, PAGE);
  assert.equal(boxes.length, 1);
  assert.ok(boxes[0].x1 <= 297.1);
  assert.ok(boxes[0].x0 > 5, "trimmed onto the frame");
});

test("no cut marks falls back to a top-left A6 area", () => {
  const segs = [...frame(16, 16, 281, 403), ...content(0, 0)];
  const boxes = detectLabels(segs, PAGE);
  assert.equal(boxes.length, 1);
  assert.equal(boxes[0].source, "grid");
});

test("frameOf finds the printed frame and ignores inner rules", () => {
  const cell: Box = { x0: 0, y0: 0, x1: 297, y1: 419, source: "grid" };
  const segs = [...frame(16, 16, 281, 403), ...content(0, 0)];
  const found = frameOf(segs, cell, PAGE);
  assert.ok(found);
  assert.equal(Math.round(found.x0), 16);
  assert.equal(Math.round(found.y1), 403);
});
