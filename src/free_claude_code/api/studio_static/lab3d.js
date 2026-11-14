/* The Lab's 3D build view: a design drawn as the real thing, in its
   materials, on a studio floor, with every part labelled by a pointer line.

   - Drag the view to turn it, the wheel to zoom.
   - Click a part to see what it is and how it works; drag a part to move it
     (the first move pins every part where it is, so nothing else jumps).
   - Turn, lift and lower the chosen part; "Auto layout" lets the view lay
     it out again.
   - Ask the AI to build or change the design from the box at the bottom.

   lab.js loads this module and calls window.FCCLab3D.mount(host, hooks);
   without WebGL mount returns null and the Lab keeps its tiles. */
import { stage, THREE } from "./fcc3d.js";

const GAP = 6; // mm between parts the view lays out
const MAX_COPIES = 6; // copies of a counted part shown
const WORLD = 6; // the design's widest side, in scene units

const CONNECTOR = /\b(slot|header|connector|socket|port|usb|jack|plug|terminal|pins?)\b/i;
const HEAT_SINK = /heat ?sink|radiator|cooler/i;
const CHIP = /\b(chip|chipset|controller|processor|cpu|bios|ic|bridge)\b/i;
const COIL = /\b(inductor|coil|choke)\b/i;

/* ---------------------------------------------------------------- looks */

const textures = new Map();

function boardTexture(colour) {
  const key = `board:${colour}`;
  if (textures.has(key)) return textures.get(key);
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const paint = canvas.getContext("2d");
  paint.fillStyle = colour;
  paint.fillRect(0, 0, size, size);
  // Copper traces under the solder mask, a shade lighter than the board.
  const base = new THREE.Color(colour);
  paint.strokeStyle = `#${base.clone().offsetHSL(0, 0, 0.06).getHexString()}`;
  paint.lineWidth = 2;
  let seed = 7;
  const random = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  for (let i = 0; i < 26; i += 1) {
    let x = random() * size;
    let y = random() * size;
    paint.beginPath();
    paint.moveTo(x, y);
    for (let step = 0; step < 3; step += 1) {
      if (random() < 0.5) x += (random() - 0.5) * 120;
      else y += (random() - 0.5) * 120;
      paint.lineTo(x, y);
    }
    paint.stroke();
  }
  // Vias and pads: the little white dots of a real board.
  paint.fillStyle = "rgba(240,240,235,0.85)";
  for (let i = 0; i < 360; i += 1) {
    const cluster = Math.floor(random() * 12);
    const cx = ((cluster * 73) % size) + random() * 40;
    const cy = ((cluster * 151) % size) + random() * 40;
    paint.beginPath();
    paint.arc(cx % size, cy % size, 1.3, 0, Math.PI * 2);
    paint.fill();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  textures.set(key, texture);
  return texture;
}

function surface(item) {
  const color = new THREE.Color(item.colour || "#8a8f98");
  switch (item.finish) {
    case "metal":
      return new THREE.MeshStandardMaterial({ color, metalness: 0.85, roughness: 0.32 });
    case "board": {
      const map = boardTexture(item.colour || "#2f6b3a").clone();
      map.needsUpdate = true;
      const [w, , d] = item.size_mm;
      map.repeat.set(Math.max(1, w / 90), Math.max(1, (d || w) / 90));
      return new THREE.MeshStandardMaterial({ map, roughness: 0.5, metalness: 0.08 });
    }
    case "glass":
    case "gem":
      return new THREE.MeshPhysicalMaterial({ color, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.35, depthWrite: false });
    case "wood":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.85 });
    case "rubber":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.95 });
    case "ceramic":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.4 });
    case "wafer":
      return new THREE.MeshStandardMaterial({ color, roughness: 0.25, metalness: 0.5 });
    default:
      return new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.02 });
  }
}

const plastic = (hex, roughness = 0.6) => new THREE.MeshStandardMaterial({ color: hex, roughness, metalness: 0.02 });
const metal = (hex, roughness = 0.3) => new THREE.MeshStandardMaterial({ color: hex, roughness, metalness: 0.9 });

function mesh(geometry, material, x = 0, y = 0, z = 0) {
  const made = new THREE.Mesh(geometry, material);
  made.position.set(x, y, z);
  made.castShadow = true;
  made.receiveShadow = true;
  return made;
}

// A row of gold pins along a line, as one instanced mesh.
function pins(count, from, to, y, size) {
  const shown = Math.max(1, Math.min(count, 60));
  const geometry = new THREE.BoxGeometry(size, size, size * 2.4);
  const row = new THREE.InstancedMesh(geometry, metal(0xd8b45a, 0.25), shown);
  const matrix = new THREE.Matrix4();
  for (let i = 0; i < shown; i += 1) {
    const t = shown === 1 ? 0.5 : i / (shown - 1);
    matrix.makeTranslation(from[0] + (to[0] - from[0]) * t, y, from[1] + (to[1] - from[1]) * t);
    row.setMatrixAt(i, matrix);
  }
  row.castShadow = true;
  return row;
}

// A black chip with silver legs on four sides.
function chip(w, d, h) {
  const group = new THREE.Group();
  group.add(mesh(new THREE.BoxGeometry(w, h, d), plastic(0x1b1c1f, 0.45), 0, h / 2, 0));
  const leg = Math.max(0.3, Math.min(w, d) * 0.04);
  const silver = metal(0xc9ccd1, 0.35);
  for (const side of [-1, 1]) {
    for (const along of ["x", "z"]) {
      const span = along === "x" ? w : d;
      const count = Math.max(4, Math.round(span / (leg * 2.6)));
      const bar = new THREE.InstancedMesh(new THREE.BoxGeometry(leg, leg * 0.6, leg * 2.2), silver, count);
      const matrix = new THREE.Matrix4();
      for (let i = 0; i < count; i += 1) {
        const offset = -span / 2 + (span * (i + 0.5)) / count;
        if (along === "x") matrix.makeTranslation(offset, leg * 0.3, side * (d / 2 + leg));
        else matrix.makeRotationY(Math.PI / 2).setPosition(side * (w / 2 + leg), leg * 0.3, offset);
        bar.setMatrixAt(i, matrix);
      }
      group.add(bar);
    }
  }
  return group;
}

const SLEEVES = [0x2f8f4e, 0x1c2a4a, 0x26272b, 0x6a5acd, 0xd1a03b];

// One copy of a component, its bottom centre at the origin, in mm.
function body(item, alive, number) {
  const [a, b, c] = item.size_mm;
  const group = new THREE.Group();
  const look = surface(item);
  const flat = item.shape === "board" || item.shape === "plate";
  // A part on a board is drawn as a board with its chips; otherwise by kind.
  const kind = flat ? "" : item.part_kind;
  const name = item.name || "";

  if (item.shape === "wire") {
    const length = Math.min(b, item.reach || b);
    const points = [];
    for (let i = 0; i <= 24; i += 1) {
      const t = i / 24;
      points.push(new THREE.Vector3(-length / 2 + length * t, a / 2 + Math.sin(t * Math.PI) * length * 0.04, Math.sin(t * Math.PI * 3) * length * 0.03));
    }
    const curve = new THREE.CatmullRomCurve3(points);
    group.add(mesh(new THREE.TubeGeometry(curve, 48, Math.max(a / 2, 0.4), 8, false), plastic(number % 2 ? 0xc0392b : 0x222222, 0.5)));
    return group;
  }

  if (kind === "passive") {
    const r = Math.max(2, Math.min(a, c || a) / 2);
    const tall = Math.max(4, b);
    group.add(mesh(new THREE.CylinderGeometry(r, r, tall, 24), plastic(SLEEVES[number % SLEEVES.length], 0.35), 0, tall / 2, 0));
    group.add(mesh(new THREE.CylinderGeometry(r * 0.96, r * 0.96, 0.4, 24), metal(0xd4d7dc), 0, tall + 0.2, 0));
    group.add(mesh(new THREE.BoxGeometry(r * 0.25, tall * 0.98, r * 0.3), plastic(0xe9e9e9), r * 0.92, tall / 2, 0));
    return group;
  }

  if (kind === "light") {
    const r = Math.max(1.5, Math.min(a, c || a) / 2);
    const glow = new THREE.MeshStandardMaterial({ color: item.colour || 0xff3b30, emissive: item.colour || 0xff3b30, emissiveIntensity: alive ? 1.4 : 0.05, transparent: true, opacity: 0.85, roughness: 0.2 });
    group.add(mesh(new THREE.CylinderGeometry(r, r, r * 1.6, 20), glow, 0, r * 0.8, 0));
    group.add(mesh(new THREE.SphereGeometry(r, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), glow, 0, r * 1.6, 0));
    return group;
  }

  if (kind === "power" && item.shape === "cylinder" && b < a) {
    // A coin cell lies flat.
    group.add(mesh(new THREE.CylinderGeometry(a / 2, a / 2, b, 36), metal(0xd9dce0, 0.22), 0, b / 2, 0));
    return group;
  }

  if (kind === "power" && (item.shape === "cylinder" || item.shape === "rod" || /aa|18650|cell/i.test(item.part_id || ""))) {
    const r = Math.max(3, Math.min(a, c || a) / 2);
    const long = Math.max(r * 3, b);
    const cell = new THREE.Group();
    cell.add(mesh(new THREE.CylinderGeometry(r, r, long, 28), plastic(SLEEVES[(number + 1) % SLEEVES.length], 0.3)));
    cell.add(mesh(new THREE.CylinderGeometry(r * 0.35, r * 0.35, 1.2, 16), metal(0xd4d7dc), 0, long / 2 + 0.6, 0));
    cell.add(mesh(new THREE.CylinderGeometry(r * 1.01, r * 1.01, long * 0.12, 28), metal(0xc0c4ca), 0, -long / 2 + long * 0.06, 0));
    cell.rotation.z = Math.PI / 2; // batteries lie down
    cell.position.y = r;
    group.add(cell);
    return group;
  }

  if (kind === "motion" && /wheel|tyre|tire/i.test(`${name} ${item.part_id || ""}`)) {
    const r = Math.max(5, a / 2);
    const wide = Math.max(4, b || r * 0.6);
    const wheel = new THREE.Group();
    wheel.add(mesh(new THREE.CylinderGeometry(r, r, wide, 36), surface(item)));
    wheel.add(mesh(new THREE.TorusGeometry(r * 0.92, r * 0.1, 10, 36), plastic(0x1a1a1a, 0.95), 0, wide / 2, 0).rotateX(Math.PI / 2));
    wheel.add(mesh(new THREE.TorusGeometry(r * 0.92, r * 0.1, 10, 36), plastic(0x1a1a1a, 0.95), 0, -wide / 2, 0).rotateX(Math.PI / 2));
    wheel.add(mesh(new THREE.CylinderGeometry(r * 0.45, r * 0.45, wide * 1.04, 24), plastic(0xf2c230, 0.5)));
    wheel.rotation.x = Math.PI / 2; // standing up, rolling forwards
    wheel.position.y = r;
    group.add(wheel);
    return group;
  }

  if (kind === "motion") {
    const r = Math.max(4, Math.min(a, c || a) / 2);
    const long = Math.max(r * 2, b);
    const motor = new THREE.Group();
    motor.add(mesh(new THREE.CylinderGeometry(r, r, long, 28), metal(0xb9bec6, 0.28)));
    motor.add(mesh(new THREE.CylinderGeometry(r * 0.12, r * 0.12, long * 0.35, 12), metal(0xe6e8eb, 0.2), 0, long / 2 + long * 0.17, 0));
    motor.add(mesh(new THREE.CylinderGeometry(r * 1.02, r * 1.02, long * 0.1, 28), plastic(0x2a2a2a), 0, -long / 2 + long * 0.05, 0));
    motor.rotation.z = Math.PI / 2;
    motor.position.y = r;
    group.add(motor);
    return group;
  }

  if (kind === "display") {
    const thick = Math.max(2, Math.min(b, 8));
    group.add(mesh(new THREE.BoxGeometry(a, thick, c || a * 0.6), plastic(0x15171a, 0.4), 0, thick / 2, 0));
    const face = new THREE.MeshStandardMaterial({ color: 0x0b1a2e, emissive: 0x3aa0ff, emissiveIntensity: alive ? 0.7 : 0, roughness: 0.15 });
    group.add(mesh(new THREE.BoxGeometry(a * 0.9, 0.3, (c || a * 0.6) * 0.82), face, 0, thick + 0.15, 0));
    return group;
  }

  if (kind === "sound") {
    const r = Math.max(4, Math.min(a, c || a) / 2);
    const tall = Math.max(3, b);
    group.add(mesh(new THREE.CylinderGeometry(r, r * 0.8, tall, 28), plastic(0x1d1d1f, 0.6), 0, tall / 2, 0));
    group.add(mesh(new THREE.TorusGeometry(r * 0.7, r * 0.06, 8, 32), metal(0x9aa0a6), 0, tall + 0.1, 0).rotateX(Math.PI / 2));
    return group;
  }

  if (kind === "control") {
    const w = Math.max(4, a);
    const d = Math.max(4, c || a);
    group.add(mesh(new THREE.BoxGeometry(w, Math.max(2, b * 0.5), d), plastic(0x2a2c30), 0, Math.max(1, b * 0.25), 0));
    group.add(mesh(new THREE.CylinderGeometry(Math.min(w, d) * 0.3, Math.min(w, d) * 0.3, Math.max(1.5, b * 0.5), 20), plastic(0xd64545, 0.4), 0, Math.max(2, b * 0.5) + Math.max(0.75, b * 0.25), 0));
    return group;
  }

  if (HEAT_SINK.test(name)) {
    const w = a;
    const d = c || a;
    const tall = Math.max(4, b);
    const foot = Math.max(1, tall * 0.15);
    const fin = metal(0xc6cbd2, 0.4);
    group.add(mesh(new THREE.BoxGeometry(w, foot, d), fin, 0, foot / 2, 0));
    const fins = Math.max(4, Math.round(w / 3));
    for (let i = 0; i < fins; i += 1) {
      group.add(mesh(new THREE.BoxGeometry(Math.max(0.4, (w / fins) * 0.35), tall - foot, d), fin, -w / 2 + (w * (i + 0.5)) / fins, foot + (tall - foot) / 2, 0));
    }
    return group;
  }

  if (COIL.test(name) && !flat) {
    const r = Math.max(2, Math.min(a, c || a) / 2);
    group.add(mesh(new THREE.BoxGeometry(r * 2, r * 0.5, r * 2), plastic(0x2a2a2a), 0, r * 0.25, 0));
    group.add(mesh(new THREE.TorusGeometry(r * 0.62, r * 0.32, 12, 28), metal(0xb86b35, 0.35), 0, r * 0.5 + r * 0.3, 0).rotateX(Math.PI / 2));
    return group;
  }

  if (CHIP.test(name) && item.shape === "box" && !HEAT_SINK.test(name) && !CONNECTOR.test(name) && b <= Math.min(a, c || a) * 0.4) {
    group.add(chip(a, c || a, b));
    return group;
  }

  if (CONNECTOR.test(name) && !flat && item.finish !== "metal") {
    const w = a;
    const d = c || a;
    const tall = Math.max(2, b);
    group.add(mesh(new THREE.BoxGeometry(w, tall, d), look, 0, tall / 2, 0));
    const along = w >= d;
    const count = Math.round((along ? w : d) / 2.54);
    const half = (along ? w : d) / 2 - 1.2;
    group.add(pins(count, along ? [-half, 0] : [0, -half], along ? [half, 0] : [0, half], tall + 0.3, 0.6));
    return group;
  }

  // A plain shape in its material.
  let main;
  if (item.shape === "rod" || item.shape === "tube") {
    const r = Math.max(0.5, a / 2);
    const geometry = item.shape === "tube" ? new THREE.CylinderGeometry(r, r, b, 24, 1, true) : new THREE.CylinderGeometry(r, r, b, 24);
    main = mesh(geometry, look, 0, r, 0);
    main.rotation.z = Math.PI / 2; // rods and tubes lie along x
  } else if (item.shape === "cylinder") {
    main = mesh(new THREE.CylinderGeometry(a / 2, a / 2, b, 32), look, 0, b / 2, 0);
  } else if (item.shape === "sphere") {
    main = mesh(new THREE.SphereGeometry(a / 2, 32, 20), look, 0, a / 2, 0);
  } else {
    main = mesh(new THREE.BoxGeometry(a, b, c || a), look, 0, b / 2, 0);
  }
  if (item.role === "casing") {
    // See into it: the casing is drawn as a tinted shell.
    look.transparent = true;
    look.opacity = item.seeThrough ? 0.22 : 0.92;
    look.depthWrite = !item.seeThrough;
    main.castShadow = !item.seeThrough;
  }
  group.add(main);

  // Electronics on a board: a chip and a header, so it reads as a real board.
  if (item.shape === "board" && item.part_kind && item.part_kind !== "structure") {
    const side = Math.max(4, Math.min(a, c || a) * (item.part_kind === "brain" ? 0.32 : 0.4));
    const part = chip(side, side, Math.max(1.2, side * 0.12));
    part.position.set(-a * 0.12, b, 0);
    group.add(part);
    const strip = Math.max(5, a * 0.7);
    const header = mesh(new THREE.BoxGeometry(strip, 2.5, 2.5), plastic(0x161616), 0, b + 1.25, -(c || a) / 2 + 3);
    group.add(header);
    group.add(pins(Math.round(strip / 2.54), [-strip / 2 + 1, -(c || a) / 2 + 3], [strip / 2 - 1, -(c || a) / 2 + 3], b + 3, 0.6));
  } else if (kind && kind !== "structure" && item.shape !== "board" && item.shape !== "plate" && item.role !== "casing") {
    // A module in a box: a dark chip on top.
    if (item.shape === "box") {
      const part = chip(Math.max(2, a * 0.5), Math.max(2, (c || a) * 0.5), Math.max(0.8, b * 0.08));
      part.position.y = b;
      group.add(part);
    }
  }
  return group;
}

/* --------------------------------------------------------------- layout */

function footprint(item) {
  const [a, b, c] = item.size_mm;
  let size;
  if (item.shape === "wire") size = { w: Math.min(b, item.reach || b), h: a, d: Math.max(a, Math.min(b, item.reach || b) * 0.08) };
  else if (item.shape === "rod" || item.shape === "tube") size = { w: b, h: a, d: a };
  else if (item.part_kind === "power" && item.shape !== "board" && (item.shape === "cylinder" || item.shape === "rod" || /aa|18650|cell/i.test(item.part_id || ""))) size = { w: Math.max(Math.min(a, c || a) * 1.5, b), h: Math.min(a, c || a), d: Math.min(a, c || a) };
  else if (item.part_kind === "motion" && /wheel|tyre|tire/i.test(`${item.name} ${item.part_id || ""}`)) size = { w: a, h: a, d: Math.max(4, b || a * 0.3) };
  else if (item.part_kind === "motion" && item.shape !== "board") size = { w: Math.max(a, b), h: Math.min(a, c || a), d: Math.min(a, c || a) };
  else if (item.shape === "cylinder") size = { w: a, h: b, d: a };
  else if (item.shape === "sphere") size = { w: a, h: a, d: a };
  else size = { w: a, h: b, d: c || a };
  const turn = ((item.turn_deg || 0) % 180 + 180) % 180;
  return turn >= 45 && turn < 135 ? { w: size.d, h: size.h, d: size.w } : size;
}

/* Where each item (and its copies) sits, in mm: { x, y, z } is the centre
   of its footprint at its bottom. Items with their own at_mm keep it; a
   board or plate is the base the rest is laid out on. */
export function layout(items) {
  const spots = new Map();
  const solid = items.filter((item) => item.role !== "casing");
  // The biggest board or plate is the base, pinned or not.
  const base = solid
    .filter((item) => item.shape === "board" || item.shape === "plate")
    .sort((one, two) => footprint(two).w * footprint(two).d - footprint(one).w * footprint(one).d)[0];
  let area = null;
  if (base) {
    const size = footprint(base);
    const [bx, by, bz] = base.at_mm || [0, 0, 0];
    if (!base.at_mm) spots.set(base.index, [{ x: 0, y: 0, z: 0 }]);
    area = { w: size.w, d: size.d, top: by + size.h, x: bx, z: bz };
  }
  const reach = area ? area.w * 0.9 : 200;
  for (const item of items) item.reach = reach;
  const free = solid
    .filter((item) => item !== base && !item.at_mm)
    .sort((one, two) => footprint(two).w * footprint(two).d - footprint(one).w * footprint(one).d);
  const totalArea = free.reduce((sum, item) => sum + footprint(item).w * footprint(item).d * Math.min(item.count || 1, MAX_COPIES), 0);
  const width = area ? area.w : Math.max(60, Math.sqrt(totalArea) * 1.4);
  const offsetX = area ? area.x : 0;
  const offsetZ = area ? area.z : 0;
  const startX = -width / 2 + GAP;
  let x = startX;
  let z = (area ? -area.d / 2 : -width / 2) + GAP;
  let rowDepth = 0;
  for (const item of free) {
    const size = footprint(item);
    const copies = [];
    for (let copy = 0; copy < Math.min(item.count || 1, MAX_COPIES); copy += 1) {
      if (x + size.w > width / 2 - GAP && x > startX) {
        x = startX;
        z += rowDepth + GAP;
        rowDepth = 0;
      }
      const onBase = area && z + size.d <= area.d / 2;
      copies.push({ x: offsetX + x + size.w / 2, y: onBase ? area.top : 0, z: offsetZ + z + size.d / 2 });
      x += size.w + GAP;
      rowDepth = Math.max(rowDepth, size.d);
    }
    spots.set(item.index, copies);
  }
  for (const item of items) {
    if (!item.at_mm) continue;
    const [px, py, pz] = item.at_mm;
    const size = footprint(item);
    const copies = [];
    for (let copy = 0; copy < Math.min(item.count || 1, MAX_COPIES); copy += 1) copies.push({ x: px + copy * (size.w + GAP), y: py, z: pz });
    spots.set(item.index, copies);
  }
  // A casing without a place goes round everything else.
  let min = [Infinity, Infinity];
  let max = [-Infinity, -Infinity];
  for (const item of solid) {
    const size = footprint(item);
    for (const spot of spots.get(item.index) || []) {
      min = [Math.min(min[0], spot.x - size.w / 2), Math.min(min[1], spot.z - size.d / 2)];
      max = [Math.max(max[0], spot.x + size.w / 2), Math.max(max[1], spot.z + size.d / 2)];
    }
  }
  const middle = Number.isFinite(min[0]) ? [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2] : [0, 0];
  for (const item of items) {
    if (item.role === "casing" && !item.at_mm) spots.set(item.index, [{ x: middle[0], y: 0, z: middle[1] }]);
  }
  return spots;
}

/* ------------------------------------------------------------------ view */

function mount(host, hooks = {}) {
  host.classList.add("lab3d");
  const view = stage(host, { camera: [0, 5.2, 7.2], fit: { radius: WORLD * 0.56, height: 1.2 }, autoRotate: false, fov: 38 });
  if (!view) return null;
  const { scene, camera, renderer, controls } = view;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  if (controls) {
    controls.enablePan = true;
    controls.minDistance = 2;
    controls.maxDistance = 30;
  }

  // A studio floor and soft light, like a product render.
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f96, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(4, 9, 5);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -7, right: 7, top: 7, bottom: -7, near: 0.5, far: 30 });
  key.shadow.bias = -0.0005;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xdfe8ff, 0.6);
  fill.position.set(-6, 4, -3);
  scene.add(fill);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({ color: 0x8e9196, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  const root = new THREE.Group();
  scene.add(root);

  // Labels: HTML over the canvas, with pointer lines to each part.
  const overlay = document.createElement("div");
  overlay.className = "lab3d-overlay";
  const lines = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  lines.setAttribute("class", "lab3d-lines");
  overlay.append(lines);
  host.append(overlay);

  const tools = document.createElement("div");
  tools.className = "lab3d-tools";
  host.append(tools);
  const tool = (text, label, onclick) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = text;
    button.setAttribute("aria-label", label);
    button.addEventListener("click", onclick);
    tools.append(button);
    return button;
  };

  let items = [];
  let groups = new Map(); // index -> THREE.Group (all copies)
  let labels = new Map(); // index -> { el, line }
  let scale = 1;
  let showLabels = true;
  let seeThrough = true;
  let selected = null;
  let fitted = false;
  let extentWas = 0;

  const labelsButton = tool("Labels: on", "Show or hide the labels", () => {
    showLabels = !showLabels;
    labelsButton.textContent = `Labels: ${showLabels ? "on" : "off"}`;
    overlay.hidden = !showLabels;
  });
  const casingButton = tool("Casing: see-through", "See through the casing or not", () => {
    seeThrough = !seeThrough;
    casingButton.textContent = `Casing: ${seeThrough ? "see-through" : "solid"}`;
    rebuild();
  });
  tool("↻ Turn", "Turn the chosen part a quarter", () => nudge({ turn: 90 }));
  tool("▲ Up", "Lift the chosen part 2 mm", () => nudge({ lift: 2 }));
  tool("▼ Down", "Lower the chosen part 2 mm", () => nudge({ lift: -2 }));
  tool("Auto layout", "Let the view lay out every part again", () => hooks.onLayout?.());
  tool("Reset view", "Look from the front again", () => {
    camera.position.set(0, 5.2, 7.2);
    controls?.target.set(0, 0, 0);
    fitted = false;
    fitCamera();
  });

  // Ask the AI to build or change it.
  const ask = document.createElement("form");
  ask.className = "lab3d-ask";
  ask.innerHTML = '<input type="text" aria-label="Ask the AI to build or change this design" placeholder="Ask the AI: add a cooling fan, put the battery under the board…" /><button class="primary" type="submit">Ask AI</button>';
  ask.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = ask.querySelector("input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    hooks.onAsk?.(text);
  });
  host.append(ask);

  function nudge({ turn = 0, lift = 0 }) {
    if (selected === null) {
      hooks.onHint?.("Click a part first.");
      return;
    }
    const placed = pinned();
    const mine = placed.find((row) => row.index === selected);
    if (!mine) return;
    mine.turn_deg = ((mine.turn_deg || 0) + turn) % 360;
    mine.at_mm = [mine.at_mm[0], Math.max(0, Math.round((mine.at_mm[1] + lift) * 10) / 10), mine.at_mm[2]];
    hooks.onPlace?.(placed);
  }

  // Where every part is now, so moving one pins them all.
  function pinned() {
    return items.map((item) => {
      const group = groups.get(item.index);
      const first = group?.userData.first || { x: 0, y: 0, z: 0 };
      return { index: item.index, at_mm: [round(first.x), round(first.y), round(first.z)], turn_deg: item.turn_deg || 0 };
    });
  }
  const round = (value) => Math.round(value * 10) / 10;

  function clearScene() {
    for (const group of groups.values()) {
      group.traverse((node) => {
        node.geometry?.dispose();
        for (const material of [].concat(node.material || [])) {
          material.map?.dispose(); // each board has its own copy
          material.dispose();
        }
      });
      root.remove(group);
    }
    groups = new Map();
    for (const { el, line } of labels.values()) {
      el.remove();
      line.remove();
    }
    labels = new Map();
  }

  function rebuild() {
    clearScene();
    const spots = layout(items);
    let min = new THREE.Vector3(Infinity, 0, Infinity);
    let max = new THREE.Vector3(-Infinity, 0, -Infinity);
    items.forEach((item) => {
      const size = footprint(item);
      const group = new THREE.Group();
      group.userData.index = item.index;
      const copies = spots.get(item.index) || [{ x: 0, y: 0, z: 0 }];
      group.userData.first = copies[0];
      copies.forEach((spot, number) => {
        const copy = body({ ...item, seeThrough }, item.alive, item.index + number);
        copy.position.set(spot.x, spot.y, spot.z);
        copy.rotation.y = THREE.MathUtils.degToRad(item.turn_deg || 0);
        group.add(copy);
        min = min.min(new THREE.Vector3(spot.x - size.w / 2, 0, spot.z - size.d / 2));
        max = max.max(new THREE.Vector3(spot.x + size.w / 2, spot.y + size.h, spot.z + size.d / 2));
      });
      group.traverse((node) => {
        if (node.isMesh) node.userData.index = item.index;
      });
      root.add(group);
      groups.set(item.index, group);
      const el = document.createElement("button");
      el.type = "button";
      el.className = `lab3d-label ${item.verdict ? `v-${item.verdict}` : ""} ${item.state ? `st-${item.state}` : ""}`;
      el.textContent = item.count > 1 ? `${item.name} ×${item.count}` : item.name;
      el.title = `${item.name}: ${item.materialName || ""}`;
      el.addEventListener("click", () => pick(item.index));
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      lines.append(line);
      overlay.append(el);
      labels.set(item.index, { el, line });
    });
    // Fit the design to the stage: its widest side becomes WORLD units.
    const extent = Number.isFinite(min.x) ? Math.max(max.x - min.x, max.z - min.z, max.y * 1.5, 1) : 100;
    if (!extentWas || Math.abs(extent - extentWas) / extentWas > 0.35) {
      scale = WORLD / extent;
      extentWas = extent;
      fitted = false;
    }
    root.scale.setScalar(scale);
    const centre = Number.isFinite(min.x) ? new THREE.Vector3((min.x + max.x) / 2, 0, (min.z + max.z) / 2) : new THREE.Vector3();
    root.position.set(-centre.x * scale, 0, -centre.z * scale);
    highlight();
    fitCamera();
  }

  function fitCamera() {
    if (fitted) return;
    fitted = true;
    camera.position.setLength(WORLD * 1.35);
    controls?.update();
  }

  function highlight() {
    for (const [index, group] of groups) {
      const on = index === selected;
      group.traverse((node) => {
        for (const material of [].concat(node.material || [])) {
          if (!material.emissive) continue;
          if (material.userData.glow === undefined) material.userData.glow = { colour: material.emissive.getHex(), strength: material.emissiveIntensity };
          material.emissive.setHex(on ? 0x2e7dff : material.userData.glow.colour);
          material.emissiveIntensity = on ? 0.12 : material.userData.glow.strength;
        }
      });
      labels.get(index)?.el.classList.toggle("on", on);
    }
  }

  function pick(index) {
    selected = index;
    highlight();
    hooks.onSelect?.(index);
  }

  // Labels follow their parts: a column down each side, pointing in.
  const anchor = new THREE.Vector3();
  const box = new THREE.Box3();
  function placeLabels() {
    if (!showLabels || !labels.size) return;
    const width = host.clientWidth;
    const height = host.clientHeight;
    lines.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const points = [];
    for (const [index, group] of groups) {
      box.setFromObject(group);
      if (box.isEmpty()) continue;
      box.getCenter(anchor);
      anchor.y = box.max.y;
      anchor.project(camera);
      points.push({ index, x: (anchor.x * 0.5 + 0.5) * width, y: (-anchor.y * 0.5 + 0.5) * height, behind: anchor.z > 1 });
    }
    const narrow = width < 560;
    for (const side of ["left", "right"]) {
      const mine = points.filter((point) => (point.x < width / 2) === (side === "left")).sort((one, two) => one.y - two.y);
      let floorY = 14;
      for (const point of mine) {
        const { el, line } = labels.get(point.index);
        const labelY = Math.max(floorY, Math.min(height - 104, point.y));
        floorY = labelY + (narrow ? 20 : 24);
        const edge = side === "left" ? 8 : width - 8;
        el.style.top = `${labelY - 10}px`;
        el.style.left = side === "left" ? `${edge}px` : "";
        el.style.right = side === "right" ? "8px" : "";
        el.classList.toggle("right", side === "right");
        el.hidden = point.behind;
        const box2 = el.getBoundingClientRect();
        const from = side === "left" ? edge + box2.width : edge - box2.width;
        line.setAttribute("x1", from);
        line.setAttribute("y1", labelY);
        line.setAttribute("x2", point.x);
        line.setAttribute("y2", point.y);
        line.style.display = point.behind ? "none" : "";
      }
    }
  }

  // Click to choose a part, drag to move it.
  const pointer = new THREE.Vector2();
  const caster = new THREE.Raycaster();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const hit = new THREE.Vector3();
  let drag = null;
  const canvas = renderer.domElement;
  const aim = (event) => {
    const rect = canvas.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    caster.setFromCamera(pointer, camera);
  };
  canvas.addEventListener("pointerdown", (event) => {
    aim(event);
    const found = caster.intersectObjects([...groups.values()], true)[0];
    if (!found) return;
    const index = found.object.userData.index;
    const group = groups.get(index);
    if (!group) return;
    if (controls) controls.enabled = false;
    plane.constant = -found.point.y;
    caster.ray.intersectPlane(plane, hit);
    drag = { index, group, start: hit.clone(), origin: group.position.clone(), moved: false, id: event.pointerId };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    aim(event);
    if (!drag) {
      const over = caster.intersectObjects([...groups.values()], true)[0];
      canvas.style.cursor = over ? "grab" : "";
      return;
    }
    if (!caster.ray.intersectPlane(plane, hit)) return;
    const shift = hit.clone().sub(drag.start);
    if (shift.length() > 0.02) drag.moved = true;
    drag.group.position.set(drag.origin.x + shift.x / scale, drag.origin.y, drag.origin.z + shift.z / scale);
    canvas.style.cursor = "grabbing";
  });
  const finish = () => {
    if (!drag) return;
    const { index, group, moved, id } = drag;
    drag = null;
    if (controls) controls.enabled = true;
    try {
      canvas.releasePointerCapture(id);
    } catch {
      /* already released */
    }
    canvas.style.cursor = "";
    if (!moved) {
      pick(index);
      return;
    }
    selected = index;
    const placed = pinned();
    const mine = placed.find((row) => row.index === index);
    mine.at_mm = [round(mine.at_mm[0] + group.position.x), mine.at_mm[1], round(mine.at_mm[2] + group.position.z)];
    hooks.onPlace?.(placed);
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", () => {
    // A cancelled touch (the page scrolled) puts the part back.
    if (!drag) return;
    drag.group.position.copy(drag.origin);
    if (controls) controls.enabled = true;
    drag = null;
  });

  // Labels move with the view; the stage's loop doesn't know about them,
  // so they follow on their own frame clock (paused when hidden).
  let ticking = 0;
  let api = null;
  const tick = () => {
    if (!host.isConnected) {
      api?.dispose(); // the Lab moved on without saying
      return;
    }
    ticking = requestAnimationFrame(tick);
    if (!document.hidden) placeLabels();
  };
  ticking = requestAnimationFrame(tick);

  let disposed = false;
  api = {
    show(next, options = {}) {
      const was = items;
      items = next.map((item) => ({ ...item, alive: Boolean(options.works) && (item.state === "ok" || item.state === "on") }));
      // A part removed or the parts reordered: the choice is dropped rather
      // than moved onto another part.
      const same = was.length === items.length && was.every((item, at) => item.name === items[at].name);
      if (selected !== null && !same) {
        selected = null;
        hooks.onSelect?.(null);
      }
      rebuild();
    },
    select(index) {
      selected = index;
      highlight();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(ticking);
      clearScene();
      overlay.remove();
      tools.remove();
      ask.remove();
      view.dispose();
      host.classList.remove("lab3d");
    },
  };
  return api;
}

window.FCCLab3D = { mount, layout };
