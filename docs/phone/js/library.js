// The library: the user's approved references for games and websites, kept
// on this phone. The user adds photos, notes and their own projects; every
// game or site the Playground finishes lands here waiting for approval.
// Approved items are what the AI reads (library tool) before it makes a new
// game or site, so it makes originals in the spirit of what the user likes.
import { state, save, changed, feed } from "./state.js";
import { uid, words } from "./ui.js";
import { isPicture } from "./projects.js";

export const LIBRARY_KINDS = { game: "Game", website: "Website", photo: "Photo", note: "Note" };
/** A project kept as a reference: its text files, up to this much. */
const SNAPSHOT_CHARS = 160_000;
const READ_CHARS = 3_500;
const MAX_ITEMS = 300;

/** Keep a reference: a project (its text files are copied, so the reference
 * stays as it was), a photo (a picture's data address) or a note. */
export async function addToLibrary({ kind, title, notes = "", tags = [], project = null, image = "", by = "you", approved = true }) {
  const sort = kind in LIBRARY_KINDS ? kind : "note";
  const files = {};
  if (project) {
    let room = SNAPSHOT_CHARS;
    for (const [path, text] of Object.entries(project.files)) {
      if (path.startsWith("parts/") || isPicture(text) || typeof text !== "string" || text.length > room) continue;
      files[path] = text;
      room -= text.length;
    }
  }
  const item = {
    id: uid(),
    kind: sort,
    title: String(title || "").trim().slice(0, 80) || LIBRARY_KINDS[sort],
    notes: String(notes || "").trim().slice(0, 2000),
    tags: [...new Set(tags.map((tag) => String(tag).trim().toLowerCase()).filter(Boolean))].slice(0, 12),
    project_id: project ? project.id : "",
    files,
    image: typeof image === "string" && image.startsWith("data:image/") ? image : "",
    by,
    approved: Boolean(approved),
    created_at: Date.now(),
  };
  if (state.library.length >= MAX_ITEMS) {
    // Full: the oldest one still waiting for approval makes room; approved
    // references are never dropped without the user removing them.
    const waiting = [...state.library].reverse().find((entry) => !entry.approved);
    if (!waiting) throw new Error(`Your library is full (${MAX_ITEMS} approved references): remove some first.`);
    state.library = state.library.filter((entry) => entry.id !== waiting.id);
  }
  state.library.unshift(item);
  await save.library();
  changed("library");
  feed(by === "you" ? "You" : by, `${approved ? "Added to" : "Waiting in"} the library: ${item.title}`);
  return item;
}

export async function setApproved(id, approved) {
  const item = state.library.find((entry) => entry.id === id);
  if (!item) throw new Error("That reference is gone.");
  item.approved = Boolean(approved);
  await save.library();
  changed("library");
  return item;
}

export async function removeFromLibrary(id) {
  state.library = state.library.filter((entry) => entry.id !== id);
  await save.library();
  changed("library");
}

/** The references that match a search, best first. Only approved ones
 * unless asked; kind narrows to games, websites, photos or notes. */
export function searchLibrary(query = "", { kind = "", approvedOnly = true, limit = 8 } = {}) {
  const wanted = words(query);
  return state.library
    .filter((item) => (!approvedOnly || item.approved) && (!kind || item.kind === kind))
    .map((item) => {
      const hay = `${item.title} ${item.notes} ${item.tags.join(" ")} ${item.kind}`.toLowerCase();
      const score = wanted.reduce((sum, word) => sum + (hay.includes(word) ? 1 : 0), 0);
      return [score, item];
    })
    .filter(([score]) => !wanted.length || score > 0)
    .sort((a, b) => b[0] - a[0] || b[1].created_at - a[1].created_at)
    .slice(0, limit)
    .map(([, item]) => item);
}

const line = (item) => `- ${item.id} · ${LIBRARY_KINDS[item.kind]} · ${item.title}${item.approved ? "" : " (waiting for approval)"}${item.notes ? `: ${item.notes.slice(0, 160)}` : ""}${Object.keys(item.files).length ? ` · files: ${Object.keys(item.files).slice(0, 8).join(", ")}` : ""}`;

/** The library tool: search the approved references, or read one. */
export function useLibrary(args) {
  const action = String(args.action || "search");
  if (action === "search") {
    const found = searchLibrary(String(args.query || ""), { kind: String(args.kind || "") });
    if (!found.length) return state.library.some((item) => item.approved) ? "No approved reference matches that. Try other words, or search with no words to see them all." : "The library has no approved references yet: make something original from the user's words and taste.";
    return `Approved references (read one with action read and its id; take its feel, make something original):\n${found.map(line).join("\n")}`;
  }
  if (action !== "read") throw new Error("action is search or read.");
  const item = state.library.find((entry) => entry.id === String(args.id || "").trim());
  if (!item) throw new Error("No reference with that id. Search first.");
  if (!item.approved) return `${item.title} is waiting for the user's approval; don't use it yet.`;
  const parts = [`${LIBRARY_KINDS[item.kind]}: ${item.title}`, item.notes ? `The user's notes: ${item.notes}` : "", item.tags.length ? `Tags: ${item.tags.join(", ")}` : ""];
  const main = ["index.html", "game.js", "styles.css", "app.js"].filter((path) => item.files[path]);
  for (const path of main) parts.push(`${path}:\n${item.files[path].slice(0, READ_CHARS)}${item.files[path].length > READ_CHARS ? "\n[cut]" : ""}`);
  if (item.image) parts.push("It is a photo the user approved; its notes say what to take from it.");
  return parts.filter(Boolean).join("\n\n");
}
