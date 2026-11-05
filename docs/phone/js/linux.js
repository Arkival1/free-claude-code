// FCC Linux on the phone: a small custom Linux (Alpine-based, built by
// scripts/linux/build_fcc_linux.py) running in the v86 emulator inside a
// sealed box: an iframe with an origin of its own (sandbox="allow-scripts"), a
// content policy with no network, the engine and the system handed in by
// message. Its terminal is xterm.js on the serial line. The first boot is
// saved as a snapshot on the phone (in its own store, not the backups), so
// later it opens in about a second; "Keep my session" saves where you are.
// Jarvis runs commands through the same serial line (lab/linux tool).

export const LINUX_VERSION = "1.0";
const MEMORY_MB = 128;
// rootfstype=ramfs: the system lives in memory without tmpfs's half-of-RAM cap
// (its files alone take most of that); init_on_free=1 zeroes freed memory, so
// snapshots compress well.
const CMDLINE = "console=ttyS0,115200 quiet loglevel=3 rootfstype=ramfs tsc=reliable mitigations=off random.trust_cpu=on init_on_free=1";
const FILES = {
  libv86: ["linux/libv86.js", "e257912c4a1129e36a86c1e2df69904ab969d87bffd24aa6676e84d6ddffc1c6"],
  wasm: ["linux/v86.wasm", "2f0c4150f266415b754a84a32e6f8e4c975a1d3abb94c78b047fa30027db1ef1"],
  bios: ["linux/seabios.bin", "73e3f359102e3a9982c35fce98eb7cd08f18303ac7f1ba6ebfbe6cdc1c244d98"],
  vgaBios: ["linux/vgabios.bin", "a4bc0d80cc3ca028c73dafa8fee396b8d054ce87ebd8abfbd31b06b437607880"],
  xterm: ["linux/xterm.js", "1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495"],
  xtermCss: ["linux/xterm.css", "ba8e6985669488981ccf40c0cefe3aba80722cb6c92de7ad628b0bd717faf2b6"],
  kernel: ["linux/fcc-linux.kernel", "1c3ff14102200692a49019d091262ade97dcb6fc7ae1bd56ae2f94fae4033b2d"],
  initrd: ["linux/fcc-linux.initrd", "2cfa451d8b4f32d7f5a1b97d190bc63ac43f316f126d40d1b565ee3def4db5f6"],
};
/** Snapshots belong to this exact system and engine. */
const SNAPSHOT_KEY = `${FILES.kernel[1].slice(0, 12)}-${FILES.initrd[1].slice(0, 12)}-${FILES.wasm[1].slice(0, 12)}`;
export const DOWNLOAD_BYTES = 25_100_000;

/** Base64 of text (UTF-8), in pieces, so big files don't overflow the stack. */
function base64(text) {
  const bytes = new TextEncoder().encode(String(text));
  let out = "";
  for (let at = 0; at < bytes.length; at += 0x6000) out += String.fromCharCode(...bytes.subarray(at, at + 0x6000));
  return btoa(out);
}
/** The terminal takes lines of about 4,000 characters: longer data goes in pieces. */
const LINE = 3000;

const hex = (buffer) => [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");

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
  if (globalThis.crypto && crypto.subtle && hex(await crypto.subtle.digest("SHA-256", bytes)) !== sum) {
    if (globalThis.caches) await caches.open("fcc-phone-linux-1.0").then((cache) => cache.delete(response.url)).catch(() => false);
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
      return { ...out, libv86: text(out.libv86), xterm: text(out.xterm), xtermCss: text(out.xtermCss) };
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
  // Snapshots of an older system or engine are dropped: they can't be restored.
  await dbDo("readwrite", (store) => store.put(packed, `${kind}:${SNAPSHOT_KEY}`));
  return packed.byteLength;
}
export async function forgetSession() {
  try {
    await dbDo("readwrite", (store) => store.delete(`session:${SNAPSHOT_KEY}`));
  } catch {
    // Nothing kept.
  }
}
export const hasSession = async () => Boolean(await readSnapshot("session"));

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
  addEventListener("message", async (event) => {
    const job = event.data;
    if (event.source !== parent || !job) return;
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

let current = null;
/** The FCC Linux that's running (one at a time), or null. */
export const runningLinux = () => current;

/**
 * Start FCC Linux in `host` (the terminal shows there). Resolves when it's
 * ready for commands: { frame, run(command), write(path, text), send(keys),
 * keep(), stop(), booted ("snapshot" | "session" | "boot"), seconds }.
 */
export async function startLinux(host, { onProgress, onStatus = () => {}, fresh = false } = {}) {
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
      const files = { ...parts, wasm: parts.wasm.slice(0), bios: parts.bios.slice(0), vgaBios: parts.vgaBios.slice(0), kernel: state ? null : parts.kernel.slice(0), initrd: state ? null : parts.initrd.slice(0) };
      onStatus(state ? "Opening FCC Linux…" : "Starting FCC Linux for the first time (about 15–40 s; after this it opens in a second)…");
      post({ type: "boot", files, state, memoryMb: MEMORY_MB, cmdline: CMDLINE, fontSize: 12 });
    } else if (message.type === "out") {
      output += message.text;
      if (output.length > 400_000) output = output.slice(-200_000);
      settle();
      // A fresh boot is ready at its first prompt; a restored one answers a command instead.
      if (!machine.ready && !state && /fcc\x1b\[0m:/.test(output)) markReady("boot");
    } else if (message.type === "ready") {
      if (message.restored) {
        // A restored machine is already at its prompt: say hello to check.
        machine.run("true").then(() => markReady(session ? "session" : "snapshot"), () => {});
      }
    } else if (message.type === "size") {
      // Tell Linux the terminal's size, so htop, nano and tmux draw to fit.
      machine.size = { cols: Number(message.cols) || 80, rows: Number(message.rows) || 24 };
      if (machine.ready) machine.run(`stty cols ${machine.size.cols} rows ${machine.size.rows}`).catch(() => {});
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
    if (machine.size) machine.run(`stty cols ${machine.size.cols} rows ${machine.size.rows}`).catch(() => {});
    if (how === "boot") {
      // Keep the fresh machine, so next time it opens in about a second.
      try {
        await new Promise((resolve) => setTimeout(resolve, 800));
        await writeSnapshot("clean", await machine.capture());
      } catch {
        // Next time boots again.
      }
    }
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
    /** Run a shell command; resolves { code, text } (the output, plain text). */
    run(command, { timeoutMs = 60000 } = {}) {
      const id = nextId();
      const encoded = base64(command);
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          waiting.delete(`run:${id}`);
          reject(new Error(`No answer within ${Math.round(timeoutMs / 1000)} s (is something still running? Ctrl-C stops it).`));
        }, timeoutMs);
        waiting.set(`run:${id}`, (result) => {
          clearTimeout(timer);
          resolve(result);
        });
        if (encoded.length <= LINE) post({ type: "send", text: ` __fcc_run ${id} ${encoded}\n` });
        else {
          // One piece at a time, each acknowledged, so the terminal's input
          // buffer never overflows.
          (async () => {
            for (let at = 0, n = 0; at < encoded.length; at += LINE, n += 1) {
              const ack = `${id}p${n}`;
              await new Promise((done) => {
                waiting.set(`ack:${ack}`, done);
                post({ type: "send", text: ` printf %s '${encoded.slice(at, at + LINE)}' >> /tmp/.fcc-b64-${id}; printf '\\033]fcc;ack;${ack}\\a\\n'\n` });
              });
              if (closed) return;
            }
            post({ type: "send", text: ` __fcc_run ${id} "$(cat /tmp/.fcc-b64-${id}; rm -f /tmp/.fcc-b64-${id})"\n` });
          })();
        }
      });
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
  return String(text)
    .replace(/\x1b\][^\x07]*\x07/g, "")
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "")
    .replace(/\r/g, "")
    .replace(/^\n+/, "")
    .slice(0, 20000);
}
