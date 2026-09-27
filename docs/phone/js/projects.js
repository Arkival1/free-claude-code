// Projects the Builder makes on the phone: files kept on the phone, shown in
// a preview, and saved out as one HTML file you can open anywhere.
import { state, save, changed, feed } from "./state.js";
import { uid } from "./ui.js";

export const MAX_FILE_CHARS = 200_000;
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
  project.files[name] = text;
  project.updated_at = Date.now();
  await save.projects();
  changed("projects");
  feed(agentName, `${isNew ? "Wrote" : "Updated"} ${project.name}/${name} (${text.length.toLocaleString()} characters).`);
  return name;
}

export async function deleteFile(project, path, agentName) {
  const name = cleanPath(path);
  if (!(name in project.files)) throw new Error(`There is no ${name} in ${project.name}.`);
  delete project.files[name];
  project.updated_at = Date.now();
  await save.projects();
  changed("projects");
  feed(agentName, `Deleted ${project.name}/${name}.`);
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
  return html;
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
    if (!text.trim()) problems.push(`${name} is empty.`);
    if (/lorem ipsum|TODO|your (?:text|content) here|placeholder/i.test(text)) problems.push(`${name} still has placeholder text.`);
  }
  for (const page of pages) {
    const html = project.files[page];
    if (!/<!doctype html>/i.test(html)) problems.push(`${page} has no <!DOCTYPE html>.`);
    if (!/<meta[^>]+viewport/i.test(html)) problems.push(`${page} has no viewport tag, so it won't fit phones.`);
    if (!/<title>[^<]+<\/title>/i.test(html)) problems.push(`${page} has no <title>.`);
    for (const match of html.matchAll(/(?:href|src)=["']([^"'#?]+)["']/gi)) {
      const target = match[1];
      if (/^(https?:|mailto:|tel:|data:|\/\/|#)/i.test(target)) continue;
      if (!project.files[cleanRelative(target)]) problems.push(`${page} links to ${target}, which isn't in the project.`);
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
  const blob = new Blob([text], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 5000);
}
