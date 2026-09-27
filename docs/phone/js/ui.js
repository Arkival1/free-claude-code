// Small DOM helpers shared by every screen.

export const $ = (id) => document.getElementById(id);

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked") node.checked = Boolean(value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const card = (title, children, extra = {}) =>
  el("section", { class: `card ${extra.class || ""}`.trim(), ...extra.attrs }, [
    el("h2", { text: title }),
    ...[].concat(children),
  ]);

export const empty = (text) => el("p", { class: "empty", text });

export const button = (text, onclick, extra = {}) =>
  el("button", { type: "button", text, onclick, ...extra });

let toastTimer = null;
export function notify(text) {
  const toast = $("toast");
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 3400);
}

export function openSheet(title, children) {
  $("sheet-title").textContent = title;
  $("sheet-body").replaceChildren(...[].concat(children).filter(Boolean));
  $("sheet").hidden = false;
}

export function closeSheet() {
  $("sheet").hidden = true;
  $("sheet-body").replaceChildren();
}

export const ago = (ms) => {
  if (!ms) return "never";
  const minutes = Math.round((Date.now() - ms) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(ms).toLocaleDateString();
};

export const bytes = (value) => {
  if (!value && value !== 0) return "?";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`;
};

export const uid = () =>
  (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, "").slice(0, 16);

export const words = (text) =>
  String(text || "")
    .toLowerCase()
    .match(/[a-z0-9']{3,}/g) || [];

export function meter(fraction) {
  return el("div", { class: "meter" }, [el("i", { style: { width: `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%` } })]);
}

export function go(route) {
  if (location.hash === `#${route}`) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = route;
}
