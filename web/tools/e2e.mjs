#!/usr/bin/env node
/** End-to-end smoke test of the built app in a real Chrome (no Web Bluetooth). */
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://127.0.0.1:4173/";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });

const errors = [];
page.on("response", (res) => {
  if (res.status() >= 400) errors.push(`${res.status()} ${res.url()}`);
});
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto(url, { waitUntil: "networkidle" });
console.log("title:", await page.title());

await page.click("#sample");
await page.waitForSelector(".card", { timeout: 30000 });
await page.waitForFunction(() => document.querySelectorAll(".card canvas").length >= 4, null, { timeout: 30000 });

const cards = await page.locator(".card").count();
const metas = await page.locator(".card .meta").allTextContents();
const thumbs = await page.$$eval(".card canvas", (nodes) =>
  nodes.map((n) => `${n.width}x${n.height}`),
);
console.log("cards:", cards);
console.log("meta :", metas.join(" | "));
console.log("thumb:", thumbs.join(" "));
await page.screenshot({ path: "/tmp/web-e2e.png", fullPage: true });
console.log("console errors:", errors.length ? errors.slice(0, 5) : "none");
await browser.close();
process.exit(cards === 4 && errors.length === 0 ? 0 : 1);
