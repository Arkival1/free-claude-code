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
// Copies kept elsewhere that let apps in a browser in, for sites that don't
// always: crates.io's index is also on GitHub (rust-lang/crates.io-index).
const MIRRORS = {
  "index.crates.io": (url) => `https://raw.githubusercontent.com/rust-lang/crates.io-index/master${url.pathname}`,
};
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
/** Hosts whose redirects (reads only) are followed: package indexes and
 * GitHub, which send downloads on to their own file servers. */
const FOLLOW = new Set([
  "pypi.org",
  "files.pythonhosted.org",
  "registry.npmjs.org",
  "index.crates.io",
  "static.crates.io",
  "crates.io",
  "rubygems.org",
  "proxy.golang.org",
  "sum.golang.org",
  "api.github.com",
  "github.com",
  "codeload.github.com",
  "raw.githubusercontent.com",
  "objects.githubusercontent.com",
]);

/** The calls fcc-github push makes (the only ones a 10-minute OK covers). */
const PUSH_STEPS = [
  ["POST", /^\/repos\/[^/]+\/[^/]+\/git\/(blobs|trees|commits)$/],
  ["PATCH", /^\/repos\/[^/]+\/[^/]+\/git\/refs\/heads\/.+$/],
];

/** True for FCC itself and anything local: the address FCC is served from,
 * the linked PC, this machine, the home network and Tailscale (where the PC
 * lives), by name or by number. FCC Linux only reaches the public internet. */
function offLimits(url) {
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (globalThis.location && location.hostname && host === location.hostname.toLowerCase()) return true;
  const pc = state.settings.pc && state.settings.pc.address;
  if (pc) {
    try {
      if (host === new URL(pc).hostname.toLowerCase()) return true;
    } catch {
      // Not an address: nothing to match.
    }
  }
  if (host.includes(":")) return LOCAL_V6.test(host);
  if (host === "localhost" || !host.includes(".") || /\.(localhost|local|internal|lan|home|ts\.net)$/.test(host)) return true;
  const v4 = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(host);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return a === 0 || a === 10 || a === 127 || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || a >= 224;
  }
  return false;
}
// IPv6 loopback, unspecified, private (fc00::/7), link-local (fe80::/10) and
// IPv4 written as IPv6.
const LOCAL_V6 = /^(::1?|f[cd][0-9a-f]{0,2}:.*|fe[89ab][0-9a-f]?:.*|::ffff:.*)$/;

/** An answer's bytes, or null once it passes BODY_LIMIT (the rest isn't read). */
async function readCapped(response) {
  if (!response.body) return new ArrayBuffer(0);
  const reader = response.body.getReader();
  const parts = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > BODY_LIMIT) {
      reader.cancel().catch(() => {});
      return null;
    }
    parts.push(value);
  }
  const out = new Uint8Array(size);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out.buffer;
}

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
  // FCC itself (the PC server or the phone app's own site) and local
  // addresses are never reachable from inside Linux: a program there could
  // otherwise read or change FCC through the page's connection.
  if (offLimits(url)) {
    log({ what: describe(method, url), status: "blocked" });
    return text(403, "FCC Linux can't reach FCC itself.");
  }
  const headers = new Headers();
  // Only headers a browser may send without asking the site first: anything
  // else makes the browser ask (a preflight), which most sites refuse. GitHub
  // allows its own API headers. A token only ever comes from FCC.
  const allowed = new Set(["accept", "accept-language", "content-language", "content-type", "range", ...(url.hostname === "api.github.com" ? ["x-github-api-version"] : [])]);
  for (const [name, value] of Array.isArray(request.headers) ? request.headers : []) {
    const lower = String(name).toLowerCase();
    if (!allowed.has(lower)) continue;
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
      // One OK covers one repository's push for ten minutes (a push is several
      // calls: new blobs, a tree, a commit, then moving the branch). Any other
      // change (deleting the repo, its settings, GraphQL, an organisation)
      // asks every time.
      const repo = (/^\/repos\/([^/]+\/[^/]+)/.exec(url.pathname) || [])[1] || "";
      const pushing = Boolean(repo) && PUSH_STEPS.some(([verb, path]) => verb === method && path.test(url.pathname));
      if (!pushing || !((approved.get(repo) || 0) > Date.now())) {
        const ok = await ask(pushing ? `FCC Linux wants to push to ${repo} on GitHub (${method} ${url.pathname.slice(0, 80)}).\n\nAllow pushing to ${repo} for the next 10 minutes?` : `FCC Linux wants to change something on GitHub (${method} ${url.pathname.slice(0, 80)}).\n\nAllow this one change?`);
        if (!ok) {
          log({ what: describe(method, url), status: "denied" });
          return text(403, "The user said no to this GitHub change.");
        }
        if (pushing) approved.set(repo, Date.now() + APPROVAL_MS);
      }
    }
  }
  let response;
  // The browser follows a redirect before FCC could see where it goes, so a
  // site could bounce a request into FCC or the home network. Redirects are
  // followed only for reads from package indexes and GitHub (they send
  // downloads to their own file servers); anything else isn't followed.
  const reading = ["GET", "HEAD"].includes(method);
  const follows = reading && FOLLOW.has(url.hostname);
  const send = (address) => fetch(address, { method, headers, body: reading ? undefined : request.body, redirect: follows ? "follow" : "manual", credentials: "omit" });
  try {
    response = await send(url.href);
  } catch {
    const mirror = method === "GET" && MIRRORS[url.hostname];
    response = mirror ? await send(mirror(url)).catch(() => null) : null;
    if (!response) {
      log({ what: describe(method, url), status: "blocked" });
      return text(502, `${url.hostname} doesn't let apps in a browser reach it, so FCC Linux can't use it from the phone.`);
    }
  }
  if (response.type === "opaqueredirect") {
    log({ what: describe(method, url), status: "redirect" });
    return text(502, `${url.hostname} answered with a redirect, and FCC Linux only follows redirects from package indexes and GitHub (so no site can bounce a request into FCC or your home network). Use the final address directly.`);
  }
  if (response.url && offLimits(new URL(response.url))) {
    log({ what: describe(method, url), status: "blocked" });
    return text(403, "FCC Linux can't reach FCC itself.");
  }
  // The size cap holds while the answer arrives, so a huge download stops
  // before it fills the phone's memory.
  const tooBig = () => text(413, `${url.hostname} sent more than ${BODY_LIMIT / 1048576} MB in one answer.`);
  let body = await readCapped(response);
  if (!body) return tooBig();
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
