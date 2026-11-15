// Seeded random numbers (mulberry32) so a world can be replayed and saved.
export function makeRng(seed) {
  let s = seed >>> 0;
  const r = () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  r.getState = () => s;
  r.setState = (v) => {
    s = v | 0;
  };
  return r;
}

export const pick = (r, arr) => arr[Math.floor(r() * arr.length)];
export const chance = (r, p) => r() < p;
export const randInt = (r, a, b) => a + Math.floor(r() * (b - a + 1));
export const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
export const dist = (ax, ay, bx, by) => Math.hypot(ax - bx, ay - by);

export function shuffle(r, arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// Fill "{name}" style slots in a template.
export function fill(text, vars) {
  return text.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m));
}

// Smooth 2D value noise for terrain.
export function makeNoise(seed) {
  const hash = (x, y) => {
    let h = (x * 374761393 + y * 668265263 + seed * 2246822519) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  };
  const smooth = (t) => t * t * (3 - 2 * t);
  const n = (x, y) => {
    const xi = Math.floor(x);
    const yi = Math.floor(y);
    const xf = smooth(x - xi);
    const yf = smooth(y - yi);
    const a = hash(xi, yi);
    const b = hash(xi + 1, yi);
    const c = hash(xi, yi + 1);
    const d = hash(xi + 1, yi + 1);
    return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf;
  };
  return (x, y, oct = 4) => {
    let v = 0;
    let amp = 1;
    let f = 1;
    let tot = 0;
    for (let i = 0; i < oct; i++) {
      v += n(x * f, y * f) * amp;
      tot += amp;
      amp *= 0.5;
      f *= 2;
    }
    return v / tot;
  };
}

// A cheap per-tile hash for pixel texture variation.
export function tileHash(x, y, k = 0) {
  let h = (x * 73856093) ^ (y * 19349663) ^ (k * 83492791);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
