const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

// The Plex and Emby pages share app.js and style.css; only index.html (fields, labels) differs.
function markup(slug) {
  const root = path.resolve(__dirname, `../official/${slug}-media-sync/frontend`);
  const asset = (name) => fs.readFileSync(
    name.startsWith("appearance.")
      ? path.resolve(__dirname, "../sdk", `frontend_${name}`)
      : path.join(root, name), "utf8",
  );
  return fs.readFileSync(path.join(root, "index.html"), "utf8")
    .replace(/<link rel="stylesheet" href="\.\/([^"]+)">/g,
      (_, name) => `<style>${asset(name)}</style>`)
    .replace(/<script src="\.\/([^"]+)"><\/script>/g,
      (_, name) => `<script nonce="fixture">${asset(name).replace(/<\/script/gi, "<\\/script")}</script>`)
    .replace("<head>", `<head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-fixture'; style-src 'unsafe-inline'">`);
}

let browser;
before(async () => { browser = await chromium.launch({ args: ["--no-sandbox"] }); });
after(async () => { await browser?.close(); });

// A fixture host: answers the sandbox bridge and records every action and its values.
async function mount(page, slug, { connected = false, phases = ["done"], conflicts = [] } = {}) {
  await page.setContent(`<iframe title="${slug}" sandbox="allow-scripts"></iframe>`);
  await page.evaluate(({ html, connected, phases, conflicts }) => {
    const iframe = document.querySelector("iframe");
    window.actions = [];
    let isConnected = connected;
    let step = 0;
    const snapshot = (extra = {}) => ({
      connected: isConnected, account_name: "viewer", server_name: "Den", phase: "idle",
      processed: 0, conflict_total: conflicts.length, conflicts,
      libraries: [{ id: "1", name: "Films", kind: "movie", category: "auto" },
        { id: "2", name: "Series", kind: "show", category: "anime" }],
      ...extra,
    });
    window.addEventListener("message", event => {
      if (event.source !== iframe.contentWindow || event.data?.type !== "plugin-api-request") return;
      const { payload, requestId } = event.data;
      let result = {};
      if (event.data.method === "plugin.run-action") {
        window.actions.push({ action: payload.actionId, values: payload.values });
        const id = payload.actionId;
        if (id === "status") result = snapshot();
        else if (id === "connect") {
          if (Object.values(payload.values).some(v => v === "")) result = { ok: false, error: "Enter your server URL." };
          else { isConnected = true; result = snapshot(); }
        } else if (id === "sync") {
          const phase = phases[Math.min(step, phases.length - 1)];
          step += 1;
          result = snapshot({ phase, processed: step * 50 });
        } else if (id === "disconnect") { isConnected = false; result = snapshot(); }
        else result = snapshot();
      }
      event.source.postMessage({ type: "plugin-api-response", requestId, result }, "*");
    });
    iframe.srcdoc = html;
  }, { html: markup(page.slug), connected, phases, conflicts });
  return page.frameLocator("iframe");
}

for (const [slug, label, fields] of [
  ["plex", "Plex", { server_url: "Server URL", token: "Plex token" }],
  ["emby", "Emby", { server_url: "Server URL", username: "Username", password: "Password" }],
]) {
  test(`${label}: connecting sends the fields once and clears secret inputs`, async () => {
    const page = await browser.newPage();
    page.slug = slug;
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    try {
      const frame = await mount(page, slug);
      await frame.getByText(`Connect your ${label} account to start.`).waitFor();
      for (const [field, name] of Object.entries(fields)) {
        await frame.getByLabel(name, { exact: true }).fill(`${field}-value`);
      }
      await frame.getByRole("button", { name: `Connect ${label}` }).click();
      await frame.getByText("Connected as viewer on Den.").waitFor();
      const actions = await page.evaluate(() => window.actions);
      const connect = actions.find(a => a.action === "connect");
      assert.deepEqual(Object.keys(connect.values).sort(), Object.keys(fields).sort());
      assert.equal(await frame.locator("#connect-panel").isVisible(), false);
      for (const input of await frame.locator("input[type=password]").all()) {
        assert.equal(await input.inputValue(), "");
      }
      assert.deepEqual(errors, []);
    } finally { await page.close(); }
  });

  test(`${label}: Sync now steps until done and library choices are saved`, async () => {
    const page = await browser.newPage();
    page.slug = slug;
    try {
      const frame = await mount(page, slug, { connected: true, phases: ["roots", "episodes", "done"] });
      await frame.getByText("Connected as viewer on Den.").waitFor();
      assert.equal(await frame.getByLabel("Films").inputValue(), "auto");
      await frame.getByLabel("Series").selectOption("tv_show");
      await frame.getByRole("button", { name: "Save library choices" }).click();
      await frame.getByRole("button", { name: "Sync now" }).click();
      await frame.getByText("Sync complete.").waitFor();
      const actions = await page.evaluate(() => window.actions);
      assert.deepEqual(actions.find(a => a.action === "save-libraries").values,
        { mappings: { 1: "auto", 2: "tv_show" } });
      assert.equal(actions.filter(a => a.action === "sync").length, 3);
      assert.equal(await frame.locator("#processed").textContent(), "150");
    } finally { await page.close(); }
  });
}

test("review decisions send the chosen merge target", async () => {
  const page = await browser.newPage();
  page.slug = "plex";
  try {
    const frame = await mount(page, "plex", {
      connected: true,
      conflicts: [{ external_id: "101", title: "Fixture Film", reason: "ambiguous_match",
        decisions: ["merge", "new"], candidates: [{ id: "a", title: "Mine A" }, { id: "b", title: "Mine B" }] }],
    });
    await frame.getByText("Several items in your library could be this one.").waitFor();
    await frame.getByLabel("Library item to merge Fixture Film into").selectOption("b");
    await frame.getByRole("button", { name: "Merge into the chosen item" }).click();
    await page.waitForFunction(() => window.actions.some(a => a.action === "resolve"));
    const resolve = (await page.evaluate(() => window.actions)).find(a => a.action === "resolve");
    assert.deepEqual(resolve.values, { external_id: "101", decision: "merge", target_id: "b" });
  } finally { await page.close(); }
});
