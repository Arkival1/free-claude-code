// FCC Linux's internet: off until the user switches it on (Lab, FCC Linux).
//
// Programs inside reach the web as plain http://host/path: v86's "fetch"
// network takes port 80 only, so nothing inside does TLS. The box hands each
// request to the page, and this file makes the real https request (the
// secure part runs here, outside the box) and decides what's allowed:
//   - the switch is off: 403 and a plain message, nothing leaves the phone;
//   - fcc.plugins: a plugin the user switched on (More, Plugins) with its key
//     filled in here, never inside Linux;
//   - api.github.com: the user's GitHub token is added here, never inside
//     Linux; a change (POST, PATCH, PUT, DELETE) waits for the user's OK;
//   - package indexes (PyPI, npm, crates, Go): their https links are turned
//     into http ones, so pip, npm, cargo and go fetch through here too;
//   - a site that doesn't let apps in a browser call it: 502 and a message.
// Every request is logged (host, path, status) for the user to see.
import { state, save, changed } from "./state.js";
import { byName, usePlugin } from "./plugins.js";

const LOG_SIZE = 120;
const APPROVAL_MS = 10 * 60 * 1000;
const approved = new Map(); // "owner/repo" -> until when changes are allowed
const BODY_LIMIT = 200 * 1048576;
export const netLog = [];
const watchers = new Set();

const settings = () => state.settings.linux || {};
/** Is FCC Linux's internet switched on? */
export const internetOn = () => Boolean(settings().internet);
/** Is a GitHub token saved (for FCC Linux's fcc-github)? */
export const githubTokenSaved = () => Boolean(settings().githubToken);

async function update(change) {
  state.settings.linux = { ...settings(), ...change };
  await save.settings();
  changed("linux");
}
export const setInternet = (on) => update({ internet: Boolean(on) });
export const setGithubToken = (token) => update({ githubToken: String(token || "").trim() });

/** Watch the request log; returns a stop function. */
export function watchNet(watch) {
  watchers.add(watch);
  return () => watchers.delete(watch);
}
function log(entry) {
  netLog.unshift({ at: Date.now(), ...entry });
  netLog.length = Math.min(netLog.length, LOG_SIZE);
  for (const watch of watchers) watch(netLog[0]);
}

const text = (status, message) => ({ status, headers: [["content-type", "text/plain; charset=utf-8"]], body: new TextEncoder().encode(`${message}\n`).buffer });

// Package indexes list their downloads as https links; inside Linux those must
// be http, so they come back through here (and are fetched as https here).
const REWRITE = [
  [/^pypi\.org$/, ["https://files.pythonhosted.org/", "http://files.pythonhosted.org/"], ["https://pypi.org/", "http://pypi.org/"]],
  [/^registry\.npmjs\.org$/, ["https://registry.npmjs.org/", "http://registry.npmjs.org/"]],
  [/^index\.crates\.io$/, ["https://static.crates.io/", "http://static.crates.io/"]],
  [/^rubygems\.org$/, ["https://rubygems.org/", "http://rubygems.org/"]],
];
// What cargo needs from crates.io's index root, which doesn't answer apps in a
// browser itself: where crates download from.
const CRATES_CONFIG = JSON.stringify({ dl: "http://static.crates.io/crates", api: "http://crates.io" });

/** Plain words for a request to show the user. */
function describe(method, url) {
  return `${method} ${url.hostname}${url.pathname.length > 50 ? `${url.pathname.slice(0, 50)}…` : url.pathname}`;
}

/** fcc.status: what's switched on (for fcc-net inside Linux). */
function status() {
  const plugins = Object.entries(state.settings.plugins || {}).filter(([, saved]) => saved.on).map(([name]) => name);
  return text(200, [`Internet: ${internetOn() ? "on" : "off (switch it on in FCC: Lab, FCC Linux)"}`, `GitHub token: ${githubTokenSaved() ? "saved in FCC" : "not saved (add it in FCC: Lab, FCC Linux)"}`, `Plugins on: ${plugins.length ? plugins.join(", ") : "none (More, Plugins)"}`, state.settings.pluginsOn === false ? "Plugin APIs are switched off in More, Plugins." : ""].filter(Boolean).join("\n"));
}

/** fcc.plugins/call?plugin=NAME&url=URL: one plugin call, its key added here. */
async function plugin(url) {
  const name = url.searchParams.get("plugin") || "";
  const address = url.searchParams.get("url") || "";
  const item = byName(name);
  if (!item) return text(404, `There's no plugin called ${name}. The list is in FCC: More, Plugins.`);
  try {
    const answer = await usePlugin({ action: "call", plugin: item.name, url: address });
    return text(200, answer);
  } catch (error) {
    return text(403, error.message);
  }
}

/**
 * One request from inside FCC Linux: { url, method, headers: [[name, value]],
 * body }. ask(question) shows the user a yes/no (for GitHub changes). Returns
 * { status, headers, body (ArrayBuffer) }.
 */
export async function handle(request, { ask = (question) => confirm(question) } = {}) {
  let url;
  try {
    url = new URL(String(request.url));
  } catch {
    return text(400, "That isn't a web address.");
  }
  const method = String(request.method || "GET").toUpperCase();
  if (url.hostname === "fcc.status") return status();
  if (!internetOn()) {
    log({ what: describe(method, url), status: "off" });
    return text(403, "FCC Linux's internet is off. The user switches it on in FCC: Lab, FCC Linux (Internet).");
  }
  if (url.hostname === "fcc.plugins") {
    const answer = await plugin(url);
    log({ what: `plugin ${url.searchParams.get("plugin") || ""}`, status: answer.status });
    return answer;
  }
  if (url.hostname === "index.crates.io" && url.pathname === "/config.json") return { status: 200, headers: [["content-type", "application/json"]], body: new TextEncoder().encode(CRATES_CONFIG).buffer };
  url.protocol = "https:";
  if (url.port === "80") url.port = "";
  const headers = new Headers();
  for (const [name, value] of Array.isArray(request.headers) ? request.headers : []) {
    const lower = String(name).toLowerCase();
    // The browser sets these itself; a token only ever comes from FCC.
    if (["host", "connection", "content-length", "accept-encoding", "authorization", "cookie", "origin", "referer"].includes(lower)) continue;
    try {
      headers.append(name, value);
    } catch {
      // A header the browser won't send.
    }
  }
  if (url.hostname === "api.github.com") {
    const token = settings().githubToken;
    if (token) headers.set("authorization", `Bearer ${token}`);
    if (!["GET", "HEAD"].includes(method)) {
      // One OK covers one repository for ten minutes (a push is several calls).
      const repo = (/^\/repos\/([^/]+\/[^/]+)/.exec(url.pathname) || [])[1] || url.pathname;
      if (!((approved.get(repo) || 0) > Date.now())) {
        const ok = await ask(`FCC Linux wants to change ${repo} on GitHub (${method} ${url.pathname.slice(0, 80)}).\n\nAllow changes to ${repo} for the next 10 minutes?`);
        if (!ok) {
          log({ what: describe(method, url), status: "denied" });
          return text(403, "The user said no to this GitHub change.");
        }
        approved.set(repo, Date.now() + APPROVAL_MS);
      }
    }
  }
  let response;
  try {
    response = await fetch(url.href, { method, headers, body: ["GET", "HEAD"].includes(method) ? undefined : request.body, redirect: "follow", credentials: "omit" });
  } catch {
    log({ what: describe(method, url), status: "blocked" });
    return text(502, `${url.hostname} doesn't let apps in a browser reach it, so FCC Linux can't use it from the phone.`);
  }
  let body = await response.arrayBuffer();
  if (body.byteLength > BODY_LIMIT) return text(413, `${url.hostname} sent more than ${BODY_LIMIT / 1048576} MB in one answer.`);
  const rule = REWRITE.find(([host]) => host.test(url.hostname));
  const kind = response.headers.get("content-type") || "";
  if (rule && /json|html|text|xml/.test(kind)) {
    let words = new TextDecoder().decode(body);
    for (const [from, to] of rule.slice(1)) words = words.replaceAll(from, to);
    body = new TextEncoder().encode(words).buffer;
  }
  const out = [];
  for (const [name, value] of response.headers) if (!["content-encoding", "content-length", "transfer-encoding", "set-cookie"].includes(name)) out.push([name, value]);
  log({ what: describe(method, url), status: response.status });
  return { status: response.status, headers: out, body };
}
