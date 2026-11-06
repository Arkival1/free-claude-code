// FCC Linux on the phone: FCC's own Linux (Alpine-based, with every language,
// built by scripts/linux/build_fcc_linux2.py) running in the v86 emulator inside a
// sealed box: an iframe with an origin of its own (sandbox="allow-scripts"), a
// content policy with no network, the engine and the system handed in by
// message. Its terminal is xterm.js on the serial line. The first boot is
// saved as a snapshot on the phone (in its own store, not the backups), so
// later it opens in about a second; "Keep my session" saves where you are.
// Jarvis runs commands through the same serial line (lab/linux tool).

import { digest } from "./sha256.js";
import { useManifest, readFile, readList, setActivity, pruneOld } from "./linuxfiles.js";
import { handle as netHandle } from "./linuxnet.js";

export const LINUX_VERSION = "2.0";
// Compilers (Rust, Go, C++) need room; memory nobody uses stays zero, so
// snapshots stay small (init_on_free=1 zeroes what's freed).
const MEMORY_MB = 512;
// The kernel starts a tiny system (the initrd) that opens the real one over
// 9p: its files come from the page (js/linuxfiles.js), fetched as they're used.
const CMDLINE = "console=ttyS0,115200 quiet loglevel=3 tsc=reliable mitigations=off random.trust_cpu=on init_on_free=1";
const FILES = {
  libv86: ["linux/libv86.js", "e257912c4a1129e36a86c1e2df69904ab969d87bffd24aa6676e84d6ddffc1c6"],
  wasm: ["linux/v86.wasm", "2f0c4150f266415b754a84a32e6f8e4c975a1d3abb94c78b047fa30027db1ef1"],
  bios: ["linux/seabios.bin", "73e3f359102e3a9982c35fce98eb7cd08f18303ac7f1ba6ebfbe6cdc1c244d98"],
  vgaBios: ["linux/vgabios.bin", "a4bc0d80cc3ca028c73dafa8fee396b8d054ce87ebd8abfbd31b06b437607880"],
  xterm: ["linux/xterm.js", "1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495"],
  xtermCss: ["linux/xterm.css", "ba8e6985669488981ccf40c0cefe3aba80722cb6c92de7ad628b0bd717faf2b6"],
  kernel: ["linux/fcc-linux.kernel", "f37a5f89fefb28023b824fc71e814d2b6cc34bc27567fcdc5db75b3b95de6b2c"],
  initrd: ["linux/fcc-linux.initrd", "1fcc5236166073d5d93e7599902b992b0553d9371890dd800546c4f4a4d8f936"],
  // What's in the system: the file list and each pack with its SHA-256.
  manifest: ["linux/fcc-linux.json", "89b3125f958f2af45a45114b09945e8a8e27f463e6ce012d34a432ec902d8f88"],
};
/** A short hash of text (FNV-1a), for keys. */
function shortHash(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) hash = Math.imul(hash ^ text.charCodeAt(i), 0x01000193) >>> 0;
  return hash.toString(16).padStart(8, "0");
}
/** Snapshots belong to this exact system, engine, memory and kernel options. */
const SNAPSHOT_KEY = `${LINUX_VERSION}-${MEMORY_MB}-${shortHash(CMDLINE)}-${FILES.kernel[1].slice(0, 12)}-${FILES.initrd[1].slice(0, 12)}-${FILES.manifest[1].slice(0, 12)}-${FILES.wasm[1].slice(0, 12)}`;
export const DOWNLOAD_BYTES = 12_119_434;

/** Base64 of text (UTF-8), in pieces, so big files don't overflow the stack. */
function base64(text) {
  const bytes = new TextEncoder().encode(String(text));
  let out = "";
  for (let at = 0; at < bytes.length; at += 0x6000) out += String.fromCharCode(...bytes.subarray(at, at + 0x6000));
  return btoa(out);
}
/** The terminal takes lines of about 4,000 characters: longer data goes in pieces. */
const LINE = 3000;

async function fetchChecked([path, sum], onBytes) {
  const response = await fetch(new URL(`../${path}`, import.meta.url));
  if (!response.ok) throw new Error(`Couldn't get FCC Linux's ${path.split("/").pop()} (${response.status}). Try again with the internet on.`);
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    size += value.length;
    if (onBytes) onBytes(value.length);
  }
  const bytes = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, at);
    at += chunk.length;
  }
  // Always checked: the browser's SHA-256, or plain JS where it has none.
  if ((await digest(bytes)) !== sum) {
    if (globalThis.caches) await caches.open(`fcc-phone-linux-${LINUX_VERSION}`).then((cache) => cache.delete(response.url)).catch(() => false);
    throw new Error(`FCC Linux's ${path.split("/").pop()} isn't the file FCC shipped (its checksum is wrong), so it wasn't run. Reload the app to fetch it again.`);
  }
  return bytes.buffer;
}

let files = null;
/** The engine, the terminal and the system (about 25 MB, kept by the app). */
export function loadLinux(onProgress) {
  if (!files) {
    let got = 0;
    const count = (bytes) => onProgress && onProgress((got += bytes), DOWNLOAD_BYTES);
    files = (async () => {
      const names = Object.keys(FILES);
      const loaded = await Promise.all(names.map((name) => fetchChecked(FILES[name], count)));
      const out = Object.fromEntries(names.map((name, i) => [name, loaded[i]]));
      const text = (buffer) => new TextDecoder().decode(buffer);
      const manifest = JSON.parse(text(out.manifest));
      useManifest(manifest, new URL("../linux/", import.meta.url));
      pruneOld().catch(() => 0);
      return { ...out, manifest, libv86: text(out.libv86), xterm: text(out.xterm), xtermCss: text(out.xtermCss) };
    })().catch((error) => {
      files = null;
      throw error;
    });
  }
  return files;
}

/* ------------------------------------------------------------ snapshots */

const DB = "fcc-linux";
const openDb = () =>
  new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("snapshots");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
async function dbDo(mode, work) {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction("snapshots", mode);
      const request = work(transaction.objectStore("snapshots"));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}
const zip = (buffer, how) => new Response(new Blob([buffer]).stream().pipeThrough(how === "in" ? new CompressionStream("gzip") : new DecompressionStream("gzip"))).arrayBuffer();

/** kind: "clean" (fresh after the first boot) or "session" (where you left off). */
async function readSnapshot(kind) {
  try {
    const stored = await dbDo("readonly", (store) => store.get(`${kind}:${SNAPSHOT_KEY}`));
    return stored ? await zip(stored, "out") : null;
  } catch {
    return null;
  }
}
async function writeSnapshot(kind, buffer) {
  const packed = await zip(buffer, "in");
  await dbDo("readwrite", (store) => store.put(packed, `${kind}:${SNAPSHOT_KEY}`));
  // Snapshots of an older system or engine can't be restored: drop them.
  try {
    const keys = await dbDo("readonly", (store) => store.getAllKeys());
    for (const key of keys) if (!String(key).endsWith(`:${SNAPSHOT_KEY}`)) await dbDo("readwrite", (store) => store.delete(key));
  } catch {
    // They go next time.
  }
  return packed.byteLength;
}
async function forget(kind) {
  try {
    await dbDo("readwrite", (store) => store.delete(`${kind}:${SNAPSHOT_KEY}`));
  } catch {
    // Nothing kept.
  }
}
export const forgetSession = () => forget("session");
/** Is a session kept? (Counts it; doesn't unpack it.) */
export async function hasSession() {
  try {
    return (await dbDo("readonly", (store) => store.count(`session:${SNAPSHOT_KEY}`))) > 0;
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------- the box */

// What runs in the box; it becomes text for the box's page.
function linuxBox() {
  const send = (message, transfer) => parent.postMessage(message, "*", transfer || []);
  let emulator = null;
  let pending = "";
  setInterval(() => {
    if (pending) {
      send({ type: "out", text: pending });
      pending = "";
    }
  }, 60);
  const load = (code) =>
    new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = URL.createObjectURL(new Blob([code], { type: "text/javascript" }));
      tag.onload = resolve;
      tag.onerror = () => reject(new Error("FCC Linux's engine didn't load."));
      document.head.append(tag);
    });
  addEventListener("error", (event) => send({ type: "crash", text: String(event.message || "error").slice(0, 300) }));
  // The box has no network: v86 asks for the system's files with
  // XMLHttpRequest, and this stand-in asks the page, which checks and serves
  // them (a pack it can't get yet answers 503, and v86 tries again later).
  const asks = new Map();
  let askNumber = 0;
  window.XMLHttpRequest = class BoxRequest {
    constructor() {
      this.readyState = 0;
      this.status = 0;
      this.response = null;
      this.responseType = "";
      this.aborted = false;
    }
    open(method, url) {
      this.url = String(url);
      this.readyState = 1;
    }
    setRequestHeader() {}
    getResponseHeader() {
      return null;
    }
    abort() {
      this.aborted = true;
    }
    send() {
      askNumber += 1;
      asks.set(askNumber, this);
      send({ type: "get", id: askNumber, url: this.url });
    }
  };
  // Programs inside reach the web only through the page too: v86's network
  // card hands each http request to fetch, and this stand-in passes it on;
  // the page (js/linuxnet.js) decides, and makes the real https request.
  const nets = new Map();
  let netNumber = 0;
  window.fetch = (input, init = {}) =>
    new Promise((resolve, reject) => {
      netNumber += 1;
      nets.set(netNumber, { resolve, reject });
      const url = typeof input === "string" ? input : String((input && input.url) || input);
      const headers = [...new Headers(init.headers || (input && input.headers) || [])];
      const raw = init.body;
      const body = raw instanceof Uint8Array ? raw.slice().buffer : raw instanceof ArrayBuffer ? raw : typeof raw === "string" ? new TextEncoder().encode(raw).buffer : undefined;
      send({ type: "net", id: netNumber, url, method: init.method || "GET", headers, body }, body ? [body] : []);
    });
  const netAnswer = (job) => {
    const waiting = nets.get(job.id);
    nets.delete(job.id);
    if (!waiting) return;
    const empty = [101, 204, 205, 304].includes(job.status);
    try {
      waiting.resolve(new Response(empty ? null : job.body, { status: job.status, headers: job.headers }));
    } catch (error) {
      waiting.reject(error);
    }
  };
  const answer = (job) => {
    const request = asks.get(job.id);
    asks.delete(job.id);
    if (!request || request.aborted) return;
    request.readyState = 4;
    if (job.error) {
      request.status = job.retry ? 503 : 404;
    } else {
      request.status = 200;
      request.response = request.responseType === "json" ? JSON.parse(job.text) : job.bytes;
    }
    if (request.onreadystatechange) request.onreadystatechange();
    if (request.onload) request.onload();
  };
  addEventListener("message", async (event) => {
    const job = event.data;
    if (event.source !== parent || !job) return;
    if (job.type === "got") return answer(job);
    if (job.type === "netback") return netAnswer(job);
    try {
      if (job.type === "boot" && !emulator) {
        const style = document.createElement("style");
        style.textContent = job.files.xtermCss;
        document.head.append(style);
        await load(job.files.xterm);
        await load(job.files.libv86);
        const options = {
          wasm_fn: async (imports) => (await WebAssembly.instantiate(job.files.wasm, imports)).instance.exports,
          memory_size: job.memoryMb * 1024 * 1024,
          vga_memory_size: 2 * 1024 * 1024,
          bios: { buffer: job.files.bios },
          vga_bios: { buffer: job.files.vgaBios },
          autostart: true,
          disable_keyboard: true,
          disable_mouse: true,
          screen_container: document.getElementById("screen"),
          serial_container_xtermjs: document.getElementById("term"),
        };
        // The system's files, over 9p (tag host9p); a restored machine already
        // knows its file list, so only a fresh boot reads it.
        options.filesystem = job.state ? { baseurl: "fs/" } : { baseurl: "fs/", basefs: "fs/list.json" };
        options.net_device = { type: "ne2k", relay_url: "fetch" };
        if (job.state) options.initial_state = { buffer: job.state };
        else Object.assign(options, { bzimage: { buffer: job.files.kernel }, initrd: { buffer: job.files.initrd }, cmdline: job.cmdline });
        emulator = new V86(options);
        emulator.add_listener("serial0-output-byte", (byte) => (pending += String.fromCharCode(byte)));
        emulator.add_listener("emulator-ready", () => {
          fit();
          send({ type: "ready", restored: Boolean(job.state) });
        });
        // A phone-sized terminal: a 12 px font, as many columns and rows as fit.
        let size = "";
        const fit = () => {
          const term = emulator.serial_adapter && emulator.serial_adapter.term;
          const box = document.getElementById("term");
          if (!term || !box.clientWidth) return;
          term.options.fontSize = job.fontSize;
          const probe = document.createElement("span");
          probe.style.cssText = `position:absolute;visibility:hidden;font:${job.fontSize}px monospace;white-space:pre`;
          probe.textContent = "W".repeat(40);
          document.body.append(probe);
          const cellW = probe.getBoundingClientRect().width / 40;
          const cellH = job.fontSize * 1.2;
          probe.remove();
          const cols = Math.max(30, Math.floor((box.clientWidth - 8) / cellW));
          const rows = Math.max(10, Math.floor((box.clientHeight - 8) / cellH));
          term.resize(cols, rows);
          if (`${cols}x${rows}` !== size) {
            size = `${cols}x${rows}`;
            send({ type: "size", cols, rows });
          }
        };
        addEventListener("resize", () => setTimeout(fit, 100));
      } else if (job.type === "send" && emulator) {
        emulator.serial0_send(String(job.text));
      } else if (job.type === "save" && emulator) {
        const state = await emulator.save_state();
        send({ type: "state", id: job.id, state }, [state]);
      }
    } catch (error) {
      send({ type: "failed", text: String((error && error.message) || error).slice(0, 300) });
    }
  });
  send({ type: "loaded" });
}

const POLICY = "default-src 'none'; script-src 'unsafe-inline' blob: 'wasm-unsafe-eval'; style-src 'unsafe-inline'; img-src blob: data:; font-src data:; connect-src 'none'; worker-src blob:; frame-src 'none'; form-action 'none'; base-uri 'none'";
const BOX_HTML = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${POLICY}">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>html,body{margin:0;height:100%;background:#0b0f14;overflow:hidden}#term{position:absolute;inset:0;padding:4px}#screen{display:none}</style>
</head><body><div id="screen"><div></div><canvas></canvas></div><div id="term"></div><script>(${linuxBox.toString()})();</script></body></html>`;

/* --------------------------------------------------------- the machine */

const IDLE_MARK = "\x1b]fcc;idle\x07";
let current = null;
/** The FCC Linux that's running (one at a time), or null. */
export const runningLinux = () => current;
let lastProblem = "";
/** Has FCC Linux stopped by itself, with a reason not shown yet? */
export const hasProblem = () => Boolean(lastProblem);
/** Why FCC Linux last stopped by itself ("" if it didn't); reading it clears it. */
export function takeProblem() {
  const problem = lastProblem;
  lastProblem = "";
  return problem;
}
// What FCC Linux is fetching now (a pack the first time it's used): the
// screen shows it, since a program waits meanwhile.
const activityWatchers = new Set();
/** Watch what FCC Linux is fetching ("" when nothing); returns a stop function. */
export function watchActivity(watch) {
  activityWatchers.add(watch);
  return () => activityWatchers.delete(watch);
}
setActivity((text) => {
  if (current) current.activity = text;
  for (const watch of activityWatchers) watch(text);
});

/**
 * Start FCC Linux in `host` (the terminal shows there). Resolves when it's
 * ready for commands: { frame, run(command), write(path, text), send(keys),
 * keep(), stop(), booted ("snapshot" | "session" | "boot"), seconds }.
 */
export async function startLinux(host, options = {}) {
  for (let tries = 0; ; tries += 1) {
    try {
      return await startOnce(host, options);
    } catch (error) {
      // A kept session (or the saved start) that doesn't answer is dropped,
      // and FCC Linux opens from the next best: the saved start, or a boot.
      if (!error.restoreFailed || tries >= 2) throw error;
      await forget(error.restoreFailed);
      (options.onStatus || (() => {}))(error.restoreFailed === "session" ? "Your kept session didn't answer, so it was cleared; opening FCC Linux fresh…" : "The saved start didn't answer, so FCC Linux is booting from scratch…");
    }
  }
}

async function startOnce(host, { onProgress, onStatus = () => {}, fresh = false } = {}) {
  if (current) current.stop();
  const started = Date.now();
  onStatus("Getting FCC Linux…");
  const parts = await loadLinux(onProgress);
  const session = fresh ? null : await readSnapshot("session");
  const clean = session ? null : await readSnapshot("clean");
  const state = session || clean;
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("title", "FCC Linux terminal");
  frame.className = "linux-box";
  let output = "";
  let ids = 0;
  // Ids unique to this start, so output left from an earlier session can't answer.
  const tag = Math.random().toString(36).slice(2, 8);
  const nextId = () => `${tag}${(ids += 1)}`;
  const waiting = new Map();
  let closed = false;
  // Is the shell at its prompt? bash says so with markers (PROMPT_COMMAND:
  // idle, PS0: busy). Kept and saved machines were kept at their prompt.
  const idleWaiters = new Set();
  // Every line FCC types brings exactly one prompt back; a prompt nobody at
  // FCC is owed is the user's (projects then bring changed files back).
  let owed = 0;
  let markerTail = "";
  const countPrompts = (text) => {
    const scan = markerTail + text;
    let at = scan.indexOf(IDLE_MARK);
    let users = 0;
    while (at >= 0) {
      if (at + IDLE_MARK.length > markerTail.length) {
        if (owed > 0) owed -= 1;
        else users += 1;
      }
      at = scan.indexOf(IDLE_MARK, at + 1);
    }
    markerTail = scan.slice(-(IDLE_MARK.length - 1));
    if (users && machine.ready && machine.onUserIdle) machine.onUserIdle();
  };
  const setIdle = (value) => {
    machine.idle = value;
    if (!value) return;
    for (const done of [...idleWaiters]) done(true);
    applySize();
  };
  const waitIdle = (ms) =>
    machine.idle
      ? Promise.resolve(true)
      : new Promise((resolve) => {
          const done = (value) => {
            clearTimeout(timer);
            idleWaiters.delete(done);
            resolve(value);
          };
          const timer = setTimeout(() => done(false), ms);
          idleWaiters.add(done);
        });
  // Tell Linux the terminal's size (so htop, nano and tmux draw to fit), only
  // at the prompt: typed into a program, stty would land in it.
  let sizeSet = "";
  const applySize = () => {
    if (!machine.ready || !machine.idle || !machine.size) return;
    const want = `${machine.size.cols}x${machine.size.rows}`;
    if (want === sizeSet) return;
    sizeSet = want;
    machine.run(`stty cols ${machine.size.cols} rows ${machine.size.rows}`).catch(() => (sizeSet = ""));
  };
  let resolveReady;
  let rejectReady;
  const ready = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  const post = (message, transfer) => frame.contentWindow && frame.contentWindow.postMessage(message, "*", transfer || []);
  const listen = (event) => {
    if (event.source !== frame.contentWindow || !event.data || closed) return;
    const message = event.data;
    if (message.type === "loaded") {
      // Copies: the box keeps its own; ours stay for the next start.
      const files = { libv86: parts.libv86, xterm: parts.xterm, xtermCss: parts.xtermCss, wasm: parts.wasm.slice(0), bios: parts.bios.slice(0), vgaBios: parts.vgaBios.slice(0), kernel: state ? null : parts.kernel.slice(0), initrd: state ? null : parts.initrd.slice(0) };
      onStatus(state ? "Opening FCC Linux…" : "Starting FCC Linux for the first time (about 15–40 s; after this it opens in a second)…");
      post({ type: "boot", files, state, memoryMb: MEMORY_MB, cmdline: CMDLINE, fontSize: 12 });
    } else if (message.type === "get") {
      const id = message.id;
      const url = String(message.url || "");
      (url.endsWith("list.json") ? readList().then((text) => ({ text })) : readFile(url).then((bytes) => ({ bytes })))
        .then((reply) => post({ type: "got", id, ...reply }, reply.bytes ? [reply.bytes] : []))
        .catch((error) => {
          machine.activity = error.message;
          for (const watch of activityWatchers) watch(error.message);
          if (error.retry === false) {
            // v86 waits for ever on anything but "try again" (5xx), so a file
            // that can never come (a bad checksum, a missing pack) stops FCC
            // Linux and says why, instead of leaving a program hanging.
            lastProblem = error.message;
            machine.stop();
            for (const watch of activityWatchers) watch(error.message);
            return;
          }
          post({ type: "got", id, error: error.message, retry: true });
        });
    } else if (message.type === "net") {
      const id = message.id;
      netHandle(message)
        .catch(() => ({ status: 502, headers: [["content-type", "text/plain"]], body: new TextEncoder().encode("FCC couldn't make that request.\n").buffer }))
        .then((reply) => post({ type: "netback", id, ...reply }, reply.body ? [reply.body] : []));
    } else if (message.type === "out") {
      output += message.text;
      if (output.length > 400_000) output = output.slice(-200_000);
      const fresh = output.slice(-(String(message.text).length + 16));
      const idleAt = fresh.lastIndexOf("\x1b]fcc;idle\x07");
      const busyAt = fresh.lastIndexOf("\x1b]fcc;busy\x07");
      settle();
      if (idleAt >= 0 || busyAt >= 0) setIdle(idleAt > busyAt);
      countPrompts(String(message.text));
      // A fresh boot is ready at its first prompt; a restored one answers a command instead.
      if (!machine.ready && !state && /fcc\x1b\[0m:/.test(output)) markReady("boot");
    } else if (message.type === "ready") {
      if (message.restored) {
        // A restored machine is already at its prompt: say hello to check.
        // No answer (it was kept mid-program?) → start from the next best.
        machine.run("true", { timeoutMs: 20000 }).then(
          () => markReady(session ? "session" : "snapshot"),
          () => rejectReady(Object.assign(new Error("FCC Linux's saved state didn't answer."), { restoreFailed: session ? "session" : "clean" })),
        );
      }
    } else if (message.type === "size") {
      machine.size = { cols: Number(message.cols) || 80, rows: Number(message.rows) || 24 };
      applySize();
    } else if (message.type === "state") {
      const job = waiting.get(`save:${message.id}`);
      if (job) job(message.state);
    } else if (message.type === "failed" || message.type === "crash") {
      if (!machine.ready) rejectReady(new Error(message.text));
    }
  };
  const markReady = async (how) => {
    if (machine.ready) return;
    machine.ready = true;
    machine.booted = how;
    machine.seconds = Math.round((Date.now() - started) / 100) / 10;
    resolveReady(machine);
    if (how === "boot") {
      // Keep the fresh machine at its prompt, so next time it opens in about
      // a second (the terminal's size is set after, so it isn't mid-command).
      try {
        if (machine.idle) await writeSnapshot("clean", await machine.capture());
      } catch {
        // Next time boots again.
      }
    }
    applySize();
  };
  // Command results: output between the markers __fcc_run prints.
  const settle = () => {
    for (const [key, done] of waiting) {
      if (key.startsWith("ack:")) {
        if (output.includes(`\x1b]fcc;ack;${key.slice(4)}\x07`)) {
          waiting.delete(key);
          done();
        }
        continue;
      }
      if (!key.startsWith("run:")) continue;
      const id = key.slice(4);
      const end = output.match(new RegExp(`\\x1b\\]fcc;end;${id};(\\d+)\\x07`));
      if (!end) continue;
      const begin = output.indexOf(`\x1b]fcc;begin;${id}\x07`);
      const body = begin >= 0 ? output.slice(begin + `\x1b]fcc;begin;${id}\x07`.length, end.index) : "";
      waiting.delete(key);
      done({ code: Number(end[1]), text: plain(body) });
    }
  };
  const machine = {
    frame,
    ready: false,
    size: null,
    booted: "",
    seconds: 0,
    send: (keys) => post({ type: "send", text: String(keys) }),
    idle: Boolean(state),
    waitIdle,
    /** Run a shell command; resolves { code, text } (the output, plain text).
     * Commands go one at a time, and only when the shell is at its prompt. */
    run(command, { timeoutMs = 60000 } = {}) {
      const job = queue.then(() => runNow(String(command), timeoutMs));
      queue = job.then(
        () => {},
        () => {},
      );
      return job;
    },
    /** Write a text file inside FCC Linux. */
    async write(path, text) {
      const quoted = `'${String(path).replace(/'/g, "'\\''")}'`;
      // The command carries the file (run() splits long ones into pieces).
      return machine.run(`mkdir -p "$(dirname ${quoted})" && printf '%s' '${base64(text)}' | base64 -d > ${quoted}`);
    },
    capture: () =>
      new Promise((resolve, reject) => {
        const id = nextId();
        const timer = setTimeout(() => reject(new Error("FCC Linux didn't hand over its state.")), 30000);
        waiting.set(`save:${id}`, (state) => {
          clearTimeout(timer);
          waiting.delete(`save:${id}`);
          resolve(state);
        });
        post({ type: "save", id });
      }),
    /** Keep this session (files, programs, history) for next time. */
    async keep() {
      // Kept at its prompt, so it opens ready for commands.
      if (!(await waitIdle(3000))) throw new Error("Something is running in FCC Linux (nano, htop, python, tmux…). Close it so the terminal is back at its prompt, then Keep.");
      // Linux lets go of its file cache first (freed memory is zeroed), so
      // the snapshot holds your work, not copies of the compilers.
      await machine.run("sync; echo 3 > /proc/sys/vm/drop_caches", { timeoutMs: 30000 }).catch(() => null);
      return writeSnapshot("session", await machine.capture());
    },
    stop() {
      if (closed) return;
      closed = true;
      removeEventListener("message", listen);
      frame.remove();
      if (current === machine) current = null;
      for (const [key, done] of waiting) if (key.startsWith("run:")) done({ code: -1, text: "FCC Linux was closed." });
      waiting.clear();
      if (!machine.ready) rejectReady(new Error("FCC Linux was closed."));
    },
  };
  let queue = Promise.resolve();
  const runNow = async (command, timeoutMs) => {
    if (closed) return { code: -1, text: "FCC Linux was closed." };
    if (!(await waitIdle(3000))) throw new Error("FCC Linux's terminal is busy: a program is open in it (nano, htop, python, tmux…). Close it (Ctrl-C or its quit key), or use the linux tool's interrupt, then try again.");
    const id = nextId();
    const encoded = base64(command);
    // Ctrl-E Ctrl-U first: anything half-typed at the prompt is cleared, not run with it.
    const line = (text) => {
      owed += 1;
      post({ type: "send", text: `\x05\x15 ${text}\n` });
    };
    return new Promise((resolve, reject) => {
      let over = false;
      const finish = (error, result) => {
        if (over) return;
        over = true;
        clearTimeout(timer);
        waiting.delete(`run:${id}`);
        if (error) reject(error);
        else resolve(result);
      };
      const timer = setTimeout(() => finish(new Error(`No answer within ${Math.round(timeoutMs / 1000)} s (is something still running? Ctrl-C stops it).`)), timeoutMs);
      waiting.set(`run:${id}`, (result) => finish(null, result));
      if (encoded.length <= LINE) {
        line(`__fcc_run ${id} ${encoded}`);
        return;
      }
      // One piece at a time, each acknowledged, so the terminal's input
      // buffer never overflows; a time-out or a stop ends the sending.
      (async () => {
        for (let at = 0, n = 0; at < encoded.length; at += LINE, n += 1) {
          if (closed || over) return;
          // Each piece only at the prompt (a program opened meanwhile isn't typed into).
          if (n > 0 && !(await waitIdle(3000))) return finish(new Error("FCC Linux's terminal got busy while the command was being sent, so it was stopped."));
          const ack = `${id}p${n}`;
          const taken = await new Promise((done) => {
            const wait = setTimeout(() => {
              waiting.delete(`ack:${ack}`);
              done(false);
            }, 15000);
            waiting.set(`ack:${ack}`, () => {
              clearTimeout(wait);
              done(true);
            });
            line(`printf %s '${encoded.slice(at, at + LINE)}' >> /tmp/.fcc-b64-${id}; printf '\\033]fcc;ack;${ack}\\a\\n'`);
          });
          if (!taken) return finish(new Error("FCC Linux stopped taking the command (its terminal isn't reading)."));
        }
        if (!closed && !over) line(`__fcc_run ${id} "$(cat /tmp/.fcc-b64-${id}; rm -f /tmp/.fcc-b64-${id})"`);
      })();
    });
  };
  current = machine;
  addEventListener("message", listen);
  frame.srcdoc = BOX_HTML;
  host.append(frame);
  const limit = setTimeout(() => rejectReady(new Error("FCC Linux didn't start within 3 minutes.")), 180000);
  try {
    await ready;
  } catch (error) {
    machine.stop();
    throw error;
  } finally {
    clearTimeout(limit);
  }
  return machine;
}

/** Terminal text without colours, cursor moves or the echoed command line. */
export function plain(text) {
  const clean = String(text)
    .replace(/\x1b\][^\x07]*\x07/g, "")
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "")
    .replace(/\r/g, "")
    .replace(/^\n+/, "");
  // The end matters most (errors, results), so a long output keeps its end.
  return clean.length > 20000 ? `… (${clean.length - 20000} earlier characters left out) …\n${clean.slice(-20000)}` : clean;
}
