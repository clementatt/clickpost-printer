import "./style.css";

import { Printer, describeError, isSupported } from "./ble.ts";
import { analyseDocument, autoOffset, composeOnHead, openPdf, renderLabel } from "./pdfdoc.ts";
import { buildStream, DPI, PRINT_HEAD_DOTS, type Bitmap } from "./protocol.ts";
import type { Box } from "./detect.ts";
import {
  guessTracking,
  nowStamp,
  sha256Short,
  toCsv,
  toJson,
  type PrintLogEntry,
} from "./printlog.ts";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";

const LABEL_W_MM = 76;
const LABEL_H_MM = 130;
const LABEL_W_DOTS = Math.round((LABEL_W_MM * DPI) / 25.4); // 898
const LABEL_H_DOTS = Math.round((LABEL_H_MM * DPI) / 25.4); // 1535

interface LabelJob {
  page: PDFPageProxy;
  pageIndex: number;
  indexOnPage: number;
  box: Box;
  selected: boolean;
  thumb?: HTMLCanvasElement;
}

const $ = <T extends HTMLElement>(sel: string): T => {
  const el = document.querySelector(sel);
  if (!el) throw new Error(`missing element: ${sel}`);
  return el as T;
};

const state: {
  doc?: PDFDocumentProxy;
  jobs: LabelJob[];
  printer: Printer;
  busy: boolean;
  fileName: string;
  log: PrintLogEntry[];
} = { jobs: [], printer: new Printer(), busy: false, fileName: "", log: [] };

function log(message: string, kind: "info" | "error" | "ok" = "info"): void {
  const line = document.createElement("div");
  line.className = `log-line ${kind}`;
  line.textContent = message;
  $(".log").prepend(line);
}

function setBusy(busy: boolean): void {
  state.busy = busy;
  for (const btn of document.querySelectorAll<HTMLButtonElement>("button[data-busy-lock]")) {
    btn.disabled = busy;
  }
}

function drawBitmap(canvas: HTMLCanvasElement, bitmap: Bitmap, scale = 1): void {
  canvas.width = bitmap.width;
  canvas.height = bitmap.rows.length;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const img = ctx.createImageData(bitmap.width, bitmap.rows.length);
  for (let y = 0; y < bitmap.rows.length; y++) {
    const row = bitmap.rows[y];
    for (let x = 0; x < bitmap.width; x++) {
      const i = (y * bitmap.width + x) * 4;
      const on = row[x] ? 0 : 255;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = on;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  canvas.style.aspectRatio = `${canvas.width} / ${canvas.height}`;
  void scale;
}

async function onFile(file: File): Promise<void> {
  if (state.busy) return;
  setBusy(true);
  $(".log").replaceChildren();
  try {
    state.fileName = file.name;
    log(`読み込み: ${file.name}`);
    const data = await file.arrayBuffer();
    state.doc = await openPdf(data);
    log(`${state.doc.numPages} ページ`, "ok");

    const analysis = await analyseDocument(state.doc, 1);
    state.jobs = [];
    const pagesEl = $("#pages");
    pagesEl.replaceChildren();

    for (const pageInfo of analysis) {
      if (!pageInfo.boxes.length) continue;
      const page = await state.doc.getPage(pageInfo.pageIndex + 1);
      const section = document.createElement("section");
      section.className = "page";
      const heading = document.createElement("h2");
      heading.textContent =
        analysis.length > 1
          ? `ページ ${pageInfo.pageIndex + 1} — ${pageInfo.boxes.length} 枚`
          : `${pageInfo.boxes.length} 枚のラベルを検出`;
      section.append(heading);

      const grid = document.createElement("div");
      grid.className = "labels";

      for (const [i, box] of pageInfo.boxes.entries()) {
        const job: LabelJob = { page, pageIndex: pageInfo.pageIndex, indexOnPage: i, box, selected: true };
        state.jobs.push(job);

        const card = document.createElement("label");
        card.className = "card";
        const check = document.createElement("input");
        check.type = "checkbox";
        check.checked = true;
        check.addEventListener("change", () => {
          job.selected = check.checked;
          updatePrintCount();
        });

        const thumb = document.createElement("canvas");
        thumb.className = "thumb";
        job.thumb = thumb;

        const meta = document.createElement("span");
        meta.className = "meta";
        const w = ((box.x1 - box.x0) * 25.4) / 72;
        const h = ((box.y1 - box.y0) * 25.4) / 72;
        meta.textContent = `#${i + 1} · ${w.toFixed(1)} × ${h.toFixed(1)} mm`;

        card.append(check, thumb, meta);
        grid.append(card);

        const bitmap = await renderLabel(page, box, 420, 1);
        drawBitmap(thumb, bitmap);
      }
      section.append(grid);
      pagesEl.append(section);
    }

    if (!state.jobs.length) {
      log("ラベルが見つかりませんでした。--crop 相当の手動指定が必要です。", "error");
    } else {
      log(`${state.jobs.length} 枚を検出`, "ok");
    }
    $("#sheet").hidden = state.jobs.length === 0;
    updatePrintCount();
  } catch (err) {
    log(`失敗: ${(err as Error).message}`, "error");
    console.error(err);
  } finally {
    setBusy(false);
  }
}

function updateLogButtons(): void {
  const enabled = state.log.length > 0;
  ($("#log-csv") as HTMLButtonElement).disabled = !enabled;
  ($("#log-json") as HTMLButtonElement).disabled = !enabled;
}

function downloadLog(kind: "csv" | "json"): void {
  if (!state.log.length) return;
  const stamp = nowStamp().replace(/[:+]/g, "-").slice(0, 15);
  const name = `print-log-${stamp}.${kind}`;
  const text = kind === "csv" ? toCsv(state.log) : toJson(state.log);
  // BOM so Excel opens the Shift-JIS-free UTF-8 CSV correctly on Windows
  const body = kind === "csv" ? `\ufeff${text}` : text;
  const blob = new Blob([body], {
    type: kind === "csv" ? "text/csv;charset=utf-8" : "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
  log(`ログを書き出しました: ${name} (${state.log.length} 件)`, "ok");
}

function updatePrintCount(): void {
  const n = state.jobs.filter((j) => j.selected).length;
  const btn = $("#print");
  btn.textContent = `印刷する (${n} 枚)`;
  (btn as HTMLButtonElement).disabled = n === 0;
}

function settings() {
  return {
    darkness: Number(($("#darkness") as HTMLInputElement).value),
    speed: Number(($("#speed") as HTMLInputElement).value),
    paper: ($("#paper") as HTMLSelectElement).value as "adhesive" | "ticket" | "card" | "transparent",
    supersample: Number(($("#supersample") as HTMLInputElement).value),
  };
}

async function buildJobBitmaps(job: LabelJob): Promise<{ bitmap: Bitmap; stream: Uint8Array }> {
  const opts = settings();
  const label = await renderLabel(job.page, job.box, LABEL_W_DOTS, opts.supersample);
  const offset = autoOffset(LABEL_W_DOTS, PRINT_HEAD_DOTS);
  const composed = composeOnHead(label, PRINT_HEAD_DOTS, LABEL_H_DOTS, offset);
  const stream = buildStream(composed, {
    paper: opts.paper,
    darkness: opts.darkness - 1,
    speed: opts.speed - 1,
  });
  return { bitmap: composed, stream };
}

async function printSelected(): Promise<void> {
  const jobs = state.jobs.filter((j) => j.selected);
  if (!jobs.length) return;
  if (!state.printer.connected) {
    log("先にプリンタへ接続してください", "error");
    return;
  }
  setBusy(true);
  const bar = $("#progress") as HTMLProgressElement;
  try {
    for (const [i, job] of jobs.entries()) {
      const { bitmap, stream } = await buildJobBitmaps(job);
      const label = `[${i + 1}/${jobs.length}] ページ${job.pageIndex + 1} #${job.indexOnPage + 1}`;
      log(`${label}: ${bitmap.width}×${bitmap.rows.length} dots, ${stream.length} bytes`);
      const seconds = await state.printer.send(stream, (sent, total) => {
        bar.max = total;
        bar.value = sent;
      });
      log(`${label}: 送信 ${seconds.toFixed(1)}s`);
      const status = await state.printer.query(0x70);
      const statusText = state.printer.describeStatus(status);
      const tracking = guessTracking(state.fileName);
      state.log.push({
        at: nowStamp(),
        file: state.fileName,
        page: job.pageIndex + 1,
        label: job.indexOnPage + 1,
        tracking,
        widthMm: (job.box.x1 - job.box.x0) * 25.4 / 72,
        heightMm: (job.box.y1 - job.box.y0) * 25.4 / 72,
        bytes: stream.length,
        sha256: await sha256Short(stream),
        status: statusText,
      });
      updateLogButtons();
      log(`${label}: ${statusText} 追跡: ${tracking ?? "—"}`,
          status && status[3] === 0 ? "ok" : "info");
      if (i < jobs.length - 1) await new Promise((r) => setTimeout(r, 1500));
    }
    log("完了", "ok");
  } catch (err) {
    log(`印刷失敗: ${(err as Error).message}`, "error");
    console.error(err);
  } finally {
    bar.value = 0;
    setBusy(false);
  }
}

async function connect(acceptAll = false, remembered = false): Promise<void> {
  const step = (msg: string) => log(`  ${msg}`);
  try {
    if (!isSupported()) {
      log("このブラウザは Web Bluetooth 非対応です（Chrome / Edge を使ってください）", "error");
      return;
    }
    setBusy(true);
    if (remembered) {
      const name = await state.printer.useRemembered();
      if (!name) {
        log("以前に許可したデバイスがありません。「プリンタに接続」から選んでください", "error");
        return;
      }
      log(`記憶しているデバイス: ${name}`);
    } else {
      log("デバイスを選択してください…");
      const name = await state.printer.request(acceptAll);
      log(`選択: ${name}`);
    }
    await state.printer.connect(step);
    log(`接続: ${state.printer.name}${state.printer.mtu ? ` (MTU ${state.printer.mtu})` : ""}`, "ok");
    $("#print").removeAttribute("disabled");
    ($("#self-test") as HTMLButtonElement).disabled = false;

    const info = await state.printer.selfTest(step);
    log(`プリンタ応答 OK: ${info.name} / 状態 ${info.status} / 用紙 ${info.paper}`, "ok");
  } catch (err) {
    log(`接続失敗: ${describeError(err)}`, "error");
    if ((err as Error).message?.includes("選ばれません")) {
      log("ヒント: プリンタの電源が入っていて、スマホアプリ等が接続していないか確認してください", "info");
    }
    console.error(err);
  } finally {
    setBusy(false);
  }
}

async function selfTest(): Promise<void> {
  try {
    const step = (msg: string) => log(`  ${msg}`);
    const info = await state.printer.selfTest(step);
    log(`接続テスト: ${info.name} / 状態 ${info.status} / 用紙 ${info.paper}`, "ok");
  } catch (err) {
    log(`接続テスト失敗: ${describeError(err)}`, "error");
  }
}

async function downloadStream(): Promise<void> {
  const jobs = state.jobs.filter((j) => j.selected);
  if (!jobs.length) return;
  setBusy(true);
  try {
    for (const [i, job] of jobs.entries()) {
      const { stream } = await buildJobBitmaps(job);
      const blob = new Blob([stream as unknown as BlobPart], { type: "application/octet-stream" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `label-${i + 1}.bin`;
      a.click();
      URL.revokeObjectURL(a.href);
      await new Promise((r) => setTimeout(r, 150));
    }
    log(`${jobs.length} 件のコマンド列を書き出しました`, "ok");
  } finally {
    setBusy(false);
  }
}

function wire(): void {
  const input = $("#file") as HTMLInputElement;
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (file) void onFile(file);
  });

  const drop = $("#drop");
  for (const type of ["dragenter", "dragover"]) {
    drop.addEventListener(type, (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    drop.addEventListener(type, (e) => {
      e.preventDefault();
      drop.classList.remove("over");
    });
  }
  drop.addEventListener("drop", (e) => {
    const file = (e as DragEvent).dataTransfer?.files?.[0];
    if (file) void onFile(file);
  });
  drop.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("button")) return;
    input.click();
  });
  $("#browse").addEventListener("click", (e) => {
    e.stopPropagation();
    input.click();
  });

  // synthetic demo sheet (no personal data), shipped next to index.html
  $("#sample").addEventListener("click", (e) => {
    e.stopPropagation();
    void (async () => {
      try {
        const url = new URL("sample-4up.pdf", document.baseURI);
        const res = await fetch(url);
        if (!res.ok) throw new Error(`sample not found (${res.status})`);
        const blob = await res.blob();
        await onFile(new File([blob], "sample-4up.pdf", { type: "application/pdf" }));
      } catch (err) {
        log(`サンプルを読み込めません: ${(err as Error).message}`, "error");
      }
    })();
  });

  $("#connect").addEventListener("click", () => void connect(false, false));
  $("#connect-all").addEventListener("click", () => void connect(true, false));
  $("#connect-remembered").addEventListener("click", () => void connect(false, true));
  $("#self-test").addEventListener("click", () => void selfTest());
  $("#print").addEventListener("click", () => void printSelected());
  $("#download").addEventListener("click", () => void downloadStream());
  $("#log-csv").addEventListener("click", () => downloadLog("csv"));
  $("#log-json").addEventListener("click", () => downloadLog("json"));

  if (!isSupported()) {
    $(".banner").hidden = false;
  }
}

wire();
