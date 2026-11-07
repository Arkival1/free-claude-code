// The library screen: the user's approved references for games and websites.
// Add photos, notes and projects; approve (or remove) the games and sites the
// Playground made; search it all. The AI reads only what is approved.
import { state, onChange } from "../state.js";
import { el, button, card, notify, go, ago, openSheet, closeSheet } from "../ui.js";
import { addToLibrary, setApproved, removeFromLibrary, searchLibrary, LIBRARY_KINDS } from "../library.js";

const GLYPH = { game: "◇", website: "⌘", photo: "▣", note: "✎" };
const PHOTO_SIDE = 900;

/** A photo, made small enough to keep: a JPEG data address. */
async function smallPhoto(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, PHOTO_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = el("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.82);
}

function kindSelect(value = "website", kinds = ["website", "game", "note"]) {
  const select = el("select", { "aria-label": "What it is" }, kinds.map((key) => el("option", { value: key, text: LIBRARY_KINDS[key] })));
  select.value = value;
  return select;
}

function addNoteSheet() {
  const title = el("input", { "aria-label": "Title", placeholder: "Calm yoga studio site" });
  const notes = el("textarea", { "aria-label": "What to take from it", rows: 4, placeholder: "What you like about it: the colours, the layout, the feel, the controls…" });
  const kind = kindSelect("website");
  openSheet("Add a note", [
    el("label", {}, ["What it is", kind]),
    el("label", {}, ["Title", title]),
    el("label", {}, ["What to take from it", notes]),
    button("Add to the library", async () => {
      if (!title.value.trim() && !notes.value.trim()) return notify("Give it a title or a note first.");
      await addToLibrary({ kind: kind.value, title: title.value, notes: notes.value });
      closeSheet();
      notify("Added to your library.");
    }, { class: "primary" }),
  ]);
}

function addPhotoSheet(image) {
  const title = el("input", { "aria-label": "Title", placeholder: "Forest temple at night" });
  const notes = el("textarea", { "aria-label": "What to take from it", rows: 3, placeholder: "The mood, the colours, the kind of game or site it's for…" });
  openSheet("Add a photo", [
    el("img", { class: "lib-preview", src: image, alt: "The photo you picked" }),
    el("label", {}, ["Title", title]),
    el("label", {}, ["What to take from it", notes]),
    button("Add to the library", async () => {
      await addToLibrary({ kind: "photo", title: title.value || "Photo", notes: notes.value, image });
      closeSheet();
      notify("Added to your library.");
    }, { class: "primary" }),
  ]);
}

function addProjectSheet() {
  if (!state.projects.length) return notify("No projects yet: make a game or site first.");
  const project = el("select", { "aria-label": "Project" }, state.projects.map((item) => el("option", { value: item.id, text: item.name })));
  const kind = kindSelect("website", ["website", "game"]);
  const notes = el("textarea", { "aria-label": "What to take from it", rows: 3, placeholder: "What makes it good: keep the layout, the colours, the controls…" });
  openSheet("Add a project", [
    el("label", {}, ["Project", project]),
    el("label", {}, ["It is a", kind]),
    el("label", {}, ["What to take from it", notes]),
    button("Add as approved", async () => {
      const chosen = state.projects.find((item) => item.id === project.value);
      await addToLibrary({ kind: kind.value, title: chosen.name, notes: notes.value, project: chosen });
      closeSheet();
      notify("Added to your library.");
    }, { class: "primary" }),
  ]);
}

function itemRow(item) {
  return el("div", { class: "item lib-item" }, [
    item.image ? el("img", { class: "lib-thumb", src: item.image, alt: item.title }) : el("span", { class: "glyph", "aria-hidden": "true", text: GLYPH[item.kind] || "·" }),
    el("div", { class: "grow" }, [
      el("strong", { text: item.title }),
      el("small", { text: `${LIBRARY_KINDS[item.kind]} · ${item.by === "you" ? "added by you" : `made by ${item.by}`} · ${ago(item.created_at)}${Object.keys(item.files || {}).length ? ` · ${Object.keys(item.files).length} files` : ""}` }),
      item.notes ? el("p", { class: "small", text: item.notes }) : null,
      el("div", { class: "row" }, [
        item.approved
          ? button("Unapprove", () => setApproved(item.id, false), { "aria-label": `Unapprove ${item.title}` })
          : button("Approve", async () => {
              await setApproved(item.id, true);
              notify(`${item.title} is now a reference.`);
            }, { class: "primary", "aria-label": `Approve ${item.title}` }),
        item.project_id && state.projects.some((project) => project.id === item.project_id) ? button("Open", () => go(`projects/${item.project_id}`)) : null,
        button("Remove", () => removeFromLibrary(item.id), { class: "danger", "aria-label": `Remove ${item.title}` }),
      ]),
    ]),
  ]);
}

export function render(view) {
  let kind = "";
  const search = el("input", { type: "search", "aria-label": "Search the library", placeholder: "Search games, sites, photos, notes…" });
  const photo = el("input", { type: "file", accept: "image/*", class: "visually-hidden", "aria-label": "Photo for the library" });
  photo.addEventListener("change", async () => {
    const file = photo.files[0];
    photo.value = "";
    if (!file) return;
    try {
      addPhotoSheet(await smallPhoto(file));
    } catch {
      notify("That photo couldn't be read.");
    }
  });
  const filters = el("div", { class: "lib-filters", role: "group", "aria-label": "Show" });
  const list = el("div", {});
  const draw = () => {
    filters.replaceChildren(
      ...[["", "All"], ...Object.entries(LIBRARY_KINDS).map(([key, label]) => [key, `${label}s`])].map(([key, label]) =>
        el("button", { class: "lib-filter", type: "button", "aria-pressed": String(kind === key), text: label, onclick: () => {
          kind = key;
          draw();
        } })
      )
    );
    const found = searchLibrary(search.value, { kind, approvedOnly: false, limit: 300 });
    const waiting = found.filter((item) => !item.approved);
    const approved = found.filter((item) => item.approved);
    list.replaceChildren(
      ...(waiting.length ? [card(`Waiting for your approval (${waiting.length})`, waiting.map(itemRow))] : []),
      card(`Approved references (${approved.length})`, approved.length ? approved.map(itemRow) : [el("p", { class: "empty", text: state.library.length ? "Nothing matches." : "Nothing yet. Add photos, notes and projects you like; finished games and sites wait above for your approval." })])
    );
  };
  search.addEventListener("input", draw);
  draw();
  view.replaceChildren(
    card("Library", [
      el("p", { class: "small muted", text: "What you approve here is what the AI reads before it makes a game or website, so it makes originals in the spirit of what you like." }),
      search,
      el("div", { class: "row" }, [photo, button("Add a photo", () => photo.click()), button("Add a note", addNoteSheet), button("Add a project", addProjectSheet)]),
    ]),
    filters,
    list
  );
  return onChange((what) => (what === "library" || what === "projects") && document.activeElement !== search && draw());
}
