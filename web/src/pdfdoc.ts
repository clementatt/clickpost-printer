/** PDF loading, label detection (vector based) and device-resolution rendering. */

import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { detectLabels, type Box } from "./detect.ts";
import { extractSegments, type OpsMap } from "./pdfgeom.ts";
import type { Bitmap as DotBitmap } from "./protocol.ts";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export interface PageAnalysis {
  pageIndex: number;
  widthPt: number;
  heightPt: number;
  boxes: Box[];
}

/** Optional CJK resources; without them some embedded fonts fall back. */
function assetBase(): string {
  const base = new URL(".", document.baseURI).href;
  return base;
}

export async function openPdf(data: ArrayBuffer): Promise<PDFDocumentProxy> {
  const base = assetBase();
  return pdfjs.getDocument({
    data,
    isEvalSupported: false,
    cMapUrl: `${base}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${base}standard_fonts/`,
  }).promise;
}

export async function analysePage(page: PDFPageProxy, marginMm = 1): Promise<PageAnalysis> {
  const widthPt = page.view[2] - page.view[0];
  const heightPt = page.view[3] - page.view[1];
  const ops = await page.getOperatorList();
  const segments = extractSegments(
    { fnArray: ops.fnArray as unknown as number[], argsArray: ops.argsArray },
    heightPt,
    pdfjs.OPS as unknown as OpsMap,
  );
  const boxes = detectLabels(segments, { width: widthPt, height: heightPt }, marginMm);
  return { pageIndex: page.pageNumber - 1, widthPt, heightPt, boxes };
}

export async function analyseDocument(doc: PDFDocumentProxy, marginMm = 1): Promise<PageAnalysis[]> {
  const out: PageAnalysis[] = [];
  for (let i = 1; i <= doc.numPages; i++) {
    out.push(await analysePage(await doc.getPage(i), marginMm));
  }
  return out;
}

function binFromCanvas(canvas: HTMLCanvasElement, thresholdValue = 128): DotBitmap {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("canvas 2d context unavailable");
  const { width, height } = canvas;
  const data = ctx.getImageData(0, 0, width, height).data;
  const rows: Uint8Array[] = [];
  for (let y = 0; y < height; y++) {
    const row = new Uint8Array(width);
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      row[x] = luma < thresholdValue ? 1 : 0;
    }
    rows.push(row);
  }
  return { width, rows };
}

/**
 * Render one label region at printer resolution.
 *
 * Drawn `supersample` times larger and then downscaled, which keeps 6–8 pt
 * Japanese glyphs legible after binarisation.
 */
export async function renderLabel(
  page: PDFPageProxy,
  box: Box,
  targetWidth: number,
  supersample = 2,
): Promise<DotBitmap> {
  const widthPt = box.x1 - box.x0;
  const heightPt = box.y1 - box.y0;
  const scale = (targetWidth * supersample) / widthPt;
  const full = document.createElement("canvas");
  full.width = Math.round(widthPt * scale);
  full.height = Math.round(heightPt * scale);
  const ctx = full.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("canvas 2d context unavailable");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, full.width, full.height);

  await page.render({
    canvasContext: ctx,
    viewport: page.getViewport({ scale }),
    transform: [1, 0, 0, 1, -box.x0 * scale, -box.y0 * scale],
  }).promise;

  const outW = targetWidth;
  const outH = Math.max(1, Math.round((heightPt / widthPt) * targetWidth));
  const out = document.createElement("canvas");
  out.width = outW;
  out.height = outH;
  const octx = out.getContext("2d", { willReadFrequently: true });
  if (!octx) throw new Error("canvas 2d context unavailable");
  octx.imageSmoothingEnabled = true;
  octx.imageSmoothingQuality = "high";
  octx.fillStyle = "#fff";
  octx.fillRect(0, 0, outW, outH);
  octx.drawImage(full, 0, 0, outW, outH);
  return binFromCanvas(out);
}

/** Paste the label onto the 960-dot head canvas, centred like the device does. */
export function composeOnHead(
  label: DotBitmap,
  headDots: number,
  heightDots: number,
  offsetDots: number,
): DotBitmap {
  const rows: Uint8Array[] = [];
  for (let y = 0; y < heightDots; y++) {
    const row = new Uint8Array(headDots);
    const src = label.rows[y];
    if (src) row.set(src.subarray(0, Math.min(src.length, headDots - offsetDots)), offsetDots);
    rows.push(row);
  }
  return { width: headDots, rows };
}

export function autoOffset(widthDots: number, headDots = 960): number {
  const raw = Math.max(0, headDots - widthDots) >> 1;
  return ((raw + 4) >> 3) << 3;
}
