#!/usr/bin/env node
/**
 * Copy the pdf.js runtime resources (CMaps + standard fonts) into public/.
 * They are build inputs from node_modules, not source: keeping them out of git
 * keeps the repository small and guarantees they match the installed pdfjs.
 */

import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = join(root, "node_modules", "pdfjs-dist");
const dest = join(root, "public");

for (const dir of ["cmaps", "standard_fonts"]) {
  const from = join(src, dir);
  if (!existsSync(from)) {
    console.error(`missing ${from} - run npm install first`);
    process.exit(1);
  }
  mkdirSync(dest, { recursive: true });
  cpSync(from, join(dest, dir), { recursive: true });
  console.log(`copied ${dir} -> public/${dir}`);
}
