// A designer's once-over for a web project: what would make it look finished.
// The same rules and wording as polish_check on the PC.
const HEX = /#(?:[0-9a-fA-F]{3}){1,2}\b/g;
const RULE = /([^{}]+)\{([^{}]*)\}/g;
const FONT_PX = /font-size\s*:\s*(\d+(?:\.\d+)?)px/gi;
const MIN_TEXT_PX = 14;
const MAX_COLORS = 14;
const MAX_NOTES = 24;

function rgb(hex) {
  let value = hex.replace("#", "");
  if (value.length === 3) value = [...value].map((char) => char + char).join("");
  return [0, 2, 4].map((at) => parseInt(value.slice(at, at + 2), 16) / 255);
}

function luminance(hex) {
  const channel = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const [r, g, b] = rgb(hex).map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** The WCAG contrast ratio between two hex colours (1 to 21). */
export function contrast(first, second) {
  const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

function declared(block, name) {
  const match = block.match(new RegExp(`(?:^|;)\\s*${name}\\s*:\\s*([^;]+)`, "i"));
  return match ? match[1].trim() : null;
}

function colorOf(value, variables) {
  if (!value) return null;
  const variable = value.match(/var\(\s*(--[\w-]+)/);
  if (variable) value = variables[variable[1]] || "";
  const found = value.match(/#(?:[0-9a-fA-F]{3}){1,2}\b/);
  return found ? found[0] : null;
}

/** Suggestions that make a working page look and feel finished. files: {path: text}. */
export function polishNotes(files) {
  const entries = Object.entries(files);
  const css = entries.filter(([path]) => path.endsWith(".css")).map(([, text]) => text).join("\n");
  const pages = entries.filter(([path]) => path.endsWith(".html") || path.endsWith(".htm"));
  const inline = pages.flatMap(([, text]) => [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map((match) => match[1])).join("\n");
  const styles = `${css}\n${inline}`;
  if (!pages.length) return [];
  if (!styles.trim()) {
    return ["The pages have no styles at all: add a stylesheet with a color scheme, spacing, and a readable font."];
  }
  const notes = [];
  const variables = Object.fromEntries([...styles.matchAll(/(--[\w-]+)\s*:\s*([^;}]+)/g)].map((match) => [match[1], match[2]]));
  const rules = [...styles.matchAll(RULE)].map((match) => [match[1].trim(), match[2]]);
  const bodyRules = rules.filter(([selector]) => /(^|,)\s*(body|:root|html)\s*($|,)/.test(selector)).map(([, body]) => body);
  let textColor = null;
  let background = null;
  for (const body of bodyRules) {
    textColor = textColor || colorOf(declared(body, "color"), variables);
    background = background || colorOf(declared(body, "background-color") || declared(body, "background"), variables);
  }
  if (textColor && background && contrast(textColor, background) < 4.5) {
    notes.push(`Text ${textColor} on ${background} has a contrast of ${contrast(textColor, background).toFixed(1)}:1; make it at least 4.5:1 so it is easy to read.`);
  }
  if (!styles.includes("@media") && !/clamp\(|auto-fit|auto-fill|minmax\(/.test(styles)) {
    notes.push("Nothing adapts to screen size: add @media rules or fluid sizes (clamp, grid auto-fit) so it works on phones.");
  }
  if (!styles.includes(":focus")) notes.push("Add :focus-visible styles so keyboard users can see where they are.");
  const clickable = /(^|[\s,}])(a|button|\.button|\.btn)\b[^{]*\{/.test(styles);
  if (clickable && !styles.includes(":hover")) notes.push("Buttons and links have no :hover state; give them one so they feel clickable.");
  const tiny = [...new Set([...styles.matchAll(FONT_PX)].map((match) => parseFloat(match[1])).filter((px) => px < MIN_TEXT_PX))].sort((a, b) => a - b);
  if (tiny.length) notes.push(`Some text is only ${tiny[0]}px; keep body text at ${MIN_TEXT_PX}px or more (16px is best).`);
  const colors = new Set((styles.match(HEX) || []).map((color) => color.toLowerCase()));
  const hasVariables = Object.keys(variables).length > 0;
  if (colors.size > MAX_COLORS && !hasVariables) {
    notes.push(`${colors.size} different colors are scattered through the CSS; put a small palette in :root variables and reuse it.`);
  }
  if (!hasVariables && colors.size > 4) notes.push("Define colors and spacing once as CSS variables in :root so the design stays consistent.");
  if (!styles.includes("max-width") && !styles.includes("min(")) {
    notes.push("Content can stretch edge to edge on wide screens; give it a max-width (about 1100px) and center it.");
  }
  if (!styles.includes("line-height")) notes.push("Set a line-height around 1.5 for comfortable reading.");
  if (!styles.includes("font-family")) {
    notes.push("No font is chosen, so the browser's plain default shows: set a font-family (a Google Font such as Inter or Poppins, or system-ui).");
  }
  if (!styles.includes("transition") && clickable) notes.push("Add short transitions (150-250ms) to hovers and toggles so changes feel smooth.");
  const backgroundPicture = /background(-image)?\s*:[^;]*url\(/i.test(styles);
  for (const [path, text] of pages) {
    if (!/<(header|nav|main|footer)\b/i.test(text)) notes.push(`${path}: use header, nav, main, and footer so the layout has clear structure.`);
    if (!/<h1\b/i.test(text)) notes.push(`${path}: has no <h1> headline.`);
    if (/<img\b(?![^>]*\b(?:width|height|loading)=)/i.test(text)) {
      notes.push(`${path}: give images width and height (or loading="lazy") so the page does not jump while loading.`);
    }
    if (/<img\b(?![^>]*\balt=)/i.test(text)) notes.push(`${path}: every <img> needs alt text describing it (alt="" for decoration).`);
    // Ignore <link> tags: an emoji favicon is an <svg> inside an attribute.
    const body = text.replace(/<link\b(?:"[^"]*"|'[^']*'|[^'">])*>/gi, "");
    const contentPage = (text.match(/<section\b/gi) || []).length >= 2;
    if (contentPage && !/<(img|svg|picture|video|canvas)\b/i.test(body) && !backgroundPicture) {
      notes.push(`${path}: has no pictures; a real photo (find_images) or an SVG illustration makes it look finished.`);
    }
    if (!/<meta[^>]+name=["']description/i.test(text)) {
      notes.push(`${path}: add <meta name="description" content="..."> so search engines and shared links show a summary.`);
    }
    if (!text.includes('rel="icon"') && !text.includes("rel='icon'")) {
      notes.push(`${path}: add a favicon (an emoji SVG works: <link rel="icon" href="data:image/svg+xml,...">).`);
    }
  }
  return notes.slice(0, MAX_NOTES);
}
