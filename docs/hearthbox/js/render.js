// Draws the world on a canvas: pixel-art terrain baked once, then buildings,
// people, animals, weather, night lights and effects every frame.
import { BUILDINGS, JOBS } from "./data.js";
import { tileHash } from "./rng.js";
import { F, T } from "./world.js";

const TP = 8; // baked pixels per tile
const BASE = {
  [T.DEEP]: [36, 78, 146],
  [T.WATER]: [62, 124, 196],
  [T.SAND]: [226, 206, 150],
  [T.GRASS]: [106, 172, 74],
  [T.DIRT]: [148, 110, 72],
  [T.HILL]: [132, 150, 84],
  [T.MOUNTAIN]: [126, 122, 118],
  [T.SNOW]: [236, 240, 246],
  [T.ASH]: [72, 68, 64],
};
const SPRITES = {
  tree: ["..aaaa..", ".abbbba.", "abbcbbba", "abbbbcba", ".abbbba.", "..adda..", "...dd...", "...dd..."],
  pine: ["...a....", "..aba...", ".abbba..", "..aba...", ".abbba..", "abbcbba.", "...d....", "...d...."],
  young: ["........", "........", "...aa...", "..abba..", "..abba..", "...dd...", "...d....", "........"],
  sapling: ["........", "........", "........", "...b....", "..bab...", "...d....", "........", "........"],
  bush: ["........", "........", "..aaaa..", ".abrbba.", ".abbbra.", "..aaaa..", "........", "........"],
  bushE: ["........", "........", "..aaaa..", ".abbbba.", ".abbbba.", "..aaaa..", "........", "........"],
  flowers: ["........", ".r....y.", "........", "...p....", "......w.", ".y......", "....r...", "........"],
  stump: ["........", "........", "........", "........", "...ee...", "..eDDe..", "..eeee..", "........"],
};
const SP_COL = {
  a: [38, 92, 44],
  b: [56, 128, 58],
  c: [104, 176, 88],
  d: [104, 72, 42],
  D: [168, 128, 84],
  e: [120, 84, 50],
  r: [214, 60, 60],
  y: [242, 214, 76],
  p: [196, 120, 220],
  w: [250, 250, 250],
};

export class Renderer {
  constructor(canvas) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.cam = { x: 48, y: 48, z: 28 };
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.glow = makeGlow();
    this.shake = 0;
  }

  setSim(sim) {
    this.sim = sim;
    const W = sim.world;
    this.bake = document.createElement("canvas");
    this.bake.width = W.w * TP;
    this.bake.height = W.h * TP;
    this.bctx = this.bake.getContext("2d");
    this.img = this.bctx.createImageData(W.w * TP, W.h * TP);
    W.allDirty = true;
  }

  resize() {
    const w = this.c.clientWidth;
    const h = this.c.clientHeight;
    this.c.width = Math.round(w * this.dpr);
    this.c.height = Math.round(h * this.dpr);
  }

  center(x, y) {
    this.cam.x = x;
    this.cam.y = y;
  }
  zoomAt(factor, sx, sy) {
    const before = this.toWorld(sx, sy);
    this.cam.z = Math.max(5 * this.dpr, Math.min(48 * this.dpr, this.cam.z * factor));
    const after = this.toWorld(sx, sy);
    this.cam.x += before.x - after.x;
    this.cam.y += before.y - after.y;
    this.clamp();
  }
  pan(dx, dy) {
    this.cam.x -= (dx * this.dpr) / this.cam.z;
    this.cam.y -= (dy * this.dpr) / this.cam.z;
    this.clamp();
  }
  clamp() {
    const W = this.sim.world;
    this.cam.x = Math.max(0, Math.min(W.w, this.cam.x));
    this.cam.y = Math.max(0, Math.min(W.h, this.cam.y));
  }
  // CSS pixel -> tile coordinates.
  toWorld(sx, sy) {
    const z = this.cam.z;
    return { x: this.cam.x + (sx * this.dpr - this.c.width / 2) / z, y: this.cam.y + (sy * this.dpr - this.c.height / 2) / z };
  }
  toScreen(x, y) {
    const z = this.cam.z;
    return { x: (x - this.cam.x) * z + this.c.width / 2, y: (y - this.cam.y) * z + this.c.height / 2 };
  }

  // ---------- terrain bake ----------
  paintTile(i) {
    const W = this.sim.world;
    const x = i % W.w;
    const y = (i / W.w) | 0;
    const d = this.img.data;
    const rowW = W.w * TP;
    const t = W.t[i];
    for (let py = 0; py < TP; py++) {
      for (let px = 0; px < TP; px++) {
        let tt = t;
        // Ragged edges between terrains.
        const edgeX = px < 2 ? -1 : px > 5 ? 1 : 0;
        const edgeY = py < 2 ? -1 : py > 5 ? 1 : 0;
        if ((edgeX || edgeY) && tileHash(x * TP + px, y * TP + py, 3) < 0.28) {
          const nx = x + edgeX;
          const ny = y + edgeY;
          if (W.inb(nx, ny)) tt = W.t[W.idx(nx, ny)];
        }
        const base = BASE[tt];
        const h = tileHash(x * TP + px, y * TP + py, 1);
        let k = (h - 0.5) * 18;
        if (tt === T.GRASS && h > 0.93) k -= 22;
        if (tt === T.WATER || tt === T.DEEP) k = (((px + py * 3 + x * 5 + y * 7) % 11 === 0) ? 22 : 0) + (h - 0.5) * 6;
        if (tt === T.MOUNTAIN) k += (px - py) * 3 + (h > 0.8 ? 18 : 0);
        if (tt === T.HILL) k += (px - py) * 1.5;
        if (tt === T.SNOW) k = (h - 0.5) * 8;
        let r = base[0] + k;
        let g = base[1] + k;
        let b = base[2] + k;
        if (W.road[i]) {
          const gap = (px + (py >> 2) * 2) % 4 === 0 || py % 4 === 0;
          r = gap ? 130 : 182 + (h - 0.5) * 16;
          g = gap ? 112 : 164 + (h - 0.5) * 16;
          b = gap ? 92 : 132 + (h - 0.5) * 16;
        }
        const o = ((y * TP + py) * rowW + x * TP + px) * 4;
        d[o] = r;
        d[o + 1] = g;
        d[o + 2] = b;
        d[o + 3] = 255;
      }
    }
    const f = W.flora[i];
    if (f) {
      const v = tileHash(x, y, 9);
      const name = f === F.TREE ? (t === T.HILL || v < 0.25 ? "pine" : "tree") : f === F.YOUNG ? "young" : f === F.SAPLING ? "sapling" : f === F.BUSH ? "bush" : f === F.BUSH_EMPTY ? "bushE" : f === F.FLOWERS ? "flowers" : "stump";
      const sp = SPRITES[name];
      const tint = (v - 0.5) * 24;
      for (let py = 0; py < TP; py++)
        for (let px = 0; px < TP; px++) {
          const ch = sp[py][px];
          if (ch === ".") continue;
          const col = SP_COL[ch];
          const o = ((y * TP + py) * rowW + x * TP + px) * 4;
          const leafy = ch === "a" || ch === "b" || ch === "c";
          d[o] = col[0] + (leafy ? tint : 0);
          d[o + 1] = col[1] + (leafy ? tint : 0);
          d[o + 2] = col[2];
        }
    }
  }

  updateBake() {
    const W = this.sim.world;
    if (W.allDirty) {
      for (let i = 0; i < W.w * W.h; i++) this.paintTile(i);
      this.bctx.putImageData(this.img, 0, 0);
      W.allDirty = false;
      W.dirty.clear();
      return;
    }
    if (!W.dirty.size) return;
    for (const i of W.dirty) {
      this.paintTile(i);
      const x = i % W.w;
      const y = (i / W.w) | 0;
      this.bctx.putImageData(this.img, 0, 0, x * TP, y * TP, TP, TP);
    }
    W.dirty.clear();
  }

  // ---------- frame ----------
  draw(state) {
    const sim = this.sim;
    const ctx = this.ctx;
    const z = this.cam.z;
    const now = performance.now();
    this.updateBake();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#1d3f73";
    ctx.fillRect(0, 0, this.c.width, this.c.height);
    let sx = 0;
    let sy = 0;
    if (this.shake > 0) {
      sx = (Math.random() - 0.5) * this.shake;
      sy = (Math.random() - 0.5) * this.shake;
      this.shake *= 0.9;
      if (this.shake < 0.5) this.shake = 0;
    }
    const ox = this.c.width / 2 - this.cam.x * z + sx;
    const oy = this.c.height / 2 - this.cam.y * z + sy;
    const W = sim.world;
    const x0 = Math.max(0, Math.floor(this.cam.x - this.c.width / 2 / z) - 1);
    const y0 = Math.max(0, Math.floor(this.cam.y - this.c.height / 2 / z) - 1);
    const x1 = Math.min(W.w, Math.ceil(this.cam.x + this.c.width / 2 / z) + 1);
    const y1 = Math.min(W.h, Math.ceil(this.cam.y + this.c.height / 2 / z) + 3);
    ctx.imageSmoothingEnabled = false;
    ctx.setTransform(z / TP, 0, 0, z / TP, ox, oy);
    ctx.drawImage(this.bake, x0 * TP, y0 * TP, (x1 - x0) * TP, (y1 - y0) * TP, x0 * TP, y0 * TP, (x1 - x0) * TP, (y1 - y0) * TP);
    ctx.setTransform(z, 0, 0, z, ox, oy);
    const vis = (x, y, m = 3) => x > x0 - m && x < x1 + m && y > y0 - m && y < y1 + m;

    // Graves.
    for (const g of sim.graves) if (vis(g.x, g.y)) drawGrave(ctx, g.x, g.y);

    // Things sorted by their bottom edge for a little depth.
    const items = [];
    for (const b of sim.buildings) if (vis(b.x + b.w / 2, b.y + b.h / 2, 4)) items.push({ y: b.y + b.h, b });
    for (const a of sim.agents) {
      if (!vis(a.x, a.y)) continue;
      if (a.action && a.action.kind === "sleep" && a.action.phase === "do" && a.home != null && sim.buildingAt(Math.floor(a.x), Math.floor(a.y))) continue;
      items.push({ y: a.y + 0.01, a });
    }
    for (const n of sim.animals) if (vis(n.x, n.y)) items.push({ y: n.y, n });
    items.sort((p, q) => p.y - q.y);
    const light = sim.light();
    for (const it of items) {
      if (it.b) drawBuilding(ctx, sim, it.b, now, light, state.selBuilding === it.b.id, z);
      else if (it.a) drawAgent(ctx, sim, it.a, now, z, state.sel === it.a.id);
      else drawAnimal(ctx, it.n, now, light);
    }

    // Fire.
    for (const i of sim.fires) {
      const x = i % W.w;
      const y = (i / W.w) | 0;
      if (!vis(x, y)) continue;
      drawFire(ctx, x, y, now, W.fire[i]);
    }

    // Ghost of a building being placed, or the brush.
    if (state.ghost) {
      const g = state.ghost;
      const d = BUILDINGS[g.type];
      ctx.fillStyle = g.ok ? "rgba(90,220,120,0.38)" : "rgba(240,80,70,0.38)";
      ctx.fillRect(g.x, g.y, d.w, d.h);
      ctx.strokeStyle = g.ok ? "#7dffa0" : "#ff7a6e";
      ctx.lineWidth = 2 / z;
      ctx.strokeRect(g.x, g.y, d.w, d.h);
    }
    if (state.brush) {
      ctx.strokeStyle = "rgba(255,255,255,0.8)";
      ctx.lineWidth = 2 / z;
      ctx.beginPath();
      ctx.arc(Math.floor(state.brush.x) + 0.5, Math.floor(state.brush.y) + 0.5, state.brush.r, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Night and lights.
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const dark = 1 - light;
    if (dark > 0.02) {
      ctx.fillStyle = `rgba(10,16,46,${dark * 0.62})`;
      ctx.fillRect(0, 0, this.c.width, this.c.height);
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = dark * 0.85;
      for (const b of sim.buildings) {
        if (!b.done || b.type === "farm" || b.type === "park" || b.type === "well" || b.type === "statue") continue;
        if (!vis(b.x + b.w / 2, b.y + b.h / 2, 4)) continue;
        const p = this.toScreen(b.x + b.w / 2 + sx / z, b.y + b.h * 0.7 + sy / z);
        const r = z * (1.2 + b.w * 0.5);
        ctx.drawImage(this.glow, p.x - r, p.y - r, r * 2, r * 2);
      }
      for (const i of sim.fires) {
        const p = this.toScreen((i % W.w) + 0.5, ((i / W.w) | 0) + 0.5);
        const r = z * 2.2;
        ctx.drawImage(this.glow, p.x - r, p.y - r, r * 2, r * 2);
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    }

    // Rain.
    if (sim.weather.kind === "rain") {
      ctx.fillStyle = "rgba(60,80,110,0.18)";
      ctx.fillRect(0, 0, this.c.width, this.c.height);
      ctx.strokeStyle = "rgba(190,210,255,0.45)";
      ctx.lineWidth = this.dpr;
      ctx.beginPath();
      const t = now / 1000;
      for (let k = 0; k < 140; k++) {
        const px = (tileHash(k, 1, 7) * this.c.width + t * 160 * this.dpr) % this.c.width;
        const py = (tileHash(k, 2, 7) * this.c.height + t * 700 * this.dpr) % this.c.height;
        ctx.moveTo(px, py);
        ctx.lineTo(px - 4 * this.dpr, py + 12 * this.dpr);
      }
      ctx.stroke();
    }

    // Labels, bubbles and icons in screen space.
    this.drawOverlays(state, now);
    this.drawFx(now);
  }

  drawOverlays(state, now) {
    const sim = this.sim;
    const ctx = this.ctx;
    const z = this.cam.z;
    const d = this.dpr;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const close = z >= 15 * d;
    // Building icons when zoomed out, so the town reads at a glance.
    if (z < 22 * d) {
      ctx.font = `${Math.round(Math.max(10, z * 0.55))}px system-ui, sans-serif`;
      for (const b of sim.buildings) {
        if (b.type === "house" || b.type === "farm") continue;
        const p = this.toScreen(b.x + b.w / 2, b.y + b.h / 2);
        if (p.x < -20 || p.y < -20 || p.x > this.c.width + 20 || p.y > this.c.height + 20) continue;
        ctx.globalAlpha = b.done ? 0.95 : 0.6;
        ctx.fillText(BUILDINGS[b.type].icon, p.x, p.y);
      }
      ctx.globalAlpha = 1;
    }
    const taken = [];
    const free = (x, y, w, h) => {
      for (const r of taken) if (x < r[0] + r[2] && x + w > r[0] && y < r[1] + r[3] && y + h > r[1]) return false;
      taken.push([x, y, w, h]);
      return true;
    };
    const order = [...sim.agents].sort((p, q) => (q.id === state.sel) - (p.id === state.sel));
    for (const a of order) {
      const p = this.toScreen(a.x, a.y);
      if (p.x < -200 || p.y < -100 || p.x > this.c.width + 200 || p.y > this.c.height + 100) continue;
      const sel = state.sel === a.id;
      const top = p.y - z * (a.age < 14 ? 0.75 : 1.0);
      const talking = a.convo && a.say && sim.time - a.say.t < 14;
      let shown = false;
      if (talking && (close || sel || state.bubbles === "all")) {
        const box = bubbleBox(ctx, a.say.text, p.x, top - 6 * d, d);
        if (sel || free(box.x, box.y, box.w, box.h)) {
          bubble(ctx, a.say.text, p.x, top - 6 * d, d, sel);
          shown = true;
        }
      }
      if (shown) {
        // Bubble drawn.
      } else if (a.convo) {
        ctx.font = `${Math.round(12 * d)}px system-ui`;
        ctx.fillText("💬", p.x, top - 4 * d);
      } else if (close && a.action) {
        const icon = actionIcon(a);
        if (icon) {
          ctx.font = `${Math.round(11 * d)}px system-ui`;
          ctx.fillText(icon, p.x, top - 4 * d);
        }
      }
      if (sel || (state.names && z >= 24 * d)) {
        ctx.font = `600 ${Math.round(11 * d)}px system-ui, sans-serif`;
        const w = ctx.measureText(a.name).width + 8 * d;
        if (!free(p.x - w / 2, p.y + 3 * d, w, 15 * d) && !sel) continue;
        ctx.fillStyle = sel ? "rgba(255,214,90,0.95)" : "rgba(20,22,30,0.6)";
        roundRect(ctx, p.x - w / 2, p.y + 3 * d, w, 15 * d, 7 * d);
        ctx.fill();
        ctx.fillStyle = sel ? "#2a1f00" : "#fff";
        ctx.fillText(a.name, p.x, p.y + 10.5 * d);
      }
    }
  }

  drawFx(now) {
    const ctx = this.ctx;
    const z = this.cam.z;
    const d = this.dpr;
    const t = Date.now();
    this.sim.fx = this.sim.fx.filter((f) => t - f.t0 < 1600);
    for (const f of this.sim.fx) {
      const age = (t - f.t0) / 1000;
      const p = this.toScreen(f.x, f.y);
      if (f.kind === "float") {
        ctx.globalAlpha = Math.max(0, 1 - age / 1.4);
        ctx.font = `700 ${Math.round(12 * d)}px system-ui`;
        ctx.fillStyle = "#fff";
        ctx.strokeStyle = "rgba(0,0,0,0.6)";
        ctx.lineWidth = 3 * d;
        ctx.strokeText(f.text, p.x, p.y - age * 26 * d);
        ctx.fillText(f.text, p.x, p.y - age * 26 * d);
        ctx.globalAlpha = 1;
      } else if (f.kind === "bolt" && age < 0.5) {
        if (age < 0.08) {
          ctx.fillStyle = "rgba(255,255,255,0.5)";
          ctx.fillRect(0, 0, this.c.width, this.c.height);
        }
        ctx.strokeStyle = `rgba(230,240,255,${1 - age * 2})`;
        ctx.lineWidth = 3 * d;
        ctx.beginPath();
        let x = p.x + 40 * d;
        let y = 0;
        ctx.moveTo(x, y);
        const steps = 8;
        for (let k = 1; k <= steps; k++) {
          y = (p.y * k) / steps;
          x = p.x + (k === steps ? 0 : (tileHash(k, f.t0 % 997, 5) - 0.5) * 50 * d + (40 * d * (steps - k)) / steps);
          ctx.lineTo(x, y);
        }
        ctx.stroke();
      } else if (f.kind === "meteor") {
        if (age < 0.6) {
          const k = age / 0.6;
          const mx = p.x + (1 - k) * 300 * d;
          const my = p.y - (1 - k) * 500 * d;
          ctx.fillStyle = "rgba(255,200,90,0.9)";
          ctx.beginPath();
          ctx.arc(mx, my, 10 * d, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "rgba(255,120,40,0.6)";
          ctx.lineWidth = 8 * d;
          ctx.beginPath();
          ctx.moveTo(mx, my);
          ctx.lineTo(mx + 60 * d, my - 100 * d);
          ctx.stroke();
        } else {
          if (!f.boom) {
            f.boom = true;
            this.shake = 24 * d;
          }
          const k = (age - 0.6) / 1;
          ctx.fillStyle = `rgba(255,170,60,${Math.max(0, 0.8 - k)})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, z * (1 + k * 5), 0, Math.PI * 2);
          ctx.fill();
        }
      } else if (f.kind === "bless") {
        ctx.strokeStyle = `rgba(255,226,120,${Math.max(0, 1 - age)})`;
        ctx.lineWidth = 4 * d;
        ctx.beginPath();
        ctx.arc(p.x, p.y, z * (0.5 + age * 4), 0, Math.PI * 2);
        ctx.stroke();
        ctx.font = `${Math.round(14 * d)}px system-ui`;
        for (let k = 0; k < 6; k++) {
          const ang = k + age * 2;
          ctx.globalAlpha = Math.max(0, 1 - age);
          ctx.fillText("✨", p.x + Math.cos(ang) * z * 2, p.y + Math.sin(ang) * z * 2 - age * 20 * d);
        }
        ctx.globalAlpha = 1;
      }
    }
  }
}

// ---------- pieces ----------
function makeGlow() {
  const g = document.createElement("canvas");
  g.width = g.height = 64;
  const c = g.getContext("2d");
  const grd = c.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,196,110,0.75)");
  grd.addColorStop(0.4, "rgba(255,160,70,0.28)");
  grd.addColorStop(1, "rgba(255,140,60,0)");
  c.fillStyle = grd;
  c.fillRect(0, 0, 64, 64);
  return g;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function wrap(ctx, text, maxW) {
  const words = text.split(" ");
  const lines = [];
  let cur = "";
  for (const w of words) {
    const t = cur ? cur + " " + w : w;
    if (ctx.measureText(t).width > maxW && cur) {
      lines.push(cur);
      cur = w;
    } else cur = t;
  }
  if (cur) lines.push(cur);
  if (lines.length > 3) {
    lines.length = 3;
    lines[2] = lines[2].replace(/\s*\S*$/, "") + "…";
  }
  return lines;
}

function bubbleBox(ctx, text, x, y, d) {
  ctx.font = `${Math.round(11 * d)}px system-ui, sans-serif`;
  const lines = wrap(ctx, text, 150 * d);
  const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 12 * d;
  const h = lines.length * 13 * d + 8 * d;
  const cw = ctx.canvas.width;
  return { x: Math.max(4 * d, Math.min(cw - w - 4 * d, x - w / 2)), y: y - h - 5 * d, w, h: h + 5 * d };
}

function bubble(ctx, text, x, y, d, sel) {
  ctx.font = `${Math.round(11 * d)}px system-ui, sans-serif`;
  const lines = wrap(ctx, text, 150 * d);
  const lh = 13 * d;
  const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 12 * d;
  const h = lines.length * lh + 8 * d;
  const cw = ctx.canvas.width;
  const bx = Math.max(4 * d, Math.min(cw - w - 4 * d, x - w / 2));
  const by = y - h - 5 * d;
  ctx.fillStyle = sel ? "rgba(255,248,220,0.97)" : "rgba(255,255,255,0.93)";
  ctx.strokeStyle = sel ? "#e2b23a" : "rgba(0,0,0,0.25)";
  ctx.lineWidth = 1 * d;
  roundRect(ctx, bx, by, w, h, 7 * d);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x - 4 * d, by + h - 0.5);
  ctx.lineTo(x, by + h + 5 * d);
  ctx.lineTo(x + 4 * d, by + h - 0.5);
  ctx.fill();
  ctx.fillStyle = "#222";
  lines.forEach((l, k) => ctx.fillText(l, bx + w / 2, by + 4 * d + lh * (k + 0.5)));
}

function actionIcon(a) {
  const k = a.action.kind;
  const doing = a.action.phase === "do";
  if (a.carry) return a.carry.type === "wood" ? "🪵" : a.carry.type === "stone" ? "🪨" : "🍞";
  if (!doing) return k === "flee" ? "😱" : k === "fight" ? "⚔️" : null;
  return { sleep: "💤", eat: "🍽️", farm: "🌾", chop: "🪓", mine: "⛏️", build: "🔨", party: "🎉", firefight: "🪣", fight: "⚔️", learn: "📖", heal: "🩹", socialize: "🍻", explore: "🧭" }[k] || null;
}

function drawGrave(ctx, x, y) {
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.fillRect(x - 0.18, y + 0.05, 0.36, 0.08);
  ctx.fillStyle = "#9a9a9a";
  ctx.fillRect(x - 0.13, y - 0.3, 0.26, 0.35);
  ctx.beginPath();
  ctx.arc(x, y - 0.3, 0.13, Math.PI, 0);
  ctx.fill();
  ctx.fillStyle = "#6e6e6e";
  ctx.fillRect(x - 0.02, y - 0.32, 0.04, 0.18);
  ctx.fillRect(x - 0.07, y - 0.26, 0.14, 0.04);
}

function drawFire(ctx, x, y, now, life) {
  const t = now / 120;
  for (let k = 0; k < 3; k++) {
    const fx = x + 0.2 + k * 0.3;
    const h = 0.45 + Math.sin(t + k * 2 + x) * 0.15;
    ctx.fillStyle = k === 1 ? "rgba(255,210,80,0.95)" : "rgba(255,110,40,0.9)";
    ctx.beginPath();
    ctx.moveTo(fx - 0.14, y + 0.9);
    ctx.quadraticCurveTo(fx - 0.1, y + 0.9 - h * 0.6, fx, y + 0.9 - h);
    ctx.quadraticCurveTo(fx + 0.1, y + 0.9 - h * 0.6, fx + 0.14, y + 0.9);
    ctx.fill();
  }
  if (Math.sin(t * 0.7 + y) > 0.6) {
    ctx.fillStyle = "rgba(80,80,80,0.4)";
    ctx.beginPath();
    ctx.arc(x + 0.5, y - 0.2 - ((now / 600) % 1) * 0.6, 0.2, 0, Math.PI * 2);
    ctx.fill();
  }
}

function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v) => Math.max(0, Math.min(255, Math.round(v * k)));
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
}

function drawBuilding(ctx, sim, b, now, light, selected, z) {
  const d = BUILDINGS[b.type];
  const v = sim.villageById(b.village);
  const vc = v ? v.color : "#fff";
  const { x, y, w, h } = b;
  const pct = d.work ? b.progress / d.work : 1;
  const lw = 1 / z;
  if (!b.done) {
    // Blueprint and scaffolding.
    ctx.fillStyle = "rgba(255,255,255,0.12)";
    ctx.fillRect(x, y, w, h);
    ctx.setLineDash([0.18, 0.12]);
    ctx.strokeStyle = vc;
    ctx.lineWidth = 2 * lw;
    ctx.strokeRect(x + 0.05, y + 0.05, w - 0.1, h - 0.1);
    ctx.setLineDash([]);
    if (b.funded && pct > 0) {
      const hh = h * 0.8 * pct;
      ctx.fillStyle = d.wall || "#c8a27a";
      ctx.fillRect(x + 0.15, y + h - 0.1 - hh, w - 0.3, hh);
      ctx.strokeStyle = "#8a6a44";
      ctx.lineWidth = 2 * lw;
      for (let k = 0; k <= w; k += 0.5) {
        ctx.beginPath();
        ctx.moveTo(x + k, y + h);
        ctx.lineTo(x + k, y + 0.1);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.moveTo(x, y + h * 0.4);
      ctx.lineTo(x + w, y + h * 0.4);
      ctx.stroke();
    } else if (!b.funded) {
      ctx.fillStyle = "rgba(160,120,70,0.8)";
      ctx.fillRect(x + w / 2 - 0.25, y + h / 2 - 0.12, 0.5, 0.25);
    }
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    ctx.fillRect(x, y - 0.25, w, 0.14);
    ctx.fillStyle = "#7dff9a";
    ctx.fillRect(x, y - 0.25, w * pct, 0.14);
    if (selected) outline(ctx, b, z);
    return;
  }
  const lit = light < 0.6;
  const win = lit ? "#ffd27a" : "#5c6f86";
  // Shadow.
  ctx.fillStyle = "rgba(0,0,0,0.22)";
  ctx.fillRect(x + 0.12, y + 0.2, w, h);
  switch (b.type) {
    case "farm": {
      ctx.fillStyle = "#8a6440";
      ctx.fillRect(x, y, w, h);
      const g = b.growth / 100;
      const r = Math.round(90 + g * 150);
      const gg = Math.round(170 - g * 10);
      ctx.fillStyle = `rgb(${r},${gg},60)`;
      for (let k = 0.2; k < h; k += 0.45) ctx.fillRect(x + 0.12, y + k, w - 0.24, 0.12 + g * 0.16);
      ctx.strokeStyle = "#6b4a2a";
      ctx.lineWidth = 2 * lw;
      ctx.strokeRect(x + 0.04, y + 0.04, w - 0.08, h - 0.08);
      ctx.fillStyle = "#c79a5a";
      ctx.fillRect(x + w - 0.6, y + 0.3, 0.06, 0.5);
      ctx.fillRect(x + w - 0.75, y + 0.42, 0.36, 0.05);
      break;
    }
    case "park": {
      ctx.fillStyle = "#5fbf5a";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#d8c49a";
      ctx.fillRect(x + w / 2 - 0.12, y, 0.24, h);
      ctx.fillRect(x, y + h / 2 - 0.12, w, 0.24);
      for (const [fx, fy, c] of [[0.4, 0.4, "#ff6b8a"], [1.5, 0.5, "#ffe066"], [0.5, 1.5, "#b48cff"], [1.6, 1.6, "#ff9f43"]]) {
        ctx.fillStyle = c;
        ctx.beginPath();
        ctx.arc(x + fx, y + fy, 0.1, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = "#2f7a3a";
      ctx.beginPath();
      ctx.arc(x + 1.5, y + 0.5, 0.35, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "well": {
      ctx.fillStyle = "#8f8f8f";
      ctx.beginPath();
      ctx.arc(x + 0.5, y + 0.6, 0.38, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#3a78c2";
      ctx.beginPath();
      ctx.arc(x + 0.5, y + 0.6, 0.24, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#7a4b2a";
      ctx.fillRect(x + 0.12, y - 0.05, 0.06, 0.65);
      ctx.fillRect(x + 0.82, y - 0.05, 0.06, 0.65);
      ctx.fillStyle = "#a0472f";
      ctx.fillRect(x + 0.02, y - 0.15, 0.96, 0.18);
      break;
    }
    case "statue": {
      ctx.fillStyle = "#8d8d8d";
      ctx.fillRect(x + 0.15, y + 0.6, 0.7, 0.35);
      ctx.fillStyle = "#c9c9c9";
      ctx.fillRect(x + 0.38, y + 0.05, 0.24, 0.55);
      ctx.beginPath();
      ctx.arc(x + 0.5, y - 0.05, 0.14, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "market": {
      wall(ctx, x, y, w, h, d.wall, 0.45);
      const stripes = ["#7b4fa0", "#f4eee4"];
      for (let k = 0; k < 6; k++) {
        ctx.fillStyle = stripes[k % 2];
        ctx.fillRect(x + (k * w) / 6, y - 0.1, w / 6, h * 0.5);
      }
      ctx.fillStyle = "#c0392b";
      for (let k = 0; k < 3; k++) {
        ctx.beginPath();
        ctx.arc(x + 0.5 + k, y + h - 0.3, 0.12, 0, Math.PI * 2);
        ctx.fill();
      }
      break;
    }
    case "tower": {
      ctx.fillStyle = shade(d.wall, 0.8);
      ctx.fillRect(x + 0.35, y - 1.2, w - 0.7, h + 1.1);
      ctx.fillStyle = d.wall;
      ctx.fillRect(x + 0.45, y - 1.2, w - 0.9, h + 1.1);
      ctx.fillStyle = shade(d.wall, 0.7);
      for (let k = 0; k < 4; k++) ctx.fillRect(x + 0.3 + k * 0.38, y - 1.45, 0.24, 0.3);
      ctx.fillStyle = win;
      ctx.fillRect(x + w / 2 - 0.1, y - 0.6, 0.2, 0.3);
      ctx.fillStyle = "#4a3426";
      ctx.fillRect(x + w / 2 - 0.18, y + h - 0.55, 0.36, 0.5);
      flag(ctx, x + w / 2, y - 1.45, vc, now);
      break;
    }
    default: {
      // Houses and other buildings: a front wall with a roof above.
      const wallC = d.wall || "#d7b98e";
      const roofC = d.roof || "#b5523b";
      const roofH = h * 0.62;
      wall(ctx, x, y, w, h, wallC, roofH);
      ctx.fillStyle = roofC;
      ctx.beginPath();
      ctx.moveTo(x - 0.08, y + roofH);
      ctx.lineTo(x + 0.25, y - 0.25);
      ctx.lineTo(x + w - 0.25, y - 0.25);
      ctx.lineTo(x + w + 0.08, y + roofH);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = shade(roofC, 0.75);
      ctx.fillRect(x + 0.25, y - 0.25, w - 0.5, 0.12);
      for (let k = y + 0.05; k < y + roofH; k += 0.28) {
        ctx.fillRect(x + 0.05, k, w - 0.1, 0.03);
      }
      // Door and windows.
      ctx.fillStyle = "#5a3a24";
      ctx.fillRect(x + w / 2 - 0.15, y + h - 0.48, 0.3, 0.45);
      ctx.fillStyle = win;
      ctx.fillRect(x + 0.25, y + roofH + 0.12, 0.25, 0.2);
      ctx.fillRect(x + w - 0.5, y + roofH + 0.12, 0.25, 0.2);
      if (b.type === "townhall") flag(ctx, x + w / 2, y - 0.25, vc, now);
      if (b.type === "clinic") {
        ctx.fillStyle = "#fff";
        ctx.fillRect(x + w / 2 - 0.22, y + 0.15, 0.44, 0.44);
        ctx.fillStyle = "#2e9e5b";
        ctx.fillRect(x + w / 2 - 0.05, y + 0.2, 0.1, 0.34);
        ctx.fillRect(x + w / 2 - 0.17, y + 0.32, 0.34, 0.1);
      }
      if (b.type === "temple") {
        ctx.fillStyle = "#e7c34a";
        ctx.beginPath();
        ctx.moveTo(x + w / 2 - 0.25, y - 0.2);
        ctx.lineTo(x + w / 2, y - 1.1);
        ctx.lineTo(x + w / 2 + 0.25, y - 0.2);
        ctx.fill();
      }
      if (b.type === "school") {
        ctx.fillStyle = "#e7c34a";
        ctx.fillRect(x + w / 2 - 0.12, y - 0.55, 0.24, 0.3);
      }
      if (b.type === "tavern") {
        ctx.fillStyle = "#e0a84a";
        ctx.fillRect(x + w - 0.35, y + roofH - 0.05, 0.3, 0.22);
      }
      if ((b.type === "house" || b.type === "tavern" || b.type === "townhall") && Math.sin(now / 900 + b.id) > -0.2) {
        ctx.fillStyle = "rgba(200,200,200,0.35)";
        const s = (now / 1800 + b.id * 0.37) % 1;
        ctx.beginPath();
        ctx.arc(x + w - 0.5 + s * 0.3, y - 0.4 - s * 0.8, 0.12 + s * 0.15, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
  if (b.hp < 100) {
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    ctx.fillRect(x, y - 0.4, w, 0.12);
    ctx.fillStyle = "#ff5e4d";
    ctx.fillRect(x, y - 0.4, (w * b.hp) / 100, 0.12);
  }
  if (selected) outline(ctx, b, z);
}

function wall(ctx, x, y, w, h, c, top) {
  ctx.fillStyle = c;
  ctx.fillRect(x + 0.05, y + top - 0.1, w - 0.1, h - top + 0.08);
  ctx.fillStyle = shade(c, 0.82);
  ctx.fillRect(x + 0.05, y + h - 0.1, w - 0.1, 0.08);
}

function flag(ctx, x, y, c, now) {
  ctx.fillStyle = "#5a4a3a";
  ctx.fillRect(x - 0.03, y - 0.9, 0.06, 0.9);
  ctx.fillStyle = c;
  const wave = Math.sin(now / 250) * 0.06;
  ctx.beginPath();
  ctx.moveTo(x + 0.03, y - 0.9);
  ctx.lineTo(x + 0.5, y - 0.78 + wave);
  ctx.lineTo(x + 0.03, y - 0.62);
  ctx.fill();
}

function outline(ctx, b, z) {
  ctx.strokeStyle = "#ffd65a";
  ctx.lineWidth = 3 / z;
  ctx.strokeRect(b.x - 0.1, b.y - 0.35, b.w + 0.2, b.h + 0.45);
}

// Text sized in tiles, drawn at a whole-pixel font so every browser renders it.
function worldText(ctx, text, x, y, size, z) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(1 / z, 1 / z);
  ctx.font = `${Math.max(6, Math.round(size * z))}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 0, 0);
  ctx.restore();
}

function drawAgent(ctx, sim, a, now, z, sel) {
  const child = a.age < 14;
  const s = child ? 0.7 : 1;
  const x = a.x;
  const y = a.y;
  const sleeping = a.action && a.action.kind === "sleep" && a.action.phase === "do";
  if (sel) {
    ctx.strokeStyle = "#ffd65a";
    ctx.lineWidth = 2.5 / z;
    ctx.beginPath();
    ctx.ellipse(x, y + 0.05, 0.42, 0.18, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath();
  ctx.ellipse(x, y + 0.05, 0.22 * s, 0.08, 0, 0, Math.PI * 2);
  ctx.fill();
  if (z < 9) {
    ctx.fillStyle = JOBS[a.job].color;
    ctx.fillRect(x - 0.2, y - 0.6 * s, 0.4, 0.6 * s);
    return;
  }
  const shirt = JOBS[a.job].color;
  if (sleeping) {
    ctx.fillStyle = shirt;
    ctx.fillRect(x - 0.3 * s, y - 0.18, 0.5 * s, 0.18);
    ctx.fillStyle = a.look.skin;
    ctx.beginPath();
    ctx.arc(x + 0.28 * s, y - 0.1, 0.11 * s, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    worldText(ctx, "z", x + 0.4, y - 0.4 - ((now / 800) % 1) * 0.2, 0.3, z);
    return;
  }
  const moving = a.action && a.action.phase === "walk";
  const step = moving ? Math.sin(a.walk * 6) : 0;
  const bob = moving ? Math.abs(step) * 0.04 : 0;
  // Legs.
  ctx.fillStyle = "#3d3a4a";
  ctx.fillRect(x - 0.12 * s, y - 0.25 * s - bob, 0.09 * s, 0.25 * s + step * 0.05);
  ctx.fillRect(x + 0.03 * s, y - 0.25 * s - bob, 0.09 * s, 0.25 * s - step * 0.05);
  // Body.
  ctx.fillStyle = shirt;
  ctx.fillRect(x - 0.17 * s, y - 0.56 * s - bob, 0.34 * s, 0.33 * s);
  ctx.fillStyle = "rgba(0,0,0,0.12)";
  ctx.fillRect(x - 0.17 * s, y - 0.3 * s - bob, 0.34 * s, 0.07 * s);
  // Arms.
  ctx.fillStyle = a.look.skin;
  ctx.fillRect(x - 0.22 * s, y - 0.52 * s - bob - step * 0.03, 0.06 * s, 0.24 * s);
  ctx.fillRect(x + 0.16 * s, y - 0.52 * s - bob + step * 0.03, 0.06 * s, 0.24 * s);
  // Head.
  const hy = y - 0.7 * s - bob;
  ctx.fillStyle = a.sick ? "#a9d18e" : a.look.skin;
  ctx.beginPath();
  ctx.arc(x, hy, 0.15 * s, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = a.age >= 62 ? "#d9d9d9" : a.look.hair;
  ctx.beginPath();
  ctx.arc(x, hy - 0.02 * s, 0.155 * s, Math.PI * 1.05, Math.PI * 1.95);
  ctx.fill();
  if (a.look.hairStyle === 1) ctx.fillRect(x - 0.16 * s * a.facing - (a.facing < 0 ? 0.06 * s : 0), hy - 0.06 * s, 0.06 * s, 0.22 * s);
  if (a.look.hairStyle === 2) {
    ctx.beginPath();
    ctx.arc(x - 0.1 * s * a.facing, hy - 0.12 * s, 0.07 * s, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.fillStyle = "#222";
  ctx.fillRect(x + 0.05 * s * a.facing - 0.015, hy - 0.01, 0.03 * s, 0.035 * s);
  if (a.carry) {
    ctx.fillStyle = a.carry.type === "wood" ? "#8a5a2b" : a.carry.type === "stone" ? "#9a9a9a" : "#e0b04a";
    ctx.fillRect(x - 0.15 * s, y - 1.0 * s - bob, 0.3 * s, 0.12 * s);
  }
  if (a.partner != null && sim.agentById(a.partner) && Math.abs(sim.agentById(a.partner).x - x) < 1.5 && Math.abs(sim.agentById(a.partner).y - y) < 1.5) {
    ctx.fillStyle = "#ff6b8a";
    worldText(ctx, "♥", x, hy - 0.3, 0.28, z);
  }
}

function drawAnimal(ctx, n, now, light) {
  const x = n.x;
  const y = n.y;
  const step = n.path ? Math.sin(n.walk * 8) * 0.04 : 0;
  ctx.fillStyle = "rgba(0,0,0,0.22)";
  ctx.beginPath();
  ctx.ellipse(x, y + 0.04, 0.26, 0.08, 0, 0, Math.PI * 2);
  ctx.fill();
  const f = n.facing;
  if (n.kind === "sheep") {
    ctx.fillStyle = "#3a3a3a";
    ctx.fillRect(x - 0.15, y - 0.16, 0.06, 0.16 + step);
    ctx.fillRect(x + 0.09, y - 0.16, 0.06, 0.16 - step);
    ctx.fillStyle = "#f4f1ea";
    ctx.beginPath();
    ctx.ellipse(x, y - 0.25, 0.26, 0.17, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#3a3a3a";
    ctx.beginPath();
    ctx.ellipse(x + 0.25 * f, y - 0.3, 0.09, 0.07, 0, 0, Math.PI * 2);
    ctx.fill();
  } else {
    ctx.fillStyle = "#5d5d66";
    ctx.fillRect(x - 0.2, y - 0.18, 0.06, 0.18 + step);
    ctx.fillRect(x + 0.12, y - 0.18, 0.06, 0.18 - step);
    ctx.fillStyle = "#7c7c86";
    ctx.fillRect(x - 0.25, y - 0.38, 0.5, 0.22);
    ctx.fillRect(x + 0.18 * f - 0.08, y - 0.5, 0.2, 0.18);
    ctx.beginPath();
    ctx.moveTo(x + 0.22 * f, y - 0.5);
    ctx.lineTo(x + 0.18 * f, y - 0.62);
    ctx.lineTo(x + 0.12 * f, y - 0.5);
    ctx.fill();
    ctx.fillRect(x - 0.3 * f - 0.06, y - 0.36, 0.14, 0.05);
    ctx.fillStyle = light < 0.5 ? "#ff3b3b" : "#222";
    ctx.fillRect(x + 0.22 * f - 0.02, y - 0.45, 0.04, 0.04);
  }
}
