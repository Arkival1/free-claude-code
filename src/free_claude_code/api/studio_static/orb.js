/* The Orb edition: talk to Jarvis, ask his two advisers, approve his PC
   steps, and stop him at any moment. Nothing else lives here. */
(() => {
  "use strict";

  const TOKEN_KEY = "fcc.studio.token";
  const $ = (id) => document.getElementById(id);
  const log = $("orb-log");
  const input = $("orb-input");
  const form = $("orb-form");
  const sendButton = $("orb-send");
  const withAdvisers = $("orb-with-advisers");
  const statusLine = $("orb-status");
  const approvals = $("orb-approvals");
  const sheet = $("sheet");
  const sheetTitle = $("sheet-title");
  const sheetBody = $("sheet-body");
  const toast = $("toast");
  const pcGuard = $("pc-guard");
  const pcStop = $("pc-stop");

  let orb = null;
  let state = null;
  let pcState = null;
  let lastSeq = 0;
  let busy = false;
  let toastTimer = null;

  const el = (tag, props = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, "");
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const child of [].concat(children)) {
      if (child == null) continue;
      node.append(child instanceof Node ? child : document.createTextNode(child));
    }
    return node;
  };

  function token() {
    const fromUrl = new URLSearchParams(location.search).get("token");
    try {
      if (fromUrl) localStorage.setItem(TOKEN_KEY, fromUrl);
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch {
      return fromUrl || "";
    }
  }

  async function api(path, options = {}) {
    const headers = { "content-type": "application/json" };
    const key = token();
    if (key) headers["x-api-key"] = key;
    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch {
      throw new Error("Can't reach FCC on this PC.");
    }
    const text = await response.text();
    let body = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = {};
    }
    if (response.status === 401) throw new Error("FCC needs its token: open this page from the FCC shortcut.");
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }
  const post = (path, payload) => api(path, { method: "POST", body: JSON.stringify(payload || {}) });

  function notify(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.hidden = true), 3200);
  }

  function openSheet(heading, nodes) {
    sheetTitle.textContent = heading;
    sheetBody.replaceChildren(...[].concat(nodes));
    sheet.hidden = false;
  }

  function closeSheet() {
    sheet.hidden = true;
    sheetBody.replaceChildren();
  }

  sheet.addEventListener("click", (event) => {
    if (event.target.hasAttribute("data-close-sheet")) closeSheet();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !sheet.hidden) closeSheet();
  });

  /* ------------------------------------------------------------ the core */

  function setOrb(name) {
    if (orb) orb.setState(name);
  }

  function renderStatus() {
    if (!state) return;
    const model = state.jarvis.model.replace(/^local\//, "");
    const local = state.jarvis.model.startsWith("local/");
    const pc = state.pc || {};
    const hands = !pc.enabled
      ? "no PC control"
      : pc.stopped
        ? "stopped"
        : pc.level === "off"
          ? "PC: off"
          : `PC: ${pc.level}`;
    statusLine.textContent = local ? `${model} · ${hands}` : "Pick Jarvis's model on this PC (⚙)";
    $("orb-advisers").replaceChildren(
      ...state.advisers.map((adviser) =>
        el("span", { class: "orb-chip", title: adviser.speciality || "" }, [
          el("strong", { text: adviser.name }),
          ` · ${adviser.model.replace(/^local\//, "")}`,
        ]),
      ),
    );
  }

  async function loadState() {
    state = await api("/studio/api/orb");
    showPcGuard(state.pc);
    renderStatus();
  }

  /* -------------------------------------------------------- the talk log */

  function addEntry(kind, who, text, extra = "") {
    const item = el("li", { class: `orb-msg ${kind}${extra ? ` ${extra}` : ""}` }, [
      who ? el("small", { text: who }) : null,
      text,
    ]);
    log.append(item);
    item.scrollIntoView({ block: "end", behavior: "smooth" });
    return item;
  }

  function showMessage(message) {
    if (message.role === "user") addEntry("you", "You", message.text);
    else if (message.role === "assistant") addEntry("jarvis", message.author || "Jarvis", message.text);
    else if (message.role === "event" && message.text) addEntry("event", "", message.text);
  }

  async function pollChat() {
    if (!state) return;
    try {
      const { messages } = await api(`/studio/api/chats/${state.chat_id}?after=${lastSeq}`);
      for (const message of messages) {
        lastSeq = Math.max(lastSeq, message.sequence);
        showMessage(message);
      }
    } catch {
      // Offline for a moment: the next poll catches up.
    }
  }

  async function say(text) {
    busy = true;
    sendButton.disabled = true;
    setOrb("thinking");
    try {
      if (withAdvisers.checked) {
        addEntry("you", "You (with advisers)", text);
        const { job } = await post("/studio/api/orb/say", { text, advisers: true });
        await followJob(job);
      } else {
        await post("/studio/api/orb/say", { text });
        await pollChat();
      }
      if (orb) orb.burst();
    } catch (error) {
      addEntry("event", "", error.message, "failed");
    } finally {
      busy = false;
      sendButton.disabled = false;
      setOrb("idle");
    }
  }

  async function followJob(job) {
    const seen = new Set();
    let current = job;
    let misses = 0;
    for (;;) {
      current.steps.forEach((step, index) => {
        const key = `${index}:${step.status}`;
        if (step.status !== "done" || seen.has(key)) return;
        seen.add(key);
        const adviser = step.agent_id !== current.hands_id;
        const label = `${step.agent}${adviser ? ` (${step.stage})` : ""}`;
        addEntry(adviser ? "adviser" : "jarvis", label, step.result || "Done.");
      });
      if (current.status !== "working" && !current.running) break;
      await new Promise((resolve) => setTimeout(resolve, 2000));
      try {
        current = await api(`/studio/api/playground/${current.id}`);
        misses = 0;
      } catch {
        // FCC restarted or the job is gone: stop waiting after about a minute.
        misses += 1;
        if (misses >= 30) {
          addEntry("event", "", "Lost track of that job (FCC may have restarted). Ask Jarvis again.", "failed");
          return;
        }
      }
    }
    if (current.summary) addEntry("event", "", current.summary);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    input.style.height = "";
    say(text);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = `${Math.min(160, input.scrollHeight)}px`;
  });

  /* ------------------------------------------------- waiting for your OK */

  async function pollApprovals() {
    try {
      const { pending } = await api("/studio/api/commands/pending");
      approvals.hidden = !pending.length;
      approvals.replaceChildren(
        ...pending.map((request) =>
          el("div", { class: "orb-approval" }, [
            el("small", { class: "muted", text: "Jarvis wants to:" }),
            el("code", { text: request.command.replace(/^\[PC\] /, "") }),
            el("div", { class: "orb-row" }, [
              el("button", {
                class: "orb-primary",
                type: "button",
                text: "Allow",
                onclick: () => decide(request.id, "approve"),
              }),
              el("button", {
                class: "orb-secondary",
                type: "button",
                text: "No",
                onclick: () => decide(request.id, "deny"),
              }),
            ]),
          ]),
        ),
      );
    } catch {
      // Try again on the next poll.
    }
  }

  async function decide(id, choice) {
    try {
      await post(`/studio/api/commands/${id}/${choice}`);
    } catch (error) {
      notify(error.message);
    }
    pollApprovals();
  }

  /* --------------------------------------------------------- Jarvis's PC */

  const PC_LEVELS = {
    off: "Off: no PC tools",
    look: "Look: reads files and folders only",
    ask: "Ask: every change waits for your OK",
    full: "Full: works on his own (deleting, moving, installs, scripts and code runners still ask)",
  };
  const pcPanelShown = () => !sheet.hidden && sheetTitle.textContent === "Jarvis's PC";

  function showPcGuard(pc) {
    pcState = pc;
    pcGuard.hidden = !(pc && pc.enabled);
    if (pcGuard.hidden) return;
    pcGuard.dataset.state = pc.stopped ? "stopped" : pc.active ? "on" : "off";
    pcStop.textContent = pc.stopped ? "Jarvis stopped" : "■ Stop Jarvis";
    pcStop.title = pc.stopped
      ? "Jarvis can't touch this PC. Open the PC panel to let him carry on."
      : "Stop Jarvis now: ends anything he's running on this PC.";
    if (state) {
      state.pc = pc;
      renderStatus();
    }
    const typing = sheetBody.contains(document.activeElement) && document.activeElement.matches("input, textarea, select");
    if (pcPanelShown() && !typing) fillPcPanel();
  }

  async function refreshPc() {
    try {
      showPcGuard(await api("/studio/api/pc-control"));
    } catch {
      // Offline: keep showing the last state.
    }
  }

  async function stopJarvis() {
    pcStop.disabled = true;
    try {
      const pc = await post("/studio/api/pc-control/stop");
      showPcGuard(pc);
      setOrb("offline");
      notify(pc.killed ? `Jarvis stopped. Ended ${pc.killed} running.` : "Jarvis stopped. He can't touch this PC.");
    } catch (error) {
      notify(error.message);
    } finally {
      pcStop.disabled = false;
    }
  }

  async function pcChange(path, payload, done) {
    try {
      showPcGuard(await post(path, payload));
      if (pcPanelShown()) fillPcPanel();
      if (done) notify(done);
    } catch (error) {
      notify(error.message);
    }
  }

  function pcLogRow(row) {
    const when = new Date(row.at || 0).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const tag = row.verdict || row.status || (row.result ? "result" : "");
    return el("li", { class: `pc-log-row${tag ? ` pc-${tag}` : ""}` }, [
      el("span", { class: "pc-log-when", text: when }),
      el("strong", { text: row.who || "" }),
      tag ? el("span", { class: "pc-log-tag", text: tag }) : null,
      el("span", { class: "pc-log-text", text: row.text || "" }),
    ]);
  }

  function fillPcPanel() {
    const pc = pcState || {};
    const big = pc.stopped
      ? el("button", {
          class: "orb-primary pc-big",
          type: "button",
          text: "Let Jarvis carry on",
          onclick: () => pcChange("/studio/api/pc-control/resume", {}, "Jarvis can use the PC again."),
        })
      : el("button", { class: "pc-big pc-big-stop", type: "button", text: "■ Stop Jarvis now", onclick: stopJarvis });
    const level = el(
      "select",
      {},
      Object.entries(PC_LEVELS).map(([value, label]) => el("option", { value, text: label, selected: pc.level === value })),
    );
    level.addEventListener("change", () => pcChange("/studio/api/pc-control/level", { level: level.value }, "Saved."));
    const roots = el("textarea", { rows: "3" });
    roots.value = (pc.roots || []).join("\n");
    const recent = (pc.log || []).slice(-40).reverse();
    sheetBody.replaceChildren(
      el("p", {
        class: "muted",
        text: pc.stopped
          ? "Stopped. Jarvis can't run anything or change files on this PC until you let him carry on (only from this PC)."
          : pc.active
            ? `Jarvis has hands on this PC while he thinks on the local model.${pc.running ? ` Running now: ${pc.running}.` : ""} His advisers never do.`
            : "Jarvis has no PC tools at this level.",
      }),
      big,
      el("label", { class: "orb-field" }, [el("span", { text: "What he may do on his own" }), level]),
      el("label", { class: "orb-field" }, [el("span", { text: "His folders (one per line)" }), roots]),
      el("button", {
        class: "orb-secondary",
        type: "button",
        text: "Save folders",
        onclick: () =>
          pcChange(
            "/studio/api/pc-control/roots",
            { roots: roots.value.split("\n").map((line) => line.trim()).filter(Boolean) },
            "Folders saved.",
          ),
      }),
      el("p", {
        class: "muted",
        text: "Never, at any level: Windows' own folders, FCC's code and keys, saved passwords, banking, buying, or wiping a drive.",
      }),
      el("h3", { text: "What he did" }),
      recent.length ? el("ol", { class: "pc-log" }, recent.map(pcLogRow)) : el("p", { class: "muted", text: "Nothing yet." }),
    );
  }

  function openPcPanel() {
    openSheet("Jarvis's PC", []);
    fillPcPanel();
    refreshPc();
  }

  pcStop.addEventListener("click", () => (pcState && pcState.stopped ? openPcPanel() : stopJarvis()));
  $("pc-panel").addEventListener("click", openPcPanel);
  // Ctrl+Alt+Pause (or Ctrl+Alt+S) stops Jarvis.
  document.addEventListener("keydown", (event) => {
    if (!event.ctrlKey || !event.altKey) return;
    if (event.key !== "Pause" && event.key.toLowerCase() !== "s") return;
    if (!pcState || !pcState.enabled || pcState.stopped) return;
    event.preventDefault();
    stopJarvis();
  });

  /* ------------------------------------------- Jarvis and his advisers */

  async function openSetup() {
    let models = { local: { models: [] }, server: [] };
    try {
      models = await api("/studio/api/models/available");
    } catch {
      // The current models still show.
    }
    const local = (models.local && models.local.models) || [];
    // All local: only models this PC serves (LM Studio or FCC's engine).
    const choices = local.map((id) => [id, id.replace(/^local\//, "")]);
    const picker = (current) => {
      const select = el(
        "select",
        {},
        choices.map(([value, label]) => el("option", { value, text: label, selected: value === current })),
      );
      if (!choices.length && !(current || "").startsWith("local/")) {
        select.append(el("option", { value: "", text: "Start LM Studio and load a model first" }));
      }
      if (current && current.startsWith("local/") && !choices.some(([value]) => value === current)) {
        select.prepend(el("option", { value: current, text: current, selected: true }));
      }
      return select;
    };
    const jarvisModel = picker(state.jarvis.model);
    const cards = state.advisers.map((adviser, index) => {
      const name = el("input", { type: "text", maxlength: "60", value: adviser.name });
      const speciality = el("textarea", { rows: "3", maxlength: "600" });
      speciality.value = adviser.speciality || "";
      const model = picker(adviser.model);
      return el("div", { class: "orb-card" }, [
        el("h3", { text: `Adviser ${index + 1}` }),
        el("label", { class: "orb-field" }, [el("span", { text: "Name" }), name]),
        el("label", { class: "orb-field" }, [el("span", { text: "Speciality and role" }), speciality]),
        el("label", { class: "orb-field" }, [el("span", { text: "Model on this PC (a smaller one is fine)" }), model]),
        el("button", {
          class: "orb-secondary",
          type: "button",
          text: "Save adviser",
          onclick: async () => {
            try {
              Object.assign(
                state,
                await post(`/studio/api/orb/advisers/${index + 1}`, {
                  name: name.value,
                  speciality: speciality.value,
                  model: model.value,
                }),
              );
              renderStatus();
              notify(`${name.value} saved.`);
            } catch (error) {
              notify(error.message);
            }
          },
        }),
      ]);
    });
    openSheet("Jarvis and his advisers", [
      el("p", {
        class: "muted",
        text: "All local: Jarvis and his advisers think on this PC's models (LM Studio). Jarvis does the work; his two advisers only advise: they search the web and suggest tools, and never touch this PC. With one model loaded at a time, FCC swaps them in when you ask.",
      }),
      el("div", { class: "orb-card" }, [
        el("h3", { text: "Jarvis" }),
        el("label", { class: "orb-field" }, [el("span", { text: "Model on this PC" }), jarvisModel]),
        el("button", {
          class: "orb-secondary",
          type: "button",
          text: "Save Jarvis",
          onclick: async () => {
            try {
              Object.assign(state, await post("/studio/api/orb/jarvis", { model: jarvisModel.value }));
              renderStatus();
              notify("Jarvis saved.");
            } catch (error) {
              notify(error.message);
            }
          },
        }),
      ]),
      ...cards,
    ]);
  }

  $("orb-setup").addEventListener("click", () => state && openSetup());

  /* ---------------------------------------------------------------- start */

  async function start() {
    if (window.FCCCoreOrb && !orb) orb = window.FCCCoreOrb.createCoreOrb($("orb-canvas"));
    try {
      await loadState();
    } catch (error) {
      statusLine.textContent = error.message;
      setOrb("offline");
      setTimeout(start, 5000);
      return;
    }
    await pollChat();
    pollApprovals();
    setInterval(() => {
      if (busy) pollChat();
      pollApprovals();
    }, 1500);
    setInterval(refreshPc, 5000);
  }

  start();
})();
