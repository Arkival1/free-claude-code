// Models: Model Control on the phone. Download a model, add one from Files,
// load it, tune it, and test its speed, the same as on the PC.
import { state, save, changed, onChange } from "../state.js";
import { el, button, card, notify, openSheet, closeSheet, bytes, meter, ago } from "../ui.js";
import * as engine from "../engine.js";
import { brainOf } from "../brains.js";

const downloads = new Map(); // id -> {done, total, controller}

export function render(view) {
  const draw = () => {
    const ready = state.models.filter((model) => model.ready);
    view.replaceChildren(
      statusCard(ready),
      card(
        "Models on this phone",
        ready.length || state.models.length
          ? state.models.map(modelRow)
          : [el("p", { class: "empty", text: "No models yet. Download one below, or add a .gguf file from Files." })]
      ),
      addCard(),
      catalogCard()
    );
  };
  draw();
  return onChange((what) => {
    if (["models", "engine", "settings"].includes(what)) draw();
  });
}

function statusCard(ready) {
  const status = engine.status;
  const loaded = status.loadedId ? engine.modelById(status.loadedId) : null;
  const speed = status.lastSpeed;
  const usingPhone = state.settings.brain === "local";
  return card("Engine", [
    el("p", { class: "muted", text: "llama.cpp, the engine Model Control uses on your PC, running inside the app. Models stay on this phone and work offline." }),
    el("div", { class: "kv" }, [
      el("span", { text: "Graphics chip" }),
      el("strong", { text: engine.webgpu() ? "Available (WebGPU)" : "Not available here; runs on the processor" }),
      el("span", { text: "Loaded" }),
      el("strong", { text: status.loading ? `Loading ${engine.modelById(status.loading)?.name || "…"}` : loaded ? loaded.name : "Nothing" }),
      el("span", { text: "Last speed" }),
      el("strong", { text: speed ? `${speed.tokensPerSecond.toFixed(1)} tokens/s writing, ${speed.readPerSecond.toFixed(0)} reading` : "not measured" }),
    ]),
    status.error ? el("p", { class: "warn", text: status.error }) : null,
    ready.length && !usingPhone
      ? el("label", { class: "check" }, [
          el("input", { type: "checkbox", "aria-label": "Use phone models by default", onchange: async (event) => {
            if (!event.target.checked) return;
            state.settings.brain = "local";
            if (!state.settings.localModel) state.settings.localModel = ready[0].id;
            await save.settings();
            changed("settings");
            notify("Your agents now think on this phone.");
          } }),
          el("span", { text: "Use a model on this phone as every agent's default brain" }),
        ])
      : usingPhone
        ? el("p", { class: "good", text: "Your agents think on this phone by default." })
        : null,
    loaded ? button("Unload", async () => {
      await engine.unload();
      notify("Unloaded; its memory is free again.");
    }) : null,
  ]);
}

function badges(model) {
  const info = model.info || {};
  return el("div", { class: "badges" }, [
    info.sizeLabel ? el("span", { class: "pill", text: info.sizeLabel }) : null,
    el("span", { class: "pill", text: bytes(model.size) }),
    info.contextMax ? el("span", { class: "pill", text: `up to ${info.contextMax.toLocaleString()} tokens` }) : null,
    info.tools ? el("span", { class: "pill good", text: "Tools" }) : null,
    info.reasoning ? el("span", { class: "pill gold", text: "Reasoning" }) : null,
    model.source === "file" ? el("span", { class: "pill", text: "from Files" }) : null,
  ]);
}

function modelRow(model) {
  const loaded = engine.status.loadedId === model.id;
  const isDefault = state.settings.localModel === model.id;
  const need = engine.estimate(model);
  const going = downloads.get(model.id);
  if (!model.ready) {
    return el("article", { class: "model" }, [
      el("div", { class: "row" }, [el("strong", { class: "grow", text: model.name }), el("span", { class: "pill", text: going ? "downloading" : "not finished" })]),
      going ? meter(going.total ? going.done / going.total : 0) : null,
      going ? el("small", { class: "muted", text: `${bytes(going.done)} of ${bytes(going.total)}` }) : null,
      el("div", { class: "row" }, [
        going
          ? button("Stop", () => going.controller.abort())
          : button("Finish download", () => startDownload(engine.CATALOG.find((entry) => entry.id === model.id) || model), { class: "primary" }),
        going ? null : button("Remove", () => removeModel(model), { class: "danger" }),
      ]),
    ]);
  }
  return el("article", { class: `model${loaded ? " loaded" : ""}` }, [
    el("div", { class: "row" }, [
      el("strong", { class: "grow", text: model.name }),
      loaded ? el("span", { class: "pill good", text: "loaded" }) : null,
      isDefault ? el("span", { class: "pill gold", text: "default" }) : null,
    ]),
    badges(model),
    need ? el("small", { class: "muted", text: `Needs about ${bytes(need)} of memory at ${engine.settingsFor(model).context.toLocaleString()} tokens of context.${need > 2.5 * 1024 ** 3 ? " That's a lot for an iPhone: pick a smaller context or model if it crashes." : ""}` }) : null,
    model.lastSpeed ? el("small", { class: "muted", text: `Speed test: ${model.lastSpeed.toFixed(1)} tokens/s (${ago(model.testedAt)})` }) : null,
    el("div", { class: "row" }, [
      loaded
        ? button("Unload", () => engine.unload(), { "aria-label": `Unload ${model.name}` })
        : button("Load", () => loadNow(model), { class: "primary", "aria-label": `Load ${model.name}` }),
      isDefault ? null : button("Make default", async () => {
        state.settings.localModel = model.id;
        await save.settings();
        changed("settings");
        notify(`${model.name} is the phone's default model.`);
      }, { "aria-label": `Make ${model.name} the default` }),
      button("Test speed", () => testSpeed(model), { "aria-label": `Test the speed of ${model.name}` }),
      button("Settings", () => settingsSheet(model), { "aria-label": `Settings for ${model.name}` }),
      button("Delete", () => removeModel(model), { class: "danger", "aria-label": `Delete ${model.name}` }),
    ]),
  ]);
}

async function loadNow(model) {
  notify(`Loading ${model.name}…`);
  try {
    await engine.chat(model, { messages: [{ role: "user", content: "Hi" }], maxTokens: 1 });
    notify(`${model.name} is loaded.`);
  } catch (error) {
    notify(error.message);
  }
}

async function testSpeed(model) {
  notify(`Timing ${model.name}…`);
  try {
    const speed = await engine.speedTest(model);
    model.lastSpeed = speed.tokensPerSecond;
    model.testedAt = Date.now();
    await save.models();
    changed("models");
    notify(`${model.name}: ${speed.tokensPerSecond.toFixed(1)} tokens a second.`);
  } catch (error) {
    notify(error.message);
  }
}

async function removeModel(model) {
  if (!confirm(`Delete ${model.name} from this phone? It frees ${bytes(model.size)}.`)) return;
  await engine.remove(model);
  notify(`${model.name} deleted.`);
}

function settingsSheet(model) {
  const chosen = engine.settingsFor(model);
  const context = el("select", { "aria-label": "Context" }, engine.CONTEXTS.map((value) => el("option", { value: String(value), text: `${value.toLocaleString()} tokens` })));
  context.value = String(chosen.context);
  const gpu = el("input", { type: "checkbox", checked: chosen.gpu, "aria-label": "Use the graphics chip" });
  openSheet(`${model.name} settings`, [
    el("label", {}, ["Context (how much it remembers at once)", context]),
    el("p", { class: "muted small", text: "More context uses more memory. 4,096 suits most chats; the Builder likes 8,192 for bigger pages." }),
    el("label", { class: "check" }, [gpu, el("span", { text: "Use the graphics chip (faster)" })]),
    button("Save", async () => {
      model.settings = { context: Number(context.value), gpu: gpu.checked };
      await save.models();
      changed("models");
      closeSheet();
      notify("Saved. It reloads with these settings next time it's used.");
    }, { class: "primary" }),
  ]);
}

// What "Add from Files" is doing, kept here so it survives the screen redrawing.
const adding = { status: "", fraction: null };

function addCard() {
  const input = el("input", { type: "file", accept: ".gguf,application/octet-stream", class: "visually-hidden", "aria-label": "Choose a model file" });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    adding.status = `Reading ${file.name}…`;
    adding.fraction = 0;
    changed("models");
    let last = 0;
    try {
      const model = await engine.addFile(file, (done, total) => {
        adding.fraction = total ? done / total : 0;
        adding.status = `Copying ${file.name}: ${bytes(done)} of ${bytes(total)}`;
        if (Date.now() - last > 400) {
          last = Date.now();
          changed("models");
        }
      });
      adding.status = `${model.name} added.${model.info.tools ? " It can use tools." : " It can't use tools, so it's best for chatting."}`;
      if (!state.settings.localModel) {
        state.settings.localModel = model.id;
        await save.settings();
      }
    } catch (error) {
      adding.status = error.message;
    } finally {
      adding.fraction = null;
      changed("models");
    }
  });
  return card("Add a model from Files", [
    el("p", { class: "muted", text: "Any .gguf model: from your iPhone's Files app, iCloud Drive, or a download. Studio reads it and says what it can do. Under 2 GB works best; a 0.5–3B model at Q4_K_M suits an iPhone." }),
    el("label", { class: "drop" }, [input, el("strong", { text: "Choose a .gguf file" }), el("small", { class: "muted", text: "It's copied into the app, so it works offline." })]),
    adding.fraction === null ? null : meter(adding.fraction),
    el("p", { class: "muted", role: "status", text: adding.status }),
  ]);
}

async function startDownload(entry) {
  if (downloads.has(entry.id)) return;
  const controller = new AbortController();
  const progress = { done: 0, total: entry.size, controller };
  downloads.set(entry.id, progress);
  changed("models");
  let last = 0;
  try {
    await engine.download(entry, (done, total) => {
      progress.done = done;
      progress.total = total || entry.size;
      if (Date.now() - last > 500) {
        last = Date.now();
        changed("models");
      }
    }, controller.signal);
    if (!state.settings.localModel) state.settings.localModel = entry.id;
    if (!state.settings.brain) state.settings.brain = "local";
    await save.settings();
    notify(`${entry.name} is on your phone.`);
  } catch (error) {
    notify(controller.signal.aborted ? "Download stopped. Finish it any time." : `Download failed: ${error.message}`);
  } finally {
    downloads.delete(entry.id);
    changed("models");
  }
}

function catalogCard() {
  return card("Download a model", [
    el("p", { class: "muted", text: "Free models that fit an iPhone. Downloading uses Wi-Fi data once; after that they work offline." }),
    ...engine.CATALOG.map((entry) => {
      const have = state.models.find((model) => model.id === entry.id);
      return el("div", { class: "item" }, [
        el("div", { class: "grow" }, [el("strong", { text: entry.name }), el("small", { text: `${bytes(entry.size)} · ${entry.note} Good for ${entry.good.join(", ")}.` })]),
        have && have.ready
          ? el("span", { class: "pill good", text: "on phone" })
          : button(downloads.has(entry.id) ? "…" : "Download", () => startDownload(entry), { class: "primary", "aria-label": `Download ${entry.name}`, disabled: downloads.has(entry.id) }),
      ]);
    }),
    el("p", { class: "muted small", text: `Your default brain: ${brainOf({ brain: "default" }) === "local" ? "this phone" : state.settings.brain || "not set"}.` }),
  ]);
}
