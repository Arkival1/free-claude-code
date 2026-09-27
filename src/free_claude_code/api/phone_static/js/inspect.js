// look_at_site: open the project like a visitor would, on a phone and on a
// computer, and measure what a person would notice: sideways scrolling,
// broken pictures, tiny text, small buttons, hard-to-read colours, errors.
// The page runs in a sandboxed frame; a small script inside it measures and
// posts the results back, so the page never touches the app.
import { previewHtml } from "./projects.js";

export const WIDTHS = [
  { label: "Phone", width: 390, height: 844 },
  { label: "Computer", width: 1280, height: 800 },
];
const WAIT_MS = 8000;

// Runs inside the page. TOKEN is replaced per look.
const MEASURE = `(() => {
  const TOKEN = "__TOKEN__";
  const errors = [];
  const broken = new Set();
  addEventListener("error", (event) => {
    const target = event.target;
    if (target && target.tagName === "IMG") broken.add(target.getAttribute("src") || "(no src)");
    else if (event.message) errors.push(String(event.message).slice(0, 160));
  }, true);
  addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    errors.push("Unhandled promise: " + String((reason && reason.message) || reason).slice(0, 140));
  });
  const name = (el) => {
    let text = el.tagName.toLowerCase();
    if (el.id) text += "#" + el.id;
    else if (typeof el.className === "string" && el.className.trim()) text += "." + el.className.trim().split(/\\s+/).slice(0, 2).join(".");
    return text;
  };
  const words = (el) => (el.innerText || el.getAttribute("aria-label") || el.value || "").trim().replace(/\\s+/g, " ").slice(0, 40);
  const shown = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && Number(style.opacity) > 0.05;
  };
  const parse = (value) => {
    const match = value.match(/rgba?\\(([^)]+)\\)/);
    if (!match) return null;
    const parts = match[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const behind = (el) => {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== "none") return null;
      const color = parse(style.backgroundColor);
      if (color && color.a > 0.9) return color;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  let sent = false;
  const report = () => {
    if (sent) return;
    sent = true;
    const width = innerWidth;
    const root = document.documentElement;
    const all = [...document.body ? document.body.querySelectorAll("*") : []];
    const wide = [];
    for (const el of all) {
      if (wide.length >= 3) break;
      const rect = el.getBoundingClientRect();
      if (rect.right > width + 2 && rect.width > 0 && getComputedStyle(el).position !== "fixed" && shown(el)) {
        if (!wide.some((item) => el.closest(item.selector))) wide.push({ selector: name(el), width: Math.round(rect.width), right: Math.round(rect.right) });
      }
    }
    const tiny = [];
    const faint = [];
    for (const el of all) {
      const own = [...el.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim());
      if (!own || !shown(el) || ["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName)) continue;
      const style = getComputedStyle(el);
      const size = parseFloat(style.fontSize);
      if (size < 12 && tiny.length < 3) tiny.push({ text: words(el), px: Math.round(size * 10) / 10 });
      const color = parse(style.color);
      const back = behind(el);
      if (color && back && faint.length < 3) {
        const [light, dark] = [lum(color), lum(back)].sort((a, b) => b - a);
        const ratio = (light + 0.05) / (dark + 0.05);
        const large = size >= 24 || (size >= 18.6 && Number(style.fontWeight) >= 700);
        if (ratio < (large ? 3 : 4.5)) faint.push({ text: words(el), ratio: Math.round(ratio * 10) / 10 });
      }
    }
    const small = [];
    if (width < 600) {
      for (const el of document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button]")) {
        if (!shown(el)) continue;
        const rect = el.getBoundingClientRect();
        if ((rect.width < 32 || rect.height < 32) && small.length < 4 && !(el.tagName === "A" && getComputedStyle(el).display === "inline")) {
          small.push({ text: words(el) || name(el), w: Math.round(rect.width), h: Math.round(rect.height) });
        }
      }
    }
    const images = [...document.images];
    for (const img of images) if (img.complete && img.naturalWidth === 0 && img.getAttribute("src")) broken.add(img.getAttribute("src"));
    const stretched = [];
    for (const img of images) {
      if (!img.complete || !img.naturalWidth || !shown(img) || stretched.length >= 3) continue;
      const rect = img.getBoundingClientRect();
      const fit = getComputedStyle(img).objectFit;
      const drawn = rect.width / rect.height;
      const real = img.naturalWidth / img.naturalHeight;
      if ((fit === "fill" || !fit) && Math.abs(drawn / real - 1) > 0.08) {
        stretched.push({ src: (img.getAttribute("src") || "").slice(0, 60), w: Math.round(rect.width), h: Math.round(rect.height) });
      }
    }
    const firstScreen = (sel) => [...document.querySelectorAll(sel)].find((el) => shown(el) && el.getBoundingClientRect().top < innerHeight);
    const heading = firstScreen("h1, h2");
    const action = firstScreen("a.button, a.btn, button, [role=button], input[type=submit]");
    const picture = [...document.querySelectorAll("img, svg, picture, video, canvas")].some((el) => shown(el) && el.getBoundingClientRect().top < innerHeight && el.getBoundingClientRect().width > 80);
    parent.postMessage({
      fccLook: TOKEN,
      width,
      screens: Math.round((root.scrollHeight / innerHeight) * 10) / 10,
      sideways: root.scrollWidth > width + 2,
      wide,
      tiny,
      faint,
      small,
      broken: [...broken].slice(0, 5),
      stretched,
      errors: errors.slice(0, 5),
      title: document.title,
      h1: document.querySelectorAll("h1").length,
      images: images.length,
      noAlt: images.filter((img) => !img.hasAttribute("alt")).length,
      heading: heading ? words(heading) : "",
      action: action ? words(action) : "",
      picture,
    }, "*");
  };
  addEventListener("load", () => setTimeout(report, 600));
  setTimeout(report, ${WAIT_MS - 1500});
})();`;

function measure(project, size) {
  return new Promise((resolve) => {
    const token = Math.random().toString(36).slice(2);
    const html = previewHtml(project, `<script>${MEASURE.replace("__TOKEN__", token)}</script>`);
    if (html === null) return resolve(null);
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("aria-hidden", "true");
    frame.tabIndex = -1;
    frame.style.cssText = `position:fixed;left:0;top:0;width:${size.width}px;height:${size.height}px;border:0;opacity:0;pointer-events:none;z-index:-1`;
    let done = false;
    const finish = (result) => {
      if (done) return;
      done = true;
      removeEventListener("message", onMessage);
      clearTimeout(timer);
      frame.remove();
      resolve(result);
    };
    const onMessage = (event) => {
      if (event.source === frame.contentWindow && event.data && event.data.fccLook === token) finish({ ...event.data, label: size.label });
    };
    const timer = setTimeout(() => finish({ label: size.label, width: size.width, timedOut: true }), WAIT_MS);
    addEventListener("message", onMessage);
    frame.srcdoc = html;
    document.body.append(frame);
  });
}

/** Measure the project's front page at each width. Null when it has no page. */
export async function lookAtSite(project) {
  const results = [];
  for (const size of WIDTHS) {
    const result = await measure(project, size);
    if (result === null) return null;
    results.push(result);
  }
  return results;
}

/** What the looks found, as plain text for an agent. */
export function describeLook(results) {
  const lines = [];
  let problems = 0;
  for (const look of results) {
    lines.push(`${look.label} (${look.width}px wide):`);
    if (look.timedOut) {
      lines.push("- The page didn't finish loading in time; a script may be stuck in a loop.");
      problems += 1;
      continue;
    }
    const first = [look.heading && `heading "${look.heading}"`, look.action && `button "${look.action}"`, look.picture ? "a picture" : "no picture"].filter(Boolean).join(", ");
    lines.push(`- ${look.screens} screens tall. First screen shows: ${first}.`);
    const found = [];
    if (look.sideways) {
      const culprits = look.wide.map((item) => `${item.selector} (${item.width}px wide)`).join(", ");
      found.push(`Scrolls sideways: something is wider than the screen${culprits ? `: ${culprits}` : ""}. Use max-width: 100%, flex-wrap, or a grid with minmax.`);
    }
    for (const src of look.broken) found.push(`Broken picture: ${src} didn't load.`);
    for (const item of look.stretched || []) {
      found.push(`Stretched picture: ${item.src} is squashed to ${item.w}x${item.h}; add img { height: auto; } (or object-fit: cover with a fixed height).`);
    }
    for (const error of look.errors) found.push(`Script error: ${error}`);
    if (look.tiny.length) found.push(`Tiny text: ${look.tiny.map((item) => `"${item.text}" at ${item.px}px`).join(", ")}; use 14px or more.`);
    if (look.faint.length) found.push(`Hard to read: ${look.faint.map((item) => `"${item.text}" (${item.ratio}:1)`).join(", ")}; aim for 4.5:1 contrast.`);
    if (look.small.length) found.push(`Small tap targets: ${look.small.map((item) => `"${item.text}" (${item.w}x${item.h})`).join(", ")}; make buttons and links at least 44px tall on phones.`);
    if (!look.title) found.push("The page has no <title>.");
    if (!look.h1) found.push("There is no <h1> headline.");
    if (look.noAlt) found.push(`${look.noAlt} picture(s) have no alt text.`);
    problems += found.length;
    lines.push(...(found.length ? found.map((text) => `- ${text}`) : ["- Nothing wrong spotted."]));
  }
  lines.unshift(problems ? `Looked at the site: ${problems} thing(s) to fix.` : "Looked at the site: it looks right on a phone and a computer.");
  return lines.join("\n");
}
