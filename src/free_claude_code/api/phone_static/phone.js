/* FCC Phone: your own agents, with their own memory, on your phone.
   Everything lives on the phone (IndexedDB). Agents think with a free AI you
   pick (Gemini, Groq, OpenRouter, or any OpenAI-style service), or with your
   PC's AI once paired. Pairing also shares memories with the PC. */
(() => {
  "use strict";

  const VERSION = "1.0.0";
  const MAX_TOOL_ROUNDS = 6;
  const HISTORY_TURNS = 20;
  const PROVIDERS = {
    gemini: {
      label: "Google Gemini",
      base: "https://generativelanguage.googleapis.com/v1beta/openai",
      keyUrl: "https://aistudio.google.com/apikey",
      note: "Free with a Google account. The most generous free tier: recommended.",
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
  const TEMPLATES = [
    {
      name: "Helper",
      role: "planner",
      instructions:
        "You plan things with the user: break goals into clear numbered steps, say what to check, and keep plans short and doable. Use calculate for every sum.",
    },
    {
      name: "Researcher",
      role: "researcher",
      instructions:
        "You look things up before answering. Use wikipedia for facts, say where facts came from, and say plainly when you are not sure.",
    },
    {
      name: "Coach",
      role: "coach",
      instructions:
        "You are an encouraging fitness and habits coach. Remember the user's goals and progress with remember, and check recall before giving advice.",
    },
    { name: "Custom", role: "assistant", instructions: "" },
  ];

  // ----------------------------------------------------------------- helpers

  const $ = (id) => document.getElementById(id);
  const view = $("view");
  const uid = () =>
    (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, "").slice(0, 16);

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "value") node.value = value;
      else if (key === "checked") node.checked = Boolean(value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of [].concat(children)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const card = (title, children) => el("section", { class: "card" }, [el("h2", { text: title }), ...[].concat(children)]);
  const empty = (text) => el("p", { class: "empty", text });

  let toastTimer = null;
  function notify(text) {
    const toast = $("toast");
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.hidden = true), 3200);
  }

  function openSheet(title, children) {
    $("sheet-title").textContent = title;
    $("sheet-body").replaceChildren(...[].concat(children).filter(Boolean));
    $("sheet").hidden = false;
  }
  function closeSheet() {
    $("sheet").hidden = true;
    $("sheet-body").replaceChildren();
  }
  $("sheet").addEventListener("click", (event) => {
    if (event.target.hasAttribute("data-close")) closeSheet();
  });

  const ago = (ms) => {
    if (!ms) return "never";
    const minutes = Math.round((Date.now() - ms) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} h ago`;
    return new Date(ms).toLocaleDateString();
  };

  const words = (text) =>
    String(text || "")
      .toLowerCase()
      .match(/[a-z0-9']{3,}/g) || [];

  // ----------------------------------------------------------------- storage

  const store = (() => {
    const memoryOnly = new Map();
    let opening = null;
    const open = () => {
      if (!("indexedDB" in window)) return Promise.resolve(null);
      opening =
        opening ||
        new Promise((resolve) => {
          try {
            const request = indexedDB.open("fcc-phone", 1);
            request.onupgradeneeded = () => request.result.createObjectStore("kv");
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve(null);
          } catch {
            resolve(null);
          }
        });
      return opening;
    };
    const run = async (mode, work) => {
      const db = await open();
      if (!db) return work(null);
      return new Promise((resolve, reject) => {
        const tx = db.transaction("kv", mode);
        const request = work(tx.objectStore("kv"));
        tx.oncomplete = () => resolve(request ? request.result : undefined);
        tx.onerror = () => reject(tx.error);
      });
    };
    return {
      async get(key, fallback) {
        try {
          const value = await run("readonly", (kv) => (kv ? kv.get(key) : null));
          if (value !== undefined && value !== null) return value;
        } catch {
          /* fall through to the copy in memory */
        }
        return memoryOnly.has(key) ? memoryOnly.get(key) : fallback;
      },
      async set(key, value) {
        memoryOnly.set(key, value);
        try {
          await run("readwrite", (kv) => (kv ? kv.put(value, key) : null));
        } catch {
          /* kept in memory for this visit */
        }
      },
      async remove(key) {
        memoryOnly.delete(key);
        try {
          await run("readwrite", (kv) => (kv ? kv.delete(key) : null));
        } catch {
          /* nothing to remove */
        }
      },
      durable: async () => Boolean(await open()),
    };
  })();

  const state = {
    settings: null,
    agents: [],
    memories: [],
    pcMemories: [],
    chats: {},
    modelLists: {},
    route: "chat",
    agentId: null,
    busy: false,
  };

  const defaultSettings = () => ({
    brain: "",
    keys: { gemini: "", groq: "", openrouter: "", custom: "" },
    customBase: "",
    models: { gemini: "", groq: "", openrouter: "", custom: "" },
    noTools: {},
    pc: null,
    cloudSeesPc: false,
    speak: false,
  });

  const jarvis = () => ({
    id: "jarvis",
    name: "Jarvis",
    role: "main",
    instructions:
      "You are the user's personal AI on their phone: warm, quick, and practical. Remember what matters about the user with remember, and check recall before answering anything personal.",
    brain: "default",
    model: "",
    created_at: Date.now(),
  });

  const save = {
    settings: () => store.set("settings", state.settings),
    agents: () => store.set("agents", state.agents),
    memories: () => store.set("memories", state.memories),
    pcMemories: () => store.set("pcMemories", state.pcMemories),
    chat: (agentId) => store.set(`chat:${agentId}`, state.chats[agentId] || []),
  };

  async function load() {
    state.settings = Object.assign(defaultSettings(), await store.get("settings", {}));
    state.settings.keys = Object.assign(defaultSettings().keys, state.settings.keys);
    state.settings.models = Object.assign(defaultSettings().models, state.settings.models);
    state.agents = await store.get("agents", []);
    if (!state.agents.some((agent) => agent.id === "jarvis")) {
      state.agents.unshift(jarvis());
      await save.agents();
    }
    state.memories = await store.get("memories", []);
    state.pcMemories = await store.get("pcMemories", []);
    state.agentId = (await store.get("agentId", "jarvis")) || "jarvis";
    if (!state.agents.some((agent) => agent.id === state.agentId)) state.agentId = "jarvis";
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  }

  async function chatOf(agentId) {
    if (!state.chats[agentId]) state.chats[agentId] = await store.get(`chat:${agentId}`, []);
    return state.chats[agentId];
  }

  const agentById = (id) => state.agents.find((agent) => agent.id === id) || state.agents[0];

  // ------------------------------------------------------------------ brains

  const brainOf = (agent) => (agent.brain && agent.brain !== "default" ? agent.brain : state.settings.brain);
  const brainReady = (brain) =>
    brain === "pc" ? Boolean(state.settings.pc && state.settings.pc.token) : Boolean(brain && state.settings.keys[brain] && baseOf(brain));
  const baseOf = (brain) => (brain === "custom" ? state.settings.customBase.replace(/\/+$/, "") : PROVIDERS[brain] && PROVIDERS[brain].base);
  const modelOf = (agent) => {
    const brain = brainOf(agent);
    return (agent.brain !== "default" && agent.model) || state.settings.models[brain] || "";
  };

  class BrainError extends Error {}

  async function request(url, options = {}, timeout = 90000) {
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

  async function errorText(response) {
    try {
      const body = await response.json();
      const message = body.error && (body.error.message || body.error) || body.detail || body.message;
      return typeof message === "string" ? message : JSON.stringify(message);
    } catch {
      return response.statusText || `status ${response.status}`;
    }
  }

  function cleanModelId(id) {
    return String(id || "").replace(/^models\//, "");
  }

  function bestModel(brain, rows) {
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

  async function listModels(brain) {
    if (brain === "pc") return [];
    const base = baseOf(brain);
    const key = state.settings.keys[brain];
    if (!base) throw new BrainError("Add the service's address first.");
    const headers = key ? { Authorization: `Bearer ${key}` } : {};
    const response = await request(`${base}/models`, { headers }, 20000);
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) throw new BrainError(`${PROVIDERS[brain].label} refused that key. Check it and paste it again.`);
      throw new BrainError(`${PROVIDERS[brain].label}: ${await errorText(response)}`);
    }
    const body = await response.json();
    let rows = (body.data || body.models || []).map((row) => ({ ...row, id: cleanModelId(row.id || row.name) }));
    if (brain === "openrouter") rows = rows.filter((row) => row.id.endsWith(":free"));
    rows.sort((a, b) => a.id.localeCompare(b.id));
    state.modelLists[brain] = rows;
    if (!state.settings.models[brain] || !rows.some((row) => row.id === state.settings.models[brain])) {
      state.settings.models[brain] = bestModel(brain, rows);
      await save.settings();
    }
    return rows;
  }

  /** One model call. Returns {text, tool_calls: [{id, name, arguments}]}. */
  async function think(agent, system, messages, tools) {
    const brain = brainOf(agent);
    if (!brain) throw new BrainError("Pick a brain first: Settings, Brain.");
    if (brain === "pc") return thinkOnPc(system, messages, tools);
    if (!brainReady(brain)) throw new BrainError(`Add your ${PROVIDERS[brain].label} key in Settings first.`);
    let model = modelOf(agent);
    if (!model) {
      await listModels(brain);
      model = modelOf(agent);
    }
    if (!model) throw new BrainError(`Pick a model for ${PROVIDERS[brain].label} in Settings.`);
    const useTools = tools.length && !state.settings.noTools[`${brain}:${model}`];
    const body = {
      model,
      messages: [{ role: "system", content: system }, ...messages],
      temperature: 0.5,
      max_tokens: 1200,
    };
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
        // This model can't take tools: answer without them from now on.
        state.settings.noTools[`${brain}:${model}`] = true;
        await save.settings();
        return think(agent, system, messages.filter((m) => m.role === "user" || (m.role === "assistant" && !m.tool_calls)), []);
      }
      if (response.status === 401 || response.status === 403) throw new BrainError(`${PROVIDERS[brain].label} refused the key. Check it in Settings.`);
      if (response.status === 429) throw new BrainError(`${PROVIDERS[brain].label}'s free limit is used up for now. Wait a bit, or pick another brain in Settings.`);
      throw new BrainError(`${PROVIDERS[brain].label}: ${detail}`);
    }
    const data = await response.json();
    const message = (data.choices && data.choices[0] && data.choices[0].message) || {};
    return {
      text: stripThinking(message.content || ""),
      tool_calls: (message.tool_calls || []).map((call, index) => ({
        id: call.id || `call_${Date.now()}_${index}`,
        name: call.function && call.function.name,
        arguments: parseArgs(call.function && call.function.arguments),
      })),
    };
  }

  const stripThinking = (text) => String(text).replace(/<think>[\s\S]*?(<\/think>|$)/gi, "").trim();

  function parseArgs(raw) {
    if (raw && typeof raw === "object") return raw;
    try {
      return JSON.parse(raw || "{}");
    } catch {
      return {};
    }
  }

  // --------------------------------------------------------------- the PC

  const pcUrl = (path) => `${state.settings.pc.address}${path}`;

  async function pcCall(path, payload, method = "POST", timeout = 120000) {
    const pc = state.settings.pc;
    if (!pc) throw new BrainError("This phone isn't paired with a PC.");
    const response = await request(
      pcUrl(path),
      {
        method,
        headers: { Authorization: `Bearer ${pc.token}`, "Content-Type": "application/json" },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      },
      timeout
    ).catch((error) => {
      throw new BrainError(`Couldn't reach your PC. Is it on, with Studio running and Tailscale connected? (${error.message})`);
    });
    if (response.status === 401) {
      pc.broken = true;
      await save.settings();
      throw new BrainError("Your PC doesn't know this phone any more. Pair again in Settings.");
    }
    if (!response.ok) throw new BrainError(`Your PC: ${await errorText(response)}`);
    return response.json();
  }

  async function thinkOnPc(system, messages, tools) {
    const reply = await pcCall("/studio/api/phone/complete", { system, messages, tools });
    return { text: stripThinking(reply.text || ""), tool_calls: reply.tool_calls || [] };
  }

  function normalAddress(raw) {
    let address = String(raw || "").trim();
    if (!address) throw new BrainError("Type your PC's address.");
    if (!/^https?:\/\//i.test(address)) address = `https://${address}`;
    address = address.replace(/\/+$/, "").replace(/\/(studio|phone)(\/.*)?$/i, "");
    if (location.protocol === "https:" && address.startsWith("http:")) {
      throw new BrainError("Use your PC's https:// address (from Tailscale). A phone app on https can't reach plain http.");
    }
    return address;
  }

  async function pair(rawAddress, code) {
    const address = normalAddress(rawAddress);
    const response = await request(
      `${address}/studio/api/phone/pair`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code.trim(), name: phoneName() }),
      },
      20000
    ).catch(() => {
      throw new BrainError("Couldn't reach that address. Check the PC is on, Studio is running, and Tailscale is connected on both.");
    });
    if (!response.ok) throw new BrainError(await errorText(response));
    const body = await response.json();
    state.settings.pc = {
      address,
      token: body.token,
      pcName: body.pc,
      main: body.main,
      model: body.model,
      private: Boolean(body.private),
      lastSync: 0,
      broken: false,
    };
    await save.settings();
    await sync();
  }

  function phoneName() {
    const ua = navigator.userAgent;
    return /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android phone" : "Phone";
  }

  let syncing = null;
  async function sync({ quiet = false } = {}) {
    if (!state.settings.pc) return;
    if (syncing) return syncing;
    syncing = (async () => {
      const pending = state.memories.filter((memory) => !memory.synced);
      const agentName = (id) => (state.agents.find((agent) => agent.id === id) || { name: "Phone" }).name;
      try {
        const result = await pcCall("/studio/api/phone/sync", {
          memories: pending.slice(0, 500).map((memory) => ({ id: memory.id, agent: agentName(memory.agent_id), text: memory.text })),
        });
        const sent = new Set(pending.slice(0, 500).map((memory) => memory.id));
        for (const memory of state.memories) if (sent.has(memory.id)) memory.synced = true;
        state.pcMemories = result.pc_memories || [];
        Object.assign(state.settings.pc, { private: Boolean(result.private), lastSync: Date.now(), broken: false });
        await Promise.all([save.memories(), save.pcMemories(), save.settings()]);
        if (!quiet) notify(`Synced with your PC: ${sent.size} sent, ${state.pcMemories.length} from the PC.`);
      } catch (error) {
        if (!quiet) notify(error.message);
        throw error;
      } finally {
        syncing = null;
        drawBar();
      }
    })();
    return syncing;
  }

  let syncTimer = null;
  const syncSoon = () => {
    if (!state.settings.pc) return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => sync({ quiet: true }).catch(() => {}), 4000);
  };

  // ------------------------------------------------------------------ tools

  const TOOL_SPECS = [
    {
      name: "remember",
      description: "Save one fact worth keeping: something about the user, a plan, a preference, a result. Saved on the phone (and shared with the user's PC when paired).",
      parameters: { type: "object", properties: { text: { type: "string", description: "The fact, in one clear sentence." } }, required: ["text"] },
    },
    {
      name: "recall",
      description: "Search your memory for what you know about something before answering.",
      parameters: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    },
    {
      name: "calculate",
      description: "Exact arithmetic: + - * / % ^, brackets, sqrt, round, min, max, '15% of 80'. Use it for every sum.",
      parameters: { type: "object", properties: { expression: { type: "string" } }, required: ["expression"] },
    },
    {
      name: "weather",
      description: "The weather now and for the next days in any town or city.",
      parameters: {
        type: "object",
        properties: { place: { type: "string" }, days: { type: "integer", description: "1 to 7, default 3" } },
        required: ["place"],
      },
    },
    {
      name: "wikipedia",
      description: "Look a fact, person, place, or topic up on Wikipedia and read the summary.",
      parameters: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    },
  ];
  const TOOLS = TOOL_SPECS.map((spec) => ({ type: "function", function: spec }));

  async function runTool(agent, call) {
    const args = call.arguments || {};
    try {
      switch (call.name) {
        case "remember":
          return remember(agent, String(args.text || ""));
        case "recall": {
          const found = recall(agent, String(args.query || ""), 8);
          return found.length ? found.map((row) => `- ${row.text}${row.from ? ` (${row.from})` : ""}`).join("\n") : "Nothing in memory about that.";
        }
        case "calculate":
          return `${args.expression} = ${formatNumber(calculate(String(args.expression || "")))}`;
        case "weather":
          return await weather(String(args.place || ""), Number(args.days) || 3);
        case "wikipedia":
          return await wikipedia(String(args.query || ""));
        default:
          return `There is no tool called ${call.name}.`;
      }
    } catch (error) {
      return `${call.name} failed: ${error.message}`;
    }
  }

  async function remember(agent, text) {
    const clean = text.trim();
    if (!clean) return "Nothing to remember.";
    const same = state.memories.find((memory) => memory.text.toLowerCase() === clean.toLowerCase());
    if (same) return `Already remembered: ${same.text}`;
    state.memories.unshift({ id: uid(), agent_id: agent.id, text: clean.slice(0, 2000), created_at: Date.now(), synced: false });
    await save.memories();
    syncSoon();
    return `Saved to memory: ${clean}`;
  }

  /** What may reach this agent's brain from the PC's memory. */
  function pcMemoryAllowed(agent) {
    const pc = state.settings.pc;
    if (!pc || !state.pcMemories.length) return false;
    if (brainOf(agent) === "pc" && pc.private) return true;
    return Boolean(state.settings.cloudSeesPc);
  }

  function recall(agent, query, limit) {
    const terms = new Set(words(query));
    const score = (text) => words(text).reduce((sum, word) => sum + (terms.has(word) ? 1 : 0), 0);
    const rows = state.memories.map((memory) => ({ text: memory.text, at: memory.created_at, score: score(memory.text), from: "" }));
    if (pcMemoryAllowed(agent)) {
      for (const memory of state.pcMemories) rows.push({ text: memory.text, at: memory.created_at, score: score(memory.text), from: "from your PC" });
    }
    return rows
      .filter((row) => row.score > 0)
      .sort((a, b) => b.score - a.score || b.at - a.at)
      .slice(0, limit);
  }

  function formatNumber(value) {
    if (!Number.isFinite(value)) throw new Error("that isn't a number");
    return Number.isInteger(value) ? value.toLocaleString("en-US", { useGrouping: false }) : String(Number(value.toPrecision(12)));
  }

  /** A small, safe maths reader: numbers, + - * / % ^, brackets, and a few functions. */
  function calculate(source) {
    const text = source
      .toLowerCase()
      .replace(/×/g, "*")
      .replace(/÷/g, "/")
      .replace(/,/g, "")
      .replace(/(\d+(?:\.\d+)?)\s*%\s*of\s*/g, "($1/100)*");
    const tokens = text.match(/\d+(?:\.\d+)?(?:e[+-]?\d+)?|[a-z]+|\*\*|[-+*/%^(),]|\S/g) || [];
    let index = 0;
    const peek = () => tokens[index];
    const take = (expected) => {
      const token = tokens[index++];
      if (expected && token !== expected) throw new Error(`expected ${expected}`);
      return token;
    };
    const FUNCTIONS = {
      sqrt: Math.sqrt, abs: Math.abs, round: Math.round, floor: Math.floor, ceil: Math.ceil,
      log: Math.log10, ln: Math.log, sin: Math.sin, cos: Math.cos, tan: Math.tan, min: Math.min, max: Math.max,
    };
    const CONSTANTS = { pi: Math.PI, e: Math.E };
    const expression = () => {
      let value = term();
      while (peek() === "+" || peek() === "-") value = take() === "+" ? value + term() : value - term();
      return value;
    };
    const term = () => {
      let value = power();
      while (peek() === "*" || peek() === "/" || peek() === "%") {
        const op = take();
        const right = power();
        value = op === "*" ? value * right : op === "/" ? value / right : value % right;
      }
      return value;
    };
    const power = () => {
      const base = unary();
      if (peek() === "^" || peek() === "**") {
        take();
        return base ** power();
      }
      return base;
    };
    const unary = () => {
      if (peek() === "-") {
        take();
        return -unary();
      }
      if (peek() === "+") {
        take();
        return unary();
      }
      return atom();
    };
    const atom = () => {
      const token = take();
      if (token === undefined) throw new Error("the sum ended early");
      if (token === "(") {
        const value = expression();
        take(")");
        return value;
      }
      if (/^\d/.test(token)) return parseFloat(token);
      if (token in CONSTANTS) return CONSTANTS[token];
      if (token in FUNCTIONS) {
        take("(");
        const args = [expression()];
        while (peek() === ",") {
          take();
          args.push(expression());
        }
        take(")");
        return FUNCTIONS[token](...args);
      }
      throw new Error(`can't read "${token}"`);
    };
    const value = expression();
    if (index < tokens.length) throw new Error(`can't read "${tokens[index]}"`);
    return value;
  }

  const WEATHER = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "severe thunderstorms with hail",
  };

  async function getJson(url) {
    const response = await request(url, {}, 20000);
    if (!response.ok) throw new Error(`the service answered ${response.status}`);
    return response.json();
  }

  async function weather(place, days) {
    if (!place.trim()) throw new Error("say which town or city");
    const found = await getJson(`https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&format=json&name=${encodeURIComponent(place)}`);
    const spot = found.results && found.results[0];
    if (!spot) return `No place called ${place} was found.`;
    const count = Math.max(1, Math.min(7, days));
    const data = await getJson(
      `https://api.open-meteo.com/v1/forecast?latitude=${spot.latitude}&longitude=${spot.longitude}&timezone=auto&forecast_days=${count}` +
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m" +
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    );
    const now = data.current || {};
    const where = [spot.name, spot.admin1, spot.country].filter(Boolean).join(", ");
    const lines = [
      `Weather in ${where}: now ${Math.round(now.temperature_2m)}°C (feels like ${Math.round(now.apparent_temperature)}°C), ${WEATHER[now.weather_code] || "mixed weather"}, wind ${Math.round(now.wind_speed_10m)} km/h, humidity ${Math.round(now.relative_humidity_2m)}%.`,
    ];
    const daily = data.daily || {};
    (daily.time || []).forEach((day, i) => {
      const label = i === 0 ? "Today" : i === 1 ? "Tomorrow" : new Date(`${day}T12:00`).toLocaleDateString("en", { weekday: "long" });
      const rain = (daily.precipitation_probability_max || [])[i];
      lines.push(
        `${label}: ${WEATHER[(daily.weather_code || [])[i]] || "mixed weather"}, ${Math.round(daily.temperature_2m_max[i])}°C high, ${Math.round(daily.temperature_2m_min[i])}°C low${rain === null || rain === undefined ? "" : `, ${rain}% chance of rain`}.`
      );
    });
    return lines.join("\n");
  }

  async function wikipedia(query) {
    if (!query.trim()) throw new Error("say what to look up");
    const found = await getJson(
      `https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&origin=*&srlimit=3&srsearch=${encodeURIComponent(query)}`
    );
    const hits = (found.query && found.query.search) || [];
    if (!hits.length) return `Wikipedia has nothing on ${query}.`;
    const title = hits[0].title;
    const page = await getJson(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title.replace(/ /g, "_"))}`);
    const link = (page.content_urls && page.content_urls.mobile && page.content_urls.mobile.page) || "";
    const others = hits.slice(1).map((hit) => hit.title);
    return `${page.title}: ${page.extract || "(no summary)"}${link ? `\nSource: ${link}` : ""}${others.length ? `\nAlso: ${others.join(", ")}` : ""}`;
  }

  // -------------------------------------------------------------- thinking

  function systemPrompt(agent, question) {
    const now = new Date();
    const parts = [
      agent.role === "main"
        ? `You are ${agent.name}, the user's main AI.`
        : `You are ${agent.name}, one of the user's AI agents (${agent.role}).`,
      agent.instructions || "",
      `You run inside FCC Phone on the user's phone. It is ${now.toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })}.`,
      "Tools: remember saves a fact worth keeping about the user or their plans; recall searches memory; calculate does exact maths; weather gives the weather anywhere; wikipedia looks things up. Keep replies short and easy to read on a phone.",
    ];
    const relevant = recall(agent, question, 6);
    const recent = state.memories.slice(0, 4).filter((memory) => !relevant.some((row) => row.text === memory.text));
    const lines = [...relevant.map((row) => `- ${row.text}${row.from ? ` (${row.from})` : ""}`), ...recent.map((memory) => `- ${memory.text}`)];
    if (lines.length) parts.push(`What you remember (use it when it helps):\n${lines.join("\n")}`);
    return parts.filter(Boolean).join("\n\n");
  }

  async function history(agent) {
    const turns = (await chatOf(agent.id)).filter((turn) => turn.role === "user" || turn.role === "assistant");
    return turns.slice(-HISTORY_TURNS).map((turn) => ({ role: turn.role, content: turn.text }));
  }

  async function addTurn(agent, turn) {
    const chat = await chatOf(agent.id);
    chat.push({ ...turn, at: Date.now() });
    if (chat.length > 400) chat.splice(0, chat.length - 400);
    await save.chat(agent.id);
    if (state.route === "chat" && state.agentId === agent.id) drawMessages();
  }

  async function answer(agent, text) {
    state.busy = true;
    document.body.classList.add("thinking");
    drawBar();
    const convo = await history(agent);
    await addTurn(agent, { role: "user", text });
    convo.push({ role: "user", content: text });
    const system = systemPrompt(agent, text);
    try {
      for (let round = 0; round < MAX_TOOL_ROUNDS; round += 1) {
        const reply = await think(agent, system, convo, round < MAX_TOOL_ROUNDS - 1 ? TOOLS : []);
        if (!reply.tool_calls.length) {
          const said = reply.text || "(no answer)";
          await addTurn(agent, { role: "assistant", text: said });
          speak(said);
          return;
        }
        convo.push({
          role: "assistant",
          content: reply.text || "",
          tool_calls: reply.tool_calls.map((call) => ({
            id: call.id,
            type: "function",
            function: { name: call.name, arguments: JSON.stringify(call.arguments || {}) },
          })),
        });
        for (const call of reply.tool_calls) {
          const result = await runTool(agent, call);
          await addTurn(agent, { role: "tool", text: `${call.name}: ${result.split("\n")[0].slice(0, 160)}` });
          convo.push({ role: "tool", tool_call_id: call.id, content: result });
        }
      }
      await addTurn(agent, { role: "assistant", text: "I went round in circles there. Ask me again more simply?" });
    } catch (error) {
      await addTurn(agent, { role: "error", text: error.message });
    } finally {
      state.busy = false;
      document.body.classList.remove("thinking");
      drawBar();
      if (state.route === "chat") {
        drawComposerState();
        drawMessages();
      }
    }
  }

  function speak(text) {
    if (!state.settings.speak || !("speechSynthesis" in window)) return;
    try {
      speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text.replace(/[*_#`>]/g, "").slice(0, 1200));
      const english = speechSynthesis.getVoices().filter((voice) => /^en/.test(voice.lang));
      const british = english.find((voice) => /GB/.test(voice.lang) && /Daniel|Arthur|male/i.test(voice.name)) || english.find((voice) => /GB/.test(voice.lang));
      if (british) utterance.voice = british;
      speechSynthesis.speak(utterance);
    } catch {
      /* speaking is a nicety */
    }
  }

  // ------------------------------------------------------------------ views

  function drawBar() {
    const agent = agentById(state.agentId);
    const brain = brainOf(agent);
    $("title").textContent = "FCC PHONE";
    $("subtitle").textContent = state.busy
      ? `${agent.name} is thinking…`
      : brain
        ? `${agent.name} · ${PROVIDERS[brain].label}${brain !== "pc" && modelOf(agent) ? ` · ${modelOf(agent)}` : ""}`
        : "Pick a free brain in Settings to start";
    const pill = $("link-pill");
    const pc = state.settings.pc;
    pill.hidden = !pc;
    if (pc) {
      pill.textContent = pc.broken ? "PC: pair again" : `PC ${pc.lastSync ? "✓" : "…"}`;
      pill.className = `pill ${pc.broken ? "" : "good"}`;
    }
  }

  function go(route) {
    location.hash = route;
  }

  function render() {
    const route = (location.hash || "#chat").slice(1).split("/")[0] || "chat";
    state.route = ["chat", "agents", "memory", "settings"].includes(route) ? route : "chat";
    for (const tab of document.querySelectorAll(".tab")) {
      if (tab.dataset.route === state.route) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    }
    closeSheet();
    drawBar();
    ({ chat: renderChat, agents: renderAgents, memory: renderMemory, settings: renderSettings })[state.route]();
    window.scrollTo(0, 0);
  }

  let messages = null;
  let composer = null;

  async function renderChat() {
    const agent = agentById(state.agentId);
    const picker = el(
      "select",
      { "aria-label": "Agent", onchange: async () => {
        state.agentId = picker.value;
        await store.set("agentId", state.agentId);
        renderChat();
        drawBar();
      } },
      state.agents.map((item) => el("option", { value: item.id, text: item.name }))
    );
    picker.value = agent.id;
    messages = el("div", { class: "messages", "aria-live": "polite" });
    const input = el("textarea", { rows: 1, placeholder: `Message ${agent.name}`, "aria-label": "Message", enterkeyhint: "send" });
    const send = el("button", { class: "primary", type: "button", text: "Send" });
    const submit = () => {
      const text = input.value.trim();
      if (!text || state.busy) return;
      input.value = "";
      answer(agent, text);
    };
    send.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    });
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(160, input.scrollHeight)}px`;
    });
    const mic = micButton(input, submit);
    composer = { send, input };
    const nodes = [el("div", { class: "chat-head" }, [picker, el("button", { type: "button", text: "Clear", "aria-label": `Clear the chat with ${agent.name}`, onclick: () => clearChat(agent) })])];
    if (!brainReady(brainOf(agent))) nodes.push(onboarding());
    nodes.push(messages, el("div", { class: "composer" }, [input, mic, send]));
    view.replaceChildren(...nodes);
    await drawMessages();
    drawComposerState();
  }

  function drawComposerState() {
    if (!composer) return;
    composer.send.disabled = state.busy;
    composer.send.textContent = state.busy ? "…" : "Send";
  }

  async function drawMessages() {
    if (!messages) return;
    const agent = agentById(state.agentId);
    const chat = await chatOf(agent.id);
    const nodes = chat.map((turn) =>
      turn.role === "tool"
        ? el("div", { class: "msg tool", text: `⚙ ${turn.text}` })
        : el("div", { class: `msg ${turn.role}` }, [
            turn.role === "assistant" ? el("span", { class: "who", text: agent.name }) : null,
            turn.role === "error" ? el("span", { class: "who", text: "Problem" }) : null,
            turn.text,
          ])
    );
    if (!chat.length) nodes.push(el("p", { class: "muted", text: `Say hello to ${agent.name}. Try: "What's the weather in London tomorrow?", "Remember my gym days are Monday and Thursday", or "What's 15% of 240?"` }));
    if (state.busy) nodes.push(el("div", { class: "typing", text: `${agent.name} is thinking…` }));
    messages.replaceChildren(...nodes);
    requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight));
  }

  async function clearChat(agent) {
    state.chats[agent.id] = [];
    await save.chat(agent.id);
    drawMessages();
  }

  function micButton(input, submit) {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return null;
    let listening = null;
    const button = el("button", { type: "button", text: "🎤", "aria-label": "Speak" });
    button.addEventListener("click", () => {
      if (listening) {
        listening.stop();
        return;
      }
      const recognition = new Recognition();
      recognition.lang = navigator.language || "en-US";
      recognition.interimResults = true;
      recognition.onresult = (event) => {
        input.value = Array.from(event.results).map((result) => result[0].transcript).join(" ");
      };
      recognition.onend = () => {
        listening = null;
        button.textContent = "🎤";
        if (input.value.trim()) submit();
      };
      recognition.onerror = () => notify("Couldn't hear that. The keyboard's microphone works too.");
      listening = recognition;
      button.textContent = "■";
      recognition.start();
    });
    return button;
  }

  function onboarding() {
    return card("Start here", [
      el("p", { text: "Your agents need a brain. These are free:" }),
      el("ol", { class: "steps" }, [
        el("li", {}, ["Get a free key from ", el("a", { href: PROVIDERS.gemini.keyUrl, target: "_blank", rel: "noopener", text: "Google AI Studio" }), " (sign in with Google, then Create API key)."]),
        el("li", { text: "Copy the key, then come back here." }),
        el("li", {}, ["Open ", el("a", { href: "#settings", text: "Settings" }), ", paste it under Google Gemini, and press Save."]),
      ]),
      el("p", { class: "muted", text: "Groq and OpenRouter work the same way. Or pair your PC and let your agents think with its AI." }),
    ]);
  }

  // ----------------------------------------------------------------- agents

  function renderAgents() {
    const rows = state.agents.map((agent) =>
      el("div", { class: "item" }, [
        el("div", { class: "grow" }, [
          el("strong", { text: agent.name }),
          el("small", { text: `${agent.role === "main" ? "main AI" : agent.role} · ${agent.brain === "default" ? `default brain (${state.settings.brain ? PROVIDERS[state.settings.brain].label : "not set"})` : PROVIDERS[agent.brain].label}` }),
        ]),
        el("button", { type: "button", text: "Chat", "aria-label": `Chat with ${agent.name}`, onclick: async () => {
          state.agentId = agent.id;
          await store.set("agentId", agent.id);
          go("chat");
        } }),
        el("button", { type: "button", text: "Edit", "aria-label": `Edit ${agent.name}`, onclick: () => editAgent(agent) }),
      ])
    );
    view.replaceChildren(
      card("Your phone agents", [
        el("p", { class: "muted", text: "These agents live on this phone, apart from the ones on your PC. They share one memory here, and each can have its own brain." }),
        ...rows,
      ]),
      card("Add an agent", [
        el("p", { class: "muted", text: "Start from one of these, then change anything." }),
        el("div", { class: "row" }, TEMPLATES.map((template) =>
          el("button", { type: "button", text: template.name, onclick: () => editAgent(null, template) })
        )),
      ])
    );
  }

  function brainSelect(value, withDefault) {
    const select = el("select", { "aria-label": "Brain" }, [
      withDefault ? el("option", { value: "default", text: "Default brain (Settings)" }) : null,
      ...Object.entries(PROVIDERS)
        .filter(([id]) => id !== "pc" || state.settings.pc)
        .map(([id, provider]) => el("option", { value: id, text: provider.label })),
    ]);
    select.value = value || (withDefault ? "default" : "");
    return select;
  }

  function editAgent(agent, template) {
    const isNew = !agent;
    const draft = agent ? { ...agent } : { id: uid(), name: template.name === "Custom" ? "" : template.name, role: template.role, instructions: template.instructions, brain: "default", model: "", created_at: Date.now() };
    const name = el("input", { value: draft.name, "aria-label": "Name", placeholder: "e.g. Coach" });
    const instructions = el("textarea", { "aria-label": "Instructions", placeholder: "What this agent is for and how it should talk." });
    instructions.value = draft.instructions || "";
    const brain = brainSelect(draft.brain, true);
    const model = el("input", { value: draft.model || "", "aria-label": "Model", placeholder: "Leave empty for the brain's model" });
    openSheet(isNew ? "New agent" : `Edit ${draft.name}`, [
      el("label", {}, ["Name", name]),
      el("label", {}, ["Instructions", instructions]),
      el("label", {}, ["Brain", brain]),
      el("label", {}, ["Model (optional)", model]),
      el("div", { class: "row" }, [
        el("button", { class: "primary", type: "button", text: isNew ? "Create agent" : "Save", onclick: async () => {
          if (!name.value.trim()) return notify("Give it a name.");
          Object.assign(draft, { name: name.value.trim().slice(0, 40), instructions: instructions.value.trim(), brain: brain.value, model: model.value.trim() });
          if (isNew) state.agents.push(draft);
          else Object.assign(agent, draft);
          await save.agents();
          closeSheet();
          notify(isNew ? `${draft.name} joined your phone team.` : "Saved.");
          renderAgents();
          drawBar();
        } }),
        isNew || draft.id === "jarvis"
          ? null
          : el("button", { class: "danger", type: "button", text: "Delete", onclick: () => deleteAgent(agent) }),
      ]),
    ]);
  }

  async function deleteAgent(agent) {
    if (!confirm(`Delete ${agent.name} and its chat? Memories it saved stay in the phone's memory.`)) return;
    state.agents = state.agents.filter((item) => item.id !== agent.id);
    delete state.chats[agent.id];
    await Promise.all([save.agents(), store.remove(`chat:${agent.id}`)]);
    if (state.agentId === agent.id) {
      state.agentId = "jarvis";
      await store.set("agentId", "jarvis");
    }
    closeSheet();
    notify(`${agent.name} deleted.`);
    renderAgents();
  }

  // ----------------------------------------------------------------- memory

  function renderMemory() {
    const input = el("input", { placeholder: "Add a memory", "aria-label": "New memory" });
    const agentName = (id) => (state.agents.find((agent) => agent.id === id) || { name: "deleted agent" }).name;
    const pc = state.settings.pc;
    view.replaceChildren(
      card("On this phone", [
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [input]),
          el("button", { type: "button", text: "Add", onclick: async () => {
            if (!input.value.trim()) return;
            await remember(agentById("jarvis"), input.value);
            renderMemory();
          } }),
        ]),
        ...(state.memories.length
          ? state.memories.map((memory) =>
              el("div", { class: "item" }, [
                el("div", { class: "grow" }, [
                  el("strong", { text: memory.text }),
                  el("small", { text: `${agentName(memory.agent_id)} · ${ago(memory.created_at)}${pc ? (memory.synced ? " · on your PC" : " · not synced yet") : ""}` }),
                ]),
                el("button", { class: "danger", type: "button", text: "✕", "aria-label": "Forget this", onclick: async () => {
                  state.memories = state.memories.filter((item) => item.id !== memory.id);
                  await save.memories();
                  renderMemory();
                } }),
              ])
            )
          : [empty("Nothing remembered yet. Tell an agent something about you, or add it here.")]),
        pc ? el("p", { class: "muted", text: "Forgetting here doesn't remove what already went to your PC; forget it there too." }) : null,
      ]),
      card("From my PC", pc
        ? [
            el("div", { class: "row" }, [
              el("span", { class: "grow muted", text: `${state.pcMemories.length} memories from ${pc.pcName || "your PC"} · synced ${ago(pc.lastSync)}` }),
              el("button", { type: "button", text: "Sync now", onclick: async () => {
                await sync().catch(() => {});
                renderMemory();
              } }),
            ]),
            el("p", { class: "warn", text: pcMemoryAllowed(agentById("jarvis")) || state.settings.cloudSeesPc
              ? "Agents here can use these."
              : "Kept private: only agents thinking with your PC use these, when your PC's AI runs on the PC itself. Settings can change that." }),
            ...(state.pcMemories.length
              ? state.pcMemories.slice(0, 300).map((memory) =>
                  el("div", { class: "item" }, [
                    el("div", { class: "grow" }, [el("strong", { text: memory.text }), el("small", { text: memory.author || "PC" })]),
                  ])
                )
              : [empty("Nothing from the PC yet.")]),
          ]
        : [el("p", { class: "muted", text: "Pair your PC in Settings to share memories both ways." })])
    );
  }

  // --------------------------------------------------------------- settings

  function renderSettings() {
    const settings = state.settings;
    const brains = el("select", { "aria-label": "Default brain" }, [
      el("option", { value: "", text: "Choose…" }),
      ...Object.entries(PROVIDERS)
        .filter(([id]) => id !== "pc" || settings.pc)
        .map(([id, provider]) => el("option", { value: id, text: provider.label })),
    ]);
    brains.value = settings.brain || "";
    brains.addEventListener("change", async () => {
      settings.brain = brains.value;
      await save.settings();
      drawBar();
      notify(settings.brain ? `Agents now think with ${PROVIDERS[settings.brain].label}.` : "No brain picked.");
    });

    const providerCards = ["gemini", "groq", "openrouter", "custom"].map((id) => providerCard(id));
    view.replaceChildren(
      card("Brain", [
        el("label", {}, ["Your agents think with", brains]),
        el("p", { class: "muted", text: "Keys stay on this phone. Each agent can use a different brain (Agents, Edit)." }),
        el("button", { type: "button", text: "Test the brain", onclick: testBrain }),
      ]),
      ...providerCards,
      pcCard(),
      card("Voice", [
        el("label", { class: "check" }, [
          el("input", { type: "checkbox", checked: settings.speak, "aria-label": "Speak replies", onchange: async (event) => {
            settings.speak = event.target.checked;
            await save.settings();
          } }),
          "Speak replies out loud",
        ]),
        el("p", { class: "muted", text: "The 🎤 button and the keyboard's microphone both work for talking." }),
      ]),
      card("Backup", [
        el("p", { class: "muted", text: "Your agents, chats, and memories live only on this phone. Save a backup now and then (keys and the PC link are left out)." }),
        el("div", { class: "row" }, [
          el("button", { type: "button", text: "Save a backup", onclick: exportBackup }),
          importButton(),
        ]),
      ]),
      el("p", { class: "muted", text: `FCC Phone ${VERSION}` })
    );
  }

  function providerCard(id) {
    const provider = PROVIDERS[id];
    const settings = state.settings;
    const key = el("input", { type: "password", value: settings.keys[id] || "", "aria-label": `${provider.label} key`, autocomplete: "off", placeholder: "Paste your key" });
    const base = id === "custom" ? el("input", { value: settings.customBase || "", "aria-label": "Service address", placeholder: "https://…/v1" }) : null;
    const models = el("select", { "aria-label": `${provider.label} model` });
    const status = el("p", { class: "muted", role: "status" });
    const fillModels = (rows) => {
      models.replaceChildren(...(rows.length ? rows : [{ id: settings.models[id] || "" }]).filter((row) => row.id).map((row) => el("option", { value: row.id, text: row.id })));
      if (settings.models[id]) models.value = settings.models[id];
    };
    fillModels(state.modelLists[id] || []);
    models.addEventListener("change", async () => {
      settings.models[id] = models.value;
      await save.settings();
      drawBar();
    });
    const saveKey = async () => {
      settings.keys[id] = key.value.trim();
      if (base) settings.customBase = base.value.trim();
      if (!settings.brain && settings.keys[id]) settings.brain = id;
      await save.settings();
      status.textContent = "Loading models…";
      try {
        const rows = await listModels(id);
        fillModels(rows);
        status.textContent = rows.length ? `Saved. ${rows.length} models; using ${settings.models[id]}.` : "Saved.";
      } catch (error) {
        status.textContent = error.message;
      }
      drawBar();
      const brainSelectNode = view.querySelector('select[aria-label="Default brain"]');
      if (brainSelectNode) brainSelectNode.value = settings.brain;
    };
    return card(provider.label, [
      el("p", { class: "muted" }, [provider.note, " ", provider.keyUrl ? el("a", { href: provider.keyUrl, target: "_blank", rel: "noopener", text: "Get a free key" }) : null]),
      base ? el("label", {}, ["Address", base]) : null,
      el("label", {}, ["Key", key]),
      el("label", {}, ["Model", models]),
      el("button", { type: "button", text: "Save", "aria-label": `Save ${provider.label}`, onclick: saveKey }),
      status,
    ]);
  }

  async function testBrain() {
    const agent = agentById(state.agentId);
    notify("Asking…");
    try {
      const reply = await think(agent, "Answer in five words or fewer.", [{ role: "user", content: "Say hello." }], []);
      notify(`${PROVIDERS[brainOf(agent)].label}: ${reply.text || "(no words)"}`);
    } catch (error) {
      notify(error.message);
    }
  }

  function pcCard() {
    const pc = state.settings.pc;
    if (pc) {
      return card("My PC", [
        el("p", {}, [
          "Paired with ",
          el("strong", { text: pc.pcName || "your PC" }),
          ` at ${pc.address}. Its AI: ${pc.main || "Jarvis"} on ${pc.model || "?"} (${pc.private ? "runs on the PC" : "a server AI"}).`,
        ]),
        pc.broken ? el("p", { class: "warn", text: "The PC no longer knows this phone. Unpair, then pair again with a new code." }) : null,
        el("p", { class: "muted", text: `Last sync ${ago(pc.lastSync)}. Memories sync by themselves when you open the app and after new ones are saved.` }),
        el("label", { class: "check" }, [
          el("input", { type: "checkbox", checked: state.settings.cloudSeesPc, "aria-label": "Let cloud brains see PC memories", onchange: async (event) => {
            state.settings.cloudSeesPc = event.target.checked;
            await save.settings();
            notify(state.settings.cloudSeesPc ? "Cloud brains on this phone can now read your PC's memories." : "PC memories stay away from cloud brains.");
          } }),
          "Let cloud brains (Gemini, Groq, OpenRouter) read memories from my PC",
        ]),
        el("p", { class: "muted", text: "Off keeps your PC's memory bank away from cloud AIs, like on the PC." }),
        el("div", { class: "row" }, [
          el("button", { type: "button", text: "Sync now", onclick: () => sync().catch(() => {}) }),
          el("button", { class: "danger", type: "button", text: "Unpair", onclick: async () => {
            if (!confirm("Unpair from your PC? Memories stay on both.")) return;
            state.settings.pc = null;
            if (state.settings.brain === "pc") state.settings.brain = "";
            state.pcMemories = [];
            await Promise.all([save.settings(), save.pcMemories()]);
            renderSettings();
            drawBar();
          } }),
        ]),
      ]);
    }
    const address = el("input", { "aria-label": "PC address", placeholder: "https://your-pc.tail1234.ts.net", autocapitalize: "off", autocorrect: "off" });
    const code = el("input", { "aria-label": "Pairing code", placeholder: "ABCD-2345", autocapitalize: "characters", autocorrect: "off" });
    const status = el("p", { class: "muted", role: "status" });
    return card("Connect to my PC", [
      el("p", { class: "muted", text: "Optional. Pairing shares memories between this phone and FCC Studio on your PC, and lets agents here think with your PC's AI." }),
      el("ol", { class: "steps" }, [
        el("li", { text: "Install Tailscale (free) on your PC and this phone, signed in to the same account." }),
        el("li", { text: "On the PC, run  tailscale serve --bg 8082  once." }),
        el("li", { text: "In Studio on the PC: More, FCC Phone, Make a pairing code." }),
      ]),
      el("label", {}, ["PC address", address]),
      el("label", {}, ["Pairing code", code]),
      el("button", { class: "primary", type: "button", text: "Pair", onclick: async () => {
        status.textContent = "Pairing…";
        try {
          await pair(address.value, code.value);
          notify("Paired with your PC.");
          renderSettings();
          drawBar();
        } catch (error) {
          status.textContent = error.message;
        }
      } }),
      status,
    ]);
  }

  async function exportBackup() {
    const chats = {};
    for (const agent of state.agents) chats[agent.id] = await chatOf(agent.id);
    const { keys, pc, ...settings } = state.settings;
    const backup = { app: "FCC Phone", version: VERSION, saved_at: new Date().toISOString(), settings, agents: state.agents, memories: state.memories, chats };
    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
    const link = el("a", { href: URL.createObjectURL(blob), download: `fcc-phone-backup-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 5000);
  }

  function importButton() {
    const input = el("input", { type: "file", accept: "application/json,.json", hidden: true, "aria-label": "Backup file" });
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file) return;
      try {
        const backup = JSON.parse(await file.text());
        if (backup.app !== "FCC Phone") throw new Error("That isn't an FCC Phone backup.");
        if (!confirm("Replace this phone's agents, chats, and memories with the backup?")) return;
        state.agents = backup.agents || [jarvis()];
        state.memories = (backup.memories || []).map((memory) => ({ ...memory, synced: false }));
        Object.assign(state.settings, backup.settings || {}, { keys: state.settings.keys, pc: state.settings.pc });
        await Promise.all([save.agents(), save.memories(), save.settings()]);
        for (const [agentId, chat] of Object.entries(backup.chats || {})) {
          state.chats[agentId] = chat;
          await save.chat(agentId);
        }
        notify("Backup restored.");
        render();
      } catch (error) {
        notify(error.message);
      }
    });
    return el("span", {}, [input, el("button", { type: "button", text: "Restore a backup", onclick: () => input.click() })]);
  }

  // ------------------------------------------------------------------- start

  for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => go(tab.dataset.route));
  window.addEventListener("hashchange", render);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.settings && state.settings.pc) sync({ quiet: true }).catch(() => {});
  });

  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  load().then(() => {
    render();
    if (state.settings.pc) sync({ quiet: true }).catch(() => {});
  });

  // For the app's own tests: the maths reader and model picking, with no network.
  window.fccPhone = { calculate, bestModel, normalAddress, version: VERSION };
})();
