// Chats: every agent's conversation, and giving an agent a job.
import { state, chatOf, agentById, onChange, save } from "../state.js";
import { el, button, card, go, notify, openSheet, closeSheet } from "../ui.js";
import { answer, runTask, isBusy } from "../agents.js";
import { brainOf, brainReady, PROVIDERS, modelOf } from "../brains.js";
import { speak, micButton } from "../voice.js";
import { createProject, findProject } from "../projects.js";
import { store } from "../store.js";

export async function renderList(view) {
  const rows = await Promise.all(
    state.agents.map(async (agent) => {
      const chat = await chatOf(agent.id);
      const last = [...chat].reverse().find((turn) => turn.role === "user" || turn.role === "assistant");
      return el("button", { class: "item as-button", type: "button", onclick: () => go(`chat/${agent.id}`), "aria-label": `Chat with ${agent.name}` }, [
        el("div", { class: "grow" }, [el("strong", { text: agent.name }), el("small", { text: last ? last.text.slice(0, 90) : `${agent.role} · no messages yet` })]),
        isBusy(agent) ? el("span", { class: "pill gold", text: "working" }) : null,
      ]);
    })
  );
  view.replaceChildren(card("Chats", rows));
}

export async function render(view, agentId) {
  const agent = agentById(agentId) || agentById(state.agentId) || state.agents[0];
  state.agentId = agent.id;
  store.set("agentId", agent.id);
  const messages = el("div", { class: "messages", "aria-live": "polite" });
  const input = el("textarea", { rows: 1, placeholder: `Message ${agent.name}`, "aria-label": "Message", enterkeyhint: "send" });
  const send = button("Send", () => submit(), { class: "primary" });
  const submit = async () => {
    const text = input.value.trim();
    if (!text || isBusy(agent)) return;
    input.value = "";
    input.style.height = "auto";
    try {
      const said = await answer(agent, text);
      if (agent.role === "main") speak(said);
    } catch (error) {
      notify(error.message);
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(160, input.scrollHeight)}px`;
  });
  const picker = el(
    "select",
    { "aria-label": "Agent", onchange: () => go(`chat/${picker.value}`) },
    state.agents.map((item) => el("option", { value: item.id, text: item.name }))
  );
  picker.value = agent.id;
  const brain = brainOf(agent);
  view.replaceChildren(
    el("div", { class: "chat-head" }, [
      picker,
      button("Job…", () => jobSheet(agent), { "aria-label": `Give ${agent.name} a job` }),
      button("Clear", async () => {
        state.chats[agent.id] = [];
        await save.chat(agent.id);
        draw();
      }, { "aria-label": `Clear the chat with ${agent.name}` }),
    ]),
    el("p", { class: "muted small", text: `${agent.role} · ${brain ? `${PROVIDERS[brain].label}${modelOf(agent) ? ` · ${modelOf(agent)}` : ""}` : "no brain yet"}` }),
    ...(brainReady(brain)
      ? []
      : [
          card("Start here", [
            el("p", { text: `${agent.name} needs a brain. Put a free AI on this phone, or add a free cloud AI key.` }),
            el("div", { class: "row" }, [button("Model control", () => go("models"), { class: "primary" }), button("Settings", () => go("settings"))]),
          ]),
        ]),
    messages,
    el("div", { class: "composer" }, [input, micButton(input, submit), send])
  );
  const draw = async () => {
    const chat = await chatOf(agent.id);
    const nodes = chat.map((turn) =>
      turn.role === "tool"
        ? el("div", { class: "msg tool", text: `⚙ ${turn.text}` })
        : turn.role === "task"
          ? el("div", { class: "msg task", text: `▶ ${turn.text}` })
          : el("div", { class: `msg ${turn.role}` }, [
              turn.role === "assistant" ? el("span", { class: "who", text: agent.name }) : null,
              turn.role === "error" ? el("span", { class: "who", text: "Problem" }) : null,
              turn.text,
            ])
    );
    if (!chat.length) nodes.push(el("p", { class: "muted", text: examples(agent) }));
    if (isBusy(agent)) nodes.push(el("div", { class: "typing", text: `${agent.name} is working…` }));
    messages.replaceChildren(...nodes);
    send.disabled = isBusy(agent);
    send.textContent = isBusy(agent) ? "…" : "Send";
    requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight));
  };
  await draw();
  return onChange((what) => {
    if (what === `chat:${agent.id}` || what === "team") draw();
  });
}

function examples(agent) {
  switch (agent.role) {
    case "builder":
      return 'Try: "Make a one-page site for my dog-walking business with prices and a contact button."';
    case "researcher":
      return 'Try: "Compare the iPhone 12 Pro and iPhone 13 cameras." or "Who invented the transistor?"';
    case "helper":
      return 'Try: "Plan a 4-week running plan, 3 days a week." or "Budget £400 a month for food."';
    case "tester":
      return 'Try: "Check my latest project and fix what\'s wrong."';
    default:
      return `Say hello to ${agent.name}. Try: "What's the weather in London tomorrow?", "Remember my gym days are Monday and Thursday", or "Have Builder make a landing page for my bakery".`;
  }
}

function jobSheet(agent) {
  const goal = el("textarea", { "aria-label": "Job", placeholder: agent.role === "builder" ? "Build a one-page site for…" : "What should it do?" });
  const project = el("input", { "aria-label": "Project", placeholder: "Project name (for building work)", value: state.projects[0] ? state.projects[0].name : "" });
  openSheet(`A job for ${agent.name}`, [
    el("p", { class: "muted", text: `${agent.name} works on it by itself and reports back; watch it on Home under Agents at work.` }),
    el("label", {}, ["The job", goal]),
    ["builder", "tester"].includes(agent.role) ? el("label", {}, ["Project", project]) : null,
    button("Start the job", async () => {
      if (!goal.value.trim()) return notify("Say what the job is.");
      const name = project.value.trim();
      const target = name ? findProject(name) || (await createProject(name, "you")) : null;
      closeSheet();
      notify(`${agent.name} is on it.`);
      runTask(agent, goal.value.trim(), { project: target, by: "you" });
    }, { class: "primary" }),
  ]);
}
