// The Web kit on the phone: a design system (web/kit.css, kit.js) and
// polished sections (web/sections.js) that websites are built from, the
// guide to website design engineering, and the web_kit tool the AI uses.
import { SECTIONS, LOOKS, FONTS, RECIPES, pageHtml, lookCss } from "../web/sections.js";

export { SECTIONS, LOOKS, FONTS, RECIPES, pageHtml, lookCss };

async function appFile(path) {
  const response = await fetch(new URL(`../${path}`, import.meta.url));
  if (!response.ok) throw new Error(`The Web kit couldn't read ${path} (${response.status}).`);
  return response.text();
}

/** The kit's own files, as a project keeps them (kit/kit.css, kit/kit.js). */
export async function kitFiles() {
  return { "kit/kit.css": await appFile("web/kit.css"), "kit/kit.js": await appFile("web/kit.js") };
}

/** A whole site from the kit: the page, its look, and the kit. */
export async function webKitFiles(title, { recipe = "", sections = null, look = "", fonts = "", description = "" } = {}) {
  const base = RECIPES[recipe] || null;
  const chosen = Array.isArray(sections) && sections.length ? sections.filter((id) => SECTIONS[id]) : base ? base.sections : RECIPES.business.sections;
  if (!chosen.length) throw new Error(`None of those are kit sections. The list action shows them.`);
  const lookId = LOOKS[look] ? look : base ? base.look : "ocean";
  const fontsId = FONTS[fonts] ? fonts : "";
  return {
    "index.html": pageHtml({ title: String(title || "My site").replace(/[<>]/g, ""), description, sections: chosen, look: lookId, fonts: fontsId }),
    "styles.css": lookCss(lookId, fontsId),
    ...(await kitFiles()),
  };
}

export const WEB_GUIDE = `Website design engineering with the FCC Web kit

Start: web_kit page with a recipe (business, startup, studio, shop, service) or your own list of sections, a look and a title. That writes index.html, styles.css (the site's look: --brand, --accent, the fonts) and kit/kit.css + kit/kit.js (the design system). Then make it the user's: every word real, every picture real.

Plan before you build:
- Who is it for, what one action should they take (book, buy, call, sign up), and what would make them trust it. Every section earns its place by helping that action.
- Order: hook (hero) → proof (logos, numbers, reviews) → what you get (features, menu, products, pricing) → doubts answered (FAQ, guarantees) → the action (CTA, contact) → footer.

Design rules that make a site look expensive:
- Hierarchy: one idea per section, one H1 per page, a short eyebrow over each H2, headlines of 3-8 words that say a benefit, not a feature.
- Type: the kit's fluid scale (--step--1 … --step-5); body 16-18px, lines 60-75 characters; never more than two font families; headings tight (-0.02em), body relaxed (1.6).
- Space: generous, consistent (the --space-* scale); sections breathe (section = --space-2xl top and bottom); group related things, separate unrelated ones.
- Colour: one brand colour, one accent, neutrals for everything else; the brand colour marks what to tap. Check contrast (4.5:1 for text) with polish_check.
- Pictures: real photos of the real thing beat stock (find_images, or the user's photos with use_photo); same mood and colour temperature across the page; give each one alt text. The kit's gradient .art panels are stand-ins: replace them (put an <img class="photo"> inside or swap the div).
- Copy: speak to the reader ("you"), concrete numbers, short sentences, buttons that say what happens ("Book a table", not "Submit").
- Mobile first: check at 390px wide first (look_at_site); tap targets 44px+, the phone menu works, nothing scrolls sideways, forms use the right keyboard (type=email, tel).
- Motion: the kit reveals sections on scroll and respects reduce-motion; never animate for its own sake.
- Accessibility: the skip link, real labels on fields, landmarks (header, main, footer), focus rings visible, alt text.
- Speed: no heavy libraries; pictures sized for the screen (find_images gives web sizes); fonts with display=swap.

Make it yours: change the look in styles.css (--brand, --accent, --font-head, --font-body, or data-theme="dark" on <html>), add your own CSS below it, and add sections by copying from web_kit section. Make something original in the spirit of the user's references (library tool); never copy a site.

Finish: check_project, look_at_site on a phone and a computer, polish_check; fix every note; then read it once as the customer would.`;

/** The web_kit tool: the guide, what's in the kit, one section's markup, a
 * whole page from sections, or the kit added to a project. */
export async function useWebKit(args, ctx, writeFile) {
  const action = String(args.action || "guide");
  if (action === "guide") return WEB_GUIDE;
  if (action === "list") {
    const groups = {};
    for (const [id, section] of Object.entries(SECTIONS)) (groups[section.group] = groups[section.group] || []).push(`${id} (${section.about})`);
    return [
      "Sections:",
      ...Object.entries(groups).map(([group, items]) => `- ${group}: ${items.join("; ")}`),
      `Looks (brand, accent, theme, fonts): ${Object.entries(LOOKS).map(([id, look]) => `${id} ${look.brand}/${look.accent} ${look.theme} ${look.fonts}`).join("; ")}`,
      `Font pairs: ${Object.entries(FONTS).map(([id, pair]) => `${id} (${pair.name})`).join(", ")}`,
      `Recipes: ${Object.entries(RECIPES).map(([id, recipe]) => `${id} (${recipe.name}: ${recipe.sections.join(", ")})`).join("; ")}`,
    ].join("\n");
  }
  if (action === "section") {
    const section = SECTIONS[String(args.id || "")];
    if (!section) throw new Error(`No section called ${args.id}. The list action shows them.`);
    return `${section.name} (${section.group}): ${section.about}\nIt needs kit/kit.css (web_kit add). Replace FCCNAME with the site's name.\n\n${section.html}`;
  }
  if (action === "page" || action === "add") {
    if (ctx.partsOnly) return "As a helper you write only under parts/: put your section or page there (web_kit section shows the markup).";
    if (!ctx.project) throw new Error("Start or pick a project first (start_project), then use web_kit page.");
    const files = action === "add" ? await kitFiles() : await webKitFiles(args.title || ctx.project.name, { recipe: args.recipe, sections: args.sections, look: args.look, fonts: args.fonts, description: args.description });
    for (const [path, body] of Object.entries(files)) await writeFile(ctx.project, path, body);
    return action === "add"
      ? `Put the Web kit in ${ctx.project.name}: kit/kit.css and kit/kit.js. Link them in each page: <link rel="stylesheet" href="kit/kit.css" /> before your styles.css, and <script src="kit/kit.js" defer></script>.`
      : `Built ${ctx.project.name} from the Web kit: ${Object.keys(files).join(", ")}. Now write the real content into index.html, swap the .art stand-ins for real photos, and set the look in styles.css. Then check_project, look_at_site and polish_check.`;
  }
  throw new Error("action is guide, list, section, page or add.");
}
