/* FCC Studio HQ — the whole team as a pixel office.

   Every part of the agentic workflow is a station: Jarvis's command desk,
   the research library, code workshop, test bench, science lab, video
   studio, memory archive, classroom, model room, approval desk, toolshed,
   mailroom, and break room. Agents walk to the station of the tool they're
   using, work there (typing, bubbling flasks, blinking servers), and go back
   to the break room when they're done. Click an agent to see what it is
   doing and talk to it or stop it; click a station to see what's waiting
   there. Studio calls FCCHQ.render(ctx). Everything is drawn on a 480x300
   canvas and scaled up pixel-sharp; no image files. */
(() => {
  "use strict";

  const W = 480;
  const H = 300;
  const POLL_MS = 2000;
  const SPEED = 90; // pixels a second

  // ------------------------------------------------------------ the map

  const ROW_A = { top: 40, bottom: 92, walk: 104 };
  const ROW_B = { top: 124, bottom: 176, walk: 190 };
  const ROW_C = { top: 212, bottom: 262, walk: 276 };
  const LAYOUT = {
    library: { x: 10, w: 86, row: ROW_A },
    workshop: { x: 104, w: 86, row: ROW_A },
    testbench: { x: 198, w: 84, row: ROW_A },
    lab: { x: 290, w: 84, row: ROW_A },
    studio: { x: 382, w: 88, row: ROW_A },
    archive: { x: 10, w: 86, row: ROW_B },
    desk: { x: 118, w: 146, row: ROW_B },
    approvals: { x: 280, w: 84, row: ROW_B },
    servers: { x: 382, w: 88, row: ROW_B },
    school: { x: 10, w: 104, row: ROW_C },
    toolshed: { x: 122, w: 76, row: ROW_C },
    mailroom: { x: 206, w: 76, row: ROW_C },
    lounge: { x: 290, w: 180, row: ROW_C },
  };
  const LABELS = {
    library: "LIBRARY",
    workshop: "WORKSHOP",
    testbench: "TEST BENCH",
    lab: "LAB",
    studio: "STUDIO",
    archive: "MEMORY",
    desk: "COMMAND DESK",
    approvals: "APPROVALS",
    servers: "MODELS",
    school: "CLASSROOM",
    toolshed: "TOOLSHED",
    mailroom: "MAILROOM",
    lounge: "BREAK ROOM",
  };
  const TOOL_ICON = {
    web_search: "search", web_fetch: "page", research: "search", ask_researcher: "chat", find_images: "page",
    write_file: "code", edit_file: "code", read_file: "page", start_project: "code", update_plan: "list",
    run_command: "play", test_code: "play", check_project: "check", polish_check: "check", code_and_test: "play",
    lab: "flask", farm: "film", remember: "brain", recall: "brain", knowledge: "brain", learn: "book",
    skill: "tool", mcp: "tool", todo: "list", ask_agent: "chat", team_task: "chat", ask_helper: "chat",
  };

  // ------------------------------------------------------------ pixel font

  const FONT = {
    A: "010101111101101", B: "110101110101110", C: "011100100100011", D: "110101101101110",
    E: "111100110100111", F: "111100110100100", G: "011100101101011", H: "101101111101101",
    I: "111010010010111", J: "001001001101010", K: "101101110101101", L: "100100100100111",
    M: "101111111101101", N: "110101101101101", O: "010101101101010", P: "110101110100100",
    Q: "010101101110011", R: "110101110101101", S: "011100010001110", T: "111010010010010",
    U: "101101101101111", V: "101101101101010", W: "101101111111101", X: "101101010101101",
    Y: "101101010010010", Z: "111001010100111", "0": "111101101101111", "1": "010110010010111",
    "2": "110001010100111", "3": "110001010001110", "4": "101101111001001", "5": "111100110001110",
    "6": "011100111101111", "7": "111001010010010", "8": "111101111101111", "9": "111101111001110",
    " ": "000000000000000", ".": "000000000000010", "-": "000000111000000", "!": "010010010000010",
    "?": "110001010000010", ":": "000010000010000", "/": "001001010100100", "'": "010010000000000",
    "+": "000010111010000", "&": "010101010101011", "<": "001010100010001",
    ">": "100010001010100", "=": "000111000111000", "(": "010100100100010", ")": "010001001001010",
  };

  function text(g, words, x, y, colour, shadow) {
    const up = String(words).toUpperCase();
    let at = Math.round(x);
    for (const char of up) {
      const glyph = FONT[char] || FONT["?"];
      for (let i = 0; i < 15; i += 1) {
        if (glyph[i] === "1") {
          const px = at + (i % 3);
          const py = Math.round(y) + Math.floor(i / 3);
          if (shadow) {
            g.fillStyle = shadow;
            g.fillRect(px + 1, py + 1, 1, 1);
          }
          g.fillStyle = colour;
          g.fillRect(px, py, 1, 1);
        }
      }
      at += 4;
    }
  }
  const textWidth = (words) => String(words).length * 4 - 1;

  // ------------------------------------------------------------ helpers

  const rect = (g, x, y, w, h, colour) => {
    g.fillStyle = colour;
    g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  };
  const hue = (name) => {
    let hash = 7;
    for (const char of String(name || "")) hash = (hash * 31 + char.charCodeAt(0)) % 360;
    return hash;
  };
  const SKINS = ["#f1c7a1", "#d9a77c", "#b97d52", "#8d5a37", "#6a4026"];
  const HAIRS = ["#2a1d14", "#4a2c18", "#8a5a2b", "#d6b161", "#151515", "#b84a2a"];
  const pick = (list, seed) => list[seed % list.length];

  // ------------------------------------------------------------ state

  const state = {
    data: null,
    agents: new Map(), // id -> sprite
    selected: null, // { kind: "agent"|"station", id }
    activity: null,
    hover: null,
    t: 0,
  };
  let ctx = null;
  let canvas = null;
  let g = null;
  let backdrop = null;
  let panel = null;
  let feed = null;
  let plansBox = null;
  let tip = null;
  let frame = 0;
  let poller = 0;
  let last = 0;

  // ------------------------------------------------------------ layout

  function spot(stationId, slot) {
    const box = LAYOUT[stationId] || LAYOUT.lounge;
    const offsets = [0, -18, 18, -36, 36, -54, 54, -72, 72];
    const centre = box.x + box.w / 2;
    const x = Math.max(box.x + 6, Math.min(box.x + box.w - 6, centre + offsets[slot % offsets.length]));
    return { x, y: box.row.bottom + 5 };
  }

  function route(from, to) {
    // Walk down to the corridor under the row you're in, along it, then up.
    const rows = [ROW_A, ROW_B, ROW_C];
    const near = rows.reduce((best, row) => (Math.abs(row.walk - from.y) < Math.abs(best.walk - from.y) ? row : best));
    const goal = rows.reduce((best, row) => (Math.abs(row.bottom + 5 - to.y) < Math.abs(best.bottom + 5 - to.y) ? row : best));
    const path = [];
    if (near === goal) {
      path.push({ x: from.x, y: goal.walk - 4 }, { x: to.x, y: goal.walk - 4 }, to);
    } else {
      path.push({ x: from.x, y: near.walk - 4 });
      // The corridors join at the left and right edges of the office.
      const side = (from.x + to.x) / 2 < W / 2 ? 4 : W - 6;
      path.push({ x: side, y: near.walk - 4 }, { x: side, y: goal.walk - 4 }, { x: to.x, y: goal.walk - 4 }, to);
    }
    return path;
  }

  function sync(data) {
    state.data = data;
    const byStation = {};
    const seen = new Set();
    for (const agent of data.agents) {
      seen.add(agent.id);
      const slot = (byStation[agent.station] = (byStation[agent.station] || 0) + 1) - 1;
      const target = spot(agent.station, slot);
      let sprite = state.agents.get(agent.id);
      if (!sprite) {
        const seed = hue(agent.name);
        sprite = {
          id: agent.id,
          x: spot("lounge", state.agents.size).x,
          y: spot("lounge", 0).y,
          path: [],
          target: null,
          shirt: agent.main ? "#e6b422" : `hsl(${seed}, 62%, 52%)`,
          trim: agent.main ? "#fff2b0" : `hsl(${seed}, 70%, 72%)`,
          skin: pick(SKINS, seed),
          hair: pick(HAIRS, seed >> 2),
          facing: 1,
          seed,
        };
        state.agents.set(agent.id, sprite);
      }
      sprite.info = agent;
      sprite.slot = slot;
      if (!sprite.target || Math.abs(sprite.target.x - target.x) > 0.5 || Math.abs(sprite.target.y - target.y) > 0.5) {
        sprite.target = target;
        sprite.path = route({ x: sprite.x, y: sprite.y }, target);
      }
    }
    for (const id of [...state.agents.keys()]) if (!seen.has(id)) state.agents.delete(id);
  }

  // ------------------------------------------------------------ the room

  function drawBackdrop() {
    backdrop = document.createElement("canvas");
    backdrop.width = W;
    backdrop.height = H;
    const b = backdrop.getContext("2d");
    // Floor tiles.
    for (let y = 30; y < H; y += 8) {
      for (let x = 0; x < W; x += 8) {
        rect(b, x, y, 8, 8, (x / 8 + y / 8) % 2 ? "#2b3446" : "#262e3f");
        rect(b, x, y, 8, 1, "#303a4e");
      }
    }
    // Corridors: a carpet runner under each row.
    for (const row of [ROW_A, ROW_B, ROW_C]) {
      rect(b, 0, row.walk - 9, W, 10, "#3a2f4a");
      for (let x = 0; x < W; x += 6) rect(b, x, row.walk - 5, 3, 1, "#4b3d60");
    }
    rect(b, 0, 30, 6, H - 30, "#3a2f4a");
    rect(b, W - 8, 30, 8, H - 30, "#3a2f4a");
    // Back wall with windows and the sign.
    rect(b, 0, 0, W, 30, "#1b2233");
    rect(b, 0, 28, W, 3, "#11161f");
    for (let x = 18; x < W; x += 74) {
      rect(b, x, 5, 40, 17, "#0d1220");
      rect(b, x + 2, 7, 36, 13, "#22406b");
      rect(b, x + 2, 7, 36, 4, "#335c94");
      rect(b, x + 19, 7, 2, 13, "#0d1220");
      for (let s = 0; s < 4; s += 1) rect(b, x + 5 + s * 9, 15 + (s % 2) * 2, 1, 1, "#ffe9a8");
    }
    rect(b, 196, 6, 88, 15, "#0b0f18");
    rect(b, 197, 7, 86, 13, "#121b2c");
    text(b, "FCC STUDIO HQ", 214, 11, "#ffd75e", "#000");
    for (const [id, box] of Object.entries(LAYOUT)) furniture(b, id, box);
  }

  function counter(b, box, colour, top) {
    rect(b, box.x, top, box.w, box.row.bottom - top, colour);
    rect(b, box.x, top, box.w, 2, "rgba(255,255,255,0.18)");
    rect(b, box.x, box.row.bottom - 2, box.w, 2, "rgba(0,0,0,0.35)");
  }

  function sign(b, id, box) {
    const words = LABELS[id];
    const width = textWidth(words) + 6;
    const x = Math.round(box.x + (box.w - width) / 2);
    const y = box.row.top - 9;
    rect(b, x, y, width, 8, "#0b0f18");
    rect(b, x + 1, y + 1, width - 2, 6, "#151d2e");
    text(b, words, x + 3, y + 2, "#9fe7ff");
  }

  function furniture(b, id, box) {
    const top = box.row.top;
    const bottom = box.row.bottom;
    const x = box.x;
    const w = box.w;
    // A soft rug under every station.
    rect(b, x - 2, top - 2, w + 4, bottom - top + 6, "rgba(0,0,0,0.18)");
    switch (id) {
      case "library": {
        for (let s = 0; s < 3; s += 1) {
          const sx = x + 2 + s * 28;
          rect(b, sx, top, 26, 34, "#5b3a22");
          for (let shelf = 0; shelf < 4; shelf += 1) {
            rect(b, sx + 1, top + 2 + shelf * 8, 24, 1, "#3b2414");
            for (let k = 0; k < 7; k += 1) {
              const colour = ["#c0392b", "#2e86c1", "#27ae60", "#f1c40f", "#8e44ad", "#e67e22", "#16a085"][(k + shelf + s) % 7];
              rect(b, sx + 2 + k * 3, top + 3 + shelf * 8, 2, 5 + ((k * 7 + shelf) % 2), colour);
            }
          }
        }
        counter(b, box, "#6d4c33", bottom - 14);
        rect(b, x + w / 2 - 8, bottom - 20, 16, 6, "#e8e0c8");
        rect(b, x + w / 2 - 7, bottom - 19, 6, 4, "#b9b09a");
        break;
      }
      case "workshop": {
        counter(b, box, "#3d4a5c", bottom - 16);
        for (let m = 0; m < 3; m += 1) monitor(b, x + 6 + m * 28, bottom - 30, "#1f2c45");
        rect(b, x + 2, top, w - 4, 10, "#2a3446");
        text(b, "</>", x + w - 16, top + 3, "#7ee787");
        break;
      }
      case "testbench": {
        counter(b, box, "#4a3d5c", bottom - 16);
        monitor(b, x + 8, bottom - 30, "#1b2b1b");
        monitor(b, x + 48, bottom - 30, "#2b1b1b");
        rect(b, x + 2, top, w - 4, 12, "#2c2438");
        for (let l = 0; l < 8; l += 1) rect(b, x + 6 + l * 9, top + 4, 4, 4, "#334");
        break;
      }
      case "lab": {
        counter(b, box, "#d8dde4", bottom - 16);
        rect(b, x + 2, top, w - 4, 16, "#b9c2cc");
        rect(b, x + 4, top + 2, w - 8, 1, "#eef3f8");
        for (let f = 0; f < 4; f += 1) {
          const fx = x + 10 + f * 18;
          rect(b, fx, bottom - 26, 6, 10, "rgba(220,240,255,0.65)");
          rect(b, fx + 2, bottom - 30, 2, 4, "rgba(220,240,255,0.65)");
        }
        break;
      }
      case "studio": {
        rect(b, x + 30, top, w - 34, 40, "#2ecc71");
        rect(b, x + 30, top, w - 34, 2, "#27ae60");
        rect(b, x + 6, top + 14, 14, 9, "#222");
        rect(b, x + 18, top + 16, 4, 5, "#555");
        rect(b, x + 12, top + 23, 2, 18, "#444");
        rect(b, x + 7, top + 40, 12, 2, "#444");
        rect(b, x + w - 14, top + 4, 10, 10, "#fff6cc");
        rect(b, x + w - 10, top + 14, 2, 26, "#555");
        counter(b, box, "#26303d", bottom - 8);
        break;
      }
      case "archive": {
        for (let c = 0; c < 4; c += 1) {
          const cx = x + 3 + c * 21;
          rect(b, cx, top + 4, 19, bottom - top - 6, "#7f8c8d");
          for (let d = 0; d < 3; d += 1) {
            rect(b, cx + 1, top + 6 + d * 14, 17, 12, "#95a5a6");
            rect(b, cx + 7, top + 11 + d * 14, 5, 2, "#555");
          }
        }
        break;
      }
      case "desk": {
        rect(b, x + 10, top + 2, w - 20, 26, "#0c2a3a");
        rect(b, x + 12, top + 4, w - 24, 22, "#0f3b52");
        counter(b, box, "#3b2e1e", bottom - 18);
        rect(b, x, bottom - 18, w, 3, "#e6b422");
        monitor(b, x + w / 2 - 12, bottom - 32, "#102a38", 24);
        break;
      }
      case "approvals": {
        counter(b, box, "#5d4632", bottom - 16);
        rect(b, x + 8, bottom - 24, 18, 8, "#c9b28a");
        rect(b, x + 9, bottom - 26, 16, 3, "#efe4cc");
        rect(b, x + w - 26, bottom - 26, 10, 10, "#a33");
        rect(b, x + w - 23, bottom - 30, 4, 4, "#733");
        rect(b, x + 30, top + 2, 26, 18, "#efe4cc");
        text(b, "OK?", x + 37, top + 9, "#a33");
        break;
      }
      case "servers": {
        for (let r = 0; r < 4; r += 1) {
          const rx = x + 3 + r * 21;
          rect(b, rx, top, 19, bottom - top, "#141922");
          rect(b, rx + 1, top + 1, 17, bottom - top - 2, "#1d2430");
          for (let u = 0; u < 7; u += 1) rect(b, rx + 2, top + 3 + u * 7, 15, 5, "#262f3d");
        }
        break;
      }
      case "school": {
        rect(b, x + 6, top, w - 12, 22, "#3b5b3b");
        rect(b, x + 4, top - 2, w - 8, 2, "#7a5a3a");
        rect(b, x + 4, top + 22, w - 8, 2, "#7a5a3a");
        text(b, "A+B=C", x + 12, top + 6, "#eef");
        for (let d = 0; d < 3; d += 1) rect(b, x + 8 + d * 32, bottom - 12, 24, 10, "#8a6a4a");
        break;
      }
      case "toolshed": {
        rect(b, x + 2, top, w - 4, 34, "#6b4f35");
        for (let p = 0; p < 5; p += 1) rect(b, x + 6 + p * 13, top + 4, 2, 24, "#3b2a1b");
        rect(b, x + 8, top + 8, 10, 3, "#aaa");
        rect(b, x + 22, top + 6, 3, 14, "#c0392b");
        rect(b, x + 36, top + 10, 12, 4, "#888");
        counter(b, box, "#4d3a28", bottom - 12);
        rect(b, x + w / 2 - 10, bottom - 18, 20, 7, "#c0392b");
        break;
      }
      case "mailroom": {
        rect(b, x + 2, top, w - 4, 34, "#7a5c3c");
        for (let r = 0; r < 4; r += 1) {
          for (let c = 0; c < 6; c += 1) {
            rect(b, x + 5 + c * 11, top + 3 + r * 8, 9, 6, "#4a3622");
            if ((r + c) % 3 === 0) rect(b, x + 6 + c * 11, top + 4 + r * 8, 6, 3, "#f5f0e0");
          }
        }
        counter(b, box, "#5a4430", bottom - 12);
        break;
      }
      case "lounge": {
        rect(b, x + 8, bottom - 22, 70, 16, "#7d3c98");
        rect(b, x + 8, bottom - 28, 70, 8, "#6c3483");
        rect(b, x + 4, bottom - 24, 6, 18, "#6c3483");
        rect(b, x + 76, bottom - 24, 6, 18, "#6c3483");
        rect(b, x + 94, bottom - 14, 28, 8, "#8a6a4a");
        rect(b, x + 104, bottom - 18, 6, 4, "#fff");
        rect(b, x + w - 34, top + 2, 18, 30, "#555e6b");
        rect(b, x + w - 32, top + 6, 14, 8, "#222");
        rect(b, x + w - 28, top + 18, 6, 6, "#3b2a1b");
        rect(b, x + w - 12, bottom - 26, 8, 20, "#7d5a3c");
        rect(b, x + w - 16, bottom - 38, 16, 14, "#27ae60");
        rect(b, x + w - 13, bottom - 42, 10, 6, "#2ecc71");
        break;
      }
      default:
        break;
    }
    sign(b, id, box);
  }

  function monitor(b, x, y, glow, width = 20) {
    rect(b, x, y, width, 13, "#0b0f18");
    rect(b, x + 1, y + 1, width - 2, 11, glow);
    rect(b, x + width / 2 - 2, y + 13, 4, 3, "#333");
  }

  // ------------------------------------------------------------ animation

  function animate(g2, t) {
    const busyAt = new Set([...state.agents.values()].filter((s) => s.info && s.info.busy && arrived(s)).map((s) => s.info.station));
    const blink = (n) => Math.floor(t * 4 + n) % 3 === 0;
    // Servers blink always; faster when models are working.
    const servers = LAYOUT.servers;
    for (let r = 0; r < 4; r += 1) {
      for (let u = 0; u < 7; u += 1) {
        const on = blink(r * 7 + u + (busyAt.size ? t * 6 : 0));
        rect(g2, servers.x + 6 + r * 21, servers.row.top + 4 + u * 7, 2, 2, on ? "#2ecc71" : "#145a32");
        rect(g2, servers.x + 10 + r * 21, servers.row.top + 4 + u * 7, 2, 2, blink(u + r) ? "#f39c12" : "#5a3d0d");
      }
    }
    // Monitors flicker with code when someone is at them.
    for (const id of ["workshop", "testbench", "desk"]) {
      const box = LAYOUT[id];
      if (!busyAt.has(id) && id !== "desk") continue;
      const count = id === "desk" ? 1 : id === "workshop" ? 3 : 2;
      for (let m = 0; m < count; m += 1) {
        const mx = id === "desk" ? box.x + box.w / 2 - 10 : box.x + 8 + m * (id === "workshop" ? 28 : 40);
        const my = box.row.bottom - (id === "desk" ? 30 : 28);
        for (let l = 0; l < 4; l += 1) {
          const len = 4 + ((Math.floor(t * 3) + l * 5 + m) % 9);
          const colour = id === "testbench" ? (m === 0 ? "#2ecc71" : "#e74c3c") : id === "desk" ? "#ffd75e" : "#7ee787";
          rect(g2, mx, my + l * 2, Math.min(len, id === "desk" ? 20 : 16), 1, colour);
        }
      }
    }
    // Jarvis's holo screen.
    const desk = LAYOUT.desk;
    for (let i = 0; i < 6; i += 1) {
      const wave = Math.sin(t * 2 + i) * 4;
      rect(g2, desk.x + 20 + i * 18, desk.row.top + 12 + wave, 10, 1, "rgba(120,220,255,0.7)");
    }
    rect(g2, desk.x + desk.w / 2 - 3, desk.row.top + 8 + Math.sin(t * 3) * 2, 6, 6, "rgba(255,215,94,0.85)");
    // Lab flasks bubble.
    const lab = LAYOUT.lab;
    const colours = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6"];
    for (let f = 0; f < 4; f += 1) {
      const fx = lab.x + 10 + f * 18;
      const level = 5 + ((f * 3) % 4);
      rect(g2, fx + 1, lab.row.bottom - 17 - level + 1, 4, level, colours[f]);
      if (busyAt.has("lab")) {
        const rise = (t * 12 + f * 7) % 14;
        rect(g2, fx + 2 + (f % 2), lab.row.bottom - 30 - rise, 1, 1, "rgba(255,255,255,0.8)");
      }
    }
    // Studio: the camera's red light, and the ring light when filming.
    const studio = LAYOUT.studio;
    rect(g2, studio.x + 8, studio.row.top + 16, 2, 2, Math.floor(t * 2) % 2 || !busyAt.has("studio") ? "#e74c3c" : "#600");
    if (busyAt.has("studio") || (state.data && state.data.stations.find((s) => s.id === "studio" && s.count))) {
      rect(g2, studio.x + studio.w - 13, studio.row.top + 5, 8, 8, "#fffbe0");
      g2.fillStyle = "rgba(255,250,210,0.12)";
      g2.fillRect(studio.x + 30, studio.row.top, studio.w - 34, 40);
    }
    // Test bench lights.
    const bench = LAYOUT.testbench;
    for (let l = 0; l < 8; l += 1) {
      const on = busyAt.has("testbench") ? (Math.floor(t * 5) + l) % 4 === 0 : false;
      rect(g2, bench.x + 7 + l * 9, bench.row.top + 5, 2, 2, on ? (l % 3 ? "#2ecc71" : "#e74c3c") : "#1e2330");
    }
    // Approvals: a waiting slip flaps.
    const waiting = state.data ? (state.data.stations.find((s) => s.id === "approvals") || {}).count : 0;
    if (waiting) {
      const ap = LAYOUT.approvals;
      const bob = Math.round(Math.sin(t * 5) * 1.5);
      rect(g2, ap.x + ap.w / 2 - 6, ap.row.top - 20 + bob, 12, 9, "#ffd75e");
      text(g2, String(waiting), ap.x + ap.w / 2 - 1, ap.row.top - 18 + bob, "#000");
    }
    // Classroom chalk and the coffee steam.
    const school = LAYOUT.school;
    if (state.data && (state.data.stations.find((s) => s.id === "school") || {}).count) {
      rect(g2, school.x + 70 + Math.round(Math.sin(t * 4) * 6), school.row.top + 14, 6, 1, "#fff");
    }
    const lounge = LAYOUT.lounge;
    for (let s = 0; s < 3; s += 1) {
      const rise = (t * 8 + s * 4) % 10;
      rect(g2, lounge.x + 105 + Math.round(Math.sin(t * 3 + s) * 1.5), lounge.row.bottom - 20 - rise, 1, 1, "rgba(255,255,255,0.5)");
    }
  }

  const arrived = (sprite) => !sprite.path.length;

  function step(dt) {
    for (const sprite of state.agents.values()) {
      if (!sprite.path.length) continue;
      const next = sprite.path[0];
      const dx = next.x - sprite.x;
      const dy = next.y - sprite.y;
      const dist = Math.hypot(dx, dy);
      const move = SPEED * dt;
      if (dist <= move) {
        sprite.x = next.x;
        sprite.y = next.y;
        sprite.path.shift();
      } else {
        sprite.x += (dx / dist) * move;
        sprite.y += (dy / dist) * move;
        if (Math.abs(dx) > 0.2) sprite.facing = dx > 0 ? 1 : -1;
      }
    }
  }

  function drawAgent(g2, sprite, t) {
    const info = sprite.info || {};
    const walking = sprite.path.length > 0;
    const working = info.busy && !walking;
    const x = Math.round(sprite.x) - 5;
    const bob = working ? Math.round(Math.sin(t * 10 + sprite.seed) * 0.6) : 0;
    const y = Math.round(sprite.y) - 18 + bob;
    const legSwing = walking ? (Math.floor(t * 8 + sprite.seed) % 2 ? 1 : -1) : 0;
    const selected = state.selected && state.selected.kind === "agent" && state.selected.id === sprite.id;
    const hovered = state.hover && state.hover.kind === "agent" && state.hover.id === sprite.id;
    // Shadow, selection ring.
    rect(g2, x, y + 17, 11, 2, "rgba(0,0,0,0.35)");
    if (selected || hovered) {
      g2.strokeStyle = selected ? "#ffd75e" : "rgba(255,255,255,0.6)";
      g2.lineWidth = 1;
      g2.strokeRect(x - 2.5, y - 2.5, 16, 23);
    }
    if (info.main) {
      g2.fillStyle = `rgba(255, 215, 94, ${0.18 + 0.08 * Math.sin(t * 3)})`;
      g2.fillRect(x - 4, y - 4, 19, 26);
    }
    // Legs and shoes.
    rect(g2, x + 3, y + 13, 2, 3 + Math.max(0, legSwing), "#2c3e50");
    rect(g2, x + 6, y + 13, 2, 3 + Math.max(0, -legSwing), "#2c3e50");
    rect(g2, x + 2 + (legSwing > 0 ? 0 : 0), y + 16 + Math.max(0, legSwing), 3, 1, "#111");
    rect(g2, x + 6, y + 16 + Math.max(0, -legSwing), 3, 1, "#111");
    // Body.
    rect(g2, x + 2, y + 7, 7, 7, sprite.shirt);
    rect(g2, x + 2, y + 7, 7, 1, sprite.trim);
    // Arms: typing at a station, swinging when walking.
    const armLift = working ? (Math.floor(t * 12 + sprite.seed) % 2) : 0;
    rect(g2, x + 1, y + 8 + (walking ? -legSwing : 0) - armLift, 1, 4, sprite.shirt);
    rect(g2, x + 9, y + 8 + (walking ? legSwing : 0) - (working ? 1 - armLift : 0), 1, 4, sprite.shirt);
    rect(g2, x + 1, y + 12 + (walking ? -legSwing : 0) - armLift, 1, 1, sprite.skin);
    rect(g2, x + 9, y + 12 + (walking ? legSwing : 0) - (working ? 1 - armLift : 0), 1, 1, sprite.skin);
    // Head, hair, eyes (looking where they walk).
    rect(g2, x + 2, y + 1, 7, 6, sprite.skin);
    rect(g2, x + 2, y, 7, 2, sprite.hair);
    rect(g2, x + (sprite.facing > 0 ? 8 : 2), y + 1, 1, 2, sprite.hair);
    const eye = sprite.facing > 0 ? 1 : 0;
    const blink = Math.floor(t * 0.7 + sprite.seed) % 9 === 0 && (t * 10) % 3 < 1;
    if (!blink) {
      rect(g2, x + 3 + eye, y + 3, 1, 1, "#111");
      rect(g2, x + 6 + eye, y + 3, 1, 1, "#111");
    }
    if (info.main) {
      rect(g2, x + 1, y - 2, 9, 1, "#ffd75e");
      rect(g2, x + 2, y - 3, 1, 1, "#ffd75e");
      rect(g2, x + 5, y - 4, 1, 2, "#ffd75e");
      rect(g2, x + 8, y - 3, 1, 1, "#ffd75e");
    }
    // The name tag is placed after everyone is drawn, so tags never overlap.
    tags.push({ sprite, name: String(info.name || "").slice(0, 10), y: y + 20 });
    if (working) bubble(g2, sprite, x, y, t);
    else if (!info.busy && !walking && info.station === "lounge" && Math.floor(t / 3 + sprite.seed) % 4 === 0) {
      text(g2, "z", x + 11, y - 3 - Math.round((t * 2) % 3), "#9fb3d9");
    }
  }

  // Name tags: each goes in the first of three rows under its owner where
  // it overlaps no other tag. In a crowded room the busy, the hovered, the
  // chosen and Jarvis get a row first; anyone left over is in the team list.
  const tags = [];
  function drawTags(g2) {
    const picked = (tag) => {
      const id = tag.sprite.id;
      return (
        (state.selected && state.selected.kind === "agent" && state.selected.id === id) ||
        (state.hover && state.hover.kind === "agent" && state.hover.id === id)
      );
    };
    const rank = (tag) => (picked(tag) ? 0 : tag.sprite.info.busy ? 1 : tag.sprite.info.main ? 2 : 3);
    const placed = [];
    for (const tag of [...tags].sort((a, b) => rank(a) - rank(b) || a.sprite.x - b.sprite.x)) {
      const w = textWidth(tag.name) + 4;
      const left = tag.sprite.x - w / 2;
      for (let row = 0; row < 3; row += 1) {
        const top = tag.y + row * 8;
        const clash = placed.some((p) => Math.abs(p.top - top) < 8 && left < p.left + p.w + 2 && p.left < left + w + 2);
        if (clash) continue;
        placed.push({ left, top, w });
        rect(g2, left, top, w, 7, "rgba(5,8,14,0.8)");
        text(g2, tag.name, left + 2, top + 1, tag.sprite.info.busy || picked(tag) ? "#ffffff" : "#9aa6b8");
        break;
      }
    }
  }

  function bubble(g2, sprite, x, y, t) {
    const icon = TOOL_ICON[sprite.info.tool] || "dots";
    const bx = x + 6;
    const by = y - 13;
    rect(g2, bx, by, 13, 10, "#f5f7fb");
    rect(g2, bx + 1, by + 10, 3, 2, "#f5f7fb");
    rect(g2, bx - 1, by + 1, 1, 8, "#f5f7fb");
    rect(g2, bx + 13, by + 1, 1, 8, "#f5f7fb");
    const ix = bx + 2;
    const iy = by + 2;
    const ink = "#2b3446";
    switch (icon) {
      case "search":
        rect(g2, ix + 1, iy, 4, 1, ink); rect(g2, ix, iy + 1, 1, 3, ink); rect(g2, ix + 5, iy + 1, 1, 3, ink);
        rect(g2, ix + 1, iy + 4, 4, 1, ink); rect(g2, ix + 5, iy + 5, 2, 1, ink); rect(g2, ix + 7, iy + 6, 1, 1, ink);
        break;
      case "code":
        text(g2, "</>", ix - 1, iy + 1, "#1e8449");
        break;
      case "play":
        for (let r = 0; r < 5; r += 1) rect(g2, ix + 3, iy + r, 1 + Math.min(r, 4 - r) * 2, 1, "#1e8449");
        break;
      case "check":
        rect(g2, ix + 1, iy + 3, 1, 1, "#1e8449"); rect(g2, ix + 2, iy + 4, 1, 1, "#1e8449");
        rect(g2, ix + 3, iy + 5, 1, 1, "#1e8449"); for (let i = 0; i < 4; i += 1) rect(g2, ix + 4 + i, iy + 4 - i, 1, 1, "#1e8449");
        break;
      case "flask":
        rect(g2, ix + 3, iy, 3, 2, ink); rect(g2, ix + 2, iy + 2, 5, 4, "#3498db"); rect(g2, ix + 1, iy + 5, 7, 1, ink);
        break;
      case "film":
        rect(g2, ix, iy + 1, 9, 5, ink); for (let i = 0; i < 4; i += 1) rect(g2, ix + 1 + i * 2, iy + 2, 1, 1, "#f5f7fb");
        break;
      case "brain":
        rect(g2, ix + 1, iy + 1, 7, 4, "#e891b2"); rect(g2, ix + 4, iy + 1, 1, 4, "#c0577f");
        break;
      case "book":
        rect(g2, ix, iy + 1, 4, 5, "#2e86c1"); rect(g2, ix + 5, iy + 1, 4, 5, "#2e86c1"); rect(g2, ix + 4, iy + 1, 1, 5, ink);
        break;
      case "tool":
        rect(g2, ix + 1, iy, 2, 6, ink); rect(g2, ix, iy, 4, 2, ink); rect(g2, ix + 5, iy + 2, 4, 2, "#c0392b");
        break;
      case "list":
        for (let i = 0; i < 3; i += 1) { rect(g2, ix, iy + i * 2, 1, 1, ink); rect(g2, ix + 2, iy + i * 2, 6, 1, ink); }
        break;
      case "chat":
        rect(g2, ix, iy, 9, 5, "#5dade2"); rect(g2, ix + 1, iy + 5, 2, 1, "#5dade2");
        break;
      case "page":
        rect(g2, ix + 1, iy, 6, 7, "#fff"); rect(g2, ix + 1, iy, 6, 1, ink);
        for (let i = 0; i < 3; i += 1) rect(g2, ix + 2, iy + 2 + i * 2, 4, 1, "#aab");
        break;
      default:
        for (let i = 0; i < 3; i += 1) rect(g2, ix + 1 + i * 3, iy + 3, 2, 2, Math.floor(t * 3) % 3 === i ? ink : "#aab");
    }
  }

  function draw(now) {
    if (!ctx || !ctx.alive() || !canvas.isConnected) {
      cancelAnimationFrame(frame);
      return;
    }
    const dt = Math.min(0.1, last ? (now - last) / 1000 : 0);
    last = now;
    state.t += dt;
    step(dt);
    g.imageSmoothingEnabled = false;
    g.drawImage(backdrop, 0, 0);
    animate(g, state.t);
    if (state.selected && state.selected.kind === "station") {
      const box = LAYOUT[state.selected.id];
      g.strokeStyle = "#ffd75e";
      g.strokeRect(box.x - 3.5, box.row.top - 11.5, box.w + 7, box.row.bottom - box.row.top + 16);
    }
    const sprites = [...state.agents.values()].sort((a, b) => a.y - b.y);
    tags.length = 0;
    for (const sprite of sprites) drawAgent(g, sprite, state.t);
    drawTags(g);
    frame = requestAnimationFrame(draw);
  }

  // ------------------------------------------------------------ the page

  async function render(context) {
    ctx = context;
    const h = ctx.el;
    canvas = h("canvas", { class: "hq-canvas", width: W, height: H, role: "img", "aria-label": "The team at work in the HQ" });
    g = canvas.getContext("2d");
    panel = h("aside", { class: "hq-panel card", "aria-live": "polite" });
    feed = h("ol", { class: "hq-feed", "aria-label": "Newest steps" });
    plansBox = h("div", { class: "hq-plan-list" });
    const planInput = h("input", {
      type: "text",
      name: "goal",
      maxlength: "4000",
      placeholder: "A job for the whole team, e.g. research and build a site for Joe's Bakery",
      "aria-label": "Job for a team plan",
    });
    const planStatus = h("p", { class: "muted small", role: "status" });
    const planForm = h(
      "form",
      {
        class: "hq-plan-form",
        onsubmit: async (event) => {
          event.preventDefault();
          const goal = planInput.value.trim();
          if (!goal) return;
          planStatus.textContent = "Planning…";
          try {
            await ctx.api("/studio/api/plans", { method: "POST", body: JSON.stringify({ goal }) });
            planInput.value = "";
            planStatus.textContent = "";
            await refresh();
          } catch (error) {
            planStatus.textContent = (error && error.message) || "That plan could not start.";
          }
        },
      },
      [planInput, h("button", { class: "button", type: "submit", text: "Plan it" })]
    );
    tip = h("div", { class: "hq-tip", hidden: true });
    const stage = h("div", { class: "hq-stage" }, [canvas, tip]);
    ctx.view.replaceChildren(
      h("div", { class: "hq" }, [
        h("div", { class: "hq-main" }, [
          h("div", { class: "hq-head" }, [
            h("div", {}, [
              h("h2", { text: "HQ" }),
              h("p", { class: "muted small", text: "Your whole team at work. Click an agent to see what it's doing and talk to it; click a station to see what's waiting there." }),
            ]),
            h("div", { class: "hq-legend", "aria-hidden": "true" }, [h("span", { class: "dot busy" }), "working", h("span", { class: "dot idle" }), "free"]),
          ]),
          stage,
          h("section", { class: "hq-plans", "aria-label": "Team plans" }, [
            h("h3", { class: "hq-feed-title", text: "Team plans" }),
            planForm,
            planStatus,
            plansBox,
          ]),
          h("h3", { class: "hq-feed-title", text: "Newest steps" }),
          feed,
        ]),
        panel,
      ])
    );
    drawBackdrop();
    canvas.addEventListener("click", (event) => choose(hit(event)));
    canvas.addEventListener("mousemove", (event) => hover(event));
    canvas.addEventListener("mouseleave", () => {
      state.hover = null;
      tip.hidden = true;
    });
    await refresh();
    drawPanel();
    cancelAnimationFrame(frame);
    last = 0;
    frame = requestAnimationFrame(draw);
    clearInterval(poller);
    poller = setInterval(() => {
      if (!ctx.alive() || !canvas.isConnected) {
        clearInterval(poller);
        return;
      }
      if (!document.hidden) refresh().then(drawPanelLive);
    }, POLL_MS);
  }

  async function refresh() {
    try {
      const data = await ctx.api("/studio/api/hq");
      if (!ctx.alive()) return;
      sync(data);
      drawFeed();
      drawPlans();
      if (state.selected && state.selected.kind === "agent") {
        state.activity = await ctx.api(`/studio/api/agents/${state.selected.id}/activity`).catch(() => null);
      }
    } catch {
      /* the next poll tries again */
    }
  }

  function point(event) {
    const box = canvas.getBoundingClientRect();
    return { x: ((event.clientX - box.left) / box.width) * W, y: ((event.clientY - box.top) / box.height) * H };
  }

  function hit(event) {
    const at = point(event);
    const sprites = [...state.agents.values()].sort((a, b) => b.y - a.y);
    for (const sprite of sprites) {
      if (Math.abs(at.x - sprite.x) <= 8 && at.y >= sprite.y - 22 && at.y <= sprite.y + 8) return { kind: "agent", id: sprite.id };
    }
    for (const [id, box] of Object.entries(LAYOUT)) {
      if (at.x >= box.x - 3 && at.x <= box.x + box.w + 3 && at.y >= box.row.top - 11 && at.y <= box.row.bottom + 4) return { kind: "station", id };
    }
    return null;
  }

  function hover(event) {
    state.hover = hit(event);
    canvas.style.cursor = state.hover ? "pointer" : "default";
    if (!state.hover) {
      tip.hidden = true;
      return;
    }
    const words = state.hover.kind === "agent"
      ? describe((state.agents.get(state.hover.id) || {}).info)
      : (state.data.stations.find((s) => s.id === state.hover.id) || {}).name;
    tip.textContent = words || "";
    const box = canvas.getBoundingClientRect();
    tip.style.left = `${event.clientX - box.left + 12}px`;
    tip.style.top = `${event.clientY - box.top + 12}px`;
    tip.hidden = !words;
  }

  function describe(info) {
    if (!info) return "";
    const station = (state.data.stations.find((s) => s.id === info.station) || {}).name || "";
    return `${info.name}: ${info.busy ? `working in the ${station.toLowerCase()}` : "free"}${info.tool ? ` (${info.tool.replace(/_/g, " ")})` : ""}`;
  }

  async function choose(target) {
    state.selected = target;
    state.activity = null;
    drawPanel();
    if (target && target.kind === "agent") {
      state.activity = await ctx.api(`/studio/api/agents/${target.id}/activity`).catch(() => null);
      drawPanel();
    }
  }

  function drawFeed() {
    const items = (state.data && state.data.feed) || [];
    feed.replaceChildren(
      ...(items.length
        ? items.map((item) =>
            ctx.el("li", { class: item.failed ? "failed" : "" }, [
              ctx.el("button", { class: "link-button", type: "button", text: item.agent, onclick: () => choose({ kind: "agent", id: item.agent_id }) }),
              ctx.el("span", { class: "hq-tool", text: (item.tool || "").replace(/_/g, " ") }),
              ctx.el("span", { class: "muted", text: item.text }),
            ])
          )
        : [ctx.el("li", { class: "muted", text: "Nobody has done anything yet. Ask Jarvis for something and watch the team go." })])
    );
  }

  // Team plans: each step, who does it, and how far it got.
  function drawPlans() {
    const plans = (state.data && state.data.plans) || [];
    const h = ctx.el;
    plansBox.replaceChildren(
      ...(plans.length
        ? plans.map((plan) => {
            const act = async (verb) => {
              await ctx.api(`/studio/api/plans/${plan.id}/${verb}`, { method: "POST" }).catch(() => null);
              await refresh();
            };
            const button =
              plan.status === "running"
                ? h("button", { class: "link-button", type: "button", text: "Stop", onclick: () => act("stop") })
                : plan.status === "done"
                  ? null
                  : h("button", { class: "link-button", type: "button", text: "Resume", onclick: () => act("resume") });
            return h("article", { class: `hq-plan ${plan.status}`, "data-plan": plan.id }, [
              h("div", { class: "hq-plan-head" }, [
                h("strong", { text: plan.goal }),
                h("span", { class: "hq-plan-state", text: `${plan.status} · ${plan.done_steps} of ${plan.steps.length}` }),
                button,
              ].filter(Boolean)),
              h(
                "ol",
                { class: "hq-plan-steps" },
                plan.steps.map((step) =>
                  h("li", { class: `step ${step.status}`, title: step.result || step.do }, [
                    h("span", { class: "hq-tool", text: step.id }),
                    h("span", { class: "who", text: step.agent }),
                    h("span", { class: "muted", text: step.do }),
                    h("span", { class: "hq-step-state", text: step.status }),
                  ])
                )
              ),
            ]);
          })
        : [h("p", { class: "muted small", text: "No team plans yet. Give the team a bigger job above, or tell Jarvis \"get the team to …\"." })])
    );
  }

  // Only the parts that change, so a half-typed message survives the poll.
  function drawPanelLive() {
    if (!state.selected) {
      drawPanel();
      return;
    }
    const status = panel.querySelector("[data-live]");
    if (status && state.selected.kind === "agent") {
      const info = (state.agents.get(state.selected.id) || {}).info;
      if (info) status.textContent = describe(info);
      const list = panel.querySelector(".hq-steps");
      if (list) list.replaceChildren(...steps());
      return;
    }
    if (state.selected.kind === "station" && !panel.contains(document.activeElement)) drawPanel();
  }

  function steps() {
    const messages = ((state.activity && state.activity.messages) || []).slice(-8).reverse();
    if (!messages.length) return [ctx.el("li", { class: "muted", text: "Nothing yet." })];
    return messages.map((message) =>
      ctx.el("li", { class: message.failed ? "failed" : "" }, [
        ctx.el("strong", { text: message.role === "tool" ? (message.tool || "tool").replace(/_/g, " ") : message.role === "user" ? "Asked" : message.author || message.role }),
        ctx.el("span", { text: ` ${String(message.text || "").slice(0, 220)}` }),
      ])
    );
  }

  function drawPanel() {
    const h = ctx.el;
    const data = state.data || { agents: [], stations: [] };
    if (!state.selected) {
      panel.replaceChildren(
        h("h3", { text: "The team" }),
        h("ul", { class: "hq-team" }, data.agents.map((info) => {
          const sprite = state.agents.get(info.id) || {};
          return h("li", {}, [
            h("button", { class: "hq-person", type: "button", onclick: () => choose({ kind: "agent", id: info.id }) }, [
              h("span", { class: `hq-swatch ${info.busy ? "busy" : ""}`, style: `background:${sprite.shirt || "#888"}` }),
              h("strong", { text: info.name }),
              h("small", { class: "muted", text: info.busy ? (data.stations.find((s) => s.id === info.station) || {}).name || "working" : "free" }),
            ]),
          ]);
        }))
      );
      return;
    }
    if (state.selected.kind === "agent") {
      const info = (state.agents.get(state.selected.id) || {}).info;
      if (!info) {
        state.selected = null;
        drawPanel();
        return;
      }
      const box = h("textarea", { rows: 2, placeholder: `Tell ${info.name} something…`, "aria-label": `Message for ${info.name}` });
      const send = async (event) => {
        event.preventDefault();
        const words = box.value.trim();
        if (!words) return;
        try {
          await ctx.post(`/studio/api/hq/agents/${info.id}/say`, { text: words });
          box.value = "";
          ctx.notify(`Sent to ${info.name}. Watch them work.`);
        } catch (error) {
          ctx.notify(error.message);
        }
      };
      panel.replaceChildren(...[
        h("button", { class: "ghost-button small", type: "button", text: "‹ Team", onclick: () => choose(null) }),
        h("h3", { text: info.name }),
        h("p", { class: "muted small", text: `${info.role}${info.main ? " (your main AI)" : ""} · ${info.local ? "on this PC" : "on a server"}: ${info.model}` }),
        h("p", { class: "hq-status", "data-live": "1", text: describe(info) }),
        info.task ? h("p", { class: "small", text: `Task: ${info.task}` }) : null,
        h("form", { class: "hq-say", onsubmit: send }, [
          box,
          h("div", { class: "row" }, [
            h("button", { class: "primary small", type: "submit", text: "Send" }),
            info.main
              ? null
              : h("button", {
                  class: "ghost-button small",
                  type: "button",
                  text: "Stop",
                  onclick: async () => {
                    const result = await ctx.post(`/studio/api/hq/agents/${info.id}/stop`, {}).catch((error) => ctx.notify(error.message));
                    if (result) ctx.notify(result.stopped ? `Stopped ${info.name}'s task.` : `${info.name} had no task running.`);
                  },
                }),
            h("button", { class: "ghost-button small", type: "button", text: "Open", onclick: () => ctx.go(info.main ? "home" : `agent/${info.id}`) }),
          ].filter(Boolean)),
        ]),
        h("h4", { text: "What it did" }),
        h("ol", { class: "hq-steps" }, steps()),
      ].filter(Boolean));
      return;
    }
    const station = data.stations.find((s) => s.id === state.selected.id) || { name: "", what: "" };
    const here = data.agents.filter((info) => info.station === station.id);
    const nodes = [
      h("button", { class: "ghost-button small", type: "button", text: "‹ Team", onclick: () => choose(null) }),
      h("h3", { text: station.name }),
      h("p", { class: "muted small", text: station.what }),
      station.note ? h("p", { class: "small", text: station.note }) : null,
      h("h4", { text: here.length ? "Here now" : "Nobody here right now" }),
      h("ul", { class: "hq-team" }, here.map((info) => h("li", {}, [h("button", { class: "hq-person", type: "button", onclick: () => choose({ kind: "agent", id: info.id }) }, [h("strong", { text: info.name }), h("small", { class: "muted", text: info.tool ? info.tool.replace(/_/g, " ") : info.busy ? "working" : "free" })])]))),
    ];
    if (station.id === "approvals") {
      const pending = data.pending || [];
      nodes.push(
        h("h4", { text: pending.length ? "Waiting for your yes" : "Nothing waiting" }),
        ...pending.map((item) =>
          h("div", { class: "hq-approval" }, [
            h("code", { text: item.command || "" }),
            h("small", { class: "muted", text: `from ${(data.agents.find((info) => info.id === item.agent_id) || {}).name || "an agent"}` }),
            h("div", { class: "row" }, [
              h("button", { class: "primary small", type: "button", text: "Allow", onclick: () => decide(item.id, true) }),
              h("button", { class: "ghost-button small", type: "button", text: "Refuse", onclick: () => decide(item.id, false) }),
            ]),
          ])
        )
      );
    }
    if (station.route) nodes.push(h("button", { class: "ghost-button", type: "button", text: `Open ${station.name}`, onclick: () => ctx.go(station.route) }));
    panel.replaceChildren(...nodes.filter(Boolean));
  }

  async function decide(id, yes) {
    try {
      await ctx.post(`/studio/api/commands/${id}/${yes ? "approve" : "deny"}`, {});
      ctx.notify(yes ? "Allowed." : "Refused; the agent carries on without it.");
      await refresh();
      drawPanel();
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  window.FCCHQ = { render, state, spot, route };
})();
