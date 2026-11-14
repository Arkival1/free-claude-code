// Sheep wander and get eaten; wolves hunt.
import { dist, randInt } from "./rng.js";
import { T } from "./world.js";
import { remember } from "./social.js";

export function makeAnimal(sim, kind, x, y) {
  return { id: sim.id(), kind, x, y, hp: kind === "wolf" ? 36 : 20, path: null, timer: 0, hunger: kind === "wolf" ? 200 : 0, cd: 0, target: null, facing: 1, walk: 0 };
}

function walkTo(sim, n, tx, ty) {
  const p = sim.world.findPath(Math.floor(n.x), Math.floor(n.y), tx, ty, 2500);
  n.path = p && p.length ? p : null;
  return !!n.path;
}

function moveAlong(sim, n, dt, speed) {
  if (!n.path) return;
  let budget = speed * dt;
  while (budget > 0 && n.path && n.path.length) {
    const p = n.path[0];
    if (!sim.world.walkable(p.x, p.y)) {
      n.path = null;
      return;
    }
    const dx = p.x + 0.5 - n.x;
    const dy = p.y + 0.5 - n.y;
    const d = Math.hypot(dx, dy);
    if (Math.abs(dx) > 0.01) n.facing = dx > 0 ? 1 : -1;
    if (d <= budget) {
      n.x = p.x + 0.5;
      n.y = p.y + 0.5;
      n.path.shift();
      budget -= d;
    } else {
      n.x += (dx / d) * budget;
      n.y += (dy / d) * budget;
      budget = 0;
    }
  }
  if (n.path && !n.path.length) n.path = null;
  n.walk += dt;
}

function wander(sim, n, r) {
  const W = sim.world;
  for (let k = 0; k < 5; k++) {
    const x = Math.floor(n.x + (sim.rand() - 0.5) * r * 2);
    const y = Math.floor(n.y + (sim.rand() - 0.5) * r * 2);
    if (W.walkable(x, y) && W.t[W.idx(x, y)] !== T.WATER && walkTo(sim, n, x, y)) return;
  }
}

export function updateAnimal(sim, n, dt) {
  if (n.hp <= 0) {
    sim.animals = sim.animals.filter((m) => m !== n);
    return;
  }
  const W = sim.world;
  if (!W.walkable(Math.floor(n.x), Math.floor(n.y))) {
    const p = W.nearest(n.x, n.y, 8, (i, x, y) => W.walkable(x, y));
    if (!p) {
      n.hp = 0;
      return;
    }
    n.x = p.x + 0.5;
    n.y = p.y + 0.5;
    n.path = null;
  }
  if (W.fire[W.idx(Math.floor(n.x), Math.floor(n.y))] > 0) n.hp -= dt;
  n.timer -= dt;
  n.cd -= dt;
  if (n.kind === "sheep") {
    if (n.timer <= 0) {
      n.timer = 6;
      const wolf = sim.animals.find((m) => m.kind === "wolf" && dist(m.x, m.y, n.x, n.y) < 4);
      if (wolf) {
        const dx = n.x - wolf.x;
        const dy = n.y - wolf.y;
        const l = Math.hypot(dx, dy) || 1;
        walkTo(sim, n, Math.floor(n.x + (dx / l) * 5), Math.floor(n.y + (dy / l) * 5));
        n.fleeing = true;
      } else if (!n.path && sim.rand() < 0.3) {
        n.fleeing = false;
        wander(sim, n, 5);
        n.timer = randInt(sim.rand, 20, 80);
      }
    }
    moveAlong(sim, n, dt, n.fleeing ? 0.42 : 0.18);
    return;
  }
  // Wolf.
  n.hunger += dt;
  const hungry = n.hunger > 300 || (sim.isNight() && n.hunger > 150);
  if (n.timer <= 0) {
    n.timer = 5;
    if (hungry) {
      let prey = null;
      let pd = 16;
      for (const m of sim.animals)
        if (m.kind === "sheep") {
          const d = dist(m.x, m.y, n.x, n.y);
          if (d < pd) {
            pd = d;
            prey = m;
          }
        }
      if (!prey || pd > 9)
        for (const a of sim.agents) {
          const d = dist(a.x, a.y, n.x, n.y);
          if (d < Math.min(pd, 11)) {
            pd = d;
            prey = a;
          }
        }
      n.target = prey ? prey.id : null;
      if (prey && pd > 1.2) walkTo(sim, n, Math.floor(prey.x), Math.floor(prey.y));
    } else if (!n.path && sim.rand() < 0.4) {
      n.target = null;
      wander(sim, n, 8);
      n.timer = randInt(sim.rand, 15, 60);
    }
  }
  const prey = n.target != null && (sim.animals.find((m) => m.id === n.target) || sim.agentById(n.target));
  if (prey && dist(prey.x, prey.y, n.x, n.y) < 1.3) {
    n.path = null;
    if (n.cd <= 0) {
      n.cd = 8;
      sim.fx.push({ kind: "float", x: prey.x, y: prey.y - 0.8, text: "🩸", t0: Date.now() });
      if (prey.kind) {
        prey.hp = 0;
        n.hunger = 0;
        n.target = null;
      } else {
        prey.health -= 18;
        remember(sim, prey, "A wolf bit me!", 8, "event");
        if (prey.health <= 0) {
          sim.killAgent(prey, `was killed by a wolf near ${sim.describePlace(prey.x, prey.y)}`);
          n.hunger = 0;
          n.target = null;
        }
      }
    }
  }
  moveAlong(sim, n, dt, prey ? 0.4 : 0.22);
}
