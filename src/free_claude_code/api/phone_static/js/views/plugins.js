// Plugins and subagents. On this phone: free APIs from the catalog (over
// 1,500), switched on here with their keys kept on the phone, which agents
// find and call with use_plugin; no PC needed. Paired, also the PC's repos
// (skills, plugin agents, MCP servers) and subagents: add a repo from GitHub,
// switch repos and subagents on or off, add a subagent. MCP servers stay off
// until switched on on the PC.
import { state, onChange } from "../state.js";
import { el, button, card, notify, openSheet, closeSheet } from "../ui.js";
import { pcCall } from "../sync.js";
import { allPlugins, findPlugins, setPlugin, hostOf } from "../plugins.js";

const SHOWN = 30;

function keySheet(item, again) {
  const key = el("input", { type: "password", "aria-label": `API key for ${item.name}`, placeholder: item.hasKey ? "Saved: type a new one to change it" : "Paste the key", autocomplete: "off" });
  const hosts = el("input", { "aria-label": `API addresses for ${item.name}`, value: (item.hosts.length ? item.hosts : [hostOf(item.link)]).join(", "), autocapitalize: "off", autocorrect: "off" });
  openSheet(`${item.name} key`, [
    el("p", { text: "The key stays on this phone. It is only sent to the API addresses below, and the AI never sees it." }),
    el("a", { href: item.link, target: "_blank", rel: "noopener noreferrer", text: "Get a key (its docs)" }),
    el("label", {}, ["API key", key]),
    el("label", {}, ["Sent only to (addresses, comma between)", hosts]),
    el("div", { class: "row" }, [
      button("Save", async () => {
        await setPlugin(item.name, {
          on: true,
          ...(key.value.trim() ? { key: key.value.trim() } : {}),
          hosts: hosts.value.split(","),
        });
        closeSheet();
        notify(`${item.name} is on.`);
        again();
      }, { class: "primary" }),
      item.hasKey ? button("Remove the key", async () => { await setPlugin(item.name, { key: "" }); closeSheet(); again(); }, { class: "danger" }) : null,
    ]),
  ]);
}

function phoneRow(item, again) {
  return el("div", { class: "item" }, [
    el("div", { class: "grow" }, [
      el("strong", { text: item.name }),
      el("small", { text: `${item.category} · ${item.needsKey ? (item.hasKey ? "key saved" : "needs a key") : "no key needed"}${item.browserOk ? "" : " · may not answer phones"}` }),
      el("p", { class: "small", text: item.about }),
      el("a", { class: "small", href: item.link, target: "_blank", rel: "noopener noreferrer", text: "Docs" }),
    ]),
    el("div", { class: "row end" }, [
      item.needsKey ? button(item.hasKey ? "Key ✓" : "Add key", () => keySheet(item, again), { "aria-label": `Key for ${item.name}` }) : null,
      el("label", { class: "check" }, [
        el("input", { type: "checkbox", checked: item.on, "aria-label": `${item.name} on`, onchange: async (event) => {
          await setPlugin(item.name, { on: event.target.checked });
          if (event.target.checked && item.needsKey && !item.hasKey) keySheet(item, again);
          again();
        } }),
        el("span", { text: item.on ? "on" : "off" }),
      ]),
    ]),
  ]);
}

export function render(view, param = "") {
  const search = el("input", { type: "search", "aria-label": "Search plugins", placeholder: "weather, football, crypto prices, recipes…", value: decodeURIComponent(param || "") });
  const results = el("div");
  const pcBox = el("div");
  const draw = () => {
    const query = search.value.trim();
    const on = allPlugins().filter((item) => item.on);
    const found = query ? findPlugins(query, SHOWN) : [];
    // While searching, only the results; otherwise what's switched on.
    results.replaceChildren(
      query
        ? card(`Found (${found.length})`, found.length ? found.map((item) => phoneRow(item, draw)) : [el("p", { class: "empty", text: "Nothing matches. Try other words." })])
        : card(`Switched on here (${on.length})`, on.length ? on.map((item) => phoneRow(item, draw)) : [el("p", { class: "empty", text: "None yet. Search above, or let Jarvis pick: he finds the best plugin for a job and asks you to switch it on." })])
    );
  };
  search.addEventListener("input", draw);
  view.replaceChildren(
    card("Plugins on this phone", [
      el("p", { text: `${allPlugins().length.toLocaleString()} free APIs. Switch one on and your agents can use it; Jarvis picks the best fit for what you ask. Keys stay on this phone.` }),
      search,
    ]),
    results,
    pcBox
  );
  draw();
  if (state.settings.pc) renderPc(pcBox);
  return onChange((what) => what === "plugins" && document.activeElement !== search && draw());
}

async function renderPc(view) {
  view.replaceChildren(card("On my PC", [el("p", { class: "muted", text: "Reading your PC…" })]));
  let repos = [];
  let helpers = { roles: [], subagents: [] };
  try {
    [repos, helpers] = await Promise.all([
      pcCall("/studio/api/phone/plugins", undefined, "GET", 30000).then((found) => found.repos || []),
      pcCall("/studio/api/phone/subagents", undefined, "GET", 30000),
    ]);
  } catch (error) {
    view.replaceChildren(card("On my PC", [el("p", { class: "warn", text: error.message })]));
    return;
  }
  const again = () => renderPc(view);
  const switchRepo = async (repo, on) => {
    try {
      await pcCall(`/studio/api/phone/plugins/${encodeURIComponent(repo.id)}/switch`, { on });
      notify(`${repo.name} is ${on ? "on" : "off"}.`);
    } catch (error) {
      notify(error.message);
    }
    again();
  };
  const switchHelper = async (agent, on) => {
    try {
      await pcCall(`/studio/api/phone/subagents/${encodeURIComponent(agent.id)}/switch`, { on });
      notify(`${agent.name} is ${on ? "on" : "off"}.`);
    } catch (error) {
      notify(error.message);
    }
    again();
  };

  const link = el("input", { "aria-label": "GitHub repo", placeholder: "github.com/owner/repo", autocapitalize: "off", autocorrect: "off" });
  const addRepo = async () => {
    if (!link.value.trim()) return notify("Paste a GitHub link first.");
    notify("Your PC is adding it…");
    try {
      const added = await pcCall("/studio/api/phone/plugins", { url: link.value.trim() }, "POST", 180000);
      notify(`Added ${added.name} (${added.skills} skills).`);
      again();
    } catch (error) {
      notify(error.message);
    }
  };

  const name = el("input", { "aria-label": "Subagent name", placeholder: "Checker" });
  const role = el("select", { "aria-label": "Subagent role" }, helpers.roles.map((item) => el("option", { value: item.role, text: `${item.title}: ${item.when}` })));
  const addHelper = async () => {
    if (!name.value.trim()) return notify("Give the subagent a name.");
    try {
      const added = await pcCall("/studio/api/phone/subagents", { name: name.value.trim(), role: role.value });
      notify(`${added.name} joins jobs that fit.`);
      again();
    } catch (error) {
      notify(error.message);
    }
  };

  const repoRow = (repo) =>
    el("div", { class: "item" }, [
      el("div", { class: "grow" }, [
        el("strong", { text: repo.name }),
        el("small", {
          text: [
            repo.skills ? `${repo.skills} skills` : "",
            repo.agents ? `${repo.agents} agents` : "",
            repo.servers ? `${repo.servers} MCP servers (switched on on the PC)` : "",
            repo.origin === "builtin" ? "FCC's own" : repo.origin === "bundled" ? "came with FCC" : "",
          ]
            .filter(Boolean)
            .join(" · ") || repo.description,
        }),
      ]),
      el("label", { class: "check" }, [
        el("input", { type: "checkbox", checked: repo.enabled, "aria-label": `${repo.name} on`, onchange: (event) => switchRepo(repo, event.target.checked) }),
        el("span", { text: repo.enabled ? "on" : "off" }),
      ]),
    ]);
  const helperRow = (agent) =>
    el("div", { class: "item" }, [
      el("div", { class: "grow" }, [el("strong", { text: agent.name }), el("small", { text: `${agent.role} · ${agent.model}` })]),
      el("label", { class: "check" }, [
        el("input", { type: "checkbox", checked: agent.active, "aria-label": `${agent.name} on`, onchange: (event) => switchHelper(agent, event.target.checked) }),
        el("span", { text: agent.active ? "on" : "off" }),
      ]),
    ]);
  const on = repos.filter((repo) => repo.enabled);
  const off = repos.filter((repo) => !repo.enabled);
  view.replaceChildren(
    card("Add a PC plugin from GitHub", [
      link,
      button("Add", addRepo, { class: "primary" }),
      el("p", { class: "muted small", text: "Your PC downloads it, keeps a copy, and reads its skills and agents. Its MCP servers stay off until you switch them on on the PC." }),
    ]),
    card(`On my PC: switched on (${on.length})`, on.length ? on.map(repoRow) : [el("p", { class: "empty", text: "None switched on." })]),
    ...(off.length ? [card(`On my PC: off (${off.length})`, off.map(repoRow))] : []),
    card(`Subagents (${helpers.subagents.length})`, [
      ...(helpers.subagents.length ? helpers.subagents.map(helperRow) : [el("p", { class: "empty", text: "No subagents yet." })]),
      el("label", {}, ["Name", name]),
      el("label", {}, ["Role", role]),
      button("Add a subagent", addHelper),
      el("p", { class: "muted small", text: "A subagent joins the jobs its role fits (at most two at a time) and reports back." }),
    ])
  );
}
