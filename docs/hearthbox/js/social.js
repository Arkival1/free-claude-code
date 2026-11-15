// Relationships, memories and who-knows-what.
import { clamp } from "./rng.js";

export function rel(a, id) {
  return a.rel[id] || (a.rel[id] = { aff: 0, n: 0, last: -1e9 });
}
export function aff(a, b) {
  const r = a.rel[b.id];
  return r ? r.aff : 0;
}
export function addAff(a, b, d) {
  const r = rel(a, b.id);
  r.aff = clamp(r.aff + d, -100, 100);
}
export function isFamily(a, b) {
  return (
    a.partner === b.id ||
    a.parents.includes(b.id) ||
    b.parents.includes(a.id) ||
    a.parents.some((p) => b.parents.includes(p))
  );
}
export function relLabel(a, b) {
  if (a.partner === b.id) return "Partner";
  if (a.parents.includes(b.id)) return "Parent";
  if (b.parents.includes(a.id)) return "Child";
  if (a.parents.some((p) => b.parents.includes(p))) return "Sibling";
  const v = aff(a, b);
  if (v >= 55) return "Best friend";
  if (v >= 25) return "Friend";
  if (v <= -50) return "Enemy";
  if (v <= -20) return "Rival";
  return "Acquaintance";
}
export const hasTrait = (a, t) => a.traits.includes(t);
export const traitVal = (a, key, def = 1) => a.traits.reduce((v, t) => v * (TRAIT_CACHE[t]?.[key] ?? 1), def);
let TRAIT_CACHE = {};
export function setTraitTable(t) {
  TRAIT_CACHE = t;
}

export function remember(sim, a, text, imp = 3, kind = "obs") {
  a.mem.push({ t: sim.time, text, imp, kind });
  if (a.mem.length > 70) {
    // Forget the least important old memory.
    let wi = 0;
    let ws = Infinity;
    for (let i = 0; i < a.mem.length - 10; i++) {
      const m = a.mem[i];
      const score = m.imp * 2 - (sim.time - m.t) / 720;
      if (score < ws) {
        ws = score;
        wi = i;
      }
    }
    a.mem.splice(wi, 1);
  }
}

export function knows(a, factId) {
  return a.knowsSet.has(factId);
}

// An agent learns a fact by seeing it, being told, or being part of it ("quiet").
// Returns true if it was new. For party invitations, going=true/false decides attendance.
export function learn(sim, a, fact, how = "saw", from = null, going = undefined) {
  if (!fact || a.knowsSet.has(fact.id) || !a.alive) return false;
  a.knowsSet.add(fact.id);
  a.knows.push(fact.id);
  if (a.knows.length > 120) {
    const old = a.knows.shift();
    a.knowsSet.delete(old);
    delete a.src[old];
  }
  if (from) a.src[fact.id] = from.id;
  if (how !== "quiet") {
    const text =
      how === "heard" && from
        ? `${from.name} told me ${fact.kind === "idea" ? `that ${fact.text}` : fact.text}.`
        : how === "saw"
          ? `${fact.text.charAt(0).toUpperCase() + fact.text.slice(1)}. I saw it happen.`
          : `${fact.text.charAt(0).toUpperCase() + fact.text.slice(1)}.`;
    remember(sim, a, text, fact.imp, how === "heard" ? "heard" : "event");
  }
  fact.knowers = (fact.knowers || 0) + 1;
  if (fact.kind === "party" && how !== "quiet") {
    if (going === undefined) decideParty(sim, a, fact);
    else if (going && !a.goingTo.includes(fact.id)) a.goingTo.push(fact.id);
  }
  return true;
}

export function partyWant(sim, a, fact) {
  if (!fact) return 0;
  const host = sim.agentById(fact.data.host);
  let want = 0.55;
  if (host) want += aff(a, host) / 150;
  if (hasTrait(a, "friendly") || hasTrait(a, "cheerful")) want += 0.2;
  if (hasTrait(a, "shy")) want -= 0.25;
  if (hasTrait(a, "gossip")) want += 0.15;
  return want;
}

export function decideParty(sim, a, fact) {
  a.goingTo = a.goingTo || [];
  if (sim.rand() < partyWant(sim, a, fact) && !a.goingTo.includes(fact.id)) a.goingTo.push(fact.id);
}

export function bestFriend(sim, a) {
  let best = null;
  let bv = 15;
  for (const id in a.rel) {
    const o = sim.agentById(+id);
    if (!o || !o.alive) continue;
    if (a.rel[id].aff > bv) {
      bv = a.rel[id].aff;
      best = o;
    }
  }
  return best;
}
export function worstRival(sim, a) {
  let worst = null;
  let wv = -20;
  for (const id in a.rel) {
    const o = sim.agentById(+id);
    if (!o || !o.alive) continue;
    if (a.rel[id].aff < wv) {
      wv = a.rel[id].aff;
      worst = o;
    }
  }
  return worst;
}
