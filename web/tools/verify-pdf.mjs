#!/usr/bin/env node
/**
 * Headless check of the label detection against real PDFs.
 *
 * Uses pdf.js in Node only for the operator list (no canvas), so it runs the
 * exact same geometry code the browser app runs.
 *
 *   node tools/verify-pdf.mjs public/sample-4up.pdf /path/to/real.pdf
 */

import { readFileSync } from "node:fs";
import { basename } from "node:path";
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";

import { detectLabels } from "../src/detect.ts";
import { extractSegments } from "../src/pdfgeom.ts";

const files = process.argv.slice(2);
if (!files.length) {
  console.error("usage: node tools/verify-pdf.mjs <file.pdf> [...]");
  process.exit(2);
}

let failures = 0;
for (const path of files) {
  const doc = await pdfjs.getDocument({
    data: new Uint8Array(readFileSync(path)),
    cMapUrl: new URL("../node_modules/pdfjs-dist/cmaps/", import.meta.url).href,
    cMapPacked: true,
    standardFontDataUrl: new URL("../node_modules/pdfjs-dist/standard_fonts/", import.meta.url).href,
  }).promise;

  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const width = page.view[2] - page.view[0];
    const height = page.view[3] - page.view[1];
    const ops = await page.getOperatorList();
    const segments = extractSegments(ops, height, pdfjs.OPS);
    const boxes = detectLabels(segments, { width, height }, 1);
    console.log(`${basename(path)} p${i}: ${boxes.length} label(s), ${segments.length} segments`);
    for (const [n, box] of boxes.entries()) {
      const w = ((box.x1 - box.x0) * 25.4) / 72;
      const h = ((box.y1 - box.y0) * 25.4) / 72;
      console.log(`  #${n + 1} ${w.toFixed(1)} x ${h.toFixed(1)} mm (${box.source})`);
      if (w < 85 || w > 105 || h < 125 || h > 145) failures += 1;
    }
  }
}
process.exit(failures ? 1 : 0);
