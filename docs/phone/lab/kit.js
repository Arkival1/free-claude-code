// FCC Game Lab kit (three.js r186): original building blocks for 3D games.
// Textures are drawn in code (seeded noise), shaders are written here, models
// are built from shapes, and characters move by procedural animation, so a
// game made with the kit has no outside art to licence. Import it from a
// game: import * as Lab from "./lab/kit.js";
import * as THREE from "three";

// ----------------------------------------------------------------- noise

/** A seeded random number maker (mulberry32): the same seed, the same world. */
export function seeded(seed = 1) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Smooth tiling value noise: noise(x, y) in 0..1, repeating every `period`. */
export function valueNoise(seed = 1, period = 8) {
  const random = seeded(seed);
  const grid = Array.from({ length: period * period }, () => random());
  const at = (x, y) => grid[((y % period) + period) % period * period + ((x % period) + period) % period];
  const fade = (t) => t * t * (3 - 2 * t);
  return (x, y) => {
    const xi = Math.floor(x);
    const yi = Math.floor(y);
    const xf = fade(x - xi);
    const yf = fade(y - yi);
    const top = at(xi, yi) * (1 - xf) + at(xi + 1, yi) * xf;
    const bottom = at(xi, yi + 1) * (1 - xf) + at(xi + 1, yi + 1) * xf;
    return top * (1 - yf) + bottom * yf;
  };
}

/** Fractal noise: several octaves of value noise added up, 0..1. */
export function fbm(seed = 1, octaves = 4, period = 4) {
  const layers = Array.from({ length: octaves }, (_, i) => valueNoise(seed + i * 101, period * 2 ** i));
  return (u, v) => {
    let sum = 0;
    let weight = 0.5;
    let total = 0;
    layers.forEach((noise, i) => {
      sum += noise(u * period * 2 ** i, v * period * 2 ** i) * weight;
      total += weight;
      weight *= 0.5;
    });
    return sum / total;
  };
}

// -------------------------------------------------------------- textures

const mix = (a, b, t) => a + (b - a) * t;
const hex = (color) => new THREE.Color(color);

/** Recipes for the textures the kit draws: a height from noise, then colours. */
export const TEXTURES = {
  stone: { colors: ["#3c3a37", "#6d6862", "#8f887e"], cracks: 0.52, rough: 0.92, about: "Worn flagstones with dark joints" },
  wood: { colors: ["#4a2f1b", "#7a4e2c", "#a26b3d"], grain: true, rough: 0.8, about: "Planks with grain" },
  grass: { colors: ["#1f3b17", "#3d6b25", "#6b9a3a"], rough: 0.95, about: "Short grass and moss" },
  metal: { colors: ["#4b5056", "#8a9097", "#c3c8ce"], brushed: true, rough: 0.35, metal: 0.9, about: "Brushed steel" },
  lava: { colors: ["#1a0703", "#a8280a", "#ffb02e"], glow: true, rough: 0.6, about: "Cooling lava with glowing cracks" },
  sand: { colors: ["#8a6d43", "#b8975f", "#d8bb85"], rough: 0.97, about: "Desert sand" },
  bark: { colors: ["#241810", "#3d2a1b", "#5c4029"], grain: true, rough: 0.95, about: "Rough tree bark" },
  ice: { colors: ["#6d93b3", "#a9cbe4", "#e6f4ff"], rough: 0.15, about: "Frosted ice" },
};

/** Draw a texture by name: { map, normalMap, roughness, metalness, emissiveMap }.
 * Each is a CanvasTexture that repeats `repeat` times. */
export function makeTexture(kind = "stone", { size = 256, seed = 7, repeat = 4 } = {}) {
  const recipe = TEXTURES[kind] || TEXTURES.stone;
  const height = new Float32Array(size * size);
  const noise = fbm(seed, 5, 3);
  const cells = valueNoise(seed + 9, 6);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const u = x / size;
      const v = y / size;
      let h = noise(u, v);
      if (recipe.grain) h = h * 0.4 + (Math.sin((u * 6 + noise(u * 2, v * 2) * 2.5) * Math.PI * 4) * 0.5 + 0.5) * 0.6;
      if (recipe.brushed) h = h * 0.25 + noise(u * 0.05, v * 3) * 0.75;
      if (recipe.cracks) {
        const tileX = (u * 4) % 1;
        const tileY = (v * 4 + Math.floor(u * 4) * 0.5) % 1;
        const edge = Math.min(tileX, 1 - tileX, tileY, 1 - tileY);
        h *= edge < 0.035 ? 0.25 : 1;
        h = h * 0.8 + cells(u * 6, v * 6) * 0.2;
      }
      height[y * size + x] = h;
    }
  }
  const [dark, mid, light] = recipe.colors.map(hex);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const paint = canvas.getContext("2d");
  const image = paint.createImageData(size, size);
  const glowCanvas = recipe.glow ? document.createElement("canvas") : null;
  const glowImage = glowCanvas ? (glowCanvas.width = glowCanvas.height = size, glowCanvas.getContext("2d").createImageData(size, size)) : null;
  for (let i = 0; i < size * size; i += 1) {
    const h = height[i];
    const low = h < 0.5;
    const t = low ? h / 0.5 : (h - 0.5) / 0.5;
    const from = low ? dark : mid;
    const to = low ? mid : light;
    const lava = recipe.glow ? (h < 0.38 ? 1 - h / 0.38 : 0) : 0;
    image.data[i * 4] = Math.min(255, mix(from.r, to.r, t) * 255 + lava * 220);
    image.data[i * 4 + 1] = Math.min(255, mix(from.g, to.g, t) * 255 + lava * 90);
    image.data[i * 4 + 2] = mix(from.b, to.b, t) * 255;
    image.data[i * 4 + 3] = 255;
    if (glowImage) {
      glowImage.data[i * 4] = lava * 255;
      glowImage.data[i * 4 + 1] = lava * 110;
      glowImage.data[i * 4 + 2] = lava * 20;
      glowImage.data[i * 4 + 3] = 255;
    }
  }
  paint.putImageData(image, 0, 0);
  const normals = normalCanvas(height, size, recipe.brushed ? 1.2 : 3.5);
  const wrap = (texture, color) => {
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(repeat, repeat);
    texture.anisotropy = 4;
    if (color) texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  };
  let emissiveMap = null;
  if (glowCanvas) {
    glowCanvas.getContext("2d").putImageData(glowImage, 0, 0);
    emissiveMap = wrap(new THREE.CanvasTexture(glowCanvas), true);
  }
  return {
    map: wrap(new THREE.CanvasTexture(canvas), true),
    normalMap: wrap(new THREE.CanvasTexture(normals), false),
    emissiveMap,
    roughness: recipe.rough ?? 0.9,
    metalness: recipe.metal ?? 0,
    canvas,
  };
}

/** A normal map from a height field (Sobel), so flat surfaces catch light. */
function normalCanvas(height, size, strength) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const paint = canvas.getContext("2d");
  const image = paint.createImageData(size, size);
  const h = (x, y) => height[((y + size) % size) * size + ((x + size) % size)];
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const dx = (h(x + 1, y - 1) + 2 * h(x + 1, y) + h(x + 1, y + 1) - h(x - 1, y - 1) - 2 * h(x - 1, y) - h(x - 1, y + 1)) * strength;
      const dy = (h(x - 1, y + 1) + 2 * h(x, y + 1) + h(x + 1, y + 1) - h(x - 1, y - 1) - 2 * h(x, y - 1) - h(x + 1, y - 1)) * strength;
      const length = Math.hypot(dx, dy, 1);
      const i = (y * size + x) * 4;
      image.data[i] = (-dx / length * 0.5 + 0.5) * 255;
      image.data[i + 1] = (-dy / length * 0.5 + 0.5) * 255;
      image.data[i + 2] = (1 / length * 0.5 + 0.5) * 255;
      image.data[i + 3] = 255;
    }
  }
  paint.putImageData(image, 0, 0);
  return canvas;
}

/** A lit material from a texture recipe (PBR: colour, normals, roughness). */
export function makeMaterial(kind = "stone", options = {}) {
  const texture = makeTexture(kind, options);
  return new THREE.MeshStandardMaterial({
    map: texture.map,
    normalMap: texture.normalMap,
    roughness: texture.roughness,
    metalness: texture.metalness,
    emissiveMap: texture.emissiveMap,
    emissive: texture.emissiveMap ? new THREE.Color("#ff6a1a") : new THREE.Color("#000000"),
    emissiveIntensity: texture.emissiveMap ? 1.6 : 0,
  });
}

// --------------------------------------------------------------- shaders
// Each animated material has uniforms.time; call tick(materials, seconds).

const NOISE_GLSL = `
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float fbm(vec2 p) { float s = 0.0; float w = 0.5; for (int i = 0; i < 5; i++) { s += noise(p) * w; p *= 2.03; w *= 0.5; } return s; }
`;

/** Flames on a plane (use it upright, facing the camera): rising, flickering,
 * added on top of the scene so they glow. */
export function fireMaterial({ color = "#ff7a1a", core = "#fff1b0" } = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 }, color: { value: hex(color) }, core: { value: hex(core) } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: `${NOISE_GLSL}
      uniform float time; uniform vec3 color; uniform vec3 core; varying vec2 vUv;
      void main() {
        vec2 p = vec2(vUv.x * 3.0, vUv.y * 2.0 - time * 1.8);
        float n = fbm(p);
        float shape = (1.0 - vUv.y) * (1.0 - abs(vUv.x - 0.5) * 2.2);
        float flame = smoothstep(0.15, 0.85, shape * 1.4 - n * 0.75);
        vec3 c = mix(color, core, smoothstep(0.55, 1.0, flame));
        gl_FragColor = vec4(c * flame * 1.6, flame);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
}

/** Rising embers: glowing points that drift up and fade, looping. */
export function makeEmbers({ count = 220, area = 8, height = 6, color = "#ffae42", seed = 3 } = {}) {
  const random = seeded(seed);
  const positions = new Float32Array(count * 3);
  const offsets = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    positions[i * 3] = (random() - 0.5) * area;
    positions[i * 3 + 1] = random() * height;
    positions[i * 3 + 2] = (random() - 0.5) * area;
    offsets[i] = random() * 10;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("offset", new THREE.BufferAttribute(offsets, 1));
  const material = new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 }, color: { value: hex(color) }, height: { value: height } },
    vertexShader: `
      uniform float time; uniform float height; attribute float offset; varying float vLife;
      void main() {
        vec3 p = position;
        float t = mod(time * 0.6 + offset, 10.0) / 10.0;
        p.y = mod(position.y + time * 0.9 + offset, height);
        p.x += sin(time * 1.3 + offset * 3.0) * 0.25;
        p.z += cos(time * 1.1 + offset * 2.0) * 0.25;
        vLife = 1.0 - p.y / height;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = (5.0 + 6.0 * fract(offset)) * vLife * (40.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 color; varying float vLife;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d) * vLife;
        gl_FragColor = vec4(color * 1.8, a);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  return points;
}

/** Water: moving waves in the vertices, a fresnel sheen and foam. */
export function waterMaterial({ deep = "#0b2a3a", shallow = "#2f7f8f", foam = "#cfe9ef" } = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 }, deep: { value: hex(deep) }, shallow: { value: hex(shallow) }, foam: { value: hex(foam) } },
    vertexShader: `
      uniform float time; varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
      void main() {
        vUv = uv; vec3 p = position;
        float w = sin(p.x * 1.5 + time * 1.4) * 0.12 + cos(p.y * 1.2 + time * 1.1) * 0.1;
        p.z += w;
        vec4 world = modelMatrix * vec4(p, 1.0);
        vNormal = normalize(normalMatrix * vec3(-cos(p.x * 1.5 + time) * 0.18, sin(p.y * 1.2 + time) * 0.12, 1.0));
        vView = normalize(cameraPosition - world.xyz);
        gl_Position = projectionMatrix * viewMatrix * world;
      }`,
    fragmentShader: `${NOISE_GLSL}
      uniform float time; uniform vec3 deep; uniform vec3 shallow; uniform vec3 foam; varying vec2 vUv; varying vec3 vNormal; varying vec3 vView;
      void main() {
        float fresnel = pow(1.0 - max(dot(normalize(vNormal), vView), 0.0), 3.0);
        float ripples = fbm(vUv * 12.0 + vec2(time * 0.08, time * 0.05));
        vec3 c = mix(deep, shallow, ripples * 0.8 + fresnel * 0.6);
        c = mix(c, foam, smoothstep(0.72, 0.9, ripples) * 0.5);
        gl_FragColor = vec4(c, 0.92);
      }`,
    transparent: true,
  });
}

/** A rim glow (fresnel): magic, auras, highlights on a target. */
export function glowMaterial({ color = "#7fd4ff", power = 2.2, strength = 1.4 } = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { color: { value: hex(color) }, power: { value: power }, strength: { value: strength }, time: { value: 0 } },
    vertexShader: "varying vec3 vNormal; varying vec3 vView; void main() { vec4 world = modelMatrix * vec4(position, 1.0); vNormal = normalize(mat3(modelMatrix) * normal); vView = normalize(cameraPosition - world.xyz); gl_Position = projectionMatrix * viewMatrix * world; }",
    fragmentShader: "uniform vec3 color; uniform float power; uniform float strength; uniform float time; varying vec3 vNormal; varying vec3 vView; void main() { float rim = pow(1.0 - max(dot(vNormal, vView), 0.0), power) * strength * (0.85 + 0.15 * sin(time * 3.0)); gl_FragColor = vec4(color * rim, rim); }",
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

/** A cel-shaded look (three bands of light). */
export function toonMaterial(color = "#c0563a") {
  const bands = new Uint8Array([70, 150, 255]);
  const gradientMap = new THREE.DataTexture(bands, bands.length, 1, THREE.RedFormat);
  gradientMap.minFilter = gradientMap.magFilter = THREE.NearestFilter;
  gradientMap.needsUpdate = true;
  return new THREE.MeshToonMaterial({ color, gradientMap });
}

/** Burn away (uniforms.amount 0 → 1): enemies dying, spells appearing. */
export function dissolveMaterial({ color = "#9a9187", edge = "#ff8a2a" } = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { amount: { value: 0 }, color: { value: hex(color) }, edge: { value: hex(edge) }, time: { value: 0 } },
    vertexShader: "varying vec2 vUv; varying vec3 vNormal; void main() { vUv = uv; vNormal = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: `${NOISE_GLSL}
      uniform float amount; uniform vec3 color; uniform vec3 edge; varying vec2 vUv; varying vec3 vNormal;
      void main() {
        float n = fbm(vUv * 6.0);
        if (n < amount) discard;
        float light = 0.35 + 0.65 * max(dot(vNormal, normalize(vec3(0.4, 0.8, 0.5))), 0.0);
        vec3 c = mix(color * light, edge * 2.0, smoothstep(amount + 0.06, amount, n));
        gl_FragColor = vec4(c, 1.0);
      }`,
  });
}

/** A sky dome that fades from the horizon colour up to the zenith, with a sun glow. */
export function makeSky({ top = "#1b1f3a", horizon = "#e0703a", sun = new THREE.Vector3(-0.4, 0.15, -1) } = {}) {
  const material = new THREE.ShaderMaterial({
    uniforms: { top: { value: hex(top) }, horizon: { value: hex(horizon) }, sun: { value: sun.clone().normalize() } },
    vertexShader: "varying vec3 vDir; void main() { vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "uniform vec3 top; uniform vec3 horizon; uniform vec3 sun; varying vec3 vDir; void main() { float h = clamp(vDir.y * 1.6, 0.0, 1.0); vec3 c = mix(horizon, top, h); float s = pow(max(dot(vDir, sun), 0.0), 24.0); gl_FragColor = vec4(c + vec3(1.0, 0.7, 0.4) * s, 1.0); }",
    side: THREE.BackSide,
    depthWrite: false,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(400, 32, 16), material);
}

/** Move every animated material and ember system forward to `seconds`. */
export function tick(things, seconds) {
  for (const thing of things) {
    const material = thing.material || thing;
    if (material.uniforms && material.uniforms.time) material.uniforms.time.value = seconds;
  }
}

// ---------------------------------------------------------------- models

const standard = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...extra });

function shadowed(object) {
  object.traverse((child) => {
    if (child.isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });
  return object;
}

/** A rock: a lumpy stone shape (seeded), in the kit's stone texture. */
export function makeRock({ seed = 1, size = 1, material = null } = {}) {
  const geometry = new THREE.DodecahedronGeometry(size, 1);
  const random = seeded(seed);
  const position = geometry.attributes.position;
  for (let i = 0; i < position.count; i += 1) {
    const scale = 0.8 + random() * 0.35;
    position.setXYZ(i, position.getX(i) * scale, position.getY(i) * scale * 0.7, position.getZ(i) * scale);
  }
  geometry.computeVertexNormals();
  return shadowed(new THREE.Mesh(geometry, material || makeMaterial("stone", { size: 128, seed, repeat: 1 })));
}

/** A tree: a bark trunk and layered leafy cones (or bare, or burning). */
export function makeTree({ seed = 1, height = 5, leaves = "#2f5a26", bare = false, burning = false } = {}) {
  const random = seeded(seed);
  const tree = new THREE.Group();
  const bark = makeMaterial("bark", { size: 128, seed, repeat: 1 });
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.18 * height / 5, 0.32 * height / 5, height * 0.55, 8), bark);
  trunk.position.y = height * 0.275;
  tree.add(trunk);
  if (!bare) {
    const leafMaterial = standard(burning ? "#3b1a0a" : leaves, { roughness: 1, flatShading: true });
    for (let i = 0; i < 3; i += 1) {
      const radius = (1.5 - i * 0.35) * height / 5 * (0.9 + random() * 0.2);
      const cone = new THREE.Mesh(new THREE.ConeGeometry(radius, height * 0.38, 7), leafMaterial);
      cone.position.y = height * (0.5 + i * 0.17);
      cone.rotation.y = random() * Math.PI;
      tree.add(cone);
    }
  }
  if (burning) {
    const fire = fireMaterial();
    for (let i = 0; i < 3; i += 1) {
      const flame = new THREE.Mesh(new THREE.PlaneGeometry(height * 0.5, height * 0.65), fire);
      flame.position.set((random() - 0.5) * 0.8, height * (0.55 + i * 0.12), (random() - 0.5) * 0.8);
      flame.rotation.y = (i * Math.PI) / 3;
      flame.userData.flame = true;
      tree.add(flame);
    }
    tree.userData.fire = fire;
  }
  return shadowed(tree);
}

/** A tiered tower (a pagoda shape): stone base, wooden floors, curved roofs. */
export function makeTower({ floors = 5, width = 4, roof = "#2b2622", wall = "#6b3d26" } = {}) {
  const tower = new THREE.Group();
  const stone = makeMaterial("stone", { size: 128, repeat: 2 });
  const base = new THREE.Mesh(new THREE.CylinderGeometry(width * 0.8, width * 0.9, 1.2, 8), stone);
  base.position.y = 0.6;
  tower.add(base);
  let y = 1.2;
  for (let i = 0; i < floors; i += 1) {
    const size = width * (1 - i * 0.12);
    const body = new THREE.Mesh(new THREE.CylinderGeometry(size * 0.42, size * 0.46, 1.6, 8), standard(wall));
    body.position.y = y + 0.8;
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(size * 0.25, size * 0.75, 0.55, 8, 1, true), standard(roof, { side: THREE.DoubleSide }));
    cap.position.y = y + 1.8;
    const glow = new THREE.Mesh(new THREE.BoxGeometry(size * 0.3, 0.4, size * 0.86), new THREE.MeshBasicMaterial({ color: "#ffb35c" }));
    glow.position.y = y + 0.9;
    tower.add(body, cap, glow);
    y += 2.05;
  }
  const spire = new THREE.Mesh(new THREE.ConeGeometry(0.25, 2.2, 8), standard("#3a332b", { metalness: 0.4 }));
  spire.position.y = y + 1;
  tower.add(spire);
  return shadowed(tower);
}

/** A weapon: a sword (blade, guard, grip) or a long staff. */
export function makeWeapon(kind = "sword") {
  const weapon = new THREE.Group();
  const steel = makeMaterial("metal", { size: 64, repeat: 1 });
  if (kind === "staff") {
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 2.4, 8), standard("#5a3b20"));
    pole.position.y = 0.7;
    const band = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.2, 8), steel);
    band.position.y = 1.85;
    weapon.add(pole, band);
  } else {
    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.05, 0.02), steel);
    blade.position.y = 0.72;
    const guard = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.05, 0.08), standard("#b08a3e", { metalness: 0.7, roughness: 0.4 }));
    guard.position.y = 0.18;
    const grip = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.28, 6), standard("#2a1c12"));
    grip.position.y = 0.02;
    weapon.add(blade, guard, grip);
  }
  return shadowed(weapon);
}

/** A warrior made of shapes, jointed so procedural animation can pose it:
 * { root, parts: { hips, body, head, armL, armR, legL, legR, weapon } }.
 * scale 2.5 and horns make a boss. */
export function makeWarrior({ color = "#7a2f22", skin = "#c9a27e", armour = "#3c3a3a", weapon = "staff", scale = 1, horns = false } = {}) {
  const root = new THREE.Group();
  const hips = new THREE.Group();
  hips.position.y = 0.95;
  root.add(hips);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.26, 0.5, 4, 10), standard(color));
  body.position.y = 0.42;
  hips.add(body);
  const chest = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.32, 0.3), standard(armour, { metalness: 0.5, roughness: 0.5 }));
  chest.position.y = 0.55;
  hips.add(chest);
  const head = new THREE.Group();
  head.position.y = 0.98;
  head.add(new THREE.Mesh(new THREE.SphereGeometry(0.17, 14, 12), standard(skin)));
  if (horns) {
    for (const side of [-1, 1]) {
      const horn = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.45, 8), standard("#e8dcc0"));
      horn.position.set(side * 0.14, 0.18, 0);
      horn.rotation.z = -side * 0.5;
      head.add(horn);
    }
  }
  hips.add(head);
  const limb = (length, radius, material) => {
    const pivot = new THREE.Group();
    const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(radius, length, 4, 8), material);
    mesh.position.y = -length / 2 - radius;
    pivot.add(mesh);
    return pivot;
  };
  const armL = limb(0.42, 0.07, standard(color));
  armL.position.set(-0.34, 0.72, 0);
  const armR = limb(0.42, 0.07, standard(color));
  armR.position.set(0.34, 0.72, 0);
  const legL = limb(0.55, 0.09, standard(armour));
  legL.position.set(-0.14, 0, 0);
  const legR = limb(0.55, 0.09, standard(armour));
  legR.position.set(0.14, 0, 0);
  hips.add(armL, armR, legL, legR);
  const held = makeWeapon(weapon);
  held.position.set(0, -0.62, 0.06);
  held.rotation.x = Math.PI / 2;
  armR.add(held);
  root.scale.setScalar(scale);
  shadowed(root);
  return { root, parts: { hips, body, head, armL, armR, legL, legR, weapon: held } };
}

// ------------------------------------------------------------- animation

/** Pose a warrior for a moment of an action. state: idle, walk, run, attack,
 * heavy, roll, hit, dead. t: seconds into the action (or the clock for
 * loops). Returns how far through a one-off action it is (0..1). */
export function animateWarrior(warrior, state, t) {
  const { hips, head, armL, armR, legL, legR } = warrior.parts;
  const reset = () => {
    hips.position.y = 0.95;
    hips.rotation.set(0, 0, 0);
    head.rotation.set(0, 0, 0);
    for (const part of [armL, armR, legL, legR]) part.rotation.set(0, 0, 0);
  };
  reset();
  const ease = (x) => 1 - (1 - x) ** 3;
  switch (state) {
    case "walk":
    case "run": {
      const speed = state === "run" ? 11 : 7;
      const swing = state === "run" ? 0.9 : 0.6;
      const s = Math.sin(t * speed);
      legL.rotation.x = s * swing;
      legR.rotation.x = -s * swing;
      armL.rotation.x = -s * swing * 0.8;
      armR.rotation.x = s * swing * 0.5 - 0.3;
      hips.position.y = 0.95 + Math.abs(Math.cos(t * speed)) * 0.06;
      hips.rotation.x = state === "run" ? 0.18 : 0.05;
      return 0;
    }
    case "attack":
    case "heavy": {
      const length = state === "heavy" ? 1.1 : 0.55;
      const p = Math.min(1, t / length);
      const windup = state === "heavy" ? 0.45 : 0.3;
      if (p < windup) {
        const w = ease(p / windup);
        armR.rotation.x = -2.6 * w;
        armR.rotation.z = -0.4 * w;
        hips.rotation.y = 0.5 * w;
      } else {
        const strike = ease(Math.min(1, (p - windup) / 0.25));
        armR.rotation.x = -2.6 + 3.6 * strike;
        armR.rotation.z = -0.4 + 0.4 * strike;
        hips.rotation.y = 0.5 - 1.0 * strike;
        hips.rotation.x = 0.25 * strike;
      }
      armL.rotation.x = -0.4;
      legL.rotation.x = 0.35;
      legR.rotation.x = -0.25;
      return p;
    }
    case "roll": {
      const p = Math.min(1, t / 0.55);
      hips.rotation.x = p * Math.PI * 2;
      hips.position.y = 0.55 + Math.sin(p * Math.PI) * 0.15;
      legL.rotation.x = legR.rotation.x = -1.4;
      armL.rotation.x = armR.rotation.x = -1.2;
      return p;
    }
    case "hit": {
      const p = Math.min(1, t / 0.35);
      hips.rotation.x = -0.35 * Math.sin(p * Math.PI);
      head.rotation.x = -0.3 * Math.sin(p * Math.PI);
      return p;
    }
    case "dead": {
      const p = Math.min(1, t / 0.9);
      hips.rotation.x = -ease(p) * Math.PI / 2;
      hips.position.y = 0.95 - ease(p) * 0.75;
      armL.rotation.z = armR.rotation.z = ease(p) * 0.6;
      return p;
    }
    default: {
      const breath = Math.sin(t * 2.2);
      hips.position.y = 0.95 + breath * 0.012;
      armL.rotation.x = 0.05 + breath * 0.04;
      armR.rotation.x = -0.25 + breath * 0.04;
      head.rotation.x = breath * 0.03;
      return 0;
    }
  }
}

// --------------------------------------------------------------- the stage

/** A renderer tuned for phones: shadows, filmic tone mapping, a capped pixel ratio. */
export function makeRenderer(canvas, { maxPixelRatio = 1.6 } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, maxPixelRatio));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  return renderer;
}

/** Dusk lighting: a sky light, a low warm sun with soft shadows, and fog. */
export function addLights(scene, { sun = "#ffb070", sky = "#6f7fb0", ground = "#2a1a12", fog = "#3a2a2c", density = 0.028 } = {}) {
  scene.add(new THREE.HemisphereLight(sky, ground, 1.1));
  const light = new THREE.DirectionalLight(sun, 2.4);
  light.position.set(-12, 16, 8);
  light.castShadow = true;
  light.shadow.mapSize.set(1024, 1024);
  light.shadow.camera.left = light.shadow.camera.bottom = -24;
  light.shadow.camera.right = light.shadow.camera.top = 24;
  light.shadow.bias = -0.0006;
  scene.add(light);
  scene.fog = new THREE.FogExp2(fog, density);
  return light;
}

/** Touch controls: a joystick on the left, buttons on the right (and keys on
 * a computer: WASD, J attack, K heavy, Space roll, L lock, H heal). */
export function makeControls(root, buttons = [["attack", "⚔"], ["heavy", "✶"], ["roll", "⤵"], ["lock", "◎"], ["heal", "✚"]]) {
  const input = { x: 0, y: 0, look: 0, pressed: new Set() };
  const pad = document.createElement("div");
  pad.className = "lab-stick";
  const knob = document.createElement("div");
  knob.className = "lab-knob";
  pad.append(knob);
  const keys = document.createElement("div");
  keys.className = "lab-buttons";
  for (const [name, glyph] of buttons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `lab-button lab-${name}`;
    button.textContent = glyph;
    button.setAttribute("aria-label", name);
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      input.pressed.add(name);
    });
    keys.append(button);
  }
  root.append(pad, keys);
  let stick = null;
  pad.addEventListener("pointerdown", (event) => {
    stick = event.pointerId;
    pad.setPointerCapture(event.pointerId);
  });
  pad.addEventListener("pointermove", (event) => {
    if (event.pointerId !== stick) return;
    const box = pad.getBoundingClientRect();
    const dx = (event.clientX - box.left - box.width / 2) / (box.width / 2);
    const dy = (event.clientY - box.top - box.height / 2) / (box.height / 2);
    const length = Math.max(1, Math.hypot(dx, dy));
    input.x = dx / length;
    input.y = dy / length;
    knob.style.transform = `translate(${input.x * 28}px, ${input.y * 28}px)`;
  });
  const release = (event) => {
    if (event.pointerId !== stick) return;
    stick = null;
    input.x = input.y = 0;
    knob.style.transform = "";
  };
  pad.addEventListener("pointerup", release);
  pad.addEventListener("pointercancel", release);
  let drag = null;
  root.addEventListener("pointerdown", (event) => {
    if (event.target === root || event.target.tagName === "CANVAS") drag = { id: event.pointerId, x: event.clientX };
  });
  root.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    input.look += (event.clientX - drag.x) * 0.008;
    drag.x = event.clientX;
  });
  root.addEventListener("pointerup", () => (drag = null));
  const held = new Set();
  const keyMap = { j: "attack", k: "heavy", " ": "roll", l: "lock", h: "heal" };
  window.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if (keyMap[key]) input.pressed.add(keyMap[key]);
    held.add(key);
    input.x = (held.has("d") ? 1 : 0) - (held.has("a") ? 1 : 0);
    input.y = (held.has("s") ? 1 : 0) - (held.has("w") ? 1 : 0);
  });
  window.addEventListener("keyup", (event) => {
    held.delete(event.key.toLowerCase());
    input.x = (held.has("d") ? 1 : 0) - (held.has("a") ? 1 : 0);
    input.y = (held.has("s") ? 1 : 0) - (held.has("w") ? 1 : 0);
  });
  /** True once for each press of a button since the last frame. */
  input.take = (name) => input.pressed.delete(name);
  return input;
}

/** What the kit has, for the Lab screen and the AI. */
export const KIT = {
  textures: Object.fromEntries(Object.entries(TEXTURES).map(([name, recipe]) => [name, recipe.about])),
  shaders: {
    fire: "fireMaterial(): flames on an upright plane, additive",
    embers: "makeEmbers({count, area, height}): rising glowing points",
    water: "waterMaterial(): waves, fresnel sheen, foam",
    glow: "glowMaterial({color}): rim glow for magic and highlights",
    toon: "toonMaterial(color): cel shading in three bands",
    dissolve: "dissolveMaterial(): burn away with uniforms.amount 0..1",
    sky: "makeSky({top, horizon, sun}): gradient sky dome with a sun glow",
  },
  models: {
    warrior: "makeWarrior({color, weapon, scale, horns}): a jointed fighter",
    tree: "makeTree({height, bare, burning}): bark trunk and leaves, or burning",
    rock: "makeRock({seed, size}): a lumpy stone",
    tower: "makeTower({floors}): a tiered pagoda tower",
    weapon: "makeWeapon('sword' | 'staff')",
  },
  animations: {
    idle: "breathing", walk: "a walk cycle", run: "a run cycle", attack: "a quick swing", heavy: "a slow heavy swing",
    roll: "a dodge roll", hit: "flinch", dead: "fall down",
  },
};
