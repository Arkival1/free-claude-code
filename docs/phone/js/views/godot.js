// Godot on the phone, on screen: play a project's game full screen, check it,
// and the probe that tests what Godot can do here. The game runs in js/godot.js's
// sealed box; this file only shows it.
import { el, button, notify, openSheet } from "../ui.js";
import { runGodot, describeRun, probeGodot, describeProbe, probeItems, stopGodot, GODOT_VERSION } from "../godot.js";

const MB = 1048576;

function layerFor(title) {
  const status = el("p", { class: "godot-status", role: "status", text: "Starting Godot…" });
  const layer = el("div", { class: "fullscreen godot-layer", role: "dialog", "aria-label": title }, [status]);
  document.body.append(layer);
  const progress = (got, total) => {
    status.textContent = `Getting Godot ${GODOT_VERSION} (first time only): ${(got / MB).toFixed(1)} of ${(total / MB).toFixed(1)} MB`;
  };
  return { layer, status, progress };
}

/** The project's game, full screen, until Close (or it quits or crashes). */
export function playGodot(project) {
  const { layer, status, progress } = layerFor(`${project.name} in Godot`);
  const run = runGodot(project, {
    host: layer,
    mode: "play",
    onProgress: progress,
    onEvent: (event) => {
      if (event.type === "loading") status.textContent = "Starting the game…";
      if (event.type === "playing") status.hidden = true;
    },
  });
  layer.append(button("✕ Close", () => run.stop("Closed."), { class: "close-full", "aria-label": "Close the game" }));
  run.done.then((result) => {
    layer.remove();
    const trouble = result.problems.some((problem) => problem.stop) || result.crash || result.errors.length || (result.stopped && !["Closed.", "exit"].includes(result.stopped));
    if (trouble) showReport(`${project.name}: what happened`, describeRun(result));
  });
}

function showReport(title, text) {
  openSheet(title, [el("pre", { class: "godot-report", text })]);
}

/** Run the game unseen-but-small inside `host` for a few seconds; the report goes in `out`. */
export async function checkInto(project, host, out) {
  out.textContent = "Running it in Godot…";
  const run = runGodot(project, {
    host,
    mode: "check",
    seconds: 8,
    onProgress: (got, total) => (out.textContent = `Getting Godot (first time only): ${(got / MB).toFixed(1)} of ${(total / MB).toFixed(1)} MB`),
    onEvent: (event) => {
      if (event.type === "loading") out.textContent = "Starting the game…";
      if (event.type === "playing") out.textContent = "Playing it for 8 seconds…";
    },
  });
  const text = describeRun(await run.done);
  out.textContent = text;
  return text;
}

/** FCC's probe, shown full screen while it runs, then its list. */
export async function showProbe() {
  const { layer, status, progress } = layerFor("Testing Godot on this phone");
  layer.append(button("✕ Stop", () => stopGodot("Stopped."), { class: "close-full", "aria-label": "Stop the test" }));
  try {
    const result = await probeGodot(layer, progress, (event) => {
      if (event.type === "loading") status.textContent = "Testing what Godot can do on this phone (about 10 seconds)…";
      if (event.type === "playing") status.hidden = true;
    });
    layer.remove();
    if (result.stopped === "Stopped.") return;
    const counts = probeItems(result).reduce((sum, item) => ({ ...sum, [item.status]: (sum[item.status] || 0) + 1 }), {});
    showReport(result.probe ? `Godot here: ${counts.works || 0} work, ${counts.limited || 0} limited, ${counts.missing || 0} missing` : "Godot test", describeProbe(result));
  } catch (error) {
    layer.remove();
    notify(error.message);
  }
}
