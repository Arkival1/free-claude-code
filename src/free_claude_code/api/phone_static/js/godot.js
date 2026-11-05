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
import { makePack, isGodotProject } from "../godot/pack.js";

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
const NOISE = /^Failed to assign PWA callback/;

const hex = (buffer) => [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");

const ROUND = new Uint32Array([0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
const rotate = (value, bits) => (value >>> bits) | (value << (32 - bits));

/** SHA-256 in plain JS, for when the browser's own isn't there (plain http
 * from the PC on the home network), so the engine is always checked. */
export function sha256Hex(buffer) {
  const data = new Uint8Array(buffer);
  const blocks = Math.ceil((data.length + 9) / 64);
  const padded = new Uint8Array(blocks * 64);
  padded.set(data);
  padded[data.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(data.length / 0x20000000));
  view.setUint32(padded.length - 4, (data.length * 8) >>> 0);
  const state = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const w = new Uint32Array(64);
  for (let block = 0; block < blocks; block += 1) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getUint32(block * 64 + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotate(w[i - 15], 7) ^ rotate(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotate(w[i - 2], 17) ^ rotate(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let i = 0; i < 64; i += 1) {
      const t1 = (h + (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) + ((e & f) ^ (~e & g)) + ROUND[i] + w[i]) | 0;
      const t2 = ((rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) | 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) | 0;
    }
    [a, b, c, d, e, f, g, h].forEach((value, i) => (state[i] += value));
  }
  return [...state].map((word) => word.toString(16).padStart(8, "0")).join("");
}

async function digest(bytes) {
  if (globalThis.crypto && crypto.subtle) return hex(await crypto.subtle.digest("SHA-256", bytes));
  return sha256Hex(bytes);
}

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
        persistentPaths: [],
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
      if (!(ref in files)) {
        out.push({ text: `${name} loads res://${ref}, which isn't in the project.`, stop: /preload\(|ext_resource/.test(body.slice(0, body.indexOf(ref))) });
      } else if (IMPORTED.test(ref) && !/\.(png|jpe?g|webp)$/i.test(ref)) {
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
  let pack;
  try {
    pack = makePack(project.files);
  } catch (error) {
    result.stopped = "not run";
    result.problems.push({ text: error.message, stop: true });
    settle(finish(result));
    return { frame: null, stop: () => {}, done };
  }
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
        loadGodot(onProgress)
          .then((engine) => {
            if (closed) return;
            readyAt = Date.now();
            onEvent({ type: "engine" });
            frame.contentWindow.postMessage({ type: "run", script: engine.script, wasm: engine.wasm, worklets: engine.worklets, pack, args, memoryMb: MEMORY_MB, pixelRatio: PIXEL_RATIO }, "*");
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
Pictures: put them in the project (use_photo or find_images) and load them at run time: var texture := ImageTexture.create_from_image(Image.load_from_file("res://art/hero.png")). preload("res://x.png") needs Godot's importer, which the phone doesn't have. Sound the same way: AudioStreamOggVorbis.load_from_buffer(FileAccess.get_file_as_bytes(path)) or AudioStreamWAV.load_from_buffer(...).
Text: the built-in font has letters, digits and punctuation only; symbols and emoji show as empty boxes, so use words or draw shapes.
Touch: a phone has no keyboard or mouse. Give every action an on-screen control (TouchScreenButton with action set, a joystick from InputEventScreenTouch and InputEventScreenDrag) shown when DisplayServer.is_touchscreen_available().
Saving: user:// works while the game is open and starts fresh each time.
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
