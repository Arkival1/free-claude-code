/* The Ops page's 3D system pulse. In the middle, columns rise with the
   CPU, memory and graphics card load (cyan, then amber, then red). Around
   them each background lane is a ring with one bead per slot: lit beads
   are jobs running, dim ones free, and small amber beads outside are jobs
   waiting. The agents sit on the outer ring and glow while they work.

   ops.js calls FCCOps3D.show(host, data) with each reading and stop() when
   the page changes; show() returns false when 3D can't be drawn. */
import { stage, glowTexture, textSprite, THREE } from "./fcc3d.js";

const LANE_COLOURS = { web: "#40d6ff", data: "#c792ff", model_local: "#ffc861", model_server: "#4dffa6", cpu: "#ff8f5d" };
const LANE_NAMES = { web: "web", data: "data", model_local: "local AI", model_server: "server AI", cpu: "cpu" };
const COOL = new THREE.Color("#40d6ff");
const WARM = new THREE.Color("#ffb547");
const HOT = new THREE.Color("#ff5d6c");
const AGENT_RADIUS = 5.4;

let pulse = null;
let failed = false;

function heat(value, into) {
  const level = Math.max(0, Math.min(100, Number(value) || 0)) / 100;
  if (level < 0.65) return into.copy(COOL).lerp(WARM, level / 0.65 * 0.3);
  if (level < 0.85) return into.copy(WARM);
  return into.copy(WARM).lerp(HOT, (level - 0.85) / 0.15);
}

function build(host, lowPower) {
  const holder = document.createElement("div");
  holder.className = "ops-3d";
  host.append(holder);
  const view = stage(holder, {
    lowPower,
    camera: [0, 6.5, 10],
    fit: { radius: AGENT_RADIUS + 0.6, height: 2.2 },
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
  scene.fog = new THREE.FogExp2(0x02070d, 0.03);
  scene.add(new THREE.AmbientLight(0x9fd8ea, 1.0));
  const glow = glowTexture();
  const grid = new THREE.PolarGridHelper(AGENT_RADIUS + 0.8, 16, 6, 96, 0x173f52, 0x0d2636);
  scene.add(grid);
  return { host, holder, view, scene, glow, columns: [], lanes: {}, agents: [], agentKey: "", columnKey: "" };
}

/* ------------------------------------------------------------ the pieces */

// Take a piece out and free its GPU memory (the shared glow stays).
function drop(object) {
  pulse.scene.remove(object);
  object.traverse((node) => {
    node.geometry?.dispose();
    for (const material of [].concat(node.material || [])) {
      if (material.map && material.map !== pulse.glow) material.map.dispose();
      material.dispose();
    }
  });
}

function columnsFor(data) {
  const machine = data.machine || {};
  const found = [
    ["CPU", machine.cpu],
    ["RAM", machine.memory],
  ];
  (machine.gpus || []).forEach((card, index) => {
    const suffix = machine.gpus.length > 1 ? ` ${index + 1}` : "";
    found.push([`GPU${suffix}`, card.load], [`VRAM${suffix}`, card.memory]);
  });
  return found;
}

function makeColumns(names) {
  for (const column of pulse.columns) drop(column.group);
  pulse.columns = names.map((name, index) => {
    const group = new THREE.Group();
    const spread = (index - (names.length - 1) / 2) * 0.9;
    group.position.set(spread, 0, 0);
    const bar = new THREE.Mesh(
      new THREE.CylinderGeometry(0.28, 0.28, 1, 24),
      new THREE.MeshStandardMaterial({ color: 0x0c2231, emissive: COOL, emissiveIntensity: 0.8, transparent: true, opacity: 0.85 })
    );
    bar.position.y = 0.5;
    const cap = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulse.glow, color: COOL, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    cap.scale.setScalar(1.1);
    const tag = textSprite(name, "#d9f6ff", { size: 0.3 });
    tag.position.y = -0.35;
    group.add(bar, cap, tag);
    pulse.scene.add(group);
    return { group, bar, cap, height: 0.05, want: 0.05, colour: new THREE.Color(COOL), wantColour: new THREE.Color(COOL) };
  });
}

function makeLane(name, index, limit) {
  const radius = 1.75 + index * 0.68;
  const colour = LANE_COLOURS[name] || "#7fa9ba";
  const group = new THREE.Group();
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(radius, 0.018, 6, 128),
    new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.45 })
  );
  ring.rotation.x = Math.PI / 2;
  group.add(ring);
  const tag = textSprite(LANE_NAMES[name] || name, colour, { size: 0.26 });
  tag.position.set(radius, 0.25, 0);
  group.add(tag);
  const beads = Array.from({ length: limit }, () => {
    const bead = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulse.glow, color: colour, transparent: true, opacity: 0.18, depthWrite: false, blending: THREE.AdditiveBlending }));
    bead.scale.setScalar(0.45);
    group.add(bead);
    return bead;
  });
  const queue = Array.from({ length: 8 }, () => {
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulse.glow, color: "#ffb547", transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    dot.scale.setScalar(0.25);
    group.add(dot);
    return dot;
  });
  group.position.y = 0.02 + index * 0.06;
  pulse.scene.add(group);
  return { group, radius, beads, queue, running: 0, waiting: 0, limit, spin: Math.random() * Math.PI * 2, speed: 0.25 + index * 0.05 };
}

function makeAgents(agents) {
  for (const agent of pulse.agents) drop(agent.group);
  pulse.agents = agents.map((agent, index) => {
    const angle = (index / Math.max(1, agents.length)) * Math.PI * 2;
    const group = new THREE.Group();
    group.position.set(Math.cos(angle) * AGENT_RADIUS, 0.5, Math.sin(angle) * AGENT_RADIUS);
    const body = new THREE.Mesh(
      new THREE.OctahedronGeometry(0.28, 0),
      new THREE.MeshStandardMaterial({ color: 0x0c2231, emissive: "#40d6ff", emissiveIntensity: 0.25 })
    );
    const aura = new THREE.Sprite(new THREE.SpriteMaterial({ map: pulse.glow, color: "#ffc861", transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    aura.scale.setScalar(1.4);
    const tag = textSprite(agent.name, "#d9f6ff", { size: 0.28 });
    tag.position.y = 0.6;
    group.add(aura, body, tag);
    pulse.scene.add(group);
    return { id: agent.id, group, body, aura, busy: false, phase: index };
  });
}

/* ------------------------------------------------------------ motion */

function tick(seconds, running) {
  if (!pulse) return;
  for (const column of pulse.columns) {
    column.height += (column.want - column.height) * Math.min(1, seconds * 3);
    column.colour.lerp(column.wantColour, Math.min(1, seconds * 3));
    column.bar.scale.y = Math.max(0.05, column.height);
    column.bar.position.y = column.bar.scale.y / 2;
    column.bar.material.emissive.copy(column.colour);
    column.cap.position.y = column.bar.scale.y + 0.05;
    column.cap.material.color.copy(column.colour);
  }
  for (const lane of Object.values(pulse.lanes)) {
    lane.spin += seconds * lane.speed * (lane.running ? 1 : 0.25);
    lane.beads.forEach((bead, index) => {
      const angle = lane.spin + (index / lane.beads.length) * Math.PI * 2;
      bead.position.set(Math.cos(angle) * lane.radius, 0, Math.sin(angle) * lane.radius);
      const on = index < lane.running;
      bead.material.opacity = on ? 0.95 : 0.18;
      bead.scale.setScalar(on ? 0.55 + Math.sin(running * 6 + index) * 0.08 : 0.4);
    });
    lane.queue.forEach((dot, index) => {
      const angle = -0.5 - index * 0.16;
      dot.position.set(Math.cos(angle) * (lane.radius + 0.32), 0, Math.sin(angle) * (lane.radius + 0.32));
      dot.material.opacity = index < lane.waiting ? 0.9 : 0;
    });
  }
  for (const agent of pulse.agents) {
    agent.body.rotation.y += seconds * (agent.busy ? 2.4 : 0.4);
    agent.group.position.y = 0.5 + (agent.busy ? Math.sin(running * 3 + agent.phase) * 0.12 : 0);
    agent.aura.material.opacity = agent.busy ? 0.55 + Math.sin(running * 4 + agent.phase) * 0.2 : 0;
    agent.body.material.emissive.set(agent.busy ? "#ffc861" : "#40d6ff");
    agent.body.material.emissiveIntensity = agent.busy ? 0.9 : 0.25;
  }
}

function apply(data) {
  const readings = columnsFor(data);
  const columnKey = readings.map(([name]) => name).join(",");
  if (columnKey !== pulse.columnKey) {
    pulse.columnKey = columnKey;
    makeColumns(readings.map(([name]) => name));
  }
  readings.forEach(([, value], index) => {
    const column = pulse.columns[index];
    column.want = 0.15 + (Math.max(0, Math.min(100, Number(value) || 0)) / 100) * 3.6;
    heat(value, column.wantColour);
  });
  (data.workers?.lanes || []).forEach((lane, index) => {
    let ring = pulse.lanes[lane.name];
    if (!ring || ring.limit !== lane.limit) {
      if (ring) drop(ring.group);
      ring = pulse.lanes[lane.name] = makeLane(lane.name, index, lane.limit);
    }
    ring.running = lane.running;
    ring.waiting = lane.waiting;
  });
  const agents = data.agents || [];
  const agentKey = agents.map((agent) => agent.id).join(",");
  if (agentKey !== pulse.agentKey) {
    pulse.agentKey = agentKey;
    makeAgents(agents);
  }
  agents.forEach((agent, index) => {
    pulse.agents[index].busy = Boolean(agent.busy);
  });
}

/* ------------------------------------------------------------ the page's calls */

function show(host, data) {
  if (failed || !host) return false;
  if (pulse && pulse.host !== host) stop();
  if (!pulse) {
    pulse = build(host, Boolean(data?.low_power));
    if (!pulse) {
      failed = true;
      return false;
    }
    host.classList.add("in-3d");
  }
  apply(data || {});
  return true;
}

function stop() {
  if (!pulse) return;
  const { view, holder, host } = pulse;
  pulse = null;
  view.dispose();
  holder.remove();
  host.classList.remove("in-3d");
}

window.FCCOps3D = { show, stop };
