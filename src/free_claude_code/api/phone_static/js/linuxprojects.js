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
const OUT_MAX = 40; // changed files brought back after one command
const sent = new Map(); // "slug/path" -> the text last written in or read out
// File times in FCC Linux are whole seconds: the mark is set two seconds back,
// so a file changed just after a sync still counts (unchanged ones are
// skipped by their contents).
const TOUCH = `touch -d "$(date -d @$(( $(date +%s) - 2 )) '+%Y-%m-%d %H:%M:%S')" ${MARK}`;
const quote = (text) => `'${String(text).replace(/'/g, "'\\''")}'`;

function base64Text(text) {
  const bytes = new TextEncoder().encode(String(text));
  let out = "";
  for (let at = 0; at < bytes.length; at += 0x6000) out += String.fromCharCode(...bytes.subarray(at, at + 0x6000));
  return btoa(out);
}
const safe = (path) => !String(path).split("/").some((part) => part === ".." || part === "") && !String(path).startsWith("/");

/** Write every project's changed files into FCC Linux; returns how many. */
export async function syncIn(machine) {
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
      if (!safe(path) || sent.get(key) === body) continue;
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
  lines.push(TOUCH);
  await flush();
  return count;
}

/** Bring files changed under /projects back into their projects (after a
 * command); returns the paths brought back. */
export async function syncOut(machine, agentName = "FCC Linux") {
  const listed = await machine.run(`[ -d ${ROOT} ] && [ -f ${MARK} ] && cd ${ROOT} && find . -type f -newer ${MARK} | head -${OUT_MAX}; ${TOUCH}`, { timeoutMs: 60000 }).catch(() => null);
  if (!listed || !listed.text.trim()) return [];
  const back = [];
  for (const line of listed.text.split("\n")) {
    const relative = line.trim().replace(/^\.\//, "");
    const slash = relative.indexOf("/");
    if (slash < 1) continue;
    const slug = relative.slice(0, slash);
    const path = relative.slice(slash + 1);
    const project = (state.projects || []).find((item) => item.slug === slug);
    const text = TEXT_TYPES.test(path);
    if (!project || !safe(path) || !(text || PICTURE_TYPES.test(path))) continue;
    const read = await machine.run(`base64 -w0 ${quote(`${ROOT}/${relative}`)}`, { timeoutMs: 60000 }).catch(() => null);
    if (!read || read.code !== 0) continue;
    const data = read.text.trim();
    let body;
    if (text) {
      const bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
      body = new TextDecoder().decode(bytes);
      if (body.length > MAX_FILE_CHARS) continue;
    } else {
      const kind = /\.png$/i.test(path) ? "png" : /\.gif$/i.test(path) ? "gif" : /\.webp$/i.test(path) ? "webp" : "jpeg";
      body = `data:image/${kind};base64,${data}`;
    }
    const key = `${slug}/${path}`;
    // Unchanged in Linux since FCC wrote it, or already the same: nothing to do.
    if (body === sent.get(key) || project.files[path] === body) {
      sent.set(key, body);
      continue;
    }
    // Changed on both sides since FCC wrote it in: the phone's copy stays and
    // Linux's comes in beside it, so neither is lost.
    if (sent.has(key) && project.files[path] !== sent.get(key)) {
      await putFile(project, `${path}.from-linux${text ? ".txt" : path.slice(path.lastIndexOf("."))}`, body, agentName).catch(() => null);
      back.push(`${slug}/${path} (both changed: Linux's copy kept beside it)`);
      continue;
    }
    await putFile(project, path, body, agentName);
    sent.set(key, body);
    back.push(key);
  }
  return back;
}

/** Forget what was written in (after FCC Linux starts fresh). */
export function forgetSynced() {
  sent.clear();
}
