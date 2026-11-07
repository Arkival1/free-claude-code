// FCC Phone's second engine: WebLLM (MLC, Apache-2.0, kept in
// vendor/web-llm) runs a model on the phone's graphics chip through WebGPU.
// The model's weights go straight into the graphics chip's memory, piece by
// piece, so a 4B fits where the first engine (wllama, which copies the whole
// file into the page's own memory, about 1 GB on an iPhone) can't.
// Needs WebGPU: on by default from iOS 26; on iOS 18 it's Safari's Feature
// Flags, WebGPU (and FCC opened in Safari, not Chrome).

const LIBS = new URL("../vendor/web-llm/libs/", import.meta.url).href;
const HF = "https://huggingface.co/mlc-ai";

// Each graphics-chip model, pinned to the exact Hugging Face commit FCC was
// built against; f16 needs the chip's half-size numbers (shader-f16), f32
// works on every WebGPU chip but needs more memory.
export const GPU_MODELS = {
  "qwen3-4b-gpu": {
    f16: { id: "Qwen3-4B-q4f16_1-MLC", url: `${HF}/Qwen3-4B-q4f16_1-MLC/resolve/a5c9fab855e3ccbdfed2e7e69683d75f30332161/`, lib: "Qwen3-4B-q4f16_1_cs1k-webgpu.wasm" },
  },
  "qwen3-1.7b-gpu": {
    f16: { id: "Qwen3-1.7B-q4f16_1-MLC", url: `${HF}/Qwen3-1.7B-q4f16_1-MLC/resolve/80b3abcec6c3b3f5355dc0cc99cc4fb578f192bc/`, lib: "Qwen3-1.7B-q4f16_1_cs1k-webgpu.wasm" },
    f32: { id: "Qwen3-1.7B-q4f32_1-MLC", url: `${HF}/Qwen3-1.7B-q4f32_1-MLC/resolve/bddd4d584cabe19113f7e4ff46fd9e73b4d3dc89/`, lib: "Qwen3-1.7B-q4f32_1_cs1k-webgpu.wasm" },
  },
};

let library = null;
let current = null; // { key, engine }
let chip = null;

/** The WebLLM module, loaded only when a graphics-chip model is used (it's
 * 6.5 MB). Tests hand in a stand-in as window.fccWebLLM. */
async function webllm() {
  if (window.fccWebLLM) return window.fccWebLLM;
  library = library || (await import("../vendor/web-llm/web-llm.js"));
  return library;
}

/** What this phone's graphics chip offers: null when the browser has no
 * WebGPU (iOS 18 with the flag off, or Chrome on iOS 18). */
export async function chipInfo() {
  if (chip) return chip;
  if (!navigator.gpu) return null;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return null;
    chip = { f16: adapter.features.has("shader-f16") };
  } catch {
    return null;
  }
  return chip;
}

export const hasWebGPU = () => Boolean(navigator.gpu);

/** The version of a model this chip can run, or why it can't. */
export async function variantFor(modelId) {
  const versions = GPU_MODELS[modelId];
  if (!versions) throw new Error("That isn't a graphics-chip model.");
  const info = await chipInfo();
  if (!info) throw new Error("This browser has no WebGPU. On iOS 18: Settings, Apps, Safari, Advanced, Feature Flags, turn on WebGPU, then open FCC Phone in Safari. iOS 26 has it on already.");
  const version = (info.f16 && versions.f16) || versions.f32;
  if (!version) throw new Error("This phone's graphics chip can't run the 4B (it needs half-size numbers, shader-f16). Use Qwen3 1.7B (graphics chip) instead.");
  return version;
}

function appConfig(version, context) {
  return {
    model_list: [{ model: version.url, model_id: version.id, model_lib: `${LIBS}${version.lib}`, overrides: { context_window_size: context } }],
  };
}

/** Download (the first time) and start the model on the graphics chip. */
export async function load(modelId, context, onProgress) {
  const version = await variantFor(modelId);
  const key = `${version.id}:${context}`;
  if (current && current.key === key) return;
  await unload();
  const lib = await webllm();
  const engine = await lib.CreateMLCEngine(version.id, {
    appConfig: appConfig(version, context),
    initProgressCallback: (report) => onProgress && onProgress(report.progress || 0, report.text || ""),
  }, { context_window_size: context });
  current = { key, engine };
}

export async function unload() {
  const old = current;
  current = null;
  if (old && old.engine && old.engine.unload) await old.engine.unload().catch(() => {});
}

export const loadedKey = () => (current ? current.key : "");

/** Delete a graphics-chip model's files from the phone. */
export async function remove(modelId) {
  const versions = GPU_MODELS[modelId] || {};
  const lib = await webllm();
  await unload();
  for (const version of Object.values(versions)) {
    await lib.deleteModelAllInfoInCache(version.id, appConfig(version, 2048)).catch(() => {});
  }
}

// Qwen3's own way of offering tools (the format it was trained on): the
// tools go in the system message, and it answers with <tool_call> blocks.
function toolBlock(tools) {
  const lines = tools.map((tool) => JSON.stringify(tool.function ? { type: "function", function: tool.function } : tool));
  return (
    "\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\n" +
    `You are provided with function signatures within <tools></tools> XML tags:\n<tools>\n${lines.join("\n")}\n</tools>\n\n` +
    'For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>'
  );
}

const textOf = (content) =>
  typeof content === "string"
    ? content
    : Array.isArray(content)
      ? content.map((part) => (part.type === "text" ? part.text : part.type === "image_url" ? "[a picture: this model can't see pictures]" : "")).filter(Boolean).join("\n")
      : "";

function argsOf(text) {
  try {
    return typeof text === "string" ? JSON.parse(text || "{}") : text || {};
  } catch {
    return {};
  }
}

/** FCC's chat (OpenAI shape, with tools) as plain messages WebLLM accepts:
 * one system message first, tool results as the user's turn, and no two
 * turns in a row from the same side. */
export function toMessages(messages, tools) {
  const out = [];
  const add = (role, content) => {
    if (!content) return;
    const last = out[out.length - 1];
    if (last && last.role === role) last.content += `\n\n${content}`;
    else out.push({ role, content });
  };
  let system = "";
  for (const message of messages) {
    const text = textOf(message.content);
    if (message.role === "system") system += `${system ? "\n\n" : ""}${text}`;
    else if (message.role === "tool") add("user", `<tool_response>\n${text}\n</tool_response>`);
    else if (message.role === "assistant") {
      const calls = (message.tool_calls || []).map((call) => `<tool_call>\n${JSON.stringify({ name: call.function.name, arguments: argsOf(call.function.arguments) })}\n</tool_call>`);
      add("assistant", [text, ...calls].filter(Boolean).join("\n"));
    } else add("user", text);
  }
  if (tools && tools.length) system += toolBlock(tools);
  if (system) out.unshift({ role: "system", content: system });
  // WebLLM wants the last turn to be the user's.
  if (!out.length || out[out.length - 1].role !== "user") out.push({ role: "user", content: "Go on." });
  return out;
}

/** The model's reply in FCC's shape: thinking removed, <tool_call> blocks
 * turned into tool calls. */
export function fromReply(text) {
  let content = String(text || "")
    .replace(/<think>[\s\S]*?<\/think>/g, "")
    .replace(/^[\s\S]*?<\/think>/, "");
  const calls = [];
  content = content.replace(/<tool_call>\s*([\s\S]*?)\s*(?:<\/tool_call>|$)/g, (whole, body) => {
    try {
      const call = JSON.parse(body);
      if (!call || !call.name) return whole;
      calls.push({ id: `call_${calls.length}_${Date.now().toString(36)}`, type: "function", function: { name: String(call.name), arguments: JSON.stringify(call.arguments ?? {}) } });
      return "";
    } catch {
      return whole;
    }
  });
  const message = { role: "assistant", content: content.trim() };
  if (calls.length) message.tool_calls = calls;
  return message;
}

/** One answer from the graphics chip. */
export async function chat({ messages, tools, maxTokens, temperature }) {
  if (!current) throw new Error("The model isn't loaded.");
  const started = performance.now();
  const response = await current.engine.chat.completions.create({
    messages: toMessages(messages, tools),
    max_tokens: maxTokens,
    temperature,
  });
  const usage = response.usage || {};
  const seconds = (performance.now() - started) / 1000;
  const speed = (usage.extra && usage.extra.decode_tokens_per_s) || (usage.completion_tokens && seconds ? usage.completion_tokens / seconds : 0);
  const reply = (response.choices && response.choices[0] && response.choices[0].message) || {};
  return { message: fromReply(reply.content), speed, readSpeed: (usage.extra && usage.extra.prefill_tokens_per_s) || 0 };
}
