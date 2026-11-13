// Optional: let an OpenAI-compatible model (LM Studio, or a cloud service with
// the player's own key) write the villagers' words. Rules still decide events.
import { aiPrompt, parseAiLines } from "./talk.js";

const KEY = "hearthbox.ai";

export class AiVoices {
  constructor() {
    this.cfg = Object.assign({ on: false, url: "http://localhost:1234/v1", model: "", key: "" }, JSON.parse(localStorage.getItem(KEY) || "{}"));
    this.busy = false;
    this.ok = 0;
    this.fail = 0;
    this.lastError = "";
  }
  saveCfg() {
    localStorage.setItem(KEY, JSON.stringify(this.cfg));
  }
  status() {
    if (!this.cfg.on) return "Off: villagers use their own words.";
    return `${this.ok} conversations written${this.fail ? `, ${this.fail} failed${this.lastError ? " (" + this.lastError + ")" : ""}` : ""}.`;
  }
  attach(sim) {
    sim.aiRequest = (c) => this.request(sim, c);
  }

  async call(system, user, maxTokens = 700) {
    const url = this.cfg.url.replace(/\/+$/, "") + "/chat/completions";
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 25000);
    try {
      const res = await fetch(url, {
        method: "POST",
        signal: ctl.signal,
        headers: { "Content-Type": "application/json", ...(this.cfg.key ? { Authorization: `Bearer ${this.cfg.key}` } : {}) },
        body: JSON.stringify({
          model: this.cfg.model || undefined,
          messages: [
            { role: "system", content: system },
            { role: "user", content: user },
          ],
          temperature: 0.9,
          max_tokens: maxTokens,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) || "";
    } finally {
      clearTimeout(timer);
    }
  }

  request(sim, c) {
    if (!this.cfg.on || !this.cfg.url || this.busy) return;
    this.busy = true;
    c.ai = "pending";
    c.aiT = Date.now();
    const { system, user, names } = aiPrompt(sim, c);
    this.call(system, user)
      .then((raw) => {
        const lines = parseAiLines(raw, names, c);
        if (lines.length >= 2) {
          c.aiLines = lines;
          c.ai = "done";
          this.ok++;
        } else {
          c.ai = "failed";
          this.fail++;
          this.lastError = "unreadable reply";
        }
      })
      .catch((e) => {
        c.ai = "failed";
        this.fail++;
        this.lastError = e.name === "AbortError" ? "timed out" : String(e.message || e).slice(0, 60);
      })
      .finally(() => {
        this.busy = false;
      });
  }

  async test() {
    try {
      const raw = await this.call("Reply with one short friendly sentence.", "Say hello to a villager.", 60);
      return raw ? `Works: “${raw.replace(/<think>[\s\S]*?<\/think>/g, "").trim().slice(0, 80)}”` : "Connected, but the reply was empty.";
    } catch (e) {
      const m = String(e.message || e);
      if (location.protocol === "https:" && this.cfg.url.startsWith("http:")) return `Blocked: this page is https, so the browser won't call an http address. Open the game from your PC, or use an https service. (${m})`;
      return `Failed: ${m}. Check the address, the model, and that the server allows browser requests (CORS).`;
    }
  }
}
