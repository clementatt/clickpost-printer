/**
 * Label region detection from the PDF's vector content.
 *
 * A ClickPost sheet is A4 with A6 labels separated by cut marks that run to
 * the paper edge.  We take those cut marks from the page geometry, build the
 * grid they describe, drop empty cells, then shrink each cell onto its printed
 * frame (the frame is what the sheet draws around the label; everything
 * outside it — `(切り取る)` annotations, margins — is dropped).
 *
 * Vector based on purpose: the cut marks are 1.5 pt hairlines that get covered
 * by label fills in a raster, but they are perfectly visible as path segments.
 */

import type { Segment } from "./pdfgeom.ts";

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  source: "grid" | "page" | "default";
}

export interface PageSize {
  width: number;
  height: number;
}

const A6_MM = [105, 148] as const;
const MM_PER_PT = 25.4 / 72;
const EDGE_TOL = 2;
const THIN = 3;
/** A cut mark spans at least this share of the sheet. */
const LONG_RULE = 0.35;
/** A blank cell is dropped: its ink must cover this share of the cell. */
const INK_SHARE = 0.4;

export const mmPerPt = MM_PER_PT;

const toMm = (pt: number): number => pt * MM_PER_PT;

export function boxWidthMm(box: Box): number {
  return toMm(box.x1 - box.x0);
}

export function boxHeightMm(box: Box): number {
  return toMm(box.y1 - box.y0);
}

function plausible(box: Box, tolerance = 0.18): boolean {
  const w = boxWidthMm(box);
  const h = boxHeightMm(box);
  const want = A6_MM[0] / A6_MM[1];
  return w >= 55 && w <= 145 && h >= 85 && h <= 225 && Math.abs(w / h - want) <= tolerance * want;
}

const isVertical = (s: Segment): boolean => Math.abs(s.x1 - s.x0) <= THIN;
const isHorizontal = (s: Segment): boolean => Math.abs(s.y1 - s.y0) <= THIN;
const spanY = (s: Segment): number => Math.abs(s.y1 - s.y0);
const spanX = (s: Segment): number => Math.abs(s.x1 - s.x0);

function insideBox(seg: Segment, box: Box, tol = 1): boolean {
  const xs = [seg.x0, seg.x1];
  const ys = [seg.y0, seg.y1];
  return (
    Math.min(...xs) >= box.x0 - tol &&
    Math.max(...xs) <= box.x1 + tol &&
    Math.min(...ys) >= box.y0 - tol &&
    Math.max(...ys) <= box.y1 + tol
  );
}

/** x/y of the cut marks that run to the paper edge. */
export function cutGridPositions(
  segments: Segment[],
  page: PageSize,
): { xs: number[]; ys: number[] } {
  const xs = new Set<number>([0, page.width]);
  const ys = new Set<number>([0, page.height]);

  for (const seg of segments) {
    if (isVertical(seg) && spanY(seg) >= LONG_RULE * page.height) {
      const y0 = Math.min(seg.y0, seg.y1);
      const y1 = Math.max(seg.y0, seg.y1);
      if (y0 <= EDGE_TOL || y1 >= page.height - EDGE_TOL) {
        xs.add(Math.round(((seg.x0 + seg.x1) / 2) * 100) / 100);
      }
    } else if (isHorizontal(seg) && spanX(seg) >= LONG_RULE * page.width) {
      const x0 = Math.min(seg.x0, seg.x1);
      const x1 = Math.max(seg.x0, seg.x1);
      if (x0 <= EDGE_TOL || x1 >= page.width - EDGE_TOL) {
        ys.add(Math.round(((seg.y0 + seg.y1) / 2) * 100) / 100);
      }
    }
  }
  return { xs: [...xs].sort((a, b) => a - b), ys: [...ys].sort((a, b) => a - b) };
}

/** Bounding box of the printed label frame inside a cell. */
export function frameOf(
  segments: Segment[],
  cell: Box,
  page: PageSize,
): Box | null {
  let box: Box | null = null;
  const grow = (seg: Segment): void => {
    const x0 = Math.min(seg.x0, seg.x1);
    const x1 = Math.max(seg.x0, seg.x1);
    const y0 = Math.min(seg.y0, seg.y1);
    const y1 = Math.max(seg.y0, seg.y1);
    box = box
      ? { x0: Math.min(box.x0, x0), y0: Math.min(box.y0, y0), x1: Math.max(box.x1, x1), y1: Math.max(box.y1, y1), source: "grid" }
      : { x0, y0, x1, y1, source: "grid" };
  };

  for (const seg of segments) {
    if (!insideBox(seg, cell)) continue;
    const vertical = isVertical(seg) && spanY(seg) >= 0.5 * (cell.y1 - cell.y0);
    const horizontal = isHorizontal(seg) && spanX(seg) >= 0.5 * (cell.x1 - cell.x0);
    if (!vertical && !horizontal) continue;
    // a rule lying on the cell border is a cut mark, not the frame
    const onEdge =
      Math.abs(Math.min(seg.x0, seg.x1) - cell.x0) < EDGE_TOL ||
      Math.abs(Math.max(seg.x0, seg.x1) - cell.x1) < EDGE_TOL ||
      Math.abs(Math.min(seg.y0, seg.y1) - cell.y0) < EDGE_TOL ||
      Math.abs(Math.max(seg.y0, seg.y1) - cell.y1) < EDGE_TOL;
    if (onEdge) continue;
    void page;
    grow(seg);
  }
  if (!box) return null;
  const frame: Box = box;
  const wideEnough = frame.x1 - frame.x0 >= 0.3 * (cell.x1 - cell.x0);
  const tallEnough = frame.y1 - frame.y0 >= 0.3 * (cell.y1 - cell.y0);
  return wideEnough && tallEnough ? frame : null;
}

function inkCoverage(segments: Segment[], cell: Box): number {
  let box: Box | null = null;
  for (const seg of segments) {
    if (!insideBox(seg, cell)) continue;
    const x0 = Math.min(seg.x0, seg.x1);
    const x1 = Math.max(seg.x0, seg.x1);
    const y0 = Math.min(seg.y0, seg.y1);
    const y1 = Math.max(seg.y0, seg.y1);
    box = box
      ? { x0: Math.min(box.x0, x0), y0: Math.min(box.y0, y0), x1: Math.max(box.x1, x1), y1: Math.max(box.y1, y1), source: "grid" }
      : { x0, y0, x1, y1, source: "grid" };
  }
  if (!box) return 0;
  const w = (box.x1 - box.x0) / (cell.x1 - cell.x0);
  const h = (box.y1 - box.y0) / (cell.y1 - cell.y0);
  return Math.min(w, h);
}

function shrink(cell: Box, frame: Box | null, marginPt: number): Box {
  const base = frame ?? cell;
  const m = marginPt;
  const out: Box = {
    x0: Math.max(cell.x0, base.x0 - m),
    y0: Math.max(cell.y0, base.y0 - m),
    x1: Math.min(cell.x1, base.x1 + m),
    y1: Math.min(cell.y1, base.y1 + m),
    source: "grid",
  };
  return boxWidthMm(out) < 20 || boxHeightMm(out) < 20 ? cell : out;
}

/** All labels on a sheet: 1-up A4, or the 2 x 2 A6 sheet まとめ申込 emits. */
export function detectLabels(
  segments: Segment[],
  page: PageSize,
  marginMm = 1,
): Box[] {
  const marginPt = (marginMm * 72) / 25.4;
  const pageBox: Box = { x0: 0, y0: 0, x1: page.width, y1: page.height, source: "page" };
  const pageW = toMm(page.width);
  const pageH = toMm(page.height);
  if (Math.abs(pageW - A6_MM[0]) < 10 && Math.abs(pageH - A6_MM[1]) < 10) {
    return [pageBox];
  }

  const { xs, ys } = cutGridPositions(segments, page);
  const cells: Box[] = [];
  if (xs.length > 2 || ys.length > 2) {
    for (let i = 0; i < xs.length - 1; i++) {
      for (let j = 0; j < ys.length - 1; j++) {
        const cell: Box = { x0: xs[i], y0: ys[j], x1: xs[i + 1], y1: ys[j + 1], source: "grid" };
        if (!plausible(cell)) continue;
        if (inkCoverage(segments, cell) < INK_SHARE) continue; // empty quadrant
        cells.push(shrink(cell, frameOf(segments, cell, page), marginPt));
      }
    }
  }
  if (cells.length) {
    cells.sort((a, b) => Math.round(a.y0) - Math.round(b.y0) || a.x0 - b.x0);
    return cells;
  }

  const fallback: Box = {
    x0: 0,
    y0: 0,
    x1: Math.min(page.width, A6_MM[0] / MM_PER_PT),
    y1: Math.min(page.height, A6_MM[1] / MM_PER_PT),
    source: "default",
  };
  return plausible(fallback)
    ? [shrink(fallback, frameOf(segments, fallback, page), marginPt)]
    : [pageBox];
}
