// The Lab box screen: the 3D box (turn it, pinch to zoom, tap a room to go
// in), a room bar, the room's own controls underneath, and a line to tell
// Jarvis what to make: he walks to the room and does it himself.
import { state, onChange } from "../state.js";
import { el, button, card, notify, go, openSheet, closeSheet } from "../ui.js";
import { answer } from "../agents.js";
import { resolveChemical, searchChemicals, findPart, PARTS, resistorBands, MAX_ITEMS, HAZARDS } from "../../lab/science.js";
import * as shop from "../workshop.js";

const ROOM_ORDER = ["chemistry", "electronics", "blueprints", "library"];
const KIND_NAMES = { power: "Power", charger: "Charging", regulator: "Regulators", light: "Lights", motion: "Motion", sound: "Sound", brain: "Brains", sensor: "Sensors", display: "Displays", control: "Switches", passive: "Passives", structure: "Body" };
const TRY_MIXES = {
  Volcano: [[{ id: "acetic-acid", amount: 50 }, { id: "sodium-bicarbonate", amount: 5 }], {}],
  "Golden rain": [[{ id: "lead-nitrate", amount: 20 }, { id: "potassium-iodide", amount: 20 }], {}],
  "Elephant toothpaste": [[{ id: "hydrogen-peroxide-strong", amount: 50 }, { id: "potassium-iodide", amount: 10 }, { id: "dish-soap", amount: 5 }], {}],
  "Royal blue": [[{ id: "copper-sulfate", amount: 20 }, { id: "ammonia", amount: 40 }], {}],
  "Silver tree": [[{ id: "silver-nitrate", amount: 30 }, { id: "copper", amount: 2 }], {}],
  "Sodium + water": [[{ id: "water", amount: 100 }, { id: "sodium-metal", amount: 0.5 }], {}],
  "Copper flame": [[{ id: "copper-sulfate", amount: 10 }], { flame: true }],
};
const TRY_BUILDS = {
  "LED torch": [{ id: "aa", count: 2 }, { id: "led-white", count: 1 }, { id: "switch", count: 1 }],
  "Night light": [{ id: "usb", count: 1 }, { id: "arduino", count: 1 }, { id: "light-sensor", count: 1 }, { id: "led-blue", count: 2 }],
  "Solar fan": [{ id: "solar", count: 1 }, { id: "fan", count: 1 }],
  "Robot car": [{ id: "18650", count: 1 }, { id: "tp4056", count: 1 }, { id: "boost-5v", count: 1 }, { id: "motor-driver", count: 1 }, { id: "wheels", count: 1 }, { id: "arduino", count: 1 }, { id: "distance-sensor", count: 1 }],
  "Burn test": [{ id: "9v", count: 1 }, { id: "vibration", count: 1 }, { id: "led-red", count: 1 }],
};

const jarvisOf = () => state.agents.find((agent) => agent.role === "main") || state.agents[0];

export function render(view) {
  let room = state.labRoom && ROOM_ORDER.includes(state.labRoom) ? state.labRoom : null;
  let world = null;
  let picked = null;
  let selected = "";
  let filter = "";
  let topic = "";
  let query = "";
  let reply = "";
  let labels = true;
  const canvas = el("canvas", { class: "lab-world", "aria-label": "The Lab box in 3D: drag to turn, pinch to zoom, tap a room" });
  const where = el("div", { class: "lab-where" });
  const back = el("button", { class: "lab-overlay-button", type: "button", text: "⟵ Box", hidden: true, onclick: () => world && world.focus(null) });
  const status = el("p", { class: "small lab-status", "aria-live": "polite" });
  const bar = el("div", { class: "lab-roombar", role: "group", "aria-label": "Rooms" });
  const panel = el("div", { class: "lab-panel" });
  const boxNode = el("section", { class: "lab-box" });

  /* ---------------------------------------------------------- the 3D */
  const display = (items) =>
    items.map((item) => {
      const chemical = resolveChemical(item.id) || { name: item.id, formula: "", colour: "#cfe8ff", state: "liquid" };
      return { id: item.id, name: chemical.name, formula: chemical.formula, colour: chemical.colour, unit: chemical.state === "solid" ? "g" : "mL" };
    });
  const showBenches = (pour = false) => {
    if (!world) return;
    const { chemistry, electronics } = state.bench;
    world.setChemistry(display(chemistry.items), chemistry.result, { heat: chemistry.heat, flame: chemistry.flame, pour });
    world.setCircuit(electronics.parts, electronics.result, electronics.powered);
  };
  const showJarvis = () => {
    const jarvis = state.bench.jarvis;
    const fresh = jarvis.at && Date.now() - jarvis.at < 120000;
    const name = jarvisOf() ? jarvisOf().name : "Jarvis";
    status.textContent = fresh && jarvis.room ? `${name} is in ${shop.ROOM_NAMES[jarvis.room]}${jarvis.doing ? `: ${jarvis.doing}` : ""}.` : `${name} is waiting for a job. Tell him what to make below.`;
    if (world && fresh && jarvis.room) world.jarvisTo(jarvis.room, { doing: jarvis.doing ? "work" : "think", say: jarvis.doing, seconds: 9 });
  };

  /* ---------------------------------------------------------- panels */
  const drawBar = () => {
    bar.replaceChildren(
      el("button", { class: "lab-room", type: "button", "aria-pressed": String(!room), text: "Box", onclick: () => world ? world.focus(null) : setRoom(null) }),
      ...ROOM_ORDER.map((id) => el("button", { class: "lab-room", type: "button", "aria-pressed": String(room === id), text: shop.ROOM_NAMES[id], onclick: () => (world ? world.focus(id) : setRoom(id)) })),
      el("button", { class: "lab-room", type: "button", text: "Game kit", onclick: () => go("lab/game") })
    );
    where.textContent = room ? shop.ROOM_NAMES[room] : "The Lab";
    back.hidden = !room;
    boxNode.classList.toggle("in-room", Boolean(room));
  };

  const setRoom = (next) => {
    room = next;
    state.labRoom = next;
    picked = null;
    drawBar();
    drawPanel();
  };

  const tellJarvis = (text) => {
    const jarvis = jarvisOf();
    if (!jarvis) return notify("There's no main AI on this phone yet.");
    reply = `${jarvis.name} is on it…`;
    drawPanel();
    answer(jarvis, text)
      .then((said) => {
        reply = said;
        shop.jarvisWorks(state.bench.jarvis.room || room || "", "");
      })
      .catch((error) => {
        reply = `${jarvis.name} couldn't do it: ${error.message}`;
      })
      .finally(() => drawPanel());
  };

  const jarvisCard = () => {
    const box = el("textarea", { rows: 2, "aria-label": "Tell Jarvis what to make", placeholder: room === "electronics" ? "Build a night light that turns on in the dark" : room === "chemistry" ? "Show me what happens with copper sulfate and ammonia" : "Make me a solar-powered fan and save it as a chip" });
    return card(`Tell ${jarvisOf() ? jarvisOf().name : "Jarvis"}`, [
      el("p", { class: "small muted", text: "He walks to the room and does it himself, then you can save it as a blueprint, reload it later and improve it." }),
      box,
      el("div", { class: "row" }, [
        button("Send", () => {
          const text = box.value.trim();
          if (text) tellJarvis(text);
        }, { class: "primary" }),
      ]),
      reply ? el("p", { class: "lab-reply", text: reply }) : null,
    ], { class: "lab-jarvis" });
  };

  const saveSheet = (kind) => {
    const fromId = kind === "mixture" ? state.bench.from.chemistry : state.bench.from.electronics;
    const from = fromId ? shop.exactBlueprint(fromId) : null;
    const name = el("input", { "aria-label": "Blueprint name", placeholder: kind === "chip" ? "Night light chip" : kind === "mixture" ? "Blue copper mix" : "Solar plant waterer" });
    const notes = el("textarea", { rows: 3, "aria-label": "Notes", placeholder: "What it does, how it works, what changed" });
    const save = async (onto) => {
      try {
        const print = await shop.saveBlueprint({ name: name.value, kind, notes: notes.value, onto });
        closeSheet();
        const number = shop.versionNumber(print, print.versions.at(-1));
        notify(`Saved ${print.name}${number > 1 ? ` (version ${number})` : ""}.`);
        drawPanel();
      } catch (error) {
        notify(error.message);
      }
    };
    openSheet(`Save as ${shop.BLUEPRINT_KINDS[kind].toLowerCase()}`, [
      el("label", {}, ["Name", name]),
      el("label", {}, ["Notes", notes]),
      el("div", { class: "row" }, [
        from && from.kind === kind ? button(`Save as version ${shop.nextVersion(from)} of ${from.name}`, () => save(from.id), { class: "primary" }) : null,
        button(from && from.kind === kind ? "Save as a new blueprint" : "Save", () => save(""), { class: from && from.kind === kind ? "" : "primary" }),
      ]),
    ]);
  };

  const run = async (work) => {
    try {
      await work();
    } catch (error) {
      notify(error.message);
    }
    drawPanel();
  };

  function overviewPanel() {
    const { chemistry, electronics } = state.bench;
    return [
      card("The Lab", [
        el("p", { text: "Your crafting table: turn the box with a finger, pinch to zoom, tap a room to go in. Mix chemicals, build circuits, keep blueprints and read how to build anything." }),
        el("ul", { class: "lab-facts" }, [
          el("li", { text: `Chemistry: ${chemistry.items.length ? `${chemistry.items.length} in the beaker${chemistry.result ? `, ${chemistry.result.summary}` : ""}` : "the beaker is clean"}` }),
          el("li", { text: `Electronics: ${electronics.parts.length ? `${electronics.parts.length} parts on the board${electronics.result ? (electronics.result.works ? ", it works" : ", not working yet") : ""}` : "the board is empty"}` }),
          el("li", { text: `Blueprints: ${state.blueprints.length} saved` }),
          el("li", { text: `Library: ${shop.topics().length} topics of build-your-own-x tutorials` }),
        ]),
      ]),
    ];
  }

  function chemistryPanel() {
    const bench = state.bench.chemistry;
    const items = bench.items.map((item) => ({ ...item }));
    const update = (next) => run(() => shop.setBeaker(next));
    const rows = items.map((item, index) => {
      const chemical = resolveChemical(item.id);
      const unit = chemical && chemical.state === "solid" ? "g" : "mL";
      const amount = el("input", { type: "number", min: "0.1", step: "any", value: item.amount ?? (unit === "g" ? 2 : 20), "aria-label": `Amount of ${chemical ? chemical.name : item.id}`, onchange: (event) => {
        items[index].amount = Math.max(0.1, Number(event.target.value) || 1);
        update(items);
      } });
      return el("div", { class: "lab-row" }, [
        el("span", { class: "lab-swatch", style: { background: chemical ? chemical.colour : "#cfe8ff" } }),
        el("span", { class: "grow", text: chemical ? `${chemical.name} ${chemical.formula ? `(${chemical.formula})` : ""}` : item.id }),
        amount,
        el("span", { class: "small muted", text: unit }),
        el("button", { class: "lab-x", type: "button", "aria-label": `Take out ${chemical ? chemical.name : item.id}`, text: "✕", onclick: () => update(items.filter((_, i) => i !== index)) }),
      ]);
    });
    const search = el("input", { type: "search", "aria-label": "Find a chemical", placeholder: "Find a chemical: vinegar, copper, NaCl, Mg…", value: query });
    const found = el("div", { class: "lab-chips" });
    const drawFound = () => {
      const hits = query.trim() ? searchChemicals(query, 14) : [];
      const element = query.trim() && !hits.length ? resolveChemical(query.trim()) : null;
      found.replaceChildren(
        ...[...hits, ...(element ? [element] : [])].map((chemical) =>
          el("button", { class: "lab-chip", type: "button", text: chemical.name, onclick: () => {
            if (items.length >= MAX_ITEMS) return notify(`The beaker holds up to ${MAX_ITEMS} things.`);
            query = "";
            update([...items, { id: chemical.id, amount: chemical.state === "solid" ? 2 : 20 }]);
          } })
        )
      );
    };
    search.addEventListener("input", () => {
      query = search.value;
      drawFound();
    });
    drawFound();
    const heat = el("input", { type: "checkbox", checked: bench.heat, onchange: (event) => run(() => shop.setBeaker(items, { heat: event.target.checked })) });
    const flame = el("input", { type: "checkbox", checked: bench.flame, onchange: (event) => run(() => shop.setBeaker(items, { flame: event.target.checked })) });
    const result = bench.result;
    return [
      card("Chemistry bench", [
        rows.length ? el("div", { class: "lab-list" }, rows) : el("p", { class: "muted", text: "The beaker is clean. Find something on the shelf, or try one below." }),
        search,
        found,
        el("div", { class: "row lab-toggles" }, [el("label", { class: "check" }, [heat, " Heat it"]), el("label", { class: "check" }, [flame, " Flame test"])]),
        el("div", { class: "row" }, [
          button("Mix", () => run(() => shop.mix(items, { heat: bench.heat, flame: bench.flame })), { class: "primary", disabled: items.length ? null : true }),
          button("Clean the beaker", () => run(() => shop.setBeaker([], { heat: false, flame: false }))),
          button("Save as mixture", () => saveSheet("mixture"), { disabled: items.length ? null : true }),
        ]),
        el("p", { class: "small muted", text: "Try one:" }),
        el("div", { class: "lab-chips" }, Object.entries(TRY_MIXES).map(([name, [mixItems, options]]) =>
          el("button", { class: "lab-chip", type: "button", text: name, onclick: () => run(() => shop.mix(mixItems, options)) })
        )),
      ]),
      result ? resultCard(result) : null,
      picked && picked.type === "bottle" ? chemicalCard(picked.id) : null,
    ];
  }

  const resultCard = (result) => {
    const v = result.vessel;
    return card("What happens", [
      el("p", { class: "lab-summary", text: result.summary }),
      el("p", { class: "small", text: `${v.volume_ml} mL · ${v.temperature_c} °C${v.ph !== null ? ` · pH ${v.ph}` : ""}${v.gases.length ? ` · ${v.gases.map((gas) => `${gas.name} (${gas.level})`).join(", ")}` : ""}` }),
      result.observations.length ? el("ul", {}, result.observations.map((text) => el("li", { text }))) : null,
      result.reactions.length ? el("div", { class: "lab-equations" }, result.reactions.map((reaction) => el("p", {}, [el("code", { text: reaction.equation }), el("span", { class: "small muted", text: ` ${reaction.kind}${reaction.note ? `: ${reaction.note}` : ""}` })]))) : null,
      result.products.length ? el("p", { class: "small", text: `Made: ${result.products.map((product) => `${product.name} (${product.pretty}) ${product.grams} g`).join(", ")}` }) : null,
      ...result.hazards.map((hazard) => el("p", { class: `lab-hazard ${hazard.level}`, text: hazard.text })),
    ]);
  };

  const chemicalCard = (id) => {
    const chemical = resolveChemical(id);
    if (!chemical) return null;
    return card(chemical.name, [
      el("p", { class: "small", text: `${chemical.formula || ""} · ${chemical.kind} · ${chemical.state}${chemical.molarMass ? ` · ${chemical.molarMass} g/mol` : ""}` }),
      chemical.note ? el("p", { text: chemical.note }) : null,
      ...chemical.hazards.map((code) => el("p", { class: "lab-hazard caution", text: HAZARDS[code] || code })),
    ]);
  };

  function electronicsPanel() {
    const bench = state.bench.electronics;
    const parts = bench.parts.map((entry) => ({ ...entry }));
    const update = (next, extra = {}) => run(() => shop.setBoard(next, extra));
    const rows = parts.map((entry, index) => {
      const part = findPart(entry.id);
      const row = bench.result ? bench.result.parts.find((item) => item.id === entry.id) : null;
      return el("div", { class: "lab-row" }, [
        el("span", { "aria-hidden": "true", text: part ? part.icon : "▫" }),
        el("span", { class: "grow", text: `${part ? part.name : entry.id}${row && bench.powered ? ` · ${row.state}` : ""}` }),
        el("button", { class: "lab-x", type: "button", "aria-label": `One less ${part ? part.name : entry.id}`, text: "−", onclick: () => update(entry.count > 1 ? parts.map((item, i) => (i === index ? { ...item, count: item.count - 1 } : item)) : parts.filter((_, i) => i !== index)) }),
        el("span", { class: "lab-count", text: `×${entry.count}` }),
        el("button", { class: "lab-x", type: "button", "aria-label": `One more ${part ? part.name : entry.id}`, text: "+", onclick: () => update(parts.map((item, i) => (i === index ? { ...item, count: Math.min(50, item.count + 1) } : item))) }),
      ]);
    });
    const add = (id) => {
      const same = parts.find((item) => item.id === id);
      update(same ? parts.map((item) => (item.id === id ? { ...item, count: Math.min(50, item.count + 1) } : item)) : [...parts, { id, count: 1 }]);
    };
    const groups = Object.entries(KIND_NAMES)
      .map(([kind, name]) => [name, PARTS.filter((part) => part.kind === kind)])
      .filter(([, list]) => list.length);
    const series = el("input", { type: "checkbox", checked: bench.series, onchange: (event) => update(parts, { series: event.target.checked }) });
    const sun = el("input", { type: "checkbox", checked: bench.sun, onchange: (event) => update(parts, { sun: event.target.checked }) });
    const showLabels = el("input", { type: "checkbox", checked: labels, onchange: (event) => {
      labels = event.target.checked;
      if (world) world.setLabels(labels);
    } });
    return [
      card("Electronics bench", [
        rows.length ? el("div", { class: "lab-list" }, rows) : el("p", { class: "muted", text: "The board is empty. Add a power source and some parts, or try one below." }),
        el("div", { class: "row lab-toggles" }, [el("label", { class: "check" }, [series, " Batteries in series"]), el("label", { class: "check" }, [sun, " Sunny"]), el("label", { class: "check" }, [showLabels, " Labels"])]),
        el("div", { class: "row" }, [
          button(bench.powered ? "Power off" : "Power on", () => update(parts, { powered: !bench.powered }), { class: "primary", disabled: parts.length ? null : true }),
          button("Clear the board", () => update([], { powered: false })),
          button("Save as chip", () => saveSheet("chip"), { disabled: parts.length ? null : true }),
        ]),
        el("p", { class: "small muted", text: "Try one:" }),
        el("div", { class: "lab-chips" }, Object.entries(TRY_BUILDS).map(([name, build]) => el("button", { class: "lab-chip", type: "button", text: name, onclick: () => run(() => shop.circuit(build)) }))),
        el("details", { class: "lab-bin" }, [
          el("summary", { text: "Parts bin" }),
          ...groups.map(([name, list]) => el("div", {}, [el("p", { class: "small muted", text: name }), el("div", { class: "lab-chips" }, list.map((part) => el("button", { class: "lab-chip", type: "button", text: `${part.icon} ${part.name}`, onclick: () => add(part.id) })))])),
        ]),
      ]),
      bench.result && bench.powered ? readingsCard(bench.result) : null,
      picked && (picked.type === "part" || picked.type === "resistor") ? partCard(picked) : null,
    ];
  }

  const bands = (ohms) => el("span", { class: "lab-bands", "aria-label": `Colour bands ${resistorBands(ohms).map((band) => band.name).join(", ")}` }, resistorBands(ohms).map((band) => el("span", { style: { background: band.colour }, title: band.name })));

  const readingsCard = (result) =>
    card(result.works ? "✅ It works" : "⚠ Not working yet", [
      result.supply ? el("p", { class: "small", text: `${result.supply} · ${result.volts} V${result.regulated_by ? ` → ${result.rail_volts} V` : ""} · ${result.total_ma} mA · ${result.watts ?? 0} W` }) : null,
      result.runtime_text ? el("p", { text: result.runtime_text }) : null,
      el("div", { class: "lab-chips" }, result.parts.map((row) => el("span", { class: `lab-state ${row.state}`, text: `${row.icon} ${row.name}: ${row.state}` }))),
      ...result.resistors.map((item) => el("p", { class: "small" }, [bands(item.ohms), ` ${item.ohms >= 1000 ? `${item.ohms / 1000} kΩ` : `${item.ohms} Ω`} ${item.rating} for the ${item.for}`])),
      ...result.warnings.map((text) => el("p", { class: "lab-hazard warning", text })),
      ...result.tips.map((text) => el("p", { class: "small muted", text })),
    ]);

  const partCard = (what) => {
    if (what.type === "resistor") return card(`Resistor ${what.ohms >= 1000 ? `${what.ohms / 1000} kΩ` : `${what.ohms} Ω`}`, [el("p", {}, [bands(what.ohms), ` For the ${what.for}: it limits the current so the LED doesn't burn out.`]), el("p", { class: "small muted", text: resistorBands(what.ohms).map((band) => band.name).join(" · ") })]);
    const part = findPart(what.id);
    if (!part) return null;
    const row = state.bench.electronics.result ? state.bench.electronics.result.parts.find((item) => item.id === part.id) : null;
    return card(`${part.icon} ${part.name}`, [
      el("p", { class: "small", text: `${part.kind}${part.volts ? ` · ${part.volts} V` : ""}${part.milliamps ? ` · ${part.milliamps} mA` : ""}${part.capacity_mah ? ` · ${part.capacity_mah} mAh` : ""} · ${part.grams} g · about US$${part.price}` }),
      part.note ? el("p", { text: part.note }) : null,
      row && state.bench.electronics.powered ? el("p", { class: `lab-state ${row.state}`, text: `Now: ${row.state}${row.reason ? ` (${row.reason})` : ""}${row.milliamps ? `, ${row.milliamps} mA` : ""}` }) : null,
    ]);
  };

  function blueprintsPanel() {
    const list = shop.searchBlueprints(query, filter);
    const search = el("input", { type: "search", "aria-label": "Search blueprints", placeholder: "Search blueprints", value: query, onchange: (event) => {
      query = event.target.value;
      drawPanel();
    } });
    return [
      card("Blueprints", [
        el("p", { class: "small muted", text: "Save what's on the benches, reload it later, improve it as a new version, or drop a chip into another circuit." }),
        el("div", { class: "row" }, [
          button("Save the circuit as a chip", () => saveSheet("chip"), { disabled: state.bench.electronics.parts.length ? null : true }),
          button("Save the beaker as a mixture", () => saveSheet("mixture"), { disabled: state.bench.chemistry.items.length ? null : true }),
          button("Save both as an invention", () => saveSheet("invention"), { disabled: state.bench.electronics.parts.length || state.bench.chemistry.items.length ? null : true }),
        ]),
        search,
        el("div", { class: "lab-chips" }, [["", "All"], ...Object.entries(shop.BLUEPRINT_KINDS).map(([kind, name]) => [kind, `${name}s`])].map(([kind, name]) => el("button", { class: "lib-filter", type: "button", "aria-pressed": String(filter === kind), text: name, onclick: () => {
          filter = kind;
          drawPanel();
        } }))),
        list.length ? null : el("p", { class: "muted", text: state.blueprints.length ? "Nothing matches." : "No blueprints yet. Build or mix something, then save it." }),
      ]),
      ...list.map(blueprintCard),
    ];
  }

  const blueprintCard = (print) => {
    const open = selected === print.id;
    return el("section", { class: `card lab-print${open ? " selected" : ""}`, "data-id": print.id }, [
      el("h3", {}, [el("span", { class: "lab-swatch", style: { background: print.colour } }), ` ${print.name}`]),
      el("p", { class: "small muted", text: `${shop.BLUEPRINT_KINDS[print.kind]} · ${print.versions.length} version${print.versions.length === 1 ? "" : "s"} · by ${print.by}` }),
      el("p", { class: "small", text: print.summary }),
      print.notes ? el("p", { class: "small muted", text: print.notes }) : null,
      el("div", { class: "row" }, [
        button("Load", () => run(async () => {
          await shop.loadBlueprint(print.id);
          if (world) world.focus(print.kind === "mixture" ? "chemistry" : "electronics");
        }), { class: "primary" }),
        button("Improve with Jarvis", () => tellJarvis(`Improve the blueprint "${print.name}" (id ${print.id}): load it, make it better, and save it as a new version with notes on what changed.`)),
        print.kind === "chip" ? button("Add to circuit", () => run(() => shop.addChip(print.id))) : null,
        button("Delete", () => {
          if (confirm(`Delete ${print.name} and all its versions?`)) run(() => shop.removeBlueprint(print.id));
        }),
      ]),
      print.versions.length > 1
        ? el("details", {}, [
            el("summary", { text: "Versions" }),
            ...print.versions.map((version) => {
              const number = shop.versionNumber(print, version);
              return el("div", { class: "lab-row" }, [el("span", { class: "grow small", text: `v${number} · ${new Date(version.at).toLocaleDateString()} · ${version.by}${version.notes ? `: ${version.notes.slice(0, 80)}` : ""}` }), button("Load", () => run(() => shop.loadBlueprint(print.id, { version: number })))]);
            }),
          ])
        : null,
    ]);
  };

  function libraryPanel() {
    const found = shop.searchTutorials(query, topic, 60);
    const search = el("input", { type: "search", "aria-label": "Search tutorials", placeholder: "Search: database, emulator, ray tracer, Rust…", value: query, onchange: (event) => {
      query = event.target.value;
      drawPanel();
    } });
    return [
      card("Library: build your own X", [
        el("p", { class: "small muted", text: "Step-by-step guides for building technologies from scratch, from codecrafters-io/build-your-own-x (CC0, kept in FCC). Tap a topic, or a book stack in the box." }),
        search,
        el("div", { class: "lab-chips" }, [{ topic: "", count: 0 }, ...shop.topics()].map((row) => el("button", { class: "lib-filter", type: "button", "aria-pressed": String(topic === row.topic), text: row.topic ? `${row.topic} (${row.count})` : "All", onclick: () => {
          topic = row.topic;
          drawPanel();
        } }))),
      ]),
      card(`${found.length} tutorial${found.length === 1 ? "" : "s"}`, found.length ? found.map((row) => el("div", { class: "lab-tutorial" }, [
        el("a", { href: row.link, target: "_blank", rel: "noopener noreferrer", text: row.title }),
        el("p", { class: "small muted", text: `${row.topic} · ${row.language}${row.video ? " · video" : ""}` }),
        button("Ask Jarvis to build it", () => tellJarvis(`Let's build our own ${row.topic.toLowerCase()} following "${row.title}" (${row.language}, ${row.link}). Read it, plan the steps, and start it as a project.`)),
      ])) : [el("p", { class: "muted", text: "Nothing matches." })]),
    ];
  }

  function drawPanel() {
    const sections = room === "chemistry" ? chemistryPanel() : room === "electronics" ? electronicsPanel() : room === "blueprints" ? blueprintsPanel() : room === "library" ? libraryPanel() : overviewPanel();
    panel.replaceChildren(...sections.filter(Boolean), jarvisCard());
  }

  view.replaceChildren(
    boxNode,
    bar,
    panel
  );
  boxNode.append(el("div", { class: "lab-viewport" }, [canvas, el("div", { class: "lab-overlay" }, [back, where])]), status);
  drawBar();
  drawPanel();
  showJarvis();

  let stopped = false;
  (async () => {
    try {
      const { makeWorld } = await import("../../lab/world3d.js");
      if (stopped) return;
      world = makeWorld(canvas, {
        onFocus: (next) => {
          if (next !== room) setRoom(next);
        },
        onPick: (what) => {
          if (what.type === "blueprint") {
            selected = what.id;
            const print = shop.findBlueprint(what.id);
            if (print && world) world.setBlueprints(state.blueprints, print);
            if (room !== "blueprints") world.focus("blueprints");
            else drawPanel();
            return;
          }
          if (what.type === "topic") {
            topic = what.topic;
            query = "";
            if (room !== "library") world.focus("library");
            else drawPanel();
            return;
          }
          const target = what.type === "bottle" || what.type === "beaker" ? "chemistry" : "electronics";
          if (room !== target) world.focus(target);
          picked = what;
          drawPanel();
        },
      });
      world.setTopics(shop.topics());
      world.setBlueprints(state.blueprints);
      showBenches(false);
      if (room) world.focus(room);
      showJarvis();
    } catch (error) {
      status.textContent = `3D can't start on this device (${error.message}); the rooms below still work.`;
    }
  })();
  const unsubscribe = onChange((what) => {
    if (what === "bench") {
      showBenches(true);
      const editing = panel.contains(document.activeElement) && document.activeElement.tagName !== "BUTTON";
      if (!editing) drawPanel();
    } else if (what === "jarvis") showJarvis();
    else if (what === "blueprints") {
      if (world) world.setBlueprints(state.blueprints, selected ? shop.findBlueprint(selected) : null);
      if (room === "blueprints" || !room) drawPanel();
    }
  });
  return () => {
    stopped = true;
    unsubscribe();
    if (world) world.stop();
  };
}
