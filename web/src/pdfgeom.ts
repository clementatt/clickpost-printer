/**
 * Pull axis-aligned line segments out of a pdf.js operator list.
 *
 * Coordinates come out in page space with a top-left origin (y down), which is
 * the same convention the Python tool uses via PyMuPDF, so the geometry rules
 * below read the same in both implementations.
 */

export interface Segment {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

type Matrix = [number, number, number, number, number, number];

const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

function multiply(m: Matrix, n: Matrix): Matrix {
  return [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4],
    m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

export interface OperatorListLike {
  fnArray: number[];
  argsArray: unknown[];
}

/** OPS values from pdf.js (stable public enum). */
export interface OpsMap {
  save: number;
  restore: number;
  transform: number;
  moveTo: number;
  lineTo: number;
  curveTo: number;
  rectangle: number;
  constructPath: number;
  paintFormXObjectBegin?: number;
  paintFormXObjectEnd?: number;
}

export function extractSegments(
  ops: OperatorListLike,
  pageHeight: number,
  O: OpsMap,
): Segment[] {
  const segments: Segment[] = [];
  let ctm: Matrix = IDENTITY;
  const stack: Matrix[] = [];
  let current: { x: number; y: number } | null = null;

  const mapPoint = (x: number, y: number): { x: number; y: number } => ({
    x: ctm[0] * x + ctm[2] * y + ctm[4],
    y: pageHeight - (ctm[1] * x + ctm[3] * y + ctm[5]),
  });

  const emit = (ax: number, ay: number, bx: number, by: number): void => {
    const a = mapPoint(ax, ay);
    const b = mapPoint(bx, by);
    if (Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5) return;
    segments.push({ x0: a.x, y0: a.y, x1: b.x, y1: b.y });
  };

  const handlePath = (fns: ArrayLike<number>, args: ArrayLike<number>): void => {
    let p = 0;
    for (let k = 0; k < fns.length; k++) {
      const fn = fns[k];
      if (fn === O.moveTo) {
        current = { x: args[p], y: args[p + 1] };
        p += 2;
      } else if (fn === O.lineTo) {
        const next = { x: args[p], y: args[p + 1] };
        if (current) emit(current.x, current.y, next.x, next.y);
        current = next;
        p += 2;
      } else if (fn === O.curveTo) {
        // curves are irrelevant for cut marks; just move the pen
        current = { x: args[p + 4], y: args[p + 5] };
        p += 6;
      } else if (fn === O.rectangle) {
        const [x, y, w, h] = [args[p], args[p + 1], args[p + 2], args[p + 3]];
        p += 4;
        emit(x, y, x + w, y);
        emit(x + w, y, x + w, y + h);
        emit(x + w, y + h, x, y + h);
        emit(x, y + h, x, y);
        current = null;
      }
    }
  };

  for (let i = 0; i < ops.fnArray.length; i++) {
    const fn = ops.fnArray[i];
    const args = ops.argsArray[i] as unknown;
    if (fn === O.save) {
      stack.push(ctm);
    } else if (fn === O.restore) {
      ctm = stack.pop() ?? IDENTITY;
    } else if (fn === O.transform) {
      ctm = multiply(ctm, args as Matrix);
    } else if (fn === O.constructPath) {
      // v4: [fnArray, argsArray, minMax]; v3: [ops, args]
      const tuple = args as [ArrayLike<number>, ArrayLike<number>];
      if (Array.isArray(tuple[0]) || tuple[0] instanceof Int32Array || tuple[0] instanceof Uint32Array) {
        handlePath(tuple[0], tuple[1]);
      }
    } else if (fn === O.moveTo || fn === O.lineTo || fn === O.rectangle) {
      const a = args as number[];
      if (fn === O.rectangle) {
        handlePath([O.rectangle], a);
      } else {
        handlePath([fn], a);
      }
    }
  }
  return segments;
}
