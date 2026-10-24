// FCC Phone: your own agents, models, and memory, on your phone.
import { state, load, save, changed, onChange, feed, VERSION, upgradeAgent } from "./state.js";
import { $, el, notify, closeSheet } from "./ui.js";
import { sync } from "./sync.js";
import { speak } from "./voice.js";
import { calculate, findImages, remember, recall, canRead } from "./tools.js";
import { bestModel } from "./brains.js";
import { readGguf } from "./gguf.js";
import { checkProject, bundle, previewHtml, zipProject } from "./projects.js";
import { recoverFromCrash } from "./engine.js";
import { markUnanswered } from "./agents.js";
import { polishNotes } from "./polish.js";
import { lookAtSite, describeLook } from "./inspect.js";
import { templateFiles } from "./templates.js";
import * as hud from "./views/hud.js";
import * as chat from "./views/chat.js";
import * as agents from "./views/agents.js";
import * as models from "./views/models.js";
import * as projects from "./views/projects.js";
import * as rooms from "./views/rooms.js";
import * as learn from "./views/learn.js";
import * as todos from "./views/todos.js";
import * as memory from "./views/memory.js";
import * as settings from "./views/settings.js";
import * as more from "./views/more.js";

const view = $("view");
const TITLES = {
  chats: "Chats",
  chat: "Chat",
  agents: "Agents",
  models: "Models",
  more: "More",
  projects: "Projects",
  rooms: "Agent rooms",
  learn: "Learn",
  todos: "To-dos",
  memory: "Memory",
  settings: "Settings",
  help: "Help",
};
const TAB_OF = { home: "home", chats: "chats", chat: "chats", agents: "agents", models: "models" };
let cleanup = null;
let renderId = 0;

async function render() {
  const [name, param] = (location.hash || "#home").slice(1).split("/");
  const route = name in TITLES || name === "home" ? name : "home";
  state.route = route;
  renderId += 1;
  const mine = renderId;
  if (typeof cleanup === "function") cleanup();
  cleanup = null;
  closeSheet();
  document.body.dataset.route = route;
  const tab = TAB_OF[route] || "more";
  for (const button of document.querySelectorAll(".tab")) {
    if (button.dataset.route === tab) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  $("title").textContent = TITLES[route] || "FCC Phone";
  $("back").hidden = route === "home" || ["chats", "agents", "models", "more"].includes(route);
  drawPill();
  const screens = {
    home: () => hud.render(view),
    chats: () => chat.renderList(view),
    chat: () => chat.render(view, param),
    agents: () => agents.render(view, param),
    models: () => models.render(view),
    more: () => more.render(view),
    projects: () => projects.render(view, param),
    rooms: () => rooms.render(view, param),
    learn: () => learn.render(view, param),
    todos: () => todos.render(view),
    memory: () => memory.render(view),
    settings: () => settings.render(view),
    help: () => more.renderHelp(view),
  };
  try {
    const result = await screens[route]();
    if (mine !== renderId) {
      if (typeof result === "function") result();
      return;
    }
    cleanup = result;
  } catch (error) {
    view.replaceChildren(el("p", { class: "warn", text: `Something went wrong here: ${error.message}` }));
  }
  if (route !== "chat" && route !== "rooms") window.scrollTo(0, 0);
}

function drawPill() {
  const pill = $("link-pill");
  const pc = state.settings.pc;
  pill.hidden = !pc || state.route === "home";
  if (pc) {
    pill.textContent = pc.broken ? "PC: pair again" : `PC ${pc.lastSync ? "✓" : "…"}`;
    pill.className = `pill ${pc.broken ? "" : "good"}`;
  }
}

function checkReminders() {
  const now = Date.now();
  let due = false;
  for (const item of state.todos) {
    if (!item.done && item.due_at && !item.notified && item.due_at <= now) {
      item.notified = true;
      due = true;
      notify(`Reminder: ${item.text}`);
      feed("Reminder", item.text, "start");
      speak(`Reminder: ${item.text}`, { force: state.settings.speak });
    }
  }
  if (due) {
    save.todos();
    changed("todos");
  }
}

for (const button of document.querySelectorAll(".tab")) {
  button.addEventListener("click", () => {
    location.hash = button.dataset.route;
  });
}
$("back").addEventListener("click", () => history.back());
$("sheet").addEventListener("click", (event) => {
  if (event.target.hasAttribute("data-close")) closeSheet();
});
window.addEventListener("hashchange", render);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.settings.pc) sync({ quiet: true }).catch(() => {});
});
onChange((what) => {
  if (what === "pc") drawPill();
});

if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

// For the app's own tests: helpers they can call directly.
window.fccPhone = {
  version: VERSION,
  calculate,
  bestModel,
  readGguf,
  checkProject,
  bundle,
  previewHtml,
  zipProject,
  polishNotes,
  lookAtSite,
  describeLook,
  templateFiles,
  findImages,
  remember,
  recall,
  canRead,
  upgradeAgent,
  save,
  state,
  checkReminders,
};

// Resolves once saved data is loaded and the first screen is drawn.
window.fccPhone.ready = load().then(async () => {
  // If iOS closed the app mid-reply last time, say what happened.
  const crash = await recoverFromCrash().catch(() => "");
  await markUnanswered(crash).catch(() => {});
  await render();
  if (crash) notify(crash);
  setInterval(checkReminders, 20000);
  checkReminders();
  if (state.settings.pc) sync({ quiet: true }).catch(() => {});
});
