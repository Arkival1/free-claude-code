// Where an agent thinks: a model on this phone, a free cloud AI, or the PC.
import { state, save } from "./state.js";
import * as engine from "./engine.js";
import { pcCall } from "./sync.js";

export const PROVIDERS = {
  local: {
    label: "On this phone",
    note: "A model running on the iPhone itself: private, free, and works offline.",
  },
  gemini: {
    label: "Google Gemini",
    base: "https://generativelanguage.googleapis.com/v1beta/openai",
    keyUrl: "https://aistudio.google.com/apikey",
    note: "Free with a Google account. The most generous free tier.",
  },
  groq: {
    label: "Groq",
    base: "https://api.groq.com/openai/v1",
    keyUrl: "https://console.groq.com/keys",
    note: "Free tier, very fast replies.",
  },
  openrouter: {
    label: "OpenRouter (free models)",
    base: "https://openrouter.ai/api/v1",
    keyUrl: "https://openrouter.ai/keys",
    note: "Many free models; about 50 free messages a day.",
  },
  custom: {
    label: "Other (OpenAI-compatible)",
    base: "",
    keyUrl: "",
    note: "Any service with an OpenAI-style /chat/completions that allows apps in a browser.",
  },
  pc: {
    label: "My PC (FCC Studio)",
    note: "Thinks with your PC's main AI. The PC must be on and paired.",
  },
};
export const CLOUD = ["gemini", "groq", "openrouter", "custom"];

export class BrainError extends Error {}

export const brainOf = (agent) => (agent.brain && agent.brain !== "default" ? agent.brain : state.settings.brain);
export const baseOf = (brain) => (brain === "custom" ? state.settings.customBase.replace(/\/+$/, "") : PROVIDERS[brain] && PROVIDERS[brain].base);

export function localModelOf(agent) {
  const id = (agent.brain === "local" && agent.model) || state.settings.localModel;
  return engine.modelById(id) || state.models.find((model) => model.ready);
}

export function modelOf(agent) {
  const brain = brainOf(agent);
  if (brain === "local") {
    const model = localModelOf(agent);
    return model ? model.name : "";
  }
  if (brain === "pc") return (state.settings.pc && state.settings.pc.model) || "";
  return (agent.brain !== "default" && agent.model) || state.settings.models[brain] || "";
}

export function brainReady(brain) {
  if (brain === "local") return state.models.some((model) => model.ready);
  if (brain === "pc") return Boolean(state.settings.pc && state.settings.pc.token);
  return Boolean(brain && state.settings.keys[brain] && baseOf(brain));
}

/** A brain that runs on the phone or the user's own PC keeps memory private. */
export function isPrivate(agent) {
  const brain = brainOf(agent);
  if (brain === "local") return true;
  if (brain === "pc") return Boolean(state.settings.pc && state.settings.pc.private);
  return false;
}

export async function request(url, options = {}, timeout = 120000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") throw new BrainError("It took too long to answer. Try again.");
    throw new BrainError("Couldn't reach it. Check the internet connection.");
  } finally {
    clearTimeout(timer);
  }
}

export async function errorText(response) {
  try {
    const body = await response.json();
    const message = (body.error && (body.error.message || body.error)) || body.detail || body.message;
    return typeof message === "string" ? message : JSON.stringify(message);
  } catch {
    return response.statusText || `status ${response.status}`;
  }
}

const cleanId = (id) => String(id || "").replace(/^models\//, "");

export function bestModel(brain, rows) {
  const ids = rows.map((row) => row.id);
  if (brain === "gemini") {
    const usable = ids.filter((id) => /gemini/.test(id) && !/embed|tts|image|live|aqa|vision|native-audio|thinking-exp/.test(id));
    const flash = usable.filter((id) => /flash/.test(id) && !/lite/.test(id));
    const pool = flash.length ? flash : usable;
    const version = (id) => parseFloat((id.match(/gemini-(\d+(?:\.\d+)?)/) || [0, 0])[1]);
    pool.sort((a, b) => version(b) - version(a) || a.length - b.length);
    return pool[0] || ids[0] || "";
  }
  if (brain === "groq") {
    const usable = ids.filter((id) => !/whisper|tts|guard|playai|distil|compound|orpheus/.test(id));
    return usable.find((id) => /llama-3\.3-70b/.test(id)) || usable.find((id) => /70b|120b/.test(id)) || usable[0] || "";
  }
  if (brain === "openrouter") {
    const free = rows.filter((row) => row.id.endsWith(":free"));
    const tools = free.filter((row) => (row.supported_parameters || []).includes("tools"));
    const pool = (tools.length ? tools : free).slice();
    pool.sort((a, b) => (b.context_length || 0) - (a.context_length || 0));
    return (pool[0] && pool[0].id) || "";
  }
  return ids[0] || "";
}

export async function listModels(brain) {
  const base = baseOf(brain);
  const key = state.settings.keys[brain];
  if (!base) throw new BrainError("Add the service's address first.");
  const response = await request(`${base}/models`, { headers: key ? { Authorization: `Bearer ${key}` } : {} }, 20000);
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw new BrainError(`${PROVIDERS[brain].label} refused that key. Check it and paste it again.`);
    throw new BrainError(`${PROVIDERS[brain].label}: ${await errorText(response)}`);
  }
  const body = await response.json();
  let rows = (body.data || body.models || []).map((row) => ({ ...row, id: cleanId(row.id || row.name) }));
  if (brain === "openrouter") rows = rows.filter((row) => row.id.endsWith(":free"));
  rows.sort((a, b) => a.id.localeCompare(b.id));
  state.modelLists[brain] = rows;
  if (!state.settings.models[brain] || !rows.some((row) => row.id === state.settings.models[brain])) {
    state.settings.models[brain] = bestModel(brain, rows);
    await save.settings();
  }
  return rows;
}

export const stripThinking = (text) => String(text || "").replace(/<think>[\s\S]*?(<\/think>|$)/gi, "").trim();

function parseArgs(raw) {
  if (raw && typeof raw === "object") return raw;
  try {
    return JSON.parse(raw || "{}");
  } catch {
    return {};
  }
}

function normalise(message) {
  return {
    text: stripThinking(message.content || ""),
    tool_calls: (message.tool_calls || []).map((call, index) => ({
      id: call.id || `call_${Date.now()}_${index}`,
      name: (call.function && call.function.name) || call.name,
      arguments: parseArgs((call.function && call.function.arguments) || call.arguments),
    })),
  };
}

/** One model call for an agent: {text, tool_calls: [{id, name, arguments}]}. */
export async function think(agent, system, messages, tools = [], { maxTokens = 1200 } = {}) {
  const brain = brainOf(agent);
  if (!brain) throw new BrainError("Pick a brain first: Models for one on this phone, or More, Settings for a free cloud AI.");
  if (brain === "pc") {
    const reply = await pcCall("/studio/api/phone/complete", { system, messages, tools });
    return normalise({ content: reply.text, tool_calls: (reply.tool_calls || []).map((call) => ({ id: call.id, function: { name: call.name, arguments: call.arguments } })) });
  }
  if (brain === "local") {
    const model = localModelOf(agent);
    if (!model) throw new BrainError("No model on this phone yet. Open Models and download one (Qwen3 0.6B is a quick start).");
    if (!model.ready) throw new BrainError(`${model.name} hasn't finished downloading. Open Models to finish it.`);
    const system2 = model.info && model.info.reasoning ? `${system}\n\n/no_think` : system;
    const message = await engine.chat(model, { messages: [{ role: "system", content: system2 }, ...messages], tools, maxTokens: Math.min(maxTokens, 1024) });
    return normalise(message);
  }
  if (!brainReady(brain)) throw new BrainError(`Add your ${PROVIDERS[brain].label} key in More, Settings first.`);
  let model = modelOf(agent);
  if (!model) {
    await listModels(brain);
    model = modelOf(agent);
  }
  if (!model) throw new BrainError(`Pick a model for ${PROVIDERS[brain].label} in Settings.`);
  const useTools = tools.length && !state.settings.noTools[`${brain}:${model}`];
  const body = { model, messages: [{ role: "system", content: system }, ...messages], temperature: 0.5, max_tokens: maxTokens };
  if (useTools) body.tools = tools;
  const headers = { Authorization: `Bearer ${state.settings.keys[brain]}`, "Content-Type": "application/json" };
  if (brain === "openrouter") {
    headers["HTTP-Referer"] = location.origin;
    headers["X-Title"] = "FCC Phone";
  }
  const response = await request(`${baseOf(brain)}/chat/completions`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!response.ok) {
    const detail = await errorText(response);
    if (useTools && [400, 404, 422].includes(response.status) && /tool|function/i.test(detail)) {
      state.settings.noTools[`${brain}:${model}`] = true;
      await save.settings();
      return think(agent, system, messages.filter((m) => m.role === "user" || (m.role === "assistant" && !m.tool_calls)), [], { maxTokens });
    }
    if (response.status === 401 || response.status === 403) throw new BrainError(`${PROVIDERS[brain].label} refused the key. Check it in Settings.`);
    if (response.status === 429) throw new BrainError(`${PROVIDERS[brain].label}'s free limit is used up for now. Wait a bit, or pick another brain.`);
    throw new BrainError(`${PROVIDERS[brain].label}: ${detail}`);
  }
  const data = await response.json();
  return normalise((data.choices && data.choices[0] && data.choices[0].message) || {});
}
