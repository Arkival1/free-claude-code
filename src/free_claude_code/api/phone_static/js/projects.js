// Projects the Builder makes on the phone: files kept on the phone, shown in
// a preview, and saved out as one HTML file you can open anywhere.
import { state, save, changed, feed } from "./state.js";
import { uid } from "./ui.js";
import { STARTER_TEXT } from "./templates.js";

export const MAX_FILE_CHARS = 200_000;
/** Earlier versions kept of each file, so restore_file can undo a change. */
export const MAX_VERSIONS = 5;
export const TEXT_TYPES = /\.(html?|css|js|mjs|json|txt|md|svg|xml|csv)$/i;

const slug = (name) =>
  String(name || "project")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40) || "project";

export function projectById(id) {
  return state.projects.find((project) => project.id === id);
}

export function findProject(name) {
  const wanted = slug(name);
  return state.projects.find((project) => project.slug === wanted) || state.projects.find((project) => project.slug.includes(wanted) && wanted.length > 2);
}

export async function createProject(name, agentName = "you") {
  const clean = String(name || "").trim() || "New project";
  const existing = findProject(clean);
  if (existing) return existing;
  const project = { id: uid(), name: clean.slice(0, 60), slug: slug(clean), files: {}, created_at: Date.now(), updated_at: Date.now(), by: agentName };
  state.projects.unshift(project);
  await save.projects();
  changed("projects");
  feed(agentName, `Started the project ${project.name}.`);
  return project;
}

export function cleanPath(path) {
  const clean = String(path || "")
    .replace(/\\/g, "/")
    .replace(/^\.?\/+/, "")
    .split("/")
    .filter((part) => part && part !== "." && part !== "..")
    .join("/");
  if (!clean) throw new Error("Give the file a name, like index.html.");
  if (!TEXT_TYPES.test(clean)) throw new Error("Only text files (html, css, js, json, md, svg, txt) can be written here.");
  return clean.slice(0, 120);
}

export async function writeFile(project, path, content, agentName) {
  const name = cleanPath(path);
  const text = String(content ?? "");
  if (text.length > MAX_FILE_CHARS) throw new Error("That file is too long for the phone. Split it into smaller files.");
  const isNew = !(name in project.files);
  if (!isNew) keepVersion(project, name, text);
  project.files[name] = text;
  project.updated_at = Date.now();
  await save.projects();
  changed("projects");
  feed(agentName, `${isNew ? "Wrote" : "Updated"} ${project.name}/${name} (${text.length.toLocaleString()} characters).`);
  return name;
}

export const PICTURE_TYPES = /\.(jpe?g|png|webp|gif)$/i;
/** Pictures live in a project as data addresses, so previews and zips need nothing else. */
export const isPicture = (text) => typeof text === "string" && text.startsWith("data:image/");

/** Put a picture (a data address) into the project, e.g. images/shop.jpg. */
export async function putPicture(project, path, data, agentName) {
  const name = String(path || "")
    .replace(/\\/g, "/")
    .split("/")
    .filter((part) => part && part !== "." && part !== "..")
    .join("/")
    .slice(0, 120);
  if (!PICTURE_TYPES.test(name)) throw new Error("Pictures are saved as .jpg or .png files, like images/shop.jpg.");
  if (!isPicture(data)) throw new Error("That isn't a picture.");
  const isNew = !(name in project.files);
  if (!isNew) keepVersion(project, name, data);
  project.files[name] = data;
  project.updated_at = Date.now();
  await save.projects();
  changed("projects");
  feed(agentName, `${isNew ? "Added" : "Replaced"} the picture ${project.name}/${name}.`);
  return name;
}

export async function deleteFile(project, path, agentName) {
  const name = cleanPath(path);
  if (!(name in project.files)) throw new Error(`There is no ${name} in ${project.name}.`);
  keepVersion(project, name, null);
  delete project.files[name];
  project.updated_at = Date.now();
  await save.projects();
  changed("projects");
  feed(agentName, `Deleted ${project.name}/${name}.`);
}

function keepVersion(project, name, replacing) {
  const current = project.files[name];
  if (current === undefined || current === replacing) return;
  project.history = project.history || {};
  const kept = project.history[name] || [];
  kept.unshift({ at: Date.now(), content: current });
  project.history[name] = kept.slice(0, MAX_VERSIONS);
}

/** The kept earlier versions of a file, newest first. */
export function versions(project, path) {
  return (project.history && project.history[cleanPath(path)]) || [];
}

/** Put back an earlier version of a file; the one it replaces is kept too. */
export async function restoreFile(project, path, back, agentName) {
  const name = cleanPath(path);
  const kept = versions(project, name);
  if (!kept.length) throw new Error(`There is no earlier version of ${name}.`);
  if (!(back >= 1 && back <= kept.length)) throw new Error(`${name} has ${kept.length} earlier version(s).`);
  const [chosen] = kept.splice(back - 1, 1);
  await writeFile(project, name, chosen.content, agentName);
  return name;
}

export async function deleteProject(project) {
  state.projects = state.projects.filter((item) => item.id !== project.id);
  await save.projects();
  changed("projects");
}

/** Replace the first exact match of `find` in a file. */
export async function editFile(project, path, find, replace, agentName) {
  const name = cleanPath(path);
  const text = project.files[name];
  if (text === undefined) throw new Error(`There is no ${name} in ${project.name}. Write it first.`);
  if (!find) throw new Error("Say what text to find.");
  const at = text.indexOf(find);
  if (at < 0) throw new Error(`That text isn't in ${name}. Read the file again and copy the exact text.`);
  await writeFile(project, name, text.slice(0, at) + String(replace ?? "") + text.slice(at + find.length), agentName);
}

/** One HTML page with the project's CSS and JS inlined, for previews and saving. */
export function bundle(project, page = "index.html") {
  const files = project.files;
  const entry = files[page] ? page : Object.keys(files).find((name) => /\.html?$/i.test(name));
  if (!entry) return null;
  let html = files[entry];
  html = html.replace(/<link\b[^>]*href=["']([^"']+\.css)["'][^>]*>/gi, (tag, href) => {
    const css = files[cleanRelative(href)];
    return css === undefined ? tag : `<style>\n${css}\n</style>`;
  });
  html = html.replace(/<script\b([^>]*)src=["']([^"']+\.m?js)["']([^>]*)><\/script>/gi, (tag, before, src, after) => {
    const js = files[cleanRelative(src)];
    if (js === undefined) return tag;
    const module = /type=["']module["']/i.test(before + after);
    return `<script${module ? ' type="module"' : ""}>\n${js.replace(/<\/script/gi, "<\\/script")}\n</script>`;
  });
  // Pictures drawn as SVG files in the project go in as data addresses.
  const picture = (ref) => {
    const kept = files[cleanPictureRef(ref)];
    if (isPicture(kept)) return kept;
    const svg = /\.svg$/i.test(ref) ? files[cleanRelative(ref)] : undefined;
    return svg === undefined ? null : `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  };
  html = html.replace(/(\bsrc=)(["'])([^"']+)\2/gi, (match, attr, quote, ref) => {
    const inline = picture(ref);
    return inline ? `${attr}${quote}${inline}${quote}` : match;
  });
  html = html.replace(/url\(\s*(["']?)([^"')]+)\1\s*\)/gi, (match, quote, ref) => {
    const inline = picture(ref);
    return inline ? `url("${inline}")` : match;
  });
  return html;
}

/** The project's pages, front page first. */
export function pages(project) {
  const names = Object.keys(project.files).filter((name) => /\.html?$/i.test(name));
  return names.sort((a, b) => (a === "index.html" ? -1 : b === "index.html" ? 1 : 0));
}

// Previews run sandboxed, where the browser refuses saved storage; pages that
// save things (games, to-do apps) get a stand-in that lasts while they're open.
const STORAGE_SHIM =
  "<script>try{localStorage.getItem('x')}catch(e){const s=()=>{const m=new Map();return{getItem:(k)=>m.has(String(k))?m.get(String(k)):null,setItem:(k,v)=>{m.set(String(k),String(v))},removeItem:(k)=>{m.delete(String(k))},clear:()=>m.clear(),key:(i)=>[...m.keys()][i]??null,get length(){return m.size}}};for(const n of['localStorage','sessionStorage']){try{Object.defineProperty(window,n,{value:s(),configurable:true})}catch(e){}}}</script>";

// Links between the project's pages ask the app to show that page (a preview
// has no address of its own); links out of the project open in a new tab.
const PAGE_LINKS =
  "<script>document.addEventListener('click',(e)=>{const a=e.target.closest&&e.target.closest('a[href]');if(!a||e.defaultPrevented)return;const h=a.getAttribute('href');if(/^(#|mailto:|tel:|javascript:)/i.test(h))return;e.preventDefault();if(/^(https?:)?\\/\\//i.test(h)){window.open(h,'_blank','noopener');return}const page=h.split('#')[0].split('?')[0];if(page)parent.postMessage({fccPage:page},'*')});</script>";

/** A page of the project, ready for a sandboxed preview; extra goes first in <head>. */
export function previewHtml(project, { page = "index.html", extra = "" } = {}) {
  const html = bundle(project, page);
  if (html === null) return null;
  const inject = STORAGE_SHIM + PAGE_LINKS + extra;
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head[^>]*>/i, (tag) => tag + inject);
  if (/<html[^>]*>/i.test(html)) return html.replace(/<html[^>]*>/i, (tag) => tag + inject);
  return inject + html;
}

function cleanPictureRef(ref) {
  return String(ref || "").split("?")[0].split("#")[0].replace(/^\.?\/+/, "");
}

function cleanRelative(href) {
  try {
    return cleanPath(href.split("?")[0].split("#")[0]);
  } catch {
    return "";
  }
}

/** Plain checks a Tester runs, like check_project on the PC. */
export function checkProject(project) {
  const problems = [];
  const names = Object.keys(project.files);
  if (!names.length) return ["The project has no files yet."];
  const pages = names.filter((name) => /\.html?$/i.test(name));
  if (!pages.length) problems.push("There is no HTML page; add index.html.");
  else if (!project.files["index.html"]) problems.push("There is no index.html, so the project has no front page.");
  for (const name of names) {
    const text = project.files[name];
    if (isPicture(text)) continue;
    if (!text.trim()) problems.push(`${name} is empty.`);
    // Placeholder words, not placeholder="" hints or the template's picture marker.
    const words = text.replace(/\bdata-placeholder\b|\bplaceholder=(["'])[^"']*\1/gi, "");
    if (/lorem ipsum|TODO|your (?:text|content) here|placeholder/i.test(words)) problems.push(`${name} still has placeholder text.`);
    const drawn = (text.match(/<img\b[^>]*\bdata-placeholder\b/gi) || []).length;
    if (drawn) problems.push(`${name}: ${drawn} picture(s) are still the template's drawn placeholders; use real photos from find_images and remove data-placeholder (or remove it to keep the drawn art).`);
    const starter = STARTER_TEXT.find((line) => text.includes(line));
    if (starter) problems.push(`${name} still has the template's placeholder line "${starter}"; replace it with real content.`);
  }
  for (const page of pages) {
    const html = project.files[page];
    if (!/<!doctype html>/i.test(html)) problems.push(`${page} has no <!DOCTYPE html>.`);
    if (!/<meta[^>]+viewport/i.test(html)) problems.push(`${page} has no viewport tag, so it won't fit phones.`);
    if (!/<title>[^<]+<\/title>/i.test(html)) problems.push(`${page} has no <title>.`);
    for (const match of html.matchAll(/(?:href|src)=["']([^"'#?]+)["']/gi)) {
      const target = match[1];
      if (/^(https?:|mailto:|tel:|data:|\/\/|#)/i.test(target)) continue;
      if (!project.files[cleanRelative(target)] && !project.files[cleanPictureRef(target)]) problems.push(`${page} links to ${target}, which isn't in the project.`);
    }
    for (const img of html.matchAll(/<img\b(?![^>]*\balt=)[^>]*>/gi)) {
      problems.push(`${page} has an image with no alt text: ${img[0].slice(0, 60)}`);
    }
    const opened = (html.match(/<(div|section|main|header|footer|nav|ul|ol|button|form)\b/gi) || []).length;
    const closed = (html.match(/<\/(div|section|main|header|footer|nav|ul|ol|button|form)>/gi) || []).length;
    if (opened !== closed) problems.push(`${page} opens ${opened} blocks but closes ${closed}; a tag is missing.`);
  }
  return problems;
}

export function download(name, text, type = "text/html") {
  const blob = text instanceof Blob ? text : new Blob([text], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 5000);
}

// ------------------------------------------------------------------- zip

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** Every file of the project in one .zip (stored, not compressed), in a folder. */
export function zipProject(project) {
  const encoder = new TextEncoder();
  const parts = [];
  const central = [];
  let offset = 0;
  const now = new Date();
  const time = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
  const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  for (const [path, text] of Object.entries(project.files)) {
    const name = encoder.encode(`${project.slug}/${path}`);
    const data = isPicture(text) ? pictureBytes(text) : encoder.encode(text);
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x0800, 2], [8, 0, 2], [10, time, 2], [12, date, 2], [14, crc, 4], [18, data.length, 4], [22, data.length, 4], [26, name.length, 2], [28, 0, 2]].forEach(([at, value, size]) =>
      size === 4 ? local.setUint32(at, value, true) : local.setUint16(at, value, true)
    );
    const entry = new DataView(new ArrayBuffer(46));
    [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x0800, 2], [10, 0, 2], [12, time, 2], [14, date, 2], [16, crc, 4], [20, data.length, 4], [24, data.length, 4], [28, name.length, 2], [30, 0, 2], [32, 0, 2], [34, 0, 2], [36, 0, 2], [38, 0, 4], [42, offset, 4]].forEach(([at, value, size]) =>
      size === 4 ? entry.setUint32(at, value, true) : entry.setUint16(at, value, true)
    );
    parts.push(local, name, data);
    central.push(entry, name);
    offset += 30 + name.length + data.length;
  }
  const size = central.reduce((sum, part) => sum + part.byteLength, 0);
  const end = new DataView(new ArrayBuffer(22));
  const count = Object.keys(project.files).length;
  [[0, 0x06054b50, 4], [4, 0, 2], [6, 0, 2], [8, count, 2], [10, count, 2], [12, size, 4], [16, offset, 4], [20, 0, 2]].forEach(([at, value, bytes]) =>
    bytes === 4 ? end.setUint32(at, value, true) : end.setUint16(at, value, true)
  );
  return new Blob([...parts, ...central, end], { type: "application/zip" });
}

function pictureBytes(dataUrl) {
  const [head, body] = dataUrl.split(",", 2);
  if (!/;base64$/i.test(head)) return new TextEncoder().encode(decodeURIComponent(body));
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
