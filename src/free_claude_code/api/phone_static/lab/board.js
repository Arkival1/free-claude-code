// The Lab's board computer: when an Arduino, ESP32 or Raspberry Pi is on the
// electronics bench, its program (Arduino-style JavaScript: setup(), loop(),
// digitalWrite, analogRead, delay, Serial, a display) runs on the phone and
// drives the parts on the board. The program runs in a sealed box (an iframe
// with an origin of its own and a content policy with no network), on a
// virtual clock: delay() moves the clock instead of waiting, so the box runs
// a little ahead and the page plays the changes back in real time (or all at
// once for a test). Loops are counted, so an endless one stops the program,
// not the phone.
import { findPart } from "./science.js";

export const BRAINS = new Set(["arduino", "esp32", "raspberry-pi"]);
const ROLES = {
  "led-red": "led", "led-green": "led", "led-blue": "led", "led-white": "led", "led-power": "led", "led-strip": "led", bulb: "led",
  motor: "motor", fan: "motor", pump: "motor", vibration: "motor", servo: "servo", buzzer: "buzzer", speaker: "buzzer", relay: "relay",
  "light-sensor": "light", "temp-sensor": "temp", "soil-sensor": "soil", "distance-sensor": "distance", "motion-sensor": "motion",
  button: "button", switch: "switch", oled: "display",
};
const NAMES = { "light-sensor": "LIGHT", "temp-sensor": "TEMP", "soil-sensor": "SOIL", "distance-sensor": "DISTANCE", "motion-sensor": "MOTION", "led-power": "POWER_LED", "led-strip": "LED_STRIP" };
const PWM = [9, 10, 6, 5, 3, 11];
const DIGITAL = [13, 12, 11, 10, 8, 7, 6, 5, 4, 3, 9];
const ANALOG = { light: 14, temp: 15, soil: 16, distance: 17 };
const DIGITAL_IN = { motion: 2, button: 4, switch: 5 };
const MAX_COPIES = 4;
/** Sensor readings the user sets with sliders (and a test starts from). */
export const SENSOR_DEFAULTS = { light: 60, temp: 22, soil: 40, distance: 80, motion: false, button: false, switch: false };
export const SENSOR_RANGES = {
  light: { min: 0, max: 100, step: 1, unit: "%", name: "Light" },
  temp: { min: -10, max: 50, step: 0.5, unit: "°C", name: "Temperature" },
  soil: { min: 0, max: 100, step: 1, unit: "% wet", name: "Soil moisture" },
  distance: { min: 2, max: 400, step: 1, unit: "cm", name: "Distance" },
};

const label = (id) => NAMES[id] || id.toUpperCase().replace(/[^A-Z0-9]+/g, "_");

/** Which pin each part is wired to (the same build always gets the same pins). */
export function wiring(parts) {
  const brain = parts.find((entry) => BRAINS.has(entry.id));
  const wires = [];
  const used = new Set();
  const take = (pool) => {
    const pin = pool.find((candidate) => !used.has(candidate));
    if (pin !== undefined) used.add(pin);
    return pin;
  };
  Object.values(DIGITAL_IN).forEach((pin) => used.add(pin));
  const order = (role) => (role === "motor" || role === "servo" ? 0 : role === "buzzer" ? 1 : 2);
  const outputs = [];
  for (const entry of parts) {
    const role = ROLES[entry.id];
    if (!role) continue;
    const copies = Math.min(Math.max(1, Number(entry.count) || 1), MAX_COPIES);
    for (let copy = 0; copy < copies; copy += 1) {
      const part = findPart(entry.id);
      const name = `${part ? part.name : entry.id}${copies > 1 ? ` ${copy + 1}` : ""}`;
      const constant = `${label(entry.id)}${copy ? `_${copy + 1}` : ""}`;
      if (role in ANALOG) wires.push({ id: entry.id, copy, role, name, constant, pin: ANALOG[role] + copy * 0, input: true });
      else if (role in DIGITAL_IN) wires.push({ id: entry.id, copy, role, name, constant, pin: DIGITAL_IN[role], input: true });
      else if (role === "display") wires.push({ id: entry.id, copy, role, name, constant: "DISPLAY", pin: null, input: false });
      else outputs.push({ id: entry.id, copy, role, name, constant });
    }
  }
  outputs.sort((a, b) => order(a.role) - order(b.role));
  for (const wire of outputs) {
    const pin = wire.role === "motor" || wire.role === "servo" ? take(PWM) ?? take(DIGITAL) : wire.role === "buzzer" ? (used.has(8) ? take(DIGITAL) : (used.add(8), 8)) : take(DIGITAL) ?? take(PWM);
    if (pin !== undefined) wires.push({ ...wire, pin, input: false });
  }
  return { brain: brain ? brain.id : "", wires };
}

/** The wiring as the program's names: LED_RED = 13, LIGHT = A0... */
export function constantsOf(wire) {
  const names = {};
  for (const item of wire.wires) if (item.pin !== null) names[item.constant] = item.pin;
  return names;
}

const pinText = (pin) => (pin >= 14 ? `A${pin - 14}` : String(pin));

export function wiringText(wire) {
  if (!wire.brain) return "No board computer on the board (add an Arduino, ESP32 or Raspberry Pi).";
  const rows = wire.wires.map((item) => (item.role === "display" ? `display (OLED screen): ${item.name}` : `${item.constant} = pin ${pinText(item.pin)}: ${item.name}${item.input ? " (input)" : ""}`));
  return rows.length ? rows.join("\n") : "Nothing is wired to the board computer yet: add LEDs, motors, a buzzer, sensors, a button or a screen.";
}

/** A first program for what's on the board, so Run always does something. */
export function starterProgram(wire) {
  const outs = wire.wires.filter((item) => !item.input && item.pin !== null);
  const leds = outs.filter((item) => item.role === "led");
  const motors = outs.filter((item) => item.role === "motor");
  const servo = outs.find((item) => item.role === "servo");
  const buzzer = outs.find((item) => item.role === "buzzer");
  const has = (role) => wire.wires.some((item) => item.role === role);
  const lines = ["// Runs once at the start.", "function setup() {", "  Serial.begin(9600);"];
  for (const item of outs) lines.push(`  pinMode(${item.constant}, OUTPUT);`);
  if (servo) lines.push(`  servo.attach(${servo.constant});`);
  if (has("display")) lines.push('  display.clear();', '  display.println("FCC Lab");');
  lines.push('  Serial.println("Ready");', "}", "", "// Runs again and again.", "function loop() {");
  if (has("light")) lines.push("  const light = readLight(); // 0-100 %", '  Serial.println("Light: " + light + " %");');
  if (has("temp")) lines.push("  const temp = readTemperature(); // °C", '  Serial.println("Temp: " + temp + " C");');
  if (has("distance")) lines.push("  const cm = readDistance();", '  Serial.println("Distance: " + cm + " cm");');
  if (has("display")) lines.push("  display.clear();", `  display.println(${has("temp") ? '"Temp " + readTemperature() + " C"' : has("light") ? '"Light " + readLight() + " %"' : '"Time " + Math.floor(millis() / 1000) + " s"'});`);
  if (leds.length) {
    const on = has("light") ? "light < 30" : has("button") ? "digitalRead(BUTTON)" : "true";
    if (on === "true") {
      for (const item of leds) lines.push(`  digitalWrite(${item.constant}, HIGH);`);
      lines.push("  delay(500);");
      for (const item of leds) lines.push(`  digitalWrite(${item.constant}, LOW);`);
    } else for (const item of leds) lines.push(`  digitalWrite(${item.constant}, ${on} ? HIGH : LOW);`);
  }
  for (const item of motors) lines.push(`  analogWrite(${item.constant}, ${has("temp") ? "readTemperature() > 25 ? 255 : 0" : "180"}); // 0-255 speed`);
  if (servo) lines.push("  servo.write((millis() / 20) % 180);");
  if (buzzer) lines.push(`  if (${has("motion") ? "digitalRead(MOTION)" : has("button") ? "digitalRead(BUTTON)" : "false"}) tone(${buzzer.constant}, 880, 200);`);
  lines.push("  delay(500);", "}");
  return lines.join("\n");
}

// What runs in the box. It becomes text for the box's page, so it uses
// nothing from this module.
function boardBox() {
  const send = (message) => parent.postMessage(message, "*");
  const LIMIT = 5000000;
  const AHEAD = 600000;
  let vt = 0;
  let horizon = 0;
  let budget = 0;
  let events = [];
  let inputs = {};
  let line = "";
  let screen = [];
  let started = false;
  let dead = false;
  const out = (kind, pin, value) => {
    events.push({ t: vt, kind, pin, value });
    if (events.length > 20000) throw new Error("The program changes things too fast (20,000 changes in a moment): add a delay().");
  };
  const tick = () => {
    budget += 1;
    if (budget > LIMIT) throw new Error("A loop ran millions of times without stopping, so the program was stopped (an endless loop?).");
  };
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const sensor = (name) => Number(inputs[name] ?? 0);
  const api = {
    HIGH: 1, LOW: 0, INPUT: 0, OUTPUT: 1, INPUT_PULLUP: 2, A0: 14, A1: 15, A2: 16, A3: 17, A4: 18, A5: 19, LED_BUILTIN: 13,
    __tick: tick,
    pinMode() {},
    digitalWrite(pin, value) {
      tick();
      out("pin", Number(pin), value ? 255 : 0);
    },
    analogWrite(pin, value) {
      tick();
      out("pin", Number(pin), clamp(Math.round(Number(value) || 0), 0, 255));
    },
    digitalRead(pin) {
      tick();
      return inputs.pins && inputs.pins[pin] ? 1 : 0;
    },
    analogRead(pin) {
      tick();
      const role = { 14: "light", 15: "temp", 16: "soil", 17: "distance" }[pin];
      if (role === "light") return Math.round((sensor("light") / 100) * 1023);
      if (role === "temp") return Math.round(((0.5 + sensor("temp") / 100) / 5) * 1023);
      if (role === "soil") return Math.round(1023 - (sensor("soil") / 100) * 700);
      if (role === "distance") return Math.round(clamp(sensor("distance") / 400, 0, 1) * 1023);
      return 0;
    },
    readLight: () => (tick(), sensor("light")),
    readTemperature: () => (tick(), sensor("temp")),
    readSoil: () => (tick(), sensor("soil")),
    readDistance: () => (tick(), sensor("distance")),
    delay(ms) {
      tick();
      vt += Math.max(0, Number(ms) || 0);
      if (vt > horizon + AHEAD) throw new Error("loop() or setup() never finishes (a while loop that never ends?): keep the repeating part in loop().");
    },
    delayMicroseconds(us) {
      tick();
      vt += Math.max(0, Number(us) || 0) / 1000;
    },
    millis: () => Math.floor(vt),
    micros: () => Math.floor(vt * 1000),
    tone(pin, frequency, duration) {
      tick();
      out("tone", Number(pin), Math.max(0, Number(frequency) || 0));
      if (duration > 0) events.push({ t: vt + Number(duration), kind: "tone", pin: Number(pin), value: 0 });
    },
    noTone(pin) {
      tick();
      out("tone", Number(pin), 0);
    },
    map: (x, inLow, inHigh, outLow, outHigh) => ((x - inLow) * (outHigh - outLow)) / (inHigh - inLow) + outLow,
    constrain: clamp,
    random: (low, high) => (high === undefined ? Math.floor(Math.random() * low) : Math.floor(low + Math.random() * (high - low))),
    Serial: {
      begin() {},
      print(value = "") {
        line += String(value);
      },
      println(value = "") {
        tick();
        out("serial", null, (line + String(value)).slice(0, 300));
        line = "";
      },
    },
    display: {
      clear() {
        screen = [];
        out("display", null, []);
      },
      print(value = "") {
        if (!screen.length) screen.push("");
        screen[screen.length - 1] = (screen[screen.length - 1] + String(value)).slice(0, 40);
        out("display", null, screen.slice(-6));
      },
      println(value = "") {
        screen.push(String(value).slice(0, 40));
        out("display", null, screen.slice(-6));
      },
      setCursor() {},
      display() {},
      show() {},
    },
    servo: {
      pin: 9,
      attach(pin) {
        this.pin = Number(pin);
      },
      write(angle) {
        tick();
        out("servo", this.pin, clamp(Number(angle) || 0, 0, 180));
      },
    },
  };
  const fail = (error) => {
    dead = true;
    const text = String((error && error.message) || error).replace(/^Uncaught /, "").replace(/Failed to execute '\w+' on '\w+': /, "");
    // The program's own line, from the first stack frame in its script.
    const frame = String((error && error.stack) || "").split("\n").find((row) => /<anonymous>:\d+/.test(row));
    const line = (error && error.line) || (frame ? Number(frame.match(/<anonymous>:(\d+)/)[1]) : 0);
    send({ type: "error", text: text.slice(0, 400), line });
  };
  addEventListener("error", (event) => {
    event.preventDefault();
    fail({ message: event.message, line: event.lineno });
  });
  addEventListener("message", (event) => {
    const job = event.data;
    if (event.source !== parent || !job || dead) return;
    if (job.type === "load") {
      Object.assign(window, api, job.constants);
      const script = document.createElement("script");
      script.textContent = `${job.code}\n;window.__fcc = { setup: typeof setup === "function" ? setup : null, loop: typeof loop === "function" ? loop : null };`;
      document.head.append(script);
      if (dead) return;
      if (!window.__fcc || (!window.__fcc.setup && !window.__fcc.loop)) return fail("The program needs a setup() or loop() function.");
      send({ type: "loaded" });
      return;
    }
    if (job.type === "advance") {
      inputs = job.inputs || {};
      horizon = job.until;
      budget = 0;
      const wall = performance.now();
      try {
        if (!started) {
          started = true;
          if (window.__fcc.setup) window.__fcc.setup();
        }
        let calls = 0;
        while (window.__fcc.loop && vt < job.until && calls < 100000 && performance.now() - wall < 250) {
          const before = vt;
          window.__fcc.loop();
          if (vt === before) vt += 1;
          calls += 1;
        }
      } catch (error) {
        send({ type: "events", events, vt });
        events = [];
        return fail(error);
      }
      send({ type: "events", events, vt, ended: !window.__fcc.loop });
      events = [];
    }
  });
  send({ type: "ready" });
}

const BOX_HTML = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'">
</head><body><script>(${boardBox.toString()})();</script></body></html>`;

/** Count every loop's turns: `) {` and `do {` get a tick, so an endless
 * loop stops the program instead of freezing the phone. Lines stay put. */
export function guardLoops(code) {
  return String(code).replace(/\)\s*\{/g, (match) => `${match}__tick();`).replace(/\bdo\s*\{/g, (match) => `${match}__tick();`);
}

/** What the outputs are doing now, from the events played so far. */
function blankState() {
  return { pins: {}, tones: {}, servos: {}, display: [], serial: [] };
}

function apply(state, event) {
  if (event.kind === "pin") state.pins[event.pin] = event.value;
  else if (event.kind === "tone") state.tones[event.pin] = event.value;
  else if (event.kind === "servo") state.servos[event.pin] = event.value;
  else if (event.kind === "display") state.display = event.value;
  else if (event.kind === "serial") {
    state.serial.push(`${(event.t / 1000).toFixed(1)}s  ${event.value}`);
    if (state.serial.length > 200) state.serial.shift();
  }
}

/** How each wired part looks now: { "led-red#0": { state, level, angle, lines } }. */
export function partsNow(wire, state) {
  const now = {};
  for (const item of wire.wires) {
    const key = `${item.id}#${item.copy}`;
    if (item.role === "display") now[key] = { state: "on", level: 1, lines: state.display };
    else if (item.input) now[key] = { state: "on", level: 1 };
    else if (item.role === "servo") now[key] = { state: "on", level: 1, angle: state.servos[item.pin] ?? 90 };
    else if (item.role === "buzzer") {
      const level = state.tones[item.pin] || state.pins[item.pin] ? 1 : 0;
      now[key] = { state: level ? "on" : "off", level, frequency: state.tones[item.pin] || 0 };
    } else {
      const level = (state.pins[item.pin] || 0) / 255;
      now[key] = { state: level > 0 ? "on" : "off", level };
    }
  }
  if (wire.brain) now[`${wire.brain}#0`] = { state: "on", level: 1 };
  return now;
}

/** The sensor values as the box reads them (digital inputs by pin). */
function inputsFor(wire, sensors) {
  const pins = {};
  for (const item of wire.wires) if (item.role in DIGITAL_IN) pins[item.pin] = Boolean(sensors[item.role]);
  return { ...sensors, pins };
}

/**
 * Run a program for the parts on the board. live: play it in real time
 * (onState gets each change); otherwise run `seconds` of board time as fast
 * as it goes. Returns { stop(), done } (done: { state, events, error, seconds }).
 */
export function runBoard(code, parts, { host = document.body, live = true, seconds = 10, sensors = () => SENSOR_DEFAULTS, onState = () => {} } = {}) {
  const wire = wiring(parts);
  const state = blankState();
  const all = [];
  let settle;
  const done = new Promise((resolve) => (settle = resolve));
  let closed = false;
  let error = "";
  let boxTime = 0;
  let waiting = false;
  let pending = [];
  let lastWord = Date.now();
  let started = 0;
  let paused = 0;
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.className = "board-box";
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;width:1px;height:1px;opacity:0;pointer-events:none;border:0;left:-10px;top:-10px";
  const now = () => (started ? Date.now() - started - paused : 0);
  const stop = (reason = "") => {
    if (closed) return;
    closed = true;
    if (reason && !error) error = reason;
    clearInterval(timer);
    removeEventListener("message", listen);
    frame.remove();
    settle({ state, events: all, error, seconds: Math.round((live ? now() : boxTime) / 100) / 10, wire });
  };
  const advance = (until) => {
    waiting = true;
    lastWord = Date.now();
    frame.contentWindow.postMessage({ type: "advance", until, inputs: inputsFor(wire, sensors()) }, "*");
  };
  const listen = (event) => {
    if (event.source !== frame.contentWindow || !event.data || closed) return;
    const message = event.data;
    lastWord = Date.now();
    if (message.type === "ready") {
      frame.contentWindow.postMessage({ type: "load", code: guardLoops(code), constants: constantsOf(wire) }, "*");
    } else if (message.type === "loaded") {
      started = Date.now();
      advance(live ? 1000 : 2000);
    } else if (message.type === "error") {
      error = `${message.text}${message.line ? ` (line ${message.line})` : ""}`;
      if (!live || !pending.length) stop();
      else boxTime = Infinity;
    } else if (message.type === "events") {
      waiting = false;
      const events = Array.isArray(message.events) ? message.events.slice(0, 20000) : [];
      boxTime = Number(message.vt) || boxTime;
      if (live) pending.push(...events);
      else {
        for (const item of events) {
          apply(state, item);
          if (all.length < 50000) all.push(item);
        }
        if (boxTime >= seconds * 1000 || message.ended) stop();
        else advance(Math.min(seconds * 1000, boxTime + 2000));
      }
    }
  };
  addEventListener("message", listen);
  let hiddenAt = 0;
  const timer = setInterval(() => {
    if (document.hidden) {
      hiddenAt = hiddenAt || Date.now();
      return;
    }
    if (hiddenAt) {
      paused += Date.now() - hiddenAt;
      hiddenAt = 0;
    }
    if (waiting && Date.now() - lastWord > 4000) return stop("The program stopped answering, so it was stopped.");
    if (!live || !started) return;
    const t = now();
    let changed = false;
    pending.sort((a, b) => a.t - b.t);
    while (pending.length && pending[0].t <= t) {
      const item = pending.shift();
      apply(state, item);
      if (all.length < 50000) all.push(item);
      changed = true;
    }
    if (changed) onState(state, partsNow(wire, state));
    if (boxTime === Infinity && !pending.length) return stop();
    if (!waiting && boxTime !== Infinity && boxTime - t < 500) advance(t + 1000);
  }, 40);
  frame.srcdoc = BOX_HTML;
  host.append(frame);
  return { stop, done, wire };
}

/** A test run in plain words: what each output did, the serial output, the screen. */
export function describeRun(result) {
  const { wire, events, state, error, seconds } = result;
  const lines = [`Ran the program for ${seconds} s of board time.`];
  if (error) lines.push(`It stopped with an error: ${error}`);
  for (const item of wire.wires.filter((entry) => !entry.input && entry.pin !== null)) {
    const mine = events.filter((event) => event.pin === item.pin && (event.kind === "pin" || event.kind === "tone" || event.kind === "servo"));
    if (item.role === "servo") {
      const angles = mine.map((event) => event.value);
      lines.push(`${item.name} (${item.constant}): ${angles.length ? `moved ${angles.length} times, between ${Math.min(...angles)}° and ${Math.max(...angles)}°, ended at ${angles.at(-1)}°` : "never moved"}.`);
      continue;
    }
    let on = 0;
    let level = 0;
    let since = 0;
    let turnsOn = 0;
    for (const event of mine) {
      if (level > 0) on += event.t - since;
      if (!(level > 0) && event.value > 0) turnsOn += 1;
      level = event.value;
      since = event.t;
    }
    if (level > 0) on += seconds * 1000 - since;
    const share = seconds ? Math.round((on / (seconds * 1000)) * 100) : 0;
    lines.push(`${item.name} (${item.constant}, pin ${pinText(item.pin)}): ${turnsOn ? `on ${turnsOn} time${turnsOn === 1 ? "" : "s"}, ${share}% of the time${turnsOn > 1 ? ` (about ${(turnsOn / seconds).toFixed(2)} times a second)` : ""}` : "stayed off"}${level > 0 && level < 255 && item.role === "motor" ? `, ended at speed ${level}/255` : ""}.`);
  }
  if (state.display.length) lines.push(`The screen shows: ${state.display.join(" | ")}`);
  if (state.serial.length) lines.push(`Serial output (last ${Math.min(12, state.serial.length)}):`, ...state.serial.slice(-12).map((text) => `  ${text}`));
  else lines.push("Nothing was printed to Serial.");
  return lines.join("\n");
}
