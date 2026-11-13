// Conversations. Topics come from what villagers really know and feel; saying a
// line changes the world (news spreads, opinions shift, couples form).
import { BUILDINGS, JOBS, TRAITS } from "./data.js";
import { chance, clamp, dist, pick, randInt } from "./rng.js";
import { addAff, aff, hasTrait, isFamily, learn, partyWant, rel, remember } from "./social.js";

const NEWS_KINDS = new Set(["fire", "death", "birth", "couple", "meteor", "built", "destroyed", "wolf", "sick", "bless", "newcomer", "plan", "partydone", "village", "hero", "fight", "breakup"]);
const LABEL = { fire: "the fire", death: "a death", birth: "the new baby", couple: "the new couple", meteor: "the meteor", built: "the new building", destroyed: "the destruction", wolf: "wolves", sick: "the sickness", bless: "the strange light", newcomer: "the newcomer", plan: "building plans", partydone: "the party", village: "the new village", hero: "the wolf fight", fight: "the fistfight" };

// ---------- starting ----------
function canTalk(sim, a) {
  if (!a.alive || a.convo || a.age < 4 || sim.time - a.lastTalk < 40) return false;
  const k = a.action && a.action.kind;
  if (k === "sleep" && a.action.phase === "do") return false;
  return k !== "flee" && k !== "fight" && k !== "firefight";
}

export function maybeStartConversations(sim) {
  const list = sim.agents.filter((a) => canTalk(sim, a));
  for (let i = 0; i < list.length; i++) {
    const a = list[i];
    if (a.convo) continue;
    for (let j = i + 1; j < list.length; j++) {
      const b = list[j];
      if (b.convo) continue;
      if (Math.abs(a.x - b.x) > 2 || Math.abs(a.y - b.y) > 2) continue;
      if (chance(sim.rand, talkChance(sim, a, b))) {
        startConversation(sim, a, b, "met");
        break;
      }
    }
  }
}

function talkChance(sim, a, b) {
  const r = a.rel[b.id];
  let p = 0.07 * Math.sqrt(socialOf(a) * socialOf(b));
  p *= 1 + (200 - a.needs.social - b.needs.social) / 150;
  if (r && sim.time - r.last < 200) p *= 0.12;
  const v = aff(a, b);
  if (v > 30) p *= 1.5;
  if (v < -30) p *= 0.8;
  const busy = (o) => o.action && o.action.phase === "do" && ["farm", "chop", "mine", "build", "workplace", "learn"].includes(o.action.kind);
  if (busy(a) || busy(b)) p *= 0.3;
  const social = (o) => o.action && (o.action.kind === "party" || o.action.kind === "socialize");
  if (social(a) || social(b)) p *= 2.5;
  if (a.buffs.some((x) => x.kind === "angry")) p *= 2;
  return Math.min(0.9, p);
}
const socialOf = (a) => a.traits.reduce((v, t) => v * (TRAITS[t].social || 1), 1);

export function startConversation(sim, a, b, reason) {
  const c = { id: sim.id(), a: a.id, b: b.id, lines: [], queue: buildQueue(sim, a, b), next: sim.time + 1, t0: sim.time, reason, topics: [] };
  a.convo = b.convo = c.id;
  a.facing = b.x > a.x ? 1 : -1;
  b.facing = -a.facing;
  sim.convos.push(c);
  if (sim.aiRequest) sim.aiRequest(c);
  return c;
}

export function endConversation(sim, c) {
  if (!c || c.ended) return;
  c.ended = true;
  sim.convos = sim.convos.filter((x) => x !== c);
  const a = sim.agentById(c.a);
  const b = sim.agentById(c.b);
  sim.stats.talks++;
  for (const [s, o] of [[a, b], [b, a]]) {
    if (!s) continue;
    s.convo = null;
    s.lastTalk = sim.time;
    if (!o || c.lines.length < 2) continue;
    const r = rel(s, o.id);
    r.n++;
    r.last = sim.time;
    s.needs.social = Math.min(100, s.needs.social + 10 + c.lines.length * 4);
    s.needs.fun = Math.min(100, s.needs.fun + 4);
    let d = 2 + (warmth(s) + warmth(o)) / 2 + (s.happy - 50) / 30;
    for (const t of s.traits) if (o.traits.includes(t)) d += 2;
    if (c.argued) d -= 6;
    addAff(s, o, d);
    const topics = [...new Set(c.topics)].slice(0, 3);
    remember(sim, s, `Talked with ${o.name}${topics.length ? " about " + listJoin(topics) : ""}.`, c.argued ? 5 : 3, "talk");
  }
}
const warmth = (a) => a.traits.reduce((v, t) => v + (TRAITS[t].warmth || 0), 0) + (a.buffs.some((x) => x.kind === "angry") ? -6 : 0);

export function updateConversations(sim, dt) {
  for (const c of [...sim.convos]) {
    const a = sim.agentById(c.a);
    const b = sim.agentById(c.b);
    if (!a || !b || dist(a.x, a.y, b.x, b.y) > 4) {
      endConversation(sim, c);
      continue;
    }
    if (sim.time < c.next) continue;
    if (c.ai === "pending" && c.lines.length >= 1 && Date.now() - c.aiT < 25000) {
      c.next = sim.time + 1;
      continue;
    }
    if (c.aiLines && !c.aiUsed) {
      // A model wrote the words: settle the game effects now, then speak its lines.
      c.aiUsed = true;
      for (const item of c.queue) if (!item.reply) applyTopic(sim, c, item, sim.agentById(item.s), sim.agentById(item.l));
      c.queue = c.aiLines.map((l) => ({ k: "ai", s: l.s, l: l.s === c.a ? c.b : c.a, text: l.text }));
    }
    const item = c.queue.shift();
    if (!item) {
      endConversation(sim, c);
      continue;
    }
    const s = sim.agentById(item.s);
    const l = sim.agentById(item.l);
    let text = item.text;
    if (!text) {
      if (!item.reply) applyTopic(sim, c, item, s, l);
      text = lineFor(sim, c, item, s, l);
    }
    if (text) speak(sim, c, s, l, text);
    c.next = sim.time + randInt(sim.rand, 7, 12);
  }
}

function speak(sim, c, s, l, text) {
  const line = { t: sim.time, c: c.id, s: s.id, l: l.id, sn: s.name, ln: l.name, text };
  c.lines.push(line);
  sim.feed.push(line);
  if (sim.feed.length > 500) sim.feed.shift();
  s.say = { text, t: sim.time };
}

// ---------- topics ----------
function buildQueue(sim, a, b) {
  const q = [{ k: "greet", s: a.id, l: b.id }, { k: "greet", s: b.id, l: a.id, reply: true }];
  const cands = [...candidates(sim, a, b), ...candidates(sim, b, a)].map((c) => ({ ...c, w: c.w * (0.6 + sim.rand() * 0.8) }));
  cands.sort((p, q2) => q2.w - p.w);
  const n = 2 + (hasTrait(a, "gossip") || hasTrait(b, "gossip") ? 1 : 0) + (sim.rand() < 0.4 ? 1 : 0) - (hasTrait(a, "shy") && hasTrait(b, "shy") ? 1 : 0);
  const used = new Set();
  let taken = 0;
  for (const t of cands) {
    const key = t.k + ":" + (t.d.fact || t.d.c || "");
    if (used.has(key) || used.has(t.k + t.s) || taken >= n) continue;
    used.add(key);
    used.add(t.k + t.s);
    decide(sim, t);
    q.push({ k: t.k, s: t.s, l: t.l, d: t.d });
    q.push({ k: t.k, s: t.l, l: t.s, d: t.d, reply: true });
    taken++;
    if (t.k === "argue" && t.d.fight) break;
  }
  q.push({ k: "bye", s: a.id, l: b.id }, { k: "bye", s: b.id, l: a.id, reply: true });
  return q;
}

function candidates(sim, s, l) {
  const out = [];
  const add = (k, w, d = {}) => out.push({ k, w, s: s.id, l: l.id, d });
  const gossipy = hasTrait(s, "gossip") ? 1.7 : 1;
  // Parties.
  for (const p of sim.parties) {
    if (p.over || p.at < sim.time - 60) continue;
    if (s.knowsSet.has(p.fact) && !l.knowsSet.has(p.fact)) add("party", p.host === s.id ? 16 : 9 * gossipy, { fact: p.fact });
  }
  // A planted idea, then news.
  for (let i = s.knows.length - 1, seen = 0; i >= 0 && seen < 30; i--, seen++) {
    const f = sim.facts.get(s.knows[i]);
    if (!f || l.knowsSet.has(f.id)) continue;
    if (f.kind === "idea") add("idea", (s.idea === f.id ? 11 : 6) * gossipy, { fact: f.id });
    else if (NEWS_KINDS.has(f.kind) && sim.time - f.t < 3 * 1440) add("news", f.imp * (1 - (sim.time - f.t) / (3.5 * 1440)) * gossipy, { fact: f.id });
  }
  // Gossip about someone else.
  for (const id in s.rel) {
    const o = sim.agentById(+id);
    if (!o || o === l || o === s) continue;
    const v = s.rel[id].aff;
    if (Math.abs(v) >= 30) add("gossip", (Math.abs(v) / 25) * gossipy * (hasTrait(s, "kind") && v < 0 ? 0.3 : 1), { c: o.id, v });
  }
  const v = aff(s, l);
  const angry = s.buffs.some((x) => x.kind === "angry");
  if (v < -25 || angry) add("argue", angry ? 14 : 4 + -v / 12, {});
  const adult = (o) => o.age >= 18;
  if (adult(s) && adult(l) && !isFamily(s, l) && s.partner == null && l.partner == null) {
    if (s.crush === l.id) add("romance", 14);
    else if (v >= (hasTrait(s, "romantic") ? 40 : 55)) add("romance", 6);
  }
  if (s.goal && s.goal.kind === "build" && l.age >= 14 && l.help !== s.goal.bid) {
    const b = sim.buildingById(s.goal.bid);
    if (b && !b.done) add("help", 9, { bid: b.id });
  }
  const worst = Object.entries(s.needs).sort((p, q) => p[1] - q[1])[0];
  if (worst[1] < 30) add("need", 4, { need: worst[0] });
  const vill = sim.villageById(s.village);
  if (vill && s.age >= 12) add("village", 2.2, {});
  if (s.age >= 4) add("work", 2, {});
  add("ask", l.sick || l.happy < 35 || l.buffs.some((x) => x.kind === "grief") ? 5 : 1.5, {});
  add("weather", 0.8, {});
  const refl = [...s.mem].reverse().find((m) => m.kind === "reflect" && sim.time - m.t < 1440);
  if (refl) add("reflect", 2.5, { text: refl.text });
  if ((hasTrait(s, "kind") || hasTrait(s, "friendly")) && v > 10) add("compliment", 2, {});
  if (s.children.some((id) => sim.agentById(id)) || s.partner) add("family", 1.5, {});
  return out;
}

// Decide outcomes up front, so a model can be told what happens.
function decide(sim, t) {
  const s = sim.agentById(t.s);
  const l = sim.agentById(t.l);
  if (t.k === "romance") t.d.yes = aff(l, s) >= 38 || (hasTrait(l, "romantic") && aff(l, s) >= 25);
  if (t.k === "party") t.d.going = sim.rand() < partyWant(sim, l, sim.facts.get(t.d.fact));
  if (t.k === "help") t.d.yes = aff(l, s) > 15 || hasTrait(l, "kind") || hasTrait(l, "hardworking");
  if (t.k === "argue") t.d.fight = aff(s, l) < -50 && aff(l, s) < -30 && sim.rand() < 0.3;
  if (t.k === "idea") t.d.agree = aff(l, s) > 20 || hasTrait(l, "curious") || hasTrait(l, "gossip");
}

function applyTopic(sim, c, item, s, l) {
  const d = item.d || {};
  const f = d.fact && sim.facts.get(d.fact);
  switch (item.k) {
    case "party":
      if (f) learn(sim, l, f, "heard", s, d.going);
      c.topics.push(`${sim.nameOf(f ? f.data.host : s.id)}'s party`);
      break;
    case "idea":
    case "news":
      if (f) {
        learn(sim, l, f, "heard", s);
        c.topics.push(f.kind === "idea" ? "an idea" : LABEL[f.kind] || "the news");
        if (f.kind === "death" && aff(l, { id: f.data.who }) > 25) l.buffs.push({ kind: "sad", until: sim.time + 720 });
        if (f.kind === "idea" && d.agree) addAff(l, s, 3);
      }
      break;
    case "gossip": {
      const o = sim.agentById(d.c);
      if (o) {
        const trust = aff(l, s) > 0 ? 0.2 : 0.06;
        addAff(l, o, d.v * trust);
        c.topics.push(o.name);
      }
      break;
    }
    case "romance":
      c.topics.push("feelings");
      if (d.yes) sim.makeCouple(s, l);
      else {
        addAff(s, l, -6);
        remember(sim, s, `I told ${l.name} how I feel. They turned me down.`, 8, "life");
        s.buffs.push({ kind: "sad", until: sim.time + 720 });
        if (s.crush === l.id) s.crush = null;
      }
      break;
    case "argue":
      c.argued = true;
      c.topics.push("an argument");
      addAff(s, l, -5);
      addAff(l, s, -8);
      if (d.fight) {
        s.health -= 10;
        l.health -= 10;
        sim.addFact("fight", `${s.name} and ${l.name} got into a fistfight`, { x: s.x, y: s.y, radius: 6, about: [s.id, l.id], imp: 7, icon: "🥊", toast: true });
      }
      break;
    case "help":
      c.topics.push("building");
      if (d.yes) {
        l.help = d.bid;
        l.planDay = -1;
        remember(sim, l, `I promised ${s.name} I'd help build.`, 5, "plan");
      }
      break;
    case "compliment":
      addAff(l, s, 3);
      break;
    case "work":
      c.topics.push("work");
      break;
    case "village":
      c.topics.push("the village");
      break;
    case "need":
      c.topics.push(d.need === "hunger" ? "food" : d.need === "energy" ? "being tired" : "feeling lonely");
      break;
  }
}

// ---------- words ----------
function lineFor(sim, c, item, s, l) {
  const r = sim.rand;
  const P = (arr) => pick(r, arr);
  const d = item.d || {};
  const f = d.fact && sim.facts.get(d.fact);
  const L = l.name;
  const v = aff(s, l);
  const angry = s.buffs.some((x) => x.kind === "angry");
  const grumpy = hasTrait(s, "grumpy") || angry;
  const h = sim.hour;
  const tod = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Evening";
  const vill = sim.villageById(s.village);
  const pop = vill ? sim.members(vill).length : 0;
  switch (item.k) {
    case "greet":
      if (item.reply) {
        if (s.sick) return P(["Not great... I think I'm coming down with something.", `Hi ${L}. I feel awful, honestly.`]);
        if (s.buffs.some((x) => x.kind === "grief")) return P(["Hello... it's been a hard few days.", `Hi ${L}. I'm getting by.`]);
        if (angry) return P(["WHAT.", `Oh, it's YOU, ${L}.`]);
        if (aff(s, l) < -25) return P([`...${L}.`, "Hmph.", "What do you want?"]);
        if (s.partner === l.id) return P(["Hi, you.", "There you are!", `Hey ${L} ❤️`]);
        if (s.needs.energy < 25) return P(["Tired, but alive.", `Hey ${L}. Sorry, I'm half asleep.`]);
        if (s.needs.hunger < 30) return P(["Hungry, mostly! How are you?", `Hi ${L}. My stomach's growling.`]);
        if (s.happy > 72) return P([`Doing great, thanks ${L}!`, "Wonderful, actually! You?", `Hi ${L}! What a day.`]);
        if (s.happy < 35) return P(["Honestly? Not my best day.", `Hi ${L}. I've been better.`]);
        if (hasTrait(s, "shy")) return P(["Oh! H-hi.", `Um, hello ${L}.`]);
        return P([`Hi ${L}! Not bad, you?`, `Hey ${L}.`, `${tod}, ${L}.`, "Oh, hello there!"]);
      }
      if (angry) return P([`Out of my way, ${L}!`, `What are YOU looking at, ${L}?`]);
      if (s.partner === l.id) return P(["Hey, love.", `There you are, ${L}!`, "Hi sweetheart, how's your day?"]);
      if (s.parents.includes(l.id)) return P(["Hi! Guess what I did today!", `Hi ${s.parents[0] === l.id ? "Mum" : "Dad"}!`]);
      if (v > 40) return P([`${L}! Good to see you.`, `Hey ${L}, just the person I wanted to see.`, `${tod}, ${L}! How are you?`]);
      if (v < -25) return P([`Oh. ${L}.`, `Hmph. Hello, ${L}.`, `${L}. Fancy seeing you.`]);
      if (grumpy) return P([`What is it, ${L}?`, `${tod}. If you can call it good.`]);
      if (hasTrait(s, "shy")) return P([`Oh, h-hi ${L}.`, `Um, hello ${L}.`]);
      return P([`${tod}, ${L}.`, `Hello ${L}!`, `Hi ${L}, how's it going?`, `Oh hey, ${L}.`]);

    case "party": {
      const p = sim.parties.find((x) => x.fact === d.fact);
      if (!p) return null;
      const when = relWhen(sim, p.at);
      if (item.reply) {
        const host = sim.agentById(p.host);
        if (!d.going) return P(host && aff(s, host) < -20 ? [`A party with ${host.name}? No thanks.`] : ["Hmm, I'll think about it.", "Maybe. I'm not really a party person.", "I don't think I can make it, sorry."]);
        return P(["I'd love to! I'll be there.", "Count me in!", "A party? Wouldn't miss it!", `Ooh, ${when}? I'll bring snacks.`]);
      }
      if (p.host === s.id) return P([`I'm throwing a party at ${p.place} ${when}! You should come, ${L}.`, `${L}, come to my party at ${p.place} ${when}! There'll be food and music.`, `Big plans: party at ${p.place}, ${when}. Please come!`]);
      return P([`${sim.nameOf(p.host)} is throwing a party at ${p.place} ${when}. Are you going?`, `Did you hear about ${sim.nameOf(p.host)}'s party ${when}? Everyone's going.`, `There's a party at ${p.place} ${when}! ${sim.nameOf(p.host)} is hosting.`]);
    }

    case "idea": {
      if (!f) return null;
      const text = f.data.text;
      if (item.reply) return d.agree ? P(["You might be onto something.", "Huh. I never thought of that.", "You know... I think you're right.", "I'll tell the others!"]) : P(["That sounds like nonsense to me.", "I'm not so sure about that.", "Where do you get these ideas?"]);
      if (f.data.by === s.id) return P([`I've been thinking... ${text}.`, `Can I tell you something, ${L}? I really believe ${text}.`, `Hear me out: ${text}.`]);
      return P([`${sim.nameOf(f.data.by)} keeps saying ${text}. What do you think?`, `So ${sim.nameOf(s.src[f.id] ?? f.data.by)} told me ${text}. Wild, right?`]);
    }

    case "news": {
      if (!f) return null;
      if (item.reply) return newsReaction(sim, f, s, l, P);
      const from = s.src[f.id] != null && s.src[f.id] !== l.id ? sim.nameOf(s.src[f.id]) : null;
      const T = f.text.charAt(0).toUpperCase() + f.text.slice(1);
      const lead = from && chance(r, 0.6) ? `${from} told me ${f.text}.` : null;
      switch (f.kind) {
        case "death":
          return lead || P([`I have sad news... ${f.text}.`, `Did you hear? ${T}.`, `${L}... ${f.text}. I can't stop thinking about it.`]);
        case "birth":
          return lead || P([`Wonderful news: ${f.text}!`, `Have you heard? ${T}!`]);
        case "fire":
          return lead || P([`There was a fire! ${T}.`, `Did you see the smoke? ${T}.`]);
        case "meteor":
          return P([`Did you SEE that? ${T}!`, `The sky fell! ${T}!`, `I'm still shaking. ${T}.`]);
        case "couple":
          return lead || P([`Guess who's in love? ${T}!`, `Have you heard? ${T}!`]);
        case "wolf":
          return P([`Be careful out there. ${T}.`, `Lock your door tonight, ${L}. ${T}.`]);
        case "plan":
          if (f.about.includes(s.id)) {
            const b = sim.buildingById(f.data.bid);
            return b ? `We should build ${aAn(BUILDINGS[b.type].name.toLowerCase())}. I've picked a spot near ${sim.describePlace(b.x, b.y)}!` : `${T}.`;
          }
          return lead || `Did you hear? ${T}.`;
        case "built":
          return P([`Have you seen? ${T}.`, `${T}, finally!`]);
        case "hero":
          return f.about.includes(s.id) ? P(["I fought a wolf yesterday. With my bare hands, nearly!", "A wolf came at me, and I won!"]) : P([`${T}! What a hero.`, lead || `Did you hear? ${T}.`]);
        default:
          return lead || P([`Did you hear? ${T}.`, `Have you heard? ${T}!`, `So... ${f.text}. Can you believe it?`, `Big news: ${f.text}.`]);
      }
    }

    case "gossip": {
      const o = sim.agentById(d.c);
      if (!o) return null;
      const C = o.name;
      if (item.reply) {
        const mine = aff(s, o);
        if (Math.sign(mine) === Math.sign(d.v) && Math.abs(mine) > 15) return d.v > 0 ? P([`I agree! ${C} is a gem.`, `Same here. ${C} is lovely.`]) : P(["Ugh, tell me about it.", `You too? ${C} drives me mad.`]);
        if (Math.abs(mine) > 15) return d.v > 0 ? P([`Really? ${C} has always been a bit much for me.`, `Hmm. I don't trust ${C}.`]) : P([`That's not fair. ${C} means well.`, `Really? I think ${C} is lovely.`]);
        return P([`I don't know ${C} that well.`, "Interesting...", `Huh. I'll keep an eye on ${C}.`]);
      }
      if (d.v > 0) return P([`${C} is wonderful, don't you think?`, `I really like ${C}. Always there when I need help.`, `${C} always makes me laugh.`]);
      return P([`Between you and me, ${C} has been getting on my nerves.`, `Don't tell anyone, but I don't trust ${C}.`, `${C} is so full of themselves lately.`]);
    }

    case "argue":
      if (item.reply) {
        if (d.fight) return P(["That's IT!", "You want a fight? You've got one!"]);
        if (hasTrait(s, "kind") || hasTrait(s, "shy")) return P(["I'm sorry you feel that way.", "W-what did I ever do to you?"]);
        if (hasTrait(s, "brave") || hasTrait(s, "grumpy")) return P(["Say that again, I dare you.", "Back off!", "Likewise, I'm sure."]);
        return P(["Excuse me?!", "Whatever.", "Wow. Okay."]);
      }
      if (angry) return P(["WHAT are you looking at?!", "Everything is YOUR fault!", "I'm sick of all of you!"]);
      return P([`You've got some nerve showing your face, ${L}.`, `I haven't forgotten what you did, ${L}.`, `Stay out of my way, ${L}.`, "Why are you always so annoying?"]);

    case "romance":
      if (item.reply) return d.yes ? P(["I... feel the same way!", "Yes! I was hoping you'd say that.", "I'd love that. ❤️"]) : P(["Oh... I'm flattered, but I just see you as a friend.", `I'm sorry, ${L}. I don't feel that way.`, "Let's just stay friends, okay?"]);
      return P([`${L}, I really like spending time with you. Maybe... more than as friends?`, `Can I be honest? I think I'm falling for you, ${L}.`, `Would you... be with me, ${L}?`]);

    case "help": {
      const b = sim.buildingById(d.bid);
      if (!b) return null;
      if (item.reply) return d.yes ? P(["Sure, I'll lend a hand after work.", "Count me in. Where do I start?"]) : P(["Sorry, I've got my hands full.", "Maybe another time."]);
      return `I'm building ${aAn(BUILDINGS[b.type].name.toLowerCase())} near ${sim.describePlace(b.x, b.y)}. It's ${Math.round((b.progress / BUILDINGS[b.type].work) * 100)}% done. Will you help, ${L}?`;
    }

    case "need": {
      if (item.reply) {
        if (d.need === "hunger") return vill && vill.stock.food > 0 ? `There's ${Math.floor(vill.stock.food)} food at the store. Go grab a bite!` : "The store's empty... we need more farmers.";
        if (d.need === "energy") return P(["Get some rest tonight!", "Go to bed early, you look shattered."]);
        if (d.need === "social") return P(["You can always talk to me.", "I'm here. Let's catch up more often."]);
        const tav = sim.buildings.find((b) => b.village === s.village && b.type === "tavern" && b.done);
        return tav ? `Let's go to ${tav.name} sometime!` : "Want to go exploring later?";
      }
      return {
        hunger: P(["I'm starving. Haven't eaten in ages.", "My stomach won't stop growling."]),
        energy: P(["I'm exhausted. I could sleep for a week.", "I can barely keep my eyes open."]),
        social: P(["I've been so lonely lately. It's nice to talk.", "Nobody's spoken to me all day."]),
        fun: P(["I'm so bored. Nothing ever happens.", "I need some fun in my life."]),
      }[d.need];
    }

    case "village": {
      if (!vill) return null;
      if (item.reply) return P(["We'll manage, we always do.", "Someone should talk to the builders.", "Let's hope the next harvest comes in.", "I've been thinking the same thing."]);
      const homeless = sim.members(vill).filter((o) => o.home == null && o.age >= 14).length;
      const bp = sim.buildings.find((b) => b.village === vill.id && !b.done);
      if (vill.stock.food < pop * 3) return `We only have ${Math.floor(vill.stock.food)} food left for ${pop} people. It worries me.`;
      if (homeless > 0) return `${homeless} of us still don't have a home.`;
      if (bp) return `They're building ${aAn(BUILDINGS[bp.type].name.toLowerCase())} near ${sim.describePlace(bp.x, bp.y)}. ${Math.round((bp.progress / BUILDINGS[bp.type].work) * 100)}% done.`;
      return P([`Have you noticed? There are ${pop} of us in ${vill.name} now!`, `${vill.name} has ${Math.floor(vill.stock.wood)} wood and ${Math.floor(vill.stock.stone)} stone in store. Not bad!`]);
    }

    case "work":
      if (item.reply) return P(["Sounds like hard work!", "Good for you.", "Keep it up!", hasTrait(s, "lazy") ? "Rather you than me." : "We're lucky to have you.", "I could never do that."]);
      return workLine(sim, s, l, P);

    case "ask":
      if (item.reply) {
        if (s.sick) return "I've been feverish. I should see a healer.";
        if (s.buffs.some((x) => x.kind === "grief")) return "I miss them every single day.";
        if (s.needs.energy < 30) return "I barely slept, honestly.";
        if (s.happy < 35) {
          const rv = Object.entries(s.rel).sort((p, q) => p[1].aff - q[1].aff)[0];
          if (rv && rv[1].aff < -30 && sim.agentById(+rv[0])) return `It's ${sim.nameOf(+rv[0])}. They've been awful to me.`;
          if (s.home == null) return "I still don't have a home. It gets to you.";
          if (s.needs.hunger < 35) return "I'm just so hungry all the time.";
          return "I don't know. Everything feels heavy lately.";
        }
        return P(["All good, thanks for asking!", `Busy! ${JOBS[s.job].label} life.`, "Can't complain."]);
      }
      if (l.sick) return `You look pale, ${L}. Are you feeling okay?`;
      if (l.buffs.some((x) => x.kind === "grief")) return `I'm so sorry for your loss, ${L}.`;
      if (l.needs.energy < 30) return `You look tired, ${L}.`;
      if (l.happy < 35) return `You seem down lately, ${L}. What's wrong?`;
      return P([`How's work going, ${L}?`, `How are things at home, ${L}?`, `What have you been up to, ${L}?`]);

    case "weather":
      if (item.reply) return P(["It sure is.", "Mm-hmm.", "You can say that again."]);
      if (sim.weather.kind === "rain") return P(["Lovely weather for ducks, eh?", "This rain won't stop.", "The crops will love this rain."]);
      if (h >= 19) return P(["It's getting late.", "Look at that sunset."]);
      return P(["Beautiful day, isn't it?", "Nice and sunny today.", "Not a cloud in the sky."]);

    case "reflect":
      if (item.reply) return P(["That's very wise.", "I know what you mean.", "Thanks for telling me that."]);
      return `I've been thinking... ${d.text}`;

    case "compliment":
      if (item.reply) return P(["Aw, thank you!", "You're too kind.", "That made my day."]);
      return P([`You always know how to cheer me up, ${L}.`, `I love your laugh, ${L}.`, `You're a good friend, ${L}.`, `Your stories are the best, ${L}.`]);

    case "family": {
      if (item.reply) return P(["Time flies!", "That's so sweet.", "Family is everything."]);
      const kid = s.children.map((id) => sim.agentById(id)).find(Boolean);
      if (kid && chance(r, 0.6)) return `My ${kid.name} is growing up so fast. ${Math.floor(kid.age)} already!`;
      const p = sim.agentById(s.partner);
      return p ? P([`${p.name} made the best stew last night.`, `${p.name} and I are thinking about the future.`]) : "Family is everything, you know?";
    }

    case "bye":
      if (item.reply) return aff(s, l) < -25 || angry ? P(["Good riddance.", "Hmph."]) : P(["Bye!", "See you!", `Later, ${L}.`, "Take care!"]);
      if (c.argued || angry) return P(["Whatever.", "I'm done here."]);
      return P([`See you around, ${L}.`, "I should get going. Bye!", `Take care, ${L}.`, "Well, back to it."]);
  }
  return null;
}

function newsReaction(sim, f, s, l, P) {
  const grumpy = hasTrait(s, "grumpy");
  switch (f.kind) {
    case "death": {
      const who = sim.nameOf(f.data.who);
      if (aff(s, { id: f.data.who }) > 30) return P([`No... not ${who}. I can't believe it.`, `That's heartbreaking. ${who} was a dear friend.`]);
      return grumpy ? "Everyone goes sometime, I suppose." : P(["That's terrible news.", "May they rest in peace.", "Oh no. How awful."]);
    }
    case "birth":
      return grumpy ? "More mouths to feed... but that's sweet, I suppose." : P(["How lovely! A new little one.", "Aww! I'll have to bring them something.", "That's wonderful!"]);
    case "fire":
      return P(["Oh no! Was anyone hurt?", "We need more wells, I keep saying it.", "That's awful. I'll keep an eye out for smoke."]);
    case "meteor":
      return P(["I thought it was the end of the world!", "The gods must be angry with us.", "I felt the ground shake from my bed!"]);
    case "built":
      return grumpy ? "Good. Maybe now they'll build what I asked for." : P(["About time! It looks great.", "I'll have to go and see it."]);
    case "couple":
      return s.crush != null && f.about.includes(s.crush) ? "Oh... I see. Good for them, I guess." : P(["I knew it! They're perfect together.", "Really? Good for them!"]);
    case "wolf":
      return hasTrait(s, "brave") ? "Wolves? Let them come." : P(["I'll lock my door tonight.", "Wolves?! I'm staying inside."]);
    case "sick":
      return P(["I hope they get better soon.", "Keep your distance from them, just in case."]);
    case "destroyed":
      return P(["All that work, gone.", "We'll rebuild. We always do."]);
    case "plan":
      return hasTrait(s, "lazy") ? "Sounds like a lot of work." : P(["Great idea! I'll help.", "About time we built that."]);
    case "bless":
      return P(["A golden light? Are you sure you weren't dreaming?", "The heavens are watching over us!"]);
    case "hero":
      return P(["That's so brave!", "I'm glad nobody got hurt."]);
    default:
      return P(["Really? I had no idea!", "Wow. Thanks for telling me.", "Huh, I hadn't heard that."]);
  }
}

function workLine(sim, s, l, P) {
  const v = sim.villageById(s.village);
  switch (s.job) {
    case "farmer": {
      const f = sim.buildingById(s.workAt);
      if (!f) return "I'm a farmer without a farm. Funny, right?";
      return `The crops at ${f.name} are ${Math.round(f.growth)}% grown. ${sim.weather.kind === "rain" ? "This rain is a blessing." : "Should be a good harvest soon."}`;
    }
    case "woodcutter":
      return `I've chopped ${s.work} loads of wood so far. We've got ${Math.floor(v ? v.stock.wood : 0)} wood in store.`;
    case "miner":
      return `Spent all day in the hills breaking rocks. We have ${Math.floor(v ? v.stock.stone : 0)} stone now.`;
    case "builder": {
      const b = sim.buildings.find((x) => x.village === s.village && !x.done);
      return b ? `We're ${Math.round((b.progress / BUILDINGS[b.type].work) * 100)}% done with ${b.type === "house" ? "the new house" : b.name}.${b.funded ? "" : " We still need materials."}` : "Nothing to build right now, so I'm fixing fences.";
    }
    case "keeper": {
      const t = sim.buildings.find((x) => x.village === s.village && x.type === "tavern" && x.done);
      return t ? `${t.name} was packed last night!` : "I'd love to run a tavern someday.";
    }
    case "merchant":
      return `Trade's ${v && v.stock.gold > 20 ? "booming" : "slow"}. The village has ${Math.floor(v ? v.stock.gold : 0)} gold now.`;
    case "teacher": {
      const kid = sim.agents.find((o) => o.village === s.village && o.age < 14 && o.age >= 5);
      return kid ? `The children are learning fast. ${kid.name} asked me about the stars today.` : "No pupils yet. I'm preparing lessons anyway.";
    }
    case "healer": {
      const n = sim.agents.filter((o) => o.village === s.village && o.sick).length;
      return n ? `${n} ${n === 1 ? "person is" : "people are"} sick right now. I'm doing my best.` : "Everyone's healthy, thank goodness.";
    }
    case "priest":
      return "Come to the temple sometime. It brings peace.";
    case "guard":
      return sim.animals.some((n) => n.kind === "wolf") ? "There are wolves about. I'm keeping watch." : "Quiet watch today. No wolves.";
    case "child":
      return P(["I learned how to count to a hundred!", "Wanna play tag later?", "I found a frog by the water!", "When I grow up I want to be a builder!"]);
    case "elder":
      return P(["When I was young, all this was forest.", "These young folk work too hard.", `I've seen ${Math.floor(s.age)} years. Well, sort of.`]);
    default:
      return P(["I'm still looking for work. Any ideas?", "Nobody needs me today, so I'm taking it easy."]);
  }
}

function relWhen(sim, at) {
  const dayNow = Math.floor(sim.time / 1440);
  const dayAt = Math.floor(at / 1440);
  const hr = Math.floor((at % 1440) / 60);
  const hh = `${hr > 12 ? hr - 12 : hr}${hr >= 12 ? "pm" : "am"}`;
  if (dayAt === dayNow) return `tonight at ${hh}`;
  if (dayAt === dayNow + 1) return `tomorrow at ${hh}`;
  return `on day ${dayAt + 1} at ${hh}`;
}
const aAn = (w) => (/^[aeiou]/i.test(w) ? "an " : "a ") + w;
const listJoin = (xs) => (xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1]);

// ---------- optional model voices ----------
export function aiPrompt(sim, c) {
  const a = sim.agentById(c.a);
  const b = sim.agentById(c.b);
  const persona = (p, o) => {
    const mem = [...p.mem].sort((x, y) => y.imp * 2 - (sim.time - y.t) / 720 - (x.imp * 2 - (sim.time - x.t) / 720)).slice(0, 5);
    return `${p.name} ${p.last}, ${Math.floor(p.age)} years old, ${JOBS[p.job].label.toLowerCase()}, ${p.traits.map((t) => TRAITS[t].label.toLowerCase()).join(" and ")}. Mood ${Math.round(p.happy)}/100${p.sick ? ", sick" : ""}. Feels ${aff(p, o) > 40 ? "close to" : aff(p, o) < -25 ? "hostile toward" : "neutral about"} ${o.name}. Recent memories: ${mem.map((m) => m.text).join(" | ") || "none"}.`;
  };
  const topics = c.queue
    .filter((q) => !q.reply && q.k !== "greet" && q.k !== "bye")
    .map((q) => {
      const s = sim.nameOf(q.s);
      const l = sim.nameOf(q.l);
      const d = q.d || {};
      const f = d.fact && sim.facts.get(d.fact);
      switch (q.k) {
        case "party":
          return `${s} tells ${l} that ${f ? f.text : "there's a party"}; ${l} ${d.going ? "says they'll come" : "is unsure or declines"}.`;
        case "news":
        case "idea":
          return `${s} tells ${l} that ${f ? f.text : "some news"}; ${l} reacts${q.k === "idea" ? (d.agree ? " and agrees" : " and doubts it") : ""}.`;
        case "gossip":
          return `${s} gossips ${d.v > 0 ? "warmly" : "unkindly"} about ${sim.nameOf(d.c)}.`;
        case "romance":
          return `${s} confesses feelings to ${l}; ${l} ${d.yes ? "says yes" : "gently says no"}.`;
        case "argue":
          return `${s} picks an argument with ${l}${d.fight ? " and it turns into a fistfight" : ""}.`;
        case "help":
          return `${s} asks ${l} to help build; ${l} ${d.yes ? "agrees" : "declines"}.`;
        default:
          return `${s} talks about ${q.k === "work" ? "their work" : q.k === "village" ? "the village" : q.k === "need" ? "how they feel" : q.k}.`;
      }
    });
  const v = sim.villageById(a.village);
  const system = "You write short, natural dialogue for villagers in a cosy life-simulation game. Stay in character. Each line at most 25 words. No narration, no stage directions. Reply only with JSON.";
  const user = `Village: ${v ? v.name : "a small village"}, day ${sim.day}, ${sim.clock()}, weather ${sim.weather.kind}.
${persona(a, b)}
${persona(b, a)}
Write their conversation: ${a.name} greets ${b.name}, then cover in order: ${topics.join(" ") || "small talk."} Then they say goodbye.
Return {"lines":[{"speaker":"${a.name}","text":"..."},{"speaker":"${b.name}","text":"..."}]} with 6 to 12 lines, alternating speakers.`;
  return { system, user, names: { [a.name]: a.id, [b.name]: b.id } };
}

export function parseAiLines(raw, names, c) {
  let text = String(raw || "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  const m = text.match(/\{[\s\S]*\}/);
  let lines = [];
  if (m) {
    try {
      const o = JSON.parse(m[0]);
      lines = (o.lines || []).map((l) => ({ s: names[l.speaker], text: String(l.text || "").trim() }));
    } catch {
      lines = [];
    }
  }
  if (!lines.length)
    for (const row of text.split("\n")) {
      const mm = row.match(/^\s*\**([A-Za-z]+)\**\s*:\s*(.+)$/);
      if (mm && names[mm[1]]) lines.push({ s: names[mm[1]], text: mm[2].trim() });
    }
  lines = lines.filter((l) => l.s && l.text).map((l) => ({ s: l.s, text: l.text.replace(/^["“]|["”]$/g, "").slice(0, 200) }));
  // Skip the greeting the game already spoke.
  if (c && c.lines.length && lines.length > 1 && lines[0].s === c.a) lines.shift();
  return lines.slice(0, 14);
}
