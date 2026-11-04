// The phone's own chemistry and circuit benches: the PC Lab's rules
// (studio/lab/sim.py, formula.py, chemicals.py, tech.py) carried over line
// for line, on the PC's own tables (science-data.js, generated). A test runs
// the same mixes and builds through both and checks they agree, so the phone
// gives the PC's answers without the PC.

import { SCIENCE } from "./science-data.js";

export { SCIENCE };

/* ------------------------------------------------ Python-style formatting */

/** The exact decimal digits of |x| (a double's expansion ends within 100
 *  places for anything the Lab handles), split at the point. */
function exactDigits(x) {
  const [whole, fraction] = Math.abs(x).toFixed(100).split(".");
  return [whole, fraction];
}

/** Round decimal digits (a string of 0-9) to `keep` of them, ties to even.
 *  Returns [the kept digits as a BigInt, whether it carried a digit]. */
function roundDigits(digits, keep) {
  const rest = digits.slice(keep);
  let units = BigInt(digits.slice(0, keep) || "0");
  if (rest[0] > "5" || (rest[0] === "5" && (/[1-9]/.test(rest.slice(1)) || units % 2n === 1n))) units += 1n;
  return units;
}

/** f"{x:.Nf}" exactly like Python (exact value, ties to even, -0.0 kept). */
export function fixed(x, places) {
  if (!Number.isFinite(x)) return Number.isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
  const sign = x < 0 || Object.is(x, -0) ? "-" : "";
  if (Math.abs(x) >= 1e21) return sign + Math.abs(x).toFixed(places);
  const [whole, fraction] = exactDigits(x);
  const text = roundDigits(whole + fraction, whole.length + places).toString().padStart(places + 1, "0");
  return sign + (places ? `${text.slice(0, -places)}.${text.slice(-places)}` : text);
}

/** round(x, n) exactly like Python: on the float's exact decimal value,
 *  ties to even (1.0749999… is 1.07, not 1.08). */
export function round(x, places = 0) {
  if (!Number.isFinite(x) || x === 0 || Math.abs(x) >= 1e21) return x;
  return Number(fixed(x, places));
}

/** f"{x:g}" / f"{x:.Ng}" exactly like Python. */
export function general(x, precision = 6) {
  if (!Number.isFinite(x)) return Number.isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
  const sign = x < 0 || Object.is(x, -0) ? "-" : "";
  if (x === 0) return `${sign}0`;
  let exponent;
  let significant;
  if (Math.abs(x) >= 1e21) {
    exponent = Math.floor(Math.log10(Math.abs(x)));
    significant = BigInt(Math.round(Math.abs(x) / 10 ** (exponent - precision + 1)));
  } else {
    const [whole, fraction] = exactDigits(x);
    const all = (whole + fraction).replace(/^0+/, "");
    const lead = whole === "0" ? -(fraction.length - fraction.replace(/^0+/, "").length) - 1 : whole.length - 1;
    exponent = lead;
    significant = roundDigits(all, precision);
    if (significant.toString().length > precision) {
      significant /= 10n;
      exponent += 1;
    }
  }
  const digits = significant.toString().padStart(precision, "0");
  if (exponent >= -4 && exponent < precision) {
    let text;
    if (exponent >= 0) text = `${digits.slice(0, exponent + 1)}.${digits.slice(exponent + 1)}`;
    else text = `0.${"0".repeat(-exponent - 1)}${digits}`;
    return sign + text.replace(/0+$/, "").replace(/\.$/, "");
  }
  const mantissa = `${digits[0]}.${digits.slice(1)}`.replace(/0+$/, "").replace(/\.$/, "");
  return `${sign}${mantissa}e${exponent < 0 ? "-" : "+"}${String(Math.abs(exponent)).padStart(2, "0")}`;
}

/** str(x) of a Python float: 5.0, 3.3. */
export const floatText = (x) => (Number.isInteger(x) ? x.toFixed(1) : String(x));

const unique = (items) => [...new Set(items)];
const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
const firstWord = (text) => text.trim().split(/\s+/)[0];
const titleCase = (text) => text.toLowerCase().replace(/[a-z]+/g, (word) => word[0].toUpperCase() + word.slice(1));
const gcd = (a, b) => (b ? gcd(b, a % b) : a);
const lcm = (a, b) => (a * b) / gcd(a, b);
const sum = (values) => values.reduce((total, value) => total + value, 0);

/* --------------------------------------------------------------- elements */

export const ELEMENTS = SCIENCE.elements.map(([symbol, name, mass, category, state, number]) => ({ symbol, name, mass, category, state, number }));
const BY_SYMBOL = new Map(ELEMENTS.map((element) => [element.symbol, element]));
const radioactive = (element) => element.number === 43 || element.number === 61 || element.number >= 84;
export const FLAME_COLOURS = SCIENCE.flame_colours;

/* --------------------------------------------------------------- formulas */

export class FormulaError extends Error {}

const SUBSCRIPTS = "₀₁₂₃₄₅₆₇₈₉";

function readNumber(text, position) {
  const found = text.slice(position).match(/^\d+(?:\.\d+)?/);
  if (!found) return [1, position];
  return [parseFloat(found[0]), position + found[0].length];
}

const addTo = (map, key, amount) => map.set(key, (map.get(key) || 0) + amount);

function group(text) {
  const stack = [new Map()];
  let position = 0;
  while (position < text.length) {
    const char = text[position];
    if (char === "(" || char === "[") {
      stack.push(new Map());
      position += 1;
      continue;
    }
    if (char === ")" || char === "]") {
      if (stack.length === 1) throw new FormulaError(`A bracket closes with none open in '${text}'.`);
      const inner = stack.pop();
      position += 1;
      const [count, next] = readNumber(text, position);
      position = next;
      for (const [symbol, amount] of inner) addTo(stack.at(-1), symbol, amount * count);
      continue;
    }
    const found = text.slice(position).match(/^[A-Z][a-z]?/);
    if (!found) throw new FormulaError(`Can't read '${text.slice(position)}' in '${text}'.`);
    let symbol = found[0];
    if (!BY_SYMBOL.has(symbol)) {
      if (BY_SYMBOL.has(symbol[0]) && symbol.length === 2) symbol = symbol[0];
      else throw new FormulaError(`${symbol} isn't an element.`);
    }
    position += symbol.length;
    const [count, next] = readNumber(text, position);
    position = next;
    addTo(stack.at(-1), symbol, count);
  }
  if (stack.length !== 1) throw new FormulaError(`A bracket is left open in '${text}'.`);
  return stack[0];
}

/** Element counts, e.g. 'CuSO4·5H2O' → Cu 1, S 1, O 9, H 10. */
export function parseFormula(formula) {
  const text = [...formula].map((char) => (SUBSCRIPTS.includes(char) ? String(SUBSCRIPTS.indexOf(char)) : char)).join("").replaceAll(" ", "");
  if (!text) throw new FormulaError("An empty formula.");
  const total = new Map();
  for (let part of text.split(/[·.*+]/)) {
    if (!part) continue;
    let multiplier = 1;
    const found = part.match(/^(\d+(?:\.\d+)?)(.*)$/s);
    if (found) {
      multiplier = parseFloat(found[1]);
      part = found[2];
    }
    for (const [symbol, count] of group(part)) addTo(total, symbol, count * multiplier);
  }
  for (const [symbol, count] of total) total.set(symbol, Number.isInteger(count) ? count : round(count, 3));
  return total;
}

/** Grams per mole. */
export function molarMass(formula) {
  let total = 0;
  for (const [symbol, count] of parseFormula(formula)) total += BY_SYMBOL.get(symbol).mass * count;
  return round(total, 3);
}

/** Subscript digits for display: H2SO4 → H₂SO₄ (not leading multipliers). */
export function pretty(formula) {
  let out = "";
  let previous = "";
  for (const char of formula) {
    const next = /[0-9]/.test(char) && previous && (/\p{L}/u.test(previous) || ")]".includes(previous) || SUBSCRIPTS.includes(previous)) ? SUBSCRIPTS[Number(char)] : char;
    out += next;
    previous = next;
  }
  return out;
}

const SINGLE = new Set(["NH4+", "NO3-", "MnO4-", "HCO3-", "OCl-", "CH3COO-"]);
const SUPERSCRIPT = { 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹", "+": "⁺", "-": "⁻" };

/** 'SO42-' → ['SO4', -2]; 'NH4+' → ['NH4', 1]. */
export function ionCharge(ion) {
  const sign = ion.endsWith("+") ? 1 : -1;
  const body = ion.slice(0, -1);
  if (SINGLE.has(ion) || !/[0-9]$/.test(body) || body.endsWith(")")) return [body, sign];
  const found = body.match(/^(.*?[A-Za-z)\]])(\d)$/s);
  if (found && /[A-Za-z)\]]$/.test(found[1])) return [found[1], sign * Number(found[2])];
  return [body, sign];
}

export function ionPretty(ion) {
  const [body, charge] = ionCharge(ion);
  const size = Math.abs(charge) === 1 ? "" : String(Math.abs(charge));
  return pretty(body) + [...(size + (charge > 0 ? "+" : "-"))].map((char) => SUPERSCRIPT[char]).join("");
}

function hex(colour) {
  let value = colour.replace(/^#+/, "");
  if (value.length === 3) value = [...value].map((char) => char + char).join("");
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)];
}

/** Mix tints by weight: the colour and how opaque the mix looks. */
export function blend(colours) {
  const weighted = colours.filter(([, weight]) => weight > 0);
  if (!weighted.length) return ["#e3f2ff", 0.12];
  const total = sum(weighted.map(([, weight]) => weight));
  const channels = [0, 1, 2].map((index) => round(sum(weighted.map(([rgb, weight]) => hex(rgb)[index] * weight)) / total));
  const opacity = Math.min(0.95, 0.12 + total);
  return [`#${channels.map((value) => value.toString(16).padStart(2, "0")).join("")}`, round(opacity, 2)];
}

/* ---------------------------------------------------------- the chemicals */

export const HAZARDS = SCIENCE.hazards;

function shelfChemical(row) {
  return { ...row, tags: new Set(row.tags), molarMass: row.molar_mass };
}

export const CHEMICALS = SCIENCE.chemicals.map(shelfChemical);
const CHEMICAL_BY_ID = new Map(CHEMICALS.map((chemical) => [chemical.id, chemical]));

function exactChemical(text) {
  const wanted = text.trim().toLowerCase();
  if (!wanted) return null;
  if (CHEMICAL_BY_ID.has(wanted)) return CHEMICAL_BY_ID.get(wanted);
  for (const chemical of CHEMICALS) {
    const names = new Set([chemical.name.toLowerCase(), chemical.formula.toLowerCase(), ...chemical.aliases]);
    const base = chemical.name.toLowerCase().split(" (")[0];
    if (names.has(wanted) || wanted === base) return chemical;
  }
  return null;
}

function partialChemical(text) {
  const wanted = text.trim().toLowerCase();
  if (wanted.length < 3) return null;
  for (const chemical of CHEMICALS) {
    if (chemical.name.toLowerCase().includes(wanted) || chemical.aliases.some((alias) => alias.includes(wanted))) return chemical;
  }
  return null;
}

/** A shelf chemical by id, name, formula, or everyday name. */
export const findChemical = (text) => exactChemical(text) || partialChemical(text);

/** Shelf chemicals whose names, formulas, or kinds contain the words. */
export function searchChemicals(text, limit = 40) {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return CHEMICALS.slice(0, limit);
  return CHEMICALS.filter((chemical) => {
    const haystack = [chemical.name, chemical.formula, chemical.kind, ...chemical.aliases, ...chemical.roles].join(" ").toLowerCase();
    return words.every((word) => haystack.includes(word));
  }).slice(0, limit);
}

const ACTIVE = new Set(SCIENCE.active);

/** Any element as a pure substance, for the ones the shelf lacks. */
export function elementChemical(symbol) {
  const element = BY_SYMBOL.get(symbol);
  if (!element) return null;
  for (const chemical of CHEMICALS) {
    if (chemical.formula === symbol && (chemical.kind === "metal" || chemical.kind === "element")) return chemical;
  }
  const tags = new Set();
  const hazards = [];
  if (element.category === "alkali-metal" || ["Ca", "Sr", "Ba"].includes(symbol)) {
    tags.add("very-active-metal");
    hazards.push("reactive-water", "flammable");
  } else if (ACTIVE.has(symbol)) tags.add("active-metal");
  if (element.category === "halogen") hazards.push(...(["F", "Cl", "Br"].includes(symbol) ? ["toxic", "oxidizer"] : ["harmful"]));
  if (symbol === "I") tags.add("iodine");
  if (["P", "S", "C"].includes(symbol)) {
    tags.add("fuel");
    hazards.push("flammable");
  }
  if (["As", "Hg", "Cd", "Tl", "Be", "Pb"].includes(symbol)) hazards.push("toxic");
  if (radioactive(element)) hazards.push("radioactive");
  let formula = { H: "H2", N: "N2", O: "O2", F: "F2", Cl: "Cl2" }[symbol] || symbol;
  if (symbol === "Br" || symbol === "I") formula = `${symbol}2`;
  if (element.state === "solid") tags.add("insoluble");
  let molar = 0;
  try {
    molar = molarMass(formula);
  } catch (error) {
    if (!(error instanceof FormulaError)) throw error;
  }
  return {
    id: `element-${symbol.toLowerCase()}`,
    name: element.name,
    formula,
    kind: element.category.includes("metal") || ["transition", "post-transition", "lanthanide", "actinide"].includes(element.category) ? "metal" : "element",
    state: element.state !== "unknown" ? element.state : "solid",
    colour: SCIENCE.halogen_colours[symbol] || SCIENCE.element_colours[element.category] || "#cccccc",
    concentration: 0,
    ions: [],
    acid: null,
    base: null,
    density: 1,
    hazards: unique(hazards),
    roles: [],
    aliases: [symbol.toLowerCase()],
    dissolve_heat: 0,
    tags,
    note: `Pure ${element.name.toLowerCase()} (element ${element.number}).`,
    molarMass: molar,
  };
}

/** A shelf chemical, or any pure element by symbol or name. */
export function resolveChemical(text) {
  let wanted = text.trim();
  if (CHEMICAL_BY_ID.has(wanted.toLowerCase())) return CHEMICAL_BY_ID.get(wanted.toLowerCase());
  if (wanted.toLowerCase().startsWith("element-")) wanted = titleCase(wanted.slice("element-".length));
  if (BY_SYMBOL.has(wanted)) return elementChemical(wanted);
  const found = exactChemical(wanted);
  if (found) return found;
  for (const element of ELEMENTS) if (wanted.toLowerCase() === element.name.toLowerCase()) return elementChemical(element.symbol);
  return partialChemical(wanted);
}

/* ------------------------------------------------------------ the mixing */

const ROOM_C = 20.0;
const GAS_ML_PER_MOL = 24_000;
const DEFAULT_ML = 20.0;
const DEFAULT_G = 2.0;
export const MAX_ITEMS = 12;
export const MAX_AMOUNT = 2_000.0;
const SOLUBILITY = SCIENCE.solubility;
const ION_COLOURS = SCIENCE.ion_colours;
const PRECIPITATES = SCIENCE.precipitates;
const METALS = SCIENCE.metals;
const ACTIVITY = SCIENCE.activity;
const METAL_ION_NAMES = SCIENCE.metal_ion_names;

export class LabError extends Error {}

class Portion {
  constructor(chemical, amount, unit) {
    Object.assign(this, { chemical, amount, unit });
  }
  get grams() {
    return this.unit === "g" ? this.amount : this.amount * this.chemical.density;
  }
  get moles() {
    if (this.chemical.state === "solution") return (this.chemical.concentration * this.amount) / 1000;
    const mass = this.chemical.molarMass;
    return mass ? this.grams / mass : 0;
  }
  get waterMl() {
    const chemical = this.chemical;
    if (chemical.id === "water" || chemical.state === "solution") return this.amount;
    if (chemical.state === "liquid" && ["mixture", "household", "indicator"].includes(chemical.kind)) return this.amount * 0.9;
    if (chemical.id === "aloe-vera" || chemical.id === "milk") return this.amount * 0.9;
    return 0;
  }
}

const sameEntry = (a, b) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((key) => a[key] === b[key]);

class Mix {
  constructor(heat, flame) {
    this.portions = [];
    this.heat = heat;
    this.flame = flame;
    this.ions = new Map();
    this.h = 0;
    this.oh = 0;
    this.weakAcids = [];
    this.weakBases = [];
    this.solids = new Map();
    this.heatKj = 0;
    this.reactions = [];
    this.observations = [];
    this.hazards = [];
    this.products = new Map();
    this.precipitates = [];
    this.gases = new Map();
    this.tints = [];
    this.colourSteps = [];
    this.foam = 0;
    this.special = new Set();
    this.unknown = [];
  }
  get waterMl() {
    return sum(this.portions.map((portion) => portion.waterMl));
  }
  get litres() {
    return Math.max(this.waterMl, 1) / 1000;
  }
  get wet() {
    return this.waterMl > 0.5;
  }
  ion(name) {
    return this.ions.get(name) || 0;
  }
  addIon(name, amount) {
    this.ions.set(name, this.ion(name) + amount);
  }
  tagged(tag) {
    return this.portions.filter((portion) => portion.chemical.tags.has(tag));
  }
  has(...ids) {
    return this.portions.some((portion) => ids.includes(portion.chemical.id));
  }
  react(equation, kind, note = "") {
    const entry = { equation, kind, note };
    if (!this.reactions.some((known) => sameEntry(known, entry))) this.reactions.push(entry);
  }
  see(text) {
    if (!this.observations.includes(text)) this.observations.push(text);
  }
  warn(level, text) {
    const entry = { level, text };
    if (!this.hazards.some((known) => sameEntry(known, entry))) this.hazards.push(entry);
  }
  make(formula, name, moles, state) {
    if (moles <= 0) return;
    if (!this.products.has(formula)) this.products.set(formula, { formula, name, moles: 0, state });
    this.products.get(formula).moles += moles;
  }
  gas(formula, name, moles, colour) {
    if (moles <= 0) return;
    if (!this.gases.has(formula)) this.gases.set(formula, { formula, name, moles: 0, colour });
    this.gases.get(formula).moles += moles;
    this.make(formula, name, moles, "gas");
  }
}

const hasAcid = (chemical) => Boolean(chemical.acid);
const solidOf = (chemical, grams) => ({ name: chemical.name, colour: chemical.colour, grams, formula: chemical.formula });

/** What happens when these go in one beaker (and are heated, or flamed). */
export function simulate(items, { heat = false, flame = false } = {}) {
  if (!items.length) throw new LabError("Add something to the beaker first.");
  if (items.length > MAX_ITEMS) throw new LabError(`The beaker holds up to ${MAX_ITEMS} things at once.`);
  const mix = new Mix(heat, flame);
  for (const item of items) {
    const wanted = String(item.id || item.name || "").trim();
    const chemical = resolveChemical(wanted);
    if (!chemical) {
      mix.unknown.push(wanted);
      continue;
    }
    const solid = chemical.state === "solid";
    const raw = item.amount;
    const amount = typeof raw === "number" ? raw : solid ? DEFAULT_G : DEFAULT_ML;
    if (!(amount > 0 && amount <= MAX_AMOUNT)) throw new LabError(`Use between 0 and ${general(MAX_AMOUNT)} of ${chemical.name}.`);
    mix.portions.push(new Portion(chemical, amount, solid ? "g" : "mL"));
  }
  if (!mix.portions.length) return result(mix);
  dissolve(mix);
  veryActiveMetals(mix);
  carbonates(mix);
  metalsInAcid(mix);
  neutralise(mix);
  displacement(mix);
  complexes(mix);
  precipitate(mix);
  redox(mix);
  organics(mix);
  safety(mix);
  heating(mix);
  return result(mix);
}

function dissolve(mix) {
  for (const portion of mix.portions) {
    const chemical = portion.chemical;
    let moles = portion.moles;
    if (chemical.tags.has("insoluble") || chemical.kind === "metal" || chemical.kind === "oil") {
      if (chemical.state === "solid") mix.solids.set(chemical.id, solidOf(chemical, portion.grams));
      continue;
    }
    if (chemical.state === "solid") {
      if (!mix.wet) {
        mix.solids.set(chemical.id, solidOf(chemical, portion.grams));
        continue;
      }
      const limit = SOLUBILITY[chemical.formula];
      const acidEatsIt = chemical.tags.has("carbonate") && mix.portions.some((other) => hasAcid(other.chemical));
      if (limit !== undefined) {
        let fits = (limit * mix.waterMl) / 100;
        if (acidEatsIt && portion.moles) {
          const acid = sum(mix.portions.filter((other) => hasAcid(other.chemical)).map((other) => other.moles));
          fits += (acid * portion.grams) / portion.moles;
        }
        if (portion.grams > fits * 1.02) {
          const left = portion.grams - fits;
          mix.see(`Only ${general(fits, 3)} g of ${chemical.name.toLowerCase()} ${acidEatsIt ? "reacts or dissolves" : "dissolves"} in ${fixed(mix.waterMl, 0)} mL: the water is saturated and ${general(left, 3)} g sits on the bottom.`);
          mix.solids.set(chemical.id, solidOf(chemical, left));
          moles *= fits / portion.grams;
        }
      }
      if (chemical.dissolve_heat) {
        mix.heatKj += chemical.dissolve_heat * moles;
        mix.see(`The ${chemical.name.toLowerCase()} ${chemical.dissolve_heat > 0 ? "warms" : "cools"} the water as it dissolves.`);
      } else if ((chemical.kind === "salt" || chemical.kind === "sugar") && moles) mix.see(`The ${chemical.name.toLowerCase()} dissolves.`);
    }
    for (const [ion, count] of chemical.ions) if (ion !== "H+" && ion !== "OH-") mix.addIon(ion, moles * count);
    if (chemical.acid) {
      const [strength, pka, protons] = chemical.acid;
      if (strength === "strong") mix.h += moles * protons;
      else mix.weakAcids.push({ pka, left: moles * protons, conj: 0 });
    }
    if (chemical.base && !chemical.tags.has("carbonate")) {
      const [strength, pkb, hydroxides] = chemical.base;
      if (strength === "strong") mix.oh += moles * hydroxides;
      else mix.weakBases.push({ pkb, left: moles * hydroxides, conj: 0 });
    }
    if (chemical.id === "copper-sulfate-crystals") mix.special.add("hydrated-blue");
  }
}

function veryActiveMetals(mix) {
  for (const portion of mix.tagged("very-active-metal")) {
    const symbol = portion.chemical.formula;
    if (!(symbol in METALS) || !(mix.wet || mix.h)) continue;
    const [ion, electrons, heat] = METALS[symbol];
    const moles = portion.moles;
    mix.solids.delete(portion.chemical.id);
    mix.addIon(ion, moles);
    const fromAcid = Math.min(mix.h, moles * electrons);
    mix.h -= fromAcid;
    mix.oh += moles * electrons - fromAcid;
    mix.heatKj += heat * moles;
    mix.gas("H2", "hydrogen", (moles * electrons) / 2, "#ffffff");
    const name = firstWord(portion.chemical.name).toLowerCase();
    if (electrons === 1) mix.react(`2${symbol}(s) + 2H₂O(l) → 2${ionPretty(ion)}(aq) + 2OH⁻(aq) + H₂↑`, "metal + water");
    else mix.react(`${symbol}(s) + 2H₂O(l) → ${ionPretty(ion)}(aq) + 2OH⁻(aq) + H₂↑`, "metal + water");
    mix.special.add("violent");
    if (symbol === "K") mix.see("The potassium whizzes round, bursts into a lilac flame and pops.");
    else if (symbol === "Na") mix.see("The sodium melts into a silvery ball, fizzes and skates across the water.");
    else if (symbol === "Li") mix.see("The lithium fizzes steadily and floats.");
    else mix.see(`The ${name} sinks and bubbles steadily; the water turns cloudy.`);
    mix.warn("danger", `${portion.chemical.name} reacts violently with water: hydrogen can ignite and hot lye spits. Only tiny pieces, behind a shield, by a teacher.`);
  }
}

/** Use up to `wanted` moles of H+, strong acid first. Returns [got, weak]. */
function takeAcid(mix, wanted) {
  let got = Math.min(mix.h, wanted);
  mix.h -= got;
  let weak = false;
  for (const acid of [...mix.weakAcids].sort((a, b) => a.pka - b.pka)) {
    if (got >= wanted - 1e-12) break;
    const take = Math.min(acid.left, wanted - got);
    if (take > 0) {
      acid.left -= take;
      acid.conj += take;
      got += take;
      weak = true;
    }
  }
  return [got, weak];
}

function carbonates(mix) {
  for (const portion of mix.tagged("carbonate")) {
    const formula = portion.chemical.formula;
    const moles = portion.moles;
    const [per, anion] = formula.includes("HCO3") ? [1, "HCO3-"] : [2, "CO32-"];
    const acidLeft = mix.h + sum(mix.weakAcids.map((acid) => acid.left));
    if (acidLeft <= 0) continue;
    const [reactedH] = takeAcid(mix, moles * per);
    const reacted = reactedH / per;
    if (reacted <= 0) continue;
    if (mix.ions.has(anion)) mix.ions.set(anion, Math.max(0, mix.ion(anion) - reacted));
    if (formula === "CaCO3") {
      mix.addIon("Ca2+", reacted);
      const solid = mix.solids.get(portion.chemical.id);
      if (solid) {
        solid.grams = Math.max(0, solid.grams - reacted * molarMass("CaCO3"));
        if (solid.grams < 0.01) {
          mix.solids.delete(portion.chemical.id);
          mix.see("The chalk fizzes away until it has all dissolved.");
        } else mix.see("The chalk fizzes and gets smaller.");
      }
      mix.react("CaCO₃(s) + 2H⁺(aq) → Ca²⁺(aq) + CO₂↑ + H₂O(l)", "acid + carbonate");
      mix.heatKj += 15 * reacted;
    } else if (per === 1) {
      mix.react("HCO₃⁻(aq) + H⁺(aq) → CO₂↑ + H₂O(l)", "acid + carbonate");
      mix.heatKj -= 11.8 * reacted;
      mix.see("It fizzes up at once, and the beaker feels a little colder.");
    } else {
      mix.react("CO₃²⁻(aq) + 2H⁺(aq) → CO₂↑ + H₂O(l)", "acid + carbonate");
      mix.heatKj += 27 * reacted;
    }
    mix.gas("CO2", "carbon dioxide", reacted, "#ffffff");
    mix.make("H2O", "water", reacted, "liquid");
  }
}

function metalsInAcid(mix) {
  for (const portion of mix.portions) {
    const chemical = portion.chemical;
    const symbol = chemical.formula;
    if (chemical.kind !== "metal" || chemical.tags.has("very-active-metal")) continue;
    if (symbol === "Cu" && mix.ion("NO3-") && mix.h > 0) {
      const used = Math.min(portion.moles, (mix.h * 3) / 8);
      mix.h -= (used * 8) / 3;
      mix.addIon("Cu2+", used);
      mix.gas("NO", "nitrogen monoxide (turns brown NO₂ in air)", (used * 2) / 3, "#b5651d");
      mix.react("3Cu(s) + 8H⁺ + 2NO₃⁻ → 3Cu²⁺ + 2NO↑ + 4H₂O", "metal + nitric acid", "Nitric acid is an oxidiser: it dissolves copper, which other acids can't.");
      mix.see("The copper dissolves, the liquid turns blue and brown fumes rise.");
      mix.warn("danger", "Nitrogen dioxide fumes are toxic: fume cupboard only.");
      shrink(mix, portion, used);
      continue;
    }
    if (!chemical.tags.has("active-metal") || !(symbol in METALS)) {
      if (chemical.kind === "metal" && (mix.h > 0 || mix.weakAcids.length) && ["Cu", "Ag", "Au"].includes(symbol)) {
        mix.see(`The ${firstWord(chemical.name).toLowerCase()} doesn't react: it is below hydrogen in the reactivity series.`);
      }
      continue;
    }
    const [ion, electrons, heat] = METALS[symbol];
    if (mix.h <= 0 && !mix.weakAcids.some((acid) => acid.left > 0)) continue;
    const [got, weak] = takeAcid(mix, portion.moles * electrons);
    const used = got / electrons;
    if (used <= 0) continue;
    mix.addIon(ion, used);
    mix.heatKj += heat * used;
    mix.gas("H2", "hydrogen", got / 2, "#ffffff");
    mix.react(
      { 1: `2${symbol}(s) + 2H⁺ → 2${ionPretty(ion)} + H₂↑`, 2: `${symbol}(s) + 2H⁺ → ${ionPretty(ion)} + H₂↑`, 3: `2${symbol}(s) + 6H⁺ → 2${ionPretty(ion)} + 3H₂↑` }[electrons],
      "metal + acid",
    );
    const speed = weak || ["Fe", "Sn", "Ni", "Pb"].includes(symbol) ? "slowly" : "quickly";
    if (symbol === "Al" && !weak) mix.see("The aluminium waits a moment (its oxide skin) and then fizzes hard.");
    else mix.see(`The ${firstWord(chemical.name).toLowerCase()} fizzes ${speed}, giving off hydrogen.`);
    if (symbol === "Fe") mix.see("The liquid turns pale green (iron(II) ions).");
    shrink(mix, portion, used);
  }
}

function shrink(mix, portion, used) {
  const solid = mix.solids.get(portion.chemical.id);
  if (!solid) return;
  const grams = solid.grams - used * portion.chemical.molarMass;
  if (grams < 0.005) {
    mix.solids.delete(portion.chemical.id);
    mix.see(`The ${firstWord(portion.chemical.name).toLowerCase()} is used up completely.`);
  } else solid.grams = grams;
}

function neutralise(mix) {
  const both = Math.min(mix.h, mix.oh);
  if (both > 0) {
    mix.h -= both;
    mix.oh -= both;
    mix.heatKj += 57.3 * both;
    mix.make("H2O", "water", both, "liquid");
    mix.react("H⁺(aq) + OH⁻(aq) → H₂O(l)", "neutralisation", "Acid and alkali cancel out into water and a salt.");
  }
  if (mix.oh > 0) {
    for (const acid of mix.weakAcids) {
      const take = Math.min(acid.left, mix.oh);
      if (take > 0) {
        acid.left -= take;
        acid.conj += take;
        mix.oh -= take;
        mix.heatKj += 55.0 * take;
        mix.make("H2O", "water", take, "liquid");
        mix.react("HA(aq) + OH⁻(aq) → A⁻(aq) + H₂O(l)", "neutralisation", "A weak acid is neutralised.");
      }
    }
  }
  if (mix.h > 0) {
    for (const base of mix.weakBases) {
      const take = Math.min(base.left, mix.h);
      if (take > 0) {
        base.left -= take;
        base.conj += take;
        mix.h -= take;
        mix.heatKj += 52.0 * take;
        mix.react("B(aq) + H⁺(aq) → BH⁺(aq)", "neutralisation", "A weak base is neutralised.");
      }
    }
  }
  if (mix.weakBases.length && mix.weakAcids.length) {
    for (const base of mix.weakBases) {
      for (const acid of mix.weakAcids) {
        const take = Math.min(base.left, acid.left);
        if (take > 0) {
          base.left -= take;
          acid.left -= take;
          base.conj += take;
          acid.conj += take;
          mix.heatKj += 50.0 * take;
        }
      }
    }
  }
}

const times = (count) => (count === 1 ? "" : String(count));

function displacement(mix) {
  for (const portion of mix.portions) {
    const symbol = portion.chemical.formula;
    if (portion.chemical.kind !== "metal" || !ACTIVITY.includes(symbol)) continue;
    if (!mix.solids.has(portion.chemical.id) || portion.chemical.tags.has("very-active-metal")) continue;
    const rank = ACTIVITY.indexOf(symbol);
    const [ownIon, ownE] = METALS[symbol];
    for (const [ion, [metal, name, colour]] of Object.entries(METAL_ION_NAMES)) {
      if (!ACTIVITY.includes(metal) || ACTIVITY.indexOf(metal) <= rank) continue;
      const present = mix.ion(ion);
      if (present <= 1e-9) continue;
      const ionE = METALS[metal][1];
      const solid = mix.solids.get(portion.chemical.id);
      if (!solid) break;
      const have = solid.grams / portion.chemical.molarMass;
      const used = Math.min(have, (present * ionE) / ownE);
      const freed = (used * ownE) / ionE;
      mix.addIon(ion, -freed);
      mix.addIon(ownIon, used);
      shrink(mix, portion, used);
      mix.solids.set(`deposit-${metal}`, { name: `${name} metal`, colour, grams: freed * molarMass(metal), formula: metal });
      mix.make(metal, name, freed, "solid");
      mix.heatKj += 30 * used;
      const common = lcm(ownE, ionE);
      const ours = common / ownE;
      const theirs = common / ionE;
      mix.react(
        `${times(ours)}${symbol}(s) + ${times(theirs)}${ionPretty(ion)}(aq) → ${times(ours)}${ionPretty(ownIon)}(aq) + ${times(theirs)}${metal}(s)`,
        "displacement",
        `${firstWord(portion.chemical.name)} is more reactive than ${name}, so it pushes ${name} out.`,
      );
      if (metal === "Ag") mix.see("Shiny silver crystals grow on the metal like a tree, and the liquid turns blue.");
      else if (metal === "Cu") mix.see("A pink-brown coat of copper forms on the metal and the blue colour fades.");
      else mix.see(`A coat of ${name} forms on the ${firstWord(portion.chemical.name).toLowerCase()}.`);
    }
  }
}

function complexes(mix) {
  const ammonia = sum(mix.tagged("ammonia").map((portion) => portion.moles));
  const copper = mix.ion("Cu2+");
  if (ammonia && copper && ammonia >= 4 * copper) {
    mix.ions.set("Cu2+", 0);
    mix.addIon("Cu(NH3)42+", copper);
    mix.react("Cu²⁺(aq) + 4NH₃(aq) → [Cu(NH₃)₄]²⁺(aq)", "complex", "A pale blue precipitate forms first, then dissolves in more ammonia.");
    mix.see("A pale blue cloud forms, then dissolves into a deep royal-blue liquid.");
    mix.colourSteps = ["#6fb7ff", "#1036d6"];
  }
}

function precipitate(mix) {
  if (!mix.wet) return;
  mix.ions.set("OH-", mix.oh);
  for (const [cation, perC, anion, perA, formula, name, colour] of PRECIPITATES) {
    const moles = Math.min(mix.ion(cation) / perC, mix.ion(anion) / perA);
    if (moles <= 1e-7) continue;
    mix.addIon(cation, -moles * perC);
    mix.addIon(anion, -moles * perA);
    const grams = moles * molarMass(formula);
    mix.precipitates.push({ formula, name, colour, grams: round(grams, 4) });
    mix.make(formula, name, moles, "solid");
    const left = `${perC > 1 ? perC : ""}${ionPretty(cation)}(aq)`;
    const right = `${perA > 1 ? perA : ""}${ionPretty(anion)}(aq)`;
    mix.react(`${left} + ${right} → ${pretty(formula)}(s)`, "precipitation", `${capitalize(name)} doesn't dissolve in water.`);
    if (formula === "PbI2") mix.see("A brilliant yellow cloud of lead iodide swirls through the liquid ('golden rain').");
    else mix.see(`A ${colourWord(colour)} precipitate of ${name} forms and slowly settles.`);
  }
  mix.oh = mix.ion("OH-");
  mix.ions.delete("OH-");
  for (const entry of mix.precipitates) {
    if ((entry.formula === "Zn(OH)2" || entry.formula === "Al(OH)3") && mix.oh > (4 * entry.grams) / molarMass(entry.formula)) {
      entry.redissolved = true;
      mix.see(`With more alkali the white ${entry.name} dissolves again (it is amphoteric).`);
    }
  }
  mix.precipitates = mix.precipitates.filter((entry) => !entry.redissolved);
  const soap = mix.has("sodium-stearate");
  const hard = mix.ion("Ca2+") + mix.ion("Mg2+");
  if (soap && hard > 1e-5) {
    mix.precipitates.push({ formula: "Ca(C18H35O2)2", name: "soap scum", colour: "#f3efe2", grams: round(hard * 606, 3) });
    mix.react("2C₁₇H₃₅COO⁻ + Ca²⁺ → Ca(C₁₇H₃₅COO)₂(s)", "precipitation", "Hard-water ions turn soap into scum.");
    mix.see("Grey-white scum forms instead of lather: the water is hard.");
  }
}

function colourWord(colour) {
  const [red, green, blue] = hex(colour);
  if (Math.max(red, green, blue) < 60) return "black";
  if (Math.min(red, green, blue) > 225) return "white";
  if (red > 200 && green > 180 && blue < 140) return "yellow";
  if (red > 150 && green < 110 && blue < 80) return red < 200 ? "brick-red" : "orange-red";
  if (blue > red && blue > green) return "blue";
  if (green > red && green > blue) return "green";
  if (red > green && green > blue) return red < 190 ? "rust-brown" : "cream";
  if (red > blue && blue > green) return "pink";
  return "coloured";
}

function redox(mix) {
  const peroxide = mix.tagged("peroxide");
  const catalysts = mix.tagged("peroxide-catalyst");
  const surfactant = mix.tagged("surfactant").length > 0;
  const reducers = mix.tagged("reducer");
  const bleach = mix.tagged("hypochlorite");
  const iodide = mix.ion("I-");
  const acidic = mix.h > 0 || mix.weakAcids.some((acid) => acid.left > 0);
  if (peroxide.length && (catalysts.length || iodide || mix.heat || bleach.length)) {
    const moles = sum(peroxide.map((portion) => portion.moles));
    mix.gas("O2", "oxygen", moles / 2, "#ffffff");
    mix.make("H2O", "water", moles, "liquid");
    mix.heatKj += 98 * moles;
    const catalyst = catalysts.length ? catalysts[0].chemical.name.split(" (")[0].toLowerCase() : "heat";
    mix.react("2H₂O₂(aq) → 2H₂O(l) + O₂↑", "decomposition", `The ${catalyst} speeds up the splitting of hydrogen peroxide.`);
    if (surfactant) {
      mix.foam = 1.0;
      mix.special.add("elephant-toothpaste");
      mix.see("A huge column of foam erupts out of the beaker ('elephant toothpaste'), steaming warm.");
    } else mix.see("It fizzes hard, releasing oxygen: a glowing splint would relight.");
    if (iodide) {
      mix.tints.push(["#c6862a", 0.25]);
      mix.see("The foam is tinted yellow-brown by a little iodine.");
    }
    if (moles > 0.05) mix.warn("warning", "Strong peroxide decomposes fast and hot: stand back.");
  }
  if (bleach.length) {
    if (mix.h > 0 || acidic) {
      mix.gas("Cl2", "chlorine", sum(bleach.map((portion) => portion.moles)) * 0.5, "#c8e05a");
      mix.react("OCl⁻ + Cl⁻ + 2H⁺ → Cl₂↑ + H₂O", "redox");
      mix.warn("danger", "Bleach + acid releases toxic chlorine gas. Never mix them.");
      mix.see("A sharp-smelling yellow-green gas comes off.");
    }
    if (mix.tagged("ammonia").length) {
      mix.gas("NH2Cl", "chloramine", sum(bleach.map((portion) => portion.moles)) * 0.5, "#e8f4ff");
      mix.react("NH₃ + OCl⁻ → NH₂Cl + OH⁻", "redox");
      mix.warn("danger", "Bleach + ammonia makes toxic chloramine gas. Never mix them.");
    }
    if (mix.has("ethanol", "acetone", "isopropanol")) {
      mix.warn("danger", "Bleach + alcohol or acetone can make chloroform and other toxic chemicals.");
      mix.react("C₃H₆O + 3OCl⁻ → CHCl₃ + CH₃COO⁻ + 2OH⁻", "haloform");
    }
    if (iodide) {
      mix.tints.push(["#8a4b0f", 0.5]);
      mix.special.add("iodine");
      mix.react("OCl⁻ + 2I⁻ + H₂O → I₂ + Cl⁻ + 2OH⁻", "redox");
    }
    if (mix.portions.some((portion) => portion.chemical.kind === "indicator" || (portion.chemical.roles.length === 1 && portion.chemical.roles[0] === "colour"))) {
      mix.special.add("bleached");
      mix.see("The colour fades away: bleach destroys dyes.");
    }
  }
  if (iodide && peroxide.length && acidic) {
    mix.special.add("iodine");
    mix.react("H₂O₂ + 2I⁻ + 2H⁺ → I₂ + 2H₂O", "redox");
    mix.see("The liquid slowly turns yellow, then brown, as iodine forms.");
  }
  if (mix.tagged("iodine").length) mix.special.add("iodine");
  if (mix.special.has("iodine") && reducers.length) {
    mix.special.delete("iodine");
    mix.react("I₂ + 2S₂O₃²⁻ → 2I⁻ + S₄O₆²⁻  (or vitamin C)", "redox");
    mix.see("The brown iodine colour vanishes: it has been reduced to colourless iodide.");
  }
  if (mix.special.has("iodine")) {
    if (mix.tagged("starch").length) {
      mix.special.add("starch-iodine");
      mix.react("I₂ + starch → blue-black starch-iodine complex", "test");
      mix.see("It turns an intense blue-black: the classic test for starch.");
    } else mix.tints.push(["#8a4b0f", 0.6]);
  }
  const permanganate = mix.ion("MnO4-");
  if (permanganate > 0) {
    const sugary = mix.tagged("sugar").length > 0;
    const oxidised = reducers.length || sugary || peroxide.length || (mix.tagged("fuel").length && mix.wet);
    if (oxidised) {
      if (mix.oh > 0 && sugary) {
        mix.ions.set("MnO4-", 0);
        mix.colourSteps = ["#7b1fa2", "#3949ab", "#2e9e3e", "#c68a2a"];
        mix.react("MnO₄⁻ (purple) → MnO₄²⁻ (green) → MnO₂ (brown)", "redox", "The 'chemical chameleon'.");
        mix.see("The chemical chameleon: purple → blue → green → orange-brown as the sugar is oxidised.");
        mix.precipitates.push({ formula: "MnO2", name: "manganese dioxide", colour: "#6b4a2a", grams: round(permanganate * 87, 4) });
      } else if (acidic) {
        mix.ions.set("MnO4-", 0);
        mix.addIon("Mn2+", permanganate);
        mix.react("MnO₄⁻ + 8H⁺ + 5e⁻ → Mn²⁺ + 4H₂O", "redox", "Permanganate is reduced to almost colourless Mn²⁺.");
        mix.see("The purple colour disappears.");
        mix.colourSteps = ["#7b1fa2", "#e3f2ff"];
        if (peroxide.length) mix.gas("O2", "oxygen", permanganate * 2.5, "#ffffff");
      } else {
        mix.ions.set("MnO4-", 0);
        mix.precipitates.push({ formula: "MnO2", name: "manganese dioxide", colour: "#5a3d25", grams: round(permanganate * 87, 4) });
        mix.react("MnO₄⁻ + 2H₂O + 3e⁻ → MnO₂(s) + 4OH⁻", "redox");
        mix.see("The purple fades and a brown sludge of manganese dioxide forms.");
        mix.colourSteps = ["#7b1fa2", "#8d6e63"];
      }
    }
  }
}

function organics(mix) {
  const oils = mix.tagged("oil").filter((portion) => portion.chemical.kind === "oil");
  const alkali = mix.oh;
  if (oils.length && alkali > 0) {
    const oilMoles = sum(oils.map((portion) => portion.grams)) / 885;
    const soap = Math.min(oilMoles, alkali / 3);
    if (soap > 0) {
      mix.oh -= soap * 3;
      mix.make("C18H33NaO2", "soap (sodium salts of fatty acids)", soap * 3, "solid");
      mix.make("C3H8O3", "glycerin", soap, "liquid");
      mix.react("fat + 3NaOH → 3 soap + glycerin", "saponification", "Lye splits fats into soap and glycerin.");
      mix.special.add("soap");
      if (mix.heat) mix.see("Stirred hot, the oil and lye thicken to 'trace' and turn into soap.");
      else mix.see("The oil and lye slowly turn creamy; the soap sets over 24-48 hours and cures in 4 weeks.");
      mix.warn("warning", "Lye (sodium hydroxide) burns: gloves and goggles for soap making.");
    }
  }
  if (mix.has("pva-glue") && (mix.has("borax") || (mix.has("boric-acid") && mix.tagged("carbonate").length))) {
    mix.special.add("slime");
    mix.make("PVA-borate", "slime (cross-linked PVA)", 0.01, "gel");
    mix.react("PVA chains + B(OH)₄⁻ → cross-linked gel", "cross-linking", "Borate ions tie the glue's long chains together.");
    mix.see("The glue suddenly stiffens into stretchy, bouncy slime.");
  }
  const milk = mix.has("milk");
  if (milk && (mix.h > 0 || mix.weakAcids.some((acid) => acid.pka < 5 && acid.left + acid.conj > 0))) {
    mix.special.add("curdled");
    mix.precipitates.push({ formula: "casein", name: "casein curds", colour: "#fffdf0", grams: 0.5 });
    mix.see("The milk curdles into white lumps of casein.");
    mix.react("casein (in milk) + H⁺ → casein curds (solid)", "denaturing");
  }
  const surfactants = mix.tagged("surfactant");
  if (surfactants.length && mix.wet) {
    mix.foam = Math.max(mix.foam, mix.gases.size ? 0.35 : 0.2);
    if (mix.gases.size && !mix.special.has("elephant-toothpaste")) {
      mix.foam = Math.max(mix.foam, 0.7);
      mix.see("The gas bubbles are trapped in the soap as a thick foam.");
    }
  }
  const oily = mix.portions.filter((portion) => portion.chemical.tags.has("oil"));
  if (oily.length && mix.wet) {
    if (surfactants.length || mix.has("emulsifying-wax", "polysorbate-20") || mix.special.has("soap")) {
      mix.special.add("emulsion");
      mix.see("The oil and water mix into a milky emulsion.");
    } else {
      mix.special.add("layers");
      mix.see("The oil floats on top in its own layer: oil and water don't mix.");
    }
  }
}

function safety(mix) {
  const oxidisers = mix.portions.filter((portion) => portion.chemical.hazards.includes("oxidizer") && portion.chemical.state === "solid");
  const fuels = mix.tagged("fuel");
  if (oxidisers.length && fuels.length) {
    mix.special.add("fire-risk");
    mix.warn("danger", `${oxidisers[0].chemical.name} with ${fuels[0].chemical.name.toLowerCase()} is a fire and explosion risk. The Lab won't heat or light it.`);
  }
  for (const portion of mix.portions) {
    if (portion.chemical.hazards.includes("radioactive")) mix.warn("danger", `${portion.chemical.name} is radioactive: licensed labs only.`);
    if (portion.chemical.state === "gas" && portion.chemical.hazards.includes("toxic")) mix.warn("danger", `${portion.chemical.name} gas is toxic: fume cupboard only.`);
  }
}

function heating(mix) {
  if (!(mix.heat || mix.flame)) return;
  if (mix.special.has("fire-risk")) {
    mix.see("Heating stopped: fuel mixed with an oxidiser can burn explosively.");
    return;
  }
  if (mix.flame) flameTest(mix);
  if (mix.wet && mix.heat) {
    mix.see("The liquid is heated to boiling; reactions speed up and water steams off.");
    return;
  }
  for (const [key, solid] of [...mix.solids.entries()]) {
    const formula = String(solid.formula);
    const grams = solid.grams;
    if (key === "copper-sulfate-crystals") {
      const moles = grams / molarMass("CuSO4·5H2O");
      Object.assign(solid, { colour: "#f2f2ee", name: "anhydrous copper(II) sulfate", formula: "CuSO4" });
      mix.make("H2O", "steam", moles * 5, "gas");
      mix.react("CuSO₄·5H₂O(s) → CuSO₄(s) + 5H₂O(g)", "dehydration", "Add water back and it turns blue again.");
      mix.see("The blue crystals crackle, steam off their water and turn white.");
    } else if (formula === "NaHCO3") {
      const moles = grams / molarMass("NaHCO3");
      mix.gas("CO2", "carbon dioxide", moles / 2, "#ffffff");
      mix.make("Na2CO3", "sodium carbonate", moles / 2, "solid");
      mix.react("2NaHCO₃(s) → Na₂CO₃(s) + H₂O(g) + CO₂↑", "decomposition", "Why baking soda makes cakes rise.");
      mix.see("The powder gives off carbon dioxide and steam.");
    } else if (formula === "CaCO3" && mix.flame) {
      mix.react("CaCO₃(s) → CaO(s) + CO₂↑  (above 840 °C)", "decomposition");
      mix.see("In a hot flame the chalk slowly glows and turns to quicklime.");
    } else if (formula === "C12H22O11" || formula === "C6H12O6") {
      mix.colourSteps = ["#ffffff", "#e0a84a", "#8a4a12", "#1b1b1b"];
      mix.react("C₁₂H₂₂O₁₁ → caramel → 12C + 11H₂O", "decomposition");
      mix.see("The sugar melts, turns golden caramel, then black carbon, smelling of burnt toffee.");
      solid.colour = "#6b3a12";
    } else if (formula === "NH4Cl") {
      mix.react("NH₄Cl(s) ⇌ NH₃(g) + HCl(g)", "decomposition");
      mix.see("White smoke rises and re-forms as a solid on the cool part of the tube.");
    } else if (["beeswax", "paraffin-wax", "soy-wax", "shea-butter", "coconut-oil"].includes(key)) {
      mix.see(`The ${String(solid.name).toLowerCase()} melts into a clear liquid.`);
    } else if (formula === "Mg" && mix.flame) {
      mix.special.add("dazzle");
      const moles = grams / molarMass("Mg");
      mix.make("MgO", "magnesium oxide", moles, "solid");
      mix.react("2Mg(s) + O₂ → 2MgO(s)", "combustion");
      mix.see("The magnesium burns with a dazzling white light and leaves white ash.");
      mix.warn("warning", "Don't look straight at burning magnesium: it can hurt your eyes.");
      mix.heatKj += 601 * moles;
    }
  }
  if (mix.has("iron") && mix.has("sulfur")) {
    mix.react("Fe(s) + S(s) → FeS(s)", "synthesis", "A new compound: not magnetic any more.");
    mix.see("The mixture glows red as it reacts and keeps glowing on its own.");
    mix.special.add("glow");
    mix.warn("warning", "Heating sulfur gives off choking sulfur dioxide: ventilate.");
  }
}

function flameTest(mix) {
  let metals = [];
  for (const ion of [...mix.ions.keys()]) {
    if (mix.ion(ion) <= 0) continue;
    const symbol = ion.match(/^([A-Z][a-z]?)/);
    if (symbol && symbol[1] in FLAME_COLOURS && ion.endsWith("+")) metals.push(symbol[1]);
  }
  for (const portion of mix.portions) {
    const found = portion.chemical.formula.match(/^([A-Z][a-z]?)/);
    if (found && found[1] in FLAME_COLOURS && (portion.chemical.kind === "salt" || portion.chemical.kind === "base")) metals.push(found[1]);
  }
  metals = unique(metals);
  if (!metals.includes("B") && mix.has("boric-acid", "borax")) metals.push("B");
  if (!metals.length) {
    if (mix.has("ethanol", "isopropanol")) {
      mix.special.add("flame-blue");
      mix.see("The alcohol burns with a soft blue flame.");
    }
    return;
  }
  const shown = metals.includes("Na") ? "Na" : metals[0];
  const [name, colour] = FLAME_COLOURS[shown];
  mix.special.add(`flame:${colour}:${name}`);
  mix.see(`Flame test: a ${name} flame (${shown}).`);
  if (shown === "Na" && metals.length > 1) mix.see("Sodium's strong yellow hides the other colours; a blue cobalt glass would filter it out.");
}

function phOf(mix) {
  if (!mix.wet) return null;
  const litres = mix.litres;
  if (mix.h > 1e-9) return Math.max(-1.0, -Math.log10(mix.h / litres));
  if (mix.oh > 1e-9) return Math.min(14.5, 14 + Math.log10(mix.oh / litres));
  for (const acid of [...mix.weakAcids].sort((a, b) => a.pka - b.pka)) {
    if (acid.left > 1e-9) {
      if (acid.conj > 1e-9) return acid.pka + Math.log10(acid.conj / acid.left);
      return 0.5 * (acid.pka - Math.log10(acid.left / litres));
    }
  }
  const carbonate = mix.ion("CO32-");
  const bicarbonate = mix.ion("HCO3-");
  if (carbonate > 1e-9) return Math.min(14.0, 14 - 0.5 * (3.67 - Math.log10(carbonate / litres)));
  for (const base of mix.weakBases) {
    if (base.left > 1e-9) {
      if (base.conj > 1e-9) return 14 - (base.pkb + Math.log10(base.conj / base.left));
      return 14 - 0.5 * (base.pkb - Math.log10(base.left / litres));
    }
  }
  if (bicarbonate > 1e-9) return 8.3;
  if (mix.weakAcids.some((acid) => acid.conj > 0)) return 8.4;
  if (mix.weakBases.some((base) => base.conj > 0)) return 5.4;
  if (mix.ion("Fe3+") > 1e-6 || mix.ion("Al3+") > 1e-6) return 3.0;
  return 7.0;
}

/** [colour, what it means] for an indicator at a pH. */
export function indicatorColour(indicator, ph) {
  if (indicator === "phenolphthalein") {
    if (ph < 8.2) return ["#f4f8ff", "colourless (not alkaline)"];
    return ph < 10 ? ["#ff4fb3", "pink (alkaline)"] : ["#d4007a", "magenta (strongly alkaline)"];
  }
  if (indicator === "bromothymol-blue") {
    if (ph < 6.0) return ["#e8d23a", "yellow (acidic)"];
    return ph <= 7.6 ? ["#4caf50", "green (neutral)"] : ["#1e5bd6", "blue (alkaline)"];
  }
  if (indicator === "red-cabbage") {
    const steps = [[2, "#e0245e", "red"], [4, "#e85a9b", "pink"], [6, "#9c4dcc", "violet"], [7.5, "#7b3fa0", "purple"], [8.5, "#3f51b5", "blue"], [11, "#26a65b", "green"]];
    for (const [top, colour, word] of steps) if (ph < top) return [colour, word];
    return ["#e8d23a", "yellow"];
  }
  const steps = [[3, "#e53935", "red: strongly acidic"], [5, "#fb8c00", "orange: acidic"], [6.5, "#fdd835", "yellow: weakly acidic"], [7.5, "#43a047", "green: neutral"], [9, "#1e88e5", "blue: alkaline"], [11, "#3949ab", "indigo: alkaline"]];
  for (const [top, colour, word] of steps) if (ph < top) return [colour, word];
  return ["#8e24aa", "purple: strongly alkaline"];
}

const PLAIN_COLOURS = new Set(["#e8f4ff", "#cfe8ff", "#f5f5f5"]);
const DANGER_CODES = new Set(["toxic", "corrosive", "reactive-water", "radioactive"]);

function result(mix) {
  const ph = phOf(mix);
  const water = mix.waterMl;
  const totalMl = sum(mix.portions.filter((portion) => portion.unit === "mL").map((portion) => portion.amount));
  const mass = sum(mix.portions.map((portion) => portion.grams)) || 1.0;
  const heatCapacity = water * 4.18 + Math.max(0, mass - water) * 2.0;
  let rise = heatCapacity ? (mix.heatKj * 1000) / heatCapacity : 0;
  let temperature = ROOM_C + rise;
  if (temperature < 0 && mix.wet) {
    temperature = Math.max(temperature, -15.0);
    rise = temperature - ROOM_C;
  }
  if (mix.heat) temperature = Math.max(temperature, mix.wet ? 100.0 : 180.0);
  const boiling = mix.wet && temperature >= 100;
  if (boiling) {
    temperature = !mix.heat ? 100.0 : temperature;
    mix.see("It gets hot enough to boil.");
  } else if (rise > 8) mix.see(`The beaker gets warm (+${fixed(rise, 0)} °C).`);
  else if (rise < -3) {
    const frost = temperature < 3 ? "; frost forms on the outside" : "";
    mix.see(`The beaker gets cold (${fixed(rise, 0)} °C)${frost}.`);
  }

  let tints = [...mix.tints];
  const litres = mix.litres;
  for (const [ion, amount] of mix.ions) {
    if (ion in ION_COLOURS && amount > 1e-9) {
      const [colour, strength] = ION_COLOURS[ion];
      tints.push([colour, Math.min(0.85, (strength * amount) / litres)]);
    }
  }
  let indicatorNote = "";
  const bleached = mix.special.has("bleached");
  for (const portion of mix.portions) {
    const chemical = portion.chemical;
    const share = portion.amount / Math.max(totalMl, 1.0);
    const colourOnly = chemical.roles.length === 1 && chemical.roles[0] === "colour";
    if (chemical.kind === "indicator" && ph !== null && !bleached) {
      const [colour, meaning] = indicatorColour(chemical.id, ph);
      tints.push([colour, colour !== "#f4f8ff" ? 0.8 : 0.0]);
      indicatorNote = `${chemical.name.split(" (")[0]} turns ${meaning}.`;
    } else if (colourOnly && !bleached) tints.push([chemical.colour, Math.min(0.9, 0.3 + share * 3)]);
    else if (!chemical.ions.length && (chemical.state === "liquid" || chemical.state === "solution") && !PLAIN_COLOURS.has(chemical.colour)) {
      if (chemical.kind !== "indicator" && chemical.kind !== "oil" && !chemical.tags.has("iodine")) tints.push([chemical.colour, Math.min(0.6, share)]);
    }
  }
  if (indicatorNote) mix.see(indicatorNote);
  if (mix.special.has("starch-iodine")) tints = [["#141a4d", 2.0]];
  let [liquidColour, opacity] = blend(tints);
  if (mix.colourSteps.length) {
    liquidColour = mix.colourSteps.at(-1);
    opacity = liquidColour === "#e3f2ff" ? 0.12 : 0.85;
  }
  if (mix.special.has("emulsion")) [liquidColour, opacity] = ["#f7f3e8", 0.92];
  let layers = [];
  const oily = mix.portions.filter((portion) => portion.chemical.tags.has("oil") && portion.unit === "mL");
  if (mix.special.has("layers") && oily.length) {
    const [oilColour] = blend(oily.map((portion) => [portion.chemical.colour, portion.amount]));
    const oilMl = sum(oily.map((portion) => portion.amount));
    layers = [
      { name: "watery layer", colour: liquidColour, ml: round(totalMl - oilMl, 1), opacity },
      { name: "oil layer", colour: oilColour, ml: round(oilMl, 1), opacity: 0.75 },
    ];
  } else if (totalMl) layers = [{ name: "mixture", colour: liquidColour, ml: round(totalMl, 1), opacity }];

  const gases = [...mix.gases.values()].map((entry) => {
    const millilitres = entry.moles * GAS_ML_PER_MOL;
    const level = millilitres > 600 || mix.special.has("violent") ? "violent" : millilitres > 120 ? "lots" : millilitres > 10 ? "fizzing" : "a few bubbles";
    return { formula: entry.formula, name: entry.name, colour: entry.colour, ml: round(millilitres, 1), level };
  });
  const products = [...mix.products.values()].map((entry) => {
    let grams = 0;
    try {
      grams = entry.moles * molarMass(entry.formula);
    } catch (error) {
      if (!(error instanceof FormulaError)) throw error;
    }
    return {
      formula: entry.formula,
      pretty: /^[A-Za-z0-9()·]+$/.test(entry.formula) ? pretty(entry.formula) : entry.formula,
      name: entry.name,
      state: entry.state,
      moles: round(entry.moles, 5),
      grams: round(grams, 4),
    };
  });
  const dissolved = [...mix.ions.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .filter(([, amount]) => amount > 1e-7)
    .map(([ion, amount]) => ({ ion, pretty: ionPretty(ion), mol_per_l: round(amount / litres, 4) }));
  let flame = null;
  for (const mark of mix.special) {
    if (mark.startsWith("flame:")) {
      const [, colour, ...name] = mark.split(":");
      flame = { colour, name: name.join(":") };
    }
  }
  if (mix.special.has("flame-blue")) flame = { colour: "#4f7dff", name: "blue" };
  for (const portion of mix.portions) {
    for (const code of portion.chemical.hazards) mix.warn(DANGER_CODES.has(code) ? "danger" : "caution", `${portion.chemical.name}: ${HAZARDS[code] || code}.`);
  }
  const happened = mix.reactions.map((reaction) => reaction.kind);
  const summary = summarise(mix, ph, temperature, happened);
  return {
    vessel: {
      colour: liquidColour,
      opacity,
      colour_steps: mix.colourSteps,
      volume_ml: round(totalMl, 1),
      water_ml: round(water, 1),
      temperature_c: round(temperature, 1),
      ph: ph !== null ? round(ph, 2) : null,
      layers,
      precipitates: mix.precipitates,
      solids: [...mix.solids.values()].map((solid) => ({ name: solid.name, colour: solid.colour, grams: round(solid.grams, 4), formula: solid.formula })),
      gases,
      foam: round(mix.foam, 2),
      flame,
      boiling,
      effects: [...mix.special].filter((mark) => !mark.startsWith("flame:")).sort(),
    },
    ingredients: mix.portions.map((portion) => ({ id: portion.chemical.id, name: portion.chemical.name, formula: portion.chemical.formula, amount: portion.amount, unit: portion.unit, colour: portion.chemical.colour })),
    reactions: mix.reactions,
    observations: mix.observations,
    hazards: mix.hazards,
    products,
    dissolved,
    summary,
    unknown: mix.unknown,
    source: "rules",
  };
}

function summarise(mix, ph, temperature, happened) {
  const parts = [];
  if (!mix.portions.length) return "Nothing the Lab knows is in the beaker yet.";
  if (happened.length) parts.push(`Reactions: ${unique(happened).join(", ")}.`);
  else parts.push("No chemical reaction: the substances just mix.");
  if (mix.precipitates.length) parts.push(`Solid formed: ${mix.precipitates.map((entry) => entry.name).join(", ")}.`);
  if (mix.gases.size) parts.push(`Gas given off: ${[...mix.gases.values()].map((entry) => entry.name).join(", ")}.`);
  if (ph !== null) {
    const word = ph < 3 ? "strongly acidic" : ph < 6.5 ? "acidic" : ph <= 7.5 ? "neutral" : ph < 11 ? "alkaline" : "strongly alkaline";
    parts.push(`pH about ${fixed(ph, 1)} (${word}).`);
  }
  if (Math.abs(temperature - ROOM_C) >= 2) parts.push(`Temperature ${fixed(temperature, 0)} °C.`);
  if (mix.unknown.length) parts.push(`Not on the shelf: ${mix.unknown.join(", ")}.`);
  return parts.join(" ");
}

/* ------------------------------------------------------------- the parts */

export const PARTS = SCIENCE.parts;
const PART_BY_ID = new Map(PARTS.map((part) => [part.id, part]));
const E12 = SCIENCE.e12;

export function findPart(text) {
  const wanted = text.trim().toLowerCase();
  if (PART_BY_ID.has(wanted)) return PART_BY_ID.get(wanted);
  for (const part of PARTS) if (wanted === part.name.toLowerCase()) return part;
  for (const part of PARTS) if (wanted.length >= 3 && part.name.toLowerCase().includes(wanted)) return part;
  return null;
}

/** The next E12 value up (so the LED gets a little less than its limit). */
export function standardResistor(ohms) {
  if (ohms <= 0) return 0;
  let decade = 1.0;
  while (decade * 10 <= ohms) decade *= 10;
  while (decade > ohms) decade /= 10;
  for (const step of [...E12, 10.0]) if (step * decade >= ohms - 1e-9) return round(step * decade, 2);
  return round(10 * decade, 2);
}

const ohmsText = (value) => (value >= 1000 ? `${general(value / 1000)} kΩ` : `${general(value)} Ω`);

function runtimeText(hours) {
  if (hours === Infinity) return "Runs as long as it's plugged in.";
  if (hours <= 0) return "Doesn't run.";
  if (hours < 1) return `About ${fixed(hours * 60, 0)} minutes per charge.`;
  if (hours < 48) return `About ${fixed(hours, 1)} hours.`;
  return `About ${fixed(hours / 24, 0)} days.`;
}

const PASSIVE_KINDS = new Set(["power", "passive", "structure", "regulator"]);
const PASSIVE_IDS = new Set(["solar", "tp4056", "switch", "button", "transistor"]);

/** Power the parts and report what works: volts, amps, runtime, warnings. */
export function simulateBuild(entries, { series = true, sun = true } = {}) {
  const chosen = [];
  for (const entry of entries) {
    const wanted = String(entry.id || entry.name || "");
    const part = findPart(wanted);
    if (!part) throw new LabError(`No part called '${entry.id || entry.name}'.`);
    const raw = entry.count;
    const count = typeof raw === "number" && raw > 0 && raw <= 50 ? Math.trunc(raw) : 1;
    chosen.push([part, count]);
  }
  if (!chosen.length) throw new LabError("Add some parts to the bench first.");
  const ids = new Set(chosen.map(([part]) => part.id));
  const warnings = [];
  const tips = [];
  let cells = chosen.filter(([part]) => part.kind === "power");
  const solar = chosen.filter(([part]) => part.id === "solar");
  if (!cells.length && solar.length) cells = solar;
  if (!cells.length) {
    return {
      works: false,
      volts: 0.0,
      parts: chosen.map(([part, count]) => ({ id: part.id, name: part.name, icon: part.icon, count, state: "off" })),
      warnings: ["Nothing powers this build: add a battery, USB power, or a solar panel."],
      tips: [],
      total_ma: 0,
      runtime_hours: 0,
      grams: sum(chosen.map(([part, count]) => part.grams * count)),
      price: round(sum(chosen.map(([part, count]) => part.price * count)), 2),
      resistors: [],
    };
  }
  if (new Set(cells.map(([part]) => part.id)).size > 1) warnings.push("Don't mix different batteries in one pack: the weaker one drains, heats, and can leak.");
  const first = cells[0][0];
  const count = sum(cells.map(([, number]) => number));
  let volts;
  let capacity;
  let maxMa;
  if (series) {
    volts = sum(cells.map(([part, number]) => part.volts * number));
    capacity = first.capacity_mah ? Math.min(...cells.map(([part]) => part.capacity_mah)) : 0.0;
    maxMa = Math.min(...cells.map(([part]) => part.milliamps));
  } else {
    volts = first.volts;
    capacity = sum(cells.map(([part, number]) => part.capacity_mah * number));
    maxMa = sum(cells.map(([part, number]) => part.milliamps * number));
  }
  const supply = (count > 1 ? `${count} x ` : "") + first.name + (series && count > 1 ? " in series" : count > 1 ? " side by side" : "");
  if (first.id === "solar" && !sun) {
    volts *= 0.5;
    maxMa *= 0.1;
    warnings.push("Cloudy: the solar panel gives about a tenth of its power.");
  }
  if (first.rechargeable && first.needs.includes("charger") && !ids.has("tp4056") && (first.id === "18650" || first.id === "lipo")) warnings.push(`${first.name} needs a protected charger board (TP4056) to charge safely.`);
  if (solar.length && (first.id === "18650" || first.id === "lipo") && !ids.has("tp4056")) warnings.push("Never wire a solar panel straight to a lithium cell: charge it through a TP4056.");
  let rail = volts;
  let efficiency = 1.0;
  let regulated = "";
  if (ids.has("boost-5v")) {
    if (volts < 0.9) warnings.push("The boost converter needs at least 0.9 V to start.");
    else [rail, efficiency, regulated] = [5.0, 0.85, "boost-5v"];
  } else if (ids.has("regulator-3v3") && volts >= 3.6) [rail, efficiency, regulated] = [3.3, 3.3 / volts, "regulator-3v3"];
  const hasController = ["arduino", "esp32", "raspberry-pi"].some((id) => ids.has(id));
  const hasDriver = ["motor-driver", "transistor", "relay"].some((id) => ids.has(id));
  const rows = [];
  const resistors = [];
  let totalMa = 0;
  for (const [part, number] of chosen) {
    if (PASSIVE_KINDS.has(part.kind) || PASSIVE_IDS.has(part.id)) {
      rows.push({ id: part.id, name: part.name, icon: part.icon, count: number, state: "ok" });
      continue;
    }
    const limit = part.volts_max || part.volts * 1.3;
    let state = "on";
    let reason = "";
    let current = part.milliamps;
    if (part.id === "arduino" && rail >= 7) state = "on";
    else if (part.needs.length && part.needs.includes("resistor")) {
      if (rail < part.volts) [state, reason, current] = ["dim", `needs ${floatText(part.volts)} V, gets ${fixed(rail, 1)} V`, part.milliamps * 0.1];
      else {
        const ohms = (rail - part.volts) / (part.milliamps / 1000);
        if (ohms < 1) state = "on";
        else {
          const value = standardResistor(ohms);
          const power = (part.milliamps / 1000) ** 2 * value;
          resistors.push({ for: part.name, ohms: value, exact_ohms: round(ohms, 1), watts: round(power, 3), rating: power < 0.2 ? "¼ W" : power < 0.4 ? "½ W" : "1 W+" });
          current = value ? ((rail - part.volts) / value) * 1000 : part.milliamps;
          tips.push(`Put a ${ohmsText(value)} resistor in series with each ${part.name.toLowerCase()} (${fixed(rail, 1)} V - ${floatText(part.volts)} V) ÷ ${general(part.milliamps / 1000)} A.`);
        }
      }
    } else if (rail > limit) [state, reason] = ["burnt", `${fixed(rail, 1)} V is more than its ${fixed(limit, 1)} V limit`];
    else if (rail < part.volts * 0.75) [state, reason, current] = ["off", `needs about ${floatText(part.volts)} V, gets ${fixed(rail, 1)} V`, 0];
    else if (rail < part.volts * 0.9) [state, reason, current] = ["weak", `a bit under its ${floatText(part.volts)} V`, part.milliamps * 0.7];
    if (part.needs.includes("controller") && !hasController && state === "on") [state, reason] = ["idle", "needs a microcontroller (Arduino or ESP32) to tell it what to do"];
    if (part.needs.includes("driver") && !hasDriver && state === "on") warnings.push(`${part.name}: use a motor driver; a microcontroller pin can only give about 20 mA.`);
    if (part.kind === "motion" && hasController && !hasDriver && part.id !== "servo") warnings.push(`${part.name} draws ${general(part.milliamps)} mA: switch it with a transistor or motor driver, not straight from a pin.`);
    if (state === "burnt") warnings.push(`${part.name} would burn out: ${reason}. Add a regulator or use fewer cells.`);
    else if (state === "off" || state === "weak" || state === "dim") warnings.push(`${part.name} ${state === "off" ? "won't switch on" : "runs weakly"}: ${reason}.`);
    if (state !== "burnt" && state !== "off") totalMa += current * number;
    rows.push({ id: part.id, name: part.name, icon: part.icon, count: number, state, reason, milliamps: round(current, 1) });
  }
  const drawFromCells = volts ? (totalMa * (rail / volts)) / efficiency : totalMa;
  if (maxMa && drawFromCells > maxMa * 1.05) warnings.push(`The parts want ${fixed(drawFromCells, 0)} mA but the ${first.name.toLowerCase()} can only give about ${fixed(maxMa, 0)} mA: things will brown out.`);
  let runtime = capacity && drawFromCells ? capacity / drawFromCells : 0.0;
  if (first.id === "usb") runtime = Infinity;
  const works = !rows.some((row) => row.state === "burnt" || row.state === "off") && !(maxMa && drawFromCells > maxMa * 1.05);
  const watts = (rail * totalMa) / 1000;
  return {
    works,
    supply,
    volts: round(volts, 2),
    rail_volts: round(rail, 2),
    regulated_by: regulated,
    capacity_mah: capacity,
    total_ma: round(drawFromCells, 1),
    watts: round(watts, 2),
    runtime_hours: runtime === Infinity ? null : round(runtime, 1),
    runtime_text: runtimeText(runtime),
    parts: rows,
    resistors,
    warnings: unique(warnings),
    tips: unique(tips),
    grams: round(sum(chosen.map(([part, count]) => part.grams * count)), 1),
    price: round(sum(chosen.map(([part, count]) => part.price * count)), 2),
  };
}

/* ------------------------------------------------------- resistor colours */

export const BAND_COLOURS = [
  ["black", "#1b1b1b"],
  ["brown", "#7a4a1e"],
  ["red", "#d32f2f"],
  ["orange", "#f57c00"],
  ["yellow", "#fdd835"],
  ["green", "#2e7d32"],
  ["blue", "#1565c0"],
  ["violet", "#7b1fa2"],
  ["grey", "#8d8d8d"],
  ["white", "#f5f5f5"],
];
const GOLD = ["gold", "#d4af37"];
const SILVER = ["silver", "#c0c0c0"];

/** A resistor's four colour bands (two digits, the multiplier, ±5% gold). */
export function resistorBands(ohms) {
  const value = Math.max(0.1, ohms);
  let exponent = Math.floor(Math.log10(value)) - 1;
  let digits = Math.round(value / 10 ** exponent);
  if (digits >= 100) {
    digits = Math.round(digits / 10);
    exponent += 1;
  }
  const multiplier = exponent >= 0 ? BAND_COLOURS[Math.min(9, exponent)] : exponent === -1 ? GOLD : SILVER;
  const bands = [BAND_COLOURS[Math.floor(digits / 10)], BAND_COLOURS[digits % 10], multiplier, GOLD];
  return bands.map(([name, colour]) => ({ name, colour }));
}
