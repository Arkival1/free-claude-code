// The Lab's workshop: the chemistry bench, the electronics bench, the
// blueprints shelf and the Library (build-your-own-x). The user works the
// benches from the Lab screen; Jarvis works them himself through the lab tool
// (he walks to that room in the Lab box instead of handing the job to another
// agent). Same rules as the PC Lab (lab/science.js). Saved blueprints keep
// every version, so a chip, mixture or invention can be reloaded and improved.
import { state, save, changed, feed } from "./state.js";
import { uid } from "./ui.js";
import { simulate, simulateBuild, resolveChemical, searchChemicals, findPart, PARTS, MAX_ITEMS } from "../lab/science.js";
import { TUTORIALS } from "../lab/tutorials-data.js";

export const ROOM_NAMES = { chemistry: "Chemistry", electronics: "Electronics", blueprints: "Blueprints", library: "Library" };
export const BLUEPRINT_KINDS = { chip: "Chip", mixture: "Mixture", invention: "Invention" };
const MAX_BLUEPRINTS = 200;
const MAX_VERSIONS = 30;
const isKind = (kind) => typeof kind === "string" && Object.hasOwn(BLUEPRINT_KINDS, kind);
/** A yes from a model or a form: true or "true" only ("false" is no). */
const yes = (value) => value === true || value === "true";
const LED_TINT = { "led-red": "#ff4d4d", "led-green": "#4dff7a", "led-blue": "#4d7dff", "led-white": "#f4f8ff" };

/** Where Jarvis is and what he's doing (the Lab box walks him there). */
export function jarvisWorks(room, doing = "") {
  state.bench.jarvis = { room, doing, at: Date.now() };
  changed("jarvis");
}

async function keepBench() {
  await save.bench();
  changed("bench");
}

const MAX_LOG = 40;
const nameOfChemical = (id) => (resolveChemical(id) || { name: id }).name;
const nameOfPart = (id) => (findPart(id) || { name: id }).name;

/** One step at a bench (by "you" or an agent's name), kept for Jarvis to see. */
export function logStep(by, room, text) {
  if (!Array.isArray(state.bench.log)) state.bench.log = [];
  state.bench.log.push({ by: String(by || "you"), room, text: String(text).slice(0, 220), at: Date.now() });
  if (state.bench.log.length > MAX_LOG) state.bench.log.splice(0, state.bench.log.length - MAX_LOG);
}

/** What changed between two lists ([{id, amount|count}]), in words. */
function changes(before, after, nameOf, unitOf) {
  const amountOf = (entry) => entry.amount ?? entry.count ?? 1;
  const was = new Map(before.map((entry) => [entry.id, amountOf(entry)]));
  const now = new Map(after.map((entry) => [entry.id, amountOf(entry)]));
  const said = [];
  for (const [id, amount] of now) {
    if (!was.has(id)) said.push(`added ${nameOf(id)}${unitOf(id, amount)}`);
    else if (was.get(id) !== amount) said.push(`changed ${nameOf(id)} to${unitOf(id, amount) || ` ${amount}`}`);
  }
  for (const id of was.keys()) if (!now.has(id)) said.push(`took out ${nameOf(id)}`);
  return said.join(", ");
}
const chemUnit = (id, amount) => {
  const chemical = resolveChemical(id);
  return amount === undefined ? "" : ` ${amount} ${chemical && chemical.state === "solid" ? "g" : "mL"}`;
};
const partUnit = (_id, count) => (count > 1 ? ` ×${count}` : "");

/* ------------------------------------------------------------ chemistry */

/** Items as the beaker keeps them: a shelf id (or the name as typed) and an amount. */
function cleanItems(items) {
  if (!Array.isArray(items) || !items.length) throw new Error("Say what goes in the beaker: items like [{name: 'vinegar', amount: 50}].");
  if (items.length > MAX_ITEMS) throw new Error(`The beaker holds up to ${MAX_ITEMS} things at once.`);
  return items.map((item) => {
    const wanted = String((item && (item.id || item.name)) || "").trim();
    const chemical = wanted ? resolveChemical(wanted) : null;
    const amount = Number(item && item.amount);
    return { id: chemical ? chemical.id : wanted, ...(amount > 0 ? { amount } : {}) };
  });
}

/** Put things in the beaker without mixing yet (the user adding bottles). */
export async function setBeaker(items, { heat, flame, by = "you" } = {}) {
  const bench = state.bench.chemistry;
  const said = changes(bench.items, items, nameOfChemical, chemUnit);
  if (!items.length && bench.items.length) logStep(by, "chemistry", "cleaned the beaker");
  else if (said) logStep(by, "chemistry", `${said} in the beaker`);
  if (heat !== undefined && Boolean(heat) !== bench.heat) logStep(by, "chemistry", heat ? "lit the burner" : "turned the burner off");
  if (flame !== undefined && Boolean(flame) !== bench.flame) logStep(by, "chemistry", flame ? "set up a flame test" : "stopped the flame test");
  bench.items = items;
  if (heat !== undefined) bench.heat = Boolean(heat);
  if (flame !== undefined) bench.flame = Boolean(flame);
  bench.result = null;
  await keepBench();
}

/** Mix: run the PC Lab's rules on what's in the beaker. */
export async function mix(items, { heat = false, flame = false, by = "you", step = "" } = {}) {
  const clean = cleanItems(items);
  const result = simulate(clean, { heat, flame });
  state.bench.chemistry = { items: clean, heat: Boolean(heat), flame: Boolean(flame), result };
  logStep(by, "chemistry", `${step || `mixed ${result.ingredients.map((item) => item.name).join(" + ")}${heat ? " over heat" : ""}`}: ${result.summary}`);
  if (by !== "you") jarvisWorks("chemistry", `mixing ${result.ingredients.map((item) => item.name.toLowerCase()).join(" + ")}`);
  await keepBench();
  return result;
}

export function describeMix(result) {
  const v = result.vessel;
  const lines = [result.summary];
  if (result.observations.length) lines.push(`What you'd see: ${result.observations.join(" ")}`);
  if (result.reactions.length) lines.push(`Reactions: ${result.reactions.map((reaction) => `${reaction.equation} (${reaction.kind})`).join("; ")}`);
  if (result.products.length) lines.push(`Made: ${result.products.map((product) => `${product.name} ${product.pretty} ${product.grams} g`).join(", ")}`);
  lines.push(`Beaker: ${v.volume_ml} mL, ${v.temperature_c} °C${v.ph !== null ? `, pH ${v.ph}` : ""}, colour ${v.colour}.`);
  const danger = result.hazards.filter((hazard) => hazard.level !== "caution");
  if (danger.length) lines.push(`Safety: ${danger.map((hazard) => hazard.text).join(" ")}`);
  if (result.unknown.length) lines.push(`Not on the shelf (search the shelf for a match): ${result.unknown.join(", ")}`);
  return lines.join("\n");
}

/* ----------------------------------------------------------- electronics */

function cleanParts(parts) {
  if (!Array.isArray(parts) || !parts.length) throw new Error("Say what goes on the board: parts like [{id: 'aa', count: 2}, {id: 'led-red'}].");
  return parts.map((entry) => {
    const wanted = String((entry && (entry.id || entry.name)) || "").trim();
    const part = findPart(wanted);
    if (!part) throw new Error(`No part called '${wanted}'. The parts action lists them.`);
    const count = Math.trunc(Number(entry.count) || 1);
    return { id: part.id, count: Math.max(1, Math.min(50, count)) };
  });
}

/** Put parts on the board; with power on, the bench works out what happens. */
export async function setBoard(parts, { series, sun, powered, by = "you" } = {}) {
  const bench = state.bench.electronics;
  const wasOn = bench.powered;
  const said = changes(bench.parts, parts, nameOfPart, partUnit);
  if (!parts.length && bench.parts.length) logStep(by, "electronics", "cleared the board");
  else if (said) logStep(by, "electronics", `${said} on the board`);
  if (series !== undefined && Boolean(series) !== bench.series) logStep(by, "electronics", series ? "put the batteries in series" : "put the batteries side by side");
  if (sun !== undefined && Boolean(sun) !== bench.sun) logStep(by, "electronics", sun ? "put the solar panel in the sun" : "put the solar panel in the shade");
  bench.parts = parts;
  if (series !== undefined) bench.series = Boolean(series);
  if (sun !== undefined) bench.sun = Boolean(sun);
  if (powered !== undefined) bench.powered = Boolean(powered);
  if (!parts.length) bench.powered = false;
  bench.result = bench.powered && parts.length ? simulateBuild(parts, { series: bench.series, sun: bench.sun }) : null;
  if (bench.powered && (!wasOn || said)) logStep(by, "electronics", `powered it: ${bench.result.works ? "it works" : "it doesn't work yet"}`);
  else if (wasOn && !bench.powered && parts.length) logStep(by, "electronics", "switched the power off");
  await keepBench();
  return bench.result;
}

/** Build and power a circuit (Jarvis's way in: he walks to Electronics). */
export async function circuit(parts, { series = true, sun = true, by = "you" } = {}) {
  const clean = cleanParts(parts);
  const result = simulateBuild(clean, { series, sun });
  state.bench.electronics = { parts: clean, series: Boolean(series), sun: Boolean(sun), powered: true, result };
  logStep(by, "electronics", `built ${clean.map((entry) => `${nameOfPart(entry.id)}${partUnit(entry.id, entry.count)}`).join(", ")} and powered it: ${result.works ? "it works" : "it doesn't work yet"}`);
  if (by !== "you") jarvisWorks("electronics", `wiring ${clean.map((entry) => findPart(entry.id).name).join(", ")}`);
  await keepBench();
  return result;
}

const ohmsText = (value) => (value >= 1000 ? `${value / 1000} kΩ` : `${value} Ω`);

export function describeCircuit(result) {
  const lines = [result.works ? "It works." : "It doesn't work yet."];
  if (result.supply) lines.push(`Power: ${result.supply}, ${result.volts} V${result.regulated_by ? ` (rail ${result.rail_volts} V through ${result.regulated_by})` : ""}; draws ${result.total_ma} mA, ${result.watts ?? 0} W. ${result.runtime_text || ""}`);
  lines.push(`Parts: ${result.parts.map((row) => `${row.name} ×${row.count}: ${row.state}${row.reason ? ` (${row.reason})` : ""}`).join("; ")}`);
  if (result.resistors.length) lines.push(`Resistors: ${result.resistors.map((item) => `${ohmsText(item.ohms)} ${item.rating} for the ${item.for}`).join("; ")}`);
  if (result.warnings.length) lines.push(`Warnings: ${result.warnings.join(" ")}`);
  if (result.tips.length) lines.push(`Tips: ${result.tips.join(" ")}`);
  lines.push(`About ${result.grams} g, about US$${result.price}.`);
  return lines.join("\n");
}

/* ------------------------------------------------------- what's on now */

const ago = (at) => {
  const minutes = Math.round((Date.now() - at) / 60000);
  return minutes < 1 ? "just now" : minutes < 60 ? `${minutes} min ago` : minutes < 1440 ? `${Math.round(minutes / 60)} h ago` : `${Math.round(minutes / 1440)} d ago`;
};

/** The benches as they stand, in words (full: with the last steps and readings). */
export function benchNow({ full = true, steps = 8 } = {}) {
  const { chemistry, electronics } = state.bench;
  const lines = [];
  if (chemistry.items.length) {
    lines.push(`Chemistry bench: in the beaker ${chemistry.items.map((item) => `${nameOfChemical(item.id)}${chemUnit(item.id, item.amount)}`).join(", ")}${chemistry.heat ? "; burner on" : ""}${chemistry.flame ? "; flame test" : ""}.`);
    if (chemistry.result) lines.push(full ? describeMix(chemistry.result) : `Last mix: ${chemistry.result.summary}`);
    else lines.push("Not mixed yet.");
  } else lines.push("Chemistry bench: the beaker is clean.");
  if (electronics.parts.length) {
    lines.push(`Electronics bench: on the board ${electronics.parts.map((entry) => `${nameOfPart(entry.id)}${partUnit(entry.id, entry.count)}`).join(", ")}; batteries ${electronics.series ? "in series" : "side by side"}; power ${electronics.powered ? "on" : "off"}.`);
    if (electronics.result && electronics.powered) lines.push(full ? describeCircuit(electronics.result) : `${electronics.result.works ? "It works" : "It doesn't work yet"}: ${electronics.result.parts.map((row) => `${row.name} ${row.state}`).join(", ")}.`);
  } else lines.push("Electronics bench: the board is empty.");
  const log = (state.bench.log || []).slice(-steps);
  if (log.length) lines.push(`Last steps at the benches:\n${log.map((step) => `- ${step.by === "you" ? "The user" : step.by} ${step.text} (${ROOM_NAMES[step.room] || step.room}, ${ago(step.at)})`).join("\n")}`);
  return lines.join("\n");
}

/** True when something is on a bench or the user worked there in the last day. */
export function benchBusy() {
  const { chemistry, electronics, log } = state.bench;
  const last = Array.isArray(log) && log.length ? log.at(-1).at : 0;
  return chemistry.items.length > 0 || electronics.parts.length > 0 || Date.now() - last < 86_400_000;
}

/** Add to what's already on a bench (Jarvis building on the user's work). */
async function addTo(args, by) {
  if (Array.isArray(args.parts) && args.parts.length) {
    const board = state.bench.electronics.parts.map((entry) => ({ ...entry }));
    for (const entry of cleanParts(args.parts)) {
      const same = board.find((item) => item.id === entry.id);
      if (same) same.count = Math.min(50, same.count + entry.count);
      else board.push(entry);
    }
    jarvisWorks("electronics", `adding ${args.parts.map((entry) => nameOfPart(String(entry.id || entry.name || ""))).join(", ")}`);
    const result = await setBoard(board, { powered: true, by });
    return `On the board now: ${board.map((entry) => `${nameOfPart(entry.id)}${partUnit(entry.id, entry.count)}`).join(", ")}.\n${describeCircuit(result)}`;
  }
  if (Array.isArray(args.items) && args.items.length) {
    const adding = cleanItems(args.items);
    const beaker = [...state.bench.chemistry.items, ...adding];
    const step = `added ${adding.map((item) => `${nameOfChemical(item.id)}${chemUnit(item.id, item.amount)}`).join(", ")} to the beaker`;
    return describeMix(await mix(beaker, { heat: state.bench.chemistry.heat, flame: state.bench.chemistry.flame, by, step }));
  }
  throw new Error("Say what to add: parts [{id, count}] for the board, or items [{name, amount}] for the beaker.");
}

/** Take things off a bench (by id or name). */
async function takeFrom(args, by) {
  const wanted = (list) => new Set((Array.isArray(list) ? list : []).map((entry) => String((entry && (entry.id || entry.name)) || entry).trim().toLowerCase()).filter(Boolean));
  // What's on the bench first (its ids and names), the catalogue's guess only after.
  const match = (names, onBench, nameOf, lookUp) =>
    new Set([...names].map((name) => {
      const here = onBench.find((id) => id === name || nameOf(id).toLowerCase() === name) || onBench.find((id) => nameOf(id).toLowerCase().includes(name));
      return here || (lookUp(name) || { id: name }).id;
    }));
  const parts = wanted(args.parts);
  if (parts.size) {
    const ids = match(parts, state.bench.electronics.parts.map((entry) => entry.id), nameOfPart, findPart);
    const board = state.bench.electronics.parts.filter((entry) => !ids.has(entry.id));
    if (board.length === state.bench.electronics.parts.length) return `None of those are on the board. On it: ${state.bench.electronics.parts.map((entry) => nameOfPart(entry.id)).join(", ") || "nothing"}.`;
    jarvisWorks("electronics", "taking parts off the board");
    const result = await setBoard(board, { by });
    return board.length ? `On the board now: ${board.map((entry) => nameOfPart(entry.id)).join(", ")}.${result ? `\n${describeCircuit(result)}` : ""}` : "The board is empty now.";
  }
  const items = wanted(args.items);
  if (items.size) {
    const ids = match(items, state.bench.chemistry.items.map((item) => item.id), nameOfChemical, resolveChemical);
    const beaker = state.bench.chemistry.items.filter((item) => !ids.has(item.id));
    if (beaker.length === state.bench.chemistry.items.length) return `None of those are in the beaker. In it: ${state.bench.chemistry.items.map((item) => nameOfChemical(item.id)).join(", ") || "nothing"}.`;
    jarvisWorks("chemistry", "taking something out of the beaker");
    const gone = state.bench.chemistry.items.filter((item) => ids.has(item.id)).map((item) => nameOfChemical(item.id)).join(", ");
    if (!beaker.length) {
      // An empty beaker starts over, burner off, like Clean the beaker.
      await setBeaker([], { heat: false, flame: false, by });
      return "The beaker is clean now.";
    }
    return describeMix(await mix(beaker, { heat: state.bench.chemistry.heat, flame: state.bench.chemistry.flame, by, step: `took out ${gone}` }));
  }
  throw new Error("Say what to take off: parts [{id}] or items [{name}].");
}

/* ------------------------------------------------------------ blueprints */

function benchData(kind) {
  const { chemistry, electronics } = state.bench;
  const chip = { parts: electronics.parts, series: electronics.series, sun: electronics.sun };
  const mixture = { items: chemistry.items, heat: chemistry.heat, flame: chemistry.flame };
  if (kind === "chip") {
    if (!electronics.parts.length) throw new Error("The electronics bench is empty: build a circuit first.");
    return chip;
  }
  if (kind === "mixture") {
    if (!chemistry.items.length) throw new Error("The beaker is empty: mix something first.");
    return mixture;
  }
  if (!electronics.parts.length && !chemistry.items.length) throw new Error("Both benches are empty: build or mix something first.");
  return { circuit: electronics.parts.length ? chip : null, mix: chemistry.items.length ? mixture : null };
}

function summarise(kind, data) {
  try {
    if (kind === "chip") return describeCircuit(simulateBuild(data.parts, data)).split("\n").slice(0, 2).join(" ");
    if (kind === "mixture") return simulate(data.items, data).summary;
    return [data.circuit ? "A circuit" : "", data.mix ? "a mixture" : ""].filter(Boolean).join(" and ");
  } catch (error) {
    return error.message;
  }
}

function colourOf(kind, data) {
  try {
    if (kind === "mixture") return simulate(data.items, data).vessel.colour;
    const parts = kind === "chip" ? data.parts : data.circuit ? data.circuit.parts : [];
    const led = parts.find((entry) => LED_TINT[entry.id]);
    return led ? LED_TINT[led.id] : "#5fe1ff";
  } catch {
    return "#5fe1ff";
  }
}

/** A blueprint by its id or its exact name (for adding a version: never a guess). */
export function exactBlueprint(idOrName) {
  const wanted = String(idOrName || "").trim().toLowerCase();
  if (!wanted) return null;
  return state.blueprints.find((print) => print.id === wanted || print.name.toLowerCase() === wanted) || null;
}

/** A version's number (older saves kept none: their place in the list). */
export const versionNumber = (print, version) => version.number || print.versions.indexOf(version) + 1;
export const nextVersion = (print) => versionNumber(print, print.versions.at(-1)) + 1;

export function findBlueprint(idOrName) {
  const wanted = String(idOrName || "").trim().toLowerCase();
  if (!wanted) return null;
  return state.blueprints.find((print) => print.id === wanted) || state.blueprints.find((print) => print.name.toLowerCase() === wanted) || state.blueprints.find((print) => print.name.toLowerCase().includes(wanted)) || null;
}

/** Save what's on the benches as a blueprint, or as the next version of one. */
export async function saveBlueprint({ name, kind = "", notes = "", by = "you", onto = "" } = {}) {
  const existing = onto ? exactBlueprint(onto) : null;
  if (onto && !existing) throw new Error(`No blueprint with the id or name ${onto}: the blueprints action lists them (leave id out to save a new one).`);
  const { chemistry, electronics } = state.bench;
  const guess = electronics.parts.length && chemistry.items.length ? "invention" : chemistry.items.length ? "mixture" : "chip";
  const sort = isKind(kind) ? kind : existing ? existing.kind : guess;
  const data = JSON.parse(JSON.stringify(benchData(sort)));
  const version = { at: Date.now(), by, notes: String(notes || "").trim().slice(0, 2000), data, summary: summarise(sort, data) };
  if (existing) {
    if (existing.kind !== sort) throw new Error(`${existing.name} is a ${existing.kind}; save a ${sort} as its own blueprint.`);
    version.number = nextVersion(existing);
    existing.versions.push(version);
    // Past the cap the oldest versions after the first make room; each
    // version keeps its own number, so the numbers never shift.
    if (existing.versions.length > MAX_VERSIONS) existing.versions.splice(1, existing.versions.length - MAX_VERSIONS);
    Object.assign(existing, { updated_at: version.at, summary: version.summary, colour: colourOf(sort, data), notes: version.notes || existing.notes });
    state.blueprints = [existing, ...state.blueprints.filter((print) => print.id !== existing.id)];
  } else {
    if (state.blueprints.length >= MAX_BLUEPRINTS) throw new Error(`The blueprint shelf is full (${MAX_BLUEPRINTS}): delete some first.`);
    const title = String(name || "").trim().slice(0, 60) || `${BLUEPRINT_KINDS[sort]} ${state.blueprints.length + 1}`;
    version.number = 1;
    state.blueprints.unshift({ id: uid(), kind: sort, name: title, notes: version.notes, by, colour: colourOf(sort, data), summary: version.summary, created_at: version.at, updated_at: version.at, versions: [version] });
  }
  const print = existing || state.blueprints[0];
  if (sort !== "mixture") state.bench.from.electronics = print.id;
  if (sort !== "chip") state.bench.from.chemistry = print.id;
  await save.blueprints();
  await keepBench();
  changed("blueprints");
  feed(by === "you" ? "You" : by, `${existing ? `Saved version ${version.number} of` : "Saved the blueprint"} ${print.name}`);
  if (by !== "you") jarvisWorks("blueprints", `filing ${print.name}`);
  return print;
}

/** Put a blueprint (a version of it; the newest by default) back on the benches. */
export async function loadBlueprint(idOrName, { version = 0, by = "you" } = {}) {
  const print = findBlueprint(idOrName);
  if (!print) throw new Error(`No blueprint called ${idOrName}. The blueprints action lists them.`);
  const wanted = Math.trunc(Number(version));
  const chosen = (Number.isFinite(wanted) && wanted >= 1 && print.versions.find((item) => versionNumber(print, item) === wanted)) || print.versions.at(-1);
  const data = chosen.data;
  const chip = print.kind === "chip" ? data : print.kind === "invention" ? data.circuit : null;
  const brew = print.kind === "mixture" ? data : print.kind === "invention" ? data.mix : null;
  if (chip) {
    state.bench.electronics = { parts: chip.parts, series: chip.series, sun: chip.sun, powered: true, result: simulateBuild(chip.parts, chip) };
    state.bench.from.electronics = print.id;
  }
  if (brew) {
    state.bench.chemistry = { items: brew.items, heat: brew.heat, flame: brew.flame, result: simulate(brew.items, brew) };
    state.bench.from.chemistry = print.id;
  }
  if (by !== "you") jarvisWorks(chip ? "electronics" : "chemistry", `loading ${print.name}`);
  logStep(by, chip ? "electronics" : "chemistry", `loaded the blueprint ${print.name} (version ${versionNumber(print, chosen)})`);
  await keepBench();
  return { print, version: versionNumber(print, chosen) };
}

/** Drop a saved chip into the circuit on the board (its parts join the build). */
export async function addChip(idOrName) {
  const print = findBlueprint(idOrName);
  if (!print || print.kind !== "chip") throw new Error("Only a chip can be added to a circuit.");
  const parts = [...state.bench.electronics.parts.map((entry) => ({ ...entry }))];
  for (const entry of print.versions.at(-1).data.parts) {
    const same = parts.find((item) => item.id === entry.id);
    if (same) same.count = Math.min(50, same.count + entry.count);
    else parts.push({ ...entry });
  }
  return setBoard(parts);
}

export async function removeBlueprint(id) {
  state.blueprints = state.blueprints.filter((print) => print.id !== id);
  for (const room of ["chemistry", "electronics"]) if (state.bench.from[room] === id) state.bench.from[room] = "";
  await save.blueprints();
  await keepBench();
  changed("blueprints");
}

export function searchBlueprints(query = "", kind = "") {
  const words = String(query).toLowerCase().split(/\s+/).filter(Boolean);
  return state.blueprints.filter((print) => (!isKind(kind) || print.kind === kind) && words.every((word) => `${print.name} ${print.notes} ${print.summary} ${print.kind}`.toLowerCase().includes(word)));
}

/* ----------------------------------------------------------- the Library */

/** build-your-own-x's topics, with how many tutorials each has. */
export function topics() {
  const counts = new Map();
  for (const [topic] of TUTORIALS) counts.set(topic, (counts.get(topic) || 0) + 1);
  return [...counts].map(([topic, count]) => ({ topic, count }));
}

export function searchTutorials(query = "", topic = "", limit = 40) {
  const words = String(query).toLowerCase().split(/\s+/).filter(Boolean);
  return TUTORIALS.filter(([subject, language, title]) => (!topic || subject === topic) && words.every((word) => `${subject} ${language} ${title}`.toLowerCase().includes(word)))
    .slice(0, limit)
    .map(([subject, language, title, link, video]) => ({ topic: subject, language, title, link, video: video === "video" }));
}

/* -------------------------------------------------- the lab tool (Jarvis) */

/** The Lab's bench actions for the lab tool. Lab work is done in person:
 * whoever calls it walks to the room in the Lab box. */
export async function useWorkshop(args, agent) {
  const by = agent ? agent.name : "you";
  const action = String(args.action || "");
  if (action === "look") {
    jarvisWorks(state.bench.jarvis.room || "electronics", "looking at the benches");
    return benchNow();
  }
  // add with parts or items is the bench; add on its own is the Game kit (js/lab.js).
  if (action === "add" && (Array.isArray(args.parts) || Array.isArray(args.items))) return await addTo(args, by);
  if (action === "remove") return await takeFrom(args, by);
  if (action === "mix") return describeMix(await mix(args.items, { heat: yes(args.heat), flame: yes(args.flame), by }));
  if (action === "shelf") {
    const found = searchChemicals(String(args.query || ""), 25);
    jarvisWorks("chemistry", "checking the shelf");
    return found.length ? found.map((chemical) => `${chemical.id}: ${chemical.name} ${chemical.formula} (${chemical.kind}, ${chemical.state})`).join("\n") : "Nothing on the shelf matches. Any element works by its symbol too (Na, Mg, Cu...).";
  }
  if (action === "circuit") return describeCircuit(await circuit(args.parts, { series: args.series !== false && args.series !== "false", sun: args.sun !== false && args.sun !== "false", by }));
  if (action === "parts") {
    const words = String(args.query || "").toLowerCase().split(/\s+/).filter(Boolean);
    const found = PARTS.filter((part) => words.every((word) => `${part.id} ${part.name} ${part.kind}`.toLowerCase().includes(word)));
    jarvisWorks("electronics", "looking through the parts drawers");
    return found.map((part) => `${part.id}: ${part.name} (${part.kind}${part.volts ? `, ${part.volts} V` : ""}${part.milliamps ? `, ${part.milliamps} mA` : ""})${part.note ? ` ${part.note}` : ""}`).join("\n");
  }
  if (action === "save") {
    const print = await saveBlueprint({ name: args.name, kind: args.kind, notes: args.notes, by, onto: args.id });
    return `Saved ${print.name} (${print.kind}, id ${print.id}, version ${versionNumber(print, print.versions.at(-1))}). ${print.summary}`;
  }
  if (action === "blueprints") {
    const found = searchBlueprints(String(args.query || ""), isKind(args.kind) ? args.kind : "");
    jarvisWorks("blueprints", "reading the blueprints");
    return found.length ? found.slice(0, 20).map((print) => `${print.id}: ${print.name} (${print.kind}, ${print.versions.length} version${print.versions.length === 1 ? "" : "s"}) ${print.summary}${print.notes ? ` Notes: ${print.notes.slice(0, 160)}` : ""}`).join("\n") : "No blueprints saved yet.";
  }
  if (action === "load") {
    const { print, version } = await loadBlueprint(args.id || args.name, { version: Number(args.version) || 0, by });
    const lines = [`Loaded ${print.name} version ${version} (the newest is ${versionNumber(print, print.versions.at(-1))}) onto the bench.`];
    if (state.bench.electronics.result && print.kind !== "mixture") lines.push(describeCircuit(state.bench.electronics.result));
    if (state.bench.chemistry.result && print.kind !== "chip") lines.push(describeMix(state.bench.chemistry.result));
    lines.push("To improve it: change it (mix or circuit), then save with id set to this blueprint's id, which adds a version.");
    return lines.join("\n");
  }
  if (action === "tutorials") {
    const found = searchTutorials(String(args.query || ""), String(args.topic || ""), 15);
    jarvisWorks("library", `reading about ${args.query || args.topic || "building things"}`);
    if (!found.length) return `No tutorial matches. Topics: ${topics().map((row) => row.topic).join(", ")}.`;
    return found.map((row) => `${row.topic} · ${row.language}: ${row.title}${row.video ? " (video)" : ""} ${row.link}`).join("\n");
  }
  return null;
}
