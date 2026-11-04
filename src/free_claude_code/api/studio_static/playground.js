/* FCC Studio Playground: FCC's Manus-like look. One main AI does the job
   with its own hands (on this PC's model when one is set up); up to two
   advisers advise before it starts and check it after, and it fixes what
   they find. Pages: New task (home), Tasks, a task, Files, Minds. Studio
   calls FCCPlayground.render(ctx, page, id); the switch between the HUD and
   the Playground is FCCPlayground.look() / setLook() (kept in this browser). */
(() => {
  "use strict";

  const LOOK_KEY = "fcc-look";
  const POLL_MS = 2500;
  const QUICK = [
    ["⌘", "Build a website", "Build a website for "],
    ["◎", "Research anything", "Research "],
    ["▤", "Write a report", "Write a report about "],
    ["◇", "Make a game", "Make a game where "],
  ];
  const STAGE = { kickoff: "Advice", work: "The work", review: "Check" };
  const MARK = { done: "✓", running: "●", working: "●", failed: "✕", stopped: "■", waiting: "○" };

  function look() {
    try {
      return localStorage.getItem(LOOK_KEY) === "playground" ? "playground" : "hud";
    } catch {
      return "hud";
    }
  }

  function setLook(next) {
    try {
      localStorage.setItem(LOOK_KEY, next === "playground" ? "playground" : "hud");
    } catch {
      /* private mode: the look lasts until the page closes */
    }
  }

  const ago = (ms) => {
    if (!ms) return "";
    const seconds = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
    return new Date(ms).toLocaleDateString();
  };

  async function render(ctx, page, id) {
    const pages = { home, tasks, job, files, minds };
    await (pages[page] || home)(ctx, id);
  }

  // ------------------------------------------------------------ new task

  async function home(ctx) {
    const { el, api, post, notify, go, view, alive } = ctx;
    const [{ agents }, { sites }, { jobs }] = await Promise.all([
      api("/studio/api/agents"),
      api("/studio/api/sites"),
      api("/studio/api/playground"),
    ]);
    if (!alive()) return;
    const team = agents.filter((agent) => !agent.archived && agent.role !== "guide");
    const main = team.find((agent) => agent.role === "main") || team[0];
    const box = el("textarea", { class: "pg-box", rows: "4", "aria-label": "The task", placeholder: `Give ${main ? main.name : "the main AI"} a task to work on…` });
    const hands = el(
      "select",
      { "aria-label": "Who does the work" },
      team.length
        ? team.map((agent) => el("option", { value: agent.id, text: `${agent.name} does it` }))
        : [el("option", { value: "", text: "The main AI does it" })]
    );
    if (main) hands.value = main.id;
    const advisers = el("select", { "aria-label": "Advisers" }, [
      el("option", { value: "auto", text: "2 advisers" }),
      el("option", { value: "meeting", text: "Team meeting" }),
      el("option", { value: "none", text: "No advisers" }),
    ]);
    const project = el("select", { "aria-label": "Project" }, [
      el("option", { value: "", text: "New project (if it makes files)" }),
      ...sites.map((site) => el("option", { value: site.id, text: site.name })),
    ]);
    const start = async () => {
      const goal = box.value.trim();
      if (!goal) return notify("Say what the task is first.");
      try {
        const job = await post("/studio/api/playground", {
          goal,
          hands_id: hands.value,
          advisers: advisers.value,
          site_id: project.value || null,
        });
        notify("On it.");
        go(`pjob/${job.id}`);
      } catch (error) {
        notify(error.message);
      }
    };
    const recent = jobs.slice(0, 4).map((item) => jobRow(ctx, item));
    view.replaceChildren(
      el("div", { class: "pg" }, [
        el("div", { class: "pg-top" }, [
          el("p", { class: "pg-crumb" }, [el("strong", { text: "FCC" }), " / Playground"]),
          el("button", { class: "pg-ghost", type: "button", text: `Chat with ${main ? main.name : "the main AI"}`, onclick: () => go("chats") }),
        ]),
        el("div", { class: "pg-hero" }, [
          el("span", { class: "pg-mark", "aria-hidden": "true", text: "f" }),
          el("h2", { class: "pg-title", text: "What do you want to get done?" }),
          el("p", {
            class: "pg-muted",
            text: `From an idea to a finished result. ${main ? main.name : "The main AI"} does the work with its own hands, on this PC's model; the others only advise.`,
          }),
        ]),
        el("section", { class: "pg-card pg-ask" }, [
          box,
          el("div", { class: "pg-row" }, [hands, advisers, project]),
          el("button", { class: "pg-primary", type: "button", text: "Start task ↗", onclick: start }),
        ]),
        el(
          "div",
          { class: "pg-chips" },
          QUICK.map(([glyph, label, starter]) =>
            el("button", { class: "pg-chip", type: "button", onclick: () => {
              box.value = starter;
              box.focus();
            } }, [el("span", { "aria-hidden": "true", text: glyph }), label])
          )
        ),
        el(
          "div",
          { class: "pg-links" },
          [
            ["Minds", "pminds"],
            ["Files", "pfiles"],
            ["Lab", "lab"],
            ["Ideas", "ideas"],
            ["Team", "agents"],
            ["Local models", "models"],
            ["Connectors", "connectors"],
            ["Settings", "settings"],
          ].map(([label, route]) => el("button", { class: "pg-link", type: "button", text: label, onclick: () => go(route) }))
        ),
        el("div", { class: "pg-head" }, [
          el("h2", { text: "Recent tasks" }),
          el("button", { class: "pg-ghost", type: "button", text: "View all →", onclick: () => go("ptasks") }),
        ]),
        ...(recent.length ? recent : [el("p", { class: "pg-empty", text: "No tasks yet. Your first one shows up here." })]),
      ])
    );
  }

  function jobRow(ctx, item) {
    const { el, go } = ctx;
    return el("button", { class: "pg-item", type: "button", onclick: () => go(`pjob/${item.id}`), "aria-label": `Open the task: ${item.goal}` }, [
      el("span", { class: "pg-glyph", "aria-hidden": "true", text: MARK[item.running ? "working" : item.status] || "○" }),
      el("span", { class: "pg-grow" }, [
        el("strong", { text: item.goal }),
        el("small", { text: `${item.running ? "working" : item.status} · ${item.done_steps}/${item.steps.length} steps · ${ago(item.updated_at)}` }),
      ]),
    ]);
  }

  // ---------------------------------------------------------------- tasks

  async function tasks(ctx) {
    const { el, api, view, alive, go } = ctx;
    const { jobs } = await api("/studio/api/playground");
    if (!alive()) return;
    view.replaceChildren(
      el("div", { class: "pg" }, [
        el("div", { class: "pg-head" }, [
          el("h2", { text: "Your tasks" }),
          el("button", { class: "pg-ghost", type: "button", text: "New task", onclick: () => go("home") }),
        ]),
        ...(jobs.length ? jobs.map((item) => jobRow(ctx, item)) : [el("p", { class: "pg-empty", text: "No tasks yet." })]),
      ])
    );
  }

  async function job(ctx, id) {
    const { el, api, post, view, alive, go, notify } = ctx;
    const [{ agents }] = await Promise.all([api("/studio/api/agents")]);
    const names = Object.fromEntries(agents.map((agent) => [agent.id, agent.name]));
    let timer = null;
    const draw = (item) => {
      const total = item.steps.length;
      const hands = names[item.hands_id] || "The main AI";
      const advising = item.advisers.map((adviser) => names[adviser] || "?");
      const act = async (path, said) => {
        try {
          const next = await post(`/studio/api/playground/${encodeURIComponent(id)}/${path}`, {});
          notify(said);
          draw(next);
          schedule(next);
        } catch (error) {
          notify(error.message);
        }
      };
      view.replaceChildren(
        el("div", { class: "pg" }, [
          el("section", { class: "pg-card" }, [
            el("h2", { text: item.running ? "Working on it" : item.status === "done" ? "Done" : `Task ${item.status}` }),
            el("p", { text: item.goal }),
            el("p", { class: "pg-small", text: `${hands} does the work${advising.length ? ` · advising: ${advising.join(", ")}${item.meeting ? " (team meeting)" : ""}` : ""}` }),
            el("p", { class: "pg-muted pg-small", text: `${item.done_steps} of ${total} steps · updated ${ago(item.updated_at)}` }),
            el("div", { class: "pg-actions" }, [
              item.running ? el("button", { class: "pg-danger", type: "button", text: "Stop", onclick: () => act("stop", "Stopped.") }) : null,
              !item.running && item.status !== "done" ? el("button", { class: "pg-primary", type: "button", text: "Run again", onclick: () => act("resume", "Going again from where it stopped.") }) : null,
              item.site_id ? el("button", { type: "button", text: "Open the project", onclick: () => go(`site/${item.site_id}`) }) : null,
            ]),
          ]),
          el(
            "section",
            { class: "pg-card" },
            [
              el("h2", { text: "Steps" }),
              ...(total
                ? item.steps.map((step) =>
                    el("div", { class: "pg-step" }, [
                      el("span", { class: "pg-glyph", "aria-hidden": "true", text: MARK[step.status] || "○" }),
                      el("span", { class: "pg-grow" }, [
                        el("strong", { text: `${step.agent}: ${step.do}` }),
                        el("small", { text: `${STAGE[step.stage] || step.stage}${step.try_no > 1 ? ` (try ${step.try_no})` : ""} · ${step.status}` }),
                        step.result ? el("p", { class: "pg-result", text: step.result }) : null,
                      ]),
                    ])
                  )
                : [el("p", { class: "pg-muted", text: "Getting started…" })]),
            ]
          ),
          item.summary ? el("section", { class: "pg-card" }, [el("h2", { text: "What the team says" }), el("p", { class: "pg-result", text: item.summary })]) : null,
        ])
      );
    };
    const schedule = (item) => {
      clearTimeout(timer);
      if (item.running) timer = setTimeout(refresh, POLL_MS);
    };
    const refresh = async () => {
      if (!alive()) return;
      try {
        const item = await api(`/studio/api/playground/${encodeURIComponent(id)}`);
        if (!alive()) return;
        draw(item);
        schedule(item);
      } catch (error) {
        if (alive()) view.replaceChildren(el("p", { class: "pg-empty", text: error.message }));
      }
    };
    await refresh();
  }

  // ---------------------------------------------------------------- files

  async function files(ctx) {
    const { el, api, view, alive, go } = ctx;
    const { sites } = await api("/studio/api/sites");
    if (!alive()) return;
    const search = el("input", { type: "search", class: "pg-search", "aria-label": "Search files and projects", placeholder: "Search projects…" });
    const list = el("div", {});
    const draw = () => {
      const query = search.value.trim().toLowerCase();
      const shown = [...sites]
        .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))
        .filter((site) => !query || site.name.toLowerCase().includes(query));
      list.replaceChildren(
        ...(sites.length
          ? shown.length
            ? shown.map((site) =>
                el("button", { class: "pg-item", type: "button", onclick: () => go(`site/${site.id}`), "aria-label": `Open the project ${site.name}` }, [
                  el("span", { class: "pg-glyph", "aria-hidden": "true", text: "▤" }),
                  el("span", { class: "pg-grow" }, [el("strong", { text: site.name }), el("small", { text: `${site.file_count} files · ${ago(site.updated_at)}` })]),
                ])
              )
            : [el("p", { class: "pg-empty", text: "Nothing matches that." })]
          : [
              el("div", { class: "pg-empty" }, [
                el("strong", { text: "Your work, all in one place" }),
                el("p", { class: "pg-muted", text: "Projects the main AI makes appear here. Start a task to build something." }),
              ]),
            ])
      );
    };
    search.addEventListener("input", draw);
    draw();
    view.replaceChildren(el("div", { class: "pg" }, [el("div", { class: "pg-head" }, [el("h2", { text: "Your files" })]), search, list]));
  }

  // ---------------------------------------------------------------- minds

  async function minds(ctx) {
    const { el, api, post, remove, view, alive, notify } = ctx;
    const data = await api("/studio/api/playground/minds");
    if (!alive()) return;
    const input = el("input", { class: "pg-search", "aria-label": "Something you like", placeholder: "Dark, moody colours; big readable buttons…" });
    const row = (entry) =>
      el("div", { class: "pg-step" }, [
        el("span", { class: "pg-grow" }, [el("strong", { text: entry.text }), el("small", { text: ago(entry.at) })]),
        el("button", { class: "pg-ghost", type: "button", text: "✕", "aria-label": `Forget: ${entry.text.slice(0, 40)}`, onclick: async () => {
          await remove(`/studio/api/memory/entry/${encodeURIComponent(entry.id)}`);
          minds(ctx);
        } }),
      ]);
    const sections = [
      ["pattern", "Thinking patterns"],
      ["lesson", "Lessons"],
      ["thought", "Thoughts"],
    ];
    view.replaceChildren(
      el("div", { class: "pg" }, [
        el("section", { class: "pg-card" }, [
          el("h2", { text: "Your taste" }),
          el("p", { class: "pg-muted pg-small", text: "What you like. Every AI in a Playground task reads this and makes things in your image." }),
          el("div", { class: "pg-actions" }, [
            input,
            el("button", { type: "button", text: "Add", onclick: async () => {
              if (!input.value.trim()) return;
              try {
                await post("/studio/api/playground/taste", { text: input.value });
                minds(ctx);
              } catch (error) {
                notify(error.message);
              }
            } }),
          ]),
          ...(data.taste.length ? data.taste.map(row) : [el("p", { class: "pg-empty", text: "Nothing yet." })]),
        ]),
        ...data.minds.map((mind) => {
          const parts = sections.flatMap(([key, label]) => (mind[key].length ? [el("h3", { class: "pg-sub", text: label }), ...mind[key].map(row)] : []));
          return el("section", { class: "pg-card" }, [
            el("h2", { text: `${mind.name}'s mind` }),
            ...(parts.length ? parts : [el("p", { class: "pg-muted pg-small", text: "Nothing yet: it writes here after each Playground task." })]),
          ]);
        }),
      ])
    );
  }

  window.FCCPlayground = { render, look, setLook };
})();
