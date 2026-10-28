// Plugins: the repos added on your PC (skills, plugin agents, MCP servers).
// Phone agents read the switched-on skills with the skill tool while paired;
// switching a repo on or off is done on the PC (More, Repos).
import { state } from "../state.js";
import { el, button, card, go } from "../ui.js";
import { pcCall } from "../sync.js";

export async function render(view) {
  if (!state.settings.pc) {
    view.replaceChildren(
      card("Plugins", [
        el("p", { text: "Plugins and skills live on your PC. Pair this phone with your PC and your phone agents can read every skill switched on there." }),
        button("Pair with my PC", () => go("settings"), { class: "primary" }),
      ])
    );
    return;
  }
  view.replaceChildren(card("Plugins", [el("p", { class: "muted", text: "Reading your PC's plugins…" })]));
  let repos = [];
  try {
    repos = (await pcCall("/studio/api/phone/plugins", undefined, "GET", 30000)).repos || [];
  } catch (error) {
    view.replaceChildren(card("Plugins", [el("p", { class: "warn", text: error.message })]));
    return;
  }
  const on = repos.filter((repo) => repo.enabled);
  const off = repos.filter((repo) => !repo.enabled);
  const row = (repo) =>
    el("div", { class: "item" }, [
      el("div", { class: "grow" }, [
        el("strong", { text: repo.name }),
        el("small", {
          text: [
            repo.skills ? `${repo.skills} skills` : "",
            repo.agents ? `${repo.agents} agents` : "",
            repo.servers ? `${repo.servers} MCP servers (stay off)` : "",
            repo.origin === "builtin" ? "FCC's own" : repo.origin === "bundled" ? "came with FCC" : "",
          ]
            .filter(Boolean)
            .join(" · ") || repo.description,
        }),
      ]),
      el("span", { class: `pill ${repo.enabled ? "good" : ""}`, text: repo.enabled ? "on" : "off" }),
    ]);
  view.replaceChildren(
    card("How it works", [
      el("p", { text: "Agents with the skill tool (the Builder and Jarvis to start) search and read these skills while this phone is paired, and use one only when a job needs it. Switch a repo on or off on the PC: More, Repos." }),
    ]),
    card(`Switched on (${on.length})`, on.length ? on.map(row) : [el("p", { class: "empty", text: "None switched on." })]),
    ...(off.length ? [card(`Off (${off.length})`, off.map(row))] : [])
  );
}
