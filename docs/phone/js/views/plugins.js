// Plugins and subagents: the repos added on your PC (skills, plugin agents,
// MCP servers) and your subagents. Add a repo from GitHub, switch repos and
// subagents on or off, and add a subagent, all from here; they run on the PC,
// so nothing is downloaded to this phone. MCP servers stay off until you
// switch them on on the PC.
import { state } from "../state.js";
import { el, button, card, go, notify } from "../ui.js";
import { pcCall } from "../sync.js";

export async function render(view) {
  if (!state.settings.pc) {
    view.replaceChildren(
      card("Plugins and subagents", [
        el("p", { text: "Plugins and subagents run on your PC. Pair this phone with your PC to add them, switch them on, and let your phone agents use them." }),
        button("Pair with my PC", () => go("settings"), { class: "primary" }),
      ])
    );
    return;
  }
  view.replaceChildren(card("Plugins and subagents", [el("p", { class: "muted", text: "Reading your PC…" })]));
  let repos = [];
  let helpers = { roles: [], subagents: [] };
  try {
    [repos, helpers] = await Promise.all([
      pcCall("/studio/api/phone/plugins", undefined, "GET", 30000).then((found) => found.repos || []),
      pcCall("/studio/api/phone/subagents", undefined, "GET", 30000),
    ]);
  } catch (error) {
    view.replaceChildren(card("Plugins and subagents", [el("p", { class: "warn", text: error.message })]));
    return;
  }
  const again = () => render(view);
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
    card("How it works", [
      el("p", { text: "Plugins and subagents run on your PC, with its models (and its server model when LM Studio is off), so nothing is downloaded here. Agents read a plugin's skills only when a job needs them. Tasks use all of them." }),
    ]),
    card("Add a plugin from GitHub", [
      link,
      button("Add", addRepo, { class: "primary" }),
      el("p", { class: "muted small", text: "Your PC downloads it, keeps a copy, and reads its skills and agents. Its MCP servers stay off until you switch them on on the PC." }),
    ]),
    card(`Switched on (${on.length})`, on.length ? on.map(repoRow) : [el("p", { class: "empty", text: "None switched on." })]),
    ...(off.length ? [card(`Off (${off.length})`, off.map(repoRow))] : []),
    card(`Subagents (${helpers.subagents.length})`, [
      ...(helpers.subagents.length ? helpers.subagents.map(helperRow) : [el("p", { class: "empty", text: "No subagents yet." })]),
      el("label", {}, ["Name", name]),
      el("label", {}, ["Role", role]),
      button("Add a subagent", addHelper),
      el("p", { class: "muted small", text: "A subagent joins the jobs its role fits (at most two at a time) and reports back." }),
    ])
  );
}
