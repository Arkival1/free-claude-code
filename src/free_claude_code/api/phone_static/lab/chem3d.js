// The Chemistry room's bench in 3D, in real sizes (1 unit = 1 cm): a glass
// beaker sized for what's in it, the liquid in its real colour (and layers),
// bubbles for every gas given off, precipitate that clouds and settles, solids
// on the bottom, foam, steam, frost, a Bunsen burner with flame-test colours,
// a thermometer, a pH strip, and the bottles that went in. It reads the mix
// result from science.js (the PC Lab's rules).
import { THREE, mesh, block, post, standard, metal, canvasTexture, label, glowSprite, dispose, pickable, puffTexture } from "./look3d.js";
import { fireMaterial } from "./kit.js";
import { indicatorColour, resolveChemical } from "./science.js";

const RADIUS = 4.3;
const HEIGHT = 11.5;
const INSIDE = 4.08;
const FLOOR = 0.35;
const FULL = 10.6;
const SIZES = [50, 100, 250, 600, 1000, 2000];

function gradTexture(capacity) {
  return canvasTexture(512, 256, (paint, w, h) => {
    paint.clearRect(0, 0, w, h);
    paint.strokeStyle = "rgba(255,255,255,0.85)";
    paint.fillStyle = "rgba(255,255,255,0.9)";
    paint.font = "bold 18px sans-serif";
    const steps = 5;
    for (let i = 1; i <= steps; i += 1) {
      const y = h - ((FLOOR + (i / steps) * FULL) / HEIGHT) * h;
      paint.lineWidth = 2;
      paint.beginPath();
      paint.moveTo(w * 0.1, y);
      paint.lineTo(w * 0.1 + 40, y);
      paint.stroke();
      paint.fillText(`${Math.round((capacity * i) / steps)}`, w * 0.1 + 46, y + 6);
    }
    paint.fillText(`${capacity} mL`, w * 0.1, h * 0.06 + 14);
  });
}

function labelTexture(name, formula, colour) {
  return canvasTexture(256, 160, (paint, w, h) => {
    paint.fillStyle = "#fbfaf6";
    paint.fillRect(0, 0, w, h);
    paint.fillStyle = colour;
    paint.fillRect(0, 0, w, 22);
    paint.fillStyle = "#1d1d1f";
    paint.font = "bold 26px sans-serif";
    const words = name.split(" ");
    let line = "";
    let y = 62;
    for (const word of words) {
      if (paint.measureText(`${line} ${word}`).width > w - 20 && line) {
        paint.fillText(line, 10, y);
        line = word;
        y += 30;
      } else line = line ? `${line} ${word}` : word;
    }
    paint.fillText(line, 10, y);
    paint.font = "22px sans-serif";
    paint.fillStyle = "#555";
    paint.fillText(formula || "", 10, h - 14);
  });
}

/** What's on the shelf behind the bench whatever is in the beaker. */
export const STOCK = ["water", "acetic-acid", "hydrochloric-acid", "sodium-hydroxide", "ammonia", "copper-sulfate", "silver-nitrate", "potassium-iodide", "hydrogen-peroxide-strong", "phenolphthalein", "ethanol", "sodium-bicarbonate", "sodium-chloride", "magnesium"];

/** One stock bottle: brown glass for solutions, a white jar for solids, a clear
 * bottle for plain liquids, each with its label; tap it to read about it. */
function stockBottle(chemical) {
  const holder = new THREE.Group();
  const solid = chemical.state === "solid";
  const plain = chemical.state === "liquid";
  const width = solid ? 1.7 : 1.45;
  const height = solid ? 3.4 : 5.4;
  const glass = solid
    ? standard("#f3f2ee", 0.55)
    : new THREE.MeshPhysicalMaterial({ color: plain ? "#e9f3fb" : "#7a4313", transparent: true, opacity: plain ? 0.35 : 0.78, roughness: 0.08, clearcoat: 1, depthWrite: !plain });
  holder.add(post(width, height, glass, 0, 0, 0, 24));
  if (!solid) {
    holder.add(post(width * 0.55, 0.9, glass, 0, height, 0, 20));
    if (plain) holder.add(post(width - 0.2, height * 0.6, standard(chemical.colour, 0.2, 0, { transparent: true, opacity: 0.6 }), 0, 0.12, 0, 20));
  }
  holder.add(post(solid ? width + 0.06 : width * 0.62, solid ? 0.9 : 1.1, standard(solid ? "#1f2a44" : "#202326", 0.45), 0, solid ? height : height + 0.9, 0, 20));
  const tag = mesh(new THREE.CylinderGeometry(width + 0.03, width + 0.03, solid ? 1.9 : 2.3, 24, 1, true, -0.65, 1.3), new THREE.MeshStandardMaterial({ map: labelTexture(chemical.name, chemical.formula, chemical.colour), roughness: 0.85, side: THREE.DoubleSide }), 0, height * 0.42, 0);
  tag.castShadow = false;
  holder.add(tag);
  pickable(holder, { type: "stock", id: chemical.id, name: chemical.name });
  return holder;
}

/** The bench around the beaker: a reagent shelf of labelled stock bottles, a
 * test-tube rack, a conical flask, a wash bottle, goggles and a notebook. */
function benchDressing() {
  const dressing = new THREE.Group();
  const wood = standard("#b9844f", 0.55);
  const steel = metal("#aab0b6", 0.35);
  // The shelf on the wall behind the bench, two rows of bottles.
  const shelf = new THREE.Group();
  shelf.position.set(0, 13, -16.5);
  for (const row of [0, 9]) {
    shelf.add(block(54, 0.6, 5, wood, 0, row, 0));
    for (const x of [-25, 25]) shelf.add(block(0.5, 2.4, 4, steel, x, row - 2.4, -0.5));
  }
  STOCK.map((id) => resolveChemical(id)).filter(Boolean).forEach((chemical, i) => {
    const bottle = stockBottle(chemical);
    const row = i < 7 ? 0 : 9;
    bottle.position.set(-22 + (i % 7) * 7.3, row + 0.6, 0);
    shelf.add(bottle);
  });
  dressing.add(shelf);
  // A test-tube rack with coloured tubes.
  const rack = new THREE.Group();
  rack.position.set(12.5, 0, -6.5);
  rack.add(block(11, 0.5, 3, wood, 0, 0, 0), block(11, 0.4, 3, wood, 0, 3.4, 0));
  for (const x of [-5.2, 5.2]) rack.add(block(0.4, 3.8, 3, wood, x, 0, 0));
  const tubeGlass = new THREE.MeshPhysicalMaterial({ color: "#f2f8ff", transparent: true, opacity: 0.32, roughness: 0.04, clearcoat: 1, depthWrite: false });
  ["#2f7cf6", "#3fbf6a", "#f06292", "#f5c542", "#e8eef5"].forEach((colour, i) => {
    const x = -4 + i * 2;
    rack.add(post(0.62, 7.5, tubeGlass, x, 0.5, 0, 16));
    rack.add(post(0.52, 2.2 + (i % 3), standard(colour, 0.2, 0, { transparent: true, opacity: 0.85 }), x, 0.6, 0, 16));
  });
  dressing.add(rack);
  // A conical flask with a green solution.
  const flask = new THREE.Group();
  flask.position.set(-12.5, 0, -2);
  const cone = [[0, 0], [3.2, 0], [3.3, 0.3], [1.0, 6.2], [1.0, 8.2], [1.2, 8.4], [0.85, 8.4], [0.85, 6.3], [2.95, 0.4], [0, 0.4]].map(([x, y]) => new THREE.Vector2(x, y));
  const flaskGlass = new THREE.MeshPhysicalMaterial({ color: "#f2f8ff", transparent: true, opacity: 0.28, roughness: 0.03, clearcoat: 1, side: THREE.DoubleSide, depthWrite: false });
  const glassBody = mesh(new THREE.LatheGeometry(cone, 40), flaskGlass);
  glassBody.renderOrder = 3;
  flask.add(glassBody);
  const fill = [[0, 0.4], [2.9, 0.4], [1.9, 3.0], [0, 3.0]].map(([x, y]) => new THREE.Vector2(x, y));
  flask.add(mesh(new THREE.LatheGeometry(fill, 40), standard("#46c27a", 0.15, 0, { transparent: true, opacity: 0.75 })));
  dressing.add(flask);
  // A wash bottle with its bent spout.
  const wash = new THREE.Group();
  wash.position.set(-18, 0, 4);
  wash.add(post(1.9, 6, standard("#f4f6f8", 0.35, 0, { transparent: true, opacity: 0.92 }), 0, 0, 0, 24));
  wash.add(post(1.0, 1.0, standard("#2b6fd6", 0.4), 0, 6, 0, 18));
  const spout = mesh(new THREE.CylinderGeometry(0.16, 0.16, 5, 8), standard("#f4f6f8", 0.4), 1.2, 8.6, 0);
  spout.rotation.z = -0.9;
  wash.add(spout);
  dressing.add(wash);
  // Goggles and a lab notebook on the bench.
  const goggles = new THREE.Group();
  goggles.position.set(17, 0.5, 6);
  goggles.rotation.y = -0.5;
  const lens = new THREE.MeshPhysicalMaterial({ color: "#d9f0ff", transparent: true, opacity: 0.45, roughness: 0.05, clearcoat: 1 });
  for (const x of [-1.6, 1.6]) {
    const eye = mesh(new THREE.CylinderGeometry(1.5, 1.5, 0.8, 24), lens, x, 0.4, 0);
    eye.rotation.x = Math.PI / 2;
    goggles.add(eye);
  }
  goggles.add(mesh(new THREE.TorusGeometry(2.6, 0.18, 8, 30, Math.PI), standard("#20242a", 0.5), 0, 0.5, -0.8).rotateX(-Math.PI / 2));
  dressing.add(goggles);
  const notebook = new THREE.Group();
  notebook.position.set(9, 0, 7);
  notebook.rotation.y = 0.25;
  notebook.add(block(7, 0.4, 9, standard("#24476b", 0.7), 0, 0, 0), block(6.6, 0.12, 8.6, standard("#f7f4ea", 0.9), 0.1, 0.4, 0));
  dressing.add(notebook);
  return dressing;
}

export function makeChemBench() {
  const group = new THREE.Group();
  const puff = puffTexture();
  // The beaker: thick glass turned on a lathe, with its graduations.
  const profile = [[0, 0], [RADIUS - 0.2, 0], [RADIUS, 0.25], [RADIUS, HEIGHT - 0.3], [RADIUS + 0.3, HEIGHT], [RADIUS + 0.12, HEIGHT + 0.05], [INSIDE + 0.06, HEIGHT - 0.3], [INSIDE + 0.06, FLOOR], [0, FLOOR]].map(([x, y]) => new THREE.Vector2(x, y));
  const glass = new THREE.MeshPhysicalMaterial({ color: "#eef7ff", transparent: true, opacity: 0.2, roughness: 0.03, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.02, side: THREE.DoubleSide, depthWrite: false, envMapIntensity: 1.6 });
  const vessel = new THREE.Group();
  group.add(vessel);
  const beaker = mesh(new THREE.LatheGeometry(profile, 56), glass);
  beaker.renderOrder = 3;
  beaker.castShadow = false;
  pickable(beaker, { type: "beaker" });
  vessel.add(beaker);
  let capacity = 250;
  let grad = gradTexture(capacity);
  const marks = mesh(new THREE.CylinderGeometry(RADIUS + 0.02, RADIUS + 0.02, HEIGHT, 48, 1, true, -0.7, 1.4), new THREE.MeshBasicMaterial({ map: grad, transparent: true, depthWrite: false }), 0, HEIGHT / 2, 0);
  marks.renderOrder = 4;
  marks.castShadow = false;
  vessel.add(marks);
  const frost = mesh(new THREE.CylinderGeometry(RADIUS + 0.05, RADIUS + 0.05, HEIGHT * 0.8, 48, 1, true), new THREE.MeshStandardMaterial({ color: "#ffffff", transparent: true, opacity: 0, roughness: 1, depthWrite: false }), 0, HEIGHT * 0.42, 0);
  frost.renderOrder = 5;
  vessel.add(frost);
  // The contents.
  const liquidMaterial = () => new THREE.MeshPhysicalMaterial({ color: "#e3f2ff", transparent: true, opacity: 0.3, roughness: 0.08, clearcoat: 0.6, depthWrite: false });
  const lower = mesh(new THREE.CylinderGeometry(INSIDE, INSIDE, 1, 48), liquidMaterial());
  const upper = mesh(new THREE.CylinderGeometry(INSIDE, INSIDE, 1, 48), liquidMaterial());
  for (const layer of [lower, upper]) {
    layer.renderOrder = 1;
    layer.castShadow = false;
    layer.visible = false;
    vessel.add(layer);
  }
  const settled = mesh(new THREE.CylinderGeometry(INSIDE - 0.05, INSIDE - 0.05, 0.3, 40), standard("#ffffff", 0.9), 0, FLOOR + 0.15, 0);
  settled.visible = false;
  vessel.add(settled);
  const lumps = new THREE.Group();
  vessel.add(lumps);
  const particleCount = 260;
  const particles = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(0.09), standard("#ffffff", 0.8), particleCount);
  particles.count = 0;
  particles.frustumCulled = false;
  vessel.add(particles);
  const bubbleCount = 180;
  const bubbles = new THREE.InstancedMesh(new THREE.SphereGeometry(0.12, 10, 8), new THREE.MeshPhysicalMaterial({ color: "#ffffff", transparent: true, opacity: 0.45, roughness: 0.05, clearcoat: 1, depthWrite: false }), bubbleCount);
  bubbles.count = 0;
  bubbles.frustumCulled = false;
  bubbles.renderOrder = 2;
  vessel.add(bubbles);
  const foamCount = 220;
  const foam = new THREE.InstancedMesh(new THREE.SphereGeometry(0.55, 10, 8), standard("#fbfbf6", 0.95), foamCount);
  foam.count = 0;
  foam.frustumCulled = false;
  vessel.add(foam);
  const clouds = [];
  for (let i = 0; i < 14; i += 1) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: puff, transparent: true, depthWrite: false, opacity: 0 }));
    sprite.userData.keepTexture = true;
    vessel.add(sprite);
    clouds.push({ sprite, phase: i / 14, spread: Math.random() });
  }
  // Thermometer, pH strip, burner.
  const thermometer = new THREE.Group();
  thermometer.position.set(2.2, FLOOR, -1.2);
  thermometer.rotation.z = -0.22;
  thermometer.add(post(0.22, 15, new THREE.MeshPhysicalMaterial({ color: "#ffffff", transparent: true, opacity: 0.35, roughness: 0.05, depthWrite: false }), 0, 0, 0, 12));
  thermometer.add(mesh(new THREE.SphereGeometry(0.3, 12, 10), standard("#d21f2f", 0.3), 0, 0.3, 0));
  const column = post(0.09, 1, standard("#d21f2f", 0.3), 0, 0.3, 0, 8);
  thermometer.add(column);
  group.add(thermometer);
  const strip = new THREE.Group();
  strip.position.set(7.5, 0, 5);
  strip.rotation.y = 0.4;
  strip.add(block(6, 0.05, 0.8, standard("#f7f3e6", 0.9), 0, 0, 0));
  const pad = block(1.2, 0.07, 0.8, standard("#43a047", 0.8), 2.2, 0, 0);
  strip.add(pad);
  strip.visible = false;
  group.add(strip);
  const readings = new THREE.Group();
  group.add(readings);
  const burner = new THREE.Group();
  burner.visible = false;
  burner.add(post(2.2, 0.6, metal("#3d4248", 0.5), 0, 0, 0, 24));
  burner.add(post(0.7, 7.5, metal("#b9bec4", 0.3), 0, 0.6, 0, 18));
  const flame = mesh(new THREE.ConeGeometry(1.3, 6, 18, 1, true), fireMaterial({ color: "#3d6bff", core: "#bfe0ff" }), 0, 11.2, 0);
  flame.castShadow = false;
  burner.add(flame);
  const flameGlow = glowSprite("#4f7dff", 6);
  flameGlow.position.y = 10.5;
  burner.add(flameGlow);
  const tripodMetal = metal("#2f3338", 0.45);
  for (let i = 0; i < 3; i += 1) {
    const leg = block(0.25, 13.5, 0.25, tripodMetal, 0, 0, 0);
    const angle = (i / 3) * Math.PI * 2;
    leg.position.set(Math.cos(angle) * 4.6, 0, Math.sin(angle) * 4.6);
    burner.add(leg);
  }
  burner.add(mesh(new THREE.TorusGeometry(4.6, 0.18, 8, 36), tripodMetal, 0, 13.5, 0).rotateX(Math.PI / 2));
  burner.add(block(10, 0.1, 10, metal("#9aa0a6", 0.7), 0, 13.55, 0));
  group.add(burner);
  const fireLight = new THREE.PointLight("#ff8a3d", 0, 40, 2);
  fireLight.position.set(0, 6, 4);
  group.add(fireLight);
  const bottles = new THREE.Group();
  group.add(bottles);
  group.add(benchDressing());

  let result = null;
  let started = 0;
  let steps = [];
  let fill = 0;
  let fromColour = new THREE.Color("#e3f2ff");
  let gasLevel = 0;
  let gasColours = [];
  let precipitate = null;
  let foamHeight = 0;
  let violent = false;
  let hot = false;
  let seeds = [];
  const matrix = new THREE.Matrix4();
  const colour = new THREE.Color();

  function clearGroup(target) {
    for (const child of [...target.children]) {
      target.remove(child);
      dispose(child);
    }
  }

  function setCapacity(volume) {
    const next = SIZES.find((size) => size >= volume * 1.15) || SIZES.at(-1);
    if (next === capacity) return;
    capacity = next;
    grad.dispose();
    grad = gradTexture(capacity);
    marks.material.map = grad;
    marks.material.needsUpdate = true;
  }

  function addBottles(ingredients) {
    clearGroup(bottles);
    ingredients.slice(0, 12).forEach((item, i) => {
      const x = -14 + (i % 6) * 5.6;
      const z = -9 - Math.floor(i / 6) * 5;
      const holder = new THREE.Group();
      holder.position.set(x, 0, z);
      const solid = item.unit === "g";
      const glassBody = new THREE.MeshPhysicalMaterial({ color: solid ? "#f2f2f2" : "#cfe6d8", transparent: true, opacity: solid ? 0.35 : 0.3, roughness: 0.05, clearcoat: 1, depthWrite: false });
      const height = solid ? 4.2 : 6.4;
      const width = solid ? 1.9 : 1.6;
      const bottle = post(width, height, glassBody, 0, 0, 0, 24);
      bottle.renderOrder = 3;
      holder.add(bottle);
      const contents = post(width - 0.18, height * 0.62, standard(item.colour, solid ? 0.95 : 0.2, 0, { transparent: !solid, opacity: solid ? 1 : 0.75 }), 0, 0.15, 0, 24);
      holder.add(contents);
      if (!solid) holder.add(post(0.7, 1.4, glassBody, 0, height, 0, 16));
      holder.add(post(solid ? width + 0.05 : 0.8, 0.9, standard(solid ? "#2b2b2b" : "#1f6feb", 0.5), 0, solid ? height : height + 1.4, 0, 20));
      const tag = mesh(new THREE.CylinderGeometry(width + 0.03, width + 0.03, 2.2, 24, 1, true, -0.6, 1.2), new THREE.MeshStandardMaterial({ map: labelTexture(item.name, item.formula, item.colour), roughness: 0.8, side: THREE.DoubleSide }), 0, height * 0.42, 0);
      tag.castShadow = false;
      holder.add(tag);
      pickable(holder, { type: "bottle", id: item.id, name: item.name });
      bottles.add(holder);
    });
  }

  /** Show a mix: the items going in and the result (null clears it). */
  function update(items, mix, { heat = false, flame: flameTest = false, pour = true } = {}) {
    result = mix;
    clearGroup(lumps);
    clearGroup(readings);
    addBottles(mix ? mix.ingredients : items.map((item) => ({ ...item, unit: item.unit || "mL", colour: item.colour || "#cfe8ff" })));
    burner.visible = Boolean(heat || flameTest);
    vessel.position.y = burner.visible ? 13.6 : 0;
    thermometer.position.y = vessel.position.y + FLOOR;
    started = performance.now() / 1000 - (pour ? 0 : 99);
    if (!mix) {
      lower.visible = upper.visible = settled.visible = false;
      particles.count = bubbles.count = foam.count = 0;
      frost.material.opacity = 0;
      strip.visible = false;
      gasLevel = 0;
      return;
    }
    const v = mix.vessel;
    setCapacity(v.volume_ml);
    fromColour = new THREE.Color(mix.ingredients[0] ? mix.ingredients[0].colour : "#e3f2ff");
    steps = v.colour_steps.length ? v.colour_steps : [v.colour];
    fill = Math.min(1, v.volume_ml / capacity);
    const layers = v.layers.length ? v.layers : [];
    lower.visible = layers.length > 0;
    upper.visible = layers.length > 1;
    if (layers[0]) {
      lower.material.opacity = Math.max(0.2, Math.min(0.96, layers[0].opacity));
      lower.userData.share = layers.length > 1 && v.volume_ml > 0 ? layers[0].ml / v.volume_ml : 1;
    }
    if (layers[1]) {
      upper.material.color.set(layers[1].colour);
      upper.material.opacity = Math.max(0.25, layers[1].opacity);
    }
    const solids = [...v.solids];
    const random = (() => {
      let seed = 7;
      return () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    })();
    for (const solid of solids) {
      const count = Math.max(3, Math.min(24, Math.round(Math.sqrt(solid.grams) * 6)));
      const metallic = /metal|deposit/.test(solid.name) || /^[A-Z][a-z]?$/.test(solid.formula);
      const material = standard(solid.colour, metallic ? 0.3 : 0.85, metallic ? 0.9 : 0, { emissive: v.effects.includes("glow") ? "#ff5a1a" : "#000000", emissiveIntensity: v.effects.includes("glow") ? 1.2 : 0 });
      for (let i = 0; i < count; i += 1) {
        const lump = mesh(new THREE.DodecahedronGeometry(0.35 + random() * 0.35), material, (random() - 0.5) * 5, FLOOR + 0.3, (random() - 0.5) * 5);
        lump.rotation.set(random() * 3, random() * 3, random() * 3);
        lumps.add(lump);
      }
    }
    precipitate = v.precipitates.length ? v.precipitates : null;
    if (precipitate) {
      particles.material.color.set(precipitate[0].colour);
      settled.material.color.set(precipitate[0].colour);
      particles.count = particleCount;
      seeds = Array.from({ length: particleCount }, () => [(Math.random() - 0.5) * 2 * (INSIDE - 0.4), Math.random(), (Math.random() - 0.5) * 2 * (INSIDE - 0.4), 0.4 + Math.random() * 0.8]);
    } else {
      particles.count = 0;
      settled.visible = false;
    }
    const levels = { "a few bubbles": 12, fizzing: 50, lots: 110, violent: 180 };
    gasLevel = Math.max(0, ...v.gases.map((gas) => levels[gas.level] || 0));
    gasColours = v.gases.filter((gas) => gas.colour && gas.colour.toLowerCase() !== "#ffffff" && gas.colour.toLowerCase() !== "#e8f4ff").map((gas) => gas.colour);
    foamHeight = v.foam * 16;
    violent = v.effects.includes("violent");
    hot = v.boiling || v.temperature_c > 60;
    frost.material.opacity = v.temperature_c < 3 ? 0.45 : 0;
    const temperature = v.temperature_c;
    column.scale.y = Math.max(0.2, Math.min(13.5, ((temperature + 20) / 140) * 13.5));
    column.position.y = 0.3;
    if (flameTest && v.flame) {
      flame.material.uniforms.color.value.set(v.flame.colour);
      flameGlow.material.color.set(v.flame.colour);
    } else {
      flame.material.uniforms.color.value.set("#3d6bff");
      flameGlow.material.color.set("#4f7dff");
    }
    fireLight.color.set(v.effects.includes("dazzle") ? "#ffffff" : v.effects.includes("glow") ? "#ff6a1a" : flameTest && v.flame ? v.flame.colour : "#ff8a3d");
    fireLight.userData.on = burner.visible || v.effects.includes("glow") || v.effects.includes("dazzle");
    fireLight.userData.dazzle = v.effects.includes("dazzle");
    strip.visible = v.ph !== null;
    if (v.ph !== null) pad.material.color.set(indicatorColour("universal-indicator", v.ph)[0]);
    const temp = label(`${temperature.toFixed(0)} °C`, { height: 2.4 });
    temp.position.set(4.5, vessel.position.y + 15.5, -1.2);
    readings.add(temp);
    if (v.ph !== null) {
      const ph = label(`pH ${v.ph.toFixed(1)}`, { height: 2.4 });
      ph.position.set(7.5, 2.5, 5);
      readings.add(ph);
    }
  }

  function tick(t) {
    if (!result) return;
    const age = t - started;
    const pour = Math.min(1, age / 1.4);
    // Liquid level and colour: pours in, then walks through its colour steps.
    const height = Math.max(0.12, fill * FULL * pour);
    const share = lower.userData.share ?? 1;
    lower.scale.y = height * share;
    lower.position.y = FLOOR + (height * share) / 2;
    upper.scale.y = Math.max(0.05, height * (1 - share));
    upper.position.y = FLOOR + height * share + upper.scale.y / 2;
    const stepTime = Math.max(0, age - 1.4);
    const index = Math.min(steps.length - 1, Math.floor(stepTime / 1.6));
    const next = Math.min(steps.length - 1, index + 1);
    const blend = Math.min(1, (stepTime % 1.6) / 1.6);
    if (age < 1.4) colour.copy(fromColour).lerp(new THREE.Color(steps[0]), pour);
    else colour.set(steps[index]).lerp(new THREE.Color(steps[next]), index === next ? 0 : blend);
    lower.material.color.copy(colour);
    const surface = FLOOR + height;
    // Precipitate: a cloud that slowly settles into a layer on the bottom.
    if (precipitate) {
      let down = 0;
      for (let i = 0; i < particles.count; i += 1) {
        const [x, start, z, speed] = seeds[i];
        const y = Math.max(FLOOR + 0.12, FLOOR + start * (surface - FLOOR) - Math.max(0, age - 0.8) * speed * 1.4);
        if (y <= FLOOR + 0.13) down += 1;
        matrix.makeTranslation(x, Math.min(y, surface - 0.1), z);
        particles.setMatrixAt(i, matrix);
      }
      particles.instanceMatrix.needsUpdate = true;
      settled.visible = down > particles.count * 0.4;
      settled.scale.y = Math.min(1.5, (down / particles.count) * 1.5);
    }
    // Bubbles rise through the liquid (and fizz at the top).
    const wanted = Math.round(gasLevel * pour);
    bubbles.count = height > 0.3 ? wanted : 0;
    for (let i = 0; i < bubbles.count; i += 1) {
      const speed = 2 + ((i * 37) % 10) * 0.6 * (violent ? 2 : 1);
      const phase = ((t * speed) / Math.max(1, height) + i * 0.137) % 1;
      const angle = i * 2.399;
      const r = ((i * 53) % 100) / 100 * (INSIDE - 0.4);
      const size = 0.5 + ((i * 17) % 10) / 10;
      matrix.makeScale(size, size, size).setPosition(Math.cos(angle) * r + Math.sin(t * 3 + i) * 0.15, FLOOR + 0.2 + phase * (height - 0.3), Math.sin(angle) * r);
      bubbles.setMatrixAt(i, matrix);
    }
    bubbles.instanceMatrix.needsUpdate = true;
    // Foam heaps up out of the beaker.
    const foamNow = foamHeight * Math.min(1, Math.max(0, age - 1) / 3);
    foam.count = foamNow > 0.2 ? foamCount : 0;
    for (let i = 0; i < foam.count; i += 1) {
      const level = (i / foamCount) * foamNow;
      const spill = Math.max(0, surface + level - HEIGHT) * 0.25;
      const angle = i * 2.399;
      const r = Math.min(INSIDE - 0.3, ((i * 31) % 100) / 100 * INSIDE) + spill;
      const size = 0.8 + ((i * 13) % 10) / 14 + Math.sin(t * 2 + i) * 0.05;
      matrix.makeScale(size, size, size).setPosition(Math.cos(angle) * r, surface + level, Math.sin(angle) * r);
      foam.setMatrixAt(i, matrix);
    }
    foam.instanceMatrix.needsUpdate = true;
    // Steam when hot, coloured gas when the gas has a colour.
    clouds.forEach((cloud, i) => {
      const phase = (t * 0.25 + cloud.phase) % 1;
      const coloured = gasColours.length && i % 2 === 0;
      const show = hot || coloured || (violent && i < 6);
      cloud.sprite.material.opacity = show ? (1 - phase) * (coloured ? 0.55 : 0.32) : 0;
      if (coloured) cloud.sprite.material.color.set(gasColours[i % gasColours.length]);
      else cloud.sprite.material.color.set("#ffffff");
      cloud.sprite.position.set(Math.sin(cloud.spread * 9 + t * 0.4) * 2 * phase, HEIGHT + phase * 9, Math.cos(cloud.spread * 7) * 1.5 * phase);
      cloud.sprite.scale.setScalar(2 + phase * 6);
    });
    vessel.position.x = violent && age < 8 ? Math.sin(t * 50) * 0.08 : 0;
    flame.material.uniforms.time.value = t;
    fireLight.intensity = fireLight.userData.on ? (fireLight.userData.dazzle ? 60 + Math.sin(t * 30) * 30 : 25 + Math.sin(t * 8) * 4) : 0;
  }

  return {
    group,
    update,
    tick,
    stop: () => {
      clearGroup(lumps);
      clearGroup(readings);
      clearGroup(bottles);
      dispose(group);
      grad.dispose();
      puff.dispose();
    },
  };
}
