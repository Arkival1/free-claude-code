// The tile map: terrain, plants, roads, fire and pathfinding.
import { makeNoise, makeRng } from "./rng.js";

export const T = { DEEP: 0, WATER: 1, SAND: 2, GRASS: 3, DIRT: 4, HILL: 5, MOUNTAIN: 6, SNOW: 7, ASH: 8 };
export const T_NAMES = ["deep water", "water", "sand", "grass", "dirt", "hills", "mountain", "snow", "ash"];
export const F = { NONE: 0, SAPLING: 1, YOUNG: 2, TREE: 3, BUSH: 4, BUSH_EMPTY: 5, FLOWERS: 6, STUMP: 7 };

const COST = [Infinity, 2.6, 1.15, 1, 1, 1.6, Infinity, Infinity, 1.05];
const BUILDABLE = new Set([T.SAND, T.GRASS, T.DIRT, T.HILL, T.ASH]);

export class World {
  constructor(w = 96, h = 96) {
    this.w = w;
    this.h = h;
    const n = w * h;
    this.t = new Uint8Array(n);
    this.flora = new Uint8Array(n);
    this.road = new Uint8Array(n);
    this.fire = new Float32Array(n);
    this.bld = new Int32Array(n).fill(-1);
    this.dirty = new Set();
    this.allDirty = true;
  }

  idx(x, y) {
    return y * this.w + x;
  }
  inb(x, y) {
    return x >= 0 && y >= 0 && x < this.w && y < this.h;
  }
  tile(x, y) {
    return this.inb(x, y) ? this.t[y * this.w + x] : T.DEEP;
  }
  walkable(x, y) {
    return this.inb(x, y) && COST[this.t[y * this.w + x]] !== Infinity;
  }
  buildable(x, y) {
    return this.inb(x, y) && BUILDABLE.has(this.t[y * this.w + x]);
  }
  cost(i) {
    if (this.road[i]) return 0.55;
    const c = COST[this.t[i]];
    const f = this.flora[i];
    return f === F.TREE || f === F.YOUNG ? c * 1.25 : c;
  }
  setT(x, y, v) {
    if (!this.inb(x, y)) return;
    const i = this.idx(x, y);
    this.t[i] = v;
    if (v === T.WATER || v === T.DEEP || v === T.MOUNTAIN || v === T.SNOW) {
      this.flora[i] = F.NONE;
      this.road[i] = 0;
    }
    this.dirty.add(i);
  }
  setFlora(i, v) {
    if (this.flora[i] !== v) {
      this.flora[i] = v;
      this.dirty.add(i);
    }
  }
  setRoad(i, v) {
    this.road[i] = v;
    this.dirty.add(i);
  }

  generate(seed) {
    const r = makeRng(seed ^ 0x9e3779b9);
    const elev = makeNoise(seed);
    const moist = makeNoise(seed + 1013);
    const ox = r() * 50;
    const oy = r() * 50;
    const n = this.w * this.h;
    const es = new Float32Array(n);
    const ms = new Float32Array(n);
    for (let y = 0; y < this.h; y++) {
      for (let x = 0; x < this.w; x++) {
        const nx = x / this.w - 0.5;
        const ny = y / this.h - 0.5;
        const d = Math.sqrt(nx * nx + ny * ny) * 2;
        const i = y * this.w + x;
        es[i] = elev(x / 22 + ox, y / 22 + oy, 5) - d * d * 0.55;
        ms[i] = moist(x / 14 + oy, y / 14 + ox, 3);
      }
    }
    // Thresholds by share of the map, so every seed has the same mix of land.
    const sorted = Float32Array.from(es).sort();
    const q = (f) => sorted[Math.min(n - 1, Math.floor(n * f))];
    const cut = [q(0.27), q(0.37), q(0.41), q(0.875), q(0.93), q(0.982)];
    for (let i = 0; i < n; i++) {
      const e = es[i];
      const t = e < cut[0] ? T.DEEP : e < cut[1] ? T.WATER : e < cut[2] ? T.SAND : e < cut[3] ? T.GRASS : e < cut[4] ? T.HILL : e < cut[5] ? T.MOUNTAIN : T.SNOW;
      this.t[i] = t;
      const m = ms[i];
      let f = F.NONE;
      if (t === T.GRASS) {
        if (m > 0.56 && r() < 0.62) f = F.TREE;
        else if (m > 0.5 && r() < 0.22) f = F.TREE;
        else if (r() < 0.025) f = F.BUSH;
        else if (r() < 0.035) f = F.FLOWERS;
      } else if (t === T.HILL && r() < 0.14) f = F.TREE;
      this.flora[i] = f;
    }
    this.allDirty = true;
  }

  // Count walkable, buildable land around a point (for choosing a village site).
  openness(cx, cy, r) {
    let n = 0;
    for (let y = cy - r; y <= cy + r; y++)
      for (let x = cx - r; x <= cx + r; x++) if (this.buildable(x, y) && this.t[this.idx(x, y)] !== T.HILL) n++;
    return n;
  }

  // A* over an 8-way grid. Returns tiles from the next step to the target.
  findPath(sx, sy, tx, ty, maxNodes = 9000) {
    if (!this.walkable(tx, ty)) return null;
    if (sx === tx && sy === ty) return [];
    const W = this.w;
    const n = W * this.h;
    if (!this._g) {
      this._g = new Float32Array(n);
      this._from = new Int32Array(n);
      this._seen = new Uint32Array(n);
      this._shut = new Uint32Array(n);
      this._run = 0;
      this._hf = new Float64Array(n * 2);
      this._hi = new Int32Array(n * 2);
    }
    const run = ++this._run;
    const g = this._g;
    const from = this._from;
    const seen = this._seen;
    const shut = this._shut;
    const hf = this._hf;
    const hi = this._hi;
    let size = 0;
    const push = (f, i) => {
      let k = size++;
      while (k > 0) {
        const p = (k - 1) >> 1;
        if (hf[p] <= f) break;
        hf[k] = hf[p];
        hi[k] = hi[p];
        k = p;
      }
      hf[k] = f;
      hi[k] = i;
    };
    const pop = () => {
      const top = hi[0];
      const lf = hf[--size];
      const li = hi[size];
      let k = 0;
      for (;;) {
        let c = 2 * k + 1;
        if (c >= size) break;
        if (c + 1 < size && hf[c + 1] < hf[c]) c++;
        if (hf[c] >= lf) break;
        hf[k] = hf[c];
        hi[k] = hi[c];
        k = c;
      }
      hf[k] = lf;
      hi[k] = li;
      return top;
    };
    const h = (x, y) => {
      const dx = Math.abs(x - tx);
      const dy = Math.abs(y - ty);
      return 0.55 * (Math.max(dx, dy) + 0.414 * Math.min(dx, dy));
    };
    const s = sy * W + sx;
    const goal = ty * W + tx;
    g[s] = 0;
    seen[s] = run;
    from[s] = -1;
    push(h(sx, sy), s);
    let count = 0;
    while (size > 0) {
      const cur = pop();
      if (cur === goal) break;
      if (shut[cur] === run) continue;
      shut[cur] = run;
      if (++count > maxNodes) return null;
      const cx = cur % W;
      const cy = (cur / W) | 0;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (!dx && !dy) continue;
          const x = cx + dx;
          const y = cy + dy;
          if (!this.walkable(x, y)) continue;
          if (dx && dy && (!this.walkable(cx + dx, cy) || !this.walkable(cx, cy + dy))) continue;
          const ni = y * W + x;
          if (shut[ni] === run) continue;
          const step = this.cost(ni) * (dx && dy ? 1.414 : 1);
          const ng = g[cur] + step;
          if (seen[ni] !== run || ng < g[ni]) {
            seen[ni] = run;
            g[ni] = ng;
            from[ni] = cur;
            push(ng + h(x, y), ni);
          }
        }
      }
    }
    if (seen[goal] !== run) return null;
    const out = [];
    for (let c = goal; c !== s && c !== -1; c = from[c]) out.push({ x: c % W, y: (c / W) | 0 });
    return out.reverse();
  }

  // Nearest tile (by straight distance, within radius) that passes test(i, x, y).
  nearest(cx, cy, radius, test) {
    cx = Math.floor(cx);
    cy = Math.floor(cy);
    for (let r = 0; r <= radius; r++) {
      let best = null;
      let bd = Infinity;
      for (let y = cy - r; y <= cy + r; y++) {
        for (let x = cx - r; x <= cx + r; x++) {
          if (Math.max(Math.abs(x - cx), Math.abs(y - cy)) !== r || !this.inb(x, y)) continue;
          const i = y * this.w + x;
          if (!test(i, x, y)) continue;
          const d = (x - cx) ** 2 + (y - cy) ** 2;
          if (d < bd) {
            bd = d;
            best = { x, y, i };
          }
        }
      }
      if (best) return best;
    }
    return null;
  }

  // A walkable tile next to (x, y), closest to (fx, fy).
  standNear(x, y, fx, fy) {
    let best = null;
    let bd = Infinity;
    for (let dy = -1; dy <= 1; dy++)
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        if (!this.walkable(x + dx, y + dy)) continue;
        const d = (x + dx - fx) ** 2 + (y + dy - fy) ** 2;
        if (d < bd) {
          bd = d;
          best = { x: x + dx, y: y + dy };
        }
      }
    return best;
  }

  serialize() {
    const b64 = (arr) => {
      const bytes = new Uint8Array(arr.buffer);
      let s = "";
      for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(s);
    };
    return { w: this.w, h: this.h, t: b64(this.t), flora: b64(this.flora), road: b64(this.road) };
  }
  static deserialize(o) {
    const w = new World(o.w, o.h);
    const un = (s, arr) => {
      const bin = atob(s);
      const bytes = new Uint8Array(arr.buffer);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    };
    un(o.t, w.t);
    un(o.flora, w.flora);
    un(o.road, w.road);
    return w;
  }
}
