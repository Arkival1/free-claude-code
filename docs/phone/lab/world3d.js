// The Lab box: a white cut-away case (two floors, four rooms and a glass
// lift) that the user turns, zooms and taps into, like a dollhouse.
// Chemistry and Electronics hold the real benches (chem3d.js, circuit3d.js);
// Blueprints shows saved chips, mixtures and inventions on its shelves and the
// drafting table; the Library holds build-your-own-x's tutorials, a book
// stack per topic. Jarvis walks (and rides the lift) to the room a job needs
// and works at its bench. FCC's own code on three.js.
import { THREE, mesh, block, post, standard, metal, glow, canvasTexture, label, dispose, pickable } from "./look3d.js";
import { makeCircuitBench } from "./circuit3d.js";
import { makeChemBench } from "./chem3d.js";
import { makeJarvis } from "./jarvis3d.js";

export const ROOMS = {
  chemistry: { name: "Chemistry", floor: 0, x: -3.45, spot: [-3.45, -1.5], face: Math.PI, view: { target: [-3.45, 1.5, -2.4], distance: 1.7, azimuth: 0.2, polar: 1.08 } },
  electronics: { name: "Electronics", floor: 0, x: 3.45, spot: [3.0, -1.45], face: Math.PI, view: { target: [3.3, 1.22, -2.4], distance: 1.45, azimuth: -0.12, polar: 0.95 } },
  blueprints: { name: "Blueprints", floor: 1, x: -3.45, spot: [-3.4, -0.35], face: Math.PI, view: { target: [-3.45, 5.0, -0.9], distance: 7.6, azimuth: 0.15, polar: 1.3 } },
  library: { name: "Library", floor: 1, x: 3.45, spot: [3.2, -1.2], face: Math.PI, view: { target: [3.45, 5.0, -0.9], distance: 7.6, azimuth: -0.15, polar: 1.3 } },
};
const OVERVIEW = { target: [0, 3.3, 0.2], distance: 18, azimuth: 0.55, polar: 1.18 };
const FLOOR_Y = [0.3, 3.6];
const LOBBY_Z = 2.1;
const HOME = { floor: 1, x: -1.9, z: 1.6 };
const BENCH_SCALE = 0.035;

/* ------------------------------------------------------------ looks */

function perforated() {
  return canvasTexture(128, 128, (paint, w, h) => {
    paint.fillStyle = "#f3f1ec";
    paint.fillRect(0, 0, w, h);
    paint.fillStyle = "#c9c6bf";
    for (let y = 8; y < h; y += 16) for (let x = (y / 16) % 2 ? 16 : 8; x < w; x += 16) {
      paint.beginPath();
      paint.arc(x, y, 3.6, 0, Math.PI * 2);
      paint.fill();
    }
  }, { repeat: [10, 5] });
}

const tiles = (base, grout, size = 8) =>
  canvasTexture(128, 128, (paint, w, h) => {
    paint.fillStyle = base;
    paint.fillRect(0, 0, w, h);
    paint.strokeStyle = grout;
    paint.lineWidth = 2;
    for (let i = 0; i <= size; i += 1) {
      paint.beginPath();
      paint.moveTo((i * w) / size, 0);
      paint.lineTo((i * w) / size, h);
      paint.moveTo(0, (i * h) / size);
      paint.lineTo(w, (i * h) / size);
      paint.stroke();
    }
  }, { repeat: [3, 3] });

const planks = () =>
  canvasTexture(256, 256, (paint, w, h) => {
    for (let i = 0; i < 8; i += 1) {
      paint.fillStyle = ["#b07a4a", "#a46e40", "#b9844f", "#9f6a3d"][i % 4];
      paint.fillRect(0, (i * h) / 8, w, h / 8);
      paint.fillStyle = "rgba(0,0,0,0.12)";
      paint.fillRect(0, ((i + 1) * h) / 8 - 2, w, 2);
      paint.fillRect(((i * 97) % w), (i * h) / 8, 2, h / 8);
    }
  }, { repeat: [2, 2] });

const pegboard = () =>
  canvasTexture(128, 128, (paint, w, h) => {
    paint.fillStyle = "#d9b98c";
    paint.fillRect(0, 0, w, h);
    paint.fillStyle = "#6d5536";
    for (let y = 8; y < h; y += 16) for (let x = 8; x < w; x += 16) {
      paint.beginPath();
      paint.arc(x, y, 2.5, 0, Math.PI * 2);
      paint.fill();
    }
  }, { repeat: [4, 2] });

function blueprintSheet(title, kind, lines) {
  return canvasTexture(512, 360, (paint, w, h) => {
    paint.fillStyle = "#1d4f91";
    paint.fillRect(0, 0, w, h);
    paint.strokeStyle = "rgba(255,255,255,0.12)";
    for (let x = 0; x < w; x += 16) {
      paint.beginPath();
      paint.moveTo(x, 0);
      paint.lineTo(x, h);
      paint.stroke();
    }
    for (let y = 0; y < h; y += 16) {
      paint.beginPath();
      paint.moveTo(0, y);
      paint.lineTo(w, y);
      paint.stroke();
    }
    paint.strokeStyle = "rgba(255,255,255,0.9)";
    paint.lineWidth = 3;
    let seed = [...title].reduce((total, char) => total + char.charCodeAt(0), 7);
    const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    paint.strokeRect(40, 70, w - 80, h - 140);
    for (let i = 0; i < 9; i += 1) {
      const x = 60 + random() * (w - 160);
      const y = 90 + random() * (h - 200);
      if (i % 3 === 0) paint.strokeRect(x, y, 40 + random() * 60, 26 + random() * 30);
      else {
        paint.beginPath();
        paint.arc(x, y, 10 + random() * 18, 0, Math.PI * 2);
        paint.stroke();
      }
      paint.beginPath();
      paint.moveTo(x, y);
      paint.lineTo(60 + random() * (w - 120), 90 + random() * (h - 180));
      paint.stroke();
    }
    paint.fillStyle = "#ffffff";
    paint.font = "bold 30px sans-serif";
    paint.fillText(title.slice(0, 26), 40, 48);
    paint.font = "20px sans-serif";
    paint.fillText(kind, 40, h - 40);
    (lines || []).slice(0, 2).forEach((line, i) => paint.fillText(line.slice(0, 40), 200, h - 40 - i * 24));
  });
}

/** An environment for reflections: a soft white studio. */
function studio(renderer) {
  const room = new THREE.Scene();
  const walls = new THREE.Mesh(new THREE.BoxGeometry(30, 20, 30), new THREE.MeshBasicMaterial({ color: "#5a6470", side: THREE.BackSide }));
  room.add(walls);
  const panel = (color, strength, position, size) => {
    const item = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(strength), side: THREE.DoubleSide }));
    item.position.set(...position);
    item.lookAt(0, 0, 0);
    room.add(item);
  };
  panel("#ffffff", 6, [0, 9.5, 0], [14, 10]);
  panel("#dff4ff", 3, [-14, 4, 4], [8, 8]);
  panel("#fff1dc", 3, [14, 4, -4], [8, 8]);
  panel("#7fe0ea", 1.5, [0, 2, 14], [20, 8]);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const target = pmrem.fromScene(room, 0.04);
  dispose(room);
  pmrem.dispose();
  return target;
}

/* ------------------------------------------------------------ the world */

export function makeWorld(canvas, { onPick = () => {}, onFocus = () => {} } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  const environment = studio(renderer);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.55;
  const camera = new THREE.PerspectiveCamera(38, 1, 0.03, 200);
  scene.add(new THREE.HemisphereLight("#eaf6ff", "#c8b49c", 0.9));
  const sun = new THREE.DirectionalLight("#fff3e0", 1.9);
  sun.position.set(7, 14, 11);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1536, 1536);
  sun.shadow.camera.left = sun.shadow.camera.bottom = -9;
  sun.shadow.camera.right = sun.shadow.camera.top = 9;
  sun.shadow.bias = -0.0004;
  scene.add(sun);
  const shadowCatcher = mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.22 }), 0, -0.001, 0);
  shadowCatcher.rotation.x = -Math.PI / 2;
  scene.add(shadowCatcher);

  /* --- the case --- */
  const box = new THREE.Group();
  scene.add(box);
  const shell = new THREE.MeshStandardMaterial({ map: perforated(), roughness: 0.55 });
  const white = standard("#f4f2ed", 0.5);
  box.add(block(12.8, 0.3, 6.4, white, 0, 0, 0));
  box.add(block(12.8, 0.32, 6.4, shell, 0, 6.9, 0));
  box.add(block(12.8, 7.2, 0.25, shell, 0, 0, -3.18));
  box.add(block(0.25, 7.2, 6.4, shell, -6.28, 0, 0));
  box.add(block(0.25, 7.2, 6.4, shell, 6.28, 0, 0));
  for (const x of [-3.45, 3.45]) box.add(block(5.5, 0.3, 6.4, white, x, 3.3, 0));
  for (const x of [-0.7, 0.7]) {
    box.add(block(0.18, 6.6, 4.3, white, x, 0.3, -1.05));
  }
  // Rounded front edges, like a moulded case.
  const trim = standard("#ffffff", 0.35);
  for (const y of [0.15, 7.06]) {
    const edge = mesh(new THREE.CylinderGeometry(0.17, 0.17, 12.8, 16), trim, 0, y, 3.2);
    edge.rotation.z = Math.PI / 2;
    box.add(edge);
  }
  for (const x of [-6.28, 6.28]) box.add(mesh(new THREE.CylinderGeometry(0.17, 0.17, 7.2, 16), trim, x, 3.6, 3.2));
  const sign = (text, x, y) => {
    const tag = label(text, { height: 0.42, background: "rgba(20,28,36,0.75)" });
    tag.position.set(x, y, 2.8);
    return tag;
  };
  const signs = new THREE.Group();
  for (const [id, room] of Object.entries(ROOMS)) {
    signs.add(sign(room.name, room.x, FLOOR_Y[room.floor] + 2.75));
    // A room is tapped through an invisible volume.
    const volume = new THREE.Mesh(new THREE.BoxGeometry(5.4, 3.0, 6), new THREE.MeshBasicMaterial({ visible: false }));
    volume.position.set(room.x, FLOOR_Y[room.floor] + 1.5, 0);
    pickable(volume, { type: "room", room: id });
    box.add(volume);
  }
  box.add(signs);
  const lamp = (x, y, colour = "#fff4e2") => {
    box.add(block(1.6, 0.05, 0.6, glow("#ffffff", 1.2), x, y - 0.06, -0.6));
    const light = new THREE.PointLight(colour, 7, 7, 1.6);
    light.position.set(x, y - 0.4, 0.2);
    box.add(light);
  };

  /* --- Chemistry (ground floor, left) --- */
  const chemFloor = new THREE.MeshStandardMaterial({ map: tiles("#e9eef0", "#c3ccd1"), roughness: 0.4 });
  box.add(block(5.5, 0.02, 6, chemFloor, -3.45, 0.3, 0));
  box.add(block(5.5, 3.0, 0.05, new THREE.MeshStandardMaterial({ map: tiles("#dff3ec", "#b9d8cc", 10), roughness: 0.5 }), -3.45, 0.3, -3.03));
  box.add(block(3.1, 0.88, 0.95, standard("#f7f7f5", 0.5), -3.45, 0.3, -2.5));
  box.add(block(3.2, 0.06, 1.05, standard("#22262b", 0.3), -3.45, 1.18, -2.47));
  for (let i = 0; i < 3; i += 1) box.add(block(0.9, 0.02, 0.02, metal(), -4.45 + i * 1.0, 0.85, -2.02));
  // Shelf of bottles on the left wall and a fume hood.
  box.add(block(0.4, 0.05, 2.6, standard("#f4f2ed", 0.5), -5.95, 2.0, -1.4));
  ["#e05050", "#4fa3e0", "#f2c94c", "#7ed957", "#b07be0", "#f2994a", "#56ccf2"].forEach((colour, i) => {
    box.add(post(0.08, 0.32, new THREE.MeshPhysicalMaterial({ color: colour, transparent: true, opacity: 0.8, roughness: 0.1, clearcoat: 1 }), -5.95, 2.05, -2.55 + i * 0.34, 12));
  });
  box.add(block(1.0, 2.4, 1.1, standard("#d9dee2", 0.4), -5.55, 0.3, 0.6));
  box.add(block(0.9, 1.2, 0.04, new THREE.MeshPhysicalMaterial({ color: "#cfe9ff", transparent: true, opacity: 0.35, roughness: 0.05 }), -5.55, 1.2, 1.16));
  box.add(post(0.25, 0.65, standard("#3a6ea5", 0.5), -2.0, 0.3, -1.1, 16));
  lamp(-3.45, 3.3);
  const chemistry = makeChemBench();
  chemistry.group.scale.setScalar(BENCH_SCALE);
  chemistry.group.position.set(-3.45, 1.243, -2.35);
  box.add(chemistry.group);

  /* --- Electronics (ground floor, right) --- */
  box.add(block(5.5, 0.02, 6, standard("#556b63", 0.8), 3.45, 0.3, 0));
  box.add(block(5.5, 3.0, 0.05, new THREE.MeshStandardMaterial({ map: pegboard(), roughness: 0.7 }), 3.45, 0.3, -3.03));
  box.add(block(3.4, 0.08, 1.15, new THREE.MeshStandardMaterial({ map: planks(), roughness: 0.6 }), 3.45, 1.1, -2.42));
  for (const [x, z] of [[1.85, -2.9], [5.05, -2.9], [1.85, -1.95], [5.05, -1.95]]) box.add(block(0.07, 0.8, 0.07, metal("#5f6670"), x, 0.3, z));
  // Parts drawers, an oscilloscope with a moving trace, tools on the pegboard.
  box.add(block(1.1, 1.3, 0.6, standard("#2f5d8a", 0.5), 5.55, 0.3, -0.8));
  for (let row = 0; row < 5; row += 1) for (let col = 0; col < 3; col += 1) box.add(block(0.3, 0.2, 0.02, standard(["#f2c94c", "#e05050", "#56ccf2"][col], 0.5), 5.2 + col * 0.35, 0.42 + row * 0.24, -0.49));
  const scope = canvasTexture(256, 160, () => {});
  const scopeScreen = new THREE.MeshStandardMaterial({ map: scope, emissive: "#ffffff", emissiveMap: scope, emissiveIntensity: 0.9 });
  const scopeBody = standard("#3b4148", 0.5);
  box.add(mesh(new THREE.BoxGeometry(0.75, 0.48, 0.42), [scopeBody, scopeBody, scopeBody, scopeBody, scopeScreen, scopeBody], 4.75, 1.42, -2.75));
  for (const [x, y, w, h, colour] of [[2.2, 2.2, 0.08, 0.5, "#e05050"], [2.6, 2.3, 0.5, 0.06, "#c9ccd1"], [3.2, 2.15, 0.1, 0.45, "#f2c94c"], [3.8, 2.25, 0.35, 0.35, "#2f2f2f"]]) box.add(block(w, h, 0.05, standard(colour, 0.4, colour === "#c9ccd1" ? 1 : 0), x, y, -2.96));
  lamp(3.45, 3.3);
  const electronics = makeCircuitBench();
  electronics.group.scale.setScalar(BENCH_SCALE);
  electronics.group.position.set(3.45, 1.183, -2.5);
  box.add(electronics.group);

  /* --- Blueprints (upper floor, left) --- */
  box.add(block(5.5, 0.02, 6, standard("#2c4a7a", 0.9), -3.45, 3.6, 0));
  box.add(block(5.5, 3.0, 0.05, standard("#e8eef7", 0.7), -3.45, 3.6, -3.03));
  const table = new THREE.Group();
  table.position.set(-3.4, 3.6, -1.05);
  for (const [x, z] of [[-0.8, -0.4], [0.8, -0.4], [-0.8, 0.4], [0.8, 0.4]]) table.add(block(0.06, 0.95, 0.06, metal("#4b5563"), x, 0, z));
  let sheet = blueprintSheet("Blueprints", "Save a chip, a mixture or an invention", []);
  const sheetMaterial = new THREE.MeshStandardMaterial({ map: sheet, roughness: 0.8 });
  const board = mesh(new THREE.BoxGeometry(1.9, 0.04, 1.3), [white, white, sheetMaterial, white, white, white], 0, 1.05, 0);
  board.rotation.x = 0.35;
  table.add(board);
  box.add(table);
  const shelves = new THREE.Group();
  for (let row = 0; row < 3; row += 1) shelves.add(block(4.6, 0.06, 0.45, standard("#f4f2ed", 0.5), -3.45, 4.15 + row * 0.75, -2.78));
  box.add(shelves);
  const showcase = new THREE.Group();
  box.add(showcase);
  box.add(block(1.2, 0.75, 0.6, standard("#f4f2ed", 0.5), -1.55, 3.6, 1.6));
  box.add(post(0.22, 0.4, standard("#e4e7ea", 0.5), -5.4, 3.6, 2.0, 16));
  box.add(mesh(new THREE.ConeGeometry(0.45, 1.0, 7), standard("#3fa34d", 0.7), -5.4, 4.5, 2.0));
  lamp(-3.45, 6.6);

  /* --- Library (upper floor, right) --- */
  box.add(block(5.5, 0.02, 6, new THREE.MeshStandardMaterial({ map: planks(), roughness: 0.6 }), 3.45, 3.6, 0));
  box.add(block(5.5, 3.0, 0.05, standard("#efe2cf", 0.8), 3.45, 3.6, -3.03));
  const wood = standard("#8a5a35", 0.6);
  for (const x of [1.6, 3.45, 5.3]) {
    box.add(block(1.75, 2.7, 0.45, wood, x, 3.6, -2.78));
  }
  const books = new THREE.Group();
  box.add(books);
  box.add(block(2.4, 0.03, 1.6, standard("#c0504d", 0.95), 3.3, 3.62, 0.9));
  const chair = standard("#e0763a", 0.7);
  box.add(block(0.9, 0.45, 0.85, chair, 4.9, 3.6, 1.0));
  box.add(block(0.9, 0.8, 0.2, chair, 4.9, 3.6, 0.55));
  box.add(post(0.03, 1.6, metal("#2b2b2b"), 5.75, 3.6, 0.3, 8));
  box.add(mesh(new THREE.ConeGeometry(0.28, 0.3, 16, 1, true), glow("#fff1d0", 0.8), 5.75, 5.3, 0.3));
  box.add(post(0.2, 0.35, standard("#2b6cb0", 0.5), 1.6, 3.6, 1.9, 16));
  for (let i = 0; i < 6; i += 1) {
    const leaf = mesh(new THREE.ConeGeometry(0.08, 0.9, 5), standard("#2f9e44", 0.7), 1.6, 4.3, 1.9);
    leaf.rotation.set(Math.sin(i) * 0.6, 0, Math.cos(i * 1.7) * 0.6);
    box.add(leaf);
  }
  lamp(3.45, 6.6, "#ffe2b8");

  /* --- the lift --- */
  const liftGlass = new THREE.MeshPhysicalMaterial({ color: "#d8f4ff", transparent: true, opacity: 0.18, roughness: 0.03, clearcoat: 1, depthWrite: false, side: THREE.DoubleSide });
  const shaft = mesh(new THREE.CylinderGeometry(0.62, 0.62, 6.6, 28, 1, true), liftGlass, 0, 3.6, LOBBY_Z);
  shaft.castShadow = false;
  box.add(shaft);
  const platform = post(0.58, 0.08, metal("#aab2bb", 0.35), 0, FLOOR_Y[1] - 0.08, LOBBY_Z, 28);
  box.add(platform);

  /* --- Jarvis --- */
  const jarvis = makeJarvis();
  jarvis.root.scale.setScalar(0.95);
  box.add(jarvis.root);
  const walker = { floor: HOME.floor, path: [], state: "wave", until: 3, after: "idle", room: null, facing: 0 };
  jarvis.root.position.set(HOME.x, FLOOR_Y[HOME.floor], HOME.z);

  /* --- orbit and taps --- */
  const view = { ...OVERVIEW, target: new THREE.Vector3(...OVERVIEW.target) };
  const goal = { ...OVERVIEW, target: new THREE.Vector3(...OVERVIEW.target) };
  let focused = null;
  const pointers = new Map();
  let downAt = null;
  const onDown = (event) => {
    canvas.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 1) downAt = { x: event.clientX, y: event.clientY, time: performance.now(), moved: 0 };
  };
  const onMove = (event) => {
    const last = pointers.get(event.pointerId);
    if (!last) return;
    const dx = event.clientX - last.x;
    const dy = event.clientY - last.y;
    if (pointers.size === 1) {
      goal.azimuth -= dx * 0.008;
      goal.polar = Math.max(0.25, Math.min(1.5, goal.polar - dy * 0.006));
      if (downAt) downAt.moved += Math.abs(dx) + Math.abs(dy);
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const before = Math.hypot(a.x - b.x, a.y - b.y);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      const [c, d] = [...pointers.values()];
      const after = Math.hypot(c.x - d.x, c.y - d.y);
      if (before > 0 && after > 0) goal.distance = Math.max(0.5, Math.min(30, goal.distance * (before / after)));
      if (downAt) downAt.moved += 99;
      return;
    }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  };
  const onUp = (event) => {
    pointers.delete(event.pointerId);
    if (downAt && pointers.size === 0 && downAt.moved < 8 && performance.now() - downAt.time < 450) tap(event);
    if (pointers.size === 0) downAt = null;
  };
  const onWheel = (event) => {
    event.preventDefault();
    goal.distance = Math.max(0.5, Math.min(30, goal.distance * (1 + event.deltaY * 0.001)));
  };
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointercancel", onUp);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  function pickAt(x, y) {
    const rect = canvas.getBoundingClientRect();
    pointer.set(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObject(box, true);
    for (const hit of hits) {
      if (hit.object.userData.label || hit.object.isSprite) continue;
      let object = hit.object;
      while (object && !object.userData.pick) object = object.parent;
      if (!object) continue;
      const what = object.userData.pick;
      if (what.type === "room" && focused && hits.some((other) => other.object !== hit.object && !other.object.isSprite && findPick(other.object) && findPick(other.object).type !== "room")) continue;
      if (what.type === "books" && hit.instanceId !== undefined) return { type: "topic", topic: what.topics[hit.instanceId] };
      return what;
    }
    return null;
  }
  const findPick = (object) => {
    while (object && !object.userData.pick) object = object.parent;
    return object ? object.userData.pick : null;
  };
  function tap(event) {
    const what = pickAt(event.clientX, event.clientY);
    if (!what) return;
    if (what.type === "room") {
      if (focused !== what.room) focus(what.room);
      return;
    }
    onPick(what);
  }

  /** Fly the camera to a room (null for the whole box). */
  function focus(room) {
    focused = room && ROOMS[room] ? room : null;
    const target = focused ? ROOMS[focused].view : OVERVIEW;
    goal.target.set(...target.target);
    goal.distance = target.distance;
    goal.azimuth = target.azimuth;
    goal.polar = target.polar;
    signs.visible = !focused;
    onFocus(focused);
  }

  /* --- Jarvis walking --- */
  function routeTo(floor, x, z) {
    const here = jarvis.root.position;
    const path = [];
    if (floor !== walker.floor) {
      path.push({ x: 0, z: LOBBY_Z, floor: walker.floor });
      path.push({ x: 0, z: LOBBY_Z, floor, ride: true });
    } else if (Math.sign(x) !== Math.sign(here.x) && Math.abs(here.x) > 0.8) path.push({ x: 0, z: LOBBY_Z, floor });
    path.push({ x, z, floor });
    return path;
  }

  /** Send Jarvis to a room (or home) to work, think or wave, saying something. */
  function jarvisTo(room, { doing = "work", say = "", seconds = 0 } = {}) {
    const spot = room && ROOMS[room] ? { floor: ROOMS[room].floor, x: ROOMS[room].spot[0], z: ROOMS[room].spot[1] } : HOME;
    walker.path = routeTo(spot.floor, spot.x, spot.z);
    walker.room = room;
    walker.after = doing;
    walker.seconds = seconds;
    walker.until = 0;
    walker.state = "walk";
    jarvis.say(say);
  }

  function walk(dt) {
    if (!walker.path.length) return;
    const step = walker.path[0];
    const position = jarvis.root.position;
    if (step.ride) {
      const y = FLOOR_Y[step.floor];
      const dy = y - position.y;
      const move = Math.sign(dy) * Math.min(Math.abs(dy), dt * 1.6);
      position.y += move;
      platform.position.y = position.y - 0.08;
      walker.state = "idle";
      if (Math.abs(dy) < 0.01) {
        position.y = y;
        walker.floor = step.floor;
        walker.path.shift();
      }
      return;
    }
    const dx = step.x - position.x;
    const dz = step.z - position.z;
    const distance = Math.hypot(dx, dz);
    walker.state = "walk";
    if (distance < 0.03) {
      walker.path.shift();
      if (!walker.path.length) {
        walker.state = walker.after;
        walker.facing = walker.room ? ROOMS[walker.room].face : 0;
        if (walker.seconds) walker.until = clock.elapsedTime + walker.seconds;
      }
      return;
    }
    const speed = Math.min(distance, dt * 1.25);
    position.x += (dx / distance) * speed;
    position.z += (dz / distance) * speed;
    walker.facing = Math.atan2(dx, dz);
    if (Math.abs(step.x) < 0.1 && step.z === LOBBY_Z) platform.position.y = FLOOR_Y[walker.floor] - 0.08;
  }

  /* --- what the rooms show --- */
  function setBlueprints(list, selected = null) {
    for (const child of [...showcase.children]) {
      showcase.remove(child);
      dispose(child);
    }
    list.slice(0, 18).forEach((print, i) => {
      const x = -5.3 + (i % 6) * 0.74;
      const y = 4.21 + Math.floor(i / 6) * 0.75;
      const item = new THREE.Group();
      item.position.set(x, y, -2.75);
      if (print.kind === "chip") {
        item.add(block(0.32, 0.06, 0.32, standard("#151515", 0.4), 0, 0.03, 0));
        for (let p = 0; p < 6; p += 1) for (const side of [-1, 1]) item.add(block(0.03, 0.02, 0.06, metal("#d4af37", 0.25), -0.13 + p * 0.052, 0.02, side * 0.19));
        item.add(block(0.2, 0.01, 0.2, glow(print.colour || "#5fe1ff", 0.6), 0, 0.09, 0));
      } else if (print.kind === "mixture") {
        item.add(mesh(new THREE.SphereGeometry(0.16, 16, 12), new THREE.MeshPhysicalMaterial({ color: print.colour || "#7fd8ff", transparent: true, opacity: 0.75, roughness: 0.05, clearcoat: 1 }), 0, 0.16, 0));
        item.add(post(0.05, 0.22, new THREE.MeshPhysicalMaterial({ color: "#ffffff", transparent: true, opacity: 0.4 }), 0, 0.28, 0, 10));
      } else {
        const roll = post(0.08, 0.5, standard("#2c5aa0", 0.6), 0, 0.1, 0, 14);
        roll.rotation.z = Math.PI / 2;
        roll.position.set(0, 0.1, 0);
        item.add(roll);
        item.add(post(0.085, 0.05, standard("#f2c94c", 0.5), 0.12, 0.02, 0, 14).rotateZ(Math.PI / 2));
      }
      pickable(item, { type: "blueprint", id: print.id });
      showcase.add(item);
    });
    const shown = selected || list[0];
    sheet.dispose();
    sheet = shown ? blueprintSheet(shown.name, `${shown.kind} · version ${shown.versions.length}`, [shown.summary || ""]) : blueprintSheet("Blueprints", "Save a chip, a mixture or an invention", []);
    sheetMaterial.map = sheet;
    sheetMaterial.needsUpdate = true;
  }

  function setTopics(topics) {
    for (const child of [...books.children]) {
      books.remove(child);
      dispose(child);
    }
    const counts = topics.map((topic) => Math.max(3, Math.min(9, topic.count)));
    const total = counts.reduce((a, b) => a + b, 0);
    const shelfBooks = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), standard("#ffffff", 0.7), total);
    const owners = [];
    const matrix = new THREE.Matrix4();
    const colour = new THREE.Color();
    let index = 0;
    let x = 0.85;
    let row = 0;
    topics.forEach((topic, t) => {
      colour.setHSL((t * 0.137) % 1, 0.55, 0.45);
      for (let i = 0; i < counts[t]; i += 1) {
        const height = 0.34 + ((i * 7 + t) % 5) * 0.04;
        const thick = 0.06 + ((i + t) % 3) * 0.015;
        if (x + thick > 6.1) {
          x = 0.85;
          row += 1;
        }
        matrix.makeScale(thick, height, 0.32).setPosition(x + thick / 2, 3.95 + row * 0.62 + height / 2, -2.7);
        shelfBooks.setMatrixAt(index, matrix);
        shelfBooks.setColorAt(index, colour.clone().offsetHSL(0, 0, ((i % 3) - 1) * 0.06));
        owners.push(topic.topic);
        index += 1;
        x += thick + 0.008;
      }
      x += 0.08;
    });
    shelfBooks.castShadow = true;
    pickable(shelfBooks, { type: "books", topics: owners });
    books.add(shelfBooks);
    for (let r = 0; r <= row; r += 1) for (const cx of [1.6, 3.45, 5.3]) books.add(block(1.65, 0.04, 0.42, standard("#6e4527", 0.6), cx, 3.9 + r * 0.62, -2.72));
  }

  /* --- the loop --- */
  // Time without THREE.Clock (deprecated in r186): seconds since start.
  const clock = { start: performance.now(), last: performance.now(), elapsedTime: 0 };
  let frame = 0;
  const drawScope = (t) => {
    const paint = scope.image.getContext("2d");
    paint.fillStyle = "#04140c";
    paint.fillRect(0, 0, 256, 160);
    paint.strokeStyle = "#3dff8f";
    paint.lineWidth = 3;
    paint.beginPath();
    for (let x = 0; x < 256; x += 4) paint.lineTo(x, 80 + Math.sin(x * 0.06 + t * 4) * 40 * (0.6 + 0.4 * Math.sin(t)));
    paint.stroke();
    scope.needsUpdate = true;
  };
  function loop() {
    const now = performance.now();
    const dt = Math.min(0.05, (now - clock.last) / 1000);
    clock.last = now;
    clock.elapsedTime = (now - clock.start) / 1000;
    const t = clock.elapsedTime;
    const width = canvas.clientWidth || 320;
    const height = canvas.clientHeight || 240;
    if (canvas.width !== Math.round(width * renderer.getPixelRatio()) || canvas.height !== Math.round(height * renderer.getPixelRatio())) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.fov = camera.aspect < 1 ? 50 : 38;
      camera.updateProjectionMatrix();
    }
    const ease = Math.min(1, dt * 4);
    view.target.lerp(goal.target, ease);
    view.distance += (goal.distance - view.distance) * ease;
    view.azimuth += (goal.azimuth - view.azimuth) * ease;
    view.polar += (goal.polar - view.polar) * ease;
    const fit = camera.aspect < 1 && !focused ? 0.95 / Math.max(0.55, camera.aspect) : 1;
    const reach = view.distance * fit;
    camera.position.set(view.target.x + reach * Math.sin(view.polar) * Math.sin(view.azimuth), view.target.y + reach * Math.cos(view.polar), view.target.z + reach * Math.sin(view.polar) * Math.cos(view.azimuth));
    camera.lookAt(view.target);
    walk(dt);
    if (!walker.path.length && walker.until && t > walker.until) {
      walker.state = "idle";
      walker.until = 0;
    }
    jarvis.pose(walker.state, t);
    jarvis.root.rotation.y += ((walker.facing - jarvis.root.rotation.y + Math.PI * 3) % (Math.PI * 2) - Math.PI) * Math.min(1, dt * 8);
    chemistry.tick(t, dt);
    electronics.tick(t, dt);
    if (frame % 3 === 0) drawScope(t);
    renderer.render(scene, camera);
    frame = requestAnimationFrame(loop);
  }
  frame = requestAnimationFrame(loop);
  canvas.dataset.ready = "true";

  return {
    focus,
    get focused() {
      return focused;
    },
    jarvisTo,
    get jarvisRoom() {
      return walker.path.length ? null : walker.room;
    },
    setChemistry: (items, result, options) => chemistry.update(items, result, options),
    setCircuit: (entries, result, powered) => electronics.update(entries, result, powered),
    setLabels: (on) => {
      electronics.setLabels(on);
    },
    setBlueprints,
    setTopics,
    stop() {
      cancelAnimationFrame(frame);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      canvas.removeEventListener("wheel", onWheel);
      chemistry.stop();
      electronics.stop();
      dispose(scene);
      environment.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
