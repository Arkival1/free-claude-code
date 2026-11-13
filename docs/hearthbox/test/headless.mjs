// Runs the simulation without a screen and checks the village lives.
// Usage: node docs/hearthbox/test/headless.mjs [days] [seed]
import { Sim } from "../js/sim.js";

const days = Number(process.argv[2] || 10);
const seed = Number(process.argv[3] || 12345);
const sim = Sim.create(seed);
const t0 = Date.now();
sim.power("wolf", 10, 10);
let whispered = false;
for (let d = 0; d < days; d++) {
  for (let h = 0; h < 24; h++) {
    sim.advance(60);
    if (!whispered && sim.day === 1 && sim.hour >= 9 && sim.agents.length) {
      whispered = true;
      sim.whisper(sim.agents[0], "party");
      sim.whisper(sim.agents[1], "thought", { text: "the old well is haunted" });
    }
  }
  const v = sim.villages[0];
  const s = v.stock;
  console.log(
    `day ${sim.day} pop ${sim.agents.length} food ${Math.round(s.food)} wood ${Math.round(s.wood)} stone ${Math.round(s.stone)} gold ${Math.round(s.gold)} ` +
      `bld ${sim.buildings.filter((b) => b.done).length}/${sim.buildings.length} talks ${sim.stats.talks} births ${sim.stats.births} deaths ${sim.stats.deaths} ` +
      `happy ${Math.round(sim.agents.reduce((x, a) => x + a.happy, 0) / Math.max(1, sim.agents.length))} jobs ${JSON.stringify(sim.agents.reduce((m, a) => ((m[a.job] = (m[a.job] || 0) + 1), m), {}))}`,
  );
}
const party = [...sim.facts.values()].find((f) => f.kind === "party");
const idea = [...sim.facts.values()].find((f) => f.kind === "idea");
const knowers = (f) => (f ? sim.agents.filter((a) => a.knowsSet.has(f.id)).length : 0);
console.log("party knowers", knowers(party), "idea knowers", knowers(idea), "of", sim.agents.length);
console.log("sample feed:");
for (const l of sim.feed.slice(-14)) console.log(`  ${l.sn} → ${l.ln}: ${l.text}`);
console.log("log tail:");
for (const e of sim.log.slice(-12)) console.log(`  ${sim.clock(e.t)} ${e.icon} ${e.text}`);
const a = sim.agents[0];
if (a) {
  console.log("plan of", a.name, a.plan.map((p) => `${p.h0}-${p.h1} ${p.text}`).join(" | "));
  console.log("mem", a.mem.slice(-6).map((m) => m.text).join(" | "));
}
const saved = JSON.stringify(sim.serialize());
const back = Sim.deserialize(JSON.parse(saved));
back.advance(120);
console.log(`save ${Math.round(saved.length / 1024)} KB, reload ok, ${Date.now() - t0} ms`);
const fails = [];
if (sim.agents.length < 5) fails.push("village died out");
if (sim.stats.talks < 20) fails.push("too few conversations");
if (knowers(party) < 3) fails.push("party news did not spread");
if (!sim.buildings.some((b) => b.done && b.born > 400)) fails.push("nothing new was built");
if (fails.length) {
  console.error("FAIL:", fails.join("; "));
  process.exit(1);
}
console.log("PASS");
