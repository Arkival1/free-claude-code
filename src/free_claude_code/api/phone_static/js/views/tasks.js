// Tasks: give your PC's team a whole job, like Manus. The PC plans it into
// steps, hands each to the right agent (with every tool, plugin, subagent and
// repo agent it has), and this screen follows along live. When it's done, the
// files it made open in Projects on this phone.
import { state } from "../state.js";
import { el, button, card, notify, go, ago, meter } from "../ui.js";
import { pcCall } from "../sync.js";
import { createProject, writeFile, putPicture, isPicture } from "../projects.js";

const REFRESH_MS = 5000;
const MARK = { done: "✓", running: "●", failed: "✕", stopped: "■", skipped: "–", waiting: "○" };

function unpaired(view) {
  view.replaceChildren(
    card("Tasks", [
      el("p", { text: "Tasks run on your PC's team, with all its tools, plugins and models, so nothing has to be downloaded to this phone. Pair with your PC to start one." }),
      button("Pair with my PC", () => go("settings"), { class: "primary" }),
    ])
  );
}

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

export function render(view, param) {
  if (!state.settings.pc) {
    unpaired(view);
    return null;
  }
  return param ? renderTask(view, param) : renderList(view);
}

function renderList(view) {
  const goal = el("textarea", { "aria-label": "The job", rows: 3, placeholder: "Make a website for my electrician business with a quote form, then check it on a phone" });
  let tasks = null;
  let problem = "";
  let timer = null;
  let gone = false;

  const start = async () => {
    const text = goal.value.trim();
    if (!text) return notify("Say what the job is first.");
    try {
      const task = await pcCall("/studio/api/phone/tasks", { goal: text });
      goal.value = "";
      notify("Your PC's team is on it.");
      go(`tasks/${task.id}`);
    } catch (error) {
      notify(error.message);
    }
  };

  const draw = () => {
    if (gone) return;
    const rows = (tasks || []).map((task) =>
      el("button", { class: "item as-button", type: "button", onclick: () => go(`tasks/${task.id}`), "aria-label": `Open the job: ${task.goal}` }, [
        el("span", { class: "glyph", "aria-hidden": "true", text: MARK[task.running ? "running" : task.status] || "○" }),
        el("div", { class: "grow" }, [
          el("strong", { text: task.goal }),
          el("small", { text: `${task.running ? "working" : task.status} · ${task.done_steps}/${task.steps.length} steps · ${ago(task.updated_at)}` }),
          meter(task.steps.length ? task.done_steps / task.steps.length : 0),
        ]),
      ])
    );
    view.replaceChildren(
      card("New task", [
        goal,
        button("Start", start, { class: "primary" }),
        el("p", { class: "muted small", text: "Your PC plans the job into steps and its agents do them one by one, using their tools, your plugins and subagents. You can leave this screen; it keeps going." }),
      ]),
      card("Jobs", problem ? [el("p", { class: "warn", text: problem })] : tasks === null ? [el("p", { class: "muted", text: "Reading your PC's jobs…" })] : rows.length ? rows : [el("p", { class: "empty", text: "No jobs yet." })])
    );
  };

  const loop = async () => {
    try {
      tasks = (await pcCall("/studio/api/phone/tasks", undefined, "GET", 30000)).tasks || [];
      problem = "";
    } catch (error) {
      problem = error.message;
    }
    if (gone) return;
    // Keep what's typed: redraw the list only, never the box being typed in.
    const typing = document.activeElement === goal;
    if (!typing) draw();
    // Keep following while a job runs, and try again after a failed read.
    if (problem || (tasks && tasks.some((task) => task.running))) timer = setTimeout(loop, REFRESH_MS);
  };
  draw();
  loop();
  return () => {
    gone = true;
    clearTimeout(timer);
  };
}

function renderTask(view, id) {
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
        el("p", { class: "muted small", text: `${task.done_steps} of ${total} steps · updated ${ago(task.updated_at)}` }),
        problem ? el("p", { class: "warn", text: problem }) : null,
        el("div", { class: "row" }, [
          task.running ? button("Stop", () => act("/stop", "Stopped."), { class: "danger" }) : null,
          !task.running && task.status !== "done" ? button("Run again", () => act("/resume", "Going again from where it stopped."), { class: "primary" }) : null,
          task.has_files ? button("Open the files on this phone", () => openFiles(task)) : null,
        ]),
      ]),
      card("Steps", total ? task.steps.map((step) =>
        el("div", { class: `item${step.status === "done" ? " done" : ""}` }, [
          el("span", { class: "glyph", "aria-hidden": "true", text: MARK[step.status] || "○" }),
          el("div", { class: "grow" }, [
            el("strong", { text: `${step.agent}: ${step.do}` }),
            el("small", { text: `${step.status}${step.source ? ` · from ${step.source}` : ""}` }),
            step.result ? el("p", { class: "small", text: step.result }) : null,
          ]),
        ])
      ) : [el("p", { class: "muted", text: "Planning the steps…" })]),
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
