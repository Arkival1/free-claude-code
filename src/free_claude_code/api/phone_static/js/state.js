// Everything the app knows, loaded from the phone and saved back as it changes.
import { store } from "./store.js";

export const VERSION = "2.3.1";

export const PHONE_TOOLS = {
  remember: "Memory",
  recall: "Memory",
  calculate: "Everyday",
  weather: "Internet",
  wikipedia: "Internet",
  read_page: "Internet",
  web_search: "Internet",
  todo: "Everyday",
  start_project: "Code and files",
  write_file: "Code and files",
  read_file: "Code and files",
  edit_file: "Code and files",
  list_files: "Code and files",
  delete_file: "Code and files",
  check_project: "Code and files",
  restore_file: "Code and files",
  polish_check: "Code and files",
  look_at_site: "Code and files",
  find_images: "Internet",
  list_photos: "Code and files",
  use_photo: "Code and files",
  ask_agent: "Team",
  team_status: "Team",
  learn: "Memory",
};
export const ALL_TOOLS = Object.keys(PHONE_TOOLS);
export const MAIN_ONLY = new Set(["team_status"]);
/** Tools that read the user's memory, kept from cloud brains on the phone too. */
export const MEMORY_TOOLS = new Set(["recall", "learn"]);

const FILES = ["start_project", "write_file", "read_file", "edit_file", "list_files", "delete_file", "check_project", "restore_file"];
const DESIGN = ["find_images", "polish_check", "look_at_site"];
const PHOTOS = ["list_photos", "use_photo"];
export const ROLE_TOOLS = {
  main: ["remember", "recall", "calculate", "weather", "wikipedia", "web_search", "todo", "ask_agent", "team_status", "learn", "list_photos"],
  builder: [...FILES, ...PHOTOS, ...DESIGN, "remember", "recall", "calculate", "read_page", "wikipedia", "ask_agent"],
  researcher: ["wikipedia", "read_page", "web_search", "remember", "recall", "calculate"],
  helper: ["remember", "recall", "calculate", "todo", "weather", "wikipedia"],
  tester: ["list_files", "read_file", "check_project", "look_at_site", "polish_check", "edit_file", "write_file", "restore_file", "remember", "recall"],
  assistant: ["remember", "recall", "calculate", "weather", "wikipedia"],
};

export const ROLE_PROMPTS = {
  main:
    "You are the user's personal AI and you run their team of agents. Answer quickly and warmly. Hand real work to the right agent with ask_agent: websites and code to the Builder, facts and comparisons to the Researcher, plans to the Helper, checking a project to the Tester. Keep the user's to-do list with todo, and start studying a subject with learn when asked. Your memory is your own: remember keeps a fact to yourself unless you set share, which puts it where every agent reads it; recall searches yours, the team's, and every agent's. Photos the user sends go to Business photos (list_photos); tell the Builder to use them.",
  builder:
    "You build complete, professional websites and small apps as files in a project. For a new one, use start_project with the closest template: business for any café, shop, salon, restaurant, trade, or studio, or any site with several pages (five linked pages with a photo hero, phone menu, tabs with prices, gallery viewer, and contact form: keep its structure, class names, and app.js); website or landing for one page; webapp; game. Then make it the user's on every page: real content for this job (names, text, prices, hours), rewriting a page with write_file or changing parts with edit_file, and set the colours at the top of styles.css. Every placeholder line and drawn placeholder picture must go. Make it look designed: a Google Font pair, a small colour palette in :root variables, generous spacing, and real photos: first the user's own business photos (list_photos shows them with the user's notes, which are facts for the site; use_photo puts one in the project), then free ones from find_images (use the https address in <img>, and credit each in the footer); give every <img> alt, width, and height and drop data-placeholder; draw icons as inline SVG. Before you finish, run check_project and fix what it finds, run look_at_site and fix what a visitor would see on a phone and a computer, then polish_check for finishing touches. If a change makes things worse, undo it with restore_file. Finish by saying what you built and which files.",
  researcher:
    "You find out facts before answering. Look things up with wikipedia, web_search, and read_page, compare sources, say where each fact came from, and say plainly when you are not sure.",
  helper:
    "You plan with the user: turn goals into short numbered steps, say how to check each one worked, and give a backup plan. Use calculate for every sum and todo for things to remember to do.",
  tester:
    "You test projects. List and read the files, run check_project and look_at_site (it opens the site on a phone and a computer), then fix real problems with edit_file or write_file; undo a bad change with restore_file. Report what you checked and what you fixed.",
  assistant: "You are a helpful assistant. Keep answers short and clear.",
};

// Starter prompts from earlier versions, upgraded when the user never edited them.
const OLD_PROMPTS = {
  main: [
    "You are the user's personal AI and you run their team of agents. Answer quickly and warmly. Hand real work to the right agent with ask_agent: websites and code to the Builder, facts and comparisons to the Researcher, plans to the Helper, checking a project to the Tester. Keep the user's to-do list with todo, and start studying a subject with learn when asked.",
  ],
  builder: [
    "You build complete, professional websites and small apps as files in a project. For a new one, use start_project with the closest template: business for any café, shop, salon, restaurant, trade, or studio, or any site with several pages (five linked pages with a photo hero, phone menu, tabs with prices, gallery viewer, and contact form: keep its structure, class names, and app.js); website or landing for one page; webapp; game. Then make it the user's on every page: real content for this job (names, text, prices, hours), rewriting a page with write_file or changing parts with edit_file, and set the colours at the top of styles.css. Every placeholder line and drawn placeholder picture must go. Make it look designed: a Google Font pair, a small colour palette in :root variables, generous spacing, and real photos from find_images (use the https address in <img> with alt, width, and height, drop data-placeholder, and credit each photo in the footer); draw icons as inline SVG. Before you finish, run check_project and fix what it finds, run look_at_site and fix what a visitor would see on a phone and a computer, then polish_check for finishing touches. If a change makes things worse, undo it with restore_file. Finish by saying what you built and which files.",
    "You build complete, professional websites and small apps as files in a project. For a new one, use start_project with the closest template (website, landing, webapp, game), then make it the user's: rewrite index.html in full with write_file, keeping the template's structure and class names but with real content for this job, and set the colours at the top of styles.css. Every placeholder line must go. Make it look designed: a Google Font pair, a small colour palette in :root variables, generous spacing, and real photos from find_images (use the https address in <img> with alt, width, and height, and credit each photo in the footer); draw icons as inline SVG. Before you finish, run check_project and fix what it finds, run look_at_site and fix what a visitor would see on a phone and a computer, then polish_check for finishing touches. If a change makes things worse, undo it with restore_file. Finish by saying what you built and which files.",
    "You build complete, good-looking websites and small apps as files in a project. Start a project with start_project if there is none, then write every file in full with write_file (index.html first, then style.css and script.js). Make pages mobile-friendly, with real content, a clear layout, and working buttons. Check your work with check_project and fix what it finds. Finish by saying what you built and which files.",
  ],
  tester: [
    "You test projects. List and read the files, run check_project, then fix real problems with edit_file or write_file. Report what you checked and what you fixed.",
  ],
};
/** Tools each role gained in an app version, added once to agents of that role. */
const TOOLS_ADDED = {
  2: { builder: ["restore_file", ...DESIGN], tester: ["look_at_site", "polish_check", "restore_file"] },
  3: { builder: PHOTOS, main: ["list_photos"] },
};
const TOOLS_VERSION = 3;

export const DEFAULT_TEAM = [
  { id: "jarvis", name: "Jarvis", role: "main" },
  { id: "builder", name: "Builder", role: "builder" },
  { id: "researcher", name: "Researcher", role: "researcher" },
  { id: "helper", name: "Helper", role: "helper" },
  { id: "tester", name: "Tester", role: "tester" },
];

export function newAgent(base) {
  return {
    instructions: ROLE_PROMPTS[base.role] || ROLE_PROMPTS.assistant,
    brain: "default",
    model: "",
    tools: [...(ROLE_TOOLS[base.role] || ROLE_TOOLS.assistant)],
    allTools: false,
    toolsVersion: TOOLS_VERSION,
    created_at: Date.now(),
    ...base,
  };
}

export const defaultSettings = () => ({
  brain: "",
  localModel: "",
  keys: { gemini: "", groq: "", openrouter: "", custom: "" },
  customBase: "",
  models: { gemini: "", groq: "", openrouter: "", custom: "" },
  noTools: {},
  pc: null,
  cloudSeesPc: false,
  speak: false,
  engine: { context: 4096, gpu: true },
});

export const state = {
  settings: defaultSettings(),
  agents: [],
  memories: [],
  pcMemories: [],
  projects: [],
  rooms: [],
  todos: [],
  studies: [],
  models: [],
  photos: [],
  chats: {},
  feed: [],
  jobs: [],
  route: "home",
  agentId: "jarvis",
  busy: new Set(),
  modelLists: {},
};

export const save = {
  settings: () => store.set("settings", state.settings),
  agents: () => store.set("agents", state.agents),
  memories: () => store.set("memories", state.memories),
  pcMemories: () => store.set("pcMemories", state.pcMemories),
  projects: () => store.set("projects", state.projects),
  rooms: () => store.set("rooms", state.rooms),
  todos: () => store.set("todos", state.todos),
  studies: () => store.set("studies", state.studies),
  models: () => store.set("models", state.models),
  photos: () => store.set("photos", state.photos),
  chat: (id) => store.set(`chat:${id}`, state.chats[id] || []),
};

export async function load() {
  const settings = await store.get("settings", {});
  state.settings = Object.assign(defaultSettings(), settings);
  const fresh = defaultSettings();
  state.settings.keys = Object.assign(fresh.keys, settings.keys);
  state.settings.models = Object.assign(fresh.models, settings.models);
  state.settings.engine = Object.assign(fresh.engine, settings.engine);
  const agents = await store.get("agents", []);
  // FCC Phone 1 kept agents without tools: give them their role's tools.
  state.agents = agents.map((agent) => (agent.tools ? agent : newAgent({ ...agent, role: agent.role === "main" ? "main" : agent.role || "assistant" })));
  for (const base of DEFAULT_TEAM) {
    if (!state.agents.some((agent) => agent.id === base.id)) {
      state.agents.push(newAgent(base));
    }
  }
  for (const agent of state.agents) upgradeAgent(agent);
  state.agents.sort((a, b) => (a.id === "jarvis" ? -1 : b.id === "jarvis" ? 1 : a.created_at - b.created_at));
  await save.agents();
  for (const key of ["memories", "pcMemories", "projects", "rooms", "todos", "studies", "models", "photos"]) {
    state[key] = await store.get(key, []);
  }
  // A study or job cut short when the app closed is picked up as stopped.
  for (const study of state.studies) if (study.status === "learning") study.status = "stopped";
  state.agentId = (await store.get("agentId", "jarvis")) || "jarvis";
  if (!state.agents.some((agent) => agent.id === state.agentId)) state.agentId = "jarvis";
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
}

/** Give an agent from an earlier version its role's new tools and prompt, once. */
export function upgradeAgent(agent) {
  const from = agent.toolsVersion || 1;
  for (let version = from + 1; version <= TOOLS_VERSION; version += 1) {
    for (const name of (TOOLS_ADDED[version] || {})[agent.role] || []) {
      if (!agent.tools.includes(name)) agent.tools.push(name);
    }
  }
  agent.toolsVersion = TOOLS_VERSION;
  if ((OLD_PROMPTS[agent.role] || []).includes(agent.instructions)) agent.instructions = ROLE_PROMPTS[agent.role];
  return agent;
}

export async function chatOf(id) {
  if (!state.chats[id]) state.chats[id] = await store.get(`chat:${id}`, []);
  return state.chats[id];
}

export const agentById = (id) => state.agents.find((agent) => agent.id === id);
export const jarvis = () => agentById("jarvis") || state.agents[0];

export function agentByName(name) {
  const wanted = String(name || "").replace(/^@/, "").trim().toLowerCase();
  return (
    state.agents.find((agent) => agent.name.toLowerCase() === wanted) ||
    state.agents.find((agent) => agent.name.toLowerCase().startsWith(wanted) && wanted.length > 1)
  );
}

/** The tools an agent really has: its own, or every tool when chosen. */
export function toolsOf(agent) {
  const names = agent.allTools ? ALL_TOOLS.filter((name) => agent.role === "main" || !MAIN_ONLY.has(name)) : agent.tools || [];
  return names.filter((name) => name !== "web_search" || state.settings.pc);
}

// Live events for the HUD feed and the agents-at-work panel.
const listeners = new Set();
export function onChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function changed(what) {
  for (const listener of listeners) {
    try {
      listener(what);
    } catch {
      /* one broken panel must not stop the rest */
    }
  }
}

export function feed(agentName, text, kind = "info") {
  state.feed.unshift({ at: Date.now(), agent: agentName, text, kind });
  state.feed.length = Math.min(state.feed.length, 80);
  changed("feed");
}
