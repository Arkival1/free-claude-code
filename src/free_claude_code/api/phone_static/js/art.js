// FCC's 2D game art on the phone (owner approved, 6 November 2026): 4,000
// sprites from Kenney's packs (CC0: free for any use, credit not needed) in
// one file, games/art2d.bin, fetched the first time an agent uses it, checked
// against its SHA-256 and kept by the app. The game_art tool searches them,
// shows what a pack holds, and copies the ones a game needs into the project
// (art/<pack>/...), where Godot and the phone's web games load them.
import { ART2D, ART2D_BIN } from "./art2d.js";
import { digest } from "./sha256.js";
import { words } from "./ui.js";

export const ART_COUNT = ART2D.length;
const MAX_FOUND = 40;
const MAX_ADD = 60;
let bin = null;

/** Every pack with how many sprites and a few sample names. */
export function artPacks() {
  const packs = new Map();
  for (const [pack, path] of ART2D) {
    const entry = packs.get(pack) || { pack, count: 0, samples: [] };
    entry.count += 1;
    if (entry.samples.length < 4) entry.samples.push(path.split("/").pop());
    packs.set(pack, entry);
  }
  return [...packs.values()];
}

const idOf = (index) => `a${index}`;
const indexOf = (id) => {
  const match = /^a(\d+)$/.exec(String(id || "").trim());
  return match && Number(match[1]) < ART2D.length ? Number(match[1]) : -1;
};

/** Sprites whose pack, folder or name match every word ({ id, pack, path, width, height }). */
export function searchArt(query, pack = "") {
  const wanted = words(String(query || "").toLowerCase());
  const out = [];
  ART2D.forEach(([itemPack, path, , , width, height], index) => {
    if (pack && itemPack !== pack) return;
    const hay = `${itemPack} ${path}`.toLowerCase().replace(/[_\-/.]+/g, " ");
    if (wanted.every((word) => hay.includes(word))) out.push({ id: idOf(index), pack: itemPack, path, width, height });
  });
  return out;
}

/** The sprites' file, fetched once (the app keeps it) and checked. */
export async function artBytes(onProgress) {
  if (bin) return bin;
  const response = await fetch(new URL(`../${ART2D_BIN.path}`, import.meta.url));
  if (!response.ok) throw new Error(`Couldn't get FCC's game art (${response.status}). Try again with the internet on.`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (onProgress) onProgress(bytes.length, ART2D_BIN.bytes);
  if ((await digest(bytes.buffer)) !== ART2D_BIN.sha256) {
    if (globalThis.caches) await caches.open(ART_CACHE).then((cache) => cache.delete(response.url)).catch(() => false);
    throw new Error("FCC's game art isn't the file FCC shipped (its checksum is wrong). Reload the app to fetch it again.");
  }
  bin = bytes;
  return bin;
}
export const ART_CACHE = "fcc-phone-art-1";

/** One sprite as a PNG data address (for a project file or a picture on screen). */
export async function artPicture(id) {
  const index = indexOf(id);
  if (index < 0) throw new Error(`No sprite ${id}; search first (ids look like a123).`);
  const [, , offset, length] = ART2D[index];
  const bytes = (await artBytes()).subarray(offset, offset + length);
  let text = "";
  for (let at = 0; at < bytes.length; at += 0x8000) text += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
  return `data:image/png;base64,${btoa(text)}`;
}

/** Where a sprite goes in a project. */
export const artPath = (id) => {
  const [pack, path] = ART2D[indexOf(id)];
  return `art/${pack}/${path.split("/").pop()}`;
};

export const GAME_ART_GUIDE = `FCC's game art: ${ART2D.length} 2D sprites from Kenney's packs (CC0: free for any use, credit not needed): characters, enemies, tiles, items, coins, vehicles, spaceships, cards, board-game pieces, buttons and UI, icons and effects.
packs lists them with samples; search finds sprites by words in the pack, folder and file name (e.g. "platformer character", "tiny dungeon", "spaceship", "coin", "tank"); add copies sprites into the project as art/<pack>/<file>.png (ids from search, up to ${MAX_ADD} at once). In Godot: preload("res://art/<pack>/<file>.png"); in a web game: an <img> or the game's loader with the same path. Tiles from one pack (tiny-town, tiny-dungeon, pixel-platformer...) match each other: keep a game to one pack's style.`;

/** The game_art tool. putFile(project, path, body) writes into the project. */
export async function useArt(args, ctx, putFile) {
  const action = String(args.action || "guide");
  if (action === "guide") return GAME_ART_GUIDE;
  if (action === "packs") return artPacks().map((entry) => `${entry.pack} (${entry.count}): ${entry.samples.join(", ")}`).join("\n");
  if (action === "search") {
    const found = searchArt(args.query, String(args.pack || ""));
    if (!found.length) return `Nothing matches "${args.query || ""}". Try fewer or other words, or packs to see what's here.`;
    const shown = found.slice(0, MAX_FOUND).map((item) => `${item.id} ${item.pack}/${item.path} (${item.width}x${item.height})`);
    return `${found.length} found${found.length > MAX_FOUND ? ` (first ${MAX_FOUND})` : ""}:\n${shown.join("\n")}`;
  }
  if (action === "add") {
    if (!ctx.project) return "Open or start a project first, then add the sprites.";
    const ids = (Array.isArray(args.ids) ? args.ids : String(args.ids || "").split(/[\s,]+/)).filter(Boolean).slice(0, MAX_ADD);
    if (!ids.length) return "add needs ids from search (like a12, a340).";
    // Every id is checked before anything is written, so a bad one doesn't
    // leave half the sprites added and unreported.
    const unknown = ids.filter((id) => indexOf(id) < 0);
    if (unknown.length) return `No sprite ${unknown.join(", ")}; search first (ids look like a123). Nothing was added.`;
    const added = [];
    for (const id of ids) {
      const path = artPath(id);
      await putFile(ctx.project, path, await artPicture(id));
      added.push(path);
    }
    return `Added ${added.length} to ${ctx.project.name}:\n${added.join("\n")}`;
  }
  return "action is guide, packs, search or add.";
}
