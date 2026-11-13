/** Verify the installed preview in the actual host Vue application. */
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { gotoWhenReady, waitForServer } from "./browser_readiness.mjs";

const hostRoot = process.env.JELLYFIN_HOST_ROOT;
const work = process.env.INTEGRATION_WORK_ROOT;
const output = process.env.JELLYFIN_SCREENSHOT_DIR;
const config = path.join(work, "official-vite.config.mjs");
const port = Number(process.env.JELLYFIN_FRONTEND_PORT);
await mkdir(output, { recursive: true });
await writeFile(config, `import base from ${JSON.stringify(path.join(hostRoot, "src/frontend/vite.config.ts"))};\nexport default { ...base, root: ${JSON.stringify(path.join(hostRoot, "src/frontend"))}, server: { host: "127.0.0.1", port: ${port}, strictPort: true, proxy: { "/api": { target: ${JSON.stringify(process.env.PLUGIN_GATEWAY_URL)}, changeOrigin: true } } } };\n`);
const frontend = spawn(process.execPath, [path.join(hostRoot, "src/frontend/node_modules/vite/bin/vite.js"), "--config", config], { cwd: path.join(hostRoot, "src/frontend"), stdio: ["ignore", "pipe", "pipe"] });
// Keep the dev server output with the evidence so a slow or failing page can be diagnosed.
const serverLog = createWriteStream(path.join(output, "vite.log"));
frontend.stdout.pipe(serverLog);
frontend.stderr.pipe(serverLog);
let browser;
try {
  const base = `http://127.0.0.1:${port}`;
  await waitForServer(base);
  browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  // Pinned to a non-US locale/timezone so the host's one-time date-format
  // offer modal (shown to browsers that look American) never intercepts
  // clicks meant for this installed-preview UI under test.
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "dark",
    locale: "en-GB",
    timezoneId: "Europe/London",
  });
  assert((await context.request.post(`${base}/api/auth/login`, { data: { username_or_email: process.env.PRIMARY_USER_USERNAME, password: process.env.PRIMARY_USER_PASSWORD } })).ok());
  // Capture a returning account; first-login appearance has separate host coverage.
  const preferences = await context.request.get(`${base}/api/preferences`);
  assert(preferences.ok());
  if (Object.hasOwn(await preferences.json(), "ui_welcome_completed"))
    assert((await context.request.patch(`${base}/api/preferences`, { data: { ui_welcome_completed: true } })).ok());
  const page = await context.newPage();
  const errors = [];
  const diagnostics = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("requestfailed", request => diagnostics.push(`request failed ${request.url()} ${request.failure()?.errorText}`));
  page.on("response", response => { if (response.status() >= 400) diagnostics.push(`HTTP ${response.status()} ${response.url()}`); });
  // Warm the cold Vite server (dependency optimisation, first compile) before asserting.
  await page.goto(base, { waitUntil: "networkidle" }).catch(() => {});
  try {
    await gotoWhenReady(page, `${base}/plugins/official.jellyfin-media-sync/accounts`,
      () => page.getByRole("heading", { name: "Your Jellyfin accounts", exact: true }).last());
  } catch (error) {
    await page.screenshot({ path: path.join(output, "jellyfin-official-accounts-failure.png"), fullPage: true }).catch(() => {});
    console.error(["Accounts page did not render: " + page.url(), ...diagnostics, ...errors].join("\n"));
    throw error;
  }
  await page.getByTestId("jf-account").first().waitFor();
  assert.equal(await page.getByTestId("jf-admin").count(), 0);
  assert.equal(await page.getByLabel("Discovery API key", { exact: false }).count(), 0);
  await page.screenshot({ path: path.join(output, "jellyfin-official-accounts.png"), fullPage: true });
  // The settings contribution remains separate from the user's account route.
  await page.goto(`${base}/settings?section=jellyfin-admin`);
  await page.getByRole("heading", { name: "Jellyfin servers", exact: true }).waitFor();
  await page.getByTestId("jf-admin").waitFor();
  assert.equal(await page.getByTestId("jf-account").count(), 0);
  await page.screenshot({ path: path.join(output, "jellyfin-official-admin.png"), fullPage: true });
  const films = await (await context.request.get(`${base}/api/movie/list`)).json();
  const id = films.items.find(item => item.title === "Fixture film").id;
  await page.goto(`${base}/movies/${id}`);
  // The host renders this button from the synced watch_url and watch_label.
  const link = page.locator(".watch-links a.watch-main");
  await link.waitFor();
  assert((await link.getAttribute("href")).includes("/web/index.html#!/details?id="));
  assert((await link.textContent()).includes("Watch in Jellyfin"));
  await page.getByRole("heading", { name: "Provider progress and viewing history" }).waitFor();
  await page.locator(".provider-panel details").first().locator("summary").click();
  assert(await page.locator(".provider-panel progress").count());
  await page.screenshot({ path: path.join(output, "jellyfin-official-progress-history.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/plugins/official.jellyfin-media-sync/accounts`);
  await page.getByTestId("jf-account").first().waitFor();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  await page.screenshot({ path: path.join(output, "jellyfin-official-mobile.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log("Installed official preview browser checks passed.");
} finally {
  await browser?.close();
  frontend.kill("SIGTERM");
}
