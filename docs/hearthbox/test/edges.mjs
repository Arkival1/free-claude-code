// Edge cases found in review. Usage: node docs/hearthbox/test/edges.mjs
import { Sim } from "../js/sim.js";

const fails = [];
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? " (" + extra + ")" : ""}`);
  if (!ok) fails.push(name);
};

// 1. Lots of news while a party is planned: the invitation survives and nothing throws.
{
  const s = Sim.create(4242);
  s.advance(60);
  const host = s.agents.find((a) => a.age > 18);
  s.whisper(host, "party");
  const p = s.parties[0];
  for (let k = 0; k < 260; k++) s.addFact("plan", `filler news ${k}`, { imp: 1 });
  check("party fact kept under the fact cap", s.facts.has(p.fact));
  let threw = null;
  try {
    s.advance(2 * 1440);
  } catch (e) {
    threw = e;
  }
  check("sim keeps running under the fact cap", !threw, threw && threw.message);
  check("party ends", p.over);
}

// 2. Two parties by one host: the first ending keeps the second as the goal.
{
  const s = Sim.create(777);
  s.time = 5 * 60;
  s._lastHour = 5;
  const host = s.agents.find((a) => a.age > 18);
  s.whisper(host, "party"); // tonight
  s.advance(11 * 60);
  s.whisper(host, "party"); // tomorrow
  const second = s.parties[1].fact;
  s.advance(8 * 60);
  check("first party over", s.parties[0].over);
  check("host still plans the second party", host.goal && host.goal.fact === second);
}

// 3. Fires survive a save.
{
  const s = Sim.create(99);
  const h = s.hallOf(s.villages[0]);
  s.power("fire", h.x + 1, h.y + 1);
  const n = s.fires.length;
  const back = Sim.deserialize(JSON.parse(JSON.stringify(s.serialize())));
  check("fires saved", n > 0 && back.fires.length === n, `${n} -> ${back.fires.length}`);
}

// 5. A village plan nobody can pay for is kept for a while, then dropped and not re-placed at once.
{
  const s = Sim.create(5);
  const v = s.villages[0];
  s.settings.autoGrow = true;
  const spot = s.findSpot(v, "temple");
  const b = s.placeBuilding("temple", spot.x, spot.y, v);
  v.stock.gold = 0;
  s.advance(2 * 1440);
  check("unpaid plan kept for two days", !!s.buildingById(b.id) && !s.buildingById(b.id).funded);
  v.stock.gold = 0;
  s.advance(1.2 * 1440);
  check("unpaid plan dropped after three days", !s.buildingById(b.id));
  check("same plan not placed again at once", !s.buildings.some((x) => x.type === "temple" && !x.done && !x.byPlayer));
}

// 8. Erasing the hall while houses stand moves the store; no free hall appears.
{
  const s = Sim.create(6);
  const v = s.villages[0];
  const hall = s.hallOf(v);
  s.power("erase", hall.x + 1, hall.y + 1);
  s.advance(1440);
  const now = s.hallOf(v);
  check("store moved to another building", !!now && now.type !== "townhall");
  check("no free town hall after erasing it", !s.buildings.some((b) => b.village === v.id && b.type === "townhall"));
}

// 8b. A village that loses every building raises one new hall, once.
{
  const s = Sim.create(6);
  const v = s.villages[0];
  for (const b of [...s.buildings]) s.removeBuilding(b, "flattened");
  let threw = null;
  try {
    s.advance(1440);
  } catch (e) {
    threw = e;
  }
  check("no crash without buildings", !threw, threw && threw.message);
  check("hall rebuilt", !!s.hallOf(v));
  check("only one hall", s.buildings.filter((b) => b.village === v.id && b.type === "townhall").length === 1);
}

// The same seed gives the same story (no AI voices).
{
  const run = () => {
    const s = Sim.create(31337);
    s.advance(2 * 1440);
    return s.feed.map((l) => l.text).join("|") + s.log.map((e) => e.text).join("|");
  };
  check("same seed, same story", run() === run());
}

if (fails.length) {
  console.error("FAIL:", fails.join("; "));
  process.exit(1);
}
console.log("PASS");
