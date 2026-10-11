// Drives the real Studio UI in Chromium against a real local server.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../..");
const PYTHON = process.env.PYTHON || process.env.PYTHON3 || "python3";

async function startServer() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "mxs-ui-"));
  const env = { ...process.env, MXS_HOME: home, MXS_WORKSPACE: path.join(home, "المشروع", "data"), PYTHONPATH: `${ROOT}:${ROOT}/slidepoise/runtime/src` };
  const child = spawn(PYTHON, ["-m", "mxstudio", "serve"], { cwd: ROOT, env, stdio: "ignore" });
  const lock = path.join(home, "server.lock");
  for (let i = 0; i < 100 && !fs.existsSync(lock); i += 1) await new Promise((r) => setTimeout(r, 100));
  const { port } = JSON.parse(fs.readFileSync(lock, "utf8"));
  for (let i = 0; i < 50; i += 1) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  return { child, port, home };
}

test("Arabic RTL UI: every tab renders, settings save, language toggles, irreversible asks a human", { timeout: 120000 }, async () => {
  const { child, port } = await startServer();
  const preinstalled = process.env.MXS_CHROMIUM || "/opt/pw-browsers/chromium";
  const browser = await chromium.launch(fs.existsSync(preinstalled) ? { executablePath: preinstalled } : {});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.goto(`http://127.0.0.1:${port}/`);
    assert.equal(await page.getAttribute("html", "dir"), "rtl");
    assert.equal(await page.getAttribute("html", "lang"), "ar");
    // «ابدأ هنا» is the first page: chat, picture upload (stored and shown), honest "no model" answer
    await page.waitForSelector("#chat-text");
    assert.equal(await page.getAttribute('#nav a[href="#start"]', "class"), "active");
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGP8tNiKARtgwio6aCUAbekB3/mw8Q8AAAAASUVORK5CYII=", "base64");
    await page.setInputFiles("#chat-files", { name: "design.png", mimeType: "image/png", buffer: png });
    await page.waitForSelector("#attached .thumb img");
    await page.fill("#chat-text", "قصة عن البحر بألوان الصورة دي");
    // no model configured: not a red NO_MODEL error but «prepare a request for Claude Desktop» (phase 16)
    assert.ok((await page.textContent("#prep-note")).includes("Claude Desktop"));
    await page.waitForFunction(() => document.querySelector("#inbox-list").textContent.includes("design"));
    await page.click("#chat-send");
    await page.waitForFunction(() => document.querySelector("#chat-status").textContent.includes("نفّذ طلبات الاستوديو"));
    await page.waitForFunction(() => document.querySelector("#requests").textContent.includes("قصة عن البحر"));
    const saved = await page.evaluate(async () => (await fetch("/api/requests")).json());
    assert.equal(saved.requests[0].status, "new");
    assert.equal(saved.requests[0].image_shas.length, 1);
    // «توصيل Claude Desktop» at the bottom of the menu: status, steps, config snippet, self-test of the real command
    await page.click('#nav a[href="#mcp"]');
    await page.waitForSelector("#mcp-snippet");
    assert.ok((await page.textContent("#mcp-snippet")).includes("modulex-studio"));
    await page.click("#mcp-test");
    await page.waitForFunction(() => document.querySelector("#mcp-result").textContent.includes("✓"), null, { timeout: 90000 });
    for (const hash of ["start", "home", "stories", "fonts", "shapes", "colour", "kit", "qa", "marketing", "agent", "mcp", "doctor", "settings", "audit"]) {
      await page.click(`#nav a[href="#${hash}"]`);
      await page.waitForFunction((h) => document.querySelector(`#nav a[href="#${h}"]`).classList.contains("active"), hash);
      await page.waitForFunction(() => document.querySelector("#view").innerHTML.length > 0);
    }
    await page.click('#nav a[href="#settings"]');
    await page.waitForSelector("#tv-url");
    await page.fill("#tv-url", "http://gpu-host:8000");
    await page.check("#tv-on");
    await page.click("#save-providers");
    await page.fill("#per-day", "7.5");
    await page.click("#save-general");
    await page.fill("#key-value", "sk-ui-secret");
    await page.click("#save-key");
    await page.waitForFunction(() => document.querySelector("#view").textContent.includes("fingerprint"));
    assert.ok(!(await page.content()).includes("sk-ui-secret"));
    const settings = await page.evaluate(async () => (await fetch("/api/settings")).json());
    assert.equal(settings.providers.text_vision.base_url, "http://gpu-host:8000");
    assert.equal(settings.providers.text_vision.enabled, true);
    assert.equal(settings.budget.per_day_usd, 7.5);

    await page.click("#lang-toggle");
    assert.equal(await page.getAttribute("html", "dir"), "ltr");
    await page.click("#lang-toggle");

    await page.click('#nav a[href="#agent"]');
    await page.waitForSelector("#tool");
    await page.selectOption("#tool", "workspace.approve");
    await page.fill("#tool-args", JSON.stringify({ kind: "x", key: "y", version: 1, approved_by: "ModuleX" }));
    page.once("dialog", (d) => d.dismiss());
    await page.click("#run-tool");
    await page.waitForSelector("#confirm-dialog[open]");
    await page.click("#confirm-no");
    await page.waitForFunction(() => document.querySelector("#tool-result").textContent.includes("CANCELLED_BY_HUMAN"));
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    child.kill();
  }
});
