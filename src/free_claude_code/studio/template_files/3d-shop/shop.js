import * as THREE from "three";

const PRODUCTS = [
  { id: "boule", name: "Country sourdough", note: "Our everyday loaf: blistered crust, tangy open crumb.", spec: "78% hydration · 36 h", price: 12.5, badge: "Every day" },
  { id: "croissant", name: "Butter croissant", note: "27 layers of cultured butter, folded over two days.", spec: "27 layers · 210 °C", price: 6.0, badge: "Gone by 9" },
  { id: "roll", name: "Cinnamon scroll", note: "Brown butter, cassia and a cream cheese glaze.", spec: "Laminated · 18 min", price: 6.5 },
  { id: "baguette", name: "Baguette", note: "Five slashes, a crackling crust and a creamy middle.", spec: "75% hydration · 24 h", price: 6.0 },
];
const money = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" });
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ------------------------------------------------ cards, hours, form */
const cards = document.getElementById("cards");
for (const p of PRODUCTS) {
  const card = document.createElement("article");
  card.className = "card";
  card.dataset.id = p.id;
  card.innerHTML = `<div class="photo"><img alt="" data-photo="${p.id}"></div>${p.badge ? `<span class="badge"></span>` : ""}<div class="body"><h3></h3><p></p><div class="row"><span class="spec"></span><span class="price"></span></div></div>`;
  card.querySelector("img").alt = `${p.name}, drawn in 3D`;
  card.querySelector("h3").textContent = p.name;
  card.querySelector(".body p").textContent = p.note;
  card.querySelector(".spec").textContent = p.spec;
  card.querySelector(".price").textContent = money.format(p.price);
  if (p.badge) card.querySelector(".badge").textContent = p.badge;
  cards.append(card);
  const tilt = (x, y) => {
    const r = card.getBoundingClientRect();
    const nx = Math.min(1, Math.max(0, (x - r.left) / r.width));
    const ny = Math.min(1, Math.max(0, (y - r.top) / r.height));
    card.style.setProperty("--ry", `${(nx - 0.5) * 16}deg`);
    card.style.setProperty("--rx", `${(0.5 - ny) * 14}deg`);
    card.style.setProperty("--mx", `${nx * 100}%`);
    card.style.setProperty("--my", `${ny * 100}%`);
    card.style.setProperty("--px", `${(0.5 - nx) * 14}px`);
    card.style.setProperty("--py", `${(0.5 - ny) * 14}px`);
    card.style.setProperty("--lift", "-6px");
  };
  const rest = () => {
    for (const k of ["--rx", "--ry"]) card.style.setProperty(k, "0deg");
    for (const k of ["--px", "--py", "--lift"]) card.style.setProperty(k, "0px");
  };
  if (!reduce) {
    card.addEventListener("pointermove", (e) => tilt(e.clientX, e.clientY));
    card.addEventListener("pointerleave", rest);
    card.addEventListener("touchmove", (e) => { const t = e.touches[0]; if (t) tilt(t.clientX, t.clientY); }, { passive: true });
    card.addEventListener("touchend", rest);
  }
}

// The photos float a little as the page scrolls.
if (!reduce) {
  const imgs = () => document.querySelectorAll(".card .photo img");
  let ticking = false;
  window.addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      for (const img of imgs()) {
        const r = img.parentElement.getBoundingClientRect();
        const off = (r.top + r.height / 2 - innerHeight / 2) / innerHeight;
        img.parentElement.style.setProperty("--py", `${(-off * 18).toFixed(1)}px`);
        img.style.transform = `translate3d(var(--px, 0px), ${(-off * 18).toFixed(1)}px, 0) scale(1.02)`;
      }
    });
  }, { passive: true });
}

const HOURS = [["Monday", "Closed"], ["Tuesday", "6:30 am – 1 pm"], ["Wednesday", "6:30 am – 1 pm"], ["Thursday", "6:30 am – 1 pm"], ["Friday", "6:30 am – 2 pm"], ["Saturday", "7 am – 2 pm"], ["Sunday", "7 am – 12 pm"]];
const today = (new Date().getDay() + 6) % 7;
const tbody = document.getElementById("hours");
HOURS.forEach(([day, open], i) => {
  const tr = document.createElement("tr");
  if (i === today) tr.className = "today";
  tr.innerHTML = "<td></td><td></td>";
  tr.children[0].textContent = i === today ? `${day} (today)` : day;
  tr.children[1].textContent = open;
  tbody.append(tr);
});

const item = document.getElementById("item");
for (const p of PRODUCTS) item.add(new Option(`${p.name} · ${money.format(p.price)}`, p.id));
const daySelect = document.getElementById("day");
for (let i = 1; i <= 7 && daySelect.options.length < 5; i += 1) {
  const d = new Date(); d.setDate(d.getDate() + i);
  const idx = (d.getDay() + 6) % 7;
  if (HOURS[idx][1] === "Closed") continue;
  daySelect.add(new Option(d.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "short" }), d.toISOString().slice(0, 10)));
}
const form = document.getElementById("order");
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const err = document.getElementById("err");
  const done = document.getElementById("done");
  const name = document.getElementById("name").value.trim();
  const qty = Number(document.getElementById("qty").value);
  err.textContent = "";
  if (!name) { err.textContent = "Add your name so we can label the bag."; document.getElementById("name").focus(); return; }
  if (!Number.isInteger(qty) || qty < 1 || qty > 24) { err.textContent = "Choose between 1 and 24."; document.getElementById("qty").focus(); return; }
  const p = PRODUCTS.find((x) => x.id === item.value);
  const day = daySelect.selectedOptions[0].textContent;
  const order = `${qty} × ${p.name} for ${name}, ${day}: ${money.format(p.price * qty)} to pay at pickup.`;
  const say = (text) => { done.hidden = false; done.textContent = text; };
  // An order is never lost: a form service (data-endpoint) gets it, else the
  // visitor's email app opens with it addressed to the shop (data-email).
  const endpoint = form.dataset.endpoint;
  if (endpoint) {
    say("Sending…");
    fetch(endpoint, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        say(`Reserved: ${order}`);
        form.reset();
      })
      .catch(() => say("Sorry, that didn't send. Please call us instead."));
    return;
  }
  const to = form.dataset.email;
  if (!to) {
    say("Sorry, ordering isn't connected yet. Please call us instead.");
    return;
  }
  window.location.href = `mailto:${to}?subject=${encodeURIComponent(`Pickup order from ${name}`)}&body=${encodeURIComponent(order)}`;
  say(`Your email app is opening with your order: ${order} Press send there and it reaches us.`);
});

document.getElementById("copyPhone").addEventListener("click", () => {
  const note = document.getElementById("copyNote");
  const text = document.getElementById("phone").textContent;
  const select = () => {
    const range = document.createRange(); range.selectNodeContents(document.getElementById("phone"));
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    note.textContent = "Selected: copy it from your keyboard menu.";
  };
  if (!navigator.clipboard) { select(); return; }
  navigator.clipboard.writeText(text).then(() => { note.textContent = "Copied."; }, select);
});

(function draw3d() {
/* ------------------------------------------------------------- 3D */
const T = THREE;
let renderer;
try {
  renderer = new T.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: false });
} catch { return; } // no WebGL: the drawn fallback loaf stays
document.getElementById("fallback").remove();
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.outputColorSpace = T.SRGBColorSpace;
renderer.toneMapping = T.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = T.PCFShadowMap;
const stage = document.getElementById("stage");
stage.prepend(renderer.domElement);

// Small value noise for crust texture.
const hash = (x, y, z) => { const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453; return s - Math.floor(s); };
const smooth = (t) => t * t * (3 - 2 * t);
function noise(x, y, z) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
  const xf = smooth(x - xi), yf = smooth(y - yi), zf = smooth(z - zi);
  let v = 0;
  for (let dx = 0; dx < 2; dx++) for (let dy = 0; dy < 2; dy++) for (let dz = 0; dz < 2; dz++) {
    v += hash(xi + dx, yi + dy, zi + dz) * (dx ? xf : 1 - xf) * (dy ? yf : 1 - yf) * (dz ? zf : 1 - zf);
  }
  return v;
}
const C = (hex) => new T.Color(hex);
const mix = (a, b, t) => a.clone().lerp(b, Math.min(1, Math.max(0, t)));
function painted(geo, paint) {
  const pos = geo.attributes.position;
  const colors = new Float32Array(pos.count * 3);
  const v = new T.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    const c = paint(v, i); // three.js turns these sRGB colours linear itself
    colors.set([c.r, c.g, c.b], i * 3);
  }
  geo.setAttribute("color", new T.BufferAttribute(colors, 3));
  return geo;
}
const crustMat = () => new T.MeshStandardMaterial({ vertexColors: true, roughness: 0.78, metalness: 0 });
function shadowy(obj) { obj.traverse((n) => { if (n.isMesh) { n.castShadow = true; n.receiveShadow = true; } }); return obj; }

// A tube swept along a curve with a radius and shape that change along it.
function sweep(curve, steps, around, section) {
  const pos = [], idx = [];
  const up = new T.Vector3(0, 1, 0);
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const p = curve.getPointAt(t);
    const tan = curve.getTangentAt(t).normalize();
    const side = new T.Vector3().crossVectors(tan, up).normalize();
    for (let j = 0; j <= around; j++) {
      const a = (j / around) * Math.PI * 2;
      const [sx, sy] = section(t, a);
      pos.push(p.x + side.x * sx, p.y + sy, p.z + side.z * sx);
    }
  }
  for (let i = 0; i < steps; i++) for (let j = 0; j < around; j++) {
    const a = i * (around + 1) + j, b = a + around + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  return geo;
}

function boule() {
  const geo = new T.SphereGeometry(1, 120, 80);
  const pos = geo.attributes.position, v = new T.Vector3();
  const scored = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    let { x, y, z } = v;
    y = y < 0 ? y * 0.28 : y * 0.7;
    let r = 1 + (noise(x * 3, y * 3, z * 3) - 0.5) * 0.06;
    // A hand-cut cross on top, with the edges opened up (the "ear").
    let s = 0;
    if (v.y > 0.35) {
      const d = Math.min(Math.abs(x - z * 0.15), Math.abs(z + x * 0.1));
      s = Math.exp(-(d * d) / 0.004);
      y += -s * 0.09 + Math.exp(-((d - 0.09) ** 2) / 0.002) * 0.04;
    }
    scored[i] = s;
    pos.setXYZ(i, x * r, y * r + 0.28, z * r);
  }
  geo.computeVertexNormals();
  const dark = C("#5a2b10"), crust = C("#9c5520"), pale = C("#d9b27a"), flour = C("#efe6d6");
  painted(geo, (p, i) => {
    const n = noise(p.x * 9, p.y * 9, p.z * 9);
    let c = mix(crust, dark, (p.y - 0.25) * 1.3 + (n - 0.5) * 0.5);
    c = mix(c, pale, scored[i] * 1.2);
    if (p.y < 0.35 && p.y > 0.05 && noise(p.x * 14, p.y * 14, p.z * 14) > 0.62) c = mix(c, flour, 0.75);
    return c;
  });
  return shadowy(new T.Mesh(geo, crustMat()));
}

function croissant() {
  const curve = new T.CatmullRomCurve3([
    new T.Vector3(-1.25, 0, 0.55), new T.Vector3(-0.8, 0, -0.05), new T.Vector3(0, 0, -0.3),
    new T.Vector3(0.8, 0, -0.05), new T.Vector3(1.25, 0, 0.55),
  ]);
  const radius = (t) => {
    const body = Math.pow(Math.sin(Math.PI * t), 0.75) * 0.5 + 0.05;
    const rolls = 0.82 + 0.18 * Math.abs(Math.cos(t * Math.PI * 7));
    return body * rolls;
  };
  const geo = sweep(curve, 220, 40, (t, a) => {
    const r = radius(t);
    let y = Math.sin(a) * r * 0.86;
    if (y < -r * 0.35) y = -r * 0.35; // it sits flat on the tray
    return [Math.cos(a) * r, y + r * 0.35];
  });
  const deep = C("#7a3a10"), gold = C("#c07a2c"), light = C("#e8c58a");
  const along = [];
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) along.push(Math.floor(i / 41) / 220);
  painted(geo, (p, i) => {
    const t = along[i];
    const groove = 1 - Math.abs(Math.cos(t * Math.PI * 7));
    let c = mix(gold, deep, p.y * 1.6 + (noise(p.x * 8, p.y * 8, p.z * 8) - 0.5) * 0.4);
    return mix(c, light, groove * 0.55 - p.y * 0.2);
  });
  const mat = crustMat(); mat.roughness = 0.45; // egg-washed shine
  return shadowy(new T.Mesh(geo, mat));
}

function scroll() {
  const turns = 3.1, pts = [];
  for (let i = 0; i <= 260; i++) {
    const th = (i / 260) * turns * Math.PI * 2;
    const r = 0.12 + 0.13 * (th / (Math.PI * 2));
    pts.push(new T.Vector3(Math.cos(th) * r, 0, Math.sin(th) * r));
  }
  const curve = new T.CatmullRomCurve3(pts);
  const dough = sweep(curve, 520, 18, (t, a) => {
    const h = 0.34 - 0.08 * t;
    return [Math.cos(a) * 0.075, (Math.sin(a) * 0.5 + 0.5) * h];
  });
  const brown = C("#8a4416"), bake = C("#c98a46"), swirl = C("#5b2a0d");
  painted(dough, (p) => mix(mix(bake, brown, p.y * 3), swirl, noise(p.x * 30, p.y * 30, p.z * 30) * 0.5 - 0.15));
  const group = new T.Group();
  group.add(new T.Mesh(dough, crustMat()));
  const icing = sweep(curve, 520, 10, (t, a) => [Math.cos(a) * 0.06, 0.33 - 0.08 * t + Math.sin(a) * 0.03 + 0.02]);
  group.add(new T.Mesh(icing, new T.MeshStandardMaterial({ color: "#f3e7d6", roughness: 0.3 })));
  group.scale.setScalar(1.7);
  return shadowy(group);
}

function baguette() {
  const prof = [];
  for (let i = 0; i <= 40; i++) {
    const t = i / 40;
    prof.push(new T.Vector2(Math.max(0.001, Math.sin(Math.PI * t) ** 0.35 * 0.28), (t - 0.5) * 3.4));
  }
  const geo = new T.LatheGeometry(prof, 48);
  geo.rotateZ(Math.PI / 2);
  const pos = geo.attributes.position, v = new T.Vector3();
  const cut = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    let y = v.y > 0 ? v.y * 0.85 : v.y * 0.55;
    let s = 0;
    if (v.y > 0.12) {
      const band = ((v.x + v.z * 0.9) * 1.55 + 10) % 1;
      if (Math.abs(v.x) < 1.35) s = Math.exp(-((band - 0.5) ** 2) / 0.006);
      y -= s * 0.035;
    }
    cut[i] = s;
    pos.setXYZ(i, v.x, y + 0.16, v.z);
  }
  geo.computeVertexNormals();
  const dark = C("#6b3310"), crust = C("#b56b28"), crumb = C("#e7c48c");
  painted(geo, (p, i) => mix(mix(crust, dark, p.y * 2.2 + (noise(p.x * 7, p.y * 7, p.z * 7) - 0.5) * 0.5), crumb, cut[i]));
  return shadowy(new T.Mesh(geo, crustMat()));
}

function peel() {
  const g = new T.Group();
  const wood = new T.MeshStandardMaterial({ color: "#b88a5a", roughness: 0.85 });
  const board = new T.Mesh(new T.CylinderGeometry(2.7, 2.7, 0.12, 64), wood);
  board.position.y = -0.06; board.receiveShadow = true; g.add(board);
  const handle = new T.Mesh(new T.BoxGeometry(2.4, 0.11, 0.55), wood);
  handle.position.set(3.6, -0.06, 0); handle.receiveShadow = true; g.add(handle);
  return g;
}

// Studio light: warm oven glow, cool window rim.
function lights(scene) {
  scene.add(new T.HemisphereLight(0xfff1df, 0x3b4660, 0.75));
  const key = new T.DirectionalLight(0xffd9a8, 2.1);
  key.position.set(3, 6, 4); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5 });
  key.shadow.bias = -0.0008;
  scene.add(key);
  const rim = new T.DirectionalLight(0x9db8ff, 0.9);
  rim.position.set(-5, 3, -4); scene.add(rim);
}

const makers = { boule, croissant, roll: scroll, baguette };

// Product photos: each model rendered alone, then used on its card.
(function photos() {
  const scene = new T.Scene(); lights(scene);
  const cam = new T.PerspectiveCamera(32, 4 / 3.2, 0.1, 50);
  const floor = new T.Mesh(new T.PlaneGeometry(30, 30), new T.ShadowMaterial({ opacity: 0.22 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  renderer.setSize(640, 512, false);
  for (const p of PRODUCTS) {
    const model = makers[p.id]();
    model.rotation.y = { boule: 0.5, croissant: -0.35, roll: 0.3, baguette: -0.5 }[p.id];
    scene.add(model);
    const box = new T.Box3().setFromObject(model);
    const size = box.getSize(new T.Vector3()).length();
    const mid = box.getCenter(new T.Vector3());
    cam.position.set(mid.x + size * 0.15, mid.y + size * 0.62, mid.z + size * 1.25);
    cam.lookAt(mid);
    renderer.render(scene, cam);
    const url = renderer.domElement.toDataURL("image/png");
    const img = document.querySelector(`img[data-photo="${p.id}"]`);
    if (img) img.src = url;
    scene.remove(model);
  }
})();

// The hero: a peel with today's bake, turned by hand.
const scene = new T.Scene(); lights(scene);
const camera = new T.PerspectiveCamera(36, 1, 0.1, 80);
const board = new T.Group(); scene.add(board);
board.add(peel());
const items = {};
const place = (id, x, z, ry, s = 1) => {
  const m = makers[id](); m.position.set(x, 0, z); m.rotation.y = ry; m.scale.multiplyScalar(s);
  m.userData.id = id; board.add(m); items[id] = m; return m;
};
place("boule", -0.35, 0.25, 0.4, 1.05);
place("croissant", 1.25, 1.35, -0.6, 0.62);
place("roll", -1.55, 1.25, 0.3, 0.82);
place("baguette", 0.6, -1.45, 0.35, 0.9);
const shadowFloor = new T.Mesh(new T.PlaneGeometry(40, 40), new T.ShadowMaterial({ opacity: 0.18 }));
shadowFloor.rotation.x = -Math.PI / 2; shadowFloor.position.y = -0.13; shadowFloor.receiveShadow = true; scene.add(shadowFloor);

// Flour drifting in the oven light.
const dust = new T.BufferGeometry();
const N = 260, dpos = new Float32Array(N * 3);
for (let i = 0; i < N; i++) dpos.set([(Math.random() - 0.5) * 9, Math.random() * 4, (Math.random() - 0.5) * 9], i * 3);
dust.setAttribute("position", new T.BufferAttribute(dpos, 3));
const flour = new T.Points(dust, new T.PointsMaterial({ color: 0xfff4e0, size: 0.035, transparent: true, opacity: 0.7, depthWrite: false }));
scene.add(flour);

function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  const far = w < 520 ? 10.5 : 9;
  camera.position.set(0, far * 0.62, far * 0.86);
  camera.lookAt(0, 0.2, 0);
  camera.updateProjectionMatrix();
}
resize();
new ResizeObserver(resize).observe(stage);

// Drag to turn; the board keeps a little spin after you let go.
let turn = -0.35, spin = reduce ? 0 : 0.0025, dragging = false, lastX = 0, moved = 0, tilt = 0;
stage.addEventListener("pointerdown", (e) => { dragging = true; lastX = e.clientX; moved = 0; stage.setPointerCapture(e.pointerId); });
stage.addEventListener("pointermove", (e) => {
  const r = stage.getBoundingClientRect();
  tilt = ((e.clientY - r.top) / r.height - 0.5) * 0.25;
  if (!dragging) return;
  const dx = e.clientX - lastX; lastX = e.clientX; moved += Math.abs(dx);
  turn += dx * 0.008; spin = dx * 0.0016;
});
const tag = document.getElementById("tag"), hint = document.getElementById("hint");
const ray = new T.Raycaster(), pointer = new T.Vector2();
stage.addEventListener("pointerup", (e) => {
  dragging = false;
  if (moved > 6) return;
  const r = stage.getBoundingClientRect();
  pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  const hit = ray.intersectObjects(Object.values(items), true)[0];
  if (!hit) { tag.hidden = true; return; }
  let o = hit.object; while (o && !o.userData.id) o = o.parent;
  const p = PRODUCTS.find((x) => x.id === o.userData.id);
  tag.hidden = false;
  tag.innerHTML = "<strong></strong><span></span>";
  tag.querySelector("strong").textContent = p.name;
  tag.querySelector("span").textContent = `${p.spec} · ${money.format(p.price)}`;
  hint.textContent = "Tap another loaf, or drag to turn";
  lift = { id: p.id, t: 0 };
});
stage.addEventListener("pointercancel", () => { dragging = false; });

let lift = null, last = performance.now(), visible = true, running = false;
// One drawing loop at a time; it stops off screen and in a hidden tab.
const start = () => { if (running || !visible || document.hidden) return; running = true; last = performance.now(); requestAnimationFrame(loop); };
new IntersectionObserver((e) => { visible = e[0].isIntersecting; start(); }).observe(stage);
function loop(now) {
  if (!visible || document.hidden) { running = false; return; }
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  if (!dragging) { turn += spin; spin = spin * 0.96 + (reduce ? 0 : 0.0025) * 0.04; }
  board.rotation.y = turn;
  board.rotation.x += (tilt - board.rotation.x) * 0.08;
  // A tapped loaf hops up and turns to show itself.
  for (const [id, m] of Object.entries(items)) {
    const target = lift && lift.id === id ? 0.35 : 0;
    m.position.y += (target - m.position.y) * 0.12;
  }
  if (!reduce) {
    const a = dust.attributes.position;
    for (let i = 0; i < N; i++) {
      let y = a.getY(i) + dt * 0.12;
      if (y > 4) y = 0;
      a.setY(i, y);
      a.setX(i, a.getX(i) + Math.sin(now / 1500 + i) * 0.0015);
    }
    a.needsUpdate = true;
  }
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}
document.addEventListener("visibilitychange", start);
start();
})();
