#!/usr/bin/env node
// Screenshot every dashboard route. See ../SKILL.md.
// Usage: node screenshot.mjs [--routes /overview,/cashflow] [--desktop] [--no-mobile] [--full-page] [--port 5173]
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, openSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../../..");
const appDir = join(repo, "app");

const argv = process.argv.slice(2);
const flag = (n) => argv.includes(`--${n}`);
const opt = (n, d) => { const i = argv.indexOf(`--${n}`); return i >= 0 ? argv[i + 1] : d; };
const port = Number(opt("port", 5173));
const base = `http://localhost:${port}`;
const fullPage = flag("full-page");

// Default routes: parse app/src/routes/index.tsx so new routes are picked up.
function discoverRoutes() {
  const src = readFileSync(join(appDir, "src/routes/index.tsx"), "utf8");
  return [...src.matchAll(/path:\s*"(\/[^"]*)"/g)].map((m) => m[1]);
}
const routes = opt("routes") ? opt("routes").split(",").map((r) => (r.startsWith("/") ? r : "/" + r)) : discoverRoutes();

const viewports = [];
if (!flag("no-mobile")) viewports.push({ name: "mobile", width: 390, height: 844, dsf: 2, mobile: true });
if (flag("desktop")) viewports.push({ name: "desktop", width: 1440, height: 900, dsf: 1, mobile: false });

async function isUp() {
  try { return (await fetch(base)).ok; } catch { return false; }
}

let server = null;
async function ensureServer() {
  if (await isUp()) { console.log(`dev server already running on :${port}`); return; }
  if (!existsSync(join(appDir, "node_modules"))) {
    console.log("app/node_modules missing, running pnpm install");
    await new Promise((res, rej) => spawn("pnpm", ["install"], { cwd: appDir, stdio: "inherit" }).on("exit", (c) => (c ? rej(new Error("pnpm install failed")) : res())));
  }
  mkdirSync(join(repo, ".claude/screenshots"), { recursive: true });
  const log = openSync(join(repo, ".claude/screenshots/dev-server.log"), "w");
  server = spawn("pnpm", ["dev", "--port", String(port), "--strictPort"], { cwd: appDir, stdio: ["ignore", log, log], detached: true });
  for (let i = 0; i < 120; i++) {
    if (await isUp()) { console.log(`dev server started (pid ${server.pid})`); return; }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("dev server did not become ready in 60s; see .claude/screenshots/dev-server.log");
}

async function launch() {
  try { return await chromium.launch(); } catch {}
  // Playwright's pinned revision isn't installed: reuse any Chromium in the shared cache.
  const cache = join(homedir(), "Library/Caches/ms-playwright");
  const dirs = existsSync(cache) ? readdirSync(cache).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse() : [];
  for (const d of dirs) {
    for (const rel of ["chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing", "chrome-mac/Chromium.app/Contents/MacOS/Chromium", "chrome-linux/chrome"]) {
      const p = join(cache, d, rel);
      if (existsSync(p)) return chromium.launch({ executablePath: p });
    }
  }
  throw new Error("No Chromium found. Run: npx playwright install chromium (in the skill dir)");
}

const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const outDir = join(repo, ".claude/screenshots", ts);
mkdirSync(outDir, { recursive: true });

await ensureServer();
const browser = await launch();
let failures = 0;
const files = [];
try {
  for (const vp of viewports) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: vp.dsf,
      isMobile: vp.mobile,
      hasTouch: vp.mobile,
      colorScheme: "dark",
    });
    for (const route of routes) {
      const page = await ctx.newPage();
      const errors = [];
      page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
      page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
      page.on("requestfailed", (r) => errors.push(`requestfailed: ${r.url()}`));
      try {
        await page.goto(base + route, { waitUntil: "networkidle", timeout: 30000 });
        await page.waitForTimeout(1500); // let recharts finish animating
        const file = join(outDir, `${vp.name}-${route.replace(/^\//, "").replace(/\//g, "_") || "root"}.png`);
        await page.screenshot({ path: file, fullPage });
        files.push(file);
        console.log(`ok   ${vp.name} ${route}${errors.length ? `  (${errors.length} console errors)` : ""}`);
      } catch (e) {
        failures++;
        console.log(`FAIL ${vp.name} ${route}: ${e.message.split("\n")[0]}`);
      }
      errors.forEach((e) => console.log(`     ! ${e.slice(0, 300)}`));
      if (errors.length) failures++;
      await page.close();
    }
    await ctx.close();
  }
} finally {
  await browser.close();
  if (server && !flag("keep-server")) {
    try { process.kill(-server.pid); } catch {}
    console.log("stopped dev server we started (pass --keep-server to leave it running)");
  }
}
console.log(`\nOutput: ${outDir}`);
files.forEach((f) => console.log(f));
process.exit(failures ? 1 : 0);
