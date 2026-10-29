// Tasks: give a whole job, like Manus. On this phone, Jarvis plans it into
// steps, picks the plugin each step needs, and his agents do the steps one by
// one with their tools, on the phone's own brains (no PC needed). Paired, a
// job can run on the PC's team instead; this screen follows either live.
import { state, onChange } from "../state.js";
import { el, button, card, notify, go, ago, meter } from "../ui.js";
import { pcCall } from "../sync.js";
import { createProject, writeFile, putPicture, isPicture } from "../projects.js";
import { startTask, stopTask, resumeTask, isRunning } from "../tasks.js";

const REFRESH_MS = 5000;
const MARK = { done: "✓", running: "●", working: "●", planning: "…", failed: "✕", stopped: "■", skipped: "–", waiting: "○" };

async function openFiles(task) {
  try {
    const found = await pcCall(`/studio/api/phone/tasks/${encodeURIComponent(task.id)}/files`, undefined, "GET", 60000);
    // One phone project per job: opening it again brings it up to date.
    const project = await createProject(`${found.name} (PC job ${String(task.id).slice(-4)})`, "your PC");
    let written = 0;
    for (const [path, text] of Object.entries(found.files || {})) {
      try {
        if (isPicture(text)) await putPicture(project, path, text, "your PC");
        else await writeFile(project, path, text, "your PC");
        written += 1;
      } catch {
        // A file the phone can't keep (too big, or not text) is skipped.
      }
    }
    const left = (found.left_out || []).length;
    notify(`${written} files on this phone${left ? `; ${left} big files stay on the PC` : ""}.`);
    go(`projects/${project.id}`);
  } catch (error) {
    notify(error.message);
  }
}

function stepRow(step) {
  return el("div", { class: `item${step.status === "done" ? " done" : ""}` }, [
    el("span", { class: "glyph", "aria-hidden": "true", text: MARK[step.status] || "○" }),
    el("div", { class: "grow" }, [
      el("strong", { text: `${step.agent}: ${step.do}` }),
      el("small", { text: `${step.status}${step.plugin ? ` · plugin ${step.plugin}` : ""}${step.source ? ` · from ${step.source}` : ""}` }),
      step.result ? el("p", { class: "small", text: step.result }) : null,
    ]),
  ]);
}

export function render(view, param) {
  if (param && state.tasks.some((task) => task.id === param)) return renderPhoneTask(view, param);
  if (param) {
    if (!state.settings.pc) {
      view.replaceChildren(card("Task", [el("p", { class: "empty", text: "That job is gone." })]));
      return null;
    }
    return renderPcTask(view, param);
  }
  return renderList(view);
}

function renderList(view) {
  const goal = el("textarea", { "aria-label": "The job", rows: 3, placeholder: "Find this weekend's weather in Sydney and plan a beach day, then make a one-page site for it" });
  const where = el("select", { "aria-label": "Run it on" }, [
    el("option", { value: "phone", text: "This phone (Jarvis and the team here)" }),
    el("option", { value: "pc", text: "My PC's team" }),
  ]);
  let pcTasks = null;
  let problem = "";
  let timer = null;
  let gone = false;

  const start = async () => {
    const text = goal.value.trim();
    if (!text) return notify("Say what the job is first.");
    try {
      if (state.settings.pc && where.value === "pc") {
        const task = await pcCall("/studio/api/phone/tasks", { goal: text });
        goal.value = "";
        notify("Your PC's team is on it.");
        go(`tasks/${task.id}`);
        return;
      }
      const task = await startTask(text);
      goal.value = "";
      notify("Jarvis is planning it.");
      go(`tasks/${task.id}`);
    } catch (error) {
      notify(error.message);
    }
  };

  const phoneRow = (task) => {
    const done = task.steps.filter((step) => step.status === "done").length;
    return el("button", { class: "item as-button", type: "button", onclick: () => go(`tasks/${task.id}`), "aria-label": `Open the job: ${task.goal}` }, [
      el("span", { class: "glyph", "aria-hidden": "true", text: MARK[task.status] || "○" }),
      el("div", { class: "grow" }, [
        el("strong", { text: task.goal }),
        el("small", { text: `${task.status} · ${done}/${task.steps.length} steps · ${ago(task.updated_at)}` }),
        meter(task.steps.length ? done / task.steps.length : 0),
      ]),
    ]);
  };
  const pcRow = (task) =>
    el("button", { class: "item as-button", type: "button", onclick: () => go(`tasks/${task.id}`), "aria-label": `Open the PC job: ${task.goal}` }, [
      el("span", { class: "glyph", "aria-hidden": "true", text: MARK[task.running ? "running" : task.status] || "○" }),
      el("div", { class: "grow" }, [
        el("strong", { text: task.goal }),
        el("small", { text: `${task.running ? "working" : task.status} · ${task.done_steps}/${task.steps.length} steps · ${ago(task.updated_at)}` }),
        meter(task.steps.length ? task.done_steps / task.steps.length : 0),
      ]),
    ]);

  const draw = () => {
    if (gone) return;
    view.replaceChildren(
      card("New task", [
        goal,
        state.settings.pc ? el("label", {}, ["Run it on", where]) : null,
        button("Start", start, { class: "primary" }),
        el("p", { class: "muted small", text: "Jarvis plans the job into steps, picks the plugin each step needs, and his agents do them one by one with their tools. Keep FCC Phone open while it works." }),
      ]),
      card("Jobs on this phone", state.tasks.length ? state.tasks.map(phoneRow) : [el("p", { class: "empty", text: "No jobs yet." })]),
      ...(state.settings.pc
        ? [card("Jobs on my PC", problem ? [el("p", { class: "warn", text: problem })] : pcTasks === null ? [el("p", { class: "muted", text: "Reading your PC's jobs…" })] : pcTasks.length ? pcTasks.map(pcRow) : [el("p", { class: "empty", text: "No jobs yet." })])]
        : [])
    );
  };
  // Keep what's typed: never redraw while the box is being typed in.
  const redraw = () => document.activeElement !== goal && draw();

  const loop = async () => {
    if (!state.settings.pc || gone) return;
    try {
      pcTasks = (await pcCall("/studio/api/phone/tasks", undefined, "GET", 30000)).tasks || [];
      problem = "";
    } catch (error) {
      problem = error.message;
    }
    if (gone) return;
    redraw();
    // Keep following while a PC job runs, and try again after a failed read.
    if (problem || (pcTasks && pcTasks.some((task) => task.running))) timer = setTimeout(loop, REFRESH_MS);
  };
  draw();
  loop();
  const stop = onChange((what) => what === "tasks" && redraw());
  return () => {
    gone = true;
    clearTimeout(timer);
    stop();
  };
}

function renderPhoneTask(view, id) {
  const draw = () => {
    const task = state.tasks.find((item) => item.id === id);
    if (!task) {
      view.replaceChildren(card("Task", [el("p", { class: "empty", text: "That job is gone." })]));
      return;
    }
    const total = task.steps.length;
    const done = task.steps.filter((step) => step.status === "done").length;
    const busy = isRunning(task);
    view.replaceChildren(
      card(task.status === "planning" ? "Jarvis is planning it" : busy ? "Working on it" : task.status === "done" ? "Done" : `Task ${task.status}`, [
        el("p", { text: task.goal }),
        meter(total ? done / total : 0),
        el("p", { class: "muted small", text: `On this phone · ${done} of ${total} steps${task.replanned ? ` · Jarvis changed the plan ${task.replanned}×` : ""} · updated ${ago(task.updated_at)}` }),
        el("div", { class: "row" }, [
          busy ? button("Stop", () => { stopTask(id); notify("Stopping after this step."); }, { class: "danger" }) : null,
          !busy && task.status !== "done" ? button("Run again", () => { resumeTask(id); notify("Going again from where it stopped."); draw(); }, { class: "primary" }) : null,
          button("Projects", () => go("projects")),
        ]),
      ]),
      card("Steps", total ? task.steps.map(stepRow) : [el("p", { class: "muted", text: "Planning the steps…" })]),
      ...(task.summary ? [card("What the team says", [el("p", { text: task.summary })])] : [])
    );
  };
  draw();
  return onChange((what) => (what === "tasks" || what === "team") && draw());
}

function renderPcTask(view, id) {
  let task = null;
  let problem = "";
  let timer = null;
  let gone = false;

  const act = async (path, done) => {
    try {
      task = await pcCall(`/studio/api/phone/tasks/${encodeURIComponent(id)}${path}`, {});
      if (done) notify(done);
    } catch (error) {
      notify(error.message);
    }
    draw();
    schedule();
  };

  const draw = () => {
    if (gone) return;
    if (!task) {
      view.replaceChildren(card("Task", [el("p", { class: problem ? "warn" : "muted", text: problem || "Reading the job…" })]));
      return;
    }
    const total = task.steps.length;
    view.replaceChildren(
      card(task.running ? "Working on it" : task.status === "done" ? "Done" : `Task ${task.status}`, [
        el("p", { text: task.goal }),
        meter(total ? task.done_steps / total : 0),
        el("p", { class: "muted small", text: `On my PC · ${task.done_steps} of ${total} steps · updated ${ago(task.updated_at)}` }),
        problem ? el("p", { class: "warn", text: problem }) : null,
        el("div", { class: "row" }, [
          task.running ? button("Stop", () => act("/stop", "Stopped."), { class: "danger" }) : null,
          !task.running && task.status !== "done" ? button("Run again", () => act("/resume", "Going again from where it stopped."), { class: "primary" }) : null,
          task.has_files ? button("Open the files on this phone", () => openFiles(task)) : null,
        ]),
      ]),
      card("Steps", total ? task.steps.map(stepRow) : [el("p", { class: "muted", text: "Planning the steps…" })]),
      ...(task.summary ? [card("What the team says", [el("p", { text: task.summary })])] : [])
    );
  };

  const schedule = () => {
    clearTimeout(timer);
    if (!gone && (!task || task.running)) timer = setTimeout(refresh, REFRESH_MS);
  };

  const refresh = async () => {
    try {
      task = await pcCall(`/studio/api/phone/tasks/${encodeURIComponent(id)}`, undefined, "GET", 30000);
      problem = "";
    } catch (error) {
      problem = error.message;
    }
    draw();
    schedule();
  };
  draw();
  refresh();
  return () => {
    gone = true;
    clearTimeout(timer);
  };
}
