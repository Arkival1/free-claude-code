// Home: the Jarvis command center, like the PC's HUD, fitted to the phone.
import { state, chatOf, jarvis, onChange } from "../state.js";
import { el, button, go, notify, meter, ago } from "../ui.js";
import { createCoreOrb } from "../orb.js";
import { brainOf, brainReady, modelOf, PROVIDERS } from "../brains.js";
import { answer, isBusy } from "../agents.js";
import { speak, micButton } from "../voice.js";
import * as engine from "../engine.js";

const GLYPH = { main: "◆", builder: "⚒", researcher: "⌕", helper: "✦", tester: "✓", assistant: "●" };

export function render(view) {
  const main = jarvis();
  const canvas = el("canvas", { class: "orb-canvas", "aria-hidden": "true" });
  const refs = {
    date: el("span", { class: "hud-date" }),
    clock: el("span", { class: "hud-clock" }),
    chips: el("div", { class: "hud-chips" }),
    state: el("p", { class: "hud-state" }),
    log: el("div", { class: "hud-log", "aria-live": "polite" }),
    overview: el("div", { class: "hud-rows" }),
    team: el("div", { class: "hud-team" }),
    learning: el("div", { class: "hud-learning" }),
    feed: el("div", { class: "hud-feed" }),
  };
  const input = el("input", { type: "text", class: "hud-input", placeholder: `Talk to ${main.name}…`, "aria-label": `Message ${main.name}`, enterkeyhint: "send", autocomplete: "off" });
  const send = button("SEND", () => submit(), { class: "hud-send" });

  const submit = async () => {
    const text = input.value.trim();
    if (!text || isBusy(main)) return;
    input.value = "";
    orb.burst();
    try {
      const said = await answer(main, text);
      speak(said);
    } catch (error) {
      notify(error.message);
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  });

  const quick = [
    ["Model control", "Models on this phone", () => go("models")],
    ["Team brains", "Who thinks with what", () => go("agents/brains")],
    ["New project", "Have the Builder make a site", () => go("projects")],
    ["Learn something", "Study a subject", () => go("learn")],
    ["To-dos", "List and reminders", () => go("todos")],
    ["Agent room", "Agents talk together", () => go("rooms")],
    ["Memory", "What they remember", () => go("memory")],
    ["Settings", "Brains, PC, voice", () => go("settings")],
  ].map(([title, sub, onclick]) => el("button", { class: "hud-quick", type: "button", onclick, "aria-label": `${title} ${sub}` }, [el("strong", { text: title }), el("small", { text: sub })]));

  view.replaceChildren(
    el("div", { class: "hud" }, [
      el("header", { class: "hud-top" }, [
        el("div", {}, [el("h1", { class: "hud-title", text: main.name.toUpperCase() }), el("small", { class: "hud-sub", text: "COMMAND CENTER" })]),
        el("div", { class: "hud-when" }, [el("small", { text: "SYSTEM STATUS" }), el("strong", { class: "good", text: "OPTIMAL" }), refs.date, refs.clock]),
      ]),
      refs.chips,
      el("section", { class: "hud-core" }, [canvas, el("strong", { class: "hud-core-name", text: main.name.toUpperCase() }), el("small", { text: "AI CORE" }), refs.state]),
      el("section", { class: "hud-panel hud-talk" }, [refs.log, el("div", { class: "hud-talkbar" }, [input, micButton(input, submit, { label: `Speak to ${main.name}` }), send])]),
      refs.learning,
      el("section", { class: "hud-panel" }, [el("h2", { text: "AI CORE OVERVIEW" }), refs.overview]),
      el("section", { class: "hud-panel" }, [el("h2", { text: "AGENTS AT WORK" }), refs.team]),
      el("section", { class: "hud-panel" }, [el("h2", { text: "QUICK COMMANDS" }), el("div", { class: "hud-quicks" }, quick)]),
      el("section", { class: "hud-panel" }, [el("h2", { text: "LIVE INTELLIGENCE FEED" }), refs.feed]),
    ])
  );

  const orb = createCoreOrb(canvas);
  const tick = () => {
    const now = new Date();
    refs.date.textContent = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }).toUpperCase();
    refs.clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  tick();
  const clock = setInterval(tick, 15000);

  const drawChips = () => {
    const brain = brainOf(main);
    const local = engine.status.loadedId ? engine.modelById(engine.status.loadedId) : null;
    const chips = [
      [`CORE ${brain ? (brain === "local" ? "PHONE" : brain.toUpperCase()) : "NOT SET"}`, brainReady(brain) ? "good" : "warn"],
      [`LOCAL ${local ? local.name.toUpperCase() : state.models.some((m) => m.ready) ? "READY" : "NONE"}`, local ? "good" : ""],
      [`MEM ${state.memories.length}`, ""],
      [`PC ${state.settings.pc ? (state.settings.pc.broken ? "RE-PAIR" : "LINKED") : "OFF"}`, state.settings.pc && !state.settings.pc.broken ? "good" : ""],
      [`VOICE ${state.settings.speak ? "ON" : "OFF"}`, ""],
    ];
    refs.chips.replaceChildren(...chips.map(([text, kind]) => el("span", { class: `hud-chip ${kind}`, text })));
  };

  const drawState = () => {
    const busy = isBusy(main);
    orb.setState(busy ? "thinking" : "idle");
    refs.state.textContent = busy ? "THINKING…" : engine.status.loading ? "LOADING MODEL…" : "STANDING BY";
    send.disabled = busy;
  };

  const drawLog = async () => {
    const chat = (await chatOf(main.id)).filter((turn) => turn.role !== "task").slice(-8);
    if (!chat.length) {
      const brain = brainOf(main);
      refs.log.replaceChildren(
        el("p", { class: "hud-empty", text: brainReady(brain) ? `${main.name} is online. Ask a question, or give the team a job: "Have Builder make a landing page for my bakery."` : `${main.name} needs a brain. Open Model control to put a free AI on this phone, or Settings for a free cloud AI.` }),
        ...(brainReady(brain) ? [] : [el("div", { class: "row" }, [button("Model control", () => go("models"), { class: "primary" }), button("Settings", () => go("settings"))])])
      );
      return;
    }
    refs.log.replaceChildren(
      ...chat.map((turn) =>
        el("div", { class: `hud-line ${turn.role}` }, [
          el("span", { class: "hud-tag", text: turn.role === "user" ? "YOU" : turn.role === "assistant" ? main.name.toUpperCase() : turn.role === "tool" ? "TOOL" : "!" }),
          el("span", { text: turn.text }),
        ])
      )
    );
    refs.log.scrollTop = refs.log.scrollHeight;
  };

  const drawOverview = () => {
    const brain = brainOf(main);
    const working = state.agents.filter((agent) => isBusy(agent)).length;
    const local = engine.status.loadedId ? engine.modelById(engine.status.loadedId) : null;
    const speed = engine.status.lastSpeed;
    const rows = [
      ["AI Core", brain ? `${PROVIDERS[brain].label}${modelOf(main) ? ` · ${modelOf(main)}` : ""}` : "not set"],
      ["On-phone model", local ? `${local.name} (loaded)` : `${state.models.filter((m) => m.ready).length} on this phone`],
      ["Speed", speed ? `${speed.tokensPerSecond.toFixed(1)} tokens/s` : "not measured"],
      ["Memory", `${state.memories.length} stored${state.pcMemories.length ? ` · ${state.pcMemories.length} from PC` : ""}`],
      ["Agents", `${working} running · ${state.agents.length} total`],
      ["PC link", state.settings.pc ? `${state.settings.pc.pcName || "PC"} · synced ${ago(state.settings.pc.lastSync)}` : "not paired"],
    ];
    refs.overview.replaceChildren(...rows.map(([key, value]) => el("div", { class: "hud-row" }, [el("span", { text: key }), el("strong", { text: value })])));
  };

  const drawTeam = () => {
    refs.team.replaceChildren(
      ...state.agents.map((agent) => {
        const job = state.jobs.find((item) => item.agent === agent.id && item.status === "working");
        const busy = isBusy(agent);
        return el("button", { class: `hud-agent${busy ? " busy" : ""}`, type: "button", "aria-label": `${agent.name} ${busy ? "working" : "ready"}`, onclick: () => go(`chat/${agent.id}`) }, [
          el("span", { class: "hud-glyph", "aria-hidden": "true", text: GLYPH[agent.role] || "●" }),
          el("span", { class: "grow" }, [
            el("strong", { text: agent.name }),
            el("small", { text: job ? `${job.goal.slice(0, 60)} · step ${job.steps}` : `${agent.role} · ${PROVIDERS[brainOf(agent)]?.label || "no brain"}` }),
          ]),
          el("span", { class: `hud-dot ${busy ? "busy" : "ready"}`, text: busy ? "WORKING" : "READY" }),
        ]);
      })
    );
  };

  const drawLearning = () => {
    const study = state.studies.find((item) => item.status === "learning");
    refs.learning.hidden = !study;
    if (!study) return;
    refs.learning.replaceChildren(
      el("section", { class: "hud-panel learning" }, [
        el("h2", { text: `LEARNING · ${study.topic.toUpperCase()}` }),
        meter(study.progress),
        el("small", { text: `${Math.round(study.progress * 100)}% · ${study.step}` }),
      ])
    );
  };

  const drawFeed = () => {
    refs.feed.replaceChildren(
      ...(state.feed.length
        ? state.feed.slice(0, 14).map((item) =>
            el("div", { class: `hud-event ${item.kind}` }, [el("small", { text: `${new Date(item.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${item.agent}` }), el("span", { text: item.text })])
          )
        : [el("p", { class: "hud-empty", text: "No jobs yet. What the team does shows up here." })])
    );
  };

  const drawAll = () => {
    drawChips();
    drawState();
    drawLog();
    drawOverview();
    drawTeam();
    drawLearning();
    drawFeed();
  };
  drawAll();
  const off = onChange((what) => {
    if (what === `chat:${main.id}`) drawLog();
    if (what === "team") {
      drawState();
      drawTeam();
      drawOverview();
    }
    if (what === "feed") drawFeed();
    if (what === "learn") drawLearning();
    if (["engine", "models", "pc", "memory", "settings"].includes(what)) {
      drawChips();
      drawOverview();
      drawState();
    }
  });
  return () => {
    off();
    clearInterval(clock);
    orb.destroy();
  };
}
