// Your FCC Projects inside FCC Linux, as folders: /projects/<project>/...
// When FCC Linux opens, each project's files are written in (afterwards only
// what changed in FCC); after each command, files changed under /projects come
// back into their project (text files and pictures). Deleting a file on one
// side doesn't delete it on the other, and a new folder in /projects doesn't
// make a new project: that's done in FCC.
import { state } from "./state.js";
import { putFile, TEXT_TYPES, PICTURE_TYPES, isPicture, MAX_FILE_CHARS } from "./projects.js";

const ROOT = "/projects";
const MARK = "/tmp/.fcc-projects-mark";
const BATCH = 120_000; // characters of commands per run
const OUT_MAX = 40; // changed files read per round
const NEXT = `${MARK}.next`;
const CHANGED = "/tmp/.fcc-projects-changed";
const sent = new Map(); // "slug/path" -> the text last written in or read out
// Linux files changed but not yet read back (a read or its conflict copy
// failed): syncIn leaves them alone until a sync-out brings them back, so
// writing the phone's copy in can't overwrite Linux's change.
const pending = new Set();
// File times in FCC Linux are whole seconds: the mark is set two seconds back,
// so a file changed just after a sync still counts (unchanged ones are
// skipped by their contents).
const touchAt = (file) => `touch -d "$(date -d @$(( $(date +%s) - 2 )) '+%Y-%m-%d %H:%M:%S')" ${file}`;
const TOUCH = touchAt(MARK);
const quote = (text) => `'${String(text).replace(/'/g, "'\\''")}'`;

function base64Text(text) {
  const bytes = new TextEncoder().encode(String(text));
  let out = "";
  for (let at = 0; at < bytes.length; at += 0x6000) out += String.fromCharCode(...bytes.subarray(at, at + 0x6000));
  return btoa(out);
}
const safe = (path) => !String(path).split("/").some((part) => part === ".." || part === "") && !String(path).startsWith("/");

// One sync at a time: syncIn and syncOut share the mark and its lists, so a
// second call waits for the first to finish.
let queue = Promise.resolve();
function oneAtATime(work) {
  const run = queue.then(work, work);
  queue = run.catch(() => null);
  return run;
}

/** Write every project's changed files into FCC Linux; returns how many. */
export const syncIn = (machine) => oneAtATime(() => syncInNow(machine));

async function syncInNow(machine) {
  const lines = [];
  const done = [];
  let count = 0;
  const flush = async () => {
    if (!lines.length) return;
    const result = await machine.run(lines.join("\n"), { timeoutMs: 300000 });
    if (result.code !== 0) throw new Error(`Couldn't put your projects in FCC Linux: ${result.text.slice(-200)}`);
    for (const [key, body] of done) sent.set(key, body);
    lines.length = 0;
    done.length = 0;
  };
  let size = 0;
  for (const project of state.projects || []) {
    for (const [path, body] of Object.entries(project.files || {})) {
      const key = `${project.slug}/${path}`;
      if (!safe(path) || sent.get(key) === body || pending.has(key)) continue;
      let data;
      if (TEXT_TYPES.test(path) && typeof body === "string" && !isPicture(body)) data = base64Text(body);
      else if (PICTURE_TYPES.test(path) && isPicture(body)) data = body.slice(body.indexOf(",") + 1);
      else continue;
      const file = quote(`${ROOT}/${project.slug}/${path}`);
      lines.push(`mkdir -p "$(dirname ${file})" && printf %s '${data}' | base64 -d > ${file}`);
      done.push([key, body]);
      size += data.length;
      count += 1;
      if (size > BATCH) {
        await flush();
        size = 0;
      }
    }
  }
  // The mark is only made here when there isn't one yet: moving it would skip
  // files changed in Linux that syncOut hasn't brought back (files written
  // here come back unchanged and are skipped by their contents).
  lines.push(`[ -f ${MARK} ] || ${TOUCH}`);
  await flush();
  return count;
}

/** Bring files changed under /projects back into their projects (after a
 * command); returns the paths brought back. */
export const syncOut = (machine, agentName = "FCC Linux") => oneAtATime(() => syncOutNow(machine, agentName));

async function syncOutNow(machine, agentName) {
  // The next mark is set when the list is made, and only becomes the mark
  // once every listed file is back: files beyond one round are never skipped,
  // and a file changed while this runs is caught next time. Dependency
  // folders don't take places in the list.
  const listed = await machine.run(`[ -d ${ROOT} ] && [ -f ${MARK} ] && cd ${ROOT} && ${touchAt(NEXT)} && find . -type f -newer ${MARK} -not -path '*/node_modules/*' -not -path '*/.git/*' > ${CHANGED} && wc -l < ${CHANGED}`, { timeoutMs: 60000 }).catch(() => null);
  const total = listed && listed.code === 0 ? Number.parseInt(listed.text.trim().split("\n").pop(), 10) || 0 : 0;
  if (!total) {
    if (listed && listed.code === 0) await machine.run(`mv -f ${NEXT} ${MARK}`, { timeoutMs: 30000 }).catch(() => null);
    return [];
  }
  const back = [];
  const missed = [];
  // The projects Linux changed (FCC checks each one after an agent's job).
  back.projects = [];
  // The whole list, a page at a time (each page handled before the next is
  // read, so a long list never sits in memory at once).
  for (let from = 1; from <= total; from += OUT_MAX) {
    const page = await machine.run(`sed -n '${from},${from + OUT_MAX - 1}p' ${CHANGED}`, { timeoutMs: 60000 });
    if (page.code !== 0) throw new Error("Couldn't list the files changed in FCC Linux.");
    await bringBack(machine, page.text.split("\n"), agentName, back, missed);
  }
  if (missed.length) {
    // A file that couldn't be read keeps the mark where it is, so the next
    // sync tries it again (the ones already back are skipped by contents).
    back.push(`(couldn't read ${missed.length} changed file(s) yet, e.g. ${missed.slice(0, 3).join(", ")}: they come back on the next sync)`);
    return back;
  }
  await machine.run(`mv -f ${NEXT} ${MARK}`, { timeoutMs: 30000 });
  return back;
}

async function bringBack(machine, lines, agentName, back, missed) {
  for (const line of lines) {
    const relative = line.trim().replace(/^\.\//, "");
    const slash = relative.indexOf("/");
    if (slash < 1) continue;
    const slug = relative.slice(0, slash);
    const path = relative.slice(slash + 1);
    const project = (state.projects || []).find((item) => item.slug === slug);
    const text = TEXT_TYPES.test(path);
    if (!project || !safe(path) || !(text || PICTURE_TYPES.test(path))) continue;
    const key = `${slug}/${path}`;
    const read = await machine.run(`base64 -w0 ${quote(`${ROOT}/${relative}`)}`, { timeoutMs: 60000 }).catch(() => null);
    if (!read || read.code !== 0) {
      missed.push(relative);
      pending.add(key);
      continue;
    }
    const data = read.text.trim();
    let body;
    if (text) {
      const bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
      body = new TextDecoder().decode(bytes);
      if (body.length > MAX_FILE_CHARS) {
        // Too long for the phone: Linux's copy stays, and the phone's copy
        // never writes over it (syncIn skips pending files).
        pending.add(key);
        back.push(`${key} (too long for the phone: Linux's copy is kept there)`);
        continue;
      }
    } else {
      const kind = /\.png$/i.test(path) ? "png" : /\.gif$/i.test(path) ? "gif" : /\.webp$/i.test(path) ? "webp" : "jpeg";
      body = `data:image/${kind};base64,${data}`;
    }
    // Unchanged in Linux since FCC wrote it, or already the same: nothing to do.
    if (body === sent.get(key) || project.files[path] === body) {
      sent.set(key, body);
      pending.delete(key);
      continue;
    }
    // Changed on both sides since FCC wrote it in, or the phone has its own
    // copy and there's no record of what was written in (a kept session whose
    // record was lost): the phone's copy stays and Linux's comes in beside
    // it, so neither is lost.
    if (project.files[path] !== undefined && (!sent.has(key) || project.files[path] !== sent.get(key))) {
      try {
        await putFile(project, `${path}.from-linux${text ? ".txt" : path.slice(path.lastIndexOf("."))}`, body, agentName);
      } catch {
        // The copy couldn't be saved: the mark stays, so it's tried again.
        missed.push(relative);
        pending.add(key);
        continue;
      }
      pending.delete(key);
      back.push(`${slug}/${path} (both changed: Linux's copy kept beside it)`);
      if (!back.projects.includes(project)) back.projects.push(project);
      continue;
    }
    try {
      await putFile(project, path, body, agentName);
    } catch {
      // Not saved: the mark stays and syncIn leaves Linux's copy alone.
      missed.push(relative);
      pending.add(key);
      continue;
    }
    sent.set(key, body);
    pending.delete(key);
    back.push(key);
    if (!back.projects.includes(project)) back.projects.push(project);
  }
}

/** Forget what was written in (after FCC Linux starts fresh). */
export function forgetSynced() {
  sent.clear();
  pending.clear();
}

/** What FCC last wrote in or read out, kept with a kept session ... */
export const syncedRecord = () => [...sent];
/** ... and brought back when that session reopens, so a file changed on both
 * sides is still noticed (instead of Linux's copy replacing the phone's). */
export function restoreSynced(entries) {
  sent.clear();
  for (const [key, body] of Array.isArray(entries) ? entries : []) sent.set(key, body);
}
