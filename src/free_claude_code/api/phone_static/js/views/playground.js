// The Playground's own screens (FCC's Manus-like look): New task (its home),
// Files, and Minds (what each AI keeps in its own mind, and the user's taste).
// Tasks and More are shared with the HUD look.
import { state, onChange, save, changed, jarvis, agentById, MEMORY_KINDS } from "../state.js";
import { el, button, card, notify, go, ago } from "../ui.js";
import { brainOf, brainReady, PROVIDERS, modelOf, localModelOf } from "../brains.js";
import { startPlayground, pickAdvisers, MAX_ADVISERS, MAX_MEETING } from "../playground.js";
import { remember } from "../tools.js";

const QUICK = [
  ["⌘", "Build a website", "Build a website for "],
  ["◎", "Research anything", "Research "],
  ["▤", "Write a report", "Write a report about "],
  ["◇", "Make a game", "Make a game where "],
];
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

function adviserLine(agent) {
  const brain = brainOf(agent);
  return `${agent.name} · ${brain && brainReady(brain) ? PROVIDERS[brain].label : "no brain yet"}`;
}

export function renderHome(view) {
  const box = el("textarea", { "aria-label": "The task", rows: 4, placeholder: `Give ${jarvis().name} a task to work on…` });
  const hands = el("select", { "aria-label": "Who does the work" }, [
    el("option", { value: jarvis().id, text: `${jarvis().name} does it` }),
    ...state.agents.filter((agent) => agent.id !== jarvis().id).map((agent) => el("option", { value: agent.id, text: `${agent.name} does it` })),
  ]);
  const advisers = el("select", { "aria-label": "Advisers" }, [
    el("option", { value: "auto", text: `${MAX_ADVISERS} advisers` }),
    el("option", { value: "meeting", text: "Team meeting" }),
    el("option", { value: "none", text: "No advisers" }),
  ]);
  const project = el("select", { "aria-label": "Project" }, [
    el("option", { value: "", text: "New project (if it makes files)" }),
    ...state.projects.map((item) => el("option", { value: item.id, text: item.name })),
  ]);
  const team = el("div", { class: "pg-team" });
  const drawTeam = () => {
    const doer = agentById(hands.value) || jarvis();
    const picked = advisers.value === "none" ? [] : pickAdvisers(box.value, doer.id, advisers.value === "meeting" ? MAX_MEETING : MAX_ADVISERS);
    team.replaceChildren(
      el("p", { class: "small" }, [el("strong", { text: `${doer.name} ` }), `does the work · ${handsBrainLine(doer)}`]),
      picked.length
        ? el("p", { class: "small muted", text: `Advising: ${picked.map((id) => adviserLine(agentById(id))).join(", ")}${advisers.value === "meeting" ? ` (a team meeting: up to ${MAX_MEETING}, two at a time)` : ""}` })
        : el("p", { class: "small muted", text: "No advisers this time." })
    );
  };
  for (const input of [hands, advisers]) input.addEventListener("change", drawTeam);
  box.addEventListener("input", drawTeam);
  drawTeam();

  const start = async () => {
    const goal = box.value.trim();
    if (!goal) return notify("Say what the task is first.");
    try {
      const task = await startPlayground(goal, { hands: hands.value, advisers: advisers.value, project: project.value });
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
        el("div", { class: "grow" }, [el("strong", { text: task.goal }), el("small", { text: `${task.status} · ${ago(task.updated_at)}` })]),
      ])
    );
    recent.replaceChildren(...(rows.length ? rows : [el("p", { class: "empty", text: "No tasks yet. Your first one shows up here." })]));
  };
  drawRecent();

  view.replaceChildren(
    el("div", { class: "pg-top" }, [
      el("p", { class: "pg-crumb" }, [el("strong", { text: "FCC" }), " / Playground"]),
      el("button", { class: "ghost pg-chat", type: "button", text: `Chat with ${jarvis().name}`, onclick: () => go(`chat/${jarvis().id}`) }),
    ]),
    el("div", { class: "pg-hero" }, [
      el("span", { class: "pg-mark", "aria-hidden": "true", text: "f" }),
      el("h2", { class: "pg-title", text: "What do you want to get done?" }),
      el("p", { class: "muted", text: `From an idea to a finished result. ${jarvis().name} does the work with its own hands; the others only advise.` }),
    ]),
    el("section", { class: "card pg-ask" }, [
      box,
      el("div", { class: "pg-row" }, [hands, advisers, project]),
      team,
      button("Start task ↗", start, { class: "primary pg-start" }),
    ]),
    el(
      "div",
      { class: "pg-chips" },
      QUICK.map(([glyph, label, starter]) =>
        el("button", { class: "pg-chip", type: "button", onclick: () => {
          box.value = starter;
          box.focus();
          drawTeam();
        } }, [el("span", { "aria-hidden": "true", text: glyph }), label])
      )
    ),
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
        ["Minds", "minds"],
        ["Files", "files"],
        ["Skills & plugins", "plugins"],
        ["Team brains", "agents/brains"],
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
    el("div", { class: "grow" }, [el("strong", { text: memory.text }), el("small", { text: ago(memory.created_at) })]),
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

/** Minds: the user's taste (every AI follows it) and each AI's own mind. */
export function renderMinds(view) {
  const input = el("input", { "aria-label": "Something you like", placeholder: "Dark, moody colours; big readable buttons…" });
  const draw = () => {
    const taste = state.memories.filter((memory) => memory.kind === "taste");
    const minds = state.agents.map((agent) => {
      const own = (kind) => state.memories.filter((memory) => memory.agent_id === agent.id && memory.kind === kind);
      const sections = ["pattern", "lesson", "thought"].map((kind) => {
        const rows = own(kind).slice(0, 5);
        return rows.length ? [el("h3", { class: "pg-sub", text: MEMORY_KINDS[kind] }), ...rows.map(memoryRow)] : [];
      });
      const any = sections.some((rows) => rows.length);
      return card(`${agent.name}'s mind`, any ? sections.flat() : [el("p", { class: "small muted", text: "Nothing yet: it writes here after each Playground task." })]);
    });
    view.replaceChildren(
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
  draw();
  return onChange((what) => what === "memory" && document.activeElement !== input && draw());
}
