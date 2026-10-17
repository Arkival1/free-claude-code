// Business photos: pictures of the user's real business, sent to the agents
// with a note (what it shows, prices, hours, anything). Each is shrunk and
// turned upright here, kept on the phone, and put on sites with use_photo.
import { state, save, changed, feed } from "./state.js";
import { store } from "./store.js";
import { uid } from "./ui.js";

export const MAX_SIDE = 1600;
export const MAX_NOTE = 2000;

const clean = (name) =>
  String(name || "photo")
    .replace(/\.[a-z0-9]+$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "photo";

async function decode(file) {
  try {
    return await createImageBitmap(file);
  } catch {
    // Older Safari: let an <img> decode it (it reads iPhone HEIC photos too).
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      return image;
    } catch {
      throw new Error(`${file.name || "That file"} isn't a photo this phone can open.`);
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
}

/** Keep one photo: shrunk to 1600px, upright, as a JPEG (a small PNG stays PNG). */
export async function addPhoto(file, note = "") {
  const picture = await decode(file);
  const width = picture.width || picture.naturalWidth;
  const height = picture.height || picture.naturalHeight;
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  canvas.getContext("2d").drawImage(picture, 0, 0, canvas.width, canvas.height);
  if (picture.close) picture.close();
  const png = file.type === "image/png" && file.size < 1024 * 1024;
  const data = canvas.toDataURL(png ? "image/png" : "image/jpeg", 0.82);
  const extension = png ? ".png" : ".jpg";
  let name = `${clean(file.name)}${extension}`;
  for (let n = 2; state.photos.some((photo) => photo.name === name); n += 1) name = `${clean(file.name)}-${n}${extension}`;
  const photo = { id: `pho_${uid()}`, name, width: canvas.width, height: canvas.height, note: String(note).trim().slice(0, MAX_NOTE), created_at: Date.now() };
  await store.set(`photo:${photo.id}`, data);
  state.photos.unshift(photo);
  await save.photos();
  changed("photos");
  feed("You", `Added the photo ${name}.`);
  return photo;
}

export const photoData = (photo) => store.get(`photo:${photo.id}`, "");

export async function setNote(id, note) {
  const photo = state.photos.find((item) => item.id === id);
  if (!photo) return;
  photo.note = String(note).trim().slice(0, MAX_NOTE);
  await save.photos();
  changed("photos");
}

export async function removePhoto(id) {
  state.photos = state.photos.filter((photo) => photo.id !== id);
  await store.remove(`photo:${id}`);
  await save.photos();
  changed("photos");
}

export function findPhoto(reference) {
  const wanted = String(reference || "").trim().toLowerCase();
  return state.photos.find((photo) => [photo.id, photo.name, photo.name.replace(/\.[a-z]+$/, "")].includes(wanted));
}

export function searchPhotos(query) {
  const words = String(query || "").toLowerCase().match(/[a-z0-9]{3,}/g) || [];
  if (!words.length) return state.photos;
  return state.photos.filter((photo) => words.some((word) => `${photo.name} ${photo.note}`.toLowerCase().includes(word)));
}

/** One line an agent reads: name, size, shape, and the user's note. */
export function describe(photo) {
  const shape = photo.width > photo.height * 1.15 ? "wide" : photo.height > photo.width * 1.15 ? "tall" : "square";
  return `${photo.name} (${photo.width}x${photo.height}, ${shape})${photo.note ? ` — the user says: ${photo.note}` : ""}`;
}

/** The line added to a message that carries photos. */
export const photoLine = (photo) => `[Business photo: ${photo.name} (${photo.width}x${photo.height}), kept in Business photos with the note in this message. Builders put it on a site with use_photo.]`;
