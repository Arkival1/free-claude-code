// Panels, touch controls and the villager inspector.
import { BUILDINGS, BUILD_MENU, IDEAS, JOBS, TRAITS, WORK_JOBS } from "./data.js";
import { currentStep, moodParts } from "./agent.js";
import { relLabel } from "./social.js";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const $ = (id) => document.getElementById(id);
const MEM_ICON = { obs: "👀", event: "👀", heard: "👂", talk: "💬", reflect: "✨", whisper: "💭", life: "❤️", plan: "📐", work: "🔧" };
const POWERS = [
  ["villager", "🧑", "Villager", "Join or found a village"],
  ["sheep", "🐑", "Sheep", "Food on legs"],
  ["wolf", "🐺", "Wolf", "Hunts at night"],
  ["fire", "🔥", "Fire", "Spreads through trees"],
  ["lightning", "⚡", "Lightning", "Strike a spot"],
  ["meteor", "☄️", "Meteor", "Crater and chaos"],
  ["rain", "🌧️", "Rain", "Puts out fires, grows crops"],
  ["bless", "✨", "Bless", "Heal and cheer"],
  ["plague", "🤒", "Plague", "Spreads by talking"],
  ["madness", "😡", "Madness", "Picks fights for a day"],
  ["smite", "💀", "Smite", "Strike one villager"],
  ["erase", "🧽", "Erase", "Remove a building or animal"],
];
const LANDS = [
  ["grass", "🌱", "Grass"],
  ["forest", "🌲", "Forest"],
  ["flowers", "🌸", "Flowers"],
  ["water", "💧", "Water"],
  ["deep", "🌊", "Deep sea"],
  ["sand", "🏖️", "Sand"],
  ["hill", "⛰️", "Hills"],
  ["mountain", "🏔️", "Mountain"],
  ["road", "🛤️", "Road"],
  ["clear", "🧹", "Clear plants"],
];

function moodEmoji(h) {
  return h > 75 ? "😄" : h > 55 ? "🙂" : h > 35 ? "😐" : h > 20 ? "😟" : "😢";
}
function hh(h) {
  const m = Math.round(h * 60) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export class UI {
  constructor(game) {
    this.g = game;
    this.tab = null;
    this.mode = null; // "tab" | "agent" | "building"
    this.sel = null;
    this.selBuilding = null;
    this.tool = null;
    this.ghost = null;
    this.brush = null;
    this.brushSize = 1;
    this.follow = false;
    this.talkSeg = "chat";
    this.talkOnlySel = false;
    this.query = "";
    this.vi = 0;
    this.whisperOpen = false;
    this.pointers = new Map();
    this.opts = Object.assign({ names: true, bubbles: "near" }, JSON.parse(localStorage.getItem("hearthbox.opts") || "{}"));
    this._last = 0;
    this._feedLast = null;
  }
  get sim() {
    return this.g.sim;
  }
  get village() {
    const vs = this.sim.villages.filter((v) => this.sim.hallOf(v));
    if (!vs.length) return this.sim.villages[0] || null;
    return vs[this.vi % vs.length];
  }

  init() {
    for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => this.openTab(b.dataset.tab));
    for (const b of document.querySelectorAll("#speed button"))
      b.addEventListener("click", () => {
        this.g.speed = +b.dataset.speed;
        for (const o of document.querySelectorAll("#speed button")) o.classList.toggle("on", o === b);
      });
    $("villageBtn").addEventListener("click", () => {
      this.vi++;
      const v = this.village;
      const h = v && this.sim.hallOf(v);
      if (h) this.g.r.center(h.x + 1.5, h.y + 1.5);
      this.renderTop();
    });
    $("toolDone").addEventListener("click", () => this.setTool(null));
    $("confirmNo").addEventListener("click", () => {
      this.ghost = null;
      $("confirm").hidden = true;
    });
    $("confirmYes").addEventListener("click", () => this.placeGhost());
    $("grab").addEventListener("click", () => $("sheet").classList.toggle("tall"));
    const body = $("sheetBody");
    body.addEventListener("click", (e) => this.onClick(e));
    body.addEventListener("change", (e) => this.onChange(e));
    body.addEventListener("input", (e) => {
      if (e.target.id === "search") {
        this.query = e.target.value.toLowerCase();
        this.renderPeopleList();
      }
    });
    this.bindCanvas();
    this.sim.onEvent = (e) => this.toast(e);
  }

  // ---------- sheet ----------
  openTab(tab) {
    if (this.tab === tab && this.mode === "tab") return this.closeSheet();
    this.tab = tab;
    this.mode = "tab";
    this.whisperOpen = false;
    for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === tab);
    $("sheet").hidden = false;
    $("sheet").classList.remove("tall");
    this.renderSheet(true);
  }
  closeSheet() {
    this.tab = null;
    this.mode = null;
    $("sheet").hidden = true;
    for (const b of document.querySelectorAll("#tabs button")) b.classList.remove("on");
  }
  selectAgent(id, center = true) {
    this.sel = id;
    this.selBuilding = null;
    this.mode = "agent";
    this.whisperOpen = false;
    for (const b of document.querySelectorAll("#tabs button")) b.classList.remove("on");
    $("sheet").hidden = false;
    const a = this.sim.agentById(id);
    if (a && center) this.g.r.center(a.x, a.y + 2);
    this.renderSheet(true);
    $("sheetBody").scrollTop = 0;
  }
  selectBuilding(id) {
    this.selBuilding = id;
    this.sel = null;
    this.mode = "building";
    for (const b of document.querySelectorAll("#tabs button")) b.classList.remove("on");
    $("sheet").hidden = false;
    this.renderSheet(true);
    $("sheetBody").scrollTop = 0;
  }

  // Called often by the main loop.
  tick(now) {
    if (this.follow && this.sel) {
      const a = this.sim.agentById(this.sel);
      if (a) {
        const r = this.g.r;
        r.cam.x += (a.x - r.cam.x) * 0.15;
        r.cam.y += (a.y + 1.5 - r.cam.y) * 0.15;
      } else this.follow = false;
    }
    if (now - this._last < 450) return;
    this._last = now;
    this.renderTop();
    if (this.mode && !$("sheet").hidden) this.renderSheet(false);
  }

  renderTop() {
    const s = this.sim;
    const v = this.village;
    const icon = s.weather.kind === "rain" ? "🌧️" : s.isNight() ? "🌙" : s.hour < 7 || s.hour > 18 ? "🌅" : "☀️";
    $("clock").textContent = `Day ${s.day} · ${s.clock()} ${icon}`;
    if (!v) return;
    $("vname").textContent = v.name;
    $("vflag").textContent = s.villages.length > 1 ? "🚩" : "🏡";
    $("villageBtn").style.boxShadow = `inset 0 0 0 2px ${v.color}`;
    const mem = s.members(v);
    const happy = mem.length ? Math.round(mem.reduce((x, a) => x + a.happy, 0) / mem.length) : 0;
    const k = v.stock;
    const low = k.food < mem.length * 2;
    $("res").innerHTML = `<span class="${low ? "low" : ""}">🍞 ${Math.floor(k.food)}</span><span>🪵 ${Math.floor(k.wood)}</span><span>🪨 ${Math.floor(k.stone)}</span><span>💰 ${Math.floor(k.gold)}</span><span>👥 ${mem.length}</span><span>${moodEmoji(happy)} ${happy}%</span>`;
  }

  renderSheet(force) {
    const focused = document.activeElement && $("sheetBody").contains(document.activeElement) && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if (focused && !force) return;
    const body = $("sheetBody");
    if (this.mode === "agent") {
      const a = this.sim.agentById(this.sel);
      if (!a) {
        const dead = this.sim.dead.find((d) => d.id === this.sel);
        body.innerHTML = `<h2>🪦 ${esc(dead ? dead.name : "Gone")}<button class="close" data-act="close">✕</button></h2><p class="muted">${dead ? `${esc(dead.name)} ${esc(dead.cause)} on day ${dead.day}, aged ${dead.age}.` : "This villager is no longer with us."}</p>`;
        return;
      }
      body.innerHTML = this.agentHTML(a);
      return;
    }
    if (this.mode === "building") {
      const b = this.sim.buildingById(this.selBuilding);
      body.innerHTML = b ? this.buildingHTML(b) : `<h2>Gone<button class="close" data-act="close">✕</button></h2><p class="muted">This building no longer stands.</p>`;
      return;
    }
    if (this.mode !== "tab") return;
    const dynamic = ["people", "talk", "stats"].includes(this.tab);
    if (!force && !dynamic) {
      if (this.tab === "build") this.updateBuildCosts();
      return;
    }
    switch (this.tab) {
      case "build":
        body.innerHTML = this.buildHTML();
        break;
      case "powers":
        body.innerHTML = this.powersHTML();
        break;
      case "land":
        body.innerHTML = this.landHTML();
        break;
      case "people":
        if (force) {
          body.innerHTML = `<h2>👥 People</h2><input id="search" type="search" placeholder="Search name, job or trait" value="${esc(this.query)}"><div id="plist"></div>`;
        }
        this.renderPeopleList();
        break;
      case "talk":
        if (!force && this.talkSeg === "chat" && this.sim.feed[this.sim.feed.length - 1] === this._feedLast) return;
        this._feedLast = this.sim.feed[this.sim.feed.length - 1];
        body.innerHTML = this.talkHTML();
        break;
      case "stats":
        body.innerHTML = this.statsHTML();
        this.drawCharts();
        break;
      case "menu":
        body.innerHTML = this.menuHTML();
        break;
    }
  }

  // ---------- tabs ----------
  buildHTML() {
    const v = this.village;
    const cards = BUILD_MENU.map((t) => {
      const d = BUILDINGS[t];
      const cost = Object.entries(d.cost)
        .map(([k, n]) => `${k === "wood" ? "🪵" : k === "stone" ? "🪨" : "💰"}${n}`)
        .join(" ");
      const on = this.tool && this.tool.kind === "build" && this.tool.type === t;
      return `<button class="card ${on ? "on" : ""}" data-act="tool-build" data-type="${t}" data-cost='${JSON.stringify(d.cost)}'><b>${d.icon}</b><span>${d.name}</span><em>${cost || "free"} · ${d.w}×${d.h}</em></button>`;
    }).join("");
    const s = this.sim.settings;
    return `<h2>🏗️ Build <span class="muted small">${v ? esc(v.name) : ""}</span></h2>
      <div class="grid">${cards}<button class="card ${this.tool && this.tool.type === "road" ? "on" : ""}" data-act="tool-land" data-l="road"><b>🛤️</b><span>Road</span><em>drag to pave</em></button></div>
      <p class="muted small">Tap a building, tap the map, then ✓. Builders fetch the materials and build it. Paths are faster on roads.</p>
      <label class="toggle"><span>⚡ Instant build (free, god mode)</span><input type="checkbox" data-set="instant" ${s.instant ? "checked" : ""}></label>
      <label class="toggle"><span>🌱 Villages grow on their own</span><input type="checkbox" data-set="autoGrow" ${s.autoGrow ? "checked" : ""}></label>`;
  }
  updateBuildCosts() {
    const v = this.village;
    if (!v || this.sim.settings.instant) return;
    for (const el of document.querySelectorAll("[data-cost]")) {
      const cost = JSON.parse(el.dataset.cost);
      el.classList.toggle("cant", Object.entries(cost).some(([k, n]) => v.stock[k] < n));
    }
  }
  powersHTML() {
    const cards = POWERS.map(([k, i, n, d]) => `<button class="card ${this.tool && this.tool.kind === "power" && this.tool.p === k ? "on" : ""}" data-act="tool-power" data-p="${k}"><b>${i}</b><span>${n}</span><em>${d}</em></button>`).join("");
    return `<h2>⚡ God powers</h2><div class="grid">${cards}</div><p class="muted small">Pick a power, then tap the map. Drop a villager far from any town to found a new village.</p>`;
  }
  landHTML() {
    const cards = LANDS.map(([k, i, n]) => `<button class="card ${this.tool && this.tool.kind === "land" && this.tool.l === k ? "on" : ""}" data-act="tool-land" data-l="${k}"><b>${i}</b><span>${n}</span></button>`).join("");
    const sizes = [1, 2, 3].map((n) => `<button class="${this.brushSize === n ? "on" : ""}" data-act="size" data-n="${n}">${["Small", "Medium", "Large"][n - 1]}</button>`).join("");
    return `<h2>🌍 Shape the land</h2><div class="seg">${sizes}</div><div class="grid">${cards}</div><p class="muted small">Drag one finger to paint. Use two fingers to move the map while painting.</p>`;
  }
  renderPeopleList() {
    const el = $("plist");
    if (!el) return;
    const q = this.query;
    const s = this.sim;
    const list = s.agents
      .filter((a) => !q || `${a.name} ${a.last} ${JOBS[a.job].label} ${a.traits.join(" ")}`.toLowerCase().includes(q))
      .sort((p, q2) => p.village - q2.village || q2.age - p.age);
    let html = "";
    let lastV = null;
    for (const a of list) {
      if (a.village !== lastV && s.villages.length > 1) {
        lastV = a.village;
        const v = s.villageById(a.village);
        html += `<h3>${esc(v ? v.name : "Wanderers")}</h3>`;
      }
      html += `<div class="person" data-act="sel-agent" data-id="${a.id}">
        <div class="avatar" style="background:${JOBS[a.job].color}33;border-color:${JOBS[a.job].color}">${JOBS[a.job].icon}</div>
        <div class="info"><div><b>${esc(a.name)} ${esc(a.last)}</b> <span class="muted small">${Math.floor(a.age)} · ${JOBS[a.job].label}${a.partner ? " · 💞" : ""}${a.sick ? " · 🤒" : ""}</span></div>
        <div class="muted small">${a.convo ? "💬 Talking" : esc(a.doing)}</div></div>
        <div title="Happiness">${moodEmoji(a.happy)}</div></div>`;
    }
    el.innerHTML = html || `<p class="muted">Nobody here. Use ⚡ Powers → Villager to add people.</p>`;
  }

  talkHTML() {
    const s = this.sim;
    const seg = ["chat", "news", "log"].map((k) => `<button class="${this.talkSeg === k ? "on" : ""}" data-act="seg" data-s="${k}">${{ chat: "💬 Chat", news: "📰 News", log: "📜 Log" }[k]}</button>`).join("");
    let html = `<div class="seg">${seg}</div>`;
    if (this.talkSeg === "chat") {
      const selA = this.sel && s.agentById(this.sel);
      if (selA) html += `<label class="toggle"><span>Only ${esc(selA.name)}</span><input type="checkbox" data-set="onlySel" ${this.talkOnlySel ? "checked" : ""}></label>`;
      let lines = s.feed;
      if (this.talkOnlySel && selA) lines = lines.filter((l) => l.s === selA.id || l.l === selA.id);
      // Group into conversations, newest first, so each reads like a transcript.
      const groups = new Map();
      for (const l of lines.slice(-160)) {
        if (!groups.has(l.c)) groups.set(l.c, []);
        groups.get(l.c).push(l);
      }
      const convs = [...groups.values()].sort((p, q) => q[q.length - 1].t - p[p.length - 1].t).slice(0, 18);
      const live = new Set(s.convos.map((c) => c.id));
      html += convs.length
        ? convs
            .map((g) => {
              const f = g[0];
              const names = [...new Map(g.map((l) => [l.s, l.sn])).entries()];
              const head = names.map(([id, n]) => `<span class="who" data-act="sel-agent" data-id="${id}">${esc(n)}</span>`).join(" & ");
              return `<div class="convo"><div class="small"><b>${head}</b> <span class="muted">· ${s.clock(f.t)}${live.has(f.c) ? " · 🟢 talking now" : ""}</span></div>${g.map((l) => `<div class="small"><b>${esc(l.sn)}:</b> ${esc(l.text)}</div>`).join("")}</div>`;
            })
            .join("")
        : `<p class="muted">Nobody has spoken yet. Give them a minute.</p>`;
    } else if (this.talkSeg === "news") {
      const n = s.agents.length || 1;
      const facts = [...s.facts.values()].filter((f) => f.kind !== "partydone" || true).slice(-40).reverse();
      html += `<p class="muted small">Things villagers know. News only spreads when they see it or someone tells them.</p>`;
      html += facts
        .map((f) => {
          const k = s.agents.filter((a) => a.knowsSet.has(f.id)).length;
          const pct = Math.round((k / n) * 100);
          return `<div class="fact" ${f.x != null ? `data-act="goto" data-x="${f.x}" data-y="${f.y}"` : ""}>${f.icon} ${esc(f.text.charAt(0).toUpperCase() + f.text.slice(1))}<div class="muted small">Day ${Math.floor(f.t / 1440) + 1} ${s.clock(f.t)} · known by ${k}/${n}</div><div class="bar"><i style="width:${pct}%;background:var(--accent)"></i></div></div>`;
        })
        .join("");
    } else {
      html += s.log
        .slice(-80)
        .reverse()
        .map((e) => `<div class="line" ${e.x != null ? `data-act="goto" data-x="${e.x}" data-y="${e.y}"` : ""}><time>D${Math.floor(e.t / 1440) + 1} ${s.clock(e.t)}</time>${e.icon} ${esc(e.text)}</div>`)
        .join("");
    }
    return html;
  }

  statsHTML() {
    const s = this.sim;
    const v = this.village;
    if (!v) return `<h2>📊 Stats</h2><p class="muted">No village.</p>`;
    const mem = s.members(v);
    const kids = mem.filter((a) => a.age < 14).length;
    const elders = mem.filter((a) => a.age >= 62).length;
    const happy = mem.length ? Math.round(mem.reduce((x, a) => x + a.happy, 0) / mem.length) : 0;
    const blds = s.buildings.filter((b) => b.village === v.id);
    const counts = {};
    for (const b of blds) if (b.done) counts[b.type] = (counts[b.type] || 0) + 1;
    const loved = mem.map((a) => [a, s.agents.reduce((x, o) => x + (o.rel[a.id] ? o.rel[a.id].aff : 0), 0)]).sort((p, q) => q[1] - p[1]);
    const social = mem.map((a) => [a, Object.values(a.rel).reduce((x, r) => x + r.n, 0)]).sort((p, q) => q[1] - p[1]);
    const row = (arr, fmt) => arr.slice(0, 3).map(([a, n]) => `<span class="tag" data-act="sel-agent" data-id="${a.id}">${esc(a.name)} ${fmt(n)}</span>`).join(" ");
    const jobs = {};
    for (const a of mem) jobs[a.job] = (jobs[a.job] || 0) + 1;
    return `<h2>📊 ${esc(v.name)}</h2>
      <div class="stat">
        <div><b>${mem.length}</b><span>people (${kids} kids, ${elders} elders)</span></div>
        <div><b>${moodEmoji(happy)} ${happy}%</b><span>happiness</span></div>
        <div><b>${s.stats.talks}</b><span>conversations</span></div>
        <div><b>${v.births}</b><span>births</span></div>
        <div><b>${v.deaths}</b><span>deaths</span></div>
        <div><b>${blds.filter((b) => b.done).length}</b><span>buildings (${blds.filter((b) => !b.done).length} planned)</span></div>
      </div>
      <h3>Population</h3><canvas class="chart" data-series="pop" data-color="#6fb6ff"></canvas>
      <h3>Food store</h3><canvas class="chart" data-series="food" data-color="#ffd65a"></canvas>
      <h3>Happiness</h3><canvas class="chart" data-series="happy" data-color="#67d38a" data-max="100"></canvas>
      <h3>Jobs</h3><div class="chips">${Object.entries(jobs).map(([j, n]) => `<span class="tag">${JOBS[j].icon} ${JOBS[j].label} ${n}</span>`).join("")}</div>
      <h3>Buildings</h3><div class="chips">${Object.entries(counts).map(([t, n]) => `<span class="tag">${BUILDINGS[t].icon} ${BUILDINGS[t].name} ${n}</span>`).join("")}</div>
      <h3>Most loved</h3><div class="chips">${row(loved, (n) => `❤️${Math.round(n)}`)}</div>
      <h3>Chattiest</h3><div class="chips">${row(social, (n) => `💬${n}`)}</div>
      <h3>Remembered</h3>${s.dead.slice(-6).reverse().map((d) => `<div class="small muted">🪦 ${esc(d.name)}, ${d.age}, ${esc(d.cause)} (day ${d.day})</div>`).join("") || `<div class="small muted">Nobody has died yet.</div>`}`;
  }
  drawCharts() {
    const v = this.village;
    if (!v) return;
    for (const c of document.querySelectorAll("canvas.chart")) {
      const key = c.dataset.series;
      const pts = v.hist.map((h) => h[key]);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      c.width = c.clientWidth * dpr;
      c.height = c.clientHeight * dpr;
      const ctx = c.getContext("2d");
      if (pts.length < 2) {
        ctx.fillStyle = "#9aa1b5";
        ctx.font = `${12 * dpr}px system-ui`;
        ctx.fillText("Collecting data…", 10 * dpr, 24 * dpr);
        continue;
      }
      const max = +c.dataset.max || Math.max(...pts, 1) * 1.1;
      const W = c.width;
      const H = c.height;
      ctx.strokeStyle = c.dataset.color;
      ctx.lineWidth = 2 * dpr;
      ctx.beginPath();
      pts.forEach((p, i) => {
        const x = (i / (pts.length - 1)) * (W - 8 * dpr) + 4 * dpr;
        const y = H - 4 * dpr - (p / max) * (H - 18 * dpr);
        if (i) ctx.lineTo(x, y);
        else ctx.moveTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = "#cfd3e0";
      ctx.font = `${11 * dpr}px system-ui`;
      ctx.fillText(String(pts[pts.length - 1]), W - 40 * dpr, 13 * dpr);
    }
  }

  menuHTML() {
    const s = this.sim;
    const ai = this.g.ai.cfg;
    return `<h2>☰ Menu</h2>
      <div class="btns"><button class="btn gold" data-act="save">💾 Save now</button><button class="btn" data-act="new">🌍 New world</button></div>
      <label class="field">Seed for a new world (blank = random)<input type="text" id="seed" inputmode="numeric" placeholder="${s.seed}"></label>
      <h3>Display</h3>
      <label class="toggle"><span>Show names when zoomed in</span><input type="checkbox" data-set="names" ${this.opts.names ? "checked" : ""}></label>
      <label class="toggle"><span>Speech bubbles at every zoom</span><input type="checkbox" data-set="bubblesAll" ${this.opts.bubbles === "all" ? "checked" : ""}></label>
      <h3>AI voices (optional)</h3>
      <p class="muted small">Villagers talk on their own. To let a language model write their words, give an OpenAI-compatible address (LM Studio on your PC, or a cloud service with your key). Game rules still decide what happens; the model only phrases it. Your key stays in this browser.</p>
      <label class="toggle"><span>Use AI voices</span><input type="checkbox" data-ai="on" ${ai.on ? "checked" : ""}></label>
      <label class="field">Address<input type="url" data-ai="url" value="${esc(ai.url)}" placeholder="http://localhost:1234/v1"></label>
      <label class="field">Model<input type="text" data-ai="model" value="${esc(ai.model)}" placeholder="qwen3-4b"></label>
      <label class="field">Key (if the service needs one)<input type="password" data-ai="key" value="${esc(ai.key)}" autocomplete="off"></label>
      <div class="btns"><button class="btn" data-act="ai-test">Test</button><span class="small muted" id="aiStatus">${esc(this.g.ai.status())}</span></div>
      <h3>How to play</h3>
      <div class="help small">
        <p>👀 Watch: villagers plan their day, work, eat, sleep and talk. Tap anyone to see their needs, plan, memories, friends and what they're saying.</p>
        <p>💭 Whisper: in a villager's card, plant a thought, have them throw a party, fall for someone or hold a grudge. Then watch the news travel person to person (Talk → News).</p>
        <p>🏗️ Build: place blueprints; builders fetch wood and stone. Villages also grow by themselves.</p>
        <p>⚡ Play god: fire, meteors, wolves, rain, blessings, plague. Drop a villager far away to found a rival village.</p>
        <p>The game saves itself every half minute in this browser.</p>
      </div>
      <p class="muted small">Hearthbox · day ${s.day} · seed ${s.seed}</p>`;
  }

  // ---------- inspector ----------
  agentHTML(a) {
    const s = this.sim;
    const v = s.villageById(a.village);
    const job = JOBS[a.job];
    const n = a.needs;
    const bar = (label, val, color) => `<span>${label}</span><div class="bar"><i style="width:${Math.max(0, Math.min(100, val))}%;background:${color}"></i></div><span class="muted">${Math.round(val)}</span>`;
    const col = (v2) => (v2 > 60 ? "#67d38a" : v2 > 30 ? "#ffd65a" : "#ff6b6b");
    const step = currentStep(s, a);
    const convo = a.convo && s.convos.find((c) => c.id === a.convo);
    const other = convo && s.agentById(convo.a === a.id ? convo.b : convo.a);
    const parts = moodParts(s, a).filter((p) => p[1]);
    const rels = Object.entries(a.rel)
      .map(([id, r]) => [+id, r])
      .filter(([id]) => s.agentById(id) || s.names.has(id))
      .sort((p, q) => Math.abs(q[1].aff) - Math.abs(p[1].aff))
      .slice(0, 10);
    const relHTML = rels
      .map(([id, r]) => {
        const o = s.agentById(id);
        const label = o ? relLabel(a, o) : "Passed away";
        const w = Math.abs(r.aff) / 2;
        const bar2 = r.aff >= 0 ? `left:50%;width:${w}%;background:#67d38a` : `left:${50 - w}%;width:${w}%;background:#ff6b6b`;
        return `<div class="rel" ${o ? `data-act="sel-agent" data-id="${id}"` : ""}><span>${o ? "" : "† "}${esc(s.nameOf(id))}</span><div class="relbar"><i style="${bar2}"></i></div><span class="small muted">${label}</span></div>`;
      })
      .join("");
    const mems = a.mem
      .slice(-30)
      .reverse()
      .map((m) => `<div class="mem ${m.kind}"><time>D${Math.floor(m.t / 1440) + 1} ${s.clock(m.t)}</time><span>${MEM_ICON[m.kind] || "•"} ${esc(m.text)}</span></div>`)
      .join("");
    const talk = s.feed
      .filter((l) => l.s === a.id || l.l === a.id)
      .slice(-14)
      .reverse()
      .map((l) => `<div class="line"><time>${s.clock(l.t)}</time><span class="who" data-act="sel-agent" data-id="${l.s}">${esc(l.sn)}</span> <span class="muted">→ ${esc(l.ln)}</span><br>${esc(l.text)}</div>`)
      .join("");
    const plan = a.plan.map((p) => `<div class="${p === step ? "now" : ""}"><time>${hh(p.h0)}–${hh(p.h1)}</time><span>${esc(p.text)}</span></div>`).join("");
    const family = [a.partner, ...a.parents, ...a.children].filter((id) => id != null).map((id) => `<span class="tag" ${s.agentById(id) ? `data-act="sel-agent" data-id="${id}"` : ""}>${esc(s.nameOf(id))} · ${id === a.partner ? "partner" : a.parents.includes(id) ? "parent" : "child"}${s.agentById(id) ? "" : " †"}</span>`).join("");
    const jobSel = `<select data-set="job">${[...WORK_JOBS, "child", "elder"].map((j) => `<option value="${j}" ${a.job === j ? "selected" : ""}>${JOBS[j].icon} ${JOBS[j].label}</option>`).join("")}<option value="auto">🔄 Let the village decide</option></select>`;
    const skills = Object.entries(a.skills)
      .sort((p, q) => q[1] - p[1])
      .slice(0, 4)
      .map(([k, val]) => `<span class="tag">${k === "woodcut" ? "woodcutting" : k} ${val.toFixed(1)}</span>`)
      .join("");
    const home = a.home != null && s.buildingById(a.home);
    const doing = a.convo ? `Talking with ${other ? other.name : "someone"}` : a.action && a.action.phase === "walk" ? `On the way: ${a.doing}` : a.doing;
    const whisper = this.whisperOpen
      ? `<div class="convo"><b>💭 Whisper to ${esc(a.name)}</b>
        <label class="field">Plant a thought<textarea id="thought" rows="2" placeholder="e.g. the river is full of gold"></textarea></label>
        <div class="chips">${IDEAS.map((t) => `<span class="tag" data-act="idea" data-text="${esc(t)}">${esc(t)}</span>`).join("")}</div>
        <div class="btns"><button class="btn gold" data-act="whisper" data-k="thought">Whisper it</button></div>
        <div class="btns"><button class="btn" data-act="whisper" data-k="party">🎉 Throw a party</button><button class="btn" data-act="whisper" data-k="crush">💘 Fall for…</button><button class="btn" data-act="whisper" data-k="grudge">😤 Grudge against…</button></div>
        <div class="btns"><select id="wbuild">${BUILD_MENU.map((t) => `<option value="${t}">${BUILDINGS[t].icon} ${BUILDINGS[t].name}</option>`).join("")}</select><button class="btn" data-act="whisper" data-k="build">🏗️ Want to build it</button></div></div>`
      : "";
    return `<h2><span class="avatar" style="background:${job.color}33;border-color:${v ? v.color : job.color}">${job.icon}</span>
        <span>${esc(a.name)} ${esc(a.last)}<div class="muted small">${Math.floor(a.age)} yrs · ${job.label} · ${esc(v ? v.name : "no village")}${home ? " · lives in " + esc(home.name) : " · homeless"}</div></span>
        <button class="close" data-act="close">✕</button></h2>
      <div class="btns"><button class="btn ${this.follow ? "gold" : ""}" data-act="follow">📍 ${this.follow ? "Following" : "Follow"}</button><button class="btn ${this.whisperOpen ? "gold" : ""}" data-act="whisper-open">💭 Whisper</button><button class="btn" data-act="god" data-p="bless">✨</button><button class="btn" data-act="god" data-p="plague">🤒</button><button class="btn" data-act="god" data-p="madness">😡</button><button class="btn red" data-act="god" data-p="smite">💀</button></div>
      ${whisper}
      <div><b>${moodEmoji(a.happy)} ${esc(doing)}</b>${a.sick ? " · 🤒 sick" : ""}${a.carry ? ` · carrying ${a.carry.n} ${a.carry.type}` : ""}</div>
      ${a.thought ? `<div class="thought">“${esc(a.thought)}”</div>` : ""}
      ${convo ? `<div class="convo"><b>💬 With ${esc(other ? other.name : "?")}</b>${convo.lines.slice(-6).map((l) => `<div class="small"><b>${esc(l.sn)}:</b> ${esc(l.text)}</div>`).join("")}${convo.ai === "pending" ? `<div class="small muted">✍️ the AI is writing…</div>` : ""}</div>` : ""}
      <h3>Stats</h3>
      <div class="bars">${bar("Health", a.health, col(a.health))}${bar("Happiness", a.happy, col(a.happy))}${bar("Food", n.hunger, col(n.hunger))}${bar("Energy", n.energy, col(n.energy))}${bar("Social", n.social, col(n.social))}${bar("Fun", n.fun, col(n.fun))}</div>
      <div class="chips" style="margin-top:6px">${parts.map(([k, val]) => `<span class="tag ${val > 0 ? "pos" : "neg"}">${esc(k)} ${val > 0 ? "+" : ""}${val}</span>`).join("")}</div>
      <h3>Personality & work</h3>
      <div class="chips">${a.traits.map((t) => `<span class="tag">${TRAITS[t].icon} ${TRAITS[t].label}</span>`).join("")}${skills}</div>
      <label class="field">Job ${a.jobLocked ? "(set by you)" : "(chosen by the village)"}${jobSel}</label>
      ${family ? `<h3>Family</h3><div class="chips">${family}</div>` : ""}
      <h3>Today's plan</h3><div class="plan">${plan}</div>
      <h3>Relationships</h3>${relHTML || `<p class="muted small">Hasn't met anyone yet.</p>`}
      <h3>Recent talk</h3>${talk || `<p class="muted small">Hasn't talked to anyone yet.</p>`}
      <h3>Memories</h3>${mems}`;
  }

  buildingHTML(b) {
    const s = this.sim;
    const d = BUILDINGS[b.type];
    const v = s.villageById(b.village);
    const residents = s.residents(b);
    const workers = s.agents.filter((a) => a.action && a.action.data && a.action.data.bid === b.id);
    const pct = d.work ? Math.round((b.progress / d.work) * 100) : 100;
    const cost = Object.entries(d.cost).map(([k, n]) => `${n} ${k}`).join(", ");
    const ppl = (list) => list.map((a) => `<span class="tag" data-act="sel-agent" data-id="${a.id}">${esc(a.name)}</span>`).join(" ");
    return `<h2><span class="avatar">${d.icon}</span><span>${esc(b.name.charAt(0).toUpperCase() + b.name.slice(1))}<div class="muted small">${d.name} · ${esc(v ? v.name : "")}</div></span><button class="close" data-act="close">✕</button></h2>
      <p class="muted small">${esc(d.desc)}</p>
      ${b.done ? "" : `<p>${b.funded ? `🔨 Under construction: ${pct}%` : `📐 Blueprint, waiting for ${esc(cost || "builders")}`}</p><div class="bar"><i style="width:${pct}%;background:#67d38a"></i></div>`}
      ${b.hp < 100 ? `<p>🔥 Damage: ${Math.round(100 - b.hp)}%</p>` : ""}
      ${b.type === "farm" && b.done ? `<p>🌾 Crops ${Math.round(b.growth)}% grown</p>` : ""}
      ${residents.length ? `<h3>Lives here</h3><div class="chips">${ppl(residents)}</div>` : ""}
      ${workers.length ? `<h3>Here now</h3><div class="chips">${ppl(workers)}</div>` : ""}
      <div class="btns">${b.done ? "" : `<button class="btn gold" data-act="finish-bld">⚡ Finish now</button>`}${b.type !== "townhall" ? `<button class="btn red" data-act="remove-bld">🧽 Remove</button>` : ""}</div>`;
  }

  // ---------- events ----------
  onClick(e) {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    const s = this.sim;
    switch (act) {
      case "close":
        this.sel = null;
        this.selBuilding = null;
        this.follow = false;
        this.closeSheet();
        break;
      case "tool-build":
        this.setTool({ kind: "build", type: el.dataset.type });
        this.renderSheet(true);
        break;
      case "tool-power":
        if (el.dataset.p === "rain") {
          s.power("rain", 0, 0);
          return;
        }
        this.setTool({ kind: "power", p: el.dataset.p });
        this.renderSheet(true);
        break;
      case "tool-land":
        this.setTool({ kind: "land", l: el.dataset.l });
        this.renderSheet(true);
        break;
      case "size":
        this.brushSize = +el.dataset.n;
        this.renderSheet(true);
        break;
      case "sel-agent":
        this.selectAgent(+el.dataset.id);
        break;
      case "goto":
        this.g.r.center(+el.dataset.x, +el.dataset.y);
        break;
      case "seg":
        this.talkSeg = el.dataset.s;
        this.renderSheet(true);
        break;
      case "follow":
        this.follow = !this.follow;
        this.renderSheet(true);
        break;
      case "whisper-open":
        this.whisperOpen = !this.whisperOpen;
        this.renderSheet(true);
        break;
      case "idea":
        $("thought").value = el.dataset.text;
        break;
      case "whisper":
        this.doWhisper(el.dataset.k);
        break;
      case "god": {
        const a = s.agentById(this.sel);
        if (!a) return;
        if (el.dataset.p === "smite" && !confirm(`Strike down ${a.name}?`)) return;
        const r = s.power(el.dataset.p, a.x, a.y);
        if (r.msg) this.toast({ icon: "⚡", text: r.msg });
        this.renderSheet(true);
        break;
      }
      case "finish-bld": {
        const b = s.buildingById(this.selBuilding);
        if (b && !b.done) s.finishBuilding(b);
        this.renderSheet(true);
        break;
      }
      case "remove-bld": {
        const b = s.buildingById(this.selBuilding);
        if (b) s.removeBuilding(b, b.done ? "torn down" : "");
        this.closeSheet();
        break;
      }
      case "save":
        this.g.save();
        this.toast({ icon: "💾", text: "Saved." });
        break;
      case "new": {
        if (!confirm("Start a new world? This one will be replaced.")) return;
        const seed = parseInt(($("seed") || {}).value, 10);
        this.g.newWorld(Number.isFinite(seed) ? seed : undefined);
        break;
      }
      case "ai-test":
        $("aiStatus").textContent = "Testing…";
        this.g.ai.test().then((m) => ($("aiStatus").textContent = m));
        break;
    }
  }

  onChange(e) {
    const el = e.target;
    const s = this.sim;
    if (el.dataset.set) {
      const k = el.dataset.set;
      if (k === "instant" || k === "autoGrow") s.settings[k] = el.checked;
      else if (k === "names") this.opts.names = el.checked;
      else if (k === "bubblesAll") this.opts.bubbles = el.checked ? "all" : "near";
      else if (k === "onlySel") {
        this.talkOnlySel = el.checked;
      } else if (k === "job") {
        const a = s.agentById(this.sel);
        if (a) {
          if (el.value === "auto") a.jobLocked = false;
          else {
            a.job = el.value;
            a.jobLocked = true;
            a.workAt = null;
          }
          a.planDay = -1;
          a.action = null;
        }
      }
      localStorage.setItem("hearthbox.opts", JSON.stringify(this.opts));
      el.blur();
      this.renderSheet(true);
    }
    if (el.dataset.ai) {
      const cfg = this.g.ai.cfg;
      cfg[el.dataset.ai] = el.type === "checkbox" ? el.checked : el.value.trim();
      this.g.ai.saveCfg();
    }
  }

  doWhisper(kind) {
    const a = this.sim.agentById(this.sel);
    if (!a) return;
    if (kind === "crush" || kind === "grudge") {
      this.setTool({ kind: "pick", for: kind, who: a.id });
      return;
    }
    const data = kind === "thought" ? { text: $("thought").value } : kind === "build" ? { type: $("wbuild").value } : {};
    const r = this.sim.whisper(a, kind, data);
    this.toast({ icon: "💭", text: r.msg || (r.ok ? "Whispered." : "That didn't take.") });
    if (r.ok) this.whisperOpen = false;
    this.renderSheet(true);
  }

  setTool(t) {
    this.tool = t;
    this.ghost = null;
    this.brush = null;
    $("confirm").hidden = true;
    $("toolbar").hidden = !t;
    if (!t) return;
    let text = "";
    if (t.kind === "build") text = `Tap where the ${BUILDINGS[t.type].name.toLowerCase()} goes`;
    else if (t.kind === "power") text = `${POWERS.find((p) => p[0] === t.p)[1]} Tap the map`;
    else if (t.kind === "land") text = `${LANDS.find((p) => p[0] === t.l)[1]} Drag to paint`;
    else if (t.kind === "pick") text = `Tap who ${this.sim.nameOf(t.who)} ${t.for === "crush" ? "falls for" : "resents"}`;
    $("toolText").textContent = text;
    if (t.kind === "build" || t.kind === "power" || t.kind === "land") {
      // Make room to see the map.
      $("sheet").hidden = true;
      for (const b of document.querySelectorAll("#tabs button")) b.classList.remove("on");
      this.mode = null;
      this.tab = null;
    }
  }

  placeGhost() {
    const g = this.ghost;
    const s = this.sim;
    if (!g) return;
    const v = s.nearestVillage(g.x + 1, g.y + 1, 32);
    if (!v) {
      this.toast({ icon: "🚫", text: "Too far from any village. Drop a villager there first to found one." });
      return;
    }
    const b = s.placeBuilding(g.type, g.x, g.y, v, { byPlayer: true });
    if (!b) {
      this.toast({ icon: "🚫", text: "Can't build there." });
      return;
    }
    if (s.settings.instant) s.finishBuilding(b);
    else {
      const cost = Object.entries(BUILDINGS[g.type].cost).map(([k, n]) => `${n} ${k}`).join(", ");
      this.toast({ icon: "📐", text: `Blueprint placed in ${v.name}.${cost ? " Builders need " + cost + "." : ""}` });
    }
    this.ghost = null;
    $("confirm").hidden = true;
  }

  toast(e) {
    const box = $("toasts");
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = `${e.icon || ""} ${e.text}`;
    if (e.x != null) t.addEventListener("click", () => this.g.r.center(e.x, e.y));
    box.prepend(t);
    while (box.children.length > 2) box.lastChild.remove();
    setTimeout(() => {
      t.classList.add("out");
      setTimeout(() => t.remove(), 450);
    }, 3200);
  }

  // ---------- map input ----------
  bindCanvas() {
    const c = this.g.r.c;
    const pos = (e) => {
      const r = c.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    let pinch = null;
    let moved = false;
    let wasMulti = false;
    let lastPaint = null;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      const p = pos(e);
      this.pointers.set(e.pointerId, { ...p, sx: p.x, sy: p.y });
      if (this.pointers.size === 1) {
        moved = false;
        wasMulti = false;
        lastPaint = null;
        if (this.tool && this.tool.kind === "land") this.paintAt(p, (lastPaint = {}));
      } else if (this.pointers.size === 2) {
        wasMulti = true;
        const [a, b] = [...this.pointers.values()];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
      }
    });
    c.addEventListener("pointermove", (e) => {
      const p = this.pointers.get(e.pointerId);
      const np = pos(e);
      if (!p) {
        if (this.tool && this.tool.kind === "land") {
          const w = this.g.r.toWorld(np.x, np.y);
          this.brush = { x: w.x, y: w.y, r: this.brushSize - 0.3 };
        }
        return;
      }
      const dx = np.x - p.x;
      const dy = np.y - p.y;
      p.x = np.x;
      p.y = np.y;
      if (this.pointers.size >= 2 && pinch) {
        const [a, b] = [...this.pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        this.g.r.pan(mx - pinch.mx, my - pinch.my);
        if (pinch.d > 0) this.g.r.zoomAt(d / pinch.d, mx, my);
        pinch = { d, mx, my };
        this.follow = false;
        return;
      }
      if (this.tool && this.tool.kind === "land" && !wasMulti) {
        this.paintAt(np, lastPaint || (lastPaint = {}));
        return;
      }
      if (!moved && Math.hypot(np.x - p.sx, np.y - p.sy) > 7) moved = true;
      if (moved) {
        this.g.r.pan(dx, dy);
        this.follow = false;
      }
    });
    const up = (e) => {
      const p = this.pointers.get(e.pointerId);
      this.pointers.delete(e.pointerId);
      if (this.pointers.size < 2) pinch = null;
      if (p && this.pointers.size === 0 && !moved && !wasMulti && !(this.tool && this.tool.kind === "land")) this.tap(p.x, p.y);
    };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", (e) => {
      this.pointers.delete(e.pointerId);
      pinch = null;
    });
    c.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const p = pos(e);
        this.g.r.zoomAt(e.deltaY < 0 ? 1.12 : 0.89, p.x, p.y);
      },
      { passive: false },
    );
  }

  paintAt(p, last) {
    const w = this.g.r.toWorld(p.x, p.y);
    const tx = Math.floor(w.x);
    const ty = Math.floor(w.y);
    this.brush = { x: w.x, y: w.y, r: this.brushSize - 0.3 };
    if (last.x === tx && last.y === ty) return;
    last.x = tx;
    last.y = ty;
    this.sim.power("land:" + this.tool.l, w.x, w.y, { size: this.brushSize });
  }

  tap(sx, sy) {
    const s = this.sim;
    const r = this.g.r;
    const w = r.toWorld(sx, sy);
    const t = this.tool;
    if (t && t.kind === "build") {
      const d = BUILDINGS[t.type];
      const gx = Math.floor(w.x - d.w / 2 + 0.5);
      const gy = Math.floor(w.y - d.h / 2 + 0.5);
      const ok = s.canPlace(t.type, gx, gy) && !!s.nearestVillage(gx, gy, 32);
      this.ghost = { type: t.type, x: gx, y: gy, ok };
      $("confirm").hidden = false;
      $("confirmText").textContent = ok ? `${d.icon} ${d.name} here?` : "Can't build here";
      $("confirmYes").hidden = !ok;
      return;
    }
    if (t && t.kind === "power") {
      const res = s.power(t.p, w.x, w.y);
      if (res.msg) this.toast({ icon: POWERS.find((p) => p[0] === t.p)[1], text: res.msg });
      if (res.agent) this.selectAgent(res.agent.id, false);
      return;
    }
    const radius = Math.max(0.7, (24 * r.dpr) / r.cam.z);
    if (t && t.kind === "pick") {
      const b = s.nearestAgent(w.x, w.y - 0.4, radius);
      const a = s.agentById(t.who);
      if (b && a && b !== a) {
        const res = s.whisper(a, t.for, { target: b.id });
        this.toast({ icon: "💭", text: res.msg || "Done." });
        this.setTool(null);
        this.selectAgent(a.id, false);
      }
      return;
    }
    const a = s.nearestAgent(w.x, w.y - 0.4, radius);
    if (a) return this.selectAgent(a.id, false);
    const b = s.buildingAt(Math.floor(w.x), Math.floor(w.y)) || s.buildingAt(Math.floor(w.x), Math.floor(w.y + 0.6));
    if (b) return this.selectBuilding(b.id);
    if (this.mode === "agent" || this.mode === "building") {
      this.sel = null;
      this.selBuilding = null;
      this.follow = false;
      this.closeSheet();
    }
  }
}
