// A villager's life: needs, daily plan, actions, work and nightly reflection.
import { BUILDINGS, CLASHES, FIRST_NAMES, HAIR, JOBS, LAST_NAMES, SKILLS, SKIN, TRAITS } from "./data.js";
import { chance, clamp, dist, pick, randInt } from "./rng.js";
import { F, T } from "./world.js";
import { aff, bestFriend, hasTrait, remember, traitVal, worstRival } from "./social.js";
import { startConversation } from "./talk.js";

export const YEAR = 2 * 1440;

export function makeAgent(sim, o) {
  const r = sim.rand;
  const traits = [];
  const keys = Object.keys(TRAITS);
  while (traits.length < 2) {
    const t = pick(r, keys);
    if (traits.includes(t) || CLASHES.some(([p, q]) => (p === t && traits.includes(q)) || (q === t && traits.includes(p)))) continue;
    traits.push(t);
  }
  const used = new Set(sim.agents.map((a) => a.name));
  let name = pick(r, FIRST_NAMES);
  for (let k = 0; k < 20 && used.has(name); k++) name = pick(r, FIRST_NAMES);
  const age = o.age ?? 25;
  const skills = {};
  for (const s of SKILLS) skills[s] = age < 14 ? r() : 1 + r() * 3 + Math.min(age, 40) / 20;
  return {
    id: sim.id(),
    name,
    last: o.last || pick(r, LAST_NAMES),
    village: o.village,
    x: o.x,
    y: o.y,
    age,
    traits,
    job: age < 14 ? "child" : age >= 62 ? "elder" : "idle",
    jobLocked: false,
    workAt: null,
    skills,
    needs: { hunger: randInt(r, 60, 95), energy: randInt(r, 70, 95), social: randInt(r, 45, 85), fun: randInt(r, 45, 85) },
    health: 100,
    happy: 60,
    home: null,
    partner: null,
    parents: o.parents || [],
    children: [],
    rel: {},
    mem: [],
    knows: [],
    knowsSet: new Set(),
    src: {},
    plan: [],
    planDay: -1,
    action: null,
    path: null,
    convo: null,
    lastTalk: -1e9,
    sick: false,
    buffs: [],
    doing: "Looking around",
    thought: "",
    carry: null,
    alive: true,
    goingTo: [],
    goal: null,
    help: null,
    idea: null,
    crush: null,
    look: { skin: pick(r, SKIN), hair: pick(r, HAIR), hairStyle: randInt(r, 0, 3) },
    facing: 1,
    walk: 0,
    work: 0,
    dangerT: 0,
  };
}

// ---------- happiness ----------
const BUFF_MOOD = { joy: 20, party: 12, blessed: 25, proud: 15, grief: -30, sad: -15, angry: -20, calm: 8 };
export function moodParts(sim, a) {
  const n = a.needs;
  const parts = [["Needs", Math.round(((n.hunger + n.energy + n.social + n.fun) / 4 - 50) * 0.6)]];
  if (a.health < 70) parts.push(["Hurt", Math.round((a.health - 70) / 3)]);
  if (a.sick) parts.push(["Sick", -15]);
  if (a.home == null && a.age >= 1) parts.push(["No home", -10]);
  for (const t of a.traits) if (TRAITS[t].mood) parts.push([TRAITS[t].label, TRAITS[t].mood]);
  for (const b of a.buffs) if (BUFF_MOOD[b.kind]) parts.push([b.kind[0].toUpperCase() + b.kind.slice(1), BUFF_MOOD[b.kind]]);
  if (a.partner) parts.push(["In love", 6]);
  if (sim.weather.kind === "rain" && !hasTrait(a, "cheerful")) parts.push(["Rain", -3]);
  return parts;
}
function targetHappy(sim, a) {
  return clamp(55 + moodParts(sim, a).reduce((s, p) => s + p[1], 0), 0, 100);
}

// ---------- update ----------
export function updateAgent(sim, a, dt) {
  const n = a.needs;
  const sleeping = a.action && a.action.kind === "sleep" && a.action.phase === "do";
  n.hunger = Math.max(0, n.hunger - dt * (a.age < 3 ? 0.03 : 0.052));
  n.energy = sleeping ? Math.min(100, n.energy + dt * 0.21) : Math.max(0, n.energy - dt * 0.062);
  n.social = Math.max(0, n.social - dt * (sleeping ? 0.01 : 0.035) * traitVal(a, "social"));
  n.fun = Math.max(0, n.fun - dt * (sleeping ? 0.008 : 0.022));
  if (a.age < 3 && n.hunger < 50) {
    // Parents feed the little ones from the village store.
    const v = sim.villageById(a.village);
    if (v && v.stock.food >= 1) {
      v.stock.food -= 1;
      n.hunger += 50;
    }
  }
  if (n.hunger <= 0) a.health -= dt * 0.035;
  if (a.sick) {
    a.health -= dt * 0.01;
    if (sim.rand() < dt * 0.00025) {
      a.sick = false;
      remember(sim, a, "I finally feel better. The fever is gone.", 6, "life");
    }
  } else if (n.hunger > 25 && a.health < 100) a.health = Math.min(100, a.health + dt * 0.02);
  if (a.health <= 0) {
    sim.killAgent(a, n.hunger <= 0 ? "starved to death" : a.sick ? "died of a fever" : "died of their wounds");
    return;
  }
  a.age += dt / YEAR;
  a.happy += (targetHappy(sim, a) - a.happy) * Math.min(1, dt * 0.03);

  // Pushed off land by a god? Step to the nearest dry tile.
  const W = sim.world;
  if (!W.walkable(Math.floor(a.x), Math.floor(a.y))) {
    const p = W.nearest(a.x, a.y, 10, (i, x, y) => W.walkable(x, y));
    if (p) {
      a.x = p.x + 0.5;
      a.y = p.y + 0.5;
    }
    a.action = null;
    a.path = null;
  }
  if (a.convo) {
    a.walk = 0;
    return;
  }
  a.dangerT += dt;
  if (a.dangerT >= 4) {
    a.dangerT = 0;
    const k = a.action && a.action.kind;
    if (k !== "flee" && k !== "fight" && k !== "firefight" && danger(sim, a)) return;
  }
  if (!a.action) chooseAction(sim, a);
  if (a.action) runAction(sim, a, dt);
}

// ---------- plan ----------
function homeName(sim, a) {
  const h = a.home != null && sim.buildingById(a.home);
  return h ? "home" : "under the stars";
}
function workText(sim, a) {
  const v = sim.villageById(a.village);
  const vb = (t) => sim.buildings.find((b) => b.village === a.village && b.type === t && b.done);
  switch (a.job) {
    case "farmer": {
      const f = farmFor(sim, a);
      return f ? `Tend the crops at ${f.name}` : "Look for a farm to work";
    }
    case "woodcutter":
      return "Chop wood in the forest";
    case "miner":
      return "Mine stone in the hills";
    case "builder": {
      const b = sim.buildings.find((x) => x.village === a.village && !x.done);
      return b ? `Build the new ${BUILDINGS[b.type].name.toLowerCase()}` : "Help out around the village";
    }
    case "idle":
      return "Look for something useful to do";
    default: {
      const place = JOBS[a.job].place && vb(JOBS[a.job].place);
      return place ? `Work as ${JOBS[a.job].label.toLowerCase()} at ${place.name}` : `Work around ${v ? v.name : "the village"}`;
    }
  }
}

export function makePlan(sim, a) {
  const steps = [];
  const S = (h0, h1, kind, text, extra = {}) => steps.push({ h0, h1, kind, text, ...extra });
  const hn = homeName(sim, a);
  const vb = (t) => sim.buildings.find((b) => b.village === a.village && b.type === t && b.done);
  const school = vb("school");
  a.planDay = sim.day;
  if (a.age < 3) {
    S(0, 7, "sleep", "Sleep");
    S(7, 20, "home", "Toddle around at home");
    S(20, 24, "sleep", "Sleep");
  } else if (a.age < 14) {
    S(0, 7, "sleep", `Sleep at ${hn}`);
    S(7, 8, "eat", "Breakfast");
    if (school) S(8, 14, "school", `Lessons at ${school.name}`);
    else S(8, 14, "play", "Play around the village");
    S(14, 19, "play", "Play with friends");
    S(19, 20, "eat", "Supper");
    S(20, 24, "sleep", "Bedtime");
  } else if (a.job === "elder") {
    S(0, 7, "sleep", `Sleep at ${hn}`);
    S(7, 8, "eat", "Slow breakfast");
    S(8, 12, "leisure", "Stroll and chat with neighbours", { act: "wander" });
    S(12, 13, "eat", "Lunch");
    S(13, 15, "home", "Nap at home");
    const well = vb("well");
    S(15, 20, "leisure", well ? `Tell stories by ${well.name}` : "Tell stories to anyone who'll listen", { act: well ? "place" : "wander", place: well && well.id });
    S(20, 24, "sleep", "Early night");
  } else {
    const lazy = hasTrait(a, "lazy");
    const hard = hasTrait(a, "hardworking") || hasTrait(a, "ambitious");
    const wake = lazy ? 8 : hard ? 6 : 7;
    const end = lazy ? 16 : hard ? 18 : 17;
    const bed = hasTrait(a, "friendly") || hasTrait(a, "gossip") ? 23 : lazy ? 22 : 22;
    S(0, wake, "sleep", `Sleep at ${hn}`);
    S(wake, wake + 1, "eat", "Wake up and have breakfast");
    S(wake + 1, 12, "work", workText(sim, a));
    S(12, 13, "eat", "Lunch break");
    const hosting = a.goal && a.goal.kind === "party" && sim.parties.some((x) => x.fact === a.goal.fact && !x.over && x.at > sim.time);
    if (hosting) S(13, end, "leisure", "Invite people to my party", { act: "invite" });
    else S(13, end, "work", workText(sim, a));
    // Evening.
    const party = nextParty(sim, a);
    const leisure = pickLeisure(sim, a);
    if (party && party.at < (Math.floor(sim.time / 1440) + 1) * 1440) {
      const ph = (party.at % 1440) / 60;
      if (ph > end) S(end, ph, "leisure", leisure.text, leisure);
      S(Math.max(end, ph), Math.min(24, ph + 4), "party", `Go to ${sim.nameOf(party.host)}'s party at ${party.place}`, { fact: party.fact });
      if (ph + 4 < bed) S(ph + 4, bed, "leisure", leisure.text, leisure);
    } else S(end, bed, "leisure", leisure.text, leisure);
    S(bed, 24, "sleep", `Sleep at ${hn}`);
  }
  a.plan = steps;
}

function nextParty(sim, a) {
  for (const p of sim.parties) if (!p.over && a.goingTo && a.goingTo.includes(p.fact) && p.end > sim.time) return p;
  return null;
}

function pickLeisure(sim, a) {
  const vb = (t) => sim.buildings.find((b) => b.village === a.village && b.type === t && b.done);
  const tavern = vb("tavern");
  const park = vb("park");
  const r = sim.rand;
  if (a.goal && a.goal.kind === "party") {
    const p = sim.parties.find((x) => x.fact === a.goal.fact && !x.over);
    if (p && p.at > sim.time) return { text: "Invite everyone to my party", act: "invite" };
  }
  if (a.help != null && sim.buildingById(a.help) && !sim.buildingById(a.help).done) return { text: `Help build ${sim.buildingById(a.help).name}`, act: "help", bid: a.help };
  if (a.goal && a.goal.kind === "build") {
    const b = sim.buildingById(a.goal.bid);
    if (b && !b.done) return { text: `Work on my ${BUILDINGS[b.type].name.toLowerCase()} project`, act: "help", bid: b.id };
  }
  const crush = a.crush != null && sim.agentById(a.crush);
  if (crush) return { text: `Find ${crush.name} and spend time together`, act: "visit", target: crush.id };
  const partner = a.partner != null && sim.agentById(a.partner);
  if (partner && (hasTrait(a, "romantic") || chance(r, 0.35))) return { text: `Spend the evening with ${partner.name}`, act: "visit", target: partner.id };
  const friend = bestFriend(sim, a);
  if (hasTrait(a, "shy") && chance(r, 0.6)) return { text: "Read quietly at home", act: "home" };
  if (hasTrait(a, "curious") && chance(r, 0.5)) return { text: "Explore somewhere new", act: "explore" };
  if (tavern && chance(r, hasTrait(a, "friendly") || hasTrait(a, "gossip") ? 0.6 : 0.35)) return { text: `Drinks and gossip at ${tavern.name}`, act: "place", place: tavern.id };
  if (friend && chance(r, 0.55)) return { text: `Catch up with ${friend.name}`, act: "visit", target: friend.id };
  if (park && chance(r, 0.4)) return { text: `Relax at ${park.name}`, act: "place", place: park.id };
  const well = vb("well");
  if (well && chance(r, 0.4)) return { text: `Chat by ${well.name}`, act: "place", place: well.id };
  return { text: "Stroll around the village", act: "wander" };
}

export function currentStep(sim, a) {
  const h = sim.hour;
  return a.plan.find((s) => h >= s.h0 && h < s.h1) || null;
}

// ---------- choosing what to do ----------
function chooseAction(sim, a) {
  if (a.planDay !== sim.day && sim.hour >= 5) makePlan(sim, a);
  const n = a.needs;
  if (n.energy < 6) return act(sim, a, "sleep", Math.floor(a.x), Math.floor(a.y), 180, {}, "Collapsed from exhaustion");
  if (n.hunger < 25 && a.age >= 2 && eat(sim, a, true)) return;
  if (a.sick && seekHealer(sim, a)) return;
  const party = nextParty(sim, a);
  if (party && sim.time >= party.at - 30 && sim.time < party.end && a.age >= 3) return goParty(sim, a, party);
  const step = currentStep(sim, a);
  const kind = step ? step.kind : "leisure";
  switch (kind) {
    case "sleep":
      return goSleep(sim, a, step);
    case "eat":
      if (n.hunger < 75 && eat(sim, a, false)) return;
      return idleHome(sim, a, 30);
    case "work":
      if (doWork(sim, a)) return;
      break;
    case "school":
      if (goSchool(sim, a)) return;
      return play(sim, a);
    case "play":
      return play(sim, a);
    case "home":
      return idleHome(sim, a, 60);
    case "party":
      break;
    case "leisure":
      if (n.hunger < 45 && eat(sim, a, false)) return;
      if (leisure(sim, a, step)) return;
      break;
  }
  wander(sim, a, 8);
}

function act(sim, a, kind, tx, ty, dur, data = {}, doing = "") {
  const path = sim.world.findPath(Math.floor(a.x), Math.floor(a.y), tx, ty);
  if (!path) return false;
  a.path = path;
  a.action = { kind, tx, ty, dur, timer: dur, phase: path.length ? "walk" : "do", data, t0: sim.time };
  a.doing = doing;
  return true;
}
const door = (b) => ({ x: b.x + Math.floor(b.w / 2), y: b.y + b.h - 1 });

function hallFor(sim, a) {
  const v = sim.villageById(a.village);
  return v ? sim.hallOf(v) : null;
}

function goSleep(sim, a, step) {
  const h = a.home != null && sim.buildingById(a.home);
  const target = h ? door(h) : hallFor(sim, a) ? door(hallFor(sim, a)) : { x: Math.floor(a.x), y: Math.floor(a.y) };
  const hrs = step ? (step.h1 === 24 ? 24 - sim.hour + (a.age < 14 ? 7 : 6.5) : step.h1 - sim.hour) : 2;
  const dur = clamp(hrs * 60, 30, 600);
  if (act(sim, a, "sleep", target.x, target.y, dur, {}, h ? "Sleeping at home" : "Sleeping under the stars")) return true;
  return act(sim, a, "sleep", Math.floor(a.x), Math.floor(a.y), dur, {}, "Napping on the ground");
}

function eat(sim, a, urgent) {
  const v = sim.villageById(a.village);
  if (v && v.stock.food >= 1) {
    const h = a.home != null && sim.buildingById(a.home);
    const tavern = sim.buildings.find((b) => b.village === a.village && b.type === "tavern" && b.done);
    const place = h || hallFor(sim, a);
    const atTavern = tavern && !urgent && chance(sim.rand, 0.25);
    const p = atTavern ? tavern : place;
    if (p) {
      const d = door(p);
      return act(sim, a, "eat", d.x, d.y, 25, { place: p.id }, atTavern ? `Having a meal at ${tavern.name}` : h ? "Eating at home" : "Eating at the hall");
    }
  }
  // No food in store: berries, then sheep.
  const W = sim.world;
  const bush = W.nearest(a.x, a.y, 16, (i) => W.flora[i] === F.BUSH);
  if (bush) return act(sim, a, "forage", bush.x, bush.y, 20, { i: bush.i }, "Picking berries");
  const sheep = sim.animals.filter((n) => n.kind === "sheep" && dist(n.x, n.y, a.x, a.y) < 22);
  if (sheep.length && a.age >= 14) {
    const s = sheep.sort((p, q) => dist(p.x, p.y, a.x, a.y) - dist(q.x, q.y, a.x, a.y))[0];
    return act(sim, a, "hunt", Math.floor(s.x), Math.floor(s.y), 15, { target: s.id }, "Hunting a sheep");
  }
  a.thought = "There's nothing to eat anywhere...";
  return false;
}

function seekHealer(sim, a) {
  const clinic = sim.buildings.find((b) => b.village === a.village && b.type === "clinic" && b.done);
  if (!clinic || !sim.agents.some((o) => o.job === "healer" && o.village === a.village)) return false;
  if (a.action && a.action.kind === "heal") return false;
  const d = door(clinic);
  return act(sim, a, "heal", d.x, d.y, 60, { bid: clinic.id }, `Getting treated at ${clinic.name}`);
}

function goParty(sim, a, p) {
  const W = sim.world;
  const spot = W.nearest(p.x + (sim.rand() - 0.5) * 3, p.y + 0.5 + sim.rand() * 1.5, 4, (i, x, y) => W.walkable(x, y));
  if (!spot) return false;
  return act(sim, a, "party", spot.x, spot.y, Math.max(20, Math.min(p.end - sim.time, 90)), { fact: p.fact }, `At ${sim.nameOf(p.host)}'s party`);
}

function idleHome(sim, a, dur) {
  const h = a.home != null && sim.buildingById(a.home);
  if (h) {
    const d = door(h);
    if (act(sim, a, "idle", d.x, d.y, dur, {}, hasTrait(a, "shy") ? "Reading at home" : "Pottering about at home")) return true;
  }
  return wander(sim, a, 5);
}

function wander(sim, a, r) {
  const W = sim.world;
  const hall = hallFor(sim, a);
  const cx = hall ? hall.x + 1 : a.x;
  const cy = hall ? hall.y + 1 : a.y;
  for (let k = 0; k < 8; k++) {
    const x = Math.floor(cx + (sim.rand() - 0.5) * r * 2);
    const y = Math.floor(cy + (sim.rand() - 0.5) * r * 2);
    if (W.walkable(x, y) && W.t[W.idx(x, y)] !== T.WATER && act(sim, a, "wander", x, y, randInt(sim.rand, 10, 40), {}, "Taking a stroll")) return true;
  }
  return act(sim, a, "idle", Math.floor(a.x), Math.floor(a.y), 20, {}, "Standing around");
}

function play(sim, a) {
  if (a.age < 3) return idleHome(sim, a, 60);
  return wander(sim, a, 6) && ((a.doing = pick(sim.rand, ["Playing tag", "Chasing butterflies", "Building a stick fort", "Playing hide and seek"])), true);
}

function goSchool(sim, a) {
  const s = sim.buildings.find((b) => b.village === a.village && b.type === "school" && b.done);
  if (!s) return false;
  const d = door(s);
  return act(sim, a, "learn", d.x, d.y, 90, { bid: s.id }, `In class at ${s.name}`);
}

function leisure(sim, a, step) {
  switch (step.act) {
    case "visit": {
      const t = sim.agentById(step.target);
      if (!t || t.convo || (t.action && t.action.kind === "sleep" && t.action.phase === "do")) return false;
      if (dist(t.x, t.y, a.x, a.y) > 45) return false;
      const spot = sim.world.standNear(Math.floor(t.x), Math.floor(t.y), a.x, a.y) || { x: Math.floor(t.x), y: Math.floor(t.y) };
      return act(sim, a, "visit", spot.x, spot.y, 15, { target: t.id, tries: 0 }, `Going to see ${t.name}`);
    }
    case "invite": {
      const p = sim.parties.find((x) => a.goal && x.fact === a.goal.fact);
      if (!p) return false;
      const cands = sim.agents.filter((o) => o !== a && !o.knowsSet.has(p.fact) && !o.convo && o.age >= 6 && dist(o.x, o.y, a.x, a.y) < 40);
      if (!cands.length) return wander(sim, a, 6);
      const t = cands.sort((p1, p2) => dist(p1.x, p1.y, a.x, a.y) - dist(p2.x, p2.y, a.x, a.y))[0];
      const spot = sim.world.standNear(Math.floor(t.x), Math.floor(t.y), a.x, a.y) || { x: Math.floor(t.x), y: Math.floor(t.y) };
      return act(sim, a, "visit", spot.x, spot.y, 15, { target: t.id, tries: 0 }, `Inviting ${t.name} to my party`);
    }
    case "help": {
      const b = sim.buildingById(step.bid);
      if (!b || b.done) return false;
      return buildAt(sim, a, b);
    }
    case "place": {
      const b = sim.buildingById(step.place);
      if (!b) return false;
      const W = sim.world;
      const spot = W.nearest(b.x + b.w / 2 + (sim.rand() - 0.5) * 3, b.y + b.h + sim.rand() * 1.5, 4, (i, x, y) => W.walkable(x, y));
      if (!spot) return false;
      return act(sim, a, "socialize", spot.x, spot.y, randInt(sim.rand, 50, 110), { bid: b.id }, step.text);
    }
    case "home":
      return idleHome(sim, a, 90);
    case "explore": {
      const W = sim.world;
      for (let k = 0; k < 10; k++) {
        const ang = sim.rand() * Math.PI * 2;
        const r = 10 + sim.rand() * 14;
        const x = Math.floor(a.x + Math.cos(ang) * r);
        const y = Math.floor(a.y + Math.sin(ang) * r);
        if (W.walkable(x, y) && W.t[W.idx(x, y)] !== T.WATER && act(sim, a, "explore", x, y, 30, {}, "Exploring")) return true;
      }
      return false;
    }
    default:
      return wander(sim, a, 9);
  }
}

// ---------- work ----------
function farmFor(sim, a) {
  const farms = sim.buildings.filter((b) => b.village === a.village && b.type === "farm" && b.done);
  if (!farms.length) return null;
  const cur = farms.find((f) => f.id === a.workAt);
  if (cur) return cur;
  const load = (f) => sim.agents.filter((o) => o.workAt === f.id).length;
  const f = farms.sort((p, q) => load(p) - load(q))[0];
  a.workAt = f.id;
  return f;
}

function doWork(sim, a) {
  const v = sim.villageById(a.village);
  if (!v) return false;
  if (a.carry) return deliver(sim, a);
  const W = sim.world;
  switch (a.job) {
    case "farmer": {
      const f = farmFor(sim, a);
      if (!f) return gather(sim, a, "wood");
      const spot = { x: f.x + randInt(sim.rand, 0, f.w - 1), y: f.y + randInt(sim.rand, 0, f.h - 1) };
      return act(sim, a, "farm", spot.x, spot.y, 60, { bid: f.id }, `Tending crops at ${f.name}`);
    }
    case "woodcutter":
      return gather(sim, a, "wood");
    case "miner":
      return gather(sim, a, "stone");
    case "builder": {
      const mine = a.goal && a.goal.kind === "build" && sim.buildingById(a.goal.bid);
      const pending = sim.buildings.filter((b) => b.village === a.village && !b.done);
      const target = (mine && !mine.done && mine) || pending.find((b) => b.byPlayer) || pending.sort((p, q) => q.progress - p.progress)[0];
      if (target) return buildAt(sim, a, target);
      return gather(sim, a, v.stock.wood < v.stock.stone * 2 ? "wood" : "stone");
    }
    case "guard": {
      const wolf = sim.animals.find((n) => n.kind === "wolf" && hallFor(sim, a) && dist(n.x, n.y, hallFor(sim, a).x, hallFor(sim, a).y) < 20);
      if (wolf) return fight(sim, a, wolf);
      const t = sim.buildings.find((b) => b.village === a.village && b.type === "tower" && b.done);
      if (!t) return wander(sim, a, 12);
      if (chance(sim.rand, 0.5)) return wander(sim, a, 14) && ((a.doing = "Patrolling the village"), true);
      const d = door(t);
      return act(sim, a, "workplace", d.x, d.y, 60, { bid: t.id }, `On watch at ${t.name}`);
    }
    case "idle":
      return false;
    default: {
      const place = JOBS[a.job] && JOBS[a.job].place;
      const b = place && sim.buildings.find((x) => x.village === a.village && x.type === place && x.done);
      if (!b) return false;
      const d = door(b);
      return act(sim, a, "workplace", d.x, d.y, 60, { bid: b.id }, `Working at ${b.name}`);
    }
  }
}

function gather(sim, a, what) {
  const W = sim.world;
  const hall = hallFor(sim, a);
  const cx = hall ? hall.x + 1 : a.x;
  const cy = hall ? hall.y + 1 : a.y;
  const taken = new Set(sim.agents.filter((o) => o !== a && o.action && o.action.data && o.action.data.i != null).map((o) => o.action.data.i));
  let target;
  if (what === "wood") target = W.nearest(cx, cy, 28, (i, x, y) => W.flora[i] === F.TREE && W.bld[i] < 0 && !taken.has(i));
  else target = W.nearest(cx, cy, 30, (i, x, y) => (W.t[i] === T.MOUNTAIN || W.t[i] === T.HILL) && !taken.has(i) && W.standNear(x, y, cx, cy));
  if (!target) {
    a.thought = what === "wood" ? "There are no trees left nearby!" : "I can't find any rock to mine.";
    return false;
  }
  const stand = what === "wood" ? { x: target.x, y: target.y } : W.t[target.i] === T.HILL ? { x: target.x, y: target.y } : W.standNear(target.x, target.y, a.x, a.y);
  if (!stand) return false;
  const place = sim.describePlace(target.x, target.y);
  return act(sim, a, what === "wood" ? "chop" : "mine", stand.x, stand.y, what === "wood" ? 40 : 50, { i: target.i }, what === "wood" ? `Chopping wood in ${place}` : `Mining stone in ${place}`);
}

function deliver(sim, a) {
  const hall = hallFor(sim, a);
  if (!hall) {
    a.carry = null;
    return false;
  }
  const d = door(hall);
  return act(sim, a, "deliver", d.x, d.y, 3, {}, `Carrying ${a.carry.n} ${a.carry.type} to the store`);
}

function buildAt(sim, a, b) {
  const W = sim.world;
  const spot = W.nearest(b.x + b.w / 2, b.y + b.h, 3, (i, x, y) => W.walkable(x, y) && (W.bld[i] < 0 || W.bld[i] === b.id));
  if (!spot) return false;
  return act(sim, a, "build", spot.x, spot.y, 45, { bid: b.id }, `Building ${b.type === "house" ? "a house" : b.name}`);
}

function fight(sim, a, wolf) {
  return act(sim, a, "fight", Math.floor(wolf.x), Math.floor(wolf.y), 120, { target: wolf.id, hit: 0, repath: 0 }, "Fighting a wolf!");
}

// Danger: wolves and fire nearby. Returns true if the villager reacted.
function danger(sim, a) {
  const W = sim.world;
  const wolf = sim.animals.find((n) => n.kind === "wolf" && dist(n.x, n.y, a.x, a.y) < 5);
  if (wolf) {
    if ((a.job === "guard" || hasTrait(a, "brave")) && a.health > 45 && a.age >= 16) return fight(sim, a, wolf);
    return flee(sim, a, wolf.x, wolf.y, "Running from a wolf!");
  }
  if (sim.fires.length) {
    let near = null;
    let nd = 3;
    let ownBld = null;
    let bd = 16;
    for (const i of sim.fires) {
      const x = i % W.w;
      const y = (i / W.w) | 0;
      const d = dist(x + 0.5, y + 0.5, a.x, a.y);
      if (d < nd) {
        nd = d;
        near = { x, y };
      }
      const bid = W.bld[i];
      if (bid >= 0 && d < bd) {
        const b = sim.buildingById(bid);
        if (b && b.village === a.village) {
          bd = d;
          ownBld = { x, y, i };
        }
      }
    }
    if (ownBld && a.age >= 14 && !hasTrait(a, "shy") && a.health > 40) {
      const s = W.standNear(ownBld.x, ownBld.y, a.x, a.y);
      if (s && act(sim, a, "firefight", s.x, s.y, 60, { i: ownBld.i }, "Fighting the fire!")) return true;
    }
    if (near) return flee(sim, a, near.x + 0.5, near.y + 0.5, "Running from the fire!");
  }
  return false;
}

function flee(sim, a, fx, fy, doing) {
  const W = sim.world;
  const dx = a.x - fx;
  const dy = a.y - fy;
  const len = Math.hypot(dx, dy) || 1;
  for (const k of [8, 6, 4]) {
    const tx = Math.floor(a.x + (dx / len) * k + (sim.rand() - 0.5) * 3);
    const ty = Math.floor(a.y + (dy / len) * k + (sim.rand() - 0.5) * 3);
    if (W.walkable(tx, ty) && W.fire[W.idx(tx, ty)] === 0 && act(sim, a, "flee", tx, ty, 5, {}, doing)) return true;
  }
  return false;
}

// ---------- running an action ----------
function speedOf(a) {
  const base = a.age < 14 ? 0.28 : a.age >= 62 ? 0.24 : 0.33;
  const k = a.action && a.action.kind;
  return base * (k === "flee" || k === "firefight" || k === "fight" ? 1.6 : 1) * (a.sick ? 0.8 : 1);
}

function runAction(sim, a, dt) {
  const ac = a.action;
  if (ac.phase === "walk") {
    if (ac.kind === "visit" || ac.kind === "fight") {
      const t = ac.kind === "visit" ? sim.agentById(ac.data.target) : sim.animals.find((n) => n.id === ac.data.target);
      if (!t) return endAction(sim, a);
      if (dist(t.x, t.y, ac.tx + 0.5, ac.ty + 0.5) > 3 && (ac.data.tries = (ac.data.tries || 0) + dt) > 6) {
        ac.data.tries = 0;
        const p = sim.world.findPath(Math.floor(a.x), Math.floor(a.y), Math.floor(t.x), Math.floor(t.y));
        if (!p) return endAction(sim, a);
        a.path = p;
        ac.tx = Math.floor(t.x);
        ac.ty = Math.floor(t.y);
      }
      if (ac.kind === "visit" && dist(t.x, t.y, a.x, a.y) < 1.6) {
        a.path = [];
      }
    }
    moveAlong(sim, a, dt);
    if (a.action !== ac) return;
    if (!a.path.length) {
      ac.phase = "do";
      arrive(sim, a);
    } else if (sim.time - ac.t0 > 420) endAction(sim, a);
    return;
  }
  a.walk = 0;
  ac.timer -= dt;
  tick(sim, a, dt);
  if (a.action === ac && ac.timer <= 0) finish(sim, a);
}

function moveAlong(sim, a, dt) {
  const W = sim.world;
  let budget = speedOf(a) * dt;
  while (budget > 0 && a.path.length) {
    const p = a.path[0];
    if (!W.walkable(p.x, p.y)) {
      a.path = [];
      a.action = null;
      return;
    }
    const tx = p.x + 0.5;
    const ty = p.y + 0.5;
    const dx = tx - a.x;
    const dy = ty - a.y;
    const d = Math.hypot(dx, dy);
    const c = W.cost(W.idx(Math.floor(a.x), Math.floor(a.y)));
    const step = budget / c;
    if (Math.abs(dx) > 0.01) a.facing = dx > 0 ? 1 : -1;
    if (d <= step) {
      a.x = tx;
      a.y = ty;
      a.path.shift();
      budget -= d * c;
    } else {
      a.x += (dx / d) * step;
      a.y += (dy / d) * step;
      budget = 0;
    }
  }
  a.walk += dt;
}

function endAction(sim, a) {
  a.action = null;
  a.path = null;
}

function arrive(sim, a) {
  const ac = a.action;
  if (ac.kind === "visit") {
    const t = sim.agentById(ac.data.target);
    if (t && !t.convo && dist(t.x, t.y, a.x, a.y) < 2.5 && !(t.action && t.action.kind === "sleep" && t.action.phase === "do")) {
      endAction(sim, a);
      startConversation(sim, a, t, "visit");
    }
  }
}

function tick(sim, a, dt) {
  const ac = a.action;
  const W = sim.world;
  const n = a.needs;
  const v = sim.villageById(a.village);
  const wf = traitVal(a, "work") * (a.happy > 30 ? 1 : 0.7) * (a.sick ? 0.5 : 1);
  switch (ac.kind) {
    case "sleep":
      if (n.energy >= 99 && sim.hour >= 5 && sim.hour < 21) ac.timer = 0;
      break;
    case "farm": {
      const f = sim.buildingById(ac.data.bid);
      if (!f) return endAction(sim, a);
      f.growth += dt * 0.075 * (0.7 + a.skills.farming * 0.08) * wf * (sim.weather.kind === "rain" ? 1.5 : 1);
      if (f.growth >= 100) {
        f.growth = 0;
        a.carry = { type: "food", n: Math.round(26 + a.skills.farming * 2.5) };
        a.skills.farming = Math.min(10, a.skills.farming + 0.15);
        ac.timer = 0;
      }
      break;
    }
    case "build": {
      const b = sim.buildingById(ac.data.bid);
      if (!b || b.done) return endAction(sim, a);
      if (!b.funded) {
        const cost = BUILDINGS[b.type].cost;
        if (v && Object.entries(cost).every(([k, c]) => v.stock[k] >= c)) {
          for (const [k, c] of Object.entries(cost)) v.stock[k] -= c;
          b.funded = true;
        } else {
          a.thought = `We need more ${Object.entries(cost).filter(([k, c]) => !v || v.stock[k] < c).map(([k]) => k).join(" and ")} for ${b.type === "house" ? "the house" : b.name}.`;
          endAction(sim, a);
          const missing = Object.entries(cost).find(([k, c]) => !v || v.stock[k] < c);
          if (missing && missing[0] !== "gold") gather(sim, a, missing[0] === "wood" ? "wood" : "stone");
          return;
        }
      }
      b.progress += dt * (0.8 + a.skills.building * 0.1) * wf;
      if (b.progress >= BUILDINGS[b.type].work) {
        sim.finishBuilding(b);
        a.skills.building = Math.min(10, a.skills.building + 0.3);
        remember(sim, a, `I helped finish ${b.type === "house" ? "a new house" : b.name}.`, 6, "work");
        if (a.goal && a.goal.bid === b.id) a.goal = null;
        if (a.help === b.id) a.help = null;
        endAction(sim, a);
      }
      break;
    }
    case "workplace": {
      const b = sim.buildingById(ac.data.bid);
      if (!b) return endAction(sim, a);
      b.open = sim.time + 90;
      if (a.job === "merchant" && v) v.stock.gold += dt * 0.025 * (0.6 + a.skills.social * 0.08);
      if (a.job === "healer")
        for (const o of sim.agents)
          if (o.sick && dist(o.x, o.y, a.x, a.y) < 4 && sim.rand() < dt * 0.02) {
            o.sick = false;
            remember(sim, o, `${a.name} cured my fever.`, 7, "life");
            remember(sim, a, `I cured ${o.name}.`, 5, "work");
          }
      if (a.job === "priest") for (const o of sim.agents) if (o !== a && dist(o.x, o.y, a.x, a.y) < 4 && !o.buffs.some((b2) => b2.kind === "calm")) o.buffs.push({ kind: "calm", until: sim.time + 360 });
      a.skills[JOBS[a.job].skill] = Math.min(10, (a.skills[JOBS[a.job].skill] || 0) + dt * 0.0006);
      break;
    }
    case "socialize":
    case "party": {
      const b = ac.data.bid != null && sim.buildingById(ac.data.bid);
      const open = b && b.open > sim.time;
      n.fun = Math.min(100, n.fun + dt * (ac.kind === "party" ? 0.25 : open ? 0.18 : 0.1));
      n.social = Math.min(100, n.social + dt * 0.04);
      if (ac.kind === "party") {
        const p = sim.parties.find((x) => x.fact === ac.data.fact);
        if (p && !p.guests.includes(a.id)) p.guests.push(a.id);
        if (p && (p.over || sim.time > p.end)) ac.timer = 0;
      }
      break;
    }
    case "learn": {
      const teacher = sim.agents.some((o) => o.job === "teacher" && o.action && o.action.kind === "workplace" && o.action.data.bid === ac.data.bid && o.action.phase === "do");
      a.skills.learning = Math.min(10, a.skills.learning + dt * (teacher ? 0.004 : 0.0015));
      const s = pick(sim.rand, ["farming", "building", "social", "woodcut", "mining"]);
      a.skills[s] = Math.min(10, a.skills[s] + dt * (teacher ? 0.0015 : 0.0005));
      break;
    }
    case "idle":
      n.fun = Math.min(100, n.fun + dt * (hasTrait(a, "shy") ? 0.1 : 0.04));
      break;
    case "explore":
      n.fun = Math.min(100, n.fun + dt * 0.12);
      break;
    case "firefight": {
      const i = ac.data.i;
      if (W.fire[i] <= 0) {
        ac.timer = 0;
        break;
      }
      const well = sim.buildings.some((b) => b.type === "well" && b.done && dist(b.x, b.y, a.x, a.y) < 8);
      W.fire[i] -= dt * (well ? 7 : 3.5);
      if (W.fire[i] <= 0) {
        W.fire[i] = 0.01;
        ac.timer = 0;
        remember(sim, a, "I helped put out a fire.", 5, "event");
      }
      break;
    }
    case "fight": {
      const w = sim.animals.find((x) => x.id === ac.data.target);
      if (!w || w.hp <= 0) return endAction(sim, a);
      const d = dist(w.x, w.y, a.x, a.y);
      if (d > 1.4) {
        ac.data.repath -= dt;
        if (ac.data.repath <= 0 || !a.path || !a.path.length) {
          ac.data.repath = 4;
          a.path = sim.world.findPath(Math.floor(a.x), Math.floor(a.y), Math.floor(w.x), Math.floor(w.y)) || [];
          if (!a.path.length && d > 3) return endAction(sim, a);
        }
        moveAlong(sim, a, dt);
        if (!a.action) return;
      } else {
        ac.data.hit -= dt;
        if (ac.data.hit <= 0) {
          ac.data.hit = 6;
          w.hp -= (8 + a.skills.fighting * 1.5) * (a.job === "guard" ? 1.5 : 1);
          a.skills.fighting = Math.min(10, a.skills.fighting + 0.2);
          sim.fx.push({ kind: "float", x: w.x, y: w.y - 0.8, text: "💥", t0: Date.now() });
          if (w.hp <= 0) {
            sim.animals = sim.animals.filter((x) => x !== w);
            a.buffs.push({ kind: "proud", until: sim.time + 1440 });
            sim.addFact("hero", `${a.name} fought off a wolf near ${sim.describePlace(a.x, a.y)}`, { x: a.x, y: a.y, radius: 7, about: [a.id], imp: 7, icon: "🛡️", toast: true });
            remember(sim, a, "I killed a wolf with my own hands!", 8, "event");
            return endAction(sim, a);
          }
        }
      }
      if (a.health < 25) return flee(sim, a, w.x, w.y, "Retreating, badly hurt!");
      break;
    }
  }
}

function finish(sim, a) {
  const ac = a.action;
  const W = sim.world;
  const v = sim.villageById(a.village);
  a.action = null;
  a.path = null;
  switch (ac.kind) {
    case "eat":
      if (v && v.stock.food >= 1) {
        v.stock.food -= 1;
        a.needs.hunger = Math.min(100, a.needs.hunger + 55);
        const b = sim.buildingById(ac.data.place);
        if (b && b.type === "tavern" && b.open > sim.time) a.needs.fun = Math.min(100, a.needs.fun + 12);
      } else a.thought = "The store was empty when I got there.";
      break;
    case "forage":
      if (W.flora[ac.data.i] === F.BUSH) {
        W.setFlora(ac.data.i, F.BUSH_EMPTY);
        a.needs.hunger = Math.min(100, a.needs.hunger + 30);
        remember(sim, a, "I had to eat wild berries; the store was empty.", 3, "obs");
      }
      break;
    case "hunt": {
      const s = sim.animals.find((n) => n.id === ac.data.target);
      if (s && dist(s.x, s.y, a.x, a.y) < 2.5) {
        sim.animals = sim.animals.filter((n) => n !== s);
        a.carry = { type: "food", n: 15 };
        a.needs.hunger = Math.min(100, a.needs.hunger + 30);
        remember(sim, a, "I hunted a sheep. Poor thing, but we were hungry.", 4, "work");
      }
      break;
    }
    case "chop":
      if (W.flora[ac.data.i] === F.TREE) {
        W.setFlora(ac.data.i, F.STUMP);
        a.carry = { type: "wood", n: Math.round(3 + a.skills.woodcut / 3) };
        a.skills.woodcut = Math.min(10, a.skills.woodcut + 0.1);
        a.work++;
      }
      break;
    case "mine":
      a.carry = { type: "stone", n: Math.round(2 + a.skills.mining / 3) };
      a.skills.mining = Math.min(10, a.skills.mining + 0.1);
      a.work++;
      break;
    case "deliver":
      if (a.carry && v) {
        v.stock[a.carry.type] += a.carry.n;
        sim.fx.push({ kind: "float", x: a.x, y: a.y - 1, text: `+${a.carry.n} ${a.carry.type === "food" ? "🍞" : a.carry.type === "wood" ? "🪵" : "🪨"}`, t0: Date.now() });
      }
      a.carry = null;
      break;
    case "heal": {
      const healer = sim.agents.find((o) => o.job === "healer" && o.village === a.village && o.action && o.action.kind === "workplace" && o.action.data.bid === ac.data.bid);
      if (healer && a.sick && chance(sim.rand, 0.8)) {
        a.sick = false;
        remember(sim, a, `${healer.name} cured me at the clinic.`, 7, "life");
      }
      break;
    }
    case "explore": {
      const place = sim.describePlace(a.x, a.y);
      remember(sim, a, pick(sim.rand, [`I explored ${place}. It was peaceful.`, `I found a quiet spot in ${place}.`, `I wandered all the way to ${place}.`]), 3, "obs");
      break;
    }
  }
  if (a.carry && ac.kind !== "deliver") deliver(sim, a);
}

// ---------- nightly reflection (Smallville style) ----------
export function reflect(sim, a) {
  if (a.age < 5) return;
  const out = [];
  const bf = bestFriend(sim, a);
  if (bf && bf.id !== a.lastBest) {
    out.push(`I feel closest to ${bf.name} these days.`);
    a.lastBest = bf.id;
  }
  const rv = worstRival(sim, a);
  if (rv && rv.id !== a.lastRival) {
    out.push(`${rv.name} really gets on my nerves.`);
    a.lastRival = rv.id;
  }
  const v = sim.villageById(a.village);
  if (v) {
    const pop = sim.members(v).length;
    if (v.stock.food < pop * 3) out.push("I'm worried we'll run out of food.");
    if (sim.agents.filter((o) => o.village === a.village && o.home == null).length > 1 && a.home == null) out.push("I wish I had a home of my own.");
  }
  if (a.happy > 75) out.push(pick(sim.rand, ["Today was a good day.", "Life in the village is sweet.", "I'm grateful for my friends."]));
  else if (a.happy < 35) out.push(pick(sim.rand, ["I've been feeling low lately.", "Nothing seems to go right.", "I need a change."]));
  const today = a.mem.filter((m) => sim.time - m.t < 1440 && m.imp >= 7 && m.kind !== "reflect");
  if (today.length) {
    const t = today[today.length - 1].text.replace(/ I saw it happen\.$/, "").replace(/\.$/, "");
    out.push(`I keep thinking about today. ${t}.`);
  }
  const job = JOBS[a.job];
  if (job && job.skill && a.skills[job.skill] > 6 && !a.mem.some((m) => m.kind === "reflect" && m.text.includes("good at"))) out.push(`I'm getting really good at ${job.skill === "woodcut" ? "chopping wood" : job.skill}.`);
  if (!out.length) return;
  const text = pick(sim.rand, out);
  remember(sim, a, text, 6, "reflect");
  a.thought = text;
}

export function dailyAgent(sim, a) {
  const was = a.age - 1440 / YEAR;
  if (was < 14 && a.age >= 14) {
    remember(sim, a, "I'm all grown up now. Time to find work.", 9, "life");
    sim.event(`${a.name} ${a.last} has grown up.`, "🎓", { x: a.x, y: a.y });
    a.job = "idle";
  }
  if (a.age > 68 && chance(sim.rand, (a.age - 68) * 0.012)) {
    sim.killAgent(a, "passed away peacefully of old age");
    return;
  }
}
