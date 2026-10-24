// Agents: the phone's team, each agent's brain and tools, and Team brains.
import { state, save, changed, newAgent, ROLE_TOOLS, ROLE_PROMPTS, PHONE_TOOLS, MAIN_ONLY, MEMORY_TOOLS, ALL_TOOLS, toolsOf } from "../state.js";
import { el, button, card, go, notify, openSheet, closeSheet, uid } from "../ui.js";
import { PROVIDERS, brainOf, brainReady, isPrivate, modelOf } from "../brains.js";
import { SPECS } from "../tools.js";
import { isBusy } from "../agents.js";

const TEMPLATES = [
  { name: "Builder", role: "builder" },
  { name: "Researcher", role: "researcher" },
  { name: "Helper", role: "helper" },
  { name: "Tester", role: "tester" },
  { name: "Coach", role: "assistant", instructions: "You are an encouraging fitness and habits coach. Remember the user's goals and progress, and check recall before giving advice." },
  { name: "Custom", role: "assistant" },
];

const tokensOf = (name) => Math.round(JSON.stringify({ name, ...SPECS[name] }).length / 4);

export function render(view, sub) {
  if (sub === "brains") return renderBrains(view);
  view.replaceChildren(
    card(
      "Your phone team",
      state.agents.map((agent) =>
        el("div", { class: "item" }, [
          el("div", { class: "grow" }, [
            el("strong", { text: agent.name }),
            el("small", { text: `${agent.role === "main" ? "main AI" : agent.role} · ${brainLabel(agent)} · ${agent.allTools ? "every tool" : `${toolsOf(agent).length} tools`}` }),
          ]),
          isBusy(agent) ? el("span", { class: "pill gold", text: "working" }) : null,
          button("Chat", () => go(`chat/${agent.id}`), { "aria-label": `Chat with ${agent.name}` }),
          button("Edit", () => editAgent(agent), { "aria-label": `Edit ${agent.name}` }),
        ])
      )
    ),
    card("Team brains", [
      el("p", { class: "muted", text: "Give each agent its own brain: a model on this phone, a free cloud AI, or your PC." }),
      button("Choose each agent's brain", () => go("agents/brains"), { class: "primary" }),
    ]),
    card("Add an agent", [
      el("p", { class: "muted", text: "Start from one of these, then change anything." }),
      el("div", { class: "row" }, TEMPLATES.map((template) => button(template.name, () => editAgent(null, template)))),
    ])
  );
}

function brainLabel(agent) {
  const brain = brainOf(agent);
  if (!brain) return "no brain yet";
  const label = agent.brain === "default" ? `default (${PROVIDERS[brain].label})` : PROVIDERS[brain].label;
  return modelOf(agent) ? `${label} · ${modelOf(agent)}` : label;
}

function brainPicker(agent) {
  const brain = el("select", { "aria-label": `Brain for ${agent.name}` }, [
    el("option", { value: "default", text: `Default (${state.settings.brain ? PROVIDERS[state.settings.brain].label : "not set"})` }),
    ...Object.entries(PROVIDERS)
      .filter(([id]) => id !== "pc" || state.settings.pc)
      .map(([id, provider]) => el("option", { value: id, text: `${provider.label}${brainReady(id) ? "" : " (not set up)"}` })),
  ]);
  brain.value = agent.brain || "default";
  const local = el("select", { "aria-label": `Phone model for ${agent.name}` }, [
    el("option", { value: "", text: "The loaded or default phone model" }),
    ...state.models.filter((model) => model.ready).map((model) => el("option", { value: model.id, text: model.name })),
  ]);
  local.value = agent.brain === "local" ? agent.model || "" : "";
  const model = el("input", { "aria-label": `Model for ${agent.name}`, placeholder: "Leave empty for the brain's model", value: agent.brain !== "local" ? agent.model || "" : "" });
  const localRow = el("label", {}, ["Phone model", local]);
  const modelRow = el("label", {}, ["Model (optional)", model]);
  const sync = () => {
    localRow.hidden = brain.value !== "local";
    modelRow.hidden = ["local", "pc", "default"].includes(brain.value);
  };
  brain.addEventListener("change", sync);
  sync();
  return {
    nodes: [el("label", {}, ["Brain", brain]), localRow, modelRow],
    read: () => ({ brain: brain.value, model: brain.value === "local" ? local.value : ["pc", "default"].includes(brain.value) ? "" : model.value.trim() }),
  };
}

function toolPicker(agent) {
  const boxes = [];
  const every = el("input", { type: "checkbox", checked: agent.allTools, "aria-label": `Every tool for ${agent.name}` });
  const count = el("p", { class: "tool-count" });
  const groups = {};
  for (const [name, group] of Object.entries(PHONE_TOOLS)) {
    if (MAIN_ONLY.has(name) && agent.role !== "main") continue;
    (groups[group] = groups[group] || []).push(name);
  }
  const blocked = (name) => name === "web_search" && !state.settings.pc;
  const draw = () => {
    for (const [name, box] of boxes) {
      box.disabled = every.checked || blocked(name);
      if (every.checked) box.checked = !blocked(name);
    }
    const on = boxes.filter(([, box]) => box.checked).map(([name]) => name);
    count.textContent = `${every.checked ? "Every tool" : `${on.length} tools`}: about ${on.reduce((sum, name) => sum + tokensOf(name), 0).toLocaleString()} tokens on every message.`;
  };
  const fieldsets = Object.entries(groups).map(([group, names]) =>
    el("fieldset", { class: "tool-group" }, [
      el("legend", { text: group }),
      ...names.map((name) => {
        const box = el("input", { type: "checkbox", checked: (agent.tools || []).includes(name), "aria-label": `${name} for ${agent.name}` });
        box.addEventListener("change", draw);
        boxes.push([name, box]);
        const note = blocked(name) ? "needs your PC paired" : MEMORY_TOOLS.has(name) && isPrivate(agent) === false && state.settings.pc ? `~${tokensOf(name)} tokens` : `~${tokensOf(name)} tokens`;
        return el("label", { class: "check tool-check", title: SPECS[name].description }, [box, el("span", { text: name.replace(/_/g, " ") }), el("small", { class: "muted", text: note })]);
      }),
    ])
  );
  every.addEventListener("change", draw);
  const own = new Set(agent.tools || []);
  every.addEventListener("change", () => {
    if (!every.checked) for (const [name, box] of boxes) box.checked = own.has(name) && !blocked(name);
    draw();
  });
  draw();
  return {
    nodes: [
      el("label", { class: "check" }, [every, el("span", { text: "Every tool" })]),
      el("p", { class: "muted small", text: "Fewer tools means fewer tokens on every message, which matters most for models on the phone." }),
      ...fieldsets,
      count,
    ],
    read: () => ({
      allTools: every.checked,
      tools: every.checked ? [...own] : boxes.filter(([, box]) => box.checked).map(([name]) => name),
    }),
  };
}

function editAgent(agent, template) {
  const isNew = !agent;
  const draft = agent
    ? { ...agent }
    : newAgent({ id: uid(), name: template.name === "Custom" ? "" : template.name, role: template.role, ...(template.instructions ? { instructions: template.instructions } : {}) });
  const name = el("input", { value: draft.name, "aria-label": "Name", placeholder: "e.g. Coach" });
  const role = el(
    "select",
    { "aria-label": "Role", disabled: draft.role === "main" },
    Object.keys(ROLE_TOOLS).map((item) => el("option", { value: item, text: item === "main" ? "main AI" : item }))
  );
  role.value = draft.role;
  const instructions = el("textarea", { "aria-label": "Instructions", placeholder: "What this agent is for and how it should work." });
  instructions.value = draft.instructions || "";
  role.addEventListener("change", () => {
    if (!instructions.value.trim() || Object.values(ROLE_PROMPTS).includes(instructions.value)) instructions.value = ROLE_PROMPTS[role.value] || "";
  });
  const brain = brainPicker(draft);
  const tools = toolPicker(draft);
  openSheet(isNew ? "New agent" : `Edit ${draft.name}`, [
    el("label", {}, ["Name", name]),
    el("label", {}, ["Role", role]),
    el("label", {}, ["Instructions", instructions]),
    ...brain.nodes,
    el("h3", { class: "subhead", text: "Tools" }),
    ...tools.nodes,
    el("div", { class: "row" }, [
      button(isNew ? "Create agent" : "Save", async () => {
        if (!name.value.trim()) return notify("Give it a name.");
        if (state.agents.some((item) => item.id !== draft.id && item.name.toLowerCase() === name.value.trim().toLowerCase())) return notify("Another agent has that name.");
        Object.assign(draft, { name: name.value.trim().slice(0, 40), role: draft.role === "main" ? "main" : role.value, instructions: instructions.value.trim(), ...brain.read(), ...tools.read() });
        if (isNew) state.agents.push(draft);
        else Object.assign(agent, draft);
        await save.agents();
        changed("team");
        closeSheet();
        notify(isNew ? `${draft.name} joined your phone team.` : "Saved.");
        go("agents");
      }, { class: "primary" }),
      isNew || draft.id === "jarvis" ? null : button("Delete", () => deleteAgent(agent), { class: "danger" }),
    ]),
  ]);
}

async function deleteAgent(agent) {
  if (!confirm(`Delete ${agent.name} and its chat? Memories it saved stay.`)) return;
  state.agents = state.agents.filter((item) => item.id !== agent.id);
  delete state.chats[agent.id];
  const { store } = await import("../store.js");
  await Promise.all([save.agents(), store.remove(`chat:${agent.id}`)]);
  if (state.agentId === agent.id) state.agentId = "jarvis";
  changed("team");
  closeSheet();
  notify(`${agent.name} deleted.`);
  go("agents");
}

function renderBrains(view) {
  const pickers = state.agents.map((agent) => ({ agent, picker: brainPicker(agent) }));
  view.replaceChildren(
    card("Team brains", [
      el("p", { class: "muted", text: "Pick where each agent thinks. Models on this phone run one at a time, so agents on the phone take turns; cloud and PC brains can work side by side." }),
      ...pickers.map(({ agent, picker }) => el("div", { class: "brain-row" }, [el("strong", { text: agent.name }), ...picker.nodes])),
      el("div", { class: "row" }, [
        button("Save", async () => {
          for (const { agent, picker } of pickers) Object.assign(agent, picker.read());
          await save.agents();
          changed("team");
          notify("Team brains saved.");
          go("agents");
        }, { class: "primary" }),
        button("Back", () => go("agents")),
      ]),
    ])
  );
}

export { ALL_TOOLS };
