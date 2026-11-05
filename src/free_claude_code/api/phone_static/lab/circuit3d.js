// The Electronics room's bench in 3D, in real sizes (1 unit = 1 cm): a
// breadboard on an anti-static mat, the power source, and every part from
// the parts bin as a model (resistors with their real colour bands, LEDs that
// light, motors that spin, boards with blinking LEDs), joined by wires along
// which the current visibly flows. The bench reads the circuit result from
// science.js (the PC Lab's rules), so what you see is what the maths says.
import { THREE, mesh, block, post, standard, metal, glow, canvasTexture, boardTexture, label, glowSprite, tube, dispose, pickable, puffTexture } from "./look3d.js";
import { resistorBands, findPart } from "./science.js";
import { paintMonitor } from "./board.js";

const BOARD_W = 16.5;
const BOARD_D = 5.5;
const TOP = 0.85;
const RAIL_PLUS = -2.45;
const RAIL_MINUS = -2.1;
const MAX_COPIES = 4;
const LED_COLOURS = { "led-red": "#ff2d2d", "led-green": "#36ff5c", "led-blue": "#2f6bff", "led-white": "#eef4ff", "led-power": "#fff1c2", bulb: "#ffcf7a" };
const OFF_BOARD = new Set(["motor", "fan", "servo", "pump", "vibration", "speaker", "bulb", "raspberry-pi", "wheels", "chassis", "case", "motor-driver", "led-strip", "led-power", "soil-sensor", "wire", "solar", "relay"]);
const LEVEL = { on: 1, weak: 0.65, dim: 0.25, idle: 0.12, ok: 1, off: 0, burnt: 0 };

function breadboardTexture() {
  return canvasTexture(1024, 342, (paint, w, h) => {
    paint.fillStyle = "#f4f2ec";
    paint.fillRect(0, 0, w, h);
    const sx = w / BOARD_W;
    const sz = h / BOARD_D;
    const hole = (x, z) => {
      paint.fillStyle = "#3b3b3b";
      paint.fillRect(x * sx - 3, z * sz - 3, 6, 6);
    };
    // Power rails along both long edges: red (+) and blue (-) lines.
    for (const [z, colour] of [[0.25, "#d32f2f"], [0.75, "#1e5bd6"], [BOARD_D - 0.75, "#d32f2f"], [BOARD_D - 0.25, "#1e5bd6"]]) {
      paint.strokeStyle = colour;
      paint.lineWidth = 3;
      paint.beginPath();
      paint.moveTo(0.4 * sx, (z + (z < 1 ? -0.13 : 0.13)) * sz);
      paint.lineTo((BOARD_W - 0.4) * sx, (z + (z < 1 ? -0.13 : 0.13)) * sz);
      paint.stroke();
    }
    for (let column = 0; column < 60; column += 1) {
      const x = 0.9 + column * 0.254;
      if (column % 6 !== 5) for (const z of [0.4, 0.62, BOARD_D - 0.62, BOARD_D - 0.4]) hole(x, z);
      for (let row = 0; row < 5; row += 1) {
        hole(x, 1.25 + row * 0.254);
        hole(x, BOARD_D - 1.25 - row * 0.254);
      }
    }
    paint.fillStyle = "#d9d6cd";
    paint.fillRect(0, (BOARD_D / 2 - 0.12) * sz, w, 0.24 * sz);
    paint.fillStyle = "#8a8a8a";
    paint.font = "14px sans-serif";
    for (let column = 0; column < 60; column += 5) paint.fillText(String(column + 1), (0.82 + column * 0.254) * sx, 1.05 * sz);
  });
}

function matTexture() {
  return canvasTexture(256, 256, (paint, w, h) => {
    paint.fillStyle = "#1f4a3f";
    paint.fillRect(0, 0, w, h);
    paint.strokeStyle = "rgba(255,255,255,0.08)";
    paint.lineWidth = 1;
    for (let i = 0; i <= 8; i += 1) {
      paint.beginPath();
      paint.moveTo((i * w) / 8, 0);
      paint.lineTo((i * w) / 8, h);
      paint.moveTo(0, (i * h) / 8);
      paint.lineTo(w, (i * h) / 8);
      paint.stroke();
    }
  }, { repeat: [5, 3] });
}

function legs(group, material, points, top, bottom = 0) {
  for (const [x, z] of points) group.add(mesh(new THREE.CylinderGeometry(0.025, 0.025, top - bottom, 6), material, x, bottom + (top - bottom) / 2, z));
}

/** The models: each returns {root, plus, minus, tick} in its own frame. */
function makers(m) {
  const leadMetal = m.lead;
  const cellRow = (count, radius, length, wrap) => {
    const shown = Math.min(count, 6);
    const width = shown * radius * 2.2 + 0.5;
    const root = new THREE.Group();
    root.add(block(width, radius * 1.4, length + 1.2, m.black, 0, 0, 0));
    for (let i = 0; i < shown; i += 1) {
      const x = -width / 2 + 0.25 + radius * 1.1 + i * radius * 2.2;
      const cell = mesh(new THREE.CylinderGeometry(radius, radius, length, 24), wrap, x, radius * 1.15, 0);
      cell.rotation.x = Math.PI / 2;
      root.add(cell);
      const cap = mesh(new THREE.CylinderGeometry(radius * 0.35, radius * 0.35, 0.2, 12), m.tin, x, radius * 1.15, -length / 2 - 0.1);
      cap.rotation.x = Math.PI / 2;
      root.add(cap);
    }
    return { root, plus: new THREE.Vector3(width / 2 - 0.3, radius * 1.4, -length / 2 - 0.6), minus: new THREE.Vector3(-width / 2 + 0.3, radius * 1.4, -length / 2 - 0.6) };
  };
  const pcb = (w, d, colour, text, y = 0) => {
    const face = boardTexture(colour, text);
    const plain = standard(colour, 0.5);
    return mesh(new THREE.BoxGeometry(w, 0.16, d), [plain, plain, new THREE.MeshStandardMaterial({ map: face, roughness: 0.5 }), plain, plain, plain], 0, y + 0.08, 0);
  };
  const smallLed = (colour, x, y, z) => {
    const led = mesh(new THREE.BoxGeometry(0.18, 0.08, 0.1), glow(colour, 0), x, y, z);
    led.userData.ledColour = colour;
    return led;
  };
  const header = (length, x, y, z, alongX = true) => block(alongX ? length : 0.25, 0.25, alongX ? 0.25 : length, m.black, x, y, z);
  const chip = (w, d, x, y, z, text = "") => {
    const face = text ? canvasTexture(128, 128, (paint) => {
      paint.fillStyle = "#151515";
      paint.fillRect(0, 0, 128, 128);
      paint.fillStyle = "rgba(220,220,220,0.75)";
      paint.font = "bold 20px sans-serif";
      paint.textAlign = "center";
      paint.fillText(text, 64, 70);
    }) : null;
    const body = standard("#151515", 0.45);
    const top = face ? new THREE.MeshStandardMaterial({ map: face, roughness: 0.45 }) : body;
    return mesh(new THREE.BoxGeometry(w, 0.12, d), [body, body, top, body, body, body], x, y + 0.06, z);
  };
  const boardLeds = (root, items) => {
    const lights = items.map(([colour, x, y, z, blink]) => {
      const led = smallLed(colour, x, y, z);
      led.userData.blink = blink;
      root.add(led);
      return led;
    });
    return (t, level) => {
      for (const led of lights) led.material.emissiveIntensity = level > 0 ? (led.userData.blink ? (Math.sin(t * 6) > 0 ? 2.5 : 0.1) : 2.2) : 0;
    };
  };
  const spinner = (object, axis, speed) => (t, dt, level) => {
    object.rotation[axis] += dt * speed * level;
  };
  const led = (id) => () => {
    const colour = LED_COLOURS[id];
    const root = new THREE.Group();
    legs(root, leadMetal, [[-0.13, 0], [0.13, 0]], 0.55);
    const lens = new THREE.MeshPhysicalMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.05, transparent: true, opacity: 0.82, roughness: 0.15, clearcoat: 1 });
    root.add(mesh(new THREE.CylinderGeometry(0.29, 0.29, 0.1, 20), lens, 0, 0.6, 0));
    root.add(mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.45, 20), lens, 0, 0.87, 0));
    root.add(mesh(new THREE.SphereGeometry(0.25, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), lens, 0, 1.095, 0));
    const halo = glowSprite(colour, 2.4);
    halo.position.set(0, 1.0, 0);
    root.add(halo);
    return {
      root,
      plus: new THREE.Vector3(-0.13, 0, -0.1),
      minus: new THREE.Vector3(0.13, 0, 0.1),
      tick: (t, dt, level, state) => {
        lens.emissiveIntensity = state === "burnt" ? 0 : 0.05 + level * 3.2;
        if (state === "burnt") lens.color.set("#3a3330");
        halo.material.opacity = level;
        halo.scale.setScalar(1.6 + level * 2.4);
      },
    };
  };
  return {
    aa: (count) => cellRow(count, 0.72, 5.0, standard("#1d3557", 0.35, 0.2)),
    "aa-nimh": (count) => cellRow(count, 0.72, 5.0, standard("#2e7d32", 0.35, 0.2)),
    18650: (count) => cellRow(count, 0.92, 6.5, standard("#0f6d8c", 0.3, 0.2)),
    "9v": () => {
      const root = new THREE.Group();
      root.add(block(2.6, 1.75, 4.8, standard("#2b2b2b", 0.4), 0, 0, 0));
      root.add(block(2.62, 1.77, 1.6, standard("#c8a227", 0.35, 0.3), 0, 0, 0.8));
      root.add(post(0.3, 0.3, m.tin, 0.6, 1.75, -1.9, 12));
      root.add(post(0.34, 0.3, m.tin, -0.6, 1.75, -1.9, 6));
      return { root, plus: new THREE.Vector3(0.6, 2.05, -1.9), minus: new THREE.Vector3(-0.6, 2.05, -1.9) };
    },
    cr2032: () => {
      const root = new THREE.Group();
      root.add(post(1.3, 0.5, m.black, 0, 0, 0, 28));
      root.add(post(1.0, 0.32, metal("#d9dde2", 0.25), 0, 0.5, 0, 28));
      return { root, plus: new THREE.Vector3(0.9, 0.6, -0.9), minus: new THREE.Vector3(-0.9, 0.4, -0.9) };
    },
    lipo: () => {
      const root = new THREE.Group();
      root.add(block(3.4, 0.6, 5.0, metal("#b9bec4", 0.45), 0, 0, 0));
      root.add(block(3.42, 0.62, 0.8, standard("#e5b800", 0.5), 0, 0, -2.0));
      root.add(block(0.8, 0.4, 0.5, standard("#f2f2f2", 0.5), 0, 0.1, -2.9));
      return { root, plus: new THREE.Vector3(0.2, 0.4, -3.1), minus: new THREE.Vector3(-0.2, 0.4, -3.1) };
    },
    usb: () => {
      const root = new THREE.Group();
      root.add(block(3.6, 2.4, 3.6, standard("#f5f5f5", 0.35), 0, 0, 0));
      root.add(block(1.0, 0.4, 0.1, metal(), 0, 1.0, -1.85));
      root.add(post(0.25, 0.35, standard("#22c55e", 0.4, 0, { emissive: "#22c55e", emissiveIntensity: 1 }), 1.3, 2.4, 1.3, 10));
      return { root, plus: new THREE.Vector3(0.3, 1.2, -1.9), minus: new THREE.Vector3(-0.3, 1.2, -1.9) };
    },
    solar: () => {
      const root = new THREE.Group();
      const cells = canvasTexture(256, 160, (paint, w, h) => {
        paint.fillStyle = "#0b1f4a";
        paint.fillRect(0, 0, w, h);
        for (let x = 0; x < 6; x += 1) for (let y = 0; y < 4; y += 1) {
          paint.fillStyle = "#13306e";
          paint.fillRect(4 + x * 42, 4 + y * 39, 38, 35);
          paint.strokeStyle = "rgba(210,220,235,0.6)";
          paint.beginPath();
          paint.moveTo(4 + x * 42 + 19, 4 + y * 39);
          paint.lineTo(4 + x * 42 + 19, 39 + y * 39);
          paint.stroke();
        }
      });
      const panel = mesh(new THREE.BoxGeometry(11, 0.3, 6.6), [metal(), metal(), new THREE.MeshStandardMaterial({ map: cells, roughness: 0.2, metalness: 0.3 }), metal(), metal(), metal()], 0, 2.2, 0);
      panel.rotation.x = -0.45;
      root.add(panel);
      root.add(block(0.4, 2.2, 0.4, metal(), -4.5, 0, 1.5));
      root.add(block(0.4, 2.2, 0.4, metal(), 4.5, 0, 1.5));
      return { root, plus: new THREE.Vector3(0.4, 1.0, -2.6), minus: new THREE.Vector3(-0.4, 1.0, -2.6) };
    },
    "led-red": led("led-red"),
    "led-green": led("led-green"),
    "led-blue": led("led-blue"),
    "led-white": led("led-white"),
    "led-power": () => {
      const root = new THREE.Group();
      root.add(post(1.0, 0.15, metal("#d0d4d9"), 0, 0, 0, 6));
      const emitter = mesh(new THREE.BoxGeometry(0.5, 0.12, 0.5), glow("#ffe7a0", 0), 0, 0.2, 0);
      root.add(emitter);
      const halo = glowSprite("#fff6dc", 4);
      halo.position.y = 0.6;
      root.add(halo);
      return { root, plus: new THREE.Vector3(-0.7, 0.15, 0), minus: new THREE.Vector3(0.7, 0.15, 0), tick: (t, dt, level) => {
        emitter.material.emissiveIntensity = level * 5;
        halo.material.opacity = level;
        halo.scale.setScalar(2 + level * 5);
      } };
    },
    "led-strip": () => {
      const root = new THREE.Group();
      root.add(block(14, 0.06, 1.0, standard("#f2f2f2", 0.6), 0, 0, 0));
      const chips = [];
      for (let i = 0; i < 12; i += 1) {
        const item = mesh(new THREE.BoxGeometry(0.5, 0.14, 0.5), glow("#ffffff", 0), -6.3 + i * 1.15, 0.12, 0);
        chips.push(item);
        root.add(item);
      }
      return { root, plus: new THREE.Vector3(-7, 0.1, -0.3), minus: new THREE.Vector3(-7, 0.1, 0.3), tick: (t, dt, level, state) => {
        chips.forEach((item, i) => {
          item.material.emissive.setHSL((t * 0.15 + i / 12) % 1, 1, 0.5);
          item.material.color.copy(item.material.emissive);
          item.material.emissiveIntensity = state === "on" ? level * 2.5 : 0;
        });
      } };
    },
    bulb: () => {
      const root = new THREE.Group();
      root.add(post(0.32, 0.6, metal("#c0a060", 0.35), 0, 0, 0, 16));
      const glass = new THREE.MeshPhysicalMaterial({ color: "#ffffff", transparent: true, opacity: 0.25, roughness: 0.05, clearcoat: 1 });
      root.add(mesh(new THREE.SphereGeometry(0.55, 20, 14), glass, 0, 1.05, 0));
      const filament = mesh(new THREE.TorusGeometry(0.15, 0.025, 6, 16), glow("#ffb04a", 0), 0, 1.05, 0);
      root.add(filament);
      const halo = glowSprite("#ffcf7a", 3);
      halo.position.y = 1.05;
      root.add(halo);
      return { root, plus: new THREE.Vector3(-0.3, 0.1, 0), minus: new THREE.Vector3(0.3, 0.1, 0), tick: (t, dt, level) => {
        filament.material.emissiveIntensity = level * 6;
        halo.material.opacity = level;
        halo.scale.setScalar(1.5 + level * 4);
      } };
    },
    motor: () => {
      const root = new THREE.Group();
      const can = mesh(new THREE.CylinderGeometry(1.0, 1.0, 2.6, 24), metal("#c9ccd1", 0.25), 0, 1.0, 0);
      can.rotation.z = Math.PI / 2;
      root.add(can);
      const cap = mesh(new THREE.CylinderGeometry(0.95, 0.95, 0.4, 24), standard("#f5f5f5", 0.5), -1.5, 1.0, 0);
      cap.rotation.z = Math.PI / 2;
      root.add(cap);
      const shaft = mesh(new THREE.CylinderGeometry(0.1, 0.1, 1.0, 8), metal(), 1.75, 1.0, 0);
      shaft.rotation.z = Math.PI / 2;
      root.add(shaft);
      const propeller = new THREE.Group();
      propeller.position.set(2.2, 1.0, 0);
      propeller.add(block(0.1, 3.2, 0.5, standard("#e53935", 0.5), 0, -1.6, 0));
      root.add(propeller);
      return { root, plus: new THREE.Vector3(-1.75, 1.3, -0.3), minus: new THREE.Vector3(-1.75, 0.7, -0.3), tick: spinner(propeller, "x", 28) };
    },
    fan: () => {
      const root = new THREE.Group();
      const frame = standard("#1d1d1f", 0.5);
      for (const [x, y, w, h] of [[0, 0, 4, 0.3], [0, 3.7, 4, 0.3], [-1.85, 0, 0.3, 4], [1.85, 0, 0.3, 4]]) root.add(block(w, h, 1.0, frame, x, y, 0));
      const blades = new THREE.Group();
      blades.position.set(0, 2.0, 0);
      blades.add(post(0.6, 0.9, frame, 0, -0.45, 0, 20).rotateX(Math.PI / 2));
      for (let i = 0; i < 7; i += 1) {
        const blade = block(0.55, 1.4, 0.08, standard("#2a2a2c", 0.45), 0, 0.5, 0);
        const holder = new THREE.Group();
        holder.rotation.z = (i / 7) * Math.PI * 2;
        blade.rotation.y = 0.5;
        holder.add(blade);
        blades.add(holder);
      }
      root.add(blades);
      return { root, plus: new THREE.Vector3(1.8, 0.2, -0.5), minus: new THREE.Vector3(1.8, 0.4, -0.5), tick: spinner(blades, "z", 22) };
    },
    servo: () => {
      const root = new THREE.Group();
      root.add(block(2.3, 2.2, 1.2, standard("#1e63c7", 0.45), 0, 0, 0));
      root.add(block(3.2, 0.15, 1.2, standard("#1e63c7", 0.45), 0, 1.6, 0));
      const horn = new THREE.Group();
      horn.position.set(0.55, 2.3, 0);
      horn.add(post(0.3, 0.3, standard("#f5f5f5", 0.4), 0, 0, 0, 14));
      horn.add(block(2.0, 0.12, 0.3, standard("#f5f5f5", 0.4), 0.7, 0.18, 0));
      root.add(horn);
      return { root, plus: new THREE.Vector3(-1.15, 0.6, -0.2), minus: new THREE.Vector3(-1.15, 0.4, 0.2), tick: (t, dt, level, state, run) => {
        if (run && run.angle !== undefined) horn.rotation.y += ((((run.angle - 90) * Math.PI) / 180) - horn.rotation.y) * Math.min(1, dt * 8);
        else horn.rotation.y = state === "on" ? Math.sin(t * 1.6) * 1.1 : horn.rotation.y;
      } };
    },
    pump: () => {
      const root = new THREE.Group();
      const body = post(1.2, 3.0, standard("#202024", 0.45), 0, 0, 0, 22);
      root.add(body);
      const [pipe] = tube([[0, 3.0, 0], [0, 4.0, 0], [1.5, 4.4, 0], [3, 3.8, 0]], 0.25, new THREE.MeshPhysicalMaterial({ color: "#dff3ff", transparent: true, opacity: 0.5, roughness: 0.1 }));
      root.add(pipe);
      return { root, plus: new THREE.Vector3(-1.2, 0.5, -0.2), minus: new THREE.Vector3(-1.2, 0.3, 0.2), tick: (t, dt, level) => {
        body.position.x = level ? Math.sin(t * 90) * 0.03 * level : 0;
      } };
    },
    vibration: () => {
      const root = new THREE.Group();
      const disc = post(0.5, 0.27, metal("#c9ccd1", 0.25), 0, 0, 0, 20);
      root.add(disc);
      return { root, plus: new THREE.Vector3(-0.5, 0.15, -0.1), minus: new THREE.Vector3(-0.5, 0.15, 0.1), tick: (t, dt, level) => {
        disc.position.x = level ? Math.sin(t * 120) * 0.06 * level : 0;
      } };
    },
    buzzer: () => {
      const root = new THREE.Group();
      root.add(post(0.6, 0.95, standard("#141414", 0.5), 0, 0, 0, 24));
      root.add(post(0.1, 0.02, standard("#555", 0.5), 0, 0.95, 0, 10));
      const rings = [0, 1, 2].map(() => {
        const ring = mesh(new THREE.TorusGeometry(1, 0.03, 6, 32), new THREE.MeshBasicMaterial({ color: "#7fe3ff", transparent: true, opacity: 0 }), 0, 1.1, 0);
        ring.rotation.x = Math.PI / 2;
        root.add(ring);
        return ring;
      });
      return { root, plus: new THREE.Vector3(-0.3, 0, -0.3), minus: new THREE.Vector3(0.3, 0, -0.3), tick: (t, dt, level) => {
        rings.forEach((ring, i) => {
          const phase = (t * 0.9 + i / 3) % 1;
          ring.scale.setScalar(0.6 + phase * 2.4);
          ring.material.opacity = level ? (1 - phase) * 0.7 * level : 0;
        });
      } };
    },
    speaker: () => {
      const root = new THREE.Group();
      root.add(post(2.0, 0.5, metal("#9aa0a6", 0.35), 0, 0, 0, 28));
      const cone = mesh(new THREE.CylinderGeometry(1.8, 0.6, 0.6, 28, 1, true), standard("#1b1b1b", 0.8, 0, { side: THREE.DoubleSide }), 0, 0.75, 0);
      root.add(cone);
      root.add(post(0.55, 0.15, standard("#2a2a2a", 0.4), 0, 0.5, 0, 20));
      return { root, plus: new THREE.Vector3(-1.9, 0.25, -0.3), minus: new THREE.Vector3(-1.9, 0.25, 0.3), tick: (t, dt, level) => {
        cone.scale.y = 1 + (level ? Math.sin(t * 40) * 0.15 * level : 0);
      } };
    },
    arduino: () => {
      const root = new THREE.Group();
      root.add(header(4.0, 0, 0, -0.75));
      root.add(header(4.0, 0, 0, 0.75));
      root.add(pcb(4.3, 1.8, "#1b4f9c", "NANO", 0.85));
      root.add(chip(0.7, 0.7, 0.2, 1.01, 0, "328P"));
      root.add(block(0.8, 0.4, 0.75, metal(), -2.0, 1.01, 0));
      const tick = boardLeds(root, [["#ff3030", 1.4, 1.05, -0.5, false], ["#ffa000", 1.4, 1.05, 0.5, true]]);
      return { root, plus: new THREE.Vector3(1.9, 0, -0.75), minus: new THREE.Vector3(1.6, 0, -0.75), tick: (t, dt, level) => tick(t, level) };
    },
    esp32: () => {
      const root = new THREE.Group();
      root.add(header(4.8, 0, 0, -1.25));
      root.add(header(4.8, 0, 0, 1.25));
      root.add(pcb(5.2, 2.8, "#161616", "", 0.85));
      const shield = canvasTexture(128, 160, (paint) => {
        paint.fillStyle = "#c7cbd0";
        paint.fillRect(0, 0, 128, 160);
        paint.fillStyle = "#6b7178";
        paint.font = "bold 22px sans-serif";
        paint.fillText("ESP32", 28, 85);
      });
      const can = metal("#c7cbd0", 0.35);
      root.add(mesh(new THREE.BoxGeometry(1.8, 0.3, 2.3), [can, can, new THREE.MeshStandardMaterial({ map: shield, metalness: 0.8, roughness: 0.35 }), can, can, can], 0.9, 1.16, 0));
      root.add(block(0.9, 0.04, 2.3, standard("#c08a2c", 0.4, 0.6), 2.2, 1.01, 0));
      const tick = boardLeds(root, [["#ff3030", -1.8, 1.05, -0.9, false], ["#3a7bff", -1.8, 1.05, 0.9, true]]);
      return { root, plus: new THREE.Vector3(-2.3, 0, -1.25), minus: new THREE.Vector3(-2.0, 0, -1.25), tick: (t, dt, level) => tick(t, level) };
    },
    "raspberry-pi": () => {
      const root = new THREE.Group();
      root.add(pcb(6.5, 3.0, "#1f7a3a", "Pi Zero", 0.3));
      root.add(chip(1.2, 1.2, -0.4, 0.46, 0.2, "SoC"));
      root.add(block(5.1, 0.85, 0.5, m.black, 0, 0.46, -1.2));
      for (let i = 0; i < 20; i += 1) root.add(block(0.06, 0.6, 0.06, m.gold, -2.4 + i * 0.255, 1.31, -1.2));
      root.add(block(1.1, 0.35, 0.6, metal(), -2.6, 0.46, 1.25));
      const tick = boardLeds(root, [["#36ff5c", 2.9, 0.5, 1.1, true]]);
      return { root, plus: new THREE.Vector3(-2.3, 1.3, -1.2), minus: new THREE.Vector3(-2.0, 1.3, -1.2), tick: (t, dt, level) => tick(t, level) };
    },
    "temp-sensor": () => {
      const root = new THREE.Group();
      const grille = canvasTexture(64, 96, (paint) => {
        paint.fillStyle = "#f4f4f2";
        paint.fillRect(0, 0, 64, 96);
        paint.fillStyle = "#9a9a9a";
        for (let y = 8; y < 92; y += 10) for (let x = 8; x < 60; x += 12) paint.fillRect(x, y, 8, 5);
      });
      const white = standard("#f4f4f2", 0.6);
      root.add(mesh(new THREE.BoxGeometry(1.5, 2.5, 0.8), [white, white, white, white, new THREE.MeshStandardMaterial({ map: grille, roughness: 0.6 }), white], 0, 1.65, 0));
      legs(root, leadMetal, [[-0.4, 0], [-0.13, 0], [0.13, 0], [0.4, 0]], 0.4);
      return { root, plus: new THREE.Vector3(-0.4, 0, -0.1), minus: new THREE.Vector3(0.4, 0, -0.1) };
    },
    "light-sensor": () => {
      const root = new THREE.Group();
      legs(root, leadMetal, [[-0.12, 0], [0.12, 0]], 0.6);
      const face = canvasTexture(64, 64, (paint) => {
        paint.fillStyle = "#d9692a";
        paint.fillRect(0, 0, 64, 64);
        paint.strokeStyle = "#f3d9a0";
        paint.lineWidth = 4;
        paint.beginPath();
        for (let i = 0; i < 6; i += 1) paint.lineTo(12 + (i % 2) * 40, 8 + i * 10);
        paint.stroke();
      });
      const side = standard("#d9692a", 0.4);
      const disc = mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.12, 20), [side, new THREE.MeshStandardMaterial({ map: face, roughness: 0.3 }), side], 0, 0.66, 0);
      root.add(disc);
      return { root, plus: new THREE.Vector3(-0.12, 0, -0.1), minus: new THREE.Vector3(0.12, 0, -0.1) };
    },
    "soil-sensor": () => {
      const root = new THREE.Group();
      const prong = standard("#c99a2e", 0.35, 0.7);
      root.add(block(0.5, 0.1, 5.0, prong, -0.6, 0, 0.8));
      root.add(block(0.5, 0.1, 5.0, prong, 0.6, 0, 0.8));
      root.add(pcb(2.0, 1.2, "#1b4f9c", "", 0));
      return { root, plus: new THREE.Vector3(-0.5, 0.2, -0.6), minus: new THREE.Vector3(0.5, 0.2, -0.6) };
    },
    "distance-sensor": () => {
      const root = new THREE.Group();
      const board = pcb(4.5, 2.0, "#1b4f9c", "HC-SR04", 0);
      board.rotation.x = -Math.PI / 2;
      board.position.set(0, 1.4, 0);
      root.add(board);
      const mesh_ = canvasTexture(64, 64, (paint) => {
        paint.fillStyle = "#c9ccd1";
        paint.fillRect(0, 0, 64, 64);
        paint.strokeStyle = "#7b8189";
        for (let i = 0; i < 64; i += 5) {
          paint.beginPath();
          paint.moveTo(i, 0);
          paint.lineTo(0, i);
          paint.stroke();
        }
      });
      for (const x of [-1.25, 1.25]) {
        const eye = mesh(new THREE.CylinderGeometry(0.8, 0.8, 1.2, 24), [metal(), new THREE.MeshStandardMaterial({ map: mesh_, metalness: 0.6, roughness: 0.4 }), metal()], x, 1.4, 0.65);
        eye.rotation.x = Math.PI / 2;
        root.add(eye);
      }
      legs(root, leadMetal, [[-0.4, -0.1], [-0.13, -0.1], [0.13, -0.1], [0.4, -0.1]], 0.4);
      return { root, plus: new THREE.Vector3(-0.4, 0, -0.1), minus: new THREE.Vector3(0.4, 0, -0.1) };
    },
    "motion-sensor": () => {
      const root = new THREE.Group();
      root.add(pcb(3.2, 2.4, "#1f7a3a", "", 0.4));
      root.add(mesh(new THREE.IcosahedronGeometry(1.1, 1), standard("#f4f4f2", 0.35, 0, { flatShading: true, transparent: true, opacity: 0.92 }), 0, 1.0, 0));
      legs(root, leadMetal, [[-0.3, -0.9], [0, -0.9], [0.3, -0.9]], 0.4);
      return { root, plus: new THREE.Vector3(-0.3, 0, -0.9), minus: new THREE.Vector3(0.3, 0, -0.9) };
    },
    oled: () => {
      const root = new THREE.Group();
      root.add(header(1.1, 0, 0, -1.2));
      root.add(pcb(2.7, 2.8, "#1b4f9c", "", 0.85));
      const idle = (paint) => {
        paint.fillStyle = "#03080d";
        paint.fillRect(0, 0, 256, 160);
        paint.fillStyle = "#7fe3ff";
        paint.font = "bold 30px monospace";
        paint.fillText("FCC LAB", 52, 50);
        paint.font = "22px monospace";
        paint.fillText("Jarvis: ready", 30, 95);
        paint.fillText("~ ~ ~ ~ ~ ~", 46, 135);
      };
      const screen = canvasTexture(256, 160, idle);
      let shown = "";
      // The program's lines (display.println), up to six, like a 128x64 OLED.
      const write = (lines) => {
        const text = lines ? lines.join("\n") : "";
        if (text === shown) return;
        shown = text;
        const paint = screen.image.getContext("2d");
        if (!lines) idle(paint);
        else {
          paint.fillStyle = "#03080d";
          paint.fillRect(0, 0, 256, 160);
          paint.fillStyle = "#9eefff";
          paint.font = "bold 22px monospace";
          lines.slice(-6).forEach((row, i) => paint.fillText(String(row).slice(0, 18), 8, 24 + i * 25));
        }
        screen.needsUpdate = true;
      };
      const glass = new THREE.MeshStandardMaterial({ color: "#05070a", emissive: "#ffffff", emissiveMap: screen, emissiveIntensity: 0, roughness: 0.15, map: screen });
      const side = standard("#05070a", 0.2);
      root.add(mesh(new THREE.BoxGeometry(2.5, 0.12, 1.9), [side, side, glass, side, side, side], 0, 1.07, 0.2));
      return { root, plus: new THREE.Vector3(-0.3, 0, -1.2), minus: new THREE.Vector3(0.3, 0, -1.2), tick: (t, dt, level, state, run) => {
        write(run && run.lines ? run.lines : null);
        glass.emissiveIntensity = state === "on" ? 1.4 : 0;
        glass.color.set(state === "on" ? "#ffffff" : "#05070a");
      } };
    },
    switch: () => {
      const root = new THREE.Group();
      root.add(block(0.9, 0.5, 0.4, m.black, 0, 0.3, 0));
      root.add(block(0.25, 0.3, 0.2, standard("#f5f5f5", 0.5), 0.15, 0.8, 0));
      legs(root, leadMetal, [[-0.3, 0], [0, 0], [0.3, 0]], 0.3);
      return { root, plus: new THREE.Vector3(-0.3, 0, 0), minus: new THREE.Vector3(0.3, 0, 0) };
    },
    button: () => {
      const root = new THREE.Group();
      root.add(block(0.6, 0.35, 0.6, m.black, 0, 0.1, 0));
      root.add(post(0.18, 0.2, standard("#d32f2f", 0.4), 0, 0.45, 0, 14));
      legs(root, leadMetal, [[-0.25, -0.25], [0.25, -0.25], [-0.25, 0.25], [0.25, 0.25]], 0.1);
      return { root, plus: new THREE.Vector3(-0.25, 0, -0.25), minus: new THREE.Vector3(0.25, 0, -0.25) };
    },
    relay: () => {
      const root = new THREE.Group();
      root.add(pcb(2.6, 5.0, "#1b4f9c", "", 0));
      root.add(block(1.9, 1.5, 1.5, standard("#1e5bd6", 0.3), 0, 0.16, 0.8));
      root.add(block(1.5, 0.9, 0.8, standard("#2fa0e8", 0.4), 0, 0.16, -1.6));
      const tick = boardLeds(root, [["#ff3030", -0.9, 0.22, -0.6, false]]);
      return { root, plus: new THREE.Vector3(-0.8, 0.2, -2.3), minus: new THREE.Vector3(0.8, 0.2, -2.3), tick: (t, dt, level) => tick(t, level) };
    },
    "motor-driver": () => {
      const root = new THREE.Group();
      root.add(pcb(4.3, 4.3, "#b71c1c", "L298N", 0));
      const fins = standard("#151515", 0.4, 0.5);
      for (let i = 0; i < 7; i += 1) root.add(block(0.14, 2.2, 2.0, fins, -1.2 + i * 0.4, 0.16, 0.6));
      for (const z of [-1.7, 1.7]) root.add(block(1.2, 0.9, 0.8, standard("#2fa0e8", 0.4), 1.4, 0.16, z));
      return { root, plus: new THREE.Vector3(1.0, 1.0, -1.7), minus: new THREE.Vector3(1.6, 1.0, -1.7) };
    },
    transistor: () => {
      const root = new THREE.Group();
      legs(root, leadMetal, [[-0.13, 0], [0, 0], [0.13, 0]], 0.5);
      root.add(mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.5, 20, 1, false, 0, Math.PI), standard("#151515", 0.45), 0, 0.75, 0));
      return { root, plus: new THREE.Vector3(-0.13, 0, -0.1), minus: new THREE.Vector3(0.13, 0, -0.1) };
    },
    capacitor: () => {
      const root = new THREE.Group();
      legs(root, leadMetal, [[-0.1, 0], [0.1, 0]], 0.3);
      const sleeve = canvasTexture(128, 64, (paint) => {
        paint.fillStyle = "#1f3f9a";
        paint.fillRect(0, 0, 128, 64);
        paint.fillStyle = "#9db2e0";
        paint.fillRect(0, 0, 20, 64);
      });
      root.add(mesh(new THREE.CylinderGeometry(0.4, 0.4, 1.1, 22), new THREE.MeshStandardMaterial({ map: sleeve, roughness: 0.4 }), 0, 0.85, 0));
      root.add(post(0.38, 0.02, metal(), 0, 1.4, 0, 22));
      return { root, plus: new THREE.Vector3(-0.1, 0, -0.1), minus: new THREE.Vector3(0.1, 0, -0.1) };
    },
    "regulator-3v3": () => {
      const root = new THREE.Group();
      legs(root, leadMetal, [[-0.25, 0], [0, 0], [0.25, 0]], 0.5);
      root.add(block(1.0, 0.9, 0.45, standard("#151515", 0.45), 0, 0.5, 0));
      root.add(block(1.0, 0.7, 0.12, metal("#c9ccd1", 0.3), 0, 1.4, -0.16));
      return { root, plus: new THREE.Vector3(-0.25, 0, -0.1), minus: new THREE.Vector3(0, 0, -0.1) };
    },
    tp4056: () => {
      const root = new THREE.Group();
      root.add(header(1.6, 0, 0, -0.6));
      root.add(pcb(2.6, 1.7, "#1b4f9c", "TP4056", 0.85));
      root.add(block(0.7, 0.3, 0.6, metal(), -1.1, 1.01, 0));
      const tick = boardLeds(root, [["#ff3030", 1.0, 1.05, -0.4, false], ["#3a7bff", 1.0, 1.05, 0.4, false]]);
      return { root, plus: new THREE.Vector3(-0.5, 0, -0.6), minus: new THREE.Vector3(0.5, 0, -0.6), tick: (t, dt, level) => tick(t, level) };
    },
    "boost-5v": () => {
      const root = new THREE.Group();
      root.add(header(1.2, 0, 0, -0.45));
      root.add(pcb(2.2, 1.2, "#1b4f9c", "", 0.85));
      root.add(block(0.6, 0.45, 0.6, standard("#202020", 0.5), 0.3, 1.01, 0));
      root.add(block(0.9, 0.45, 0.8, metal(), -0.7, 1.01, 0));
      return { root, plus: new THREE.Vector3(-0.4, 0, -0.45), minus: new THREE.Vector3(0.4, 0, -0.45) };
    },
    wheels: () => {
      const root = new THREE.Group();
      const spinners = [];
      for (const side of [-1, 1]) {
        root.add(block(2.2, 1.9, 6.5, standard("#f2c200", 0.45), side * 2.2, 0, 0));
        const wheel = new THREE.Group();
        wheel.position.set(side * 4.0, 3.0, 1.5);
        const tyre = mesh(new THREE.TorusGeometry(2.4, 0.6, 12, 28), standard("#1b1b1b", 0.85), 0, 0, 0);
        tyre.rotation.y = Math.PI / 2;
        wheel.add(tyre);
        const hub = mesh(new THREE.CylinderGeometry(1.9, 1.9, 0.6, 6), standard("#f2c200", 0.45), 0, 0, 0);
        hub.rotation.z = Math.PI / 2;
        wheel.add(hub);
        root.add(wheel);
        spinners.push(wheel);
      }
      return { root, plus: new THREE.Vector3(-1.5, 1.9, -3.2), minus: new THREE.Vector3(1.5, 1.9, -3.2), tick: (t, dt, level) => spinners.forEach((wheel) => (wheel.rotation.x += dt * 6 * level)) };
    },
    chassis: () => {
      const root = new THREE.Group();
      root.add(block(14, 0.3, 9, new THREE.MeshPhysicalMaterial({ color: "#ffb36b", transparent: true, opacity: 0.55, roughness: 0.1, clearcoat: 1 }), 0, 0, 0));
      return { root, plus: new THREE.Vector3(-6, 0.3, -4), minus: new THREE.Vector3(-5, 0.3, -4) };
    },
    case: () => {
      const root = new THREE.Group();
      const lines = canvasTexture(64, 64, (paint) => {
        paint.fillStyle = "#cfd3d6";
        paint.fillRect(0, 0, 64, 64);
        paint.strokeStyle = "rgba(0,0,0,0.08)";
        for (let y = 0; y < 64; y += 3) {
          paint.beginPath();
          paint.moveTo(0, y);
          paint.lineTo(64, y);
          paint.stroke();
        }
      }, { repeat: [3, 3] });
      const pla = new THREE.MeshStandardMaterial({ map: lines, roughness: 0.7 });
      root.add(block(6, 0.3, 4, pla, 0, 0, 0));
      for (const [x, z, w, d] of [[0, -1.85, 6, 0.3], [0, 1.85, 6, 0.3], [-2.85, 0, 0.3, 4], [2.85, 0, 0.3, 4]]) root.add(block(w, 3.2, d, pla, x, 0.3, z));
      const lid = block(6, 0.3, 4, pla, 0, 0, 2);
      lid.position.set(0, 3.5, -2.0);
      lid.rotation.x = -1.1;
      root.add(lid);
      return { root, plus: new THREE.Vector3(-2.5, 3.5, -1.85), minus: new THREE.Vector3(-2.0, 3.5, -1.85) };
    },
    wire: () => {
      const root = new THREE.Group();
      root.add(mesh(new THREE.TorusGeometry(1.4, 0.35, 10, 28), standard("#d32f2f", 0.5), 0, 0.35, 0).rotateX(Math.PI / 2));
      root.add(mesh(new THREE.TorusGeometry(1.4, 0.35, 10, 28), standard("#1b1b1b", 0.5), 3.4, 0.35, 0).rotateX(Math.PI / 2));
      return { root, plus: new THREE.Vector3(0, 0.7, -1.4), minus: new THREE.Vector3(3.4, 0.7, -1.4) };
    },
    breadboard: () => {
      const root = new THREE.Group();
      root.add(block(8.2, 0.85, 5.5, standard("#f4f2ec", 0.6), 0, 0, 0));
      return { root, plus: new THREE.Vector3(-3.5, 0.85, -2.4), minus: new THREE.Vector3(-3.0, 0.85, -2.4) };
    },
  };
}

/** A resistor with its four colour bands, lying along z between two holes. */
function resistorModel(ohms, length, m) {
  const root = new THREE.Group();
  const body = mesh(new THREE.CapsuleGeometry(0.17, 0.75, 6, 16), standard("#e3cfa0", 0.55), 0, 0.55, 0);
  body.rotation.x = Math.PI / 2;
  root.add(body);
  resistorBands(ohms).forEach((band, i) => {
    const ring = mesh(new THREE.CylinderGeometry(0.182, 0.182, 0.08, 16), standard(band.colour, band.name === "gold" ? 0.3 : 0.5, band.name === "gold" ? 0.8 : 0), 0, 0.55, -0.32 + i * 0.17 + (i === 3 ? 0.1 : 0));
    ring.rotation.x = Math.PI / 2;
    root.add(ring);
  });
  const half = length / 2;
  const [lead] = tube([[0, 0, -half], [0, 0.55, -half], [0, 0.55, -0.5], [0, 0.55, 0.5], [0, 0.55, half], [0, 0, half]], 0.03, m.lead, 24);
  root.add(lead);
  return root;
}

/** The meter's screen: big digits like a real multimeter's LCD. */
function drawMeter(paint, w, h, text) {
  paint.fillStyle = "#b9c7a3";
  paint.fillRect(0, 0, w, h);
  paint.fillStyle = "rgba(0,0,0,0.08)";
  paint.fillRect(0, h - 18, w, 18);
  paint.fillStyle = "#1d2416";
  paint.font = "bold 64px ui-monospace, Menlo, monospace";
  paint.textAlign = "right";
  paint.textBaseline = "middle";
  paint.fillText(text, w - 16, h / 2 + 4);
}

/** The bench around the board: a multimeter reading the supply, a soldering
 * station, reels of hook-up wire and a parts tray. Returns { group, read }. */
function benchTools() {
  const group = new THREE.Group();
  // The multimeter, front right, with its probes.
  const meter = new THREE.Group();
  meter.position.set(17.5, 0, 6.5);
  meter.rotation.y = -0.35;
  meter.add(block(6.2, 1.6, 10.5, standard("#f2b705", 0.55), 0, 0, 0));
  meter.add(block(5.2, 1.0, 9.5, standard("#2a2d31", 0.6), 0, 0.9, 0));
  let reading = "0.00";
  const screen = canvasTexture(320, 150, (paint, w, h) => drawMeter(paint, w, h, reading));
  meter.add(mesh(new THREE.PlaneGeometry(4.4, 2.1), new THREE.MeshStandardMaterial({ map: screen, roughness: 0.35 }), 0, 1.95, -2.7).rotateX(-Math.PI / 2));
  const dial = post(1.4, 0.5, standard("#1b1d20", 0.4), 0, 1.9, 1.2, 28);
  meter.add(dial);
  meter.add(block(0.25, 0.1, 1.2, standard("#f2f2f2", 0.4), 0, 2.4, 0.8));
  for (const [x, colour] of [[-1.4, "#d32f2f"], [1.4, "#1e1e1e"]]) {
    meter.add(post(0.32, 0.4, metal("#c9ccd1", 0.3), x, 1.9, 3.9, 12));
    const [lead] = tube([new THREE.Vector3(x, 2.2, 3.9), new THREE.Vector3(x * 2, 1.2, 7), new THREE.Vector3(x * 3 - 4, 0.3, 8.5), new THREE.Vector3(x * 4 - 7, 0.3, 6)], 0.12, standard(colour, 0.45), 32);
    meter.add(lead);
  }
  group.add(meter);
  // The soldering station: a base with a knob, the iron in its coil holder.
  const station = new THREE.Group();
  station.position.set(-18, 0, 6);
  station.rotation.y = 0.4;
  station.add(block(6, 2.6, 5, standard("#30363d", 0.5), 0, 0, 0));
  station.add(mesh(new THREE.PlaneGeometry(2.2, 1.0), new THREE.MeshBasicMaterial({ color: "#ff5a36" }), -1.2, 1.6, 2.51));
  station.add(post(0.7, 0.6, standard("#c9ccd1", 0.3, 0.8), 1.5, 1.0, 2.5, 20).rotateX(Math.PI / 2));
  const coil = new THREE.Group();
  coil.position.set(0, 2.6, -0.5);
  for (let i = 0; i < 6; i += 1) coil.add(mesh(new THREE.TorusGeometry(1.1, 0.12, 8, 24), metal("#b8bec6", 0.3), 0, 0.5 + i * 0.5, 0).rotateX(Math.PI / 2));
  coil.rotation.x = 0.7;
  station.add(coil);
  const iron = new THREE.Group();
  iron.position.set(0, 4.3, 1.2);
  iron.rotation.x = 0.7;
  iron.add(post(0.6, 5, standard("#1f2328", 0.6), 0, 0, 0, 16), post(0.25, 2.2, metal("#d7dbe0", 0.25), 0, -2.2, 0, 12), mesh(new THREE.ConeGeometry(0.25, 1.2, 12), metal("#9aa0a6", 0.3), 0, -2.8, 0).rotateX(Math.PI));
  station.add(iron);
  group.add(station);
  // Reels of hook-up wire.
  ["#d32f2f", "#1e1e1e", "#f2c94c", "#2f80ed"].forEach((colour, i) => {
    const reel = new THREE.Group();
    reel.position.set(-21 + i * 4.2, 1.6, -8.5);
    reel.rotation.z = Math.PI / 2;
    const flange = standard("#e9e6df", 0.6);
    reel.add(post(1.6, 0.25, flange, 0, -1.3, 0, 24), post(1.6, 0.25, flange, 0, 1.05, 0, 24), post(1.15, 2.1, standard(colour, 0.45), 0, -1.05, 0, 24));
    group.add(reel);
  });
  // A tray of loose parts: a few resistors, LEDs and capacitors.
  const tray = new THREE.Group();
  tray.position.set(12, 0, -8.5);
  tray.add(block(9, 0.4, 5, standard("#d8dde3", 0.5), 0, 0, 0));
  for (const x of [-4.4, -0.2, 4.4]) tray.add(block(0.2, 1, 5, standard("#c9cfd6", 0.5), x, 0.4, 0));
  ["#d32f2f", "#36a852", "#2f6bff"].forEach((colour, i) => tray.add(post(0.32, 0.8, standard(colour, 0.25, 0, { transparent: true, opacity: 0.9 }), -3 + i * 0.9, 0.4, 1.2, 12)));
  for (let i = 0; i < 4; i += 1) {
    const body = post(0.22, 1.1, standard("#d9c49a", 0.5), 1 + i * 0.7, 0.6, -1.2, 10);
    body.rotation.z = Math.PI / 2;
    tray.add(body);
  }
  tray.add(post(0.5, 1.2, standard("#2b4c9a", 0.4), 3.6, 0.4, 1.4, 16), post(0.4, 0.9, standard("#2b4c9a", 0.4), 2.5, 0.4, 1.6, 16));
  group.add(tray);
  // A monitor for the board computer (its HDMI screen), back left: a terminal
  // of its output, or what its program draws; dark when nothing runs.
  const monitor = new THREE.Group();
  monitor.position.set(-13.5, 0, -6);
  monitor.rotation.y = 0.35;
  const bezel = standard("#16181b", 0.4);
  monitor.add(block(4.5, 0.4, 3.2, bezel, 0, 0, 0), block(0.9, 4.6, 0.6, bezel, 0, 0.4, -0.4));
  let view = undefined;
  const screenTexture = canvasTexture(480, 360, (paint, w, h) => paintMonitor(paint, w, h, null));
  const panel = new THREE.MeshStandardMaterial({ color: "#ffffff", map: screenTexture, emissive: "#ffffff", emissiveMap: screenTexture, emissiveIntensity: 0.15, roughness: 0.25 });
  monitor.add(mesh(new THREE.BoxGeometry(12.4, 9.4, 0.7), [bezel, bezel, bezel, bezel, panel, bezel], 0, 8.6, 0));
  group.add(monitor);
  const show = (next) => {
    if (next === view) return;
    view = next;
    paintMonitor(screenTexture.image.getContext("2d"), screenTexture.image.width, screenTexture.image.height, next || null);
    screenTexture.needsUpdate = true;
    panel.emissiveIntensity = next ? 0.9 : 0.15;
  };
  const read = (text) => {
    if (text === reading) return;
    reading = text;
    drawMeter(screen.image.getContext("2d"), screen.image.width, screen.image.height, reading);
    screen.needsUpdate = true;
  };
  return { group, read, show };
}

export function makeCircuitBench() {
  const group = new THREE.Group();
  const m = {
    black: standard("#1b1b1d", 0.5),
    tin: metal("#d5d8dc", 0.25),
    gold: metal("#d4af37", 0.25),
    lead: metal("#c4c8cc", 0.35),
    red: standard("#d32f2f", 0.45),
    blackWire: standard("#1e1e1e", 0.45),
  };
  const mat = mesh(new THREE.PlaneGeometry(46, 26), new THREE.MeshStandardMaterial({ map: matTexture(), roughness: 0.85 }), 0, 0.01, 3);
  mat.rotation.x = -Math.PI / 2;
  group.add(mat);
  const white = standard("#f4f2ec", 0.6);
  const board = mesh(new THREE.BoxGeometry(BOARD_W, TOP, BOARD_D), [white, white, new THREE.MeshStandardMaterial({ map: breadboardTexture(), roughness: 0.6 }), white, white, white], 0, TOP / 2, 0);
  pickable(board, { type: "board" });
  group.add(board);
  const build = new THREE.Group();
  group.add(build);
  const tools = benchTools();
  group.add(tools.group);
  const labels = new THREE.Group();
  group.add(labels);
  const make = makers(m);
  const dotCount = 600;
  const dots = new THREE.InstancedMesh(new THREE.SphereGeometry(0.11, 8, 6), new THREE.MeshBasicMaterial({ color: "#8ff0ff", transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false }), dotCount);
  dots.count = 0;
  dots.frustumCulled = false;
  group.add(dots);
  const smokeTexture = puffTexture();
  let live = [];
  // While a program runs on the board computer: each part's state from it.
  let running = null;
  let flows = [];
  let smoke = [];
  const matrix = new THREE.Matrix4();

  function clear() {
    for (const child of [...build.children]) {
      build.remove(child);
      dispose(child);
    }
    for (const child of [...labels.children]) {
      labels.remove(child);
      dispose(child);
    }
    live = [];
    flows = [];
    smoke = [];
  }

  function jumper(from, to, material, lift = 1.4) {
    const a = from.clone();
    const b = to.clone();
    const up = Math.max(a.y, b.y) + lift;
    const [wire, curve] = tube([a, new THREE.Vector3(a.x, up, a.z), new THREE.Vector3((a.x + b.x) / 2, up + 0.3, (a.z + b.z) / 2), new THREE.Vector3(b.x, up, b.z), b], 0.08, material, 48);
    build.add(wire);
    return curve;
  }

  function tag(text, position) {
    const sprite = label(text, { height: 1.15 });
    sprite.position.copy(position);
    labels.add(sprite);
  }

  /** Lay out a build: entries [{id, count}], result from simulateBuild. */
  function update(entries, result, powered) {
    clear();
    // The meter reads the supply while the power is on.
    tools.read(powered && result && result.volts ? Number(result.volts).toFixed(2) : "0.00");
    if (!entries.length) return;
    const rows = new Map((result ? result.parts : []).map((row) => [row.id, row]));
    const supply = entries.find((entry) => (findPart(entry.id) || {}).kind === "power") || entries.find((entry) => entry.id === "solar");
    let railPlus = new THREE.Vector3(-BOARD_W / 2 + 0.7, TOP, RAIL_PLUS);
    let railMinus = new THREE.Vector3(-BOARD_W / 2 + 0.7, TOP, RAIL_MINUS);
    let supplyPath = null;
    if (supply && make[supply.id]) {
      const model = make[supply.id](supply.count || 1);
      model.root.position.set(supply.id === "solar" ? -16 : -13, 0, supply.id === "solar" ? -3 : 0.5);
      if (supply.id === "solar") model.root.rotation.y = 0.5;
      model.root.updateMatrixWorld(true);
      pickable(model.root, { type: "part", id: supply.id });
      build.add(model.root);
      const plus = model.root.localToWorld(model.plus.clone());
      const minus = model.root.localToWorld(model.minus.clone());
      const red = jumper(plus, railPlus, m.red, 1.0);
      const black = jumper(railMinus, minus, m.blackWire, 0.8);
      supplyPath = [red, black];
      const part = findPart(supply.id);
      tag(`${result ? result.supply || part.name : part.name}${result && result.volts ? ` · ${result.volts} V` : ""}`, new THREE.Vector3(model.root.position.x, 5.5, model.root.position.z));
    }
    let slot = -BOARD_W / 2 + 1.6;
    let front = -10;
    const resistors = result ? [...result.resistors] : [];
    for (const entry of entries) {
      if (supply && entry.id === supply.id) continue;
      const part = findPart(entry.id);
      if (!part) continue;
      const row = rows.get(entry.id) || { state: powered ? "ok" : "off", milliamps: 0 };
      const copies = Math.min(entry.count || 1, MAX_COPIES);
      for (let copy = 0; copy < copies; copy += 1) {
        const offBoard = OFF_BOARD.has(entry.id);
        let model;
        if (entry.id === "resistor") {
          const ohms = resistors.length ? resistors[0].ohms : 220;
          const root = resistorModel(ohms, 2.0, m);
          model = { root, plus: new THREE.Vector3(0, 0, -1.0), minus: new THREE.Vector3(0, 0, 1.0) };
        } else if (make[entry.id]) model = make[entry.id](1);
        else {
          const root = new THREE.Group();
          root.add(block(1.5, 1.0, 1.5, standard("#8a8f98", 0.5), 0, 0, 0));
          model = { root, plus: new THREE.Vector3(-0.5, 0, -0.75), minus: new THREE.Vector3(0.5, 0, -0.75) };
        }
        const size = new THREE.Box3().setFromObject(model.root).getSize(new THREE.Vector3());
        if (offBoard) {
          model.root.position.set(front + size.x / 2, 0, 8.5);
          front += size.x + 1.5;
        } else {
          model.root.position.set(slot + size.x / 2, TOP, 0.6);
          slot += Math.max(size.x, 1.0) + 0.9;
        }
        model.root.updateMatrixWorld(true);
        pickable(model.root, { type: "part", id: entry.id });
        build.add(model.root);
        const plus = model.root.localToWorld(model.plus.clone());
        const minus = model.root.localToWorld(model.minus.clone());
        const x = model.root.position.x;
        const level = powered ? LEVEL[row.state] ?? 0 : 0;
        const segments = [];
        const resistor = resistors.find((item) => item.for === part.name);
        if (resistor && !offBoard) {
          const root = resistorModel(resistor.ohms, plus.z - RAIL_PLUS, m);
          root.position.set(plus.x, TOP, (plus.z + RAIL_PLUS) / 2);
          pickable(root, { type: "resistor", ohms: resistor.ohms, for: part.name });
          build.add(root);
          segments.push(new THREE.LineCurve3(new THREE.Vector3(plus.x, TOP + 0.55, RAIL_PLUS), new THREE.Vector3(plus.x, TOP + 0.55, plus.z)));
        } else segments.push(jumper(new THREE.Vector3(offBoard ? Math.max(-7.5, Math.min(7.5, x)) : x - 0.3, TOP, RAIL_PLUS), plus, m.red, offBoard ? 2.5 : 1.2));
        segments.push(new THREE.LineCurve3(plus, minus));
        segments.push(jumper(minus, new THREE.Vector3(offBoard ? Math.max(-7.5, Math.min(7.5, x)) + 0.4 : x + 0.3, TOP, RAIL_MINUS), m.blackWire, offBoard ? 2.0 : 0.9));
        if (level > 0 && row.state !== "ok" && row.milliamps > 0) addFlow(segments, row.milliamps);
        live.push({ model, row, level, key: `${entry.id}#${copy}` });
        if (row.state === "burnt" && powered) smoke.push(addSmoke(model.root.position.clone().add(new THREE.Vector3(0, size.y + 0.5, 0))));
        if (copy === 0) tag(`${part.name}${powered && row.state ? ` · ${row.state}` : ""}`, new THREE.Vector3(model.root.position.x, (offBoard ? 0 : TOP) + size.y + 1.4, model.root.position.z));
      }
    }
    if (powered && supplyPath && result && result.total_ma) addFlow([supplyPath[0], supplyPath[1]], result.total_ma);
  }

  function addFlow(segments, milliamps) {
    const path = new THREE.CurvePath();
    for (const segment of segments) path.add(segment);
    const length = path.getLength();
    if (!(length > 1e-6)) return;
    const strength = Math.min(1, Math.log10(1 + milliamps) / 3);
    const count = Math.round(4 + strength * 18 * Math.max(1, length / 20));
    flows.push({ path, length, speed: 2 + strength * 12, count, offset: Math.random() });
  }

  function addSmoke(position) {
    const puffs = [];
    for (let i = 0; i < 6; i += 1) {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: smokeTexture, color: "#6f6f6f", transparent: true, depthWrite: false, opacity: 0 }));
      sprite.userData.keepTexture = true;
      sprite.position.copy(position);
      build.add(sprite);
      puffs.push({ sprite, phase: i / 6, base: position.clone() });
    }
    return puffs;
  }

  function tick(t, dt) {
    for (const { model, row, level, key } of live) {
      const run = running && running[key];
      if (model.tick) model.tick(t, dt, run ? run.level : level, run ? run.state : row.state, run);
    }
    tools.show(running ? running.monitor : null);
    let used = 0;
    for (const flow of flows) {
      for (let i = 0; i < flow.count && used < dotCount; i += 1) {
        const u = (((t * flow.speed) / flow.length + flow.offset + i / flow.count) % 1 + 1) % 1;
        matrix.makeTranslation(flow.path.getPointAt(u));
        dots.setMatrixAt(used, matrix);
        used += 1;
      }
    }
    dots.count = used;
    dots.instanceMatrix.needsUpdate = true;
    for (const puffs of smoke) {
      for (const puff of puffs) {
        const phase = (t * 0.35 + puff.phase) % 1;
        puff.sprite.position.set(puff.base.x + Math.sin(t + puff.phase * 9) * 0.6 * phase, puff.base.y + phase * 6, puff.base.z);
        puff.sprite.scale.setScalar(1 + phase * 3);
        puff.sprite.material.opacity = (1 - phase) * 0.55;
      }
    }
  }

  return {
    group,
    update,
    tick,
    setLabels: (on) => (labels.visible = on),
    setRun: (states) => (running = states),
    stop: () => {
      clear();
      dispose(group);
      smokeTexture.dispose();
    },
  };
}
