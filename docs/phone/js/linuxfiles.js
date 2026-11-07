// FCC Linux 2's files on the phone. The system (about 1.2 GB with every
// language) is a file list plus packs of zstd-compressed files, built by
// scripts/linux/build_fcc_linux2.py; each file's name in the list says where it
// lives ("<pack>-<offset>-<length>.zst", hex). A pack is fetched the first time
// something in it is used, checked against the SHA-256 the manifest gives (the
// manifest itself is checked by js/linux.js), and kept here as a Blob, so a
// later read takes only the slice it needs. "Get everything" fetches them all.
import { digest } from "./sha256.js";

const DB = "fcc-linux-files";
let manifest = null;
let base = null;
const packBlobs = new Map(); // pack number -> Blob (handles are cheap)
const getting = new Map(); // pack number -> Promise<Blob>
let onActivity = () => {};

/** Use this checked manifest (from js/linux.js), with files under baseUrl. */
export function useManifest(checked, baseUrl) {
  if (manifest && manifest !== checked) packBlobs.clear();
  manifest = checked;
  base = baseUrl;
}
/** Say what's being fetched (the screen shows it while a program waits). */
export function setActivity(report) {
  onActivity = typeof report === "function" ? report : () => {};
}

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("packs");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function packsDo(mode, work) {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const request = work(db.transaction("packs", mode).objectStore("packs"));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

const MB = 1048576;
const label = (row) => (row.packages || []).slice(0, 3).join(", ") + ((row.packages || []).length > 3 ? "…" : "");

async function fetchPack(row) {
  onActivity(`Getting ${label(row)} for FCC Linux (${(row.bytes / MB).toFixed(1)} MB, first time only)…`);
  let response;
  try {
    response = await fetch(new URL(row.file, base), { cache: "no-store" });
  } catch {
    throw Object.assign(new Error(`FCC Linux needs the internet once to get ${label(row)}.`), { retry: true });
  }
  if (!response.ok) throw Object.assign(new Error(`Couldn't get FCC Linux's ${label(row)} (${response.status}).`), { retry: response.status >= 500 });
  const bytes = new Uint8Array(await response.arrayBuffer());
  if ((await digest(bytes)) !== row.sha256) throw Object.assign(new Error(`FCC Linux's ${label(row)} isn't what FCC shipped (its checksum is wrong), so it wasn't used.`), { retry: false });
  const fresh = new Blob([bytes]);
  try {
    await packsDo("readwrite", (store) => store.put({ sha256: row.sha256, blob: fresh, at: Date.now() }, row.sha256));
  } catch {
    // Checked but not kept (storage full?): used from memory this time.
    onActivity(`FCC Linux couldn't keep ${label(row)} on this phone (is its storage full?), so it will download again next time.`);
    setTimeout(() => onActivity(""), 8000);
    return fresh;
  }
  onActivity("");
  // Read it back: the stored Blob lives on the phone's storage, not in memory.
  const kept = await packsDo("readonly", (store) => store.get(row.sha256)).catch(() => null);
  return kept && kept.blob instanceof Blob ? kept.blob : fresh;
}
/** Has the manifest been loaded (FCC Linux started, or its files fetched)? */
export const hasManifest = () => Boolean(manifest);

/** A pack's bytes (as a Blob), fetching it the first time. */
function pack(number) {
  if (!manifest) return Promise.reject(new Error("FCC Linux isn't loaded."));
  const row = manifest.packs[number];
  if (!row) return Promise.reject(Object.assign(new Error(`FCC Linux has no pack ${number}.`), { retry: false }));
  if (packBlobs.has(number)) return Promise.resolve(packBlobs.get(number));
  if (!getting.has(number)) {
    getting.set(
      number,
      (async () => {
        const kept = await packsDo("readonly", (store) => store.get(row.sha256)).catch(() => null);
        const blob = kept && kept.blob instanceof Blob ? kept.blob : await fetchPack(row);
        packBlobs.set(number, blob);
        return blob;
      })().finally(() => getting.delete(number)),
    );
  }
  return getting.get(number);
}

/** One file's zstd bytes, by its name in the file list. */
export async function readFile(name) {
  const found = /^([0-9a-f]+)-([0-9a-f]+)-([0-9a-f]+)\.zst$/.exec(String(name).split("/").pop());
  if (!found) throw Object.assign(new Error(`FCC Linux asked for an unknown file (${String(name).slice(0, 60)}).`), { retry: false });
  const [number, offset, length] = found.slice(1).map((part) => parseInt(part, 16));
  const first = await pack(number);
  if (offset + length <= first.size) return first.slice(offset, offset + length).arrayBuffer();
  // A file bigger than a pack runs on through the next packs.
  const parts = [first.slice(offset)];
  let have = first.size - offset;
  for (let next = number + 1; have < length; next += 1) {
    const more = await pack(next);
    parts.push(more.slice(0, Math.min(more.size, length - have)));
    have += Math.min(more.size, length - have);
  }
  return new Blob(parts).arrayBuffer();
}

/** The file list (v86's JSON, as text), checked and kept. */
export async function readList() {
  const row = manifest.files;
  const kept = await packsDo("readonly", (store) => store.get(row.sha256)).catch(() => null);
  let blob = kept && kept.blob instanceof Blob ? kept.blob : null;
  if (!blob) {
    const response = await fetch(new URL(row.file, base), { cache: "no-store" });
    if (!response.ok) throw Object.assign(new Error(`Couldn't get FCC Linux's file list (${response.status}). Try again with the internet on.`), { retry: response.status >= 500 });
    const bytes = new Uint8Array(await response.arrayBuffer());
    if ((await digest(bytes)) !== row.sha256) throw Object.assign(new Error("FCC Linux's file list isn't what FCC shipped (its checksum is wrong), so it wasn't used."), { retry: false });
    blob = new Blob([bytes]);
    // Keeping it is a nicety: if the phone's storage refuses, the checked copy
    // in hand is used (like fetchPack does).
    await packsDo("readwrite", (store) => store.put({ sha256: row.sha256, blob, at: Date.now() }, row.sha256)).catch(() => false);
  }
  return new Response(blob.stream().pipeThrough(new DecompressionStream("gzip"))).text();
}

/** What's on the phone: { packs, have, bytes, total, missing: [labels] }. */
export async function status() {
  if (!manifest) return { packs: 0, have: 0, bytes: 0, total: 0, missing: [] };
  const keys = new Set(await packsDo("readonly", (store) => store.getAllKeys()).catch(() => []));
  const rows = manifest.packs;
  const have = rows.filter((row) => keys.has(row.sha256));
  return {
    packs: rows.length,
    have: have.length,
    bytes: have.reduce((sum, row) => sum + row.bytes, 0),
    total: rows.reduce((sum, row) => sum + row.bytes, 0),
    missing: rows.filter((row) => !keys.has(row.sha256)).flatMap((row) => row.packages || []),
  };
}

/** Get every pack now (for working offline); onProgress(gotBytes, totalBytes). */
export async function getEverything(onProgress = () => {}, shouldStop = () => false) {
  const rows = manifest.packs;
  const total = rows.reduce((sum, row) => sum + row.bytes, 0);
  let got = 0;
  for (let number = 0; number < rows.length; number += 1) {
    if (shouldStop()) break;
    await pack(number);
    got += rows[number].bytes;
    onProgress(got, total);
  }
  return got;
}

/** Drop packs this system no longer uses (after an update). */
export async function pruneOld() {
  if (!manifest) return 0;
  const wanted = new Set([...manifest.packs.map((row) => row.sha256), manifest.files.sha256]);
  const keys = await packsDo("readonly", (store) => store.getAllKeys()).catch(() => []);
  let dropped = 0;
  for (const key of keys) {
    if (wanted.has(key)) continue;
    await packsDo("readwrite", (store) => store.delete(key)).catch(() => null);
    dropped += 1;
  }
  return dropped;
}

/** Forget every pack (they come back as they're used). */
export async function forgetFiles() {
  packBlobs.clear();
  await new Promise((resolve) => {
    const request = indexedDB.deleteDatabase(DB);
    request.onsuccess = request.onerror = request.onblocked = () => resolve();
  });
}
