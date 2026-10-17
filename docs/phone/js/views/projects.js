// Projects: websites and apps the Builder makes on the phone.
import { state, onChange, agentById } from "../state.js";
import { el, button, card, go, notify, openSheet, closeSheet, ago } from "../ui.js";
import * as projects from "../projects.js";
import { runTask, isBusy } from "../agents.js";
import { addPhoto, setNote, removePhoto, photoData } from "../photos.js";

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
      ),
      photosCard()
    );
  draw();
  return onChange((what) => (what === "projects" || what === "photos") && draw());
}

/** Photos of the user's real business, each with a note the agents read. */
function photosCard() {
  const note = el("textarea", { rows: 2, "aria-label": "Note for new photos", placeholder: "What they show, prices, hours, the story…" });
  const input = el("input", { type: "file", accept: "image/*", multiple: true, class: "visually-hidden", "aria-label": "Add business photos" });
  const status = el("p", { class: "muted", role: "status" });
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    let added = 0;
    for (const file of files) {
      status.textContent = `Adding ${file.name}…`;
      try {
        await addPhoto(file, note.value);
        added += 1;
      } catch (error) {
        notify(error.message);
      }
    }
    status.textContent = added ? `Added ${added} photo${added === 1 ? "" : "s"}.` : "";
  });
  const tiles = state.photos.map((photo) => {
    const image = el("img", { alt: photo.note || photo.name, width: String(photo.width), height: String(photo.height) });
    photoData(photo).then((data) => {
      if (data) image.src = data;
    });
    const text = el("textarea", { "aria-label": `Note for ${photo.name}`, placeholder: "Add a note" });
    text.value = photo.note || "";
    text.addEventListener("change", () => setNote(photo.id, text.value).then(() => notify("Note saved.")));
    return el("figure", { class: "photo-tile" }, [
      image,
      el("small", { class: "muted", text: `${photo.name} · ${photo.width}×${photo.height}` }),
      text,
      button("Delete", async () => {
        if (!confirm(`Delete ${photo.name}? Sites that use it keep their copy.`)) return;
        await removePhoto(photo.id);
      }, { class: "danger", "aria-label": `Delete ${photo.name}` }),
    ]);
  });
  return card("Business photos", [
    el("p", { class: "muted", text: "Photos of your real business with notes. The Builder puts them on your sites before any stock photos and reads your notes as facts. You can also send photos in any chat with 🖼." }),
    note,
    el("div", { class: "row" }, [input, button("Add photos", () => input.click(), { class: "primary" })]),
    status,
    tiles.length ? el("div", { class: "photo-grid" }, tiles) : el("p", { class: "empty", text: "No photos yet." }),
  ]);
}

function renderProject(view, id) {
  const project = projects.projectById(id);
  if (!project) {
    go("projects");
    return null;
  }
  const ask = el("textarea", { "aria-label": "Change request", placeholder: "Make the header teal and add a contact form" });
  const frame = el("iframe", { class: "preview", title: `${project.name} preview`, sandbox: SANDBOX });
  let page = "index.html";
  const draw = () => {
    const pageNames = projects.pages(project);
    if (!pageNames.includes(page)) page = pageNames[0] || "index.html";
    const html = projects.previewHtml(project, { page });
    const names = Object.keys(project.files);
    const picker = pageNames.length > 1
      ? el("select", { "aria-label": "Page", onchange: (event) => { page = event.target.value; draw(); } }, pageNames.map((name) => el("option", { value: name, text: name })))
      : null;
    if (picker) picker.value = page;
    const builder = agentById("builder") || state.agents.find((agent) => agent.role === "builder");
    const tester = agentById("tester") || state.agents.find((agent) => agent.role === "tester");
    const busy = [builder, tester].filter(Boolean).some((agent) => isBusy(agent));
    if (html) frame.srcdoc = html;
    view.replaceChildren(
      card(project.name, [
        el("p", { class: "muted", text: `${names.length} files · changed ${ago(project.updated_at)}${busy ? " · the team is working on it" : ""}` }),
        picker ? el("label", { class: "page-pick" }, ["Page", picker]) : null,
        html ? frame : el("p", { class: "empty", text: busy ? "The Builder is writing the first page…" : "No page yet." }),
        html
          ? el("div", { class: "row" }, [
              button("Open full screen", () => fullScreen(project, page)),
              pageNames.length > 1
                ? button("Save all files (.zip)", () => projects.download(`${project.slug}.zip`, projects.zipProject(project)))
                : button("Save as one HTML file", () => projects.download(`${project.slug}.html`, projects.bundle(project))),
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
                el("div", { class: "grow" }, [el("strong", { text: name }), el("small", { text: projects.isPicture(project.files[name]) ? "picture" : `${project.files[name].length.toLocaleString()} characters` })]),
                projects.isPicture(project.files[name])
                  ? null
                  : button("Open", () => fileSheet(project, name), { "aria-label": `Open ${name}` }),
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
  const stopFollowing = followLinks(frame, project, (next) => {
    page = next;
    draw();
  });
  const stopWatching = onChange((what) => (what === "projects" || what === "team") && draw());
  return () => {
    stopFollowing();
    stopWatching();
  };
}

// Previews may run their scripts and open links in a new tab, but can't reach
// the app's storage (keys, memories), whatever the model wrote into them.
const SANDBOX = "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox";

/** Show another page of the project when a link in the preview asks for it. */
function followLinks(frame, project, show) {
  const listen = (event) => {
    if (event.source !== frame.contentWindow || !event.data || typeof event.data.fccPage !== "string") return;
    let wanted = "";
    try {
      wanted = projects.cleanPath(decodeURIComponent(event.data.fccPage));
    } catch {
      wanted = "";
    }
    if (projects.pages(project).includes(wanted)) show(wanted);
    else notify(`${event.data.fccPage.slice(0, 60)} isn't in ${project.name} yet.`);
  };
  addEventListener("message", listen);
  return () => removeEventListener("message", listen);
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

/** The site on its own, sandboxed, with its links between pages working. */
function fullScreen(project, page) {
  const frame = el("iframe", { class: "preview-full", title: `${project.name} full screen`, sandbox: SANDBOX });
  frame.srcdoc = projects.previewHtml(project, { page });
  const stop = followLinks(frame, project, (next) => {
    frame.srcdoc = projects.previewHtml(project, { page: next });
  });
  const layer = el("div", { class: "fullscreen", role: "dialog", "aria-label": `${project.name} full screen` }, [
    frame,
    button("✕ Close", () => {
      stop();
      layer.remove();
    }, { class: "close-full", "aria-label": "Close full screen" }),
  ]);
  document.body.append(layer);
}
