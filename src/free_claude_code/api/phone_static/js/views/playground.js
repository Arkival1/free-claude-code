// The Playground's own screens (FCC's Manus-like look): New task (its home,
// for games and websites), Files, and Minds (each AI's advice book, lessons,
// patterns and thoughts, and the user's taste). Tasks and More are shared
// with the HUD look; the Library has its own screen.
import { state, onChange, save, changed, jarvis, agentById, MEMORY_KINDS } from "../state.js";
import { el, button, card, notify, go, ago, words } from "../ui.js";
import { brainOf, brainReady, PROVIDERS, modelOf, localModelOf } from "../brains.js";
import { startPlayground, pickAdvisers, pickHelpers, KINDS, kindOf, MAX_ADVISERS } from "../playground.js";
import { remember } from "../tools.js";

const MARK = { done: "✓", working: "●", running: "●", planning: "…", failed: "✕", stopped: "■", waiting: "○" };

/** Where the main AI will think: this phone's model when one is ready (and
 * the user hasn't turned that off), else the brain it would use anyway. */
export function handsBrainLine(hands) {
  if (state.settings.playgroundLocal !== false && brainReady("local")) {
    const model = localModelOf(hands);
    return `thinks on this phone${model ? ` (${model.name})` : ""}`;
  }
  const brain = brainOf(hands);
  if (!brain || !brainReady(brain)) return "has no brain yet";
  return `thinks with ${PROVIDERS[brain].label}${modelOf(hands) ? ` ${modelOf(hands)}` : ""}${brain === "local" ? "" : " (no model on this phone yet)"}`;
}

const names = (ids) => ids.map((id) => (agentById(id) || { name: "?" }).name).join(", ");

export function renderHome(view) {
  let type = "game";
  // Until the user taps Make a website / Make a game, the job's own words
  // decide (a website asked for in words isn't made as a game).
  let picked = false;
  const box = el("textarea", { "aria-label": "The task", rows: 4, placeholder: KINDS.game.placeholder });
  const setType = (key) => {
    type = key;
    box.placeholder = KINDS[key].placeholder;
    for (const node of typeButtons) node.setAttribute("aria-pressed", String(node.dataset.type === type));
  };
  const typeButtons = Object.entries(KINDS).map(([key, kind]) =>
    el("button", { class: "pg-type", type: "button", "aria-pressed": String(key === type), onclick: () => {
      picked = true;
      setType(key);
      drawTeam();
    }, "data-type": key }, [el("span", { class: "pg-type-glyph", "aria-hidden": "true", text: kind.glyph }), `Make a ${kind.label.toLowerCase()}`])
  );
  const hands = el("select", { "aria-label": "Who does the work" }, [
    el("option", { value: jarvis().id, text: `${jarvis().name} does it` }),
    ...state.agents.filter((agent) => agent.id !== jarvis().id).map((agent) => el("option", { value: agent.id, text: `${agent.name} does it` })),
  ]);
  const helpers = el("select", { "aria-label": "Helpers" }, [
    el("option", { value: "1", text: "1 helper" }),
    el("option", { value: "2", text: "2 helpers" }),
    el("option", { value: "0", text: "No helpers" }),
  ]);
  const advisers = el("select", { "aria-label": "Advisers" }, [
    el("option", { value: "auto", text: `${MAX_ADVISERS} advisers` }),
    el("option", { value: "all", text: "Everyone advises" }),
    el("option", { value: "none", text: "No advisers" }),
  ]);
  const project = el("select", { "aria-label": "Project" }, [
    el("option", { value: "", text: "New project" }),
    ...state.projects.map((item) => el("option", { value: item.id, text: item.name })),
  ]);
  const team = el("div", { class: "pg-team" });
  const drawTeam = () => {
    const doer = agentById(hands.value) || jarvis();
    const helping = pickHelpers(type, doer.id, Number(helpers.value));
    const advising = advisers.value === "none" ? [] : pickAdvisers(box.value, doer.id, advisers.value === "all" ? Infinity : MAX_ADVISERS, helping);
    team.replaceChildren(
      el("p", { class: "small" }, [el("strong", { text: `${doer.name} ` }), `builds it · ${handsBrainLine(doer)}`]),
      el("p", { class: "small muted", text: helping.length ? `Helping (they build parts): ${names(helping)}` : "No helpers this time." }),
      el("p", { class: "small muted", text: advising.length ? `Advising: ${names(advising)}${advisers.value === "all" ? " (two talk at a time)" : ""}` : "No advisers this time." })
    );
  };
  for (const input of [hands, helpers, advisers]) input.addEventListener("change", drawTeam);
  box.addEventListener("input", () => {
    if (!picked && box.value.trim()) setType(kindOf(box.value));
    drawTeam();
  });
  // "Ask the AI for one" in the Game Lab starts a 3D game here.
  if (state.labAsk) {
    box.value = state.labAsk;
    state.labAsk = "";
    setType(kindOf(box.value));
    drawTeam();
  }
  drawTeam();

  const start = async () => {
    const goal = box.value.trim();
    if (!goal) return notify(`Say what ${type === "game" ? "game" : "website"} you want first.`);
    if (!picked) setType(kindOf(goal));
    try {
      const task = await startPlayground(goal, { type, hands: hands.value, helpers: Number(helpers.value), advisers: advisers.value, project: project.value });
      box.value = "";
      notify(`${(agentById(task.hands) || jarvis()).name} is on it.`);
      go(`tasks/${task.id}`);
    } catch (error) {
      notify(error.message);
    }
  };

  const recent = el("div", { class: "pg-recent" });
  const drawRecent = () => {
    const rows = state.tasks.slice(0, 4).map((task) =>
      el("button", { class: "item as-button", type: "button", onclick: () => go(`tasks/${task.id}`), "aria-label": `Open the task: ${task.goal}` }, [
        el("span", { class: "glyph", "aria-hidden": "true", text: MARK[task.status] || "○" }),
        el("div", { class: "grow" }, [el("strong", { text: task.goal }), el("small", { text: `${task.type ? `${KINDS[task.type].label} · ` : ""}${task.status} · ${ago(task.updated_at)}` })]),
      ])
    );
    recent.replaceChildren(...(rows.length ? rows : [el("p", { class: "empty", text: "No tasks yet. Your first one shows up here." })]));
  };
  drawRecent();

  const approved = state.library.filter((item) => item.approved).length;
  const waiting = state.library.length - approved;
  const pluginsOn = Object.values(state.settings.plugins || {}).filter((saved) => saved.on).length;
  view.replaceChildren(
    el("div", { class: "pg-top" }, [
      el("p", { class: "pg-crumb" }, [el("strong", { text: "FCC" }), " / Playground"]),
      el("button", { class: "ghost pg-chat", type: "button", text: `Chat with ${jarvis().name}`, onclick: () => go(`chat/${jarvis().id}`) }),
    ]),
    el("div", { class: "pg-hero" }, [
      el("span", { class: "pg-mark", "aria-hidden": "true", text: "f" }),
      el("h2", { class: "pg-title", text: "What do you want to make?" }),
      el("p", { class: "muted", text: `Games and websites, engineered properly. ${jarvis().name} builds it with its own hands; helpers build parts; advisers tell it what to do and which tools to use.` }),
    ]),
    el("div", { class: "pg-types", role: "group", "aria-label": "What to make" }, typeButtons),
    el("section", { class: "card pg-ask" }, [box, el("div", { class: "pg-row" }, [hands, helpers, advisers, project]), team, button("Start task ↗", start, { class: "primary pg-start" })]),
    el("div", { class: "pg-chips" }, [
      el("button", { class: "pg-chip", type: "button", onclick: () => go("library") }, [el("span", { "aria-hidden": "true", text: "▣" }), `Library · ${approved} approved${waiting ? `, ${waiting} waiting` : ""}`]),
      el("button", { class: "pg-chip", type: "button", onclick: () => go("plugins") }, [el("span", { "aria-hidden": "true", text: "⧉" }), state.settings.pluginsOn === false ? "Plugins are off" : `Plugins · ${pluginsOn} on`]),
    ]),
    brainReady("local")
      ? null
      : el("section", { class: "card pg-note" }, [
          el("div", { class: "grow" }, [
            el("strong", { text: `Give ${jarvis().name} a local brain` }),
            el("p", { class: "small muted", text: "The main AI works best on this phone's own model: free, private, offline. Until then it uses your cloud key." }),
          ]),
          button("Set up model", () => go("models")),
        ]),
    el("div", { class: "pg-links" }, [
      ...[
        ["Library", "library"],
        ["Minds", "minds"],
        ["Files", "files"],
        ["Plugins", "plugins"],
        ["Local models", "models"],
        ["Settings", "settings"],
      ].map(([label, route]) => el("button", { class: "pg-link", type: "button", text: label, onclick: () => go(route) })),
    ]),
    el("div", { class: "pg-head" }, [el("h2", { text: "Recent tasks" }), el("button", { class: "ghost", type: "button", text: "View all →", onclick: () => go("tasks") })]),
    recent
  );
  return onChange((what) => {
    if (what === "tasks") drawRecent();
    if (what === "team" || what === "settings" || what === "models") drawTeam();
  });
}

/** Files: every project and its files, with a search box. */
export function renderFiles(view) {
  const search = el("input", { type: "search", "aria-label": "Search files and projects", placeholder: "Search files and projects…" });
  const list = el("div", {});
  const draw = () => {
    const query = search.value.trim().toLowerCase();
    const projects = [...state.projects].sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
    const files = projects.reduce((sum, project) => sum + Object.keys(project.files).length, 0);
    if (!projects.length) {
      list.replaceChildren(
        el("div", { class: "pg-empty" }, [
          el("strong", { text: "Your work, all in one place" }),
          el("p", { class: "small muted", text: "Files the main AI makes appear here. Start a task to build something." }),
          button("New task", () => go("home"), { class: "primary" }),
        ])
      );
      return;
    }
    const rows = [];
    for (const project of projects) {
      const names = Object.keys(project.files);
      const hit = !query || project.name.toLowerCase().includes(query);
      const matching = query ? names.filter((name) => name.toLowerCase().includes(query)) : [];
      if (!hit && !matching.length) continue;
      rows.push(
        el("button", { class: "item as-button", type: "button", onclick: () => go(`projects/${project.id}`), "aria-label": `Open the project ${project.name}` }, [
          el("span", { class: "glyph", "aria-hidden": "true", text: "▤" }),
          el("div", { class: "grow" }, [el("strong", { text: project.name }), el("small", { text: `${names.length} file${names.length === 1 ? "" : "s"} · ${ago(project.updated_at || project.created_at)}` })]),
        ])
      );
      for (const name of matching.slice(0, 8)) {
        rows.push(
          el("button", { class: "item as-button pg-file", type: "button", onclick: () => go(`projects/${project.id}`), "aria-label": `${name} in ${project.name}` }, [
            el("span", { class: "glyph", "aria-hidden": "true", text: "·" }),
            el("div", { class: "grow" }, [el("strong", { text: name }), el("small", { text: project.name })]),
          ])
        );
      }
    }
    list.replaceChildren(
      el("p", { class: "small muted", text: `${files} files in ${projects.length} project${projects.length === 1 ? "" : "s"} · stored on this phone` }),
      ...(rows.length ? rows : [el("p", { class: "empty", text: "Nothing matches that." })])
    );
  };
  search.addEventListener("input", draw);
  draw();
  view.replaceChildren(
    el("div", { class: "pg-head" }, [el("h2", { text: "Your files" }), el("button", { class: "ghost", type: "button", text: "Projects", onclick: () => go("projects") })]),
    search,
    list
  );
  return onChange((what) => what === "projects" && draw());
}

function memoryRow(memory) {
  return el("div", { class: "item" }, [
    el("div", { class: "grow" }, [el("strong", { text: memory.text }), el("small", { text: `${MEMORY_KINDS[memory.kind || "fact"]} · ${ago(memory.created_at)}` })]),
    button(
      "✕",
      async () => {
        state.memories = state.memories.filter((item) => item.id !== memory.id);
        await save.memories();
        changed("memory");
      },
      { class: "ghost", "aria-label": `Forget: ${memory.text.slice(0, 40)}` }
    ),
  ]);
}

const MIND_SECTIONS = ["advice", "lesson", "pattern", "thought"];

/** One AI's mind as a file the user can keep: its advice book, lessons,
 * patterns and thoughts, newest first. */
export function mindFile(agent) {
  const lines = [`# ${agent.name}'s mind`, "", `Saved from FCC Phone on ${new Date().toLocaleString("en-GB")}.`];
  for (const kind of MIND_SECTIONS) {
    const rows = state.memories.filter((memory) => memory.agent_id === agent.id && memory.kind === kind);
    lines.push("", `## ${MEMORY_KINDS[kind]}`, "", ...(rows.length ? rows.map((memory) => `- ${memory.text}`) : ["- (nothing yet)"]));
  }
  return `${lines.join("\n")}\n`;
}

function download(name, text) {
  const link = el("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown" })), download: name });
  document.body.append(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 1000);
}

/** Minds: the user's taste (every AI follows it) and each AI's own mind,
 * with a search bar: the advice book (what other AIs told it), lessons,
 * thinking patterns and thoughts, all short notes. */
export function renderMinds(view) {
  const input = el("input", { "aria-label": "Something you like", placeholder: "Dark, moody colours; big readable buttons…" });
  const search = el("input", { type: "search", "aria-label": "Search the minds", placeholder: "Search advice, lessons, patterns…" });
  const body = el("div", {});
  const draw = () => {
    const wanted = words(search.value);
    const hit = (memory) => !wanted.length || wanted.every((word) => memory.text.toLowerCase().includes(word));
    const taste = state.memories.filter((memory) => memory.kind === "taste" && hit(memory));
    const minds = state.agents.map((agent) => {
      const sections = MIND_SECTIONS.map((kind) => {
        const rows = state.memories.filter((memory) => memory.agent_id === agent.id && memory.kind === kind && hit(memory)).slice(0, wanted.length ? 20 : 5);
        return rows.length ? [el("h3", { class: "pg-sub", text: MEMORY_KINDS[kind] }), ...rows.map(memoryRow)] : [];
      });
      const any = sections.some((rows) => rows.length);
      return card(`${agent.name}'s mind`, [
        ...(any ? sections.flat() : [el("p", { class: "small muted", text: wanted.length ? "Nothing matches." : "Nothing yet: it writes here after each Playground task." })]),
        button("Save as a file", () => download(`${agent.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-mind.md`, mindFile(agent)), { class: "pg-file-button", "aria-label": `Save ${agent.name}'s mind as a file` }),
      ]);
    });
    body.replaceChildren(
      card(MEMORY_KINDS.taste, [
        el("p", { class: "small muted", text: "What you like. Every AI reads this and makes things in your image." }),
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [input]),
          button("Add", async () => {
            if (!input.value.trim()) return;
            await remember(jarvis(), input.value, { kind: "taste" });
            input.value = "";
          }),
        ]),
        ...(taste.length ? taste.map(memoryRow) : [el("p", { class: "empty", text: "Nothing yet." })]),
      ]),
      ...minds
    );
  };
  search.addEventListener("input", draw);
  draw();
  view.replaceChildren(search, body);
  return onChange((what) => what === "memory" && document.activeElement !== input && draw());
}
