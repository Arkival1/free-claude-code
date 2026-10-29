// Settings: the default brain, free cloud keys, the PC link, voice, backups.
import { state, save, changed, chatOf, newAgent, DEFAULT_TEAM, VERSION } from "../state.js";
import { el, button, card, go, notify, ago, bytes } from "../ui.js";
import { PROVIDERS, CLOUD, listModels, brainReady, think } from "../brains.js";
import { pair, unpair, sync } from "../sync.js";
import * as engine from "../engine.js";
import { store } from "../store.js";
import { findPlugins } from "../plugins.js";
import { ITEMS } from "./more.js";

// What the search bar finds besides plugins: every screen and setting.
const FEATURES = [
  ...ITEMS.map(([route, , title, sub]) => [title, sub, route]),
  ["Home", "Jarvis's command center: talk, quick commands, agents at work", "home"],
  ["Chats", "Talk to any agent", "chats"],
  ["Agents", "The team: each agent's brain, tools and instructions", "agents"],
  ["Models", "AI models on this phone: download, load, test speed", "models"],
  ["Brain", "Which AI every agent thinks with by default", "settings"],
  ["Free cloud keys", "Gemini, Groq, OpenRouter or any OpenAI-style service", "settings"],
  ["Connect to my PC", "Pair with FCC Studio on your PC (optional)", "settings"],
  ["Voice", "Jarvis speaks his replies", "settings"],
  ["Backup", "Save or restore everything on this phone", "settings"],
];

export function render(view) {
  const settings = state.settings;
  const brains = el("select", { "aria-label": "Default brain" }, [
    el("option", { value: "", text: "Choose…" }),
    ...Object.entries(PROVIDERS)
      .filter(([id]) => id !== "pc" || settings.pc)
      .map(([id, provider]) => el("option", { value: id, text: `${provider.label}${brainReady(id) ? "" : " (not set up)"}` })),
  ]);
  brains.value = settings.brain || "";
  brains.addEventListener("change", async () => {
    settings.brain = brains.value;
    if (settings.brain === "local" && !settings.localModel) settings.localModel = (state.models.find((model) => model.ready) || {}).id || "";
    await save.settings();
    changed("settings");
    notify(settings.brain ? `Agents now think with ${PROVIDERS[settings.brain].label} by default.` : "No brain picked.");
    if (settings.brain === "local" && !brainReady("local")) go("models");
  });
  const usage = el("p", { class: "muted small" });
  engine.storage().then((estimate) => {
    if (estimate) usage.textContent = `Storage used by FCC Phone: ${bytes(estimate.usage)} of ${bytes(estimate.quota)} allowed.`;
  });
  view.replaceChildren(
    searchCard(),
    card("Brain", [
      el("label", {}, ["Agents think with", brains]),
      el("p", { class: "muted", text: "On this phone: a model from Models, free and private. Cloud: paste a free key below. My PC: once paired. Each agent can also have its own brain (Agents, Team brains)." }),
      el("label", { class: "check" }, [
        el("input", { type: "checkbox", checked: settings.fallback !== false, "aria-label": "Use the next brain that is set up", onchange: async (event) => {
          settings.fallback = event.target.checked;
          await save.settings();
          changed("settings");
        } }),
        el("span", { text: "If an agent's brain isn't set up (no model on this phone yet), use the next one that is: a model on this phone, then a free cloud key, then your PC if it's paired. Works without the PC." }),
      ]),
      button("Test the brain", async () => {
        notify("Asking…");
        try {
          const reply = await think({ brain: "default", role: "assistant", name: "Test" }, "Answer in five words or fewer.", [{ role: "user", content: "Say hello." }], []);
          notify(`${PROVIDERS[settings.brain]?.label || "Brain"}: ${reply.text || "(no words)"}`);
        } catch (error) {
          notify(error.message);
        }
      }),
    ]),
    ...CLOUD.map(providerCard),
    pcCard(),
    card("Voice", [
      el("label", { class: "check" }, [
        el("input", { type: "checkbox", checked: settings.speak, "aria-label": "Speak replies", onchange: async (event) => {
          settings.speak = event.target.checked;
          await save.settings();
          changed("settings");
        } }),
        el("span", { text: "Jarvis speaks his replies out loud" }),
      ]),
      el("p", { class: "muted small", text: "The 🎤 buttons and the keyboard's microphone both work for talking." }),
    ]),
    card("Backup", [
      el("p", { class: "muted", text: "Agents, chats, memories, projects, studies, and to-dos live only on this phone. Save a backup now and then (keys, the PC link, and model files are left out)." }),
      el("div", { class: "row" }, [button("Save a backup", exportBackup), importButton()]),
      usage,
    ]),
    el("p", { class: "muted small center", text: `FCC Phone ${VERSION}` })
  );
}

function providerCard(id) {
  const provider = PROVIDERS[id];
  const settings = state.settings;
  const key = el("input", { type: "password", value: settings.keys[id] || "", "aria-label": `${provider.label} key`, autocomplete: "off", placeholder: "Paste your key" });
  const base = id === "custom" ? el("input", { value: settings.customBase || "", "aria-label": "Service address", placeholder: "https://…/v1" }) : null;
  const models = el("select", { "aria-label": `${provider.label} model` });
  const status = el("p", { class: "muted", role: "status" });
  const fill = (rows) => {
    const list = rows.length ? rows : [{ id: settings.models[id] || "" }];
    models.replaceChildren(...list.filter((row) => row.id).map((row) => el("option", { value: row.id, text: row.id })));
    if (settings.models[id]) models.value = settings.models[id];
  };
  fill(state.modelLists[id] || []);
  models.addEventListener("change", async () => {
    settings.models[id] = models.value;
    await save.settings();
    changed("settings");
  });
  const saveKey = async () => {
    settings.keys[id] = key.value.trim();
    if (base) settings.customBase = base.value.trim();
    if (!settings.brain && settings.keys[id]) settings.brain = id;
    await save.settings();
    status.textContent = "Loading models…";
    try {
      const rows = await listModels(id);
      fill(rows);
      status.textContent = rows.length ? `Saved. ${rows.length} models; using ${settings.models[id]}.` : "Saved.";
    } catch (error) {
      status.textContent = error.message;
    }
    changed("settings");
  };
  return card(provider.label, [
    el("p", { class: "muted" }, [provider.note, " ", provider.keyUrl ? el("a", { href: provider.keyUrl, target: "_blank", rel: "noopener", text: "Get a free key" }) : null]),
    base ? el("label", {}, ["Address", base]) : null,
    el("label", {}, ["Key", key]),
    el("label", {}, ["Model", models]),
    button("Save", saveKey, { "aria-label": `Save ${provider.label}` }),
    status,
  ]);
}

// Pairing takes a moment: draw Settings again only if it is still on screen.
function redraw() {
  if (state.route === "settings") render(document.getElementById("view"));
}

function pcCard() {
  const pc = state.settings.pc;
  if (pc) {
    return card("My PC", [
      el("p", {}, ["Paired with ", el("strong", { text: pc.pcName || "your PC" }), ` at ${pc.address}. Its AI: ${pc.main || "Jarvis"} on ${pc.model || "?"} (${pc.private ? "runs on the PC" : "a server AI"}).`]),
      pc.broken ? el("p", { class: "warn", text: "The PC no longer knows this phone. Unpair, then pair again with a new code." }) : null,
      el("p", { class: "muted", text: `Last sync ${ago(pc.lastSync)}. Memories sync when you open the app and after new ones are saved.` }),
      el("label", { class: "check" }, [
        el("input", { type: "checkbox", checked: state.settings.cloudSeesPc, "aria-label": "Let cloud brains see PC memories", onchange: async (event) => {
          state.settings.cloudSeesPc = event.target.checked;
          await save.settings();
          changed("memory");
        } }),
        el("span", { text: "Let cloud brains (Gemini, Groq, OpenRouter) read memories from my PC" }),
      ]),
      el("p", { class: "muted small", text: "Off keeps your PC's memory bank away from cloud AIs, like on the PC. Phone models always may." }),
      el("div", { class: "row" }, [
        button("Sync now", () => sync().catch(() => {})),
        button("Unpair", async () => {
          if (!confirm("Unpair from your PC? Memories stay on both.")) return;
          await unpair();
          redraw();
        }, { class: "danger" }),
      ]),
    ]);
  }
  const address = el("input", { "aria-label": "PC address", placeholder: "https://your-pc.tail1234.ts.net", autocapitalize: "off", autocorrect: "off" });
  const code = el("input", { "aria-label": "Pairing code", placeholder: "ABCD-2345", autocapitalize: "characters", autocorrect: "off" });
  const status = el("p", { class: "muted", role: "status" });
  return card("Connect to my PC", [
    el("p", { class: "muted", text: "Optional. Pairing shares memories with FCC Studio on your PC, lets agents here think with your PC's AI, and gives the Researcher web search." }),
    el("ol", { class: "steps" }, [
      el("li", { text: "Install Tailscale (free) on your PC and this phone, signed in to the same account." }),
      el("li", { text: "On the PC, run  tailscale serve --bg 8082  once." }),
      el("li", { text: "In Studio on the PC: More, FCC Phone, Make a pairing code." }),
    ]),
    el("label", {}, ["PC address", address]),
    el("label", {}, ["Pairing code", code]),
    button("Pair", async () => {
      status.textContent = "Pairing…";
      try {
        await pair(address.value, code.value);
        notify("Paired with your PC.");
        redraw();
      } catch (error) {
        status.textContent = error.message;
      }
    }, { class: "primary" }),
    status,
  ]);
}

function searchCard() {
  const box = el("input", { type: "search", "aria-label": "Search FCC", placeholder: "Search features, settings, APIs and plugins" });
  const results = el("div", { class: "search-results" });
  const row = (title, sub, action, label) =>
    el("button", { class: "item as-button", type: "button", onclick: action, "aria-label": label || title }, [
      el("div", { class: "grow" }, [el("strong", { text: title }), el("small", { text: sub })]),
    ]);
  const link = (title, sub, href) =>
    el("a", { class: "item", href, target: "_blank", rel: "noopener noreferrer" }, [el("div", { class: "grow" }, [el("strong", { text: title }), el("small", { text: sub })])]);
  box.addEventListener("input", () => {
    const query = box.value.trim().toLowerCase();
    if (!query) return results.replaceChildren();
    const features = FEATURES.filter(([title, sub]) => `${title} ${sub}`.toLowerCase().includes(query)).slice(0, 6);
    const keys = Object.values(PROVIDERS).filter((item) => item.keyUrl && `${item.label} ${item.note} key api`.toLowerCase().includes(query));
    const plugins = findPlugins(query, 6);
    results.replaceChildren(
      ...features.map(([title, sub, route]) => row(title, sub, () => go(route))),
      ...keys.map((item) => link(`Get a free ${item.label} key`, item.note, item.keyUrl)),
      ...plugins.map((item) => row(`Plugin: ${item.name}`, `${item.about} · ${item.needsKey ? "needs a key" : "no key"} · ${item.on ? "on" : "off"}`, () => go(`plugins/${encodeURIComponent(item.name)}`), `Plugin ${item.name}`)),
      ...(features.length || keys.length || plugins.length ? [] : [el("p", { class: "empty", text: "Nothing found. Try other words." })])
    );
  });
  return card("Search", [box, results]);
}

async function exportBackup() {
  const chats = {};
  for (const agent of state.agents) chats[agent.id] = await chatOf(agent.id);
  const { keys, pc, plugins, ...settings } = state.settings;
  // Plugin keys stay on the phone, like the cloud keys: only their switches go.
  settings.plugins = Object.fromEntries(Object.entries(plugins || {}).map(([name, saved]) => [name, { on: Boolean(saved.on), hosts: saved.hosts || [] }]));
  const backup = {
    app: "FCC Phone",
    version: VERSION,
    saved_at: new Date().toISOString(),
    settings,
    agents: state.agents,
    memories: state.memories,
    projects: state.projects,
    rooms: state.rooms,
    todos: state.todos,
    studies: state.studies,
    chats,
  };
  const link = el("a", { href: URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" })), download: `fcc-phone-backup-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.append(link);
  link.click();
  link.remove();
}

function importButton() {
  const input = el("input", { type: "file", accept: "application/json,.json", class: "visually-hidden", "aria-label": "Backup file" });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      const backup = JSON.parse(await file.text());
      if (backup.app !== "FCC Phone") throw new Error("That isn't an FCC Phone backup.");
      if (!confirm("Replace this phone's agents, chats, memories, and projects with the backup?")) return;
      state.agents = (backup.agents || []).map((agent) => (agent.tools ? agent : newAgent(agent)));
      if (!state.agents.some((agent) => agent.id === "jarvis")) state.agents.unshift(newAgent(DEFAULT_TEAM[0]));
      state.memories = (backup.memories || []).map((memory) => ({ ...memory, synced: false }));
      for (const key of ["projects", "rooms", "todos", "studies"]) state[key] = backup[key] || [];
      // Keys stay as they are on this phone; a backup only carries switches.
      const kept = state.settings.plugins || {};
      const restored = (backup.settings && backup.settings.plugins) || {};
      const plugins = Object.fromEntries(
        [...new Set([...Object.keys(kept), ...Object.keys(restored)])].map((name) => [name, { ...(restored[name] || {}), key: (kept[name] || {}).key || "" }])
      );
      Object.assign(state.settings, backup.settings || {}, { keys: state.settings.keys, pc: state.settings.pc, plugins });
      await Promise.all([save.agents(), save.memories(), save.settings(), save.projects(), save.rooms(), save.todos(), save.studies()]);
      for (const [agentId, chat] of Object.entries(backup.chats || {})) {
        state.chats[agentId] = chat;
        await store.set(`chat:${agentId}`, chat);
      }
      notify("Backup restored.");
      go("home");
    } catch (error) {
      notify(error.message);
    }
  });
  return el("span", {}, [input, button("Restore a backup", () => input.click())]);
}
