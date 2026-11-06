// Godot games on the phone: the official Godot 4.7.2 web player
// (vendor/godot-web: single-threaded, the Compatibility renderer) runs a
// project in a sealed box. The box is an iframe with a blank origin of its own
// (sandbox="allow-scripts allow-pointer-lock": no pop-ups, no forms, no way
// out of the frame), a content policy with no network at all, and only
// messages to the page around it, so a game can't reach the internet or
// FCC's keys, chats and files. Its
// memory is capped, a watchdog closes it when it stops answering, and a crash
// closes only the box. The engine's files ship with FCC and are checked
// against their SHA-256 sums before they run.
import { sha256Hex, digest } from "./sha256.js";
import { makePack, importPictures, isGodotProject } from "../godot/pack.js";
import { KIT_TEXT, KIT_FONTS } from "../godot/kit.js";

export { isGodotProject };
export const GODOT_VERSION = "4.7.2";
/** The most memory a game may take (MB): past it the box says no, not the phone. */
export const MEMORY_MB = 1024;
/** Sharper than this costs frames for little gain on a phone screen. */
const PIXEL_RATIO = 2;
/** From the engine being ready (not counting its first download) to the game's first frames. */
const START_LIMIT_S = 120;
/** The engine's first download (10 MB) on a slow connection. */
const LOAD_LIMIT_S = 900;
const QUIET_LIMIT_S = 20;
const FILES = {
  script: ["godot/godot.js", "ffc3898b59fba6f5af0c02f76e5ee526cc061e65c7d2d6f4f98186876cea15c4"],
  wasm: ["godot/godot.wasm.gz", "8803ca732e04a41289a703e5a40bea7cd2c5f3a9dbf41d84f5af795e4f1d7966"],
  "godot.audio.worklet.js": ["godot/godot.audio.worklet.js", "5b476a9c9ce642c0ee4256436d1bc31d9c38f868aca0f9a8e2a57c18d2dec2a3"],
  "godot.audio.position.worklet.js": ["godot/godot.audio.position.worklet.js", "be33985bc7160d6bf9646f259cd86b259cd67b02ccb297ee5c44f8ac84327bc8"],
};
/** The engine download in bytes (for progress before the server says). */
export const ENGINE_BYTES = 10_027_646;
/** The app's cache for the engine (sw.js keeps it across updates). */
const GODOT_CACHE = "fcc-phone-godot-4.7.2";

let runtime = null;
/** The one game running now: a second one closes it (two would double the memory). */
let busy = null;
const ABORT = /\bAborted\b|RuntimeError|unreachable|out of memory|memory access out of bounds/i;
/** Lines the web player prints that say nothing about the game. */
export { sha256Hex };

const NOISE = /^Failed to assign PWA callback/;

async function fetchChecked([path, sum], onProgress) {
  const response = await fetch(new URL(`../${path}`, import.meta.url));
  if (!response.ok) throw new Error(`Couldn't get Godot's ${path.split("/").pop()} (${response.status}). Try again with the internet on.`);
  let bytes;
  if (onProgress && response.body) {
    const total = Number(response.headers.get("content-length")) || ENGINE_BYTES;
    const reader = response.body.getReader();
    const chunks = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      onProgress(received, total);
    }
    bytes = new Uint8Array(received);
    let at = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, at);
      at += chunk.length;
    }
    bytes = bytes.buffer;
  } else {
    bytes = await response.arrayBuffer();
  }
  if ((await digest(bytes)) !== sum) {
    // Drop the bad copy, so the next try fetches it again.
    if (globalThis.caches) await caches.open(GODOT_CACHE).then((cache) => cache.delete(response.url)).catch(() => false);
    throw new Error(`Godot's ${path.split("/").pop()} isn't the file FCC shipped (its checksum is wrong), so it wasn't run. Reload the app to fetch it again.`);
  }
  return bytes;
}

/** The engine's files, fetched once (about 10 MB, kept by the app for offline use) and checked. */
export function loadGodot(onProgress) {
  if (!runtime) {
    runtime = (async () => {
      const decode = (bytes) => new TextDecoder().decode(bytes);
      const [script, wasm, worklet, position] = await Promise.all([
        fetchChecked(FILES.script),
        fetchChecked(FILES.wasm, onProgress),
        fetchChecked(FILES["godot.audio.worklet.js"]),
        fetchChecked(FILES["godot.audio.position.worklet.js"]),
      ]);
      return { script: decode(script), wasm, worklets: { "godot.audio.worklet.js": decode(worklet), "godot.audio.position.worklet.js": decode(position) } };
    })().catch((error) => {
      runtime = null;
      throw error;
    });
  }
  return runtime;
}

// What runs inside the box. It is turned into text for the box's page, so it
// may use nothing from this module.
function boxMain() {
  const send = (message) => parent.postMessage(message, "*");
  const clip = (value, most = 800) => String(value).slice(0, most);
  // The engine draws on animation frames: count the ones it asks for, so the
  // page outside can tell a game that stopped from one that is still playing.
  const raf = window.requestAnimationFrame.bind(window);
  let frames = 0;
  window.requestAnimationFrame = (callback) =>
    raf((time) => {
      frames += 1;
      callback(time);
    });
  setInterval(() => send({ type: "beat", frames, hidden: document.hidden }), 1000);
  addEventListener("error", (event) => send({ type: "crash", text: clip(event.message || event.error || "error") }));
  addEventListener("unhandledrejection", (event) => send({ type: "crash", text: clip((event.reason && event.reason.message) || event.reason) }));
  let begun = false;
  addEventListener("message", async (event) => {
    const job = event.data;
    if (event.source !== parent || begun || !job || job.type !== "run") return;
    begun = true;
    try {
      // A game that wants more memory than the cap fails here, in the box.
      const pages = Math.floor(job.memoryMb * 16);
      const grow = WebAssembly.Memory.prototype.grow;
      WebAssembly.Memory.prototype.grow = function (more) {
        if (this.buffer.byteLength / 65536 + more > pages) {
          send({ type: "memory", text: `The game asked for more than ${job.memoryMb} MB of memory, so the box said no.` });
          throw new RangeError("over FCC's memory cap");
        }
        return grow.call(this, more);
      };
      const ratio = Math.min(window.devicePixelRatio || 1, job.pixelRatio);
      Object.defineProperty(window, "devicePixelRatio", { get: () => ratio, configurable: true });
      const wasm = await new Response(new Blob([job.wasm]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
      // WebRTC isn't covered by the content policy, so it's switched off here.
      for (const name of ["RTCPeerConnection", "webkitRTCPeerConnection"]) {
        Object.defineProperty(window, name, {
          value: function Blocked() {
            throw new Error("The game box has no internet.");
          },
          configurable: false,
        });
      }
      // Saves (user://): Godot keeps them in IndexedDB, which the box can't
      // open (it has no origin of its own). This stand-in holds them in
      // memory, starts from the saves the page hands in (play only), and
      // hands every change back to the page, which keeps them per game.
      const saves = new Map(Object.entries(job.saves || {}));
      const later = (work) => setTimeout(work, 0);
      const fire = (target, name, event) => typeof target[name] === "function" && target[name](event);
      const transaction = (mode) => {
        const tx = { mode, pending: 0, over: false, onerror: null, onabort: null, oncomplete: null };
        const settle = () =>
          later(() => {
            if (tx.over || tx.pending) return;
            tx.over = true;
            if (mode === "readwrite") send({ type: "saves", files: Object.fromEntries(saves) });
            fire(tx, "oncomplete", { target: tx });
          });
        const request = (work) => {
          const req = { result: undefined, error: null, onsuccess: null, onerror: null };
          tx.pending += 1;
          later(() => {
            try {
              req.result = work();
              fire(req, "onsuccess", { target: req });
            } catch (error) {
              req.error = error;
              fire(req, "onerror", { target: req, preventDefault() {} });
            }
            tx.pending -= 1;
            settle();
          });
          return req;
        };
        const writable = () => {
          if (mode !== "readwrite") throw new Error("read-only");
        };
        const store = {
          indexNames: { contains: () => true },
          createIndex() {},
          get: (key) => request(() => (saves.has(String(key)) ? structuredClone(saves.get(String(key))) : undefined)),
          put: (value, key) => request(() => (writable(), saves.set(String(key), structuredClone(value)), key)),
          delete: (key) => request(() => (writable(), saves.delete(String(key)), undefined)),
          index: () => ({
            openKeyCursor() {
              const keys = [...saves.keys()];
              const req = { result: null, onsuccess: null, onerror: null };
              let at = 0;
              const next = () => {
                tx.pending += 1;
                later(() => {
                  const key = keys[at++];
                  req.result = key === undefined ? null : { primaryKey: key, key: saves.has(key) ? saves.get(key).timestamp : null, continue: next };
                  fire(req, "onsuccess", { target: req });
                  tx.pending -= 1;
                  settle();
                });
              };
              next();
              return req;
            },
          }),
        };
        tx.objectStore = () => store;
        return tx;
      };
      const db = { objectStoreNames: { contains: () => true }, createObjectStore: () => transaction("readwrite").objectStore(), transaction: (names, mode) => transaction(mode), close() {} };
      Object.defineProperty(window, "indexedDB", {
        value: {
          open() {
            const req = { result: db, error: null, onsuccess: null, onerror: null, onupgradeneeded: null };
            later(() => fire(req, "onsuccess", { target: req }));
            return req;
          },
        },
        configurable: true,
      });
      // The only thing the engine may fetch is its own code, from memory.
      window.fetch = (input) =>
        /\.wasm$/.test(String((input && input.url) || input))
          ? Promise.resolve(new Response(wasm, { headers: { "Content-Type": "application/wasm" } }))
          : Promise.reject(new TypeError("The game box has no internet."));
      const urls = {};
      for (const [name, code] of Object.entries(job.worklets)) urls[name] = URL.createObjectURL(new Blob([code], { type: "text/javascript" }));
      if (window.AudioWorklet) {
        const addModule = AudioWorklet.prototype.addModule;
        AudioWorklet.prototype.addModule = function (url, options) {
          const name = String(url).split("/").pop();
          return name in urls ? addModule.call(this, urls[name], options) : Promise.reject(new Error("Only the engine's own sound code runs here."));
        };
      }
      await new Promise((resolve, reject) => {
        const tag = document.createElement("script");
        tag.src = URL.createObjectURL(new Blob([job.script], { type: "text/javascript" }));
        tag.onload = resolve;
        tag.onerror = () => reject(new Error("The engine didn't load."));
        document.head.append(tag);
      });
      // eslint-disable-next-line no-undef
      const Godot = Engine;
      const missing = Godot.getMissingFeatures({ threads: false });
      if (missing.length) throw new Error(`This browser can't run Godot: ${missing.join(", ")}`);
      const engine = new Godot({
        executable: "godot",
        persistentPaths: ["/userfs"],
        canvas: document.getElementById("canvas"),
        canvasResizePolicy: 2,
        onPrint: (...parts) => {
          const text = parts.join(" ");
          send({ type: "print", text: clip(text, text.startsWith("FCC_PROBE ") ? 65536 : 800) });
        },
        onPrintError: (...parts) => send({ type: "error", text: clip(parts.join(" ")) }),
        onExit: (code) => send({ type: "exit", code: Number(code) || 0 }),
      });
      send({ type: "loading" });
      await engine.init("godot");
      await engine.preloadFile(job.pack, "/game.pck");
      await engine.start({ args: ["--main-pack", "/game.pck", ...job.args] });
      send({ type: "started" });
    } catch (error) {
      send({ type: "failed", text: clip((error && error.message) || error) });
    }
  });
  send({ type: "ready" });
}

const POLICY = [
  "default-src 'none'",
  "script-src 'unsafe-inline' blob: 'wasm-unsafe-eval'",
  "style-src 'unsafe-inline'",
  "img-src blob: data:",
  "media-src blob: data:",
  "font-src blob: data:",
  "connect-src 'none'",
  "worker-src 'none'",
  "frame-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join("; ");

/** The box's page: no network, the engine and the game come in by message. */
export const BOX_HTML = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${POLICY}">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<style>html,body{margin:0;height:100%;overflow:hidden;background:#000;touch-action:none;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}canvas{display:block;width:100%;height:100%;outline:none}</style>
</head><body><canvas id="canvas" tabindex="-1"></canvas><script>(${boxMain.toString()})();</script></body></html>`;

const GODOT_TEXT = /\.(gd|gdshader|gdshaderinc|tscn|tres|godot|cfg)$/i;
const RES_PATH = /(?:preload|load)\(\s*"res:\/\/([^"]+)"\s*\)/g;
const EXT_PATH = /\[ext_resource\b[^\]]*\bpath="res:\/\/([^"]+)"/g;
const IMPORTED = /\.(png|jpe?g|webp|svg|bmp|tga|ogg|wav|mp3|glb|gltf|obj|fbx|blend|ttf|otf|woff2?)$/i;

// FCC's Godot kit (res://fcc/: fonts with symbols and emoji, textures,
// particles, day and night, wandering), added to any game that uses it and
// doesn't carry its own copy. Its fonts are fetched the first time, checked
// against their checksums and kept, like the engine.
const KIT_PATHS = new Set([...Object.keys(KIT_TEXT).map((path) => `fcc/${path}`), ...KIT_FONTS.map(([path]) => path.replace(/^godot\//, ""))]);
/** True when a game's files load res://fcc/ and the game has no kit of its own. */
export function usesKit(files) {
  if (typeof files["fcc/kit.gd"] === "string") return false;
  return Object.entries(files).some(([name, body]) => typeof body === "string" && GODOT_TEXT.test(name) && body.includes("res://fcc/"));
}
/** The kit's files for a game's pack ({ "fcc/kit.gd": text, "fcc/fonts/x.ttf": bytes }), or none. */
export async function kitFiles(files, onProgress) {
  if (!usesKit(files)) return {};
  const out = {};
  for (const [path, text] of Object.entries(KIT_TEXT)) out[`fcc/${path}`] = text;
  for (const entry of KIT_FONTS) out[entry[0].replace(/^godot\//, "")] = new Uint8Array(await fetchChecked(entry, onProgress && ((done, total) => onProgress(done, total, entry[0]))));
  return out;
}

/** A line's code: strings emptied (a "#" or a keyword inside one is only text), then the comment cut. */
const codeOf = (row) => row.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""').replace(/#.*$/, "");

/**
 * Lines of `while true:` loops with no way out: return, await or quit
 * anywhere inside (but not in a lambda, whose return leaves only the
 * lambda), or a break that isn't inside an inner loop (that break only
 * leaves the inner loop).
 */
export function endlessLoops(text) {
  const lines = text.split("\n");
  const width = (row) => row.match(/^\s*/)[0].replace(/\t/g, "    ").length;
  const leaves = (code, looped) => /\b(return|await|quit)\b/.test(code) || (/\bbreak\b/.test(code) && !looped);
  const found = [];
  lines.forEach((line, index) => {
    const head = codeOf(line).match(/^\s*while\s+(?:true|1|\(true\))\s*:\s*(.*)$/);
    if (!head) return;
    const indent = width(line);
    // A lambda's body (the rest of its line, and lines under it) doesn't count.
    const before = (code) => code.split(/\bfunc\b/)[0];
    let exits = leaves(before(head[1]), false);
    const loops = [];
    const lambdas = [];
    for (let next = index + 1; next < lines.length && !exits; next += 1) {
      const row = lines[next];
      if (!row.trim() || /^\s*#/.test(row)) continue;
      const depth = width(row);
      if (depth <= indent) break;
      while (loops.length && depth <= loops[loops.length - 1]) loops.pop();
      while (lambdas.length && depth <= lambdas[lambdas.length - 1]) lambdas.pop();
      if (lambdas.length) continue;
      const code = codeOf(row);
      if (/^\s*(for|while)\b/.test(code)) loops.push(depth);
      if (/\bfunc\b/.test(code)) lambdas.push(depth);
      if (leaves(before(code), loops.length > 0)) exits = true;
    }
    if (!exits) found.push(index + 1);
  });
  return found;
}

/**
 * What would stop the game, read from its files before it runs: { text, stop }.
 * stop: true means it would fail to start or would freeze the phone.
 */
export function godotProblems(project) {
  const files = project.files || {};
  const config = files["project.godot"];
  if (typeof config !== "string") return [{ text: "There is no project.godot, so this isn't a Godot game (godot start puts a starter in).", stop: true }];
  const out = [];
  const main = config.match(/^\s*run\/main_scene\s*=\s*"([^"]*)"/m);
  if (!main) out.push({ text: "project.godot has no run/main_scene, so Godot doesn't know which scene to open.", stop: true });
  else if (main[1].startsWith("uid://")) out.push({ text: `run/main_scene is ${main[1]}; on the phone it must be a res:// path (like res://main.tscn).`, stop: true });
  else if (!(main[1].replace(/^res:\/\//, "") in files)) out.push({ text: `The main scene ${main[1]} isn't in the project.`, stop: true });
  for (const [name, body] of Object.entries(files)) {
    if (name.startsWith("parts/")) continue;
    if (/\.cs$/i.test(name)) out.push({ text: `${name}: C# doesn't run in the web player; write it in GDScript.`, stop: true });
    if (/\.gdextension$/i.test(name)) out.push({ text: `${name}: GDExtension (native code) isn't in the phone's Godot player.`, stop: true });
    if (typeof body !== "string" || !GODOT_TEXT.test(name)) continue;
    for (const line of /\.gd$/i.test(name) ? endlessLoops(body) : []) {
      out.push({ text: `${name}:${line} has a while true loop with no break, return or await inside, which would freeze the phone. Give it a way out.`, stop: true });
    }
    const refs = [...body.matchAll(RES_PATH), ...body.matchAll(EXT_PATH)].map((match) => match[1]);
    for (const ref of new Set(refs)) {
      if (ref.startsWith(".godot/")) continue;
      if (KIT_PATHS.has(ref) && !(ref in files) && typeof files["fcc/kit.gd"] !== "string") continue; // FCC adds its kit
      if (!(ref in files)) {
        out.push({ text: `${name} loads res://${ref}, which isn't in the project.`, stop: /preload\(|ext_resource/.test(body.slice(0, body.indexOf(ref))) });
      } else if (IMPORTED.test(ref) && !/\.(png|jpe?g|webp|gif|bmp)$/i.test(ref)) {
        out.push({ text: `${name} loads res://${ref}: the phone has no importer for that kind of file, so load it at run time (for sound: AudioStreamOggVorbis.load_from_buffer or AudioStreamWAV.load_from_buffer on FileAccess.get_file_as_bytes).`, stop: false });
      }
    }
  }
  return out;
}

/** Sort the engine's error lines: errors, warnings, and the "at:" line that says where. */
function sortLine(result, text) {
  const line = text.trim();
  if (!line || NOISE.test(line)) return;
  if (/^EvalError: Refused to evaluate/.test(line)) {
    result.blocked.add("The game tried to run the browser's JavaScript (JavaScriptBridge.eval); FCC's box doesn't allow that.");
    return;
  }
  if (/^at:\s/.test(line) || /^GDScript backtrace/.test(line) || /^\[\d+\]\s/.test(line)) {
    const last = result._last;
    if (last && last.length < 1200) last.push(line);
    return;
  }
  const list = /^(?:USER\s+)?WARNING:/.test(line) ? result.warnings : result.errors;
  if (list.length >= 40) return;
  const entry = [line];
  list.push(entry);
  result._last = entry;
}

/**
 * Run a project's game in a box. host: where the box goes; mode "play" shows
 * it, "check" runs it for `seconds` after it starts and closes it.
 * Returns { frame, stop(reason), done }: done resolves with what happened.
 */
export function runGodot(project, { host = document.body, mode = "play", seconds = 8, args = [], untilPrint = null, onEvent = () => {}, onProgress } = {}) {
  const started = Date.now();
  const result = { name: project.name, mode, probe: null, started: false, startSeconds: null, seconds: 0, frames: 0, fps: 0, prints: [], errors: [], warnings: [], blocked: new Set(), crash: "", memory: "", exit: null, stopped: "", problems: godotProblems(project), _last: null };
  const blockers = result.problems.filter((problem) => problem.stop);
  let settle;
  const done = new Promise((resolve) => (settle = resolve));
  if (blockers.length) {
    result.stopped = "not run";
    settle(finish(result));
    return { frame: null, stop: () => {}, done };
  }
  try {
    makePack(project.files);
  } catch (error) {
    result.stopped = "not run";
    result.problems.push({ text: error.message, stop: true });
    settle(finish(result));
    return { frame: null, stop: () => {}, done };
  }
  // Pictures are imported as the editor would (async: JPEG and WebP become PNG).
  // FCC's kit goes in too when the game uses it (its fonts fetched once, then kept).
  const packing = Promise.all([importPictures(project.files), kitFiles(project.files)]).then(([imported, kit]) => makePack(project.files, { ...kit, ...imported }));
  const keeps = mode === "play" && typeof project.id === "string" && project.id !== "";
  const frame = document.createElement("iframe");
  // Scripts, and the mouse lock a 3D game asks for on a computer (Esc frees it).
  frame.setAttribute("sandbox", "allow-scripts allow-pointer-lock");
  frame.setAttribute("allow", "autoplay; gamepad");
  frame.setAttribute("title", `${project.name} (Godot)`);
  frame.className = mode === "check" ? "godot-box godot-check" : "godot-box";
  let lastWord = Date.now();
  let lastFrame = Date.now();
  // Playing from the first frame drawn after the engine started (a game may
  // build its world before that), and counted from there.
  let startedFrames = 0;
  let playingAt = 0;
  let readyAt = 0;
  let firstFrames = 0;
  let closed = false;
  if (busy) busy.stop("Another Godot game started, so this one was closed.");
  busy = { stop: (reason) => stop(reason) };
  const mine = busy;
  const stop = (reason = "") => {
    if (closed) return;
    closed = true;
    clearInterval(watch);
    removeEventListener("message", listen);
    if (busy === mine) busy = null;
    if (reason && !result.stopped) result.stopped = reason;
    result.seconds = Math.round((Date.now() - started) / 100) / 10;
    if (playingAt) {
      const ran = (Date.now() - playingAt) / 1000;
      result.fps = ran > 0.5 ? Math.round((result.frames - firstFrames) / ran) : 0;
    }
    frame.remove();
    settle(finish(result));
  };
  const listen = (event) => {
    if (event.source !== frame.contentWindow || !event.data || typeof event.data.type !== "string") return;
    const message = event.data;
    lastWord = Date.now();
    const text = typeof message.text === "string" ? message.text : "";
    switch (message.type) {
      case "ready":
        // Saves only come in (and go back) when the user plays; checks start clean.
        Promise.all([loadGodot(onProgress), packing, keeps ? readSaves(project.id) : {}])
          .then(([engine, pack, saves]) => {
            if (closed) return;
            readyAt = Date.now();
            onEvent({ type: "engine" });
            frame.contentWindow.postMessage({ type: "run", script: engine.script, wasm: engine.wasm, worklets: engine.worklets, pack, args, saves, memoryMb: MEMORY_MB, pixelRatio: PIXEL_RATIO }, "*");
          })
          .catch((error) => {
            result.crash = error.message;
            stop("engine");
          });
        return;
      case "beat": {
        const frames = Number(message.frames) || 0;
        if (frames !== result.frames || message.hidden) lastFrame = Date.now();
        result.frames = frames;
        // Three frames: the first one can come before a game builds its world.
        if (result.started && !playingAt && frames >= startedFrames + 3) {
          playingAt = Date.now();
          firstFrames = frames;
          result.startSeconds = Math.round((playingAt - readyAt) / 100) / 10;
          onEvent({ type: "playing" });
        }
        break;
      }
      case "started":
        result.started = true;
        startedFrames = result.frames;
        break;
      case "print":
        if (text.startsWith("FCC_PROBE ")) {
          try {
            result.probe = JSON.parse(text.slice(10));
          } catch {
            result.probe = null;
          }
        } else {
          if (result.prints.length >= 300) result.prints.shift();
          result.prints.push(text);
        }
        if (untilPrint && untilPrint.test(text)) {
          onEvent(message);
          stop("");
          return;
        }
        break;
      case "error":
        for (const line of text.split("\n")) sortLine(result, line);
        break;
      case "memory":
        result.memory = text;
        break;
      case "saves":
        if (keeps) {
          keepSaves(project.id, message.files).then((problem) => {
            if (problem && !result.warnings.includes(problem)) result.warnings.push(problem);
          });
        }
        return;
      case "crash":
        // A stray browser error may leave the game running; an engine abort doesn't.
        if (!ABORT.test(text)) {
          sortLine(result, text);
          break;
        }
        result.crash = result.crash || text;
        onEvent(message);
        stop("crash");
        return;
      case "failed":
        result.crash = result.crash || text;
        onEvent(message);
        stop("failed");
        return;
      case "exit":
        result.exit = Number(message.code) || 0;
        onEvent(message);
        stop("exit");
        return;
      default:
        break;
    }
    onEvent(message);
  };
  addEventListener("message", listen);
  let lastTick = Date.now();
  let loadFrom = started;
  const watch = setInterval(() => {
    const now = Date.now();
    // The box left the page (the screen changed): nothing is playing any more.
    if (!frame.isConnected) return stop("The game's screen was closed.");
    // The whole app was paused (another app, a locked phone, a hidden tab):
    // that isn't the game's fault, so its clocks start again.
    if (document.hidden || now - lastTick > 3000) {
      lastWord = now;
      lastFrame = now;
      if (readyAt && !playingAt) readyAt += now - lastTick;
      if (!readyAt) loadFrom += now - lastTick;
    }
    lastTick = now;
    if (document.hidden) return;
    if (!readyAt && now - loadFrom > LOAD_LIMIT_S * 1000) stop("Godot's engine didn't finish downloading, so the box was closed. Try again with a better connection.");
    else if (readyAt && !playingAt && now - readyAt > START_LIMIT_S * 1000) stop(`The game didn't show a frame within ${START_LIMIT_S} s, so the box was closed.`);
    else if (result.started && now - lastWord > QUIET_LIMIT_S * 1000) stop(`The game stopped answering for ${QUIET_LIMIT_S} s (a script stuck in a loop?), so the box was closed.`);
    else if (playingAt && now - lastFrame > QUIET_LIMIT_S * 1000) stop(`The game stopped drawing for ${QUIET_LIMIT_S} s, so the box was closed.`);
    else if (mode === "check" && playingAt && now - playingAt >= seconds * 1000) stop("");
  }, 500);
  frame.srcdoc = BOX_HTML;
  host.append(frame);
  return { frame, stop, done };
}

function finish(result) {
  delete result._last;
  result.blocked = [...result.blocked];
  result.errors = result.errors.map((lines) => lines.join("\n"));
  result.warnings = result.warnings.map((lines) => lines.join("\n"));
  return result;
}

/** A run in plain words, for an agent or the user. */
export function describeRun(result) {
  const lines = [];
  const blockers = result.problems.filter((problem) => problem.stop);
  if (blockers.length) {
    lines.push(`${result.name} didn't run: fix these first.`, ...blockers.map((problem) => `- ${problem.text}`));
  } else if (!result.started || result.startSeconds === null) {
    lines.push(`${result.name} didn't start in Godot ${GODOT_VERSION}${result.crash ? `: ${result.crash}` : result.stopped ? `: ${result.stopped}` : "."}`);
  } else {
    lines.push(`Ran ${result.name} in Godot ${GODOT_VERSION} on this phone: its first frame came after ${result.startSeconds} s, then it drew ${result.fps} frames a second${result.mode === "check" ? "" : ` (${result.seconds} s in all)`}.`);
    if (result.exit !== null) lines.push(`The game quit by itself (code ${result.exit}).`);
    if (result.crash) lines.push(`It crashed: ${result.crash}`);
    if (result.stopped && result.stopped !== "exit" && result.stopped !== "crash") lines.push(result.stopped);
  }
  if (result.memory) lines.push(result.memory);
  if (result.blocked.length) lines.push(...result.blocked);
  if (result.errors.length) lines.push(`Errors (${result.errors.length}):`, ...result.errors.slice(0, 12).map((error) => `- ${error}`));
  if (result.warnings.length) lines.push(`Warnings (${result.warnings.length}):`, ...result.warnings.slice(0, 6).map((warning) => `- ${warning}`));
  const notes = result.problems.filter((problem) => !problem.stop);
  if (notes.length) lines.push("Notes:", ...notes.map((problem) => `- ${problem.text}`));
  const said = result.prints.filter((line) => !/^Godot Engine v|^WebGL|^OpenGL API|^\s*$/.test(line));
  if (said.length) lines.push(`It printed (last ${Math.min(10, said.length)}):`, ...said.slice(-10).map((line) => `  ${line}`));
  if (result.started && !result.errors.length && !result.crash) lines.push("No errors.");
  return lines.join("\n");
}

/** Run a project's game unseen for a few seconds and say what happened. */
export async function checkGodot(project, seconds = 8) {
  const run = runGodot(project, { mode: "check", seconds: Math.max(3, Math.min(30, Number(seconds) || 8)) });
  return describeRun(await run.done);
}

// ------------------------------------------------------------------ the tool

export const GODOT_GUIDE = `Godot ${GODOT_VERSION} on this phone: the official Godot web player runs the project's game in a sealed box (no internet, no reach into the app; a crash or a stuck game closes only the box).
What runs: GDScript, scenes (.tscn), resources (.tres), shaders (.gdshader), 2D and 3D, physics, particles, sound.
How it draws: the Compatibility renderer (WebGL 2). Lights, shadows, glow, fog, particles and your own shaders work; Forward+ effects (SDFGI, VoxelGI, volumetric fog, screen-space reflections, SSAO, SSIL) and compute shaders don't.
One thread: Thread doesn't run on its own and long work freezes the game. Build big things in steps (await get_tree().process_frame between them), keep generated textures small (256 or less), and keep instance counts modest.
Pictures: put them in the project (use_photo or find_images): PNG, JPEG, WebP, GIF or BMP. FCC imports them as Godot's editor would, so preload("res://art/hero.png") and textures in scenes work. Sound is loaded at run time: AudioStreamOggVorbis.load_from_buffer(FileAccess.get_file_as_bytes(path)) or AudioStreamWAV.load_from_buffer(...).
FCC's kit (res://fcc/, added by FCC to every game that uses it): const Kit := preload("res://fcc/kit.gd"). Kit.use_fonts() first in _ready gives every text symbols (★ ♥ ⚔ ☀ ♞ → ✓) and emoji (black and white); Kit.font("pixel") or Kit.font("fantasy") for headings. Kit.texture(kind) for 2D and Kit.material(kind, tile) for 3D: stone, rock, grass, dirt, sand, wood, metal, gold, snow, lava, water, brick (made from Godot's noise, nothing to download). Life: Kit.particles_3d(kind, area) or Kit.particles_2d(kind, area) for dust, leaves, fireflies, rain, snow, embers; Kit.day_night(seconds_per_day, sun, world_environment) (2D: no sun, it tints the scene); Kit.wander(node, radius, speed) makes an NPC or animal stroll. Kit.fit_screen(get_window(), 560) keeps texts and buttons a good size on a phone held either way (needs stretch mode canvas_items, aspect expand).
Text without the kit: the built-in font has letters, digits and punctuation only; symbols and emoji show as empty boxes.
Touch: a phone has no keyboard or mouse. Give every action an on-screen control (TouchScreenButton with action set, a joystick from InputEventScreenTouch and InputEventScreenDrag) shown when DisplayServer.is_touchscreen_available().
Saving: user:// (FileAccess, ConfigFile, ResourceSaver) is kept on this phone between plays, per game, up to 16 MB; the user can clear it in Projects (Start over). Checks start with no saves, so a game must also work from nothing.
Not here: C#, GDExtension (native code), the internet (HTTPRequest and WebSocket fail on purpose), JavaScriptBridge.
Never write while true without break, return or await inside: it would freeze the phone (check refuses to run it).
How to make one: start_project, then godot start with a starter (godot starters lists them), or write project.godot (with run/main_scene="res://main.tscn"), main.tscn and main.gd yourself; building the scene in code in _ready is easier to get right than long .tscn files. Then godot check, fix every error it shows (file and line), and check again until it says No errors.`;

const known = (table, key) => typeof key === "string" && Object.hasOwn(table, key);

/** A starter's files with the game's name in project.godot. */
export function starterFiles(starters, name, title) {
  const files = { ...starters[name].files };
  files["project.godot"] = files["project.godot"].replace(/config\/name="[^"]*"/, `config/name=${JSON.stringify(String(title || "My game").slice(0, 60))}`);
  return files;
}

/* ---------------------------------------------------------------- saves */

// A game's saves (its user:// files), kept on the phone per project, apart
// from the backups. They're the game's own data, handed back only to it.
const SAVES_DB = "fcc-godot-saves";
const SAVES_MAX = 16 * 1048576;
function savesDo(mode, work) {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(SAVES_DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore("saves");
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result;
      const request = work(db.transaction("saves", mode).objectStore("saves"));
      request.onsuccess = () => {
        db.close();
        resolve(request.result);
      };
      request.onerror = () => {
        db.close();
        reject(request.error);
      };
    };
  });
}
/** A game's saves ({ path: { timestamp, mode, contents } }), or none. */
export async function readSaves(id) {
  try {
    const row = await savesDo("readonly", (store) => store.get(String(id)));
    return (row && row.files) || {};
  } catch {
    return {};
  }
}
/** Keep what the box handed back; returns a problem to show, or "". */
async function keepSaves(id, files) {
  if (!files || typeof files !== "object") return "";
  const clean = {};
  let bytes = 0;
  for (const [path, entry] of Object.entries(files)) {
    if (!path.startsWith("/userfs") || !entry || typeof entry !== "object" || typeof entry.mode !== "number") continue;
    // Godot's file system hands file bytes over as typed arrays (Int8Array here).
    if (entry.contents !== undefined && !ArrayBuffer.isView(entry.contents)) continue;
    bytes += path.length + (entry.contents ? entry.contents.byteLength : 0);
    clean[path] = { timestamp: entry.timestamp instanceof Date ? entry.timestamp : new Date(Number(entry.timestamp) || 0), mode: entry.mode, ...(entry.contents ? { contents: entry.contents } : {}) };
  }
  if (bytes > SAVES_MAX) return `The game's saves are over ${SAVES_MAX / 1048576} MB, so the newest ones weren't kept.`;
  try {
    await savesDo("readwrite", (store) => store.put({ files: clean, bytes, at: Date.now() }, String(id)));
    return "";
  } catch {
    return "The game's saves couldn't be kept on this phone.";
  }
}
/** Forget a game's saves (Start over). */
export async function forgetSaves(id) {
  try {
    await savesDo("readwrite", (store) => store.delete(String(id)));
  } catch {
    // Nothing kept.
  }
}
/** How big a game's saves are (bytes), without unpacking them. */
export async function savesSize(id) {
  try {
    const row = await savesDo("readonly", (store) => store.get(String(id)));
    return row ? Number(row.bytes) || 0 : 0;
  } catch {
    return 0;
  }
}

let lastProbe = null;

/** Close the game that is running now, if there is one. */
export function stopGodot(reason = "Closed.") {
  if (busy) busy.stop(reason);
}

/** Run FCC's probe in a box (host: where it shows; unseen when left out). */
export async function probeGodot(host, onProgress, onEvent) {
  const { GODOT_PROBE } = await import("../godot/starters.js");
  const run = runGodot({ name: "Godot probe", files: GODOT_PROBE }, { host: host || document.body, mode: "check", seconds: 60, untilPrint: /^FCC_PROBE /, onProgress, onEvent });
  const result = await run.done;
  if (result.probe) lastProbe = result;
  return result;
}

const STATUS_NAMES = { works: "Works", limited: "Limited", missing: "Missing", blocked: "Blocked on purpose (FCC's box)" };

/** The probe's items, with what the box itself knows added. */
export function probeItems(result) {
  if (!result || !result.probe || !Array.isArray(result.probe.items)) return [];
  const items = result.probe.items.filter((item) => item && typeof item.name === "string" && Object.hasOwn(STATUS_NAMES, item.status));
  if (result.prints.some((line) => /no GDExtension support/.test(line))) {
    items.push({ group: "Code", name: "GDExtension (native add-ons)", status: "missing", detail: "This web player was built without it (its own start-up line says so); native add-ons need a player built with dynamic linking." });
  }
  items.push({ group: "Engine", name: "Memory cap", status: "limited", detail: `FCC's box lets a game take up to ${MEMORY_MB} MB, so a greedy game fails in its box, not the phone.` });
  return items;
}

/** The probe in plain words. */
export function describeProbe(result) {
  const items = probeItems(result);
  if (!items.length) return `${describeRun(result)}\nThe probe didn't finish, so there is no list.`;
  const lines = [`What Godot ${GODOT_VERSION} can do on this phone (tested just now):`];
  for (const status of Object.keys(STATUS_NAMES)) {
    const shown = items.filter((item) => item.status === status);
    if (shown.length) lines.push("", `${STATUS_NAMES[status]} (${shown.length}):`, ...shown.map((item) => `- ${item.name}: ${item.detail}`));
  }
  return lines.join("\n");
}

/** The godot tool: guide, starters, start, check, probe. */
export async function useGodot(args, ctx, writeFile) {
  const action = String(args.action || "guide");
  if (action === "guide") return GODOT_GUIDE;
  const { GODOT_STARTERS } = await import("../godot/starters.js");
  if (action === "starters") {
    return `Godot starters for the phone (godot start with starter set to one):\n${Object.entries(GODOT_STARTERS).map(([name, starter]) => `- ${name}: ${starter.about}`).join("\n")}`;
  }
  if (action === "start") {
    if (ctx.partsOnly) return "As a helper you write only under parts/: put your scripts or scenes there for the main AI to use.";
    if (!ctx.project) throw new Error("Start or pick a project first (start_project), then godot start.");
    if (!known(GODOT_STARTERS, args.starter)) throw new Error(`starter is one of: ${Object.keys(GODOT_STARTERS).join(", ")}.`);
    const taken = Object.keys(ctx.project.files).filter((path) => !path.startsWith("parts/"));
    if (taken.length) return `${ctx.project.name} already has files (${taken.slice(0, 8).join(", ")}), so the starter wasn't put in. Start a new project for it.`;
    const files = starterFiles(GODOT_STARTERS, args.starter, ctx.project.name);
    for (const [path, body] of Object.entries(files)) await writeFile(ctx.project, path, body);
    return `Put the ${args.starter} starter in ${ctx.project.name}: ${Object.keys(files).join(", ")}. Make it the user's game with edit_file and write_file, then godot check and fix what it finds. The user plays it from Projects (Play).`;
  }
  if (ctx.partsOnly && (action === "check" || action === "probe")) return "The main AI runs the game; as a helper, write your part under parts/ and say what to check.";
  if (action === "check") {
    if (!ctx.project) throw new Error("Pick the project first (start_project with its name), then godot check.");
    if (!isGodotProject(ctx.project)) return `${ctx.project.name} isn't a Godot game (it has no project.godot). godot start puts a starter in a new project.`;
    if (busy) return "A Godot game is open on the phone right now; check again when it's closed.";
    return await checkGodot(ctx.project, args.seconds);
  }
  if (action === "probe") {
    if (lastProbe && args.again !== true && args.again !== "true") return describeProbe(lastProbe);
    if (busy) return "A Godot game is open on the phone right now; probe again when it's closed.";
    return describeProbe(await probeGodot());
  }
  throw new Error("action is guide, starters, start, check or probe.");
}
