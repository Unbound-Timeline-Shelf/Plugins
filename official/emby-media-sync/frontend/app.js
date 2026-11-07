// Shared by the Plex and Emby media sync pages (byte-identical copies; a test checks drift).
// index.html declares the provider and its sign-in fields; this script only talks to the
// host through the sandbox bridge and never stores or echoes a credential.
(() => {
  const $ = (id) => document.getElementById(id);
  const label = document.body.dataset.provider || "Media server";
  const categories = {
    movie: [["auto", "Automatic"], ["movie", "Movies"], ["anime", "Anime"], ["ignore", "Do not sync"]],
    show: [["auto", "Automatic"], ["tv_show", "TV shows"], ["anime", "Anime"], ["ignore", "Do not sync"]],
  };
  const reasons = {
    ambiguous_match: "Several items in your library could be this one.",
    incomplete_match: "A library item has the same title but no matching year or provider ID.",
    provider_id_mismatch: "A library item matches, but its provider IDs disagree.",
    local_watch_state_changed: `You changed its watch state here after the last ${label} sync.`,
    category_changed: "Its category was changed in your library.",
    locally_deleted: `You deleted it from your library; ${label} sync leaves it deleted.`,
    already_mapped: "Another library item is already linked to it.",
  };
  const decisions = {
    new: "Keep as a separate item",
    merge: "Merge into the chosen item",
    use_remote: `Use the ${label} watch state`,
    keep_category: "Keep my category",
  };
  const phases = {
    idle: "Not synced yet.",
    roots: "Reading libraries…",
    episodes: "Reading episodes…",
    finalize: "Checking availability…",
    restart: "The library changed; restarting the scan…",
    done: "Sync complete.",
  };
  let snapshot = { connected: false, phase: "idle", libraries: [], conflicts: [] };
  let loaded = false;
  let busy = false;
  let paused = false;

  function hostRequest(method, payload, timeoutMs = 35000) {
    return new Promise((resolve, reject) => {
      const requestId = typeof crypto.randomUUID === "function"
        ? crypto.randomUUID() : `media-${Date.now()}-${Math.random()}`;
      // 0 waits for the host, for example while its confirmation dialog is open.
      const timer = timeoutMs > 0 ? setTimeout(() => {
        window.removeEventListener("message", receive);
        reject(new Error("The host did not respond. Try again; a started sync resumes from its checkpoint."));
      }, timeoutMs) : undefined;
      function receive(event) {
        if (event.source !== window.parent || event.data?.type !== "plugin-api-response"
          || event.data.requestId !== requestId) return;
        clearTimeout(timer);
        window.removeEventListener("message", receive);
        const result = event.data.result || {};
        if (event.data.error || result.ok === false) {
          reject(new Error(event.data.error || result.error || "The action could not complete."));
        } else resolve(result);
      }
      window.addEventListener("message", receive);
      window.parent.postMessage({ type: "plugin-api-request", requestId, method, payload }, "*");
    });
  }
  const run = (actionId, values = {}, timeoutMs) =>
    hostRequest("plugin.run-action", { actionId, values }, timeoutMs);

  function option(value, text, selected) {
    const element = document.createElement("option");
    element.value = value;
    element.textContent = text;
    element.selected = value === selected;
    return element;
  }

  function renderLibraries() {
    const list = $("libraries");
    list.replaceChildren();
    for (const library of snapshot.libraries || []) {
      const row = document.createElement("label");
      row.className = "library";
      const name = document.createElement("span");
      name.textContent = library.name;
      const select = document.createElement("select");
      select.dataset.library = library.id;
      for (const [value, text] of categories[library.kind] || []) {
        select.append(option(value, text, library.category));
      }
      row.append(name, select);
      list.append(row);
    }
    $("no-libraries").hidden = (snapshot.libraries || []).length > 0;
  }

  function renderConflicts() {
    const list = $("conflicts");
    list.replaceChildren();
    for (const conflict of snapshot.conflicts || []) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = conflict.title || "Untitled item";
      const why = document.createElement("p");
      why.textContent = reasons[conflict.reason] || "This item needs review.";
      item.append(title, why);
      let target;
      if ((conflict.decisions || []).includes("merge") && (conflict.candidates || []).length) {
        target = document.createElement("select");
        target.setAttribute("aria-label", `Library item to merge ${conflict.title} into`);
        for (const candidate of conflict.candidates) target.append(option(candidate.id, candidate.title, ""));
        item.append(target);
      }
      const toolbar = document.createElement("div");
      toolbar.className = "toolbar";
      for (const decision of conflict.decisions || []) {
        if (decision === "merge" && !target) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ghost";
        button.textContent = decisions[decision] || decision;
        button.disabled = busy;
        button.onclick = () => {
          // Read the choice before perform() re-renders this list.
          const values = { external_id: conflict.external_id, decision };
          if (decision === "merge") values.target_id = target.value;
          void perform(async () => {
            const result = await run("resolve", values, 0);
            if (!result.cancelled) snapshot = result;
          });
        };
        toolbar.append(button);
      }
      if (toolbar.childElementCount) item.append(toolbar);
      list.append(item);
    }
    $("review-panel").hidden = !snapshot.conflict_total;
    $("review-more").hidden = (snapshot.conflict_total || 0) <= (snapshot.conflicts || []).length;
    $("review-more").textContent = `Showing ${(snapshot.conflicts || []).length} of ${snapshot.conflict_total}.`;
  }

  function render() {
    const connected = loaded && snapshot.connected;
    $("account").textContent = !loaded ? "Checking connection…" : connected
      ? `Connected as ${snapshot.account_name} on ${snapshot.server_name}.`
      : `Connect your ${label} account to start.`;
    $("account").className = connected ? "connected" : "hint";
    $("connect-panel").hidden = !loaded || connected;
    $("disconnect").hidden = !connected;
    $("libraries-panel").hidden = !connected;
    $("sync-panel").hidden = !connected;
    for (const button of document.querySelectorAll("button:not(#pause)")) button.disabled = busy;
    $("pause").hidden = !busy || !connected;
    $("pause").disabled = paused;
    $("progress").textContent = (paused ? "Paused. " : "") + (phases[snapshot.phase] || "Sync saved.");
    $("processed").textContent = snapshot.processed || 0;
    $("unnumbered").textContent = snapshot.unnumbered || 0;
    $("unavailable").textContent = snapshot.unavailable || 0;
    $("conflict-total").textContent = snapshot.conflict_total || 0;
    $("last-error").hidden = !snapshot.error;
    $("last-error").textContent = snapshot.error ? `Last sync problem: ${snapshot.error}` : "";
    if (connected) { renderLibraries(); renderConflicts(); }
  }

  async function perform(work) {
    if (busy) return;
    busy = true; paused = false; $("error").hidden = true; render();
    try { await work(); } catch (error) {
      $("error").textContent = error.message; $("error").hidden = false;
    } finally { busy = false; render(); }
  }

  async function syncWhileOpen() {
    // The same bounded step the host runs from Connections and the personal schedule.
    do {
      snapshot = await run("sync"); render();
    } while (!paused && snapshot.phase !== "done");
  }

  // Each handler reads the form before perform() re-renders the page from the last snapshot.
  $("connect").onclick = () => {
    if (busy) return;
    const values = {};
    for (const input of document.querySelectorAll("[data-field]")) {
      values[input.dataset.field] = input.value;
      if (input.type === "password") input.value = "";
    }
    void perform(async () => { snapshot = await run("connect", values); });
  };
  $("save-libraries").onclick = () => {
    if (busy) return;
    const mappings = {};
    for (const select of document.querySelectorAll("select[data-library]")) mappings[select.dataset.library] = select.value;
    void perform(async () => { snapshot = await run("save-libraries", { mappings }); });
  };
  $("disconnect").onclick = () => perform(async () => {
    const result = await run("disconnect", {}, 0);
    if (!result.cancelled) snapshot = result;
  });
  $("sync").onclick = () => perform(syncWhileOpen);
  $("pause").onclick = () => { paused = true; $("pause").disabled = true; };
  void perform(async () => {
    try { snapshot = await run("status"); } finally { loaded = true; }
  });
})();
