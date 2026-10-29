/**
 * Printable job log, for reconciling what was printed when.
 *
 * The label artwork itself is a raster in the PDF, so the tracking number is
 * not available as text (pdf.js finds no text layer on Japan Post's sheets).
 * We fall back to the tracking number the ClickPost site puts in the file name
 * — for a 4-up sheet all four labels share it, so the log records the row
 * order instead: labels print top-to-bottom / left-to-right, the same order as
 * the まとめ申込 CSV, so the two can be zipped later.
 */

export interface PrintLogEntry {
  at: string; // ISO 8601, local time with offset
  file: string;
  page: number; // 1-based
  label: number; // 1-based, reading order
  tracking: string | null;
  widthMm: number;
  heightMm: number;
  bytes: number;
  sha256: string;
  status: string;
}

export const CSV_COLUMNS = [
  "日時",
  "ファイル",
  "ページ",
  "ラベル#",
  "追跡番号",
  "幅mm",
  "高さmm",
  "バイト数",
  "sha256",
  "状態",
] as const;

/** ClickPost names its downloads after the tracking number (12 digits). */
export function guessTracking(fileName: string): string | null {
  const match = fileName.replace(/\.pdf$/i, "").match(/\d{12}/);
  return match ? match[0] : null;
}

export function nowStamp(date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const offsetMin = -date.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const offset = `${sign}${pad(Math.floor(Math.abs(offsetMin) / 60))}:${pad(Math.abs(offsetMin) % 60)}`;
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${offset}`
  );
}

function escape(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function toCsv(entries: PrintLogEntry[]): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const e of entries) {
    lines.push(
      [
        e.at,
        e.file,
        String(e.page),
        String(e.label),
        e.tracking ?? "",
        e.widthMm.toFixed(1),
        e.heightMm.toFixed(1),
        String(e.bytes),
        e.sha256,
        e.status,
      ]
        .map(escape)
        .join(","),
    );
  }
  return `${lines.join("\r\n")}\r\n`;
}

export function toJson(entries: PrintLogEntry[]): string {
  return `${JSON.stringify(entries, null, 2)}\n`;
}

export async function sha256Short(data: Uint8Array, take = 16): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data as unknown as BufferSource);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, take);
}
