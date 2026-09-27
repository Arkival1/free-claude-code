// The on-phone engine: llama.cpp's own server compiled for Safari (wllama),
// the same engine Model Control runs on the PC. Models are GGUF files kept in
// the phone's private storage, downloaded here or added from the Files app.
import { Wllama } from "../vendor/wllama.min.js";
import { readGguf, estimateMemory } from "./gguf.js";
import { state, save, changed, feed } from "./state.js";
import { uid } from "./ui.js";

const WLLAMA_VERSION = "3.6.1";
const CDN = `https://cdn.jsdelivr.net/npm/@wllama`;
export const ENGINE_FILES = {
  default: `${CDN}/wllama@${WLLAMA_VERSION}/esm/wasm/wllama.wasm`,
  compat: {
    worker: `${CDN}/wllama-compat@${WLLAMA_VERSION}/wasm/wllama.js`,
    wasm: `${CDN}/wllama-compat@${WLLAMA_VERSION}/wasm/wllama.wasm`,
  },
};

const HF = "https://huggingface.co";
export const CATALOG = [
  {
    id: "qwen3-0.6b",
    name: "Qwen3 0.6B",
    url: `${HF}/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf`,
    size: 396705472,
    note: "Quickest. Uses tools and can reason. A good first model.",
    good: ["Jarvis", "Helper"],
  },
  {
    id: "qwen2.5-1.5b",
    name: "Qwen2.5 1.5B Instruct",
    url: `${HF}/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf`,
    size: 1117320736,
    note: "Smarter all-rounder, good with tools.",
    good: ["Jarvis", "Researcher"],
  },
  {
    id: "qwen2.5-coder-1.5b",
    name: "Qwen2.5 Coder 1.5B",
    url: `${HF}/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf`,
    size: 1117320768,
    note: "Writes code and web pages: for the Builder and Tester.",
    good: ["Builder", "Tester"],
  },
  {
    id: "qwen3-1.7b",
    name: "Qwen3 1.7B",
    url: `${HF}/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf`,
    size: 1107409472,
    note: "The smartest small model here; thinks before answering.",
    good: ["Helper", "Researcher"],
  },
  {
    id: "llama-3.2-1b",
    name: "Llama 3.2 1B Instruct",
    url: `${HF}/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf`,
    size: 807694464,
    note: "Friendly chat, quick.",
    good: ["Jarvis"],
  },
  {
    id: "gemma-3-1b",
    name: "Gemma 3 1B",
    url: `${HF}/unsloth/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf`,
    size: 806058272,
    note: "Google's small model; good writing.",
    good: ["Helper"],
  },
];

export const MAX_FILE = 2 * 1024 * 1024 * 1024;
const CONTEXTS = [2048, 4096, 8192];
export { CONTEXTS };

let wllama = null;
let loaded = null; // { id, settingsKey }
let loading = null;
let queue = Promise.resolve();
export const status = { loadedId: null, loading: null, lastSpeed: null, error: "" };

function engine() {
  if (!wllama) {
    wllama = new Wllama({ default: ENGINE_FILES.default }, { suppressNativeLog: true, allowOffline: true, parallelDownloads: 2 });
    // Safari needs the compat build; it also runs on the phone's graphics chip.
    wllama.setCompat(ENGINE_FILES.compat);
  }
  return wllama;
}

export const webgpu = () => Boolean(navigator.gpu);

export function modelById(id) {
  return state.models.find((model) => model.id === id);
}

/** Download one catalogue model into the phone's storage. */
export async function download(entry, onProgress, signal) {
  if (state.models.some((model) => model.url === entry.url && model.ready)) return modelById(entry.id);
  const record = { id: entry.id, name: entry.name, url: entry.url, source: "download", size: entry.size, ready: false, added_at: Date.now(), settings: {} };
  state.models = state.models.filter((model) => model.id !== entry.id);
  state.models.push(record);
  await save.models();
  changed("models");
  await engine().modelManager.downloadModel(entry.url, { progressCallback: ({ loaded: done, total }) => onProgress && onProgress(done, total), signal });
  const blob = (await blobsOf(record))[0];
  record.info = await readGguf(blob, entry.url.split("/").pop());
  record.ready = true;
  await save.models();
  changed("models");
  feed("Model Control", `${entry.name} is on this phone.`);
  return record;
}

/** Add a GGUF file picked from the Files app; it is copied into the app. */
export async function addFile(file, onProgress) {
  if (file.size > MAX_FILE) throw new Error("That file is over 2 GB, the most a phone browser can load. Pick a smaller quantization (Q4_K_M of a 1–3B model).");
  const info = await readGguf(file, file.name);
  const id = `file-${uid()}`;
  const key = `fcc_${id}_${file.name.replace(/[^A-Za-z0-9._-]+/g, "-")}`;
  let done = 0;
  const counted = file.stream().pipeThrough(
    new TransformStream({
      transform(chunk, controller) {
        done += chunk.byteLength;
        if (onProgress) onProgress(done, file.size);
        controller.enqueue(chunk);
      },
    })
  );
  await engine().cacheManager.write(key, counted, { etag: String(file.lastModified || Date.now()), originalSize: file.size, originalURL: `file:${key}` });
  const record = {
    id,
    name: file.name.replace(/\.gguf$/i, ""),
    key,
    source: "file",
    size: file.size,
    ready: true,
    info,
    added_at: Date.now(),
    settings: {},
  };
  state.models.push(record);
  await save.models();
  changed("models");
  feed("Model Control", `${record.name} added from Files.`);
  return record;
}

async function blobsOf(model) {
  const w = engine();
  if (model.source === "file") {
    const blob = await w.cacheManager.open(model.key);
    if (!blob) throw new Error(`${model.name} is missing from this phone's storage. Add it again.`);
    return [blob];
  }
  const found = (await w.modelManager.getModels()).find((item) => item.url === model.url);
  if (!found) throw new Error(`${model.name} isn't downloaded. Download it on Models.`);
  return found.open();
}

export async function remove(model) {
  if (status.loadedId === model.id) await unload();
  const w = engine();
  try {
    if (model.source === "file") await w.cacheManager.delete(model.key);
    else {
      const found = (await w.modelManager.getModels({ includeInvalid: true })).find((item) => item.url === model.url);
      if (found) await found.remove();
    }
  } catch {
    /* already gone */
  }
  state.models = state.models.filter((item) => item.id !== model.id);
  if (state.settings.localModel === model.id) state.settings.localModel = "";
  await Promise.all([save.models(), save.settings()]);
  changed("models");
}

export function settingsFor(model) {
  const base = state.settings.engine;
  return {
    context: model.settings.context || base.context,
    gpu: model.settings.gpu ?? base.gpu,
  };
}

export function estimate(model) {
  if (!model.info) return null;
  return estimateMemory(model.info, model.size, settingsFor(model).context);
}

async function load(model) {
  const chosen = settingsFor(model);
  const key = `${model.id}:${chosen.context}:${chosen.gpu}`;
  if (loaded && loaded.key === key && engine().isModelLoaded()) return;
  status.loading = model.id;
  status.error = "";
  changed("engine");
  try {
    const w = engine();
    if (w.isModelLoaded()) await w.exit();
    loaded = null;
    status.loadedId = null;
    const blobs = await blobsOf(model);
    await w.loadModel(blobs, {
      n_ctx: chosen.context,
      n_gpu_layers: chosen.gpu && webgpu() ? 999 : 0,
      jinja: true,
    });
    loaded = { id: model.id, key };
    status.loadedId = model.id;
    feed("Model Control", `${model.name} loaded${chosen.gpu && webgpu() ? " on the graphics chip" : ""}.`);
  } catch (error) {
    status.error = friendly(error);
    throw new Error(status.error);
  } finally {
    status.loading = null;
    changed("engine");
  }
}

export async function unload() {
  await queue.catch(() => {});
  if (wllama && wllama.isModelLoaded()) await wllama.exit();
  loaded = null;
  status.loadedId = null;
  changed("engine");
}

function friendly(error) {
  const text = String((error && error.message) || error);
  if (/memory|OOM|allocate|RangeError/i.test(text)) return "The phone ran out of memory for this model. Pick a smaller model or a smaller context on Models.";
  if (/fetch|network|Failed to load/i.test(text)) return "Couldn't fetch the engine files. Connect to the internet once so the app can save them.";
  return text;
}

/** One chat completion on the phone, in the OpenAI shape. One at a time. */
export function chat(model, { messages, tools, maxTokens = 1024, temperature = 0.5 }) {
  const run = queue.then(async () => {
    await load(model);
    const started = performance.now();
    const response = await engine().createChatCompletion({
      messages,
      tools: tools && tools.length && model.info && model.info.tools ? tools : undefined,
      tool_choice: tools && tools.length && model.info && model.info.tools ? "auto" : undefined,
      max_tokens: maxTokens,
      temperature,
    });
    const timings = response.timings || {};
    status.lastSpeed = {
      tokensPerSecond: timings.predicted_per_second || (response.usage && response.usage.completion_tokens / ((performance.now() - started) / 1000)) || 0,
      readPerSecond: timings.prompt_per_second || 0,
      model: model.id,
      at: Date.now(),
    };
    changed("engine");
    const message = (response.choices && response.choices[0] && response.choices[0].message) || {};
    return message;
  });
  queue = run.catch(() => {});
  return run;
}

/** Time a short answer, like Test speed on the PC. */
export async function speedTest(model) {
  await chat(model, { messages: [{ role: "user", content: "Count from one to twenty in words." }], maxTokens: 96, temperature: 0 });
  return status.lastSpeed;
}

export async function storage() {
  try {
    return await navigator.storage.estimate();
  } catch {
    return null;
  }
}
