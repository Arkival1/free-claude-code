/* The Trading Bank's 3D debate arena. The four seats sit on a ring around
   the Portfolio Manager's core:

   - colour shows a seat's stance (buy green, hold amber, sell red),
   - size shows its confidence, and the halo its vote weight,
   - every line of the debate sends light from the speaker to whoever it
     answers (cross-examination and rebuttals draw arcs between seats),
   - a decision bursts from the core, the core turns amber in the risk
     period, and a red shield flashes when risk stops a trade.

   trade.js calls FCCTradeArena.show(host, snapshot) when it paints the
   desk, feed(events) with each new batch of feed lines, and stop() when the
   tab or page changes. show() returns false when 3D can't be drawn, and
   the page keeps its 2D ring. */
import { stage, glowTexture, textSprite, THREE } from "./fcc3d.js";

const RADIUS = 3.4;
// Corners of the table, so no seat hides behind the core from the front.
const SEATS = {
  1: { name: "Chart", colour: "#40d6ff", angle: -135 },
  2: { name: "News", colour: "#c792ff", angle: -45 },
  3: { name: "Macro", colour: "#4dffa6", angle: 45 },
  4: { name: "Guardian", colour: "#ff5d6c", angle: 135 },
};
const PM = { name: "PM", colour: "#ffc861" };
const STANCE = { buy: "#4dffa6", hold: "#ffb547", sell: "#ff5d6c", avoid: "#ff5d6c" };
const NEUTRAL = "#30495a";
const ANALYSTS = [1, 2, 3];

let arena = null;
let failed = false;

function seatPosition(number) {
  if (!SEATS[number]) return new THREE.Vector3(0, 0.9, 0);
  const angle = (SEATS[number].angle * Math.PI) / 180;
  return new THREE.Vector3(Math.cos(angle) * RADIUS, 0.7, Math.sin(angle) * RADIUS);
}

function build(host, lowPower) {
  const holder = document.createElement("div");
  holder.className = "arena-3d";
  host.append(holder);
  const view = stage(holder, {
    lowPower,
    camera: [0, 6, 8.5],
    fit: { radius: RADIUS + 0.9, height: 1.6 },
    onFrame: (seconds, running) => tick(seconds, running),
    onLost: () => {
      failed = true;
      stop();
    },
  });
  if (!view) {
    holder.remove();
    return null;
  }
  const { scene } = view;
  scene.fog = new THREE.FogExp2(0x02070d, 0.04);
  scene.add(new THREE.AmbientLight(0x9fd8ea, 0.9));
  const lamp = new THREE.PointLight(0xffc861, 24, 26, 1.6);
  lamp.position.set(0, 4.5, 0);
  scene.add(lamp);
  const glow = glowTexture();

  // The floor: the table's rings and a faint polar grid.
  for (const [radius, opacity] of [
    [RADIUS, 0.5],
    [RADIUS * 0.5, 0.25],
    [RADIUS * 1.42, 0.16],
  ]) {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(radius - 0.018, radius + 0.018, 128),
      new THREE.MeshBasicMaterial({ color: 0x40d6ff, transparent: true, opacity, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    scene.add(ring);
  }
  const grid = new THREE.PolarGridHelper(RADIUS * 1.42, 12, 5, 64, 0x173f52, 0x0d2636);
  grid.position.y = -0.01;
  scene.add(grid);

  // The Portfolio Manager's core.
  const core = new THREE.Group();
  core.position.set(0, 0.95, 0);
  const shell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.95, 1),
    new THREE.MeshBasicMaterial({ color: PM.colour, wireframe: true, transparent: true, opacity: 0.5 })
  );
  const heart = new THREE.Mesh(
    new THREE.SphereGeometry(0.55, 32, 24),
    new THREE.MeshStandardMaterial({ color: 0x1a1203, emissive: PM.colour, emissiveIntensity: 0.85, roughness: 0.4 })
  );
  const aura = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: PM.colour, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
  aura.scale.setScalar(3.4);
  const shield = new THREE.Mesh(
    new THREE.SphereGeometry(1.45, 24, 16),
    new THREE.MeshBasicMaterial({ color: 0xff5d6c, wireframe: true, transparent: true, opacity: 0 })
  );
  const pmTag = textSprite("PM", PM.colour);
  pmTag.position.y = 1.55;
  core.add(shell, heart, aura, shield, pmTag);
  scene.add(core);

  // The four seats.
  const seats = {};
  for (const [number, info] of Object.entries(SEATS)) {
    const group = new THREE.Group();
    group.position.copy(seatPosition(Number(number)));
    const body = new THREE.Mesh(
      new THREE.SphereGeometry(0.42, 32, 24),
      new THREE.MeshStandardMaterial({ color: 0x0c2231, emissive: info.colour, emissiveIntensity: 0.5, roughness: 0.35 })
    );
    const halo = new THREE.Mesh(
      new THREE.TorusGeometry(0.66, 0.022, 8, 72),
      new THREE.MeshBasicMaterial({ color: info.colour, transparent: true, opacity: 0.75 })
    );
    halo.rotation.x = Math.PI / 2;
    const mood = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: NEUTRAL, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }));
    mood.scale.setScalar(1.7);
    const tag = textSprite(info.name, info.colour);
    tag.position.y = 1.05;
    const column = new THREE.Mesh(
      new THREE.CylinderGeometry(0.012, 0.012, 0.7, 6),
      new THREE.MeshBasicMaterial({ color: info.colour, transparent: true, opacity: 0.35 })
    );
    column.position.y = -0.35;
    group.add(mood, body, halo, tag, column);
    scene.add(group);
    seats[number] = { group, body, halo, mood, size: 1, wantSize: 1, ring: 1, wantRing: 1, pulse: 0 };
  }

  // Light travelling between seats: one shared buffer, recycled.
  const most = lowPower ? 140 : 300;
  const positions = new Float32Array(most * 3);
  const colours = new Float32Array(most * 3);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
  geometry.setDrawRange(0, 0);
  const sparks = new THREE.Points(
    geometry,
    new THREE.PointsMaterial({ size: 0.2, map: glow, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
  );
  scene.add(sparks);

  return {
    host,
    holder,
    view,
    core,
    shell,
    heart,
    aura,
    shield,
    seats,
    sparks,
    positions,
    colours,
    most,
    flights: [],
    arcs: [],
    lastSeq: 0,
    speaking: 0,
    coreColour: new THREE.Color(PM.colour),
    wantCore: new THREE.Color(PM.colour),
    shieldLife: 0,
    burst: 0,
  };
}

/* ------------------------------------------------------------ motion */

const scratch = new THREE.Vector3();

function tick(seconds, running) {
  if (!arena) return;
  const { core, shell, heart, aura, shield, seats } = arena;
  shell.rotation.y += seconds * 0.35;
  shell.rotation.x += seconds * 0.12;
  arena.coreColour.lerp(arena.wantCore, Math.min(1, seconds * 3));
  heart.material.emissive.copy(arena.coreColour);
  shell.material.color.copy(arena.coreColour);
  aura.material.color.copy(arena.coreColour);
  const beat = 1 + Math.sin(running * 2.4) * 0.04 + arena.burst * 0.35;
  core.scale.setScalar(beat);
  arena.burst = Math.max(0, arena.burst - seconds * 1.6);
  arena.shieldLife = Math.max(0, arena.shieldLife - seconds * 0.7);
  shield.material.opacity = arena.shieldLife * 0.6;
  shield.rotation.y -= seconds * 0.8;

  for (const [number, seat] of Object.entries(seats)) {
    seat.size += (seat.wantSize - seat.size) * Math.min(1, seconds * 4);
    seat.ring += (seat.wantRing - seat.ring) * Math.min(1, seconds * 4);
    seat.pulse = Math.max(0, seat.pulse - seconds * 1.5);
    const talking = arena.speaking === Number(number) ? 0.08 + Math.sin(running * 7) * 0.05 : 0;
    seat.body.scale.setScalar(seat.size * (1 + talking + seat.pulse * 0.25));
    seat.halo.scale.setScalar(seat.ring);
    seat.halo.rotation.z += seconds * 0.6;
    seat.body.material.emissiveIntensity = 0.5 + talking * 4 + seat.pulse * 0.8;
    seat.group.position.y = 0.7 + Math.sin(running * 1.3 + Number(number)) * 0.05;
  }

  // Sparks fly along a raised curve, then land with a pulse.
  const { positions, colours } = arena;
  let shown = 0;
  arena.flights = arena.flights.filter((flight) => {
    flight.wait -= seconds;
    if (flight.wait > 0) return true;
    flight.t += seconds * flight.speed;
    if (flight.t >= 1) {
      if (flight.land) flight.land();
      return false;
    }
    if (shown < arena.most) {
      flight.curve.getPoint(flight.t, scratch);
      const at = shown * 3;
      positions[at] = scratch.x;
      positions[at + 1] = scratch.y;
      positions[at + 2] = scratch.z;
      colours[at] = flight.colour.r;
      colours[at + 1] = flight.colour.g;
      colours[at + 2] = flight.colour.b;
      shown += 1;
    }
    return true;
  });
  arena.sparks.geometry.setDrawRange(0, shown);
  arena.sparks.geometry.attributes.position.needsUpdate = true;
  arena.sparks.geometry.attributes.color.needsUpdate = true;

  arena.arcs = arena.arcs.filter((arc) => {
    arc.life -= seconds * 0.45;
    arc.line.material.opacity = Math.max(0, arc.life) * 0.7;
    if (arc.life > 0) return true;
    arena.view.scene.remove(arc.line);
    arc.line.geometry.dispose();
    arc.line.material.dispose();
    return false;
  });
}

function where(number) {
  if (number === 5 || number === 0 || !arena.seats[number]) return arena.core.position.clone();
  return arena.seats[number].group.position.clone();
}

function fly(from, to, colour, count = 10, { arc = false, delay = 0 } = {}) {
  if (!arena) return;
  const start = where(from);
  const end = where(to);
  if (start.distanceTo(end) < 0.01) return;
  const middle = start.clone().lerp(end, 0.5);
  middle.y += 1.2 + start.distanceTo(end) * 0.18;
  const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
  const tint = new THREE.Color(colour);
  const budget = Math.max(2, Math.round(count * (arena.view.lowPower ? 0.5 : 1)));
  for (let index = 0; index < budget; index += 1) {
    arena.flights.push({
      curve,
      colour: tint,
      t: 0,
      wait: delay + index * 0.06,
      speed: 0.7 + Math.random() * 0.25,
      land: index === budget - 1 ? () => landed(to) : null,
    });
  }
  if (arc) {
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)),
      new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity: 0.7 })
    );
    arena.view.scene.add(line);
    arena.arcs.push({ line, life: 1 });
  }
}

function landed(number) {
  const seat = arena?.seats[number];
  if (seat) seat.pulse = 1;
  else if (arena) arena.burst = Math.max(arena.burst, 0.4);
}

function colourOf(number) {
  return (SEATS[number] || PM).colour;
}

/* ------------------------------------------------------------ the debate */

function react(event) {
  const from = Number(event.seat || 0);
  const colour = colourOf(from);
  switch (event.kind) {
    case "briefing":
      for (const seat of [1, 2, 3, 4]) fly(5, seat, PM.colour, 6, { delay: seat * 0.1 });
      break;
    case "opening":
    case "closing":
    case "risk_note":
      fly(from, 5, event.kind === "risk_note" ? "#ffb547" : colour, 10);
      break;
    case "cross_exam":
      for (const other of ANALYSTS) if (other !== from) fly(from, other, colour, 8, { arc: true });
      break;
    case "pre_mortem":
    case "guardian_reply":
      for (const seat of ANALYSTS) fly(4, seat, SEATS[4].colour, 8, { arc: true, delay: seat * 0.12 });
      break;
    case "rebuttal":
      fly(from, 4, colour, 9, { arc: true });
      break;
    case "final_challenge":
      fly(4, 5, SEATS[4].colour, 12, { arc: true });
      break;
    case "consensus":
      arena.burst = 0.5;
      break;
    case "decision":
      arena.burst = 1;
      for (const seat of [1, 2, 3, 4]) fly(5, seat, PM.colour, 8, { delay: 0.1 });
      break;
    case "risk_report":
    case "cooling":
      arena.wantCore.set("#ffb547");
      break;
    case "risk_gate":
      arena.shieldLife = 1;
      arena.wantCore.set("#ff5d6c");
      break;
    case "order":
    case "fill":
      arena.burst = 1;
      arena.wantCore.set("#4dffa6");
      break;
    case "error":
      if (arena.seats[from]) arena.seats[from].pulse = 1;
      break;
    default:
      break;
  }
}

function apply(snapshot) {
  const confident = (view) => (view && typeof view.confidence === "number" ? view.confidence : 0.5);
  for (const [number, seat] of Object.entries(arena.seats)) {
    const view = snapshot.seats?.[number];
    const stance = view?.stance || "";
    seat.mood.material.color.set(STANCE[stance] || NEUTRAL);
    seat.mood.material.opacity = stance ? 0.95 : 0.5;
    seat.wantSize = 0.8 + confident(view) * 0.5;
    const weight = Number(snapshot.weights?.[number] ?? 1);
    seat.wantRing = 0.75 + Math.min(2, Math.max(0.5, weight)) * 0.3;
  }
  arena.speaking = Number(snapshot.activity?.seat || 0);
  const stage = String(snapshot.stage || snapshot.activity?.stage || "");
  const decided = snapshot.decision?.action;
  if (/risk|cooling/i.test(stage)) arena.wantCore.set("#ffb547");
  else if (decided === "buy") arena.wantCore.set("#4dffa6");
  else if (decided === "sell") arena.wantCore.set("#ff5d6c");
  else if (arena.shieldLife <= 0) arena.wantCore.set(PM.colour);
}

/* ------------------------------------------------------------ the page's calls */

function show(host, snapshot) {
  if (failed || !host) return false;
  if (arena && arena.host !== host) stop();
  if (!arena) {
    arena = build(host, Boolean(snapshot?.lowPower));
    if (!arena) {
      failed = true;
      return false;
    }
    host.classList.add("in-3d");
  }
  apply(snapshot || {});
  return true;
}

function feed(events) {
  if (!arena) return;
  for (const event of events) {
    if (event.seq <= arena.lastSeq) continue;
    arena.lastSeq = event.seq;
    react(event);
  }
}

function stop() {
  if (!arena) return;
  const { view, holder, host } = arena;
  arena = null;
  view.dispose();
  holder.remove();
  host.classList.remove("in-3d");
}

window.FCCTradeArena = { show, feed, stop };
