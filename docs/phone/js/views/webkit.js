// The Web kit room (#lab/web): put a website together from the kit's
// sections in a look, see it live at phone or computer size, then start it
// as a project (the AI or you write the real words and pictures) or ask the
// AI to build one.
import { state } from "../state.js";
import { el, button, card, notify, go, openSheet, closeSheet } from "../ui.js";
import { createProject, writeFile } from "../projects.js";
import { SECTIONS, LOOKS, FONTS, RECIPES, pageHtml, lookCss, kitFiles, webKitFiles } from "../webkit.js";

const GROUPS = ["Navigation", "Hero", "Proof", "Features", "Offer", "Content", "Action", "Footer"];

export function render(view) {
  const choice = (state.webKit = state.webKit || { recipe: "business", sections: [...RECIPES.business.sections], look: RECIPES.business.look, fonts: "", theme: "" });
  let width = "phone";
  let kit = null;
  const frame = el("iframe", { class: "web-preview", title: "Website preview", sandbox: "allow-scripts", "data-width": width });
  const holder = el("div", { class: "web-frame", "data-width": width }, [frame]);
  const controls = el("div");

  const page = () => {
    let html = pageHtml({ title: "Your Business", sections: choice.sections, look: choice.look, fonts: choice.fonts });
    if (choice.theme) html = html.replace(/data-theme="(light|dark)"/, `data-theme="${choice.theme}"`);
    return html;
  };
  const preview = () => {
    if (!kit) return;
    frame.srcdoc = page()
      .replace('<link rel="stylesheet" href="kit/kit.css" />', `<style>${kit["kit/kit.css"]}</style>`)
      .replace('<link rel="stylesheet" href="styles.css" />', `<style>${lookCss(choice.look, choice.fonts)}</style>`)
      .replace('<script src="kit/kit.js" defer></script>', `<script>${kit["kit/kit.js"]}</script>`);
  };

  const startSheet = () => {
    const name = el("input", { "aria-label": "The site's name", placeholder: "Harbour Café" });
    const about = el("input", { "aria-label": "One line about it", placeholder: "Coffee and fresh bakes on the harbour since 2014" });
    openSheet("Start this site", [
      el("p", { class: "small muted", text: "A project with these sections in this look. Then you or the AI write the real words and swap in real photos." }),
      el("label", {}, ["Name", name]),
      el("label", {}, ["One line about it", about]),
      button("Start it", async () => {
        try {
          const project = await createProject(name.value.trim() || "My website");
          const files = await webKitFiles(project.name, { sections: choice.sections, look: choice.look, fonts: choice.fonts, description: about.value.trim() });
          if (choice.theme) files["index.html"] = files["index.html"].replace(/data-theme="(light|dark)"/, `data-theme="${choice.theme}"`);
          for (const [path, body] of Object.entries(files)) await writeFile(project, path, body, "you");
          closeSheet();
          notify(`${project.name} is ready to make your own.`);
          go(`projects/${project.id}`);
        } catch (error) {
          notify(error.message);
        }
      }, { class: "primary" }),
    ]);
  };

  const draw = () => {
    const move = (index, by) => {
      const next = [...choice.sections];
      const [item] = next.splice(index, 1);
      next.splice(Math.max(0, Math.min(next.length, index + by)), 0, item);
      choice.sections = next;
      choice.recipe = "";
      draw();
    };
    controls.replaceChildren(
      card("Web kit", [
        el("p", { text: "Websites built from polished sections on one design system: pick a starting point, a look and the sections, see it live, then make it yours. The AI builds sites from this same kit." }),
        el("div", { class: "row" }, [
          button("⟵ Lab box", () => go("lab")),
          button("Start this site", startSheet, { class: "primary" }),
          button("Ask the AI for one", () => {
            state.labAsk = "a website for ";
            go("home");
          }),
        ]),
      ]),
      card("Start from", [
        el("div", { class: "lab-chips" }, Object.entries(RECIPES).map(([id, recipe]) => el("button", { class: "lib-filter", type: "button", "aria-pressed": String(choice.recipe === id), text: recipe.name, onclick: () => {
          Object.assign(choice, { recipe: id, sections: [...recipe.sections], look: recipe.look, fonts: "" });
          draw();
        } }))),
      ]),
      card("Look", [
        el("div", { class: "lab-chips" }, Object.entries(LOOKS).map(([id, look]) => el("button", { class: "lib-filter web-look", type: "button", "aria-pressed": String(choice.look === id), onclick: () => {
          choice.look = id;
          draw();
        } }, [el("span", { class: "web-swatch", style: { background: `linear-gradient(135deg, ${look.brand}, ${look.accent})` } }), look.name]))),
        el("div", { class: "row" }, [
          el("label", {}, ["Fonts", el("select", { "aria-label": "Fonts", onchange: (event) => {
            choice.fonts = event.target.value;
            draw();
          } }, [el("option", { value: "", text: `The look's own (${FONTS[(LOOKS[choice.look] || LOOKS.ocean).fonts].name})`, selected: !choice.fonts }), ...Object.entries(FONTS).map(([id, pair]) => el("option", { value: id, text: pair.name, selected: choice.fonts === id }))])]),
          el("label", {}, ["Theme", el("select", { "aria-label": "Theme", onchange: (event) => {
            choice.theme = event.target.value;
            draw();
          } }, [["", "The look's own"], ["light", "Light"], ["dark", "Dark"]].map(([value, text]) => el("option", { value, text, selected: choice.theme === value })))]),
        ]),
      ]),
      card(`Sections (${choice.sections.length})`, [
        el("div", { class: "lab-list" }, choice.sections.map((id, index) => el("div", { class: "lab-row" }, [
          el("span", { class: "grow", text: `${SECTIONS[id].name}` }),
          el("button", { class: "lab-x", type: "button", "aria-label": `Move ${SECTIONS[id].name} up`, text: "↑", disabled: index === 0 ? true : null, onclick: () => move(index, -1) }),
          el("button", { class: "lab-x", type: "button", "aria-label": `Move ${SECTIONS[id].name} down`, text: "↓", disabled: index === choice.sections.length - 1 ? true : null, onclick: () => move(index, 1) }),
          el("button", { class: "lab-x", type: "button", "aria-label": `Remove ${SECTIONS[id].name}`, text: "✕", onclick: () => {
            choice.sections = choice.sections.filter((_, i) => i !== index);
            choice.recipe = "";
            draw();
          } }),
        ]))),
        el("details", { class: "lab-bin" }, [
          el("summary", { text: "Add a section" }),
          ...GROUPS.map((group) => el("div", {}, [
            el("p", { class: "small muted", text: group }),
            el("div", { class: "lab-chips" }, Object.entries(SECTIONS).filter(([, section]) => section.group === group).map(([id, section]) => el("button", { class: "lab-chip", type: "button", title: section.about, text: `+ ${section.name}`, onclick: () => {
              const footer = choice.sections.findIndex((item) => SECTIONS[item].group === "Footer");
              const next = [...choice.sections];
              if (section.group === "Navigation") next.unshift(id);
              else if (section.group === "Footer" || footer === -1) next.push(id);
              else next.splice(footer, 0, id);
              choice.sections = next;
              choice.recipe = "";
              draw();
            } }))),
          ])),
        ]),
      ]),
      card("Preview", [
        el("div", { class: "lab-chips" }, [["phone", "Phone"], ["computer", "Computer"]].map(([value, text]) => el("button", { class: "lib-filter", type: "button", "aria-pressed": String(width === value), text, onclick: () => {
          width = value;
          holder.dataset.width = value;
          draw();
          fit();
        } }))),
        holder,
      ]),
    );
    preview();
  };

  // The computer view is a 1280px page scaled down to fit this phone.
  const fit = () => requestAnimationFrame(() => holder.style.setProperty("--fit", String((holder.clientWidth || 360) / 1280)));
  window.addEventListener("resize", fit);
  view.replaceChildren(controls);
  draw();
  fit();
  kitFiles()
    .then((files) => {
      kit = files;
      preview();
    })
    .catch((error) => notify(error.message));
  return () => window.removeEventListener("resize", fit);
}
