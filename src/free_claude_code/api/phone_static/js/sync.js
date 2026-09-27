// The optional link to FCC Studio on the PC: pairing, memory sync, and the
// PC's brain and web search for agents on the phone.
import { state, save, changed, feed } from "./state.js";
import { notify } from "./ui.js";

export class LinkError extends Error {}

async function request(url, options, timeout) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function errorText(response) {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body);
  } catch {
    return response.statusText || `status ${response.status}`;
  }
}

export async function pcCall(path, payload, method = "POST", timeout = 180000) {
  const pc = state.settings.pc;
  if (!pc) throw new LinkError("This phone isn't paired with a PC.");
  let response;
  try {
    response = await request(
      `${pc.address}${path}`,
      {
        method,
        headers: { Authorization: `Bearer ${pc.token}`, "Content-Type": "application/json" },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      },
      timeout
    );
  } catch {
    throw new LinkError("Couldn't reach your PC. Is it on, with Studio running and Tailscale connected?");
  }
  if (response.status === 401) {
    pc.broken = true;
    await save.settings();
    changed("pc");
    throw new LinkError("Your PC doesn't know this phone any more. Pair again in More, Settings.");
  }
  if (!response.ok) throw new LinkError(`Your PC: ${await errorText(response)}`);
  return response.json();
}

export function normalAddress(raw) {
  let address = String(raw || "").trim();
  if (!address) throw new LinkError("Type your PC's address.");
  if (!/^https?:\/\//i.test(address)) address = `https://${address}`;
  address = address.replace(/\/+$/, "").replace(/\/(studio|phone)(\/.*)?$/i, "");
  if (location.protocol === "https:" && address.startsWith("http:")) {
    throw new LinkError("Use your PC's https:// address (from Tailscale). An app on https can't reach plain http.");
  }
  return address;
}

function phoneName() {
  const ua = navigator.userAgent;
  return /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android phone" : "Phone";
}

export async function pair(rawAddress, code) {
  const address = normalAddress(rawAddress);
  let response;
  try {
    response = await request(
      `${address}/studio/api/phone/pair`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: code.trim(), name: phoneName() }) },
      20000
    );
  } catch {
    throw new LinkError("Couldn't reach that address. Check the PC is on, Studio is running, and Tailscale is connected on both.");
  }
  if (!response.ok) throw new LinkError(await errorText(response));
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
  changed("pc");
  feed("PC link", `Paired with ${body.pc}.`);
  await sync();
}

export async function unpair() {
  state.settings.pc = null;
  if (state.settings.brain === "pc") state.settings.brain = "";
  state.pcMemories = [];
  await Promise.all([save.settings(), save.pcMemories()]);
  changed("pc");
}

let syncing = null;
export function sync({ quiet = false } = {}) {
  if (!state.settings.pc) return Promise.resolve();
  if (syncing) return syncing;
  syncing = (async () => {
    const pending = state.memories.filter((memory) => !memory.synced).slice(0, 500);
    const name = (id) => (state.agents.find((agent) => agent.id === id) || { name: "Phone" }).name;
    try {
      const result = await pcCall("/studio/api/phone/sync", {
        memories: pending.map((memory) => ({ id: memory.id, agent: name(memory.agent_id), text: memory.text })),
      });
      const sent = new Set(pending.map((memory) => memory.id));
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
      changed("pc");
    }
  })();
  return syncing;
}

let timer = null;
export function syncSoon() {
  if (!state.settings.pc) return;
  clearTimeout(timer);
  timer = setTimeout(() => sync({ quiet: true }).catch(() => {}), 4000);
}

export async function pcSearch(query) {
  const result = await pcCall("/studio/api/phone/search", { query }, "POST", 60000);
  return result.results || [];
}
