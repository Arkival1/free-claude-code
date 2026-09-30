/* FCC Studio Lab — a game-like science sandbox with real results.
   Pour chemicals into a beaker, make products and see every ingredient,
   forge and test materials, power up electronics, and ask the main AI to
   do any of it from the Lab chat. Studio calls FCCLab.render(ctx). */
(() => {
  "use strict";

  const MODES = [
    ["bench", "Chemistry", "⚗"],
    ["make", "Make", "🧴"],
    ["materials", "Materials", "🔩"],
    ["tech", "Tech", "🔌"],
    ["elements", "Elements", "⚛"],
    ["made", "Made", "📦"],
  ];
  const MODE_KEY = "fcc.lab.mode";
  const SHELVES = [
    ["all", "All"],
    ["acid", "Acids"],
    ["base", "Bases"],
    ["salt", "Salts"],
    ["metal", "Metals"],
    ["oxidizer", "Oxidisers"],
    ["indicator", "Indicators"],
    ["household", "Household"],
    ["surfactant", "Soaps"],
    ["oil", "Oils & waxes"],
    ["cosmetic", "Cosmetic"],
    ["compound", "Learned"],
  ];
  const CATEGORY_COLOURS = {
    "alkali-metal": "#ff6b6b",
    "alkaline-earth": "#ffa94d",
    transition: "#74c0fc",
    "post-transition": "#8ce99a",
    metalloid: "#63e6be",
    nonmetal: "#ffe066",
    halogen: "#da77f2",
    "noble-gas": "#b197fc",
    lanthanide: "#f783ac",
    actinide: "#e599f7",
  };
  const GAS_BUBBLES = { "a few bubbles": 6, fizzing: 18, lots: 34, violent: 60 };
  const SUGGESTIONS = [
    "Make shampoo",
    "Mix lead nitrate and potassium iodide",
    "Build a flashlight",
    "Make bronze and test it",
    "What happens if sodium goes in water?",
    "Make elephant toothpaste",
  ];

  // Kept between visits so the bench is as you left it.
  const state = {
    mode: readMode(),
    catalogue: null,
    shelf: "all",
    search: "",
    beaker: [],
    heat: false,
    flame: false,
    lastMix: null,
    product: null,
    materialParts: [],
    lastMaterial: null,
    techParts: [],
    series: true,
    lastBuild: null,
    chatAfter: 0,
    chatMessages: [],
    chatBusy: false,
  };

  let ctx = null;
  let stage = null;
  let chatLog = null;
  let chatTimer = null;

  function readMode() {
    try {
      const saved = localStorage.getItem(MODE_KEY);
      return MODES.some(([id]) => id === saved) ? saved : "bench";
    } catch {
      return "bench";
    }
  }

  function saveMode(mode) {
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch {
      /* private mode: remembering the tab is only a convenience */
    }
  }

  /* ------------------------------------------------------------ helpers */

  const h = (...args) => ctx.el(...args);
  // Optional pieces are null; the DOM would print them as "null".
  const clean = (nodes) => nodes.flat().filter((node) => node != null && node !== false);
  const SUBS = "₀₁₂₃₄₅₆₇₈₉";
  function pretty(formula) {
    let out = "";
    let previous = "";
    for (const char of String(formula || "")) {
      if (/\d/.test(char) && previous && /[A-Za-z)\]₀-₉]/.test(previous)) {
        out += SUBS[Number(char)];
      } else out += char;
      previous = out.slice(-1);
    }
    return out;
  }

  function hex(colour) {
    let value = String(colour || "#e3f2ff").replace("#", "");
    if (value.length === 3) value = value.split("").map((c) => c + c).join("");
    return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) || 0);
  }

  function blend(parts) {
    const used = parts.filter(([, weight]) => weight > 0);
    if (!used.length) return "#e3f2ff";
    const total = used.reduce((sum, [, weight]) => sum + weight, 0);
    const rgb = [0, 1, 2].map((i) =>
      Math.round(used.reduce((sum, [colour, weight]) => sum + hex(colour)[i] * weight, 0) / total)
    );
    return `#${rgb.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  }

  const pale = (colour) => {
    const [r, g, b] = hex(colour);
    return r > 215 && g > 225 && b > 225;
  };

  const rand = (min, max) => min + Math.random() * (max - min);
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function chemical(id) {
    const list = (state.catalogue && state.catalogue.chemicals) || [];
    return list.find((item) => item.id === id);
  }

  function element(symbol) {
    const list = (state.catalogue && state.catalogue.elements) || [];
    return list.find((item) => item.symbol === symbol);
  }

  function vial(colour, solid, size = "") {
    return h("span", { class: `vial ${solid ? "solid" : ""} ${size}`, "aria-hidden": "true" }, [
      h("span", { class: "vial-fill", style: `--fill:${colour}` }),
    ]);
  }

  function hazardBadges(hazards) {
    return (hazards || []).map((hazard) =>
      h("span", {
        class: `hazard ${typeof hazard === "string" ? hazard : hazard.code}`,
        title: typeof hazard === "string" ? hazard : hazard.text,
        text: typeof hazard === "string" ? hazard : hazard.code,
      })
    );
  }

  function modal(heading, nodes) {
    const box = h("div", { class: "lab-modal", role: "dialog", "aria-modal": "true", "aria-label": heading }, [
      h("div", { class: "lab-modal-card" }, [
        h("header", {}, [
          h("h3", { text: heading }),
          h("button", { class: "ghost-button", type: "button", "aria-label": "Close", text: "✕", onclick: () => box.remove() }),
        ]),
        ...nodes,
      ]),
    ]);
    box.addEventListener("click", (event) => {
      if (event.target === box) box.remove();
    });
    document.body.append(...clean([box]));
    return box;
  }

  function elementCard(item) {
    const flame = item.flame
      ? h("p", {}, [
          "Flame test: ",
          h("span", { class: "flame-swatch", style: `--flame:${item.flame.colour}` }),
          ` ${item.flame.name}`,
        ])
      : null;
    return modal(`${item.name} (${item.symbol})`, [
      h("div", { class: "element-hero", style: `--cat:${CATEGORY_COLOURS[item.category] || "#aaa"}` }, [
        h("span", { class: "element-number", text: item.number }),
        h("strong", { text: item.symbol }),
        h("span", { text: item.name }),
        h("small", { text: `${item.mass}` }),
      ]),
      h("p", { class: "muted", text: `${item.category.replace(/-/g, " ")} · ${item.state} at room temperature · group ${item.group || "f-block"}, period ${item.period}${item.radioactive ? " · radioactive ☢" : ""}` }),
      item.uses ? h("p", { text: item.uses }) : null,
      flame,
      h("div", { class: "row" }, [
        h("button", {
          class: "primary",
          type: "button",
          text: "Add to the beaker",
          onclick: () => {
            document.querySelector(".lab-modal")?.remove();
            addToBeaker({ id: item.symbol, name: item.name, colour: CATEGORY_COLOURS[item.category] || "#ccc", solid: item.state === "solid" });
            switchMode("bench");
          },
        }),
      ]),
    ]);
  }

  function ingredientCard(row) {
    const formula = row.formula || row.typical_formula;
    return modal(row.name, [
      formula
        ? h("p", { class: "formula-big" }, [
            pretty(formula),
            row.typical_formula ? h("small", { class: "muted", text: " (typical molecule)" }) : null,
          ])
        : h("p", { class: "muted", text: "A natural mixture with no single formula." }),
      row.purpose ? h("p", { text: row.purpose }) : null,
      h("p", { class: "muted", text: `${row.percent}% of the product · ${row.grams} g in this batch` }),
      elementBar(row.elements || []),
      h("div", { class: "element-chips" }, (row.elements || []).map(elementChip)),
      row.hazards && row.hazards.length ? h("div", { class: "row" }, hazardBadges(row.hazards)) : null,
    ]);
  }

  function elementChip(row) {
    return h("button", {
      class: "element-chip",
      type: "button",
      style: `--cat:${CATEGORY_COLOURS[row.category] || "#aaa"}`,
      title: `${row.name}: ${row.percent}% by mass`,
      onclick: () => {
        const found = element(row.symbol);
        if (found) elementCard(found);
      },
    }, [h("strong", { text: row.symbol }), h("span", { text: `${row.percent}%` })]);
  }

  function elementBar(rows) {
    return h(
      "div",
      { class: "element-bar", role: "img", "aria-label": rows.map((r) => `${r.name} ${r.percent}%`).join(", ") },
      rows.map((row) =>
        h("span", {
          style: `flex:${Math.max(row.percent, 0.4)};--cat:${CATEGORY_COLOURS[row.category] || "#aaa"}`,
          title: `${row.name} ${row.percent}%`,
          text: row.percent > 4 ? row.symbol : "",
        })
      )
    );
  }

  /* ------------------------------------------------------------ layout */

  async function render(context) {
    ctx = context;
    if (!state.catalogue) state.catalogue = await ctx.api("/studio/api/lab");
    if (!ctx.alive()) return;
    stage = h("div", { class: "lab-stage" });
    const modes = h(
      "div",
      { class: "lab-modes", role: "tablist", "aria-label": "Lab benches" },
      MODES.map(([id, label, icon]) =>
        h("button", {
          class: `lab-mode ${state.mode === id ? "active" : ""}`,
          type: "button",
          role: "tab",
          "aria-selected": state.mode === id ? "true" : "false",
          "data-mode": id,
          onclick: () => switchMode(id),
        }, [h("span", { class: "lab-mode-icon", text: icon }), h("span", { text: label })])
      )
    );
    const layout = h("div", { class: "lab" }, [
      h("div", { class: "lab-main" }, [modes, stage]),
      chatPanel(),
    ]);
    ctx.view.replaceChildren(...clean([layout]));
    drawMode();
    await refreshChat(true);
  }

  function switchMode(mode) {
    state.mode = mode;
    saveMode(mode);
    for (const button of document.querySelectorAll(".lab-mode")) {
      const on = button.dataset.mode === mode;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    }
    drawMode();
  }

  function drawMode() {
    if (!stage) return;
    const draw = {
      bench: drawBench,
      make: drawMake,
      materials: drawMaterials,
      tech: drawTech,
      elements: drawElements,
      made: drawMade,
    }[state.mode];
    stage.replaceChildren();
    draw();
  }

  /* ------------------------------------------------------------ chemistry */

  let beakerNode = null;
  let resultsNode = null;
  let contentsNode = null;

  function drawBench() {
    const list = h("div", { class: "shelf-list" });
    const search = h("input", {
      type: "search",
      placeholder: "Search the shelf…",
      "aria-label": "Search chemicals",
      value: state.search,
      oninput: () => {
        state.search = search.value;
        fillShelf(list);
      },
    });
    const chips = h(
      "div",
      { class: "chips shelf-chips" },
      SHELVES.map(([id, label]) =>
        h("button", {
          class: `chip ${state.shelf === id ? "on" : ""}`,
          type: "button",
          text: label,
          onclick: (event) => {
            state.shelf = id;
            for (const chip of chips.children) chip.classList.remove("on");
            event.currentTarget.classList.add("on");
            fillShelf(list);
          },
        })
      )
    );
    const lookup = h("input", { type: "text", placeholder: "Any chemical, e.g. caffeine", "aria-label": "Look up a chemical" });
    const lookupForm = h("form", {
      class: "row lookup",
      onsubmit: async (event) => {
        event.preventDefault();
        const name = lookup.value.trim();
        if (!name) return;
        try {
          const found = await ctx.post("/studio/api/lab/lookup", { name });
          if (found.source === "pubchem" && !chemical(found.id)) state.catalogue.chemicals.push(found);
          addToBeaker({ id: found.id, name: found.name, colour: found.colour, solid: found.state === "solid" });
          ctx.notify(found.source === "pubchem" ? `Learned ${found.name} (${pretty(found.formula)}) from PubChem.` : `${found.name} is on the shelf.`);
          lookup.value = "";
          fillShelf(list);
        } catch (error) {
          ctx.notify(error.message);
        }
      },
    }, [h("div", { class: "grow" }, [lookup]), h("button", { class: "secondary", type: "submit", text: "Find" })]);
    fillShelf(list);

    beakerNode = beakerView();
    contentsNode = h("div", { class: "contents" });
    resultsNode = h("section", { class: "card results" });
    const heat = toggle("🔥 Heat", state.heat, (on) => {
      state.heat = on;
      beakerNode.classList.toggle("heating", on);
    });
    const flame = toggle("🕯 Flame test", state.flame, (on) => {
      state.flame = on;
    });
    const controls = h("div", { class: "bench-controls" }, [
      h("button", { class: "primary mix-button", type: "button", text: "⚗ Mix", onclick: mix }),
      heat,
      flame,
      h("button", { class: "secondary", type: "button", text: "Empty", onclick: emptyBeaker }),
    ]);
    stage.append(...clean([
      h("div", { class: "bench-grid" }, [
        h("section", { class: "card shelf" }, [
          h("h2", { text: "Chemical shelf" }),
          search,
          chips,
          list,
          h("p", { class: "muted small", text: "Tap or drag a bottle into the beaker. Not here? Look it up:" }),
          lookupForm,
        ]),
        h("section", { class: "card bench" }, [
          h("h2", { text: "Bench" }),
          beakerNode,
          contentsNode,
          controls,
        ]),
        resultsNode,
      ])
    ]));
    drawContents();
    if (state.lastMix) showMix(state.lastMix, false);
    else resultsNode.append(...clean([h("h2", { text: "What happens" }), h("p", { class: "muted", text: "Add two or more things and press Mix. Try vinegar and baking soda, or lead nitrate and potassium iodide." })]));
  }

  function toggle(label, on, change) {
    const button = h("button", {
      class: `secondary toggle ${on ? "on" : ""}`,
      type: "button",
      "aria-pressed": on ? "true" : "false",
      text: label,
      onclick: () => {
        const next = !button.classList.contains("on");
        button.classList.toggle("on", next);
        button.setAttribute("aria-pressed", next ? "true" : "false");
        change(next);
      },
    });
    return button;
  }

  function fillShelf(list) {
    const words = state.search.toLowerCase().split(/\s+/).filter(Boolean);
    const items = state.catalogue.chemicals.filter((item) => {
      if (state.shelf !== "all") {
        const kind = state.shelf === "oil" ? item.kind === "oil" : item.kind === state.shelf;
        if (!kind) return false;
      }
      const text = `${item.name} ${item.formula} ${item.kind} ${(item.aliases || []).join(" ")}`.toLowerCase();
      return words.every((word) => text.includes(word));
    });
    list.replaceChildren(...clean([
      ...items.slice(0, 160).map((item) =>
        h("button", {
          class: "bottle",
          type: "button",
          draggable: "true",
          title: item.note || item.name,
          ondragstart: (event) => event.dataTransfer.setData("text/plain", item.id),
          onclick: () => addToBeaker({ id: item.id, name: item.name, colour: item.colour, solid: item.state === "solid" }),
        }, [
          vial(item.colour, item.state === "solid"),
          h("span", { class: "bottle-name", text: item.name }),
          item.formula ? h("span", { class: "bottle-formula", text: pretty(item.formula) }) : null,
          item.hazards && item.hazards.length ? h("span", { class: "bottle-warn", title: item.hazards.map((x) => x.text).join("\n"), text: "⚠" }) : null,
        ])
      ),
      items.length ? null : ctx.el("p", { class: "muted", text: "Nothing on the shelf matches. Look it up below." })
    ]));
  }

  function beakerView() {
    const node = h("div", { class: `beaker-stage ${state.heat ? "heating" : ""}` }, [
      h("div", { class: "gas-cloud" }),
      h("div", { class: "foam" }),
      h("div", { class: "pour" }, [h("span", { class: "pour-vial" }), h("span", { class: "pour-stream" })]),
      h("div", { class: "beaker", "aria-label": "Beaker" }, [
        h("div", { class: "beaker-marks" }, ["250", "200", "150", "100", "50"].map((mark) => h("span", { text: mark }))),
        h("div", { class: "liquid" }, [
          h("div", { class: "oil-layer" }),
          h("div", { class: "bubbles" }),
          h("div", { class: "cloud" }),
          h("div", { class: "sediment" }),
        ]),
        h("div", { class: "solids" }),
      ]),
      h("div", { class: "burner" }, [h("div", { class: "flame" }), h("div", { class: "burner-base" })]),
      h("div", { class: "thermo", title: "Temperature" }, [h("div", { class: "thermo-fill" }), h("span", { class: "thermo-read", text: "20 °C" })]),
      h("div", { class: "ph-meter", title: "pH" }, [h("span", { class: "ph-read", text: "pH —" })]),
      h("div", { class: "steam" }),
    ]);
    node.addEventListener("dragover", (event) => {
      event.preventDefault();
      node.classList.add("drop");
    });
    node.addEventListener("dragleave", () => node.classList.remove("drop"));
    node.addEventListener("drop", (event) => {
      event.preventDefault();
      node.classList.remove("drop");
      const id = event.dataTransfer.getData("text/plain");
      const item = chemical(id) || element(id);
      if (item) addToBeaker({ id: item.id || item.symbol, name: item.name, colour: item.colour || CATEGORY_COLOURS[item.category], solid: item.state === "solid" });
    });
    setTimeout(() => settleLiquid(false), 0);
    return node;
  }

  function addToBeaker(item) {
    if (state.beaker.length >= 12) {
      ctx.notify("The beaker holds 12 things at once.");
      return;
    }
    const existing = state.beaker.find((entry) => entry.id === item.id);
    if (existing) existing.amount += item.solid ? 1 : 10;
    else state.beaker.push({ ...item, amount: item.solid ? 2 : 20 });
    state.lastMix = null;
    drawContents();
    pour(item);
  }

  async function pour(item) {
    if (!beakerNode) return;
    const pourNode = beakerNode.querySelector(".pour");
    pourNode.style.setProperty("--pour", item.colour || "#e3f2ff");
    pourNode.classList.toggle("powder", Boolean(item.solid));
    pourNode.classList.remove("pouring");
    void pourNode.offsetWidth;
    pourNode.classList.add("pouring");
    await wait(650);
    settleLiquid(true);
    beakerNode.querySelector(".liquid").classList.add("ripple");
    await wait(600);
    beakerNode.querySelector(".liquid")?.classList.remove("ripple");
  }

  function beakerVolume() {
    return state.beaker.reduce((sum, item) => sum + (item.solid ? item.amount * 0.4 : item.amount), 0);
  }

  function settleLiquid(animate) {
    if (!beakerNode) return;
    const liquid = beakerNode.querySelector(".liquid");
    const volume = beakerVolume();
    const level = Math.min(92, volume ? 6 + (volume / 250) * 86 : 0);
    liquid.style.height = `${level}%`;
    liquid.style.transition = animate ? "" : "none";
    const colours = state.beaker
      .filter((item) => !item.solid)
      .map((item) => [item.colour || "#e3f2ff", pale(item.colour) ? item.amount * 0.2 : item.amount]);
    liquid.style.setProperty("--liquid", blend(colours));
    liquid.style.setProperty("--alpha", colours.some(([c]) => !pale(c)) ? "0.78" : "0.35");
    const solids = beakerNode.querySelector(".solids");
    solids.replaceChildren(...clean([
      ...state.beaker
        .filter((item) => item.solid)
        .flatMap((item) =>
          Array.from({ length: Math.min(14, 3 + Math.round(item.amount * 2)) }, () =>
            h("span", { class: "grain", style: `--grain:${item.colour || "#ddd"};left:${rand(8, 88)}%;bottom:${rand(2, 10)}px;transform:rotate(${rand(0, 90)}deg)` })
          )
        )
    ]));
  }

  function drawContents() {
    if (!contentsNode) return;
    if (!state.beaker.length) {
      contentsNode.replaceChildren(...clean([h("p", { class: "muted small", text: "The beaker is empty." })]));
      return;
    }
    contentsNode.replaceChildren(...clean([
      ...state.beaker.map((item, index) => {
        const amount = h("input", {
          type: "number",
          min: "0.1",
          max: "2000",
          step: item.solid ? "0.5" : "5",
          value: String(item.amount),
          "aria-label": `Amount of ${item.name}`,
          onchange: () => {
            const value = Number(amount.value);
            if (value > 0) {
              item.amount = value;
              state.lastMix = null;
              settleLiquid(true);
            }
          },
        });
        return h("div", { class: "content-row" }, [
          vial(item.colour, item.solid, "small"),
          h("span", { class: "grow", text: item.name }),
          amount,
          h("span", { class: "unit", text: item.solid ? "g" : "mL" }),
          h("button", {
            class: "ghost-button small",
            type: "button",
            "aria-label": `Remove ${item.name}`,
            text: "✕",
            onclick: () => {
              state.beaker.splice(index, 1);
              state.lastMix = null;
              drawContents();
              resetEffects();
              settleLiquid(true);
            },
          }),
        ]);
      })
    ]));
  }

  function emptyBeaker() {
    state.beaker = [];
    state.lastMix = null;
    drawContents();
    resetEffects();
    settleLiquid(true);
    resultsNode.replaceChildren(...clean([h("h2", { text: "What happens" }), h("p", { class: "muted", text: "The beaker is clean." })]));
  }

  function resetEffects() {
    if (!beakerNode) return;
    beakerNode.className = `beaker-stage ${state.heat ? "heating" : ""}`;
    for (const selector of [".bubbles", ".cloud", ".gas-cloud", ".steam"]) beakerNode.querySelector(selector).replaceChildren();
    beakerNode.querySelector(".sediment").style.height = "0";
    beakerNode.querySelector(".foam").style.height = "0";
    beakerNode.querySelector(".oil-layer").style.height = "0";
    beakerNode.querySelector(".flame").style.removeProperty("--flame");
    beakerNode.querySelector(".thermo-fill").style.height = "20%";
    beakerNode.querySelector(".thermo-read").textContent = "20 °C";
    beakerNode.querySelector(".ph-read").textContent = "pH —";
  }

  async function mix() {
    if (!state.beaker.length) {
      ctx.notify("Put something in the beaker first.");
      return;
    }
    const button = stage.querySelector(".mix-button");
    button.disabled = true;
    try {
      const result = await ctx.post("/studio/api/lab/mix", {
        items: state.beaker.map((item) => ({ id: item.id, amount: item.amount })),
        heat: state.heat,
        flame: state.flame,
      });
      state.lastMix = result;
      await showMix(result, true);
    } catch (error) {
      ctx.notify(error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function showMix(result, animate) {
    drawResults(result);
    if (!beakerNode) return;
    resetEffects();
    const vessel = result.vessel;
    const liquid = beakerNode.querySelector(".liquid");
    if (animate) {
      beakerNode.scrollIntoView({ block: "center", behavior: "smooth" });
      beakerNode.classList.add("stirring");
      await wait(500);
      beakerNode.classList.remove("stirring");
    }
    const steps = vessel.colour_steps && vessel.colour_steps.length ? vessel.colour_steps : [vessel.colour];
    for (const colour of steps) {
      liquid.style.setProperty("--liquid", colour);
      liquid.style.setProperty("--alpha", pale(colour) ? String(Math.min(0.5, vessel.opacity)) : String(Math.max(0.55, vessel.opacity)));
      if (animate && steps.length > 1) await wait(1100);
    }
    const effects = new Set(vessel.effects || []);
    for (const gas of vessel.gases || []) bubbles(gas, animate);
    const coloured = (vessel.gases || []).filter((gas) => !pale(gas.colour));
    if (coloured.length) {
      const cloud = beakerNode.querySelector(".gas-cloud");
      cloud.style.setProperty("--gas", coloured[0].colour);
      cloud.append(...clean([...Array.from({ length: 8 }, (_, i) => h("span", { style: `left:${10 + i * 10}%;animation-delay:${i * 0.3}s` }))]));
    }
    if (vessel.precipitates && vessel.precipitates.length) precipitate(vessel.precipitates, animate);
    if (vessel.foam > 0) {
      const foam = beakerNode.querySelector(".foam");
      foam.style.setProperty("--foam", vessel.colour);
      foam.style.height = `${Math.round(vessel.foam * (effects.has("elephant-toothpaste") ? 210 : 40))}px`;
      beakerNode.classList.toggle("erupting", effects.has("elephant-toothpaste"));
    }
    const oil = (vessel.layers || []).find((layer) => layer.name === "oil layer");
    if (oil) {
      const layer = beakerNode.querySelector(".oil-layer");
      layer.style.setProperty("--oil", oil.colour);
      layer.style.height = `${Math.round((oil.ml / Math.max(vessel.volume_ml, 1)) * 100)}%`;
    }
    if (vessel.flame) {
      beakerNode.classList.add("flaming");
      beakerNode.querySelector(".flame").style.setProperty("--flame", vessel.flame.colour);
    }
    if (state.heat) beakerNode.classList.add("heating");
    const temperature = vessel.temperature_c;
    beakerNode.querySelector(".thermo-fill").style.height = `${Math.max(4, Math.min(100, ((temperature + 20) / 140) * 100))}%`;
    beakerNode.querySelector(".thermo-read").textContent = `${Math.round(temperature)} °C`;
    beakerNode.classList.toggle("hot", temperature > 45);
    beakerNode.classList.toggle("cold", temperature < 8);
    if (temperature > 60 || vessel.boiling) {
      beakerNode.querySelector(".steam").append(...clean([...Array.from({ length: 6 }, (_, i) => h("span", { style: `left:${20 + i * 11}%;animation-delay:${i * 0.4}s` }))]));
    }
    beakerNode.querySelector(".ph-read").textContent = vessel.ph == null ? "pH —" : `pH ${vessel.ph.toFixed(1)}`;
    beakerNode.querySelector(".ph-meter").style.setProperty("--ph", phColour(vessel.ph));
    for (const effect of ["violent", "glow", "dazzle", "slime", "emulsion", "curdled", "soap"]) {
      beakerNode.classList.toggle(effect, effects.has(effect));
    }
    const solids = beakerNode.querySelector(".solids");
    solids.replaceChildren(...clean([
      ...(vessel.solids || []).flatMap((solid) =>
        Array.from({ length: Math.min(16, 3 + Math.round(solid.grams * 3)) }, () =>
          h("span", { class: "grain", style: `--grain:${solid.colour};left:${rand(8, 88)}%;bottom:${rand(2, 10)}px;transform:rotate(${rand(0, 90)}deg)` })
        )
      )
    ]));
  }

  function phColour(ph) {
    if (ph == null) return "#7fa9ba";
    const stops = ["#e53935", "#fb8c00", "#fdd835", "#43a047", "#1e88e5", "#3949ab", "#8e24aa"];
    return stops[Math.max(0, Math.min(stops.length - 1, Math.floor((ph / 14) * stops.length)))];
  }

  function bubbles(gas, animate) {
    const holder = beakerNode.querySelector(".bubbles");
    const count = GAS_BUBBLES[gas.level] || 10;
    const fast = gas.level === "violent" ? 0.6 : gas.level === "lots" ? 1 : 1.8;
    holder.append(...clean([
      ...Array.from({ length: count }, () =>
        h("span", {
          style: `left:${rand(5, 92)}%;width:${rand(4, 11)}px;height:${rand(4, 11)}px;animation-duration:${rand(fast, fast * 2)}s;animation-delay:${animate ? rand(0, 1.6) : 0}s;--bubble:${pale(gas.colour) ? "rgba(255,255,255,.75)" : gas.colour}`,
        })
      )
    ]));
  }

  async function precipitate(list, animate) {
    const cloud = beakerNode.querySelector(".cloud");
    const main = list[0];
    cloud.append(...clean([
      ...Array.from({ length: 40 }, () =>
        h("span", { style: `left:${rand(3, 95)}%;top:${rand(0, 60)}%;--ppt:${main.colour};animation-delay:${animate ? rand(0, 1.2) : 0}s;animation-duration:${rand(2.2, 4)}s` })
      )
    ]));
    const sediment = beakerNode.querySelector(".sediment");
    const grams = list.reduce((sum, p) => sum + (p.grams || 0), 0);
    sediment.style.setProperty("--ppt", main.colour);
    if (animate) await wait(1400);
    sediment.style.height = `${Math.max(6, Math.min(28, 6 + grams * 30))}%`;
  }

  function drawResults(result) {
    const vessel = result.vessel;
    const facts = [
      ["Temperature", `${Math.round(vessel.temperature_c)} °C`],
      ["pH", vessel.ph == null ? "—" : vessel.ph.toFixed(1)],
      ["Volume", `${vessel.volume_ml} mL`],
    ];
    resultsNode.replaceChildren(...clean([
      h("h2", { text: "What happens" }),
      h("p", { class: "summary", text: result.summary }),
      result.prediction
        ? h("p", { class: "prediction" }, [h("strong", { text: "AI prediction · " }), result.prediction.happens || ""])
        : null,
      h("div", { class: "facts" }, facts.map(([label, value]) => h("div", { class: "fact" }, [h("span", { text: label }), h("strong", { text: value })]))),
      result.reactions.length
        ? h("div", { class: "equations" }, result.reactions.map((reaction) =>
            h("div", { class: "equation" }, [h("code", { text: reaction.equation }), h("small", { text: [reaction.kind, reaction.note].filter(Boolean).join(" — ") })])
          ))
        : null,
      result.observations.length ? h("ul", { class: "observations" }, result.observations.map((text) => h("li", { text }))) : null,
      result.products.length
        ? h("div", { class: "products" }, [
            h("h3", { text: "Made" }),
            ...result.products.map((product) =>
              h("div", { class: "product-row" }, [
                h("strong", { text: product.pretty || product.formula }),
                h("span", { class: "grow", text: product.name }),
                h("span", { class: "muted", text: product.grams ? `${product.grams} g` : `${product.moles} mol` }),
              ])
            ),
          ])
        : null,
      result.dissolved && result.dissolved.length
        ? h("p", { class: "muted small", text: `Still dissolved: ${result.dissolved.map((ion) => ion.pretty).join(", ")}` })
        : null,
      result.hazards.length
        ? h("div", { class: "hazards" }, result.hazards.map((hazard) => h("div", { class: `hazard-line ${hazard.level}`, text: hazard.text })))
        : null,
      result.unknown && result.unknown.length ? h("p", { class: "muted", text: `Not recognised: ${result.unknown.join(", ")}` }) : null,
      h("div", { class: "row" }, [
        h("button", {
          class: "secondary",
          type: "button",
          text: "Save to Made",
          onclick: async () => {
            const name = result.ingredients.map((item) => item.name.split(" (")[0]).join(" + ").slice(0, 110);
            await ctx.post("/studio/api/lab/projects", { name, kind: "mix", data: result });
            ctx.notify("Saved to Made.");
          },
        }),
      ])
    ]));
  }

  /* ------------------------------------------------------------ make */

  function drawMake() {
    const input = h("input", { type: "text", placeholder: "Shampoo, bath bomb, toothpaste, a flashlight…", "aria-label": "What should the Lab make?" });
    const form = h("form", {
      class: "row make-form",
      onsubmit: (event) => {
        event.preventDefault();
        make(input.value);
      },
    }, [h("div", { class: "grow" }, [input]), h("button", { class: "primary", type: "submit", text: "Make it" })]);
    const chips = h("div", { class: "chips" }, [
      ...state.catalogue.products.map((item) => h("button", { class: "chip", type: "button", text: item.name, onclick: () => make(item.name) })),
      ...state.catalogue.builds.map((item) => h("button", { class: "chip tech-chip", type: "button", text: `🔌 ${item.name}`, onclick: () => make(item.name) })),
    ]);
    const holder = h("div", { class: "product-holder" });
    stage.append(...clean([
      h("section", { class: "card" }, [
        h("h2", { text: "Make something" }),
        h("p", { class: "muted", text: "The Lab uses real formulas: every ingredient, its molecule, and what the whole product is made of, element by element. Anything without a recipe is written by the Lab's AI from the shelf." }),
        form,
        chips,
      ]),
      holder
    ]));
    if (state.product) showProduct(state.product, holder, false);
  }

  async function make(request) {
    if (!request.trim()) return;
    const holder = stage.querySelector(".product-holder");
    if (holder) holder.replaceChildren(...clean([h("section", { class: "card making" }, [h("div", { class: "spinner" }), h("p", { text: `Making ${request}…` })])]));
    try {
      const project = await ctx.post("/studio/api/lab/make", { request });
      openProject(project, true);
    } catch (error) {
      ctx.notify(error.message);
      if (holder) holder.replaceChildren();
    }
  }

  function openProject(project, animate) {
    if (project.kind === "product") {
      state.product = project;
      if (state.mode !== "make") switchMode("make");
      showProduct(project, stage.querySelector(".product-holder"), animate);
    } else if (project.kind === "build") {
      state.lastBuild = project.data;
      state.techParts = (project.data.bill || []).map((part) => ({ id: part.id, count: part.count || 1 }));
      state.series = project.data.series !== false;
      if (state.mode !== "tech") switchMode("tech");
      else drawMode();
    } else if (project.kind === "material") {
      state.lastMaterial = project.data;
      state.materialParts = (project.data.material.composition || []).map((part) => ({ id: part.part, percent: part.percent }));
      if (state.mode !== "materials") switchMode("materials");
      else drawMode();
    } else {
      state.lastMix = project.data;
      state.beaker = (project.data.ingredients || []).map((item) => ({ id: item.id, name: item.name, colour: item.colour, amount: item.amount, solid: item.unit === "g" }));
      if (state.mode !== "bench") switchMode("bench");
      else drawMode();
      if (animate && state.lastMix) showMix(state.lastMix, true);
    }
  }

  // Pale ingredients (most are white or clear) get a hue of their own, so
  // every one stands out as a layer in the bottle; the real colour stays on
  // its swatch.
  const layerColour = (row, index) =>
    pale(row.colour) || row.colour === "#f5f5f5" ? `hsl(${(index * 47 + 190) % 360} 70% 62%)` : row.colour;

  async function showProduct(project, holder, animate) {
    if (!holder) return;
    const data = project.data;
    const bands = h("div", { class: "bands" });
    const layers = h("div", { class: "layers" });
    const container = h("div", { class: `container xray ${data.container || "bottle"}`, style: `--product:${data.colour}` }, [
      h("div", { class: "container-cap" }),
      h("div", { class: "container-body" }, [
        h("div", { class: "container-fill" }),
        layers,
        h("div", { class: "container-label" }, [h("strong", { text: data.name }), h("span", { text: `${data.batch_g} g` })]),
      ]),
    ]);
    const view = h("button", {
      class: "secondary xray-toggle",
      type: "button",
      text: "Show it mixed",
      onclick: () => {
        const inside = container.classList.toggle("xray");
        view.textContent = inside ? "Show it mixed" : "See every ingredient inside";
      },
    });
    const table = h("table", { class: "ingredients" }, [
      h("thead", {}, [h("tr", {}, ["Ingredient", "Molecule", "%", "g", "Why"].map((label) => h("th", { text: label })))]),
      h("tbody", {}, data.ingredients.map((row) =>
        h("tr", { tabindex: "0", onclick: () => ingredientCard(row), onkeydown: (event) => event.key === "Enter" && ingredientCard(row) }, [
          h("td", {}, [vial(row.colour, (chemical(row.id) || {}).state === "solid", "small"), ` ${row.name}`]),
          h("td", { class: "mono", text: pretty(row.formula || row.typical_formula || "—") }),
          h("td", { text: String(row.percent) }),
          h("td", { text: String(row.grams) }),
          h("td", { class: "muted", text: row.purpose }),
        ])
      )),
    ]);
    const card = h("section", { class: "card product" }, [
      h("div", { class: "product-head" }, [
        h("h2", { text: data.name }),
        h("span", { class: "pill", text: data.source === "ai" ? "Written by the Lab's AI" : "Real formula" }),
        project.made_by && project.made_by !== "You" ? h("span", { class: "pill", text: `Made by ${project.made_by}` }) : null,
      ]),
      h("div", { class: "product-show" }, [h("div", { class: "container-column" }, [container, view]), bands]),
      h("h3", { text: "Every element inside" }),
      elementBar(data.elements),
      h("div", { class: "element-chips" }, data.elements.map(elementChip)),
      h("h3", { text: "Ingredients (tap one to see its molecule)" }),
      h("div", { class: "table-wrap" }, [table]),
      data.ph ? h("p", {}, [h("strong", { text: "pH: " }), data.ph]) : null,
      data.steps && data.steps.length ? h("div", {}, [h("h3", { text: "How to make it" }), h("ol", { class: "steps" }, data.steps.map((step) => h("li", { text: step })))]) : null,
      data.safety ? h("p", { class: "hazard-line warning", text: data.safety }) : null,
      data.test
        ? h("button", {
            class: "secondary",
            type: "button",
            text: "⚗ Test it on the bench",
            onclick: () => {
              state.beaker = data.test.ingredients.map((item) => ({ id: item.id, name: item.name, colour: item.colour, amount: item.amount, solid: item.unit === "g" }));
              state.lastMix = data.test;
              switchMode("bench");
              showMix(data.test, true);
            },
          })
        : null,
    ]);
    holder.replaceChildren(...clean([card]));
    const rows = data.ingredients;
    for (const [index, row] of rows.entries()) {
      const band = h("button", {
        class: "band",
        type: "button",
        style: `--band:${layerColour(row, index)};flex:${Math.max(Math.sqrt(row.percent), 0.9)}`,
        title: `${row.name}: ${row.percent}%`,
        onclick: () => ingredientCard(row),
      }, [vial(row.colour, (chemical(row.id) || {}).state === "solid", "small"), h("span", { class: "band-name grow", text: row.name.split(" (")[0] }), h("span", { class: "band-pct", text: `${row.percent}%` })]);
      bands.append(...clean([band]));
      layers.append(
        h("button", {
          class: "layer",
          type: "button",
          title: `${row.name}: ${row.percent}%`,
          "aria-label": `${row.name}, ${row.percent}%`,
          style: `--layer:${layerColour(row, index)};flex:${Math.max(Math.sqrt(row.percent), 0.9)}`,
          onclick: () => ingredientCard(row),
        }, [row.percent >= 5 ? h("span", { text: row.name.split(" (")[0] }) : null].filter(Boolean))
      );
      if (animate) {
        band.classList.add("incoming");
        container.style.setProperty("--level", `${Math.round(((index + 1) / rows.length) * 100)}%`);
        await wait(Math.min(260, 1800 / rows.length));
        band.classList.remove("incoming");
      }
    }
    container.style.setProperty("--level", "100%");
    container.classList.add("filled");
  }

  /* ------------------------------------------------------------ materials */

  function drawMaterials() {
    const picked = h("div", { class: "picked" });
    const grid = h("div", { class: "material-grid" });
    const groups = {};
    for (const item of state.catalogue.materials) (groups[item.category] ||= []).push(item);
    for (const [category, items] of Object.entries(groups)) {
      grid.append(...clean([
        h("h3", { text: category }),
        h("div", { class: "chips" }, items.map((item) =>
          h("button", {
            class: "chip material-chip",
            type: "button",
            title: item.uses || item.name,
            onclick: () => {
              if (state.materialParts.some((part) => part.id === item.id)) return;
              state.materialParts.push({ id: item.id, percent: state.materialParts.length ? 10 : 90 });
              drawPicked(picked);
            },
          }, [h("span", { class: "swatch", style: `--swatch:${item.colour}` }), item.name])
        ))
      ]));
    }
    const result = h("section", { class: "card forge-result" });
    stage.append(...clean([
      h("div", { class: "materials-grid" }, [
        h("section", { class: "card" }, [h("h2", { text: "Materials" }), h("p", { class: "muted small", text: "Pick materials, set how much of each, and forge. Known recipes become real alloys (88% copper + 12% tin = bronze)." }), grid]),
        h("div", { class: "forge-column" }, [
          h("section", { class: "card" }, [
            h("h2", { text: "Forge" }),
            picked,
            h("div", { class: "row" }, [
              h("button", { class: "primary", type: "button", text: "🔥 Forge", onclick: () => forge(result) }),
              h("button", { class: "secondary", type: "button", text: "Clear", onclick: () => { state.materialParts = []; drawPicked(picked); } }),
            ]),
          ]),
          result,
        ]),
      ])
    ]));
    drawPicked(picked);
    if (state.lastMaterial) showMaterial(state.lastMaterial, result, false);
  }

  function drawPicked(picked) {
    if (!state.materialParts.length) {
      picked.replaceChildren(...clean([h("p", { class: "muted small", text: "Nothing picked yet." })]));
      return;
    }
    picked.replaceChildren(...clean([
      ...state.materialParts.map((part, index) => {
        const item = state.catalogue.materials.find((m) => m.id === part.id) || { name: part.id, colour: "#999" };
        const number = h("input", { type: "number", min: "0", max: "100", step: "0.1", value: String(part.percent), "aria-label": `Percent of ${item.name}` });
        const slider = h("input", { type: "range", min: "0", max: "100", step: "0.5", value: String(part.percent), "aria-label": `Percent of ${item.name}` });
        slider.addEventListener("input", () => {
          part.percent = Number(slider.value);
          number.value = slider.value;
        });
        number.addEventListener("change", () => {
          part.percent = Number(number.value);
          slider.value = number.value;
        });
        return h("div", { class: "picked-row" }, [
          h("span", { class: "swatch", style: `--swatch:${item.colour}` }),
          h("span", { class: "grow", text: item.name }),
          slider,
          number,
          h("span", { text: "%" }),
          h("button", { class: "ghost-button small", type: "button", text: "✕", "aria-label": `Remove ${item.name}`, onclick: () => { state.materialParts.splice(index, 1); drawPicked(picked); } }),
        ]);
      })
    ]));
  }

  async function forge(result) {
    if (!state.materialParts.length) {
      ctx.notify("Pick at least one material.");
      return;
    }
    try {
      const made = await ctx.post("/studio/api/lab/material", { parts: state.materialParts });
      state.lastMaterial = made;
      showMaterial(made, result, true);
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  function bar(label, value, max, text, log = false) {
    const share = log ? Math.log10(1 + value) / Math.log10(1 + max) : value / max;
    return h("div", { class: "prop" }, [
      h("span", { text: label }),
      h("div", { class: "prop-bar" }, [h("i", { style: `width:${Math.max(2, Math.min(100, share * 100))}%` })]),
      h("strong", { text }),
    ]);
  }

  function showMaterial(made, holder, animate) {
    const material = made.material;
    const rig = h("div", { class: "rig" });
    const ingot = h("div", { class: `ingot ${animate ? "forging" : ""}`, style: `--metal:${material.colour}` }, [h("span", { text: material.name })]);
    holder.replaceChildren(...clean([
      h("div", { class: "product-head" }, [
        h("h2", { text: material.name }),
        h("span", { class: "pill", text: made.known ? "Real alloy" : "New blend (estimate)" }),
      ]),
      ingot,
      h("p", { class: "muted", text: made.note }),
      material.uses ? h("p", { text: material.uses }) : null,
      h("div", { class: "props" }, [
        bar("Strength", material.strength, 5000, `${material.strength} MPa`, true),
        bar("Stiffness", material.stiffness, 1100, `${material.stiffness} GPa`, true),
        bar("Density", material.density, 22, `${material.density} g/cm³`),
        bar("Melts", material.melts, 3700, `${material.melts} °C`),
        bar("Heat flow", material.conducts_heat, 5000, `${material.conducts_heat} W/m·K`, true),
        bar("Hardness", material.hardness, 10, `${material.hardness} Mohs`),
        bar("Stretch", material.stretch, 700, `${material.stretch}%`, true),
      ]),
      h("h3", { text: "Test rigs" }),
      h("div", { class: "chips" }, [
        ["Pull test", () => pullTest(rig, made)],
        ["Float test", () => floatTest(rig, made)],
        ["Heat test", () => heatTest(rig, made)],
        ["Electric test", () => electricTest(rig, made)],
      ].map(([label, run]) => h("button", { class: "chip", type: "button", text: label, onclick: run }))),
      rig
    ]));
    if (animate) setTimeout(() => ingot.classList.remove("forging"), 1400);
  }

  function pullTest(rig, made) {
    const test = made.tests.pull;
    const points = test.curve;
    const maxStrain = Math.max(...points.map((p) => p.strain_percent), 0.01);
    const maxStress = Math.max(...points.map((p) => p.stress_mpa), 1);
    const path = points.map((p, i) => `${i ? "L" : "M"}${(p.strain_percent / maxStrain) * 280 + 10},${150 - (p.stress_mpa / maxStress) * 130}`).join(" ");
    const svg = `<svg viewBox="0 0 300 160" class="curve" role="img" aria-label="Stress-strain curve"><line x1="10" y1="150" x2="295" y2="150"/><line x1="10" y1="10" x2="10" y2="150"/><path d="${path}"/><text x="200" y="145">strain ${maxStrain}%</text><text x="14" y="20">${maxStress} MPa</text></svg>`;
    rig.replaceChildren(...clean([
      h("div", { class: `specimen ${test.brittle ? "brittle" : "ductile"}`, style: `--metal:${made.material.colour}` }, [h("span"), h("span")]),
      h("div", { html: svg }),
      h("p", { text: `It ${test.word} at ${test.breaks_at_mpa} MPa after stretching ${test.stretch_percent}%.` })
    ]));
  }

  function floatTest(rig, made) {
    const floats = made.tests.float.floats_in_water;
    rig.replaceChildren(...clean([
      h("div", { class: "tank" }, [h("div", { class: `block ${floats ? "floats" : "sinks"}`, style: `--metal:${made.material.colour}` })]),
      h("p", { text: `${made.tests.float.text}: its density is ${made.material.density} g/cm³ (water is 1.0).` })
    ]));
  }

  function heatTest(rig, made) {
    const melts = made.tests.heat.melts_c;
    rig.replaceChildren(...clean([
      h("div", { class: "heat-rig", style: `--metal:${made.material.colour};--melt:${Math.min(1, melts / 3700)}` }, [h("div", { class: "heat-block" }), h("div", { class: "heat-flame" })]),
      h("p", { text: `${made.tests.heat.text} ${melts > 1200 ? "Glows red-hot long before it melts." : melts < 300 ? "A kitchen oven would soften it." : ""}` })
    ]));
  }

  function electricTest(rig, made) {
    const bulb = made.tests.electric.bulb;
    rig.replaceChildren(...clean([
      h("div", { class: `circuit-rig ${bulb}` }, [h("span", { class: "rig-battery", text: "🔋" }), h("span", { class: "rig-sample", style: `--metal:${made.material.colour}` }), h("span", { class: "rig-bulb", text: "💡" })]),
      h("p", { text: bulb === "bright" ? "The bulb lights brightly: a great conductor." : bulb === "dim" ? "The bulb glows dimly: it conducts, but resists." : "The bulb stays dark: an insulator." })
    ]));
  }

  /* ------------------------------------------------------------ tech */

  function drawTech() {
    const board = h("div", { class: "board" });
    const stats = h("section", { class: "card build-stats" });
    const bin = h("div", { class: "parts-bin" });
    const groups = {};
    for (const part of state.catalogue.parts) (groups[part.kind] ||= []).push(part);
    for (const [kind, parts] of Object.entries(groups)) {
      bin.append(...clean([
        h("h3", { text: kind }),
        h("div", { class: "part-grid" }, parts.map((part) =>
          h("button", {
            class: "part",
            type: "button",
            title: part.note || part.name,
            onclick: () => {
              const found = state.techParts.find((entry) => entry.id === part.id);
              if (found) found.count += 1;
              else state.techParts.push({ id: part.id, count: 1 });
              state.lastBuild = null;
              drawBoard(board, stats);
            },
          }, [h("span", { class: "part-icon", text: part.icon }), h("span", { class: "part-name", text: part.name }), part.volts ? h("small", { text: `${part.volts} V${part.milliamps && part.kind !== "power" ? ` · ${part.milliamps} mA` : ""}` }) : null])
        ))
      ]));
    }
    const templates = h("div", { class: "chips" }, state.catalogue.builds.map((item) =>
      h("button", { class: "chip", type: "button", text: item.name, onclick: () => make(item.name) })
    ));
    const wiring = toggle(state.series ? "Batteries in series" : "Batteries side by side", false, () => {
      state.series = !state.series;
      wiring.textContent = state.series ? "Batteries in series" : "Batteries side by side";
      state.lastBuild = null;
    });
    stage.append(...clean([
      h("div", { class: "tech-grid" }, [
        h("section", { class: "card" }, [h("h2", { text: "Parts bin" }), h("p", { class: "muted small", text: "Tap parts to put them on the board, then power it on." }), bin]),
        h("div", { class: "tech-column" }, [
          h("section", { class: "card" }, [
            h("h2", { text: "Circuit board" }),
            templates,
            board,
            h("div", { class: "row" }, [
              h("button", { class: "primary power-button", type: "button", text: "⚡ Power on", onclick: () => powerOn(board, stats) }),
              wiring,
              h("button", { class: "secondary", type: "button", text: "Clear", onclick: () => { state.techParts = []; state.lastBuild = null; drawBoard(board, stats); } }),
            ]),
          ]),
          stats,
        ]),
      ])
    ]));
    drawBoard(board, stats);
  }

  function drawBoard(board, stats) {
    const result = state.lastBuild;
    const byId = Object.fromEntries(((result && result.parts) || []).map((row) => [row.id, row]));
    board.className = `board ${result ? (result.works ? "live" : "fault") : ""}`;
    if (!state.techParts.length) {
      board.replaceChildren(...clean([h("p", { class: "muted", text: "The board is empty." })]));
      stats.replaceChildren(...clean([h("h2", { text: "Readings" }), h("p", { class: "muted", text: "Add a power source and some parts." })]));
      return;
    }
    board.replaceChildren(...clean([
      h("div", { class: "wire", "aria-hidden": "true" }),
      ...state.techParts.map((entry, index) => {
        const part = state.catalogue.parts.find((p) => p.id === entry.id) || { name: entry.id, icon: "▫", kind: "" };
        const row = byId[entry.id];
        const status = row ? row.state : "";
        const led = part.id.startsWith("led-") ? part.id.replace("led-", "") : "";
        return h("div", { class: `tile ${part.kind} ${status} ${led ? `led ${led}` : ""}`, title: row && row.reason ? row.reason : part.name }, [
          h("span", { class: "tile-icon", text: part.icon }),
          h("span", { class: "tile-name", text: part.name }),
          h("div", { class: "tile-count" }, [
            h("button", { class: "ghost-button small", type: "button", "aria-label": `Fewer ${part.name}`, text: "−", onclick: () => { entry.count -= 1; if (entry.count < 1) state.techParts.splice(index, 1); state.lastBuild = null; drawBoard(board, stats); } }),
            h("span", { text: `×${entry.count}` }),
            h("button", { class: "ghost-button small", type: "button", "aria-label": `More ${part.name}`, text: "+", onclick: () => { entry.count += 1; state.lastBuild = null; drawBoard(board, stats); } }),
          ]),
          status ? h("span", { class: `tile-state ${status}`, text: status }) : null,
          status === "burnt" ? h("span", { class: "smoke" }, [h("i"), h("i"), h("i")]) : null,
        ]);
      })
    ]));
    if (!result) {
      stats.replaceChildren(...clean([h("h2", { text: "Readings" }), h("p", { class: "muted", text: "Press Power on." })]));
      return;
    }
    stats.replaceChildren(...clean([
      h("h2", { text: result.works ? "✅ It works" : "⚠ Not working yet" }),
      h("div", { class: "facts" }, [
        ["Supply", `${result.volts} V`],
        ["Parts get", `${result.rail_volts} V`],
        ["Current", `${result.total_ma} mA`],
        ["Power", `${result.watts} W`],
        ["Runtime", result.runtime_text],
        ["Cost", `$${result.price}`],
        ["Weight", `${result.grams} g`],
      ].map(([label, value]) => h("div", { class: "fact" }, [h("span", { text: label }), h("strong", { text: value })]))),
      result.resistors.length ? h("div", {}, [h("h3", { text: "Resistors" }), ...result.resistors.map((r) => h("p", { text: `${r.for}: ${r.ohms} Ω (${r.rating}); exactly ${r.exact_ohms} Ω` }))]) : null,
      result.tips.length ? h("ul", { class: "observations" }, result.tips.map((tip) => h("li", { text: tip }))) : null,
      result.warnings.length ? h("div", { class: "hazards" }, result.warnings.map((text) => h("div", { class: "hazard-line warning", text }))) : null,
      result.steps && result.steps.length ? h("ol", { class: "steps" }, result.steps.map((step) => h("li", { text: step }))) : null,
      h("button", {
        class: "secondary",
        type: "button",
        text: "Save to Made",
        onclick: async () => {
          await ctx.post("/studio/api/lab/build", { parts: state.techParts, series: state.series, name: result.name || "My build", save: true });
          ctx.notify("Saved to Made.");
        },
      })
    ]));
  }

  async function powerOn(board, stats) {
    if (!state.techParts.length) {
      ctx.notify("Put some parts on the board first.");
      return;
    }
    try {
      const result = await ctx.post("/studio/api/lab/build", { parts: state.techParts, series: state.series });
      state.lastBuild = result;
      board.classList.add("spark");
      await wait(350);
      drawBoard(board, stats);
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  /* ------------------------------------------------------------ elements */

  function drawElements() {
    const table = h("div", { class: "ptable", role: "grid", "aria-label": "Periodic table" });
    const search = h("input", { type: "search", placeholder: "Find an element…", "aria-label": "Find an element" });
    for (const item of state.catalogue.elements) {
      let column = item.group;
      let row = item.period;
      if (!item.group) {
        row = item.number < 90 ? 9 : 10;
        column = 3 + (item.number - (item.number < 90 ? 57 : 89));
      }
      table.append(...clean([
        h("button", {
          class: "ptile",
          type: "button",
          style: `grid-column:${column};grid-row:${row};--cat:${CATEGORY_COLOURS[item.category] || "#aaa"}`,
          title: item.name,
          "data-name": `${item.name} ${item.symbol}`.toLowerCase(),
          onclick: () => elementCard(item),
        }, [h("small", { text: item.number }), h("strong", { text: item.symbol }), h("span", { text: item.name })])
      ]));
    }
    search.addEventListener("input", () => {
      const wanted = search.value.trim().toLowerCase();
      for (const tile of table.children) tile.classList.toggle("dim", Boolean(wanted) && !tile.dataset.name.includes(wanted));
    });
    const legend = h("div", { class: "legend" }, Object.entries(CATEGORY_COLOURS).map(([name, colour]) =>
      h("span", {}, [h("i", { style: `--cat:${colour}` }), name.replace(/-/g, " ")])
    ));
    stage.append(...clean([h("section", { class: "card" }, [h("h2", { text: "All 118 elements" }), search, h("div", { class: "ptable-wrap" }, [table]), legend])]));
  }

  /* ------------------------------------------------------------ made */

  async function drawMade() {
    const list = h("div", { class: "made-list" }, [h("p", { class: "muted", text: "Loading…" })]);
    stage.append(...clean([h("section", { class: "card" }, [h("h2", { text: "Made in the Lab" }), list])]));
    let projects = [];
    try {
      ({ projects } = await ctx.api("/studio/api/lab/projects"));
    } catch (error) {
      list.replaceChildren(...clean([h("p", { class: "muted", text: error.message })]));
      return;
    }
    if (!projects.length) {
      list.replaceChildren(...clean([h("p", { class: "muted", text: "Nothing made yet. Mix, make, forge, or build something, or ask in the Lab chat." })]));
      return;
    }
    const icons = { product: "🧴", mix: "⚗", material: "🔩", build: "🔌" };
    list.replaceChildren(...clean([
      ...projects.map((project) =>
        h("div", { class: "made-row" }, [
          h("span", { class: "made-dot", style: `--dot:${project.colour || "#40d6ff"}`, text: icons[project.kind] || "•" }),
          h("button", {
            class: "grow link-button",
            type: "button",
            onclick: async () => openProject(await ctx.api(`/studio/api/lab/projects/${project.id}`), true),
          }, [h("strong", { text: project.name }), h("small", { class: "muted", text: ` ${project.kind} · by ${project.made_by} · ${new Date(project.created_at).toLocaleString()}` })]),
          h("button", {
            class: "ghost-button small",
            type: "button",
            "aria-label": `Delete ${project.name}`,
            text: "🗑",
            onclick: async () => {
              await ctx.remove(`/studio/api/lab/projects/${project.id}`);
              drawMode();
            },
          }),
        ])
      )
    ]));
  }

  /* ------------------------------------------------------------ lab chat */

  function chatPanel() {
    chatLog = h("div", { class: "lab-chat-log", "aria-live": "polite" });
    const input = h("input", { type: "text", placeholder: "Hey Jarvis, make a shampoo…", "aria-label": "Ask in the Lab chat" });
    const form = h("form", {
      class: "row",
      onsubmit: async (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        input.value = "";
        await say(text);
      },
    }, [h("div", { class: "grow" }, [input]), h("button", { class: "primary", type: "submit", text: "Send" })]);
    return h("aside", { class: "card lab-chat" }, [
      h("h2", {}, [h("span", { class: "lab-orb", "aria-hidden": "true" }), " Lab chat"]),
      h("p", { class: "muted small", text: "Ask the main AI to make, mix, forge, or build anything. It works on the bench while you watch." }),
      chatLog,
      h("div", { class: "chips" }, SUGGESTIONS.map((text) => h("button", { class: "chip", type: "button", text, onclick: () => say(text) }))),
      form,
    ]);
  }

  async function say(text) {
    state.chatMessages.push({ role: "user", text, sequence: -1 });
    state.chatBusy = true;
    drawChat();
    try {
      await ctx.post("/studio/api/lab/chat", { text });
    } catch (error) {
      ctx.notify(error.message);
      state.chatBusy = false;
      drawChat();
      return;
    }
    pollChat();
  }

  function pollChat() {
    clearTimeout(chatTimer);
    chatTimer = setTimeout(async () => {
      if (!ctx.alive()) return;
      await refreshChat(false);
      if (state.chatBusy) pollChat();
    }, 1200);
  }

  async function refreshChat(first) {
    let console_;
    try {
      console_ = await ctx.api(`/studio/api/lab/chat?after=${first ? 0 : state.chatAfter}`);
    } catch {
      return;
    }
    if (!ctx.alive()) return;
    if (first) state.chatMessages = [];
    state.chatMessages = state.chatMessages.filter((message) => message.sequence !== -1 || !console_.messages.some((m) => m.role === "user" && m.text === message.text));
    for (const message of console_.messages) {
      state.chatAfter = Math.max(state.chatAfter, message.sequence);
      state.chatMessages.push(message);
      if (!first && message.role === "tool" && message.data && message.data.tool === "lab" && message.data.project_id) {
        try {
          const project = await ctx.api(`/studio/api/lab/projects/${message.data.project_id}`);
          if (ctx.alive()) {
            ctx.notify(`${console_.agent} made ${project.name}.`);
            openProject(project, true);
          }
        } catch {
          /* the project was deleted meanwhile */
        }
      }
    }
    state.chatBusy = console_.busy;
    state.agentName = console_.agent;
    drawChat();
    if (first && console_.busy) pollChat();
  }

  function drawChat() {
    if (!chatLog) return;
    const shown = state.chatMessages.slice(-40).map((message) => {
      if (message.role === "user") return h("div", { class: "bubble user", text: message.text });
      if (message.role === "tool") {
        const data = message.data || {};
        if (data.tool !== "lab") return h("div", { class: "tool-line", text: `⚙ ${data.tool || "tool"}` });
        return h("div", { class: `tool-line lab ${message.data.failed ? "failed" : ""}` }, [
          h("span", { text: `🧪 ${data.action || "lab"}` }),
          data.project_id
            ? h("button", { class: "link-button", type: "button", text: "Show on the bench", onclick: async () => openProject(await ctx.api(`/studio/api/lab/projects/${data.project_id}`), true) })
            : null,
        ]);
      }
      if (message.role === "assistant") {
        if (!message.text) return null;
        return h("div", { class: "bubble assistant" }, [h("span", { class: "who", text: message.author || state.agentName || "Jarvis" }), message.text]);
      }
      if (message.role === "event") return h("div", { class: "tool-line muted", text: message.text });
      return null;
    });
    if (state.chatBusy) shown.push(h("div", { class: "bubble assistant thinking" }, [h("span", { class: "dots" }, [h("i"), h("i"), h("i")]), " working in the Lab…"]));
    if (!shown.filter(Boolean).length) shown.push(h("p", { class: "muted small", text: "Say “Hey Jarvis, make a shampoo” and watch the bench." }));
    chatLog.replaceChildren(...clean([...shown.filter(Boolean)]));
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  window.FCCLab = { render, state };
})();
