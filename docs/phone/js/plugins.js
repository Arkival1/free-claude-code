// Plugins on the phone itself: free APIs from the catalog (apis.js), switched
// on here, with their keys kept on this phone. Agents find the best fit for a
// job and call it with the use_plugin tool; no PC needed.
//
// Keys never reach a model: an agent writes {key} where the key goes, and the
// key is filled in only for the API addresses the user approved for it.
import { state, save, changed } from "./state.js";
import { APIS } from "./apis.js";
import { words } from "./ui.js";

const CALL_CHARS = 6000;

/** One catalog row as an object, with its switch and key status. */
export function plugin(row) {
  const [name, about, auth, cors, link, category] = row;
  const saved = (state.settings.plugins || {})[name] || {};
  return {
    name,
    about,
    needsKey: auth === "key",
    browserOk: cors === "yes",
    link,
    category,
    on: Boolean(saved.on),
    hasKey: Boolean(saved.key),
    hosts: saved.hosts || [],
  };
}

export const allPlugins = () => APIS.map(plugin);
export const byName = (name) => {
  const wanted = String(name || "").trim().toLowerCase();
  const row = APIS.find((item) => item[0].toLowerCase() === wanted);
  return row ? plugin(row) : null;
};

/** The plugins that fit a need best: names and descriptions that share its
 * words, then the ones ready to use now (switched on, no key, answer phones). */
export function findPlugins(need, limit = 6) {
  const wanted = words(need);
  if (!wanted.length) return [];
  const scored = [];
  for (const row of APIS) {
    const name = row[0].toLowerCase();
    const about = `${row[1]} ${row[5]}`.toLowerCase();
    let score = 0;
    for (const word of wanted) {
      if (name.includes(word)) score += 3;
      if (about.includes(word)) score += 1;
    }
    if (!score) continue;
    const item = plugin(row);
    // Ready to use now counts: switched on, no key needed, answers phones.
    scored.push([score + (item.on ? 2 : 0) + (item.needsKey ? 0 : 1.5) + (item.browserOk ? 0.5 : 0), item]);
  }
  return scored.sort((a, b) => b[0] - a[0]).slice(0, limit).map(([, item]) => item);
}

export function hostOf(address) {
  try {
    return new URL(address).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/** Switch a plugin on or off; a key and the API addresses it may be sent to. */
export async function setPlugin(name, { on, key, hosts } = {}) {
  const item = byName(name);
  if (!item) throw new Error(`No plugin called ${name}.`);
  state.settings.plugins = state.settings.plugins || {};
  const saved = state.settings.plugins[item.name] || {};
  const next = { ...saved };
  if (on !== undefined) next.on = Boolean(on);
  if (key !== undefined) next.key = String(key).trim();
  if (hosts !== undefined) next.hosts = [...new Set(hosts.map((host) => String(host).trim().toLowerCase()).filter(Boolean))];
  if (next.key && !(next.hosts || []).length) next.hosts = [hostOf(item.link)].filter(Boolean);
  state.settings.plugins[item.name] = next;
  await save.settings();
  changed("plugins");
  return byName(item.name);
}

function describe(item) {
  const status = item.on ? (item.needsKey && !item.hasKey ? "on, but its key isn't saved yet" : "on") : "off (the user switches it on in More, Plugins)";
  return `- ${item.name} [${item.category}]: ${item.about} · ${item.needsKey ? "needs an API key" : "no key needed"} · ${status} · docs ${item.link}`;
}

/** The use_plugin tool: find the best plugin for a need, or call one. */
export async function usePlugin(args) {
  const action = String(args.action || "find");
  if (action === "find") {
    const found = findPlugins(String(args.need || args.query || ""));
    if (!found.length) return "No plugin in the catalog matches that. Try other words, or use read_page or wikipedia.";
    return `Plugins that fit (pick the best one; read its docs with read_page to find the address to call):\n${found.map(describe).join("\n")}`;
  }
  if (action !== "call") throw new Error("action is find or call.");
  const item = byName(args.plugin);
  if (!item) throw new Error(`No plugin called ${args.plugin}. Use action find first.`);
  if (!item.on) throw new Error(`${item.name} is off. Ask the user to switch it on in More, Plugins.`);
  const url = String(args.url || "");
  if (!/^https:\/\//i.test(url)) throw new Error("Give the full https:// address to call.");
  const headers = {};
  for (const [name, value] of Object.entries(args.headers && typeof args.headers === "object" ? args.headers : {})) {
    headers[String(name).slice(0, 60)] = String(value).slice(0, 300);
  }
  const wantsKey = url.includes("{key}") || Object.values(headers).some((value) => value.includes("{key}"));
  const saved = (state.settings.plugins || {})[item.name] || {};
  let address = url;
  if (wantsKey) {
    if (!saved.key) throw new Error(`${item.name} needs its API key: the user adds it in More, Plugins.`);
    if (!(saved.hosts || []).includes(hostOf(url))) {
      throw new Error(`${item.name}'s key is only sent to ${(saved.hosts || []).join(", ") || "its own address"}; the user can add ${hostOf(url)} in More, Plugins.`);
    }
    address = url.replaceAll("{key}", encodeURIComponent(saved.key));
    for (const name of Object.keys(headers)) headers[name] = headers[name].replaceAll("{key}", saved.key);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(address, { headers, signal: controller.signal });
    let body = await response.text();
    // An API that echoes the key back never hands it to the model.
    if (saved.key) body = body.replaceAll(saved.key, "[key]");
    return `${item.name} answered ${response.status}:\n${body.slice(0, CALL_CHARS)}`;
  } catch (error) {
    if (error.name === "AbortError") throw new Error(`${item.name} took too long to answer.`);
    throw new Error(`${item.name} couldn't be reached from the phone (it may not allow apps in a browser to call it).`);
  } finally {
    clearTimeout(timer);
  }
}
