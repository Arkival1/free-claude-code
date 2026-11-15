// The whole game state and the rules that tie villagers, buildings and the world together.
// No DOM in here, so it runs in node for tests.
import { BUILDINGS, FARM_NAMES, JOBS, PARK_NAMES, TAVERN_NAMES, TRAITS, VILLAGE_COLORS, villageName } from "./data.js";
import { chance, clamp, dist, makeRng, pick, randInt, shuffle } from "./rng.js";
import { F, T, World } from "./world.js";
import { learn, remember, rel, setTraitTable } from "./social.js";
import { makeAgent, updateAgent, makePlan, reflect, dailyAgent } from "./agent.js";
import { makeAnimal, updateAnimal } from "./animals.js";
import { endConversation, maybeStartConversations, updateConversations } from "./talk.js";

setTraitTable(TRAITS);

export const DAY = 1440;
const DIRS = ["east", "south-east", "south", "south-west", "west", "north-west", "north", "north-east"];

export class Sim {
  constructor(seed) {
    this.seed = seed >>> 0;
    this.rand = makeRng(this.seed);
    this.time = 6 * 60;
    this.nextId = 1;
    this.world = new World(96, 96);
    this.villages = [];
    this.agents = [];
    this.animals = [];
    this.buildings = [];
    this.convos = [];
    this.facts = new Map();
    this.log = [];
    this.feed = [];
    this.graves = [];
    this.dead = [];
    this.fires = [];
    this.parties = [];
    this.weather = { kind: "clear", until: 0 };
    this.settings = { autoGrow: true, instant: false };
    this.stats = { births: 0, deaths: 0, talks: 0, built: 0 };
    this.fx = [];
    this.onEvent = null;
    this.aiRequest = null;
    this.amap = new Map();
    this.bmap = new Map();
    this.names = new Map();
    this._lastHour = Math.floor(this.time / 60);
    this._talkAcc = 0;
  }

  static create(seed = Math.floor(Math.random() * 1e9)) {
    const s = new Sim(seed);
    s.world.generate(s.seed);
    s.setupStart();
    return s;
  }

  id() {
    return this.nextId++;
  }
  get day() {
    return Math.floor(this.time / DAY) + 1;
  }
  get hour() {
    return (this.time % DAY) / 60;
  }
  clock(t = this.time) {
    const m = Math.floor(t % DAY);
    return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  }
  when(t) {
    return `day ${Math.floor(t / DAY) + 1} at ${this.clock(t)}`;
  }
  light() {
    const h = this.hour;
    if (h >= 7 && h < 18) return 1;
    if (h >= 18 && h < 21) return 1 - (h - 18) / 3;
    if (h >= 5 && h < 7) return (h - 5) / 2;
    return 0;
  }
  isNight() {
    const h = this.hour;
    return h >= 21 || h < 5.5;
  }

  agentById(id) {
    return this.amap.get(id);
  }
  buildingById(id) {
    return this.bmap.get(id);
  }
  nameOf(id) {
    return this.names.get(id) || "someone";
  }
  villageById(id) {
    return this.villages.find((v) => v.id === id);
  }
  hallOf(v) {
    return this.bmap.get(v.hall);
  }
  members(v) {
    return this.agents.filter((a) => a.village === v.id);
  }

  // ---------- setup ----------
  setupStart() {
    const W = this.world;
    let best = null;
    let bs = -1;
    for (let k = 0; k < 400; k++) {
      const x = randInt(this.rand, 20, W.w - 20);
      const y = randInt(this.rand, 20, W.h - 20);
      if (!W.buildable(x, y)) continue;
      const s = W.openness(x, y, 7) - dist(x, y, W.w / 2, W.h / 2) * 0.8;
      if (s > bs) {
        bs = s;
        best = { x, y };
      }
    }
    if (!best) best = { x: 48, y: 48 };
    // Clear a little room for the first buildings.
    for (let y = best.y - 4; y <= best.y + 4; y++)
      for (let x = best.x - 4; x <= best.x + 4; x++)
        if (W.inb(x, y) && W.flora[W.idx(x, y)] === F.TREE && this.rand() < 0.85) W.setFlora(W.idx(x, y), F.NONE);
    const v = this.foundVillage(best.x, best.y);
    v.stock = { food: 90, wood: 40, stone: 20, gold: 0 };
    const hall = this.hallOf(v);
    const hx = hall.x + 1;
    const hy = hall.y + 1;
    const spawn = (opts) => {
      const p = W.nearest(hx + randInt(this.rand, -3, 3), hy + randInt(this.rand, -3, 3), 6, (i, x, y) => W.walkable(x, y));
      return this.addAgent(makeAgent(this, { x: p.x + 0.5, y: p.y + 0.5, village: v.id, ...opts }));
    };
    // Three couples (two with a child) and three singles.
    for (let c = 0; c < 3; c++) {
      const a = spawn({ age: randInt(this.rand, 22, 40) });
      const b = spawn({ age: randInt(this.rand, 22, 40), last: a.last });
      this.makeCouple(a, b, true);
      if (c < 2) {
        const kid = spawn({ age: randInt(this.rand, 4, 11), last: a.last, parents: [a.id, b.id] });
        a.children.push(kid.id);
        b.children.push(kid.id);
        rel(kid, a.id).aff = 70;
        rel(kid, b.id).aff = 70;
        rel(a, kid.id).aff = 80;
        rel(b, kid.id).aff = 80;
      }
    }
    for (let i = 0; i < 3; i++) spawn({ age: randInt(this.rand, 18, 60) });
    // Everyone has met.
    for (const a of this.agents)
      for (const b of this.agents) if (a !== b && !a.rel[b.id]) rel(a, b.id).aff = randInt(this.rand, -10, 25);
    for (const type of ["house", "house", "house", "farm", "well"]) {
      const spot = this.findSpot(v, type);
      if (spot) this.placeBuilding(type, spot.x, spot.y, v, { done: true });
    }
    this.assignHomes(v);
    this.assignJobs(v);
    for (const a of this.agents) makePlan(this, a);
    this.event(`${v.name} was founded by ${this.agents.length} settlers.`, "🏡", { x: hx, y: hy, toast: true });
  }

  foundVillage(cx, cy) {
    const spot = this.world.nearest(cx, cy, 8, (i, x, y) => this.canPlace("townhall", x - 1, y - 1, 1));
    if (!spot) return null;
    let name = villageName(this.rand);
    for (let k = 0; k < 10 && this.villages.some((o) => o.name === name); k++) name = villageName(this.rand);
    const v = {
      id: this.id(),
      name,
      color: VILLAGE_COLORS[this.villages.length % VILLAGE_COLORS.length],
      stock: { food: 30, wood: 15, stone: 5, gold: 0 },
      hall: null,
      hist: [],
      births: 0,
      deaths: 0,
      founded: this.time,
    };
    this.villages.push(v);
    const hall = this.placeBuilding("townhall", spot.x - 1, spot.y - 1, v, { done: true });
    v.hall = hall.id;
    return v;
  }

  nearestVillage(x, y, maxD = Infinity) {
    let best = null;
    let bd = maxD;
    for (const v of this.villages) {
      const h = this.hallOf(v);
      if (!h) continue;
      const d = dist(x, y, h.x + 1.5, h.y + 1.5);
      if (d < bd) {
        bd = d;
        best = v;
      }
    }
    return best;
  }

  addAgent(a) {
    this.agents.push(a);
    this.amap.set(a.id, a);
    this.names.set(a.id, a.name);
    return a;
  }

  makeCouple(a, b, quiet = false) {
    a.partner = b.id;
    b.partner = a.id;
    rel(a, b.id).aff = Math.max(rel(a, b.id).aff, 70);
    rel(b, a.id).aff = Math.max(rel(b, a.id).aff, 70);
    if (b.home == null && a.home != null) b.home = a.home;
    else if (a.home == null && b.home != null) a.home = b.home;
    if (!quiet) {
      remember(this, a, `${b.name} and I are together now.`, 9, "life");
      remember(this, b, `${a.name} and I are together now.`, 9, "life");
      this.addFact("couple", `${a.name} and ${b.name} are a couple now`, { x: a.x, y: a.y, radius: 5, about: [a.id, b.id], imp: 7, icon: "💞", toast: true });
    }
  }

  // ---------- buildings ----------
  canPlace(type, x, y, margin = 0) {
    const d = BUILDINGS[type];
    const W = this.world;
    for (let yy = y - margin; yy < y + d.h + margin; yy++) {
      for (let xx = x - margin; xx < x + d.w + margin; xx++) {
        const inside = xx >= x && yy >= y && xx < x + d.w && yy < y + d.h;
        if (!W.inb(xx, yy)) {
          if (inside) return false;
          continue;
        }
        const i = W.idx(xx, yy);
        if (W.bld[i] !== -1) return false;
        if (inside && (!W.buildable(xx, yy) || W.fire[i] > 0)) return false;
      }
    }
    return true;
  }

  nameBuilding(type, v) {
    const n = this.buildings.filter((b) => b.type === type && b.village === v.id).length;
    switch (type) {
      case "townhall":
        return `${v.name} Hall`;
      case "house":
        return `House ${n + 1}`;
      case "farm":
        return `${pick(this.rand, FARM_NAMES)} Farm`;
      case "tavern":
        return pick(this.rand, TAVERN_NAMES);
      case "park":
        return pick(this.rand, PARK_NAMES);
      case "well":
        return n ? `${v.name} Well ${n + 1}` : `the ${v.name} Well`;
      case "statue":
        return "the Statue";
      default:
        return `${v.name} ${BUILDINGS[type].name}${n ? " " + (n + 1) : ""}`;
    }
  }

  placeBuilding(type, x, y, v, { done = false, byPlayer = false } = {}) {
    if (!this.canPlace(type, x, y)) return null;
    const d = BUILDINGS[type];
    const b = {
      id: this.id(),
      type,
      x,
      y,
      w: d.w,
      h: d.h,
      village: v.id,
      name: this.nameBuilding(type, v),
      done: false,
      progress: 0,
      funded: false,
      hp: 100,
      growth: 0,
      byPlayer,
      born: this.time,
    };
    const W = this.world;
    for (let yy = y; yy < y + d.h; yy++)
      for (let xx = x; xx < x + d.w; xx++) {
        const i = W.idx(xx, yy);
        W.bld[i] = b.id;
        if (W.flora[i] === F.TREE) v.stock.wood += 1;
        if (W.flora[i] !== F.NONE) W.setFlora(i, F.NONE);
      }
    this.buildings.push(b);
    this.bmap.set(b.id, b);
    if (done) this.finishBuilding(b, true);
    return b;
  }

  finishBuilding(b, quiet = false) {
    b.done = true;
    b.funded = true;
    b.progress = BUILDINGS[b.type].work;
    b.hp = 100;
    if (b.type === "statue") {
      const v = this.villageById(b.village);
      let best = null;
      let bv = -Infinity;
      for (const a of this.members(v || { id: -1 })) {
        let s = 0;
        for (const o of this.agents) if (o.rel[a.id]) s += o.rel[a.id].aff;
        if (s > bv) {
          bv = s;
          best = a;
        }
      }
      if (best) {
        b.name = `the Statue of ${best.name}`;
        remember(this, best, "They built a statue of me! I'm so proud.", 9, "life");
        best.buffs.push({ kind: "proud", until: this.time + 2 * DAY });
      }
    }
    if (!quiet) {
      this.stats.built++;
      const label = b.type === "house" ? "a new house" : b.name;
      this.addFact("built", `${label} was finished`, { x: b.x + b.w / 2, y: b.y + b.h / 2, radius: 9, imp: 4, icon: BUILDINGS[b.type].icon, data: { bid: b.id }, toast: true });
    }
  }

  removeBuilding(b, cause = "") {
    const W = this.world;
    for (let yy = b.y; yy < b.y + b.h; yy++)
      for (let xx = b.x; xx < b.x + b.w; xx++) {
        const i = W.idx(xx, yy);
        if (W.bld[i] === b.id) W.bld[i] = -1;
        W.dirty.add(i);
      }
    this.buildings = this.buildings.filter((o) => o !== b);
    this.bmap.delete(b.id);
    for (const a of this.agents) {
      if (a.home === b.id) a.home = null;
      if (a.workAt === b.id) a.workAt = null;
    }
    if (b.type === "townhall") {
      const v = this.villageById(b.village);
      if (v) {
        // The village moves its store to another of its buildings, or scatters.
        const other = this.buildings.find((o) => o.village === v.id && o.done);
        if (other) {
          v.hall = other.id;
        } else {
          v.hall = null;
        }
      }
    }
    if (cause && b.done) {
      this.addFact("destroyed", `${b.type === "house" ? "a house" : b.name} was ${cause}`, { x: b.x + b.w / 2, y: b.y + b.h / 2, radius: 12, imp: 8, icon: "💥", toast: true });
    }
  }

  buildingAt(x, y) {
    if (!this.world.inb(x, y)) return null;
    const id = this.world.bld[this.world.idx(x, y)];
    return id >= 0 ? this.bmap.get(id) : null;
  }

  residents(b) {
    return this.agents.filter((a) => a.home === b.id);
  }

  findSpot(v, type) {
    const hall = this.hallOf(v);
    if (!hall) return null;
    const d = BUILDINGS[type];
    const hx = hall.x + 1;
    const hy = hall.y + 1;
    const W = this.world;
    for (let r = 3; r <= 24; r++) {
      const ring = [];
      for (let y = hy - r; y <= hy + r; y++)
        for (let x = hx - r; x <= hx + r; x++) if (Math.max(Math.abs(x - hx), Math.abs(y - hy)) === r) ring.push({ x: x - Math.floor(d.w / 2), y: y - Math.floor(d.h / 2) });
      shuffle(this.rand, ring);
      let best = null;
      let bs = Infinity;
      let found = 0;
      for (const p of ring) {
        if (!this.canPlace(type, p.x, p.y, 1)) continue;
        let trees = 0;
        for (let yy = p.y; yy < p.y + d.h; yy++) for (let xx = p.x; xx < p.x + d.w; xx++) if (W.flora[W.idx(xx, yy)] === F.TREE) trees++;
        if (trees < bs) {
          bs = trees;
          best = p;
        }
        if (++found > 6) break;
      }
      if (best) return best;
    }
    return null;
  }

  // ---------- facts, events, places ----------
  addFact(kind, text, o = {}) {
    const f = {
      id: this.id(),
      kind,
      text,
      t: this.time,
      imp: o.imp ?? 5,
      about: o.about || [],
      data: o.data || {},
      x: o.x,
      y: o.y,
      icon: o.icon || "📰",
      knowers: 0,
    };
    this.facts.set(f.id, f);
    if (this.facts.size > 220) {
      const keep = new Set(this.parties.filter((p) => !p.over).map((p) => p.fact));
      for (const id of this.facts.keys()) {
        if (keep.has(id)) continue;
        this.facts.delete(id);
        break;
      }
    }
    const radius = o.radius ?? 8;
    for (const a of this.agents) {
      if (f.about.includes(a.id)) learn(this, a, f, "quiet");
      else if (o.x != null && dist(a.x, a.y, o.x, o.y) <= radius) learn(this, a, f, "saw");
    }
    this.event(cap(text) + ".", f.icon, { x: o.x, y: o.y, toast: o.toast, kind });
    return f;
  }

  event(text, icon = "•", o = {}) {
    const e = { t: this.time, text, icon, x: o.x, y: o.y, kind: o.kind || "info" };
    this.log.push(e);
    if (this.log.length > 300) this.log.shift();
    if (o.toast && this.onEvent) this.onEvent(e);
    return e;
  }

  describePlace(x, y) {
    let best = null;
    let bd = 5;
    for (const b of this.buildings) {
      if (!b.done) continue;
      const d = dist(x, y, b.x + b.w / 2, b.y + b.h / 2);
      if (d < bd) {
        bd = d;
        best = b;
      }
    }
    if (best) return best.type === "house" ? `${best.name.replace(/^House \d+$/, "a house")}` : best.name;
    const v = this.nearestVillage(x, y);
    const W = this.world;
    const t = W.tile(Math.floor(x), Math.floor(y));
    const fl = W.flora[W.idx(clamp(Math.floor(x), 0, W.w - 1), clamp(Math.floor(y), 0, W.h - 1))];
    const feature = fl === F.TREE ? "woods" : t === T.HILL || t === T.MOUNTAIN ? "hills" : t === T.SAND || t === T.WATER ? "shore" : t === T.ASH ? "burnt fields" : "fields";
    if (!v) return `the far ${feature}`;
    const h = this.hallOf(v);
    const dx = x - (h.x + 1.5);
    const dy = y - (h.y + 1.5);
    if (Math.hypot(dx, dy) < 6) return `the middle of ${v.name}`;
    const dir = DIRS[(Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) + 8) % 8];
    return `the ${feature} ${dir} of ${v.name}`;
  }

  // ---------- fire ----------
  flammable(i) {
    const W = this.world;
    if (W.fire[i] > 0) return false;
    const f = W.flora[i];
    if (f === F.TREE || f === F.YOUNG || f === F.SAPLING || f === F.BUSH || f === F.BUSH_EMPTY) return true;
    const bid = W.bld[i];
    if (bid >= 0) {
      const b = this.bmap.get(bid);
      return b && b.type !== "well" && b.type !== "statue";
    }
    return W.t[i] === T.GRASS;
  }
  ignite(i, force = false) {
    const W = this.world;
    if (W.fire[i] > 0 || (!force && !this.flammable(i))) return false;
    if (W.t[i] === T.WATER || W.t[i] === T.DEEP) return false;
    W.fire[i] = 55 + this.rand() * 20;
    this.fires.push(i);
    return true;
  }
  updateFire(dt) {
    const W = this.world;
    const rain = this.weather.kind === "rain";
    const before = this.fires;
    this.fires = [];
    const spread = [];
    for (const i of before) {
      if (W.fire[i] <= 0) continue;
      W.fire[i] -= dt * (rain ? 7 : 1);
      if (W.fire[i] <= 0) {
        W.fire[i] = 0;
        this.burnOut(i);
        continue;
      }
      this.fires.push(i);
      const x = i % W.w;
      const y = (i / W.w) | 0;
      if (!rain) {
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          if (!W.inb(x + dx, y + dy)) continue;
          const j = W.idx(x + dx, y + dy);
          if (!this.flammable(j)) continue;
          const f = W.flora[j];
          const p = f === F.TREE || f === F.YOUNG ? 0.03 : f ? 0.022 : W.bld[j] >= 0 ? 0.02 : 0.0028;
          if (this.rand() < p * dt) spread.push(j);
        }
      }
      const bid = W.bld[i];
      if (bid >= 0) {
        const b = this.bmap.get(bid);
        if (b) {
          b.hp -= dt * 0.35;
          if (b.hp <= 0) {
            b.hp = 0;
            this.removeBuilding(b, "destroyed by fire");
          }
        }
      }
      for (const a of this.agents) if (Math.floor(a.x) === x && Math.floor(a.y) === y) a.health -= dt * 0.8;
    }
    for (const j of spread) this.ignite(j);
  }
  burnOut(i) {
    const W = this.world;
    const f = W.flora[i];
    if (f !== F.NONE && f !== F.FLOWERS) W.setFlora(i, f === F.TREE ? F.STUMP : F.NONE);
    if (W.t[i] === T.GRASS && W.bld[i] < 0) W.setT(i % W.w, (i / W.w) | 0, T.ASH);
    if (f === F.FLOWERS) W.setFlora(i, F.NONE);
  }

  // ---------- life and death ----------
  killAgent(a, cause) {
    if (!a.alive) return;
    a.alive = false;
    a.cause = cause;
    if (a.convo) endConversation(this, this.convos.find((c) => c.id === a.convo));
    this.agents = this.agents.filter((o) => o !== a);
    this.amap.delete(a.id);
    this.dead.push({ id: a.id, name: `${a.name} ${a.last}`, age: Math.floor(a.age), cause, day: this.day, job: a.job });
    if (this.dead.length > 200) this.dead.shift();
    this.graves.push({ x: a.x, y: a.y, name: a.name, day: this.day });
    if (this.graves.length > 60) this.graves.shift();
    this.stats.deaths++;
    const v = this.villageById(a.village);
    if (v) v.deaths++;
    const p = this.agentById(a.partner);
    if (p) {
      p.partner = null;
      p.buffs.push({ kind: "grief", until: this.time + 3 * DAY });
      remember(this, p, `My partner ${a.name} is gone. I miss them terribly.`, 10, "life");
    }
    for (const o of this.agents) {
      if (o.crush === a.id) o.crush = null;
      if (o.rel[a.id] && o.rel[a.id].aff > 40 && o !== p) o.buffs.push({ kind: "sad", until: this.time + DAY });
    }
    const f = this.addFact("death", `${a.name} ${cause}`, { x: a.x, y: a.y, radius: 8, imp: 9, icon: "🪦", toast: true, data: { who: a.id } });
    // Family hears at once.
    for (const id of [a.partner, ...a.parents, ...a.children]) {
      const o = this.agentById(id);
      if (o) learn(this, o, f, "news");
    }
  }

  // ---------- villages ----------
  assignHomes(v) {
    const houses = this.buildings.filter((b) => b.village === v.id && b.type === "house" && b.done);
    const count = new Map(houses.map((h) => [h.id, 0]));
    const mem = this.members(v);
    for (const a of mem) {
      if (a.home != null && !count.has(a.home)) a.home = null;
      if (a.home != null) count.set(a.home, count.get(a.home) + 1);
    }
    // Children live with a parent; partners live together.
    for (const a of mem) {
      if (a.home != null) continue;
      const fam = [a.partner, ...a.parents].map((id) => this.agentById(id)).find((o) => o && o.home != null && count.get(o.home) < BUILDINGS.house.cap);
      let h = fam ? this.bmap.get(fam.home) : null;
      if (!h) h = houses.find((x) => count.get(x.id) === 0) || houses.find((x) => count.get(x.id) < BUILDINGS.house.cap && a.age >= 16);
      if (!h) continue;
      a.home = h.id;
      count.set(h.id, count.get(h.id) + 1);
      if (/^House \d+$/.test(h.name)) h.name = `the ${a.last} house`;
      remember(this, a, `I moved into ${h.name}.`, 6, "life");
    }
  }

  assignJobs(v) {
    const mem = this.members(v);
    const done = (t) => this.buildings.filter((b) => b.village === v.id && b.type === t && b.done);
    for (const a of mem) {
      if (a.jobLocked) continue;
      if (a.age < 14) a.job = "child";
      else if (a.age >= 62) a.job = "elder";
      else if (a.job === "child" || a.job === "elder") a.job = "idle";
    }
    const workers = mem.filter((a) => a.age >= 14 && a.age < 62);
    const pop = mem.length;
    const farmCap = done("farm").length * 3;
    const pending = this.buildings.filter((b) => b.village === v.id && !b.done).length;
    const place = (job) => {
      const p = JOBS[job].place;
      return p ? done(p).length * (BUILDINGS[p].jobs || 1) : 0;
    };
    const hungry = v.stock.food < pop * 4;
    const farmNeed = Math.min(farmCap, Math.max(1, Math.ceil(pop * 0.26)));
    // Fill jobs in priority order until we run out of workers.
    const plan = [
      ["farmer", Math.min(farmNeed, Math.max(1, Math.ceil(pop * (hungry ? 0.3 : 0.15))))],
      ["builder", pending ? Math.min(1 + pending, Math.max(1, Math.floor(workers.length / 3))) : 0],
      ["healer", place("healer")],
      ["woodcutter", 1],
      ["miner", 1],
      ["farmer", farmNeed],
      ["keeper", place("keeper")],
      ["teacher", place("teacher")],
      ["guard", place("guard")],
      ["merchant", place("merchant")],
      ["priest", place("priest")],
      ["woodcutter", v.stock.wood < 60 ? 2 : 1],
      ["miner", v.stock.stone < 40 ? 2 : 1],
    ];
    const target = {};
    let left = workers.length;
    for (const a of workers)
      if (a.jobLocked) {
        target[a.job] = (target[a.job] || 0) + 1;
        left--;
      }
    for (const [job, n] of plan) {
      const add = Math.max(0, Math.min(left, n - (target[job] || 0)));
      target[job] = (target[job] || 0) + add;
      left -= add;
    }
    while (left > 0) {
      const job = (target.farmer || 0) < farmCap ? "farmer" : v.stock.wood <= v.stock.stone * 1.5 ? "woodcutter" : "miner";
      target[job] = (target[job] || 0) + 1;
      left--;
    }
    const have = {};
    for (const a of workers) have[a.job] = (have[a.job] || 0) + 1;
    const free = [];
    for (const a of workers) {
      if (a.jobLocked) continue;
      if ((have[a.job] || 0) > (target[a.job] || 0)) {
        have[a.job]--;
        free.push(a);
      }
    }
    const skillOf = (a, job) => a.skills[JOBS[job].skill] || 0;
    for (const [job] of plan) {
      while ((have[job] || 0) < (target[job] || 0) && free.length) {
        free.sort((p, q) => skillOf(q, job) - skillOf(p, job));
        const a = free.shift();
        if (a.job !== job) {
          a.job = job;
          a.workAt = null;
          a.planDay = -1;
          remember(this, a, `I started working as ${aOrAn(JOBS[job].label.toLowerCase())}.`, 5, "life");
        }
        have[job] = (have[job] || 0) + 1;
      }
    }
    for (const a of free) {
      a.job = "idle";
      a.workAt = null;
    }
  }

  // A village whose plan can't be paid for in three days gives it up, so it can grow again.
  dropStuckPlans(v) {
    for (const b of [...this.buildings]) {
      if (b.village !== v.id || b.done || b.funded || b.byPlayer) continue;
      if (this.time - b.born < 3 * DAY) continue;
      this.removeBuilding(b);
      v.skip = { ...(v.skip || {}), [b.type]: this.time + 3 * DAY };
      this.event(`${v.name} gave up on its ${BUILDINGS[b.type].name.toLowerCase()} plan: not enough materials.`, "📐");
    }
  }

  // A village that lost every building puts up a new hall where its people are.
  rebuildHall(v) {
    const mem = this.members(v);
    // Only when nothing finished is left: otherwise the store moved to another building.
    if (!mem.length || this.buildings.some((b) => b.village === v.id && b.done)) return false;
    const cx = Math.floor(mem.reduce((s, a) => s + a.x, 0) / mem.length);
    const cy = Math.floor(mem.reduce((s, a) => s + a.y, 0) / mem.length);
    const spot = this.world.nearest(cx, cy, 14, (i, x, y) => this.canPlace("townhall", x - 1, y - 1, 1));
    if (!spot) return false;
    const hall = this.placeBuilding("townhall", spot.x - 1, spot.y - 1, v, { done: true });
    if (!hall) return false;
    v.hall = hall.id;
    this.addFact("built", `the people of ${v.name} raised a new town hall`, { x: spot.x, y: spot.y, radius: 10, imp: 7, icon: "🏛️", toast: true });
    return true;
  }

  autoBuild(v) {
    if (!this.settings.autoGrow) return;
    if (this.buildings.some((b) => b.village === v.id && !b.done && !b.byPlayer)) return;
    const mem = this.members(v);
    const pop = mem.length;
    if (!pop) return;
    const count = (t) => this.buildings.filter((b) => b.village === v.id && b.type === t).length;
    const cap = count("house") * BUILDINGS.house.cap;
    const kids = mem.filter((a) => a.age < 14).length;
    const sick = mem.filter((a) => a.sick).length;
    let type = null;
    if (cap < pop + 2) type = "house";
    else if (count("farm") * 9 < pop) type = "farm";
    else if (!count("well") && pop >= 5) type = "well";
    else if (!count("tavern") && pop >= 9) type = "tavern";
    else if (!count("school") && kids >= 3) type = "school";
    else if (!count("clinic") && (pop >= 14 || (sick && pop >= 8))) type = "clinic";
    else if (!count("market") && pop >= 12) type = "market";
    else if (!count("park") && pop >= 13) type = "park";
    else if (!count("tower") && (pop >= 17 || this.animals.some((n) => n.kind === "wolf"))) type = "tower";
    else if (!count("temple") && pop >= 20 && v.stock.gold >= 10) type = "temple";
    else if (!count("statue") && pop >= 22 && v.stock.gold >= 5) type = "statue";
    if (!type || (v.skip && v.skip[type] > this.time)) return;
    const spot = this.findSpot(v, type);
    if (!spot) return;
    const b = this.placeBuilding(type, spot.x, spot.y, v);
    if (!b) return;
    const adults = mem.filter((a) => a.age >= 16);
    const proposer = adults.find((a) => a.traits.includes("ambitious")) || pick(this.rand, adults.length ? adults : mem);
    remember(this, proposer, `I suggested we build ${aOrAn(BUILDINGS[type].name)}.`, 6, "plan");
    this.addFact("plan", `${proposer.name} wants the village to build ${aOrAn(BUILDINGS[type].name.toLowerCase())} near ${this.describePlace(b.x + b.w / 2, b.y + b.h / 2)}`, {
      x: proposer.x,
      y: proposer.y,
      radius: 4,
      about: [proposer.id],
      imp: 5,
      icon: "📐",
      data: { bid: b.id },
    });
  }

  births(v) {
    const mem = this.members(v);
    const food = v.stock.food;
    for (const a of mem) {
      const p = this.agentById(a.partner);
      if (!p || a.id > p.id || a.home == null) continue;
      if (a.age < 18 || p.age < 18 || a.age > 46 || p.age > 46) continue;
      if (food < mem.length * 2 || (a.happy + p.happy) / 2 < 40) continue;
      if (this.time - (a.lastBaby ?? -1e9) < 3 * 1440) continue;
      const kids = a.children.filter((id) => this.agentById(id)).length;
      if (!chance(this.rand, kids >= 3 ? 0.04 : 0.22)) continue;
      const home = this.bmap.get(a.home);
      const baby = this.addAgent(makeAgent(this, { x: home ? home.x + 1 : a.x, y: home ? home.y + 1.5 : a.y, village: v.id, age: 0, last: a.last, parents: [a.id, p.id] }));
      baby.home = a.home;
      a.children.push(baby.id);
      p.children.push(baby.id);
      a.lastBaby = p.lastBaby = this.time;
      for (const par of [a, p]) {
        rel(par, baby.id).aff = 90;
        rel(baby, par.id).aff = 80;
        remember(this, par, `Our baby ${baby.name} was born today!`, 10, "life");
        par.buffs.push({ kind: "joy", until: this.time + DAY });
      }
      this.stats.births++;
      v.births++;
      this.addFact("birth", `${a.name} and ${p.name} had a baby called ${baby.name}`, { x: baby.x, y: baby.y, radius: 6, about: [a.id, p.id], imp: 8, icon: "👶", toast: true });
      makePlan(this, baby);
    }
  }

  // ---------- time ----------
  step(dt) {
    this.time += dt;
    for (const a of [...this.agents]) updateAgent(this, a, dt);
    for (const n of [...this.animals]) updateAnimal(this, n, dt);
    updateConversations(this, dt);
    this._talkAcc += dt;
    if (this._talkAcc >= 3) {
      this._talkAcc = 0;
      maybeStartConversations(this);
    }
    if (this.fires.length) this.updateFire(dt);
    this.updateParties();
    const h = Math.floor(this.time / 60);
    if (h !== this._lastHour) {
      this._lastHour = h;
      this.hourly(h % 24);
    }
  }

  advance(minutes) {
    while (minutes > 0) {
      const d = Math.min(1, minutes);
      this.step(d);
      minutes -= d;
    }
  }

  hourly(hour) {
    this.regrow();
    if (this.weather.kind === "rain" && this.time >= this.weather.until) {
      this.weather = { kind: "clear", until: 0 };
      this.event("The rain stopped.", "🌤️");
    } else if (this.weather.kind === "clear" && chance(this.rand, 0.02)) {
      this.weather = { kind: "rain", until: this.time + randInt(this.rand, 2, 5) * 60 };
      this.event("It started to rain.", "🌧️");
    }
    for (const v of this.villages) {
      if (!this.hallOf(v) && !this.rebuildHall(v)) continue;
      this.dropStuckPlans(v);
      this.assignHomes(v);
      if (hour % 2 === 0) this.assignJobs(v);
      this.autoBuild(v);
      if (hour === 7) this.births(v);
      if (hour % 2 === 0) this.sample(v);
    }
    if (hour === 21) for (const a of this.agents) reflect(this, a);
    if (hour === 5) for (const a of [...this.agents]) dailyAgent(this, a);
    // Sheep slowly multiply; the wild sometimes sends a wolf.
    const sheep = this.animals.filter((n) => n.kind === "sheep");
    if (sheep.length >= 2 && sheep.length < 40 && chance(this.rand, 0.06)) {
      const s = pick(this.rand, sheep);
      this.animals.push(makeAnimal(this, "sheep", s.x, s.y));
    }
    for (const a of this.agents) a.buffs = a.buffs.filter((b) => b.until > this.time);
  }

  sample(v) {
    const mem = this.members(v);
    const happy = mem.length ? mem.reduce((s, a) => s + a.happy, 0) / mem.length : 0;
    v.hist.push({ t: this.time, pop: mem.length, food: Math.round(v.stock.food), wood: Math.round(v.stock.wood), stone: Math.round(v.stock.stone), gold: Math.round(v.stock.gold), happy: Math.round(happy) });
    if (v.hist.length > 240) v.hist.shift();
  }

  regrow() {
    const W = this.world;
    const n = W.w * W.h;
    for (let k = 0; k < 600; k++) {
      const i = Math.floor(this.rand() * n);
      if (W.bld[i] >= 0 || W.fire[i] > 0) continue;
      const t = W.t[i];
      const f = W.flora[i];
      if (t === T.ASH) {
        if (this.rand() < 0.12) W.setT(i % W.w, (i / W.w) | 0, T.GRASS);
        continue;
      }
      if (f === F.SAPLING && this.rand() < 0.35) W.setFlora(i, F.YOUNG);
      else if (f === F.YOUNG && this.rand() < 0.3) W.setFlora(i, F.TREE);
      else if (f === F.STUMP && this.rand() < 0.12) W.setFlora(i, F.SAPLING);
      else if (f === F.BUSH_EMPTY && this.rand() < 0.3) W.setFlora(i, F.BUSH);
      else if (f === F.NONE && t === T.GRASS && !W.road[i]) {
        const x = i % W.w;
        const y = (i / W.w) | 0;
        let trees = 0;
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) if (W.inb(x + dx, y + dy) && W.flora[W.idx(x + dx, y + dy)] === F.TREE) trees++;
        if (trees && this.rand() < 0.06 * trees) W.setFlora(i, F.SAPLING);
        else if (this.rand() < 0.004) W.setFlora(i, this.rand() < 0.5 ? F.BUSH : F.FLOWERS);
      }
    }
  }

  updateParties() {
    for (const p of this.parties) {
      const f = this.facts.get(p.fact);
      if (p.over) continue;
      if (!f) {
        p.over = true;
        for (const a of this.agents) if (a.goingTo) a.goingTo = a.goingTo.filter((id) => id !== p.fact);
        const host = this.agentById(p.host);
        if (host && host.goal && host.goal.fact === p.fact) host.goal = null;
        continue;
      }
      if (!p.started && this.time >= p.at) {
        p.started = true;
        const going = this.agents.filter((a) => a.goingTo && a.goingTo.includes(p.fact)).length;
        this.event(`${this.nameOf(p.host)}'s party at ${p.place} has started. ${going} people said they'd come.`, "🎉", { x: p.x, y: p.y, toast: true });
      }
      if (this.time >= p.end) {
        p.over = true;
        const guests = p.guests.filter((id) => id !== p.host && this.agentById(id));
        const host = this.agentById(p.host);
        for (const id of guests) {
          const g = this.agentById(id);
          remember(this, g, `I went to ${this.nameOf(p.host)}'s party at ${p.place}. ${guests.length > 5 ? "So many people came!" : "It was cosy."}`, 7, "life");
          g.buffs.push({ kind: "party", until: this.time + DAY });
          if (host) {
            rel(g, host.id).aff = clamp(rel(g, host.id).aff + 8, -100, 100);
            rel(host, g.id).aff = clamp(rel(host, g.id).aff + 5, -100, 100);
          }
        }
        if (host) {
          remember(this, host, `${guests.length} people came to my party. ${guests.length >= 4 ? "What a night!" : "I hoped more would come."}`, 8, "life");
          if (host.goal && host.goal.kind === "party" && host.goal.fact === p.fact) host.goal = null;
        }
        for (const a of this.agents) if (a.goingTo) a.goingTo = a.goingTo.filter((id) => id !== p.fact);
        this.addFact("partydone", `${guests.length} guests came to ${this.nameOf(p.host)}'s party at ${p.place}`, { x: p.x, y: p.y, radius: 3, about: guests, imp: 5, icon: "🎊", toast: true });
      }
    }
    if (this.parties.length > 20) this.parties = this.parties.filter((p) => !p.over || this.time - p.end < DAY);
  }

  // ---------- god powers ----------
  nearestAgent(x, y, r = 2) {
    let best = null;
    let bd = r;
    for (const a of this.agents) {
      const d = dist(a.x, a.y, x, y);
      if (d < bd) {
        bd = d;
        best = a;
      }
    }
    return best;
  }

  spawnVillager(x, y) {
    const W = this.world;
    const p = W.nearest(x, y, 4, (i, xx, yy) => W.walkable(xx, yy));
    if (!p) return { ok: false, msg: "Can't stand there." };
    let v = this.nearestVillage(p.x, p.y, 26);
    let founded = false;
    if (!v) {
      v = this.foundVillage(p.x, p.y);
      if (!v) return { ok: false, msg: "No room for a village here." };
      founded = true;
    }
    const a = this.addAgent(makeAgent(this, { x: p.x + 0.5, y: p.y + 0.5, village: v.id, age: randInt(this.rand, 17, 45) }));
    for (const o of this.members(v)) if (o !== a) rel(a, o.id).aff = rel(o, a.id).aff = randInt(this.rand, -5, 10);
    makePlan(this, a);
    this.assignHomes(v);
    this.assignJobs(v);
    if (founded) {
      this.event(`${a.name} ${a.last} founded the village of ${v.name}.`, "🚩", { x: p.x, y: p.y, toast: true });
      remember(this, a, `I founded ${v.name}. A fresh start.`, 9, "life");
      for (const o of this.agents) if (o !== a && this.rand() < 0.3) learn(this, o, this.addFact("village", `a new village called ${v.name} was founded`, { imp: 6, icon: "🚩", about: [a.id] }), "news");
    } else {
      this.addFact("newcomer", `${a.name} ${a.last} moved to ${v.name}`, { x: a.x, y: a.y, radius: 6, about: [a.id], imp: 5, icon: "🧳" });
      remember(this, a, `I arrived in ${v.name}. I hope people here are nice.`, 7, "life");
    }
    return { ok: true, msg: founded ? `${a.name} founded ${v.name}` : `${a.name} joined ${v.name}`, agent: a };
  }

  power(kind, x, y, o = {}) {
    const W = this.world;
    const tx = Math.floor(x);
    const ty = Math.floor(y);
    if (!W.inb(tx, ty)) return { ok: false };
    const now = Date.now();
    switch (kind) {
      case "villager":
        return this.spawnVillager(tx, ty);
      case "sheep":
      case "wolf": {
        if (!W.walkable(tx, ty)) return { ok: false, msg: "Animals need land." };
        this.animals.push(makeAnimal(this, kind, tx + 0.5, ty + 0.5));
        if (kind === "wolf") this.addFact("wolf", `a wolf was seen near ${this.describePlace(x, y)}`, { x, y, radius: 7, imp: 6, icon: "🐺" });
        return { ok: true };
      }
      case "fire": {
        let lit = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (W.inb(tx + dx, ty + dy) && this.ignite(W.idx(tx + dx, ty + dy), dx === 0 && dy === 0)) lit++;
        if (lit) this.addFact("fire", `a fire broke out near ${this.describePlace(x, y)}`, { x, y, radius: 9, imp: 7, icon: "🔥", toast: true });
        return { ok: lit > 0 };
      }
      case "lightning": {
        this.fx.push({ kind: "bolt", x: tx + 0.5, y: ty + 0.5, t0: now });
        this.ignite(W.idx(tx, ty), true);
        this.strike(tx + 0.5, ty + 0.5, 1.3, 75, "was struck by lightning");
        return { ok: true };
      }
      case "smite": {
        const a = this.nearestAgent(x, y, 2.5);
        if (!a) return { ok: false, msg: "Tap closer to a villager." };
        this.fx.push({ kind: "bolt", x: a.x, y: a.y, t0: now });
        this.killAgent(a, "was struck down by the heavens");
        return { ok: true };
      }
      case "meteor": {
        this.fx.push({ kind: "meteor", x: tx + 0.5, y: ty + 0.5, t0: now });
        for (let dy = -4; dy <= 4; dy++)
          for (let dx = -4; dx <= 4; dx++) {
            const xx = tx + dx;
            const yy = ty + dy;
            if (!W.inb(xx, yy)) continue;
            const d = Math.hypot(dx, dy);
            const i = W.idx(xx, yy);
            if (d <= 1.2) W.setT(xx, yy, T.WATER);
            else if (d <= 3 && W.t[i] !== T.WATER && W.t[i] !== T.DEEP) {
              W.setT(xx, yy, d < 2.2 ? T.DIRT : T.ASH);
              W.setFlora(i, F.NONE);
              W.road[i] = 0;
            } else if (d <= 4.2 && this.rand() < 0.5) this.ignite(i);
          }
        for (const b of [...this.buildings]) if (dist(b.x + b.w / 2, b.y + b.h / 2, tx + 0.5, ty + 0.5) < 3 + b.w / 2) this.removeBuilding(b, "flattened by a meteor");
        this.strike(tx + 0.5, ty + 0.5, 3.2, 999, "was killed by a falling meteor");
        this.strike(tx + 0.5, ty + 0.5, 5.5, 35, "");
        this.addFact("meteor", `a meteor crashed into ${this.describePlace(x, y)}`, { x, y, radius: 40, imp: 9, icon: "☄️", toast: true });
        return { ok: true };
      }
      case "rain":
        this.weather = { kind: "rain", until: this.time + 4 * 60 };
        this.event("The heavens opened: heavy rain.", "🌧️", { toast: true });
        return { ok: true };
      case "bless": {
        const hit = this.agents.filter((a) => dist(a.x, a.y, x, y) < 3.5);
        for (const a of hit) {
          a.health = 100;
          a.sick = false;
          a.needs.hunger = Math.max(a.needs.hunger, 80);
          a.buffs.push({ kind: "blessed", until: this.time + DAY });
          remember(this, a, "A warm golden light washed over me. I feel wonderful.", 8, "event");
        }
        this.fx.push({ kind: "bless", x, y, t0: now });
        if (hit.length) this.addFact("bless", `a golden light blessed ${hit.map((a) => a.name).slice(0, 3).join(", ")}`, { x, y, radius: 7, imp: 7, icon: "✨", about: hit.map((a) => a.id) });
        return { ok: true, msg: hit.length ? `Blessed ${hit.length}` : "Nobody there, but the land glows." };
      }
      case "plague": {
        const a = this.nearestAgent(x, y, 3);
        if (!a) return { ok: false, msg: "Tap closer to a villager." };
        a.sick = true;
        remember(this, a, "I feel feverish and weak.", 7, "event");
        this.addFact("sick", `${a.name} has fallen ill`, { x: a.x, y: a.y, radius: 4, about: [a.id], imp: 6, icon: "🤒", toast: true });
        return { ok: true };
      }
      case "madness": {
        const a = this.nearestAgent(x, y, 3);
        if (!a) return { ok: false, msg: "Tap closer to a villager." };
        a.buffs.push({ kind: "angry", until: this.time + DAY });
        remember(this, a, "Everything and everyone is making me furious today.", 7, "event");
        this.fx.push({ kind: "float", x: a.x, y: a.y - 1, text: "😡", t0: now });
        return { ok: true };
      }
      case "erase": {
        const b = this.buildingAt(tx, ty);
        if (b) {
          this.removeBuilding(b, b.done ? "torn down" : "");
          return { ok: true, msg: `Removed ${b.name}` };
        }
        const n = this.animals.find((m) => dist(m.x, m.y, x, y) < 1.5);
        if (n) {
          this.animals = this.animals.filter((m) => m !== n);
          return { ok: true };
        }
        if (W.road[W.idx(tx, ty)]) {
          W.setRoad(W.idx(tx, ty), 0);
          return { ok: true };
        }
        return { ok: false };
      }
      default:
        if (kind.startsWith("land:")) return this.paint(kind.slice(5), x, y, o.size || 1);
        return { ok: false };
    }
  }

  strike(x, y, r, dmg, cause) {
    for (const a of [...this.agents])
      if (dist(a.x, a.y, x, y) < r) {
        a.health -= dmg;
        if (a.health <= 0) this.killAgent(a, cause || "died of their wounds");
        else remember(this, a, "Something exploded right next to me. I'm hurt.", 7, "event");
      }
    this.animals = this.animals.filter((n) => dist(n.x, n.y, x, y) >= r || (n.hp -= dmg) > 0);
  }

  paint(type, x, y, size) {
    const W = this.world;
    const r = size - 0.5;
    let n = 0;
    for (let dy = -size; dy <= size; dy++)
      for (let dx = -size; dx <= size; dx++) {
        if (Math.hypot(dx, dy) > r + 0.01 && !(dx === 0 && dy === 0)) continue;
        const xx = Math.floor(x) + dx;
        const yy = Math.floor(y) + dy;
        if (!W.inb(xx, yy)) continue;
        const i = W.idx(xx, yy);
        if (W.bld[i] >= 0) continue;
        n++;
        switch (type) {
          case "grass":
            W.setT(xx, yy, T.GRASS);
            W.setFlora(i, F.NONE);
            break;
          case "forest":
            if (!W.buildable(xx, yy)) W.setT(xx, yy, T.GRASS);
            W.setFlora(i, this.rand() < 0.7 ? F.TREE : F.YOUNG);
            break;
          case "flowers":
            if (!W.buildable(xx, yy)) W.setT(xx, yy, T.GRASS);
            W.setFlora(i, this.rand() < 0.7 ? F.FLOWERS : F.BUSH);
            break;
          case "water":
            W.setT(xx, yy, T.WATER);
            break;
          case "deep":
            W.setT(xx, yy, T.DEEP);
            break;
          case "sand":
            W.setT(xx, yy, T.SAND);
            W.setFlora(i, F.NONE);
            break;
          case "hill":
            W.setT(xx, yy, T.HILL);
            break;
          case "mountain":
            W.setT(xx, yy, T.MOUNTAIN);
            break;
          case "road":
            if (W.walkable(xx, yy) && W.t[i] !== T.WATER) {
              W.setRoad(i, 1);
              if (W.flora[i] !== F.NONE) W.setFlora(i, F.NONE);
            }
            break;
          case "clear":
            W.setFlora(i, F.NONE);
            if (W.road[i]) W.setRoad(i, 0);
            break;
        }
      }
    return { ok: n > 0 };
  }

  // ---------- whispers (plant ideas, Smallville style) ----------
  whisper(a, kind, data = {}) {
    const v = this.villageById(a.village);
    switch (kind) {
      case "thought": {
        const text = String(data.text || "").trim().slice(0, 140);
        if (!text) return { ok: false };
        remember(this, a, `A thought struck me: ${text}`, 9, "whisper");
        const f = this.addFact("idea", `${a.name} believes ${text}`, { about: [a.id], imp: 7, icon: "💭", data: { text, by: a.id } });
        a.idea = f.id;
        return { ok: true, msg: `${a.name} can't stop thinking about it.` };
      }
      case "party": {
        if (!v) return { ok: false };
        const place =
          this.buildings.find((b) => b.village === v.id && b.done && b.type === "tavern") ||
          this.buildings.find((b) => b.village === v.id && b.done && b.type === "park") ||
          this.hallOf(v);
        if (!place) return { ok: false };
        const dayStart = Math.floor(this.time / DAY) * DAY;
        // Next evening, so word has a day to travel (tonight if it is still early).
        const at = dayStart + (this.hour < 6 ? 0 : DAY) + 18 * 60;
        const f = this.addFact("party", `${a.name} is throwing a party at ${place.name} on ${this.when(at)}`, {
          about: [a.id],
          imp: 8,
          icon: "🎉",
          data: { host: a.id, bid: place.id, at },
        });
        this.parties.push({ fact: f.id, host: a.id, at, end: at + 4 * 60, place: place.name, x: place.x + place.w / 2, y: place.y + place.h, guests: [], started: false, over: false });
        a.goingTo = [...(a.goingTo || []), f.id];
        a.goal = { kind: "party", fact: f.id };
        remember(this, a, `I'm going to throw a party at ${place.name} on ${this.when(at)}! I should invite everyone.`, 9, "whisper");
        a.planDay = -1;
        return { ok: true, msg: `${a.name} will host a party at ${this.clock(at)} on day ${Math.floor(at / DAY) + 1}.` };
      }
      case "crush": {
        const b = this.agentById(data.target);
        if (!b || b === a) return { ok: false };
        rel(a, b.id).aff = Math.max(rel(a, b.id).aff, 60);
        a.crush = b.id;
        remember(this, a, `I can't stop thinking about ${b.name}. Is this love?`, 9, "whisper");
        return { ok: true, msg: `${a.name} is smitten with ${b.name}.` };
      }
      case "grudge": {
        const b = this.agentById(data.target);
        if (!b || b === a) return { ok: false };
        rel(a, b.id).aff = Math.min(rel(a, b.id).aff, -60);
        remember(this, a, `${b.name} wronged me. I won't forget it.`, 9, "whisper");
        return { ok: true, msg: `${a.name} now resents ${b.name}.` };
      }
      case "build": {
        if (!v) return { ok: false };
        const type = data.type || "house";
        const spot = this.findSpot(v, type);
        if (!spot) return { ok: false, msg: "No room near the village." };
        const b = this.placeBuilding(type, spot.x, spot.y, v, { byPlayer: true });
        a.goal = { kind: "build", bid: b.id };
        remember(this, a, `I've decided to build ${aOrAn(BUILDINGS[type].name.toLowerCase())}. I'll need help.`, 9, "whisper");
        this.addFact("plan", `${a.name} wants to build ${aOrAn(BUILDINGS[type].name.toLowerCase())} near ${this.describePlace(b.x, b.y)}`, { about: [a.id], imp: 6, icon: "📐", data: { bid: b.id } });
        return { ok: true, msg: `${a.name} is rallying help for ${aOrAn(BUILDINGS[type].name.toLowerCase())}.` };
      }
    }
    return { ok: false };
  }

  // ---------- save ----------
  serialize() {
    return {
      v: 1,
      seed: this.seed,
      rng: this.rand.getState(),
      time: this.time,
      nextId: this.nextId,
      world: this.world.serialize(),
      villages: this.villages,
      agents: this.agents.map((a) => ({ ...a, knowsSet: undefined, convo: null, action: null, path: null })),
      animals: this.animals.map((n) => ({ ...n, path: null })),
      buildings: this.buildings,
      facts: [...this.facts.values()],
      log: this.log.slice(-120),
      feed: this.feed.slice(-200),
      graves: this.graves,
      dead: this.dead,
      parties: this.parties,
      weather: this.weather,
      settings: this.settings,
      stats: this.stats,
      names: [...this.names],
      fires: this.fires.map((i) => [i, Math.round(this.world.fire[i])]),
    };
  }

  static deserialize(o) {
    const s = new Sim(o.seed);
    s.rand.setState(o.rng);
    s.time = o.time;
    s.nextId = o.nextId;
    s.world = World.deserialize(o.world);
    s.villages = o.villages;
    s.buildings = o.buildings;
    for (const b of s.buildings) {
      s.bmap.set(b.id, b);
      for (let y = b.y; y < b.y + b.h; y++) for (let x = b.x; x < b.x + b.w; x++) s.world.bld[s.world.idx(x, y)] = b.id;
    }
    s.agents = o.agents.map((a) => ({ ...a, knowsSet: new Set(a.knows), convo: null, action: null, path: null, planDay: -1 }));
    for (const a of s.agents) s.amap.set(a.id, a);
    s.animals = o.animals;
    for (const f of o.facts) s.facts.set(f.id, f);
    s.log = o.log;
    s.feed = o.feed;
    s.graves = o.graves;
    s.dead = o.dead;
    s.parties = o.parties;
    s.weather = o.weather;
    s.settings = { ...s.settings, ...o.settings };
    s.stats = o.stats;
    s.names = new Map(o.names);
    for (const [i, f] of o.fires || []) {
      if (f > 0 && s.world.fire[i] === 0) {
        s.world.fire[i] = f;
        s.fires.push(i);
      }
    }
    s._lastHour = Math.floor(s.time / 60);
    return s;
  }
}

export function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
export function aOrAn(w) {
  return (/^[aeiou]/i.test(w) ? "an " : "a ") + w;
}
