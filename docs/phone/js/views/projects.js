// Projects: websites and apps the Builder makes on the phone.
import { state, onChange, agentById } from "../state.js";
import { el, button, card, go, notify, openSheet, closeSheet, ago } from "../ui.js";
import * as projects from "../projects.js";
import { runTask, isBusy } from "../agents.js";

export function render(view, id) {
  if (id) return renderProject(view, id);
  const name = el("input", { "aria-label": "What to build", placeholder: "A one-page site for my bakery with a menu and opening hours" });
  const draw = () =>
    view.replaceChildren(
      card("Build something", [
        el("p", { class: "muted", text: "Say what you want and the Builder makes it: pages, styles, and scripts, checked by the Tester if you ask." }),
        name,
        button("Have the Builder make it", async () => {
          const goal = name.value.trim();
          if (!goal) return notify("Say what to build.");
          const builder = agentById("builder") || state.agents.find((agent) => agent.role === "builder");
          if (!builder) return notify("There is no Builder on the team. Add one on Agents.");
          const project = await projects.createProject(goal.split(/[,.]/)[0].slice(0, 40), "you");
          notify("The Builder is on it. Watch it on Home.");
          runTask(builder, goal, { project, by: "you" });
          go(`projects/${project.id}`);
        }, { class: "primary" }),
      ]),
      card(
        "Projects",
        state.projects.length
          ? state.projects.map((project) =>
              el("button", { class: "item as-button", type: "button", onclick: () => go(`projects/${project.id}`), "aria-label": `Open ${project.name}` }, [
                el("div", { class: "grow" }, [el("strong", { text: project.name }), el("small", { text: `${Object.keys(project.files).length} files · changed ${ago(project.updated_at)}` })]),
              ])
            )
          : [el("p", { class: "empty", text: "No projects yet." })]
      )
    );
  draw();
  return onChange((what) => what === "projects" && draw());
}

function renderProject(view, id) {
  const project = projects.projectById(id);
  if (!project) {
    go("projects");
    return null;
  }
  const ask = el("textarea", { "aria-label": "Change request", placeholder: "Make the header teal and add a contact form" });
  const frame = el("iframe", { class: "preview", title: `${project.name} preview`, sandbox: "allow-scripts allow-forms allow-modals" });
  const draw = () => {
    const html = projects.previewHtml(project);
    const names = Object.keys(project.files);
    const builder = agentById("builder") || state.agents.find((agent) => agent.role === "builder");
    const tester = agentById("tester") || state.agents.find((agent) => agent.role === "tester");
    const busy = [builder, tester].filter(Boolean).some((agent) => isBusy(agent));
    if (html) frame.srcdoc = html;
    view.replaceChildren(
      card(project.name, [
        el("p", { class: "muted", text: `${names.length} files · changed ${ago(project.updated_at)}${busy ? " · the team is working on it" : ""}` }),
        html ? frame : el("p", { class: "empty", text: busy ? "The Builder is writing the first page…" : "No page yet." }),
        html
          ? el("div", { class: "row" }, [
              button("Open full screen", () => fullScreen(project)),
              button("Save as one HTML file", () => projects.download(`${project.slug}.html`, projects.bundle(project))),
            ])
          : null,
      ]),
      card("Change it", [
        ask,
        el("div", { class: "row" }, [
          button("Ask the Builder", () => {
            if (!builder || !ask.value.trim()) return notify("Say what to change.");
            runTask(builder, `In the project ${project.name}: ${ask.value.trim()}`, { project, by: "you" });
            ask.value = "";
            notify("The Builder is on it.");
          }, { class: "primary", disabled: !builder }),
          button("Have the Tester check it", () => {
            if (!tester) return notify("There is no Tester on the team.");
            runTask(tester, `Check the project ${project.name} and fix real problems.`, { project, by: "you" });
            notify("The Tester is checking it.");
          }, { disabled: !tester }),
        ]),
      ]),
      card("Files", [
        ...(names.length
          ? names.map((name) =>
              el("div", { class: "item" }, [
                el("div", { class: "grow" }, [el("strong", { text: name }), el("small", { text: `${project.files[name].length.toLocaleString()} characters` })]),
                button("Open", () => fileSheet(project, name), { "aria-label": `Open ${name}` }),
              ])
            )
          : [el("p", { class: "empty", text: "No files yet." })]),
        el("div", { class: "row" }, [
          button("New file", () => fileSheet(project, "")),
          button("Delete project", async () => {
            if (!confirm(`Delete ${project.name} and its files?`)) return;
            await projects.deleteProject(project);
            go("projects");
          }, { class: "danger" }),
        ]),
      ])
    );
  };
  draw();
  return onChange((what) => (what === "projects" || what === "team") && draw());
}

function fileSheet(project, name) {
  const path = el("input", { "aria-label": "File name", value: name, placeholder: "about.html" });
  const body = el("textarea", { class: "code", "aria-label": "File contents", spellcheck: "false" });
  body.value = name ? project.files[name] : "";
  openSheet(name || "New file", [
    el("label", {}, ["Name", path]),
    el("label", {}, ["Contents", body]),
    el("div", { class: "row" }, [
      button("Save", async () => {
        try {
          const saved = await projects.writeFile(project, path.value, body.value, "you");
          if (name && saved !== projects.cleanPath(name)) await projects.deleteFile(project, name, "you");
          closeSheet();
          notify("Saved.");
        } catch (error) {
          notify(error.message);
        }
      }, { class: "primary" }),
      name ? button("Delete file", async () => {
        await projects.deleteFile(project, name, "you");
        closeSheet();
      }, { class: "danger" }) : null,
    ]),
  ]);
}

/** The page on its own, sandboxed: it can run its scripts but can't reach the
 * app's storage (keys, memories), whatever the model wrote into it. */
function fullScreen(project) {
  const frame = el("iframe", { class: "preview-full", title: `${project.name} full screen`, sandbox: "allow-scripts allow-forms allow-modals" });
  frame.srcdoc = projects.previewHtml(project);
  const layer = el("div", { class: "fullscreen", role: "dialog", "aria-label": `${project.name} full screen` }, [
    frame,
    button("✕ Close", () => layer.remove(), { class: "close-full", "aria-label": "Close full screen" }),
  ]);
  document.body.append(layer);
}
