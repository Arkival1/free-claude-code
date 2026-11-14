/* FCC Studio — the Changer: an AI that changes FCC itself. It works in a
   copy of FCC's own files (never the running app), checks the copy,
   screenshots it running with no keys and no data, and packs the changes
   into an update zip (with a backup zip to undo it). Studio calls
   FCCChanger.render(ctx). */
(() => {
  "use strict";

  const POLL_MS = 4000;
  const DEFAULT_PAGES = "home, lab, trade, learn";
  let ctx = null;
  let root = null;
  let timer = null;
  let data = null;

  const el = (...args) => ctx.el(...args);
  const withToken = (url) => {
    const key = ctx.token ? ctx.token() : "";
    if (!key) return url;
    return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(key)}`;
  };
  const when = (ms) => (ms ? new Date(ms).toLocaleString() : "");
  const working = () => (data.runs || []).find((run) => ["queued", "running"].includes(run.status));
  const ACTIVE = ["planning", "building"];
  const projectBusy = () => data.project && ACTIVE.includes(data.project.status);
  const projectOpen = () =>
    data.project && !["done", "cancelled", "failed"].includes(data.project.status);
  const STATUS_TEXT = {
    planning: "Planning: the Planner is reading the code",
    choose: "Pick a suggestion",
    awaiting_plan: "Waiting for you to approve the plan",
    building: "Building",
    paused: "Paused",
    awaiting_release: "Ready to release",
    done: "Done",
    cancelled: "Cancelled",
    failed: "Stopped",
  };
  let blockedHits = null;

  async function render(context) {
    ctx = context;
    if (timer) clearTimeout(timer);
    root = el("div", { class: "changer" });
    ctx.view.replaceChildren(root);
    await refresh();
  }

  async function refresh() {
    if (timer) clearTimeout(timer);
    data = await ctx.api("/studio/api/changer");
    if (!ctx.alive()) return;
    paint();
    if (working() || projectBusy()) {
      timer = setTimeout(() => {
        if (ctx.alive()) refresh().catch(() => {});
      }, POLL_MS);
    }
  }

  function card(title, children, extraClass = "") {
    return el("section", { class: `card ${extraClass}`.trim() }, [
      title ? el("h2", { text: title }) : null,
      ...[].concat(children),
    ]);
  }

  // Runs one button's job with the button disabled, then repaints.
  function action(label, run, options = {}) {
    return el("button", {
      class: options.primary ? "primary" : "ghost",
      text: label,
      onclick: async (event) => {
        const button = event.currentTarget;
        if (options.confirm && !window.confirm(options.confirm)) return;
        button.disabled = true;
        const before = button.textContent;
        button.textContent = options.busy || "Working…";
        try {
          await run();
          await refresh();
        } catch (error) {
          ctx.notify(error.message);
        } finally {
          button.disabled = false;
          button.textContent = before;
        }
      },
    });
  }

  function paint() {
    if (!data.ready) {
      root.replaceChildren(
        card("The Changer", [
          el("p", {
            text: "The Changer needs FCC running from its own folder (the fcc folder you unzipped), so it can copy FCC's files. This FCC was installed another way.",
          }),
        ])
      );
      return;
    }
    root.replaceChildren(
      ...[
        introCard(),
        projectOpen() ? projectCard() : askCard(),
        data.project && !projectOpen() ? projectCard() : null,
        notebookCard(),
        changesCard(),
        shotsCard(),
        updatesCard(),
        runsCard(),
      ].filter(
        Boolean
      )
    );
  }

  function introCard() {
    const copy = data.copy;
    return card("The Changer", [
      el("p", {
        text: "Tell it what to change or fix in FCC. It works on a copy of FCC's own files, never the app you're using; it checks its work, takes screenshots, and makes an update zip you install when you want (close FCC, unzip over your fcc folder, start FCC). Every update comes with a backup zip to undo it.",
      }),
      teamModelForm(),
      el("p", { class: "muted" }, [
        `Model: ${data.agent.model} · `,
        el("a", { href: `#agent/${data.agent.id}`, text: "change the Changer's model" }),
        copy
          ? ` · Copy of FCC ${copy.version} (${copy.files} files, made ${when(copy.made_at)})`
          : " · No copy yet (made when you start the first change)",
      ]),
      copy
        ? action("Start over from a fresh copy", () => ctx.post("/studio/api/changer/fresh"), {
            confirm: "Start over? Changes in the copy that aren't in an update zip are lost.",
            busy: "Copying…",
          })
        : null,
    ]);
  }

  // One model for the whole Changer team, e.g. switching from NVIDIA to a
  // FreeLLMAPI router on this PC; the team notebook keeps its memory.
  function teamModelForm() {
    const input = el("input", {
      type: "text",
      value: data.agent.model,
      maxlength: 200,
      "aria-label": "Model for the whole Changer team",
      placeholder: "e.g. freellmapi/auto:coding or nvidia_nim/…",
    });
    return el("div", { class: "changer-note-form" }, [
      el("label", { class: "muted", text: "Model for the whole Changer team (Changer, Planner, Reviewer, Security). Its notebook stays when you switch." }),
      input,
      action("Use for the whole team", async () => {
        const done = await ctx.post("/studio/api/changer/team-model", { model: input.value.trim() });
        ctx.notify(`The Changer team now uses ${done.model}.`);
      }),
    ]);
  }

  // The notebook everyone on the update shares (the Changer, its reviewers,
  // helpers, team agents and Aider): FCC keeps it, so it holds when the
  // model or API changes. The owner can add a note for the whole team.
  function notebookCard() {
    const notes = (data.project && data.project.notebook) || [];
    const lessons = data.lessons || [];
    const input = el("textarea", {
      rows: 2,
      maxlength: 600,
      placeholder: "A note for the whole team, e.g. keep the old button colours",
      "aria-label": "Note for the Changer team",
    });
    const keep = el("input", { type: "checkbox" });
    const noteLine = (note) =>
      el("li", { class: `changer-note ${note.kind}` }, [
        el("span", { class: "pill", text: note.kind }),
        el("strong", { text: ` ${note.author}: ` }),
        el("span", { text: note.text }),
      ]);
    return card("Team notebook", [
      el("p", {
        class: "muted",
        text: "Everyone working on the update reads this before each step and writes what they found, decided and finished, so nothing is done twice and a model switch loses nothing.",
      }),
      notes.length
        ? el("ol", { class: "changer-notebook" }, notes.slice().reverse().map(noteLine))
        : el("p", { class: "muted", text: "No notes yet: they appear as the team works." }),
      el("div", { class: "changer-note-form" }, [
        input,
        el("label", { class: "muted" }, [keep, " Keep as a lesson for later updates"]),
        action("Add note", async () => {
          const text = input.value.trim();
          if (!text) throw new Error("Write the note first.");
          await ctx.post("/studio/api/changer/notes", { text, lesson: keep.checked });
        }),
      ]),
      el("p", { class: "muted" }, [
        "Helper team: eight lean agents from wshobson/agents (debugger, error detective, test automator, security auditor, Python and JavaScript experts, UI designer, search specialist) the Changer can hand parts to. Each gets the Light, Strong or default model its job needs. ",
        action("Add the helper team", async () => {
          const done = await ctx.post("/studio/api/changer/helpers");
          ctx.notify(done.added.length ? `Added: ${done.added.join(", ")}` : "The helper team is already on the team.");
        }, { busy: "Adding…" }),
      ]),
      lessons.length
        ? el("details", {}, [
            el("summary", { text: `Lessons kept for later updates (${lessons.length})` }),
            el(
              "ul",
              { class: "changer-notebook" },
              lessons.map((note) =>
                el("li", { class: "changer-note lesson" }, [
                  el("span", { text: `${note.author}: ${note.text} ` }),
                  action("Forget", () => ctx.api(`/studio/api/changer/lessons/${note.id}`, { method: "DELETE" })),
                ])
              )
            ),
          ])
        : null,
    ]);
  }

  // The update project: plan, milestones, approvals, tasks, checkpoints.
  function projectCard() {
    const project = data.project;
    const plan = project.plan || {};
    const milestones = plan.milestones || [];
    const act = (name, body = {}) => ctx.post(`/studio/api/changer/project/${name}`, body);
    const feedback = el("textarea", {
      rows: "2",
      maxlength: "4000",
      placeholder: "What to change in the plan",
      "aria-label": "Notes for a new plan",
    });
    const buttons = [];
    if (project.status === "awaiting_plan") {
      buttons.push(action("Approve the plan", () => act("approve"), { primary: true, busy: "Starting…" }));
    }
    if (ACTIVE.includes(project.status)) {
      buttons.push(action("Pause", () => act("pause"), { busy: "Pausing…" }));
      const current = [...(project.tasks || [])].reverse().find((task) => ["queued", "running"].includes(task.status));
      if (current) {
        buttons.push(
          el("button", { class: "primary", text: `Watch ${current.agent} work`, onclick: () => ctx.go(`task/${current.run_id}`) })
        );
      }
    }
    if (project.status === "paused") {
      buttons.push(action("Resume", () => act("resume"), { primary: true, busy: "Resuming…" }));
    }
    if (projectOpen() && !ACTIVE.includes(project.status)) {
      buttons.push(action("Cancel the project", () => act("cancel"), { confirm: "Cancel this project? The copy keeps its changes; roll back to undo them." }));
    }
    const replan = ["awaiting_plan", "paused", "choose"].includes(project.status)
      ? el("div", { class: "changer-replan" }, [
          feedback,
          action("Change the plan", () => act("replan", { feedback: feedback.value }), { busy: "Replanning…" }),
        ])
      : null;
    const used = project.tokens || 0;
    return card(`Update project: ${STATUS_TEXT[project.status] || project.status}`, [
      el("p", { class: "changer-goal", text: project.request }),
      project.note ? el("p", { class: "changer-note", text: project.note }) : null,
      el("p", { class: "muted" }, [
        `${project.size || "size not decided yet"}${project.kind ? ` · ${project.kind}` : ""} · about ${used.toLocaleString()} of ${Number(project.budget).toLocaleString()} tokens (estimated)`,
      ]),
      el(
        "p",
        { class: "muted" },
        Object.entries(project.team || {}).map(([name, model]) => `${name}: ${model}`).join(" · ")
      ),
      plan.summary ? el("p", { text: plan.summary }) : null,
      plan.spec
        ? el("details", {}, [el("summary", { text: "Spec" }), el("pre", { class: "changer-spec", text: plan.spec })])
        : null,
      (plan.risks || []).length
        ? el("details", {}, [el("summary", { text: "Risks" }), el("ul", {}, plan.risks.map((risk) => el("li", { text: risk })))])
        : null,
      (project.protected || []).length
        ? el("p", { class: "warn", text: `Touches protected files: ${project.protected.join(", ")}` })
        : null,
      (plan.suggestions || []).length && project.status === "choose"
        ? el(
            "ol",
            { class: "changer-suggestions" },
            plan.suggestions.map((item, index) =>
              el("li", {}, [
                el("strong", { text: item.title }),
                el("p", { class: "muted", text: `${item.why} · value ${item.value} · effort ${item.effort} · risk ${item.risk}` }),
                action("Build this", () => act("choose", { index }), { busy: "Planning…" }),
              ])
            )
          )
        : null,
      milestones.length
        ? el(
            "ol",
            { class: "changer-milestones" },
            milestones.map((item) =>
              el("li", { class: `milestone ${item.status}` }, [
                el("span", { class: `pill ${item.status}`, text: item.status }),
                el("strong", { text: ` ${item.title}` }),
                el("p", { class: "muted", text: item.goal }),
                item.review ? el("p", { class: "muted", text: item.review }) : null,
              ])
            )
          )
        : null,
      el("div", { class: "row wrap" }, buttons),
      replan,
      tasksBlock(project),
      checkpointsBlock(project),
    ]);
  }

  function tasksBlock(project) {
    const tasks = project.tasks || [];
    if (!tasks.length) return null;
    return el("details", { open: ACTIVE.includes(project.status) }, [
      el("summary", { text: `Tasks (${tasks.length})` }),
      el(
        "ul",
        { class: "changer-tasks" },
        tasks.map((task) =>
          el("li", {}, [
            el("button", {
              class: "link",
              text: `${task.agent} · ${task.kind}${task.kind === "plan" ? "" : ` · milestone ${Number(task.milestone) + 1}`}`,
              onclick: () => ctx.go(`task/${task.run_id}`),
            }),
            el("span", { class: `pill ${task.status}`, text: task.status }),
            task.review ? el("span", { class: "muted", text: ` ${task.review.verdict}` }) : null,
          ])
        )
      ),
    ]);
  }

  function checkpointsBlock(project) {
    const points = project.checkpoints || [];
    if (!points.length || ACTIVE.includes(project.status)) return null;
    return el("details", {}, [
      el("summary", { text: `Checkpoints (${points.length})` }),
      el(
        "ul",
        { class: "changer-tasks" },
        points.map((point) =>
          el("li", {}, [
            el("span", { text: `${point.label} · ${when(point.at)}` }),
            action("Roll back to here", () => ctx.post("/studio/api/changer/project/rollback", { checkpoint: point.id }), {
              confirm: `Put the copy back to "${point.label}"?`,
              busy: "Rolling back…",
            }),
          ])
        )
      ),
    ]);
  }

  function askCard() {
    const run = working();
    if (run) {
      return card("Working", [
        el("p", { class: "changer-goal", text: run.goal }),
        el("p", {
          class: "muted",
          text: `${run.status === "queued" ? "Starting" : "Working"}: step ${run.step} of ${run.max_steps}${run.helper ? " (a helper)" : ""}`,
        }),
        el("button", {
          class: "primary",
          text: "Watch it work",
          onclick: () => ctx.go(`task/${run.id}`),
        }),
      ]);
    }
    const box = el("textarea", {
      rows: "4",
      maxlength: "8000",
      placeholder: "e.g. Add a dark/light switch to Settings, or: the Lab's Mix button does nothing on the phone, fix it",
      "aria-label": "What should the Changer change?",
    });
    const budget = el("select", { "aria-label": "Token budget" }, [
      el("option", { value: "0", text: "Budget: normal (decided by size)" }),
      el("option", { value: "5000000", text: "Budget: big project (about 5M tokens)" }),
      el("option", { value: "15000000", text: "Budget: very big project (about 15M tokens)" }),
    ]);
    return card("What should it change?", [
      el("p", {
        class: "muted",
        text: "Small fixes go straight through. Bigger jobs become an update project: the Planner reads the code and makes a plan in milestones for you to approve; then each milestone is built, checked, reviewed by a different agent, screenshotted and saved before the next. Vague requests get up to three suggestions first.",
      }),
      box,
      budget,
      action(
        "Start the change",
        async () => {
          if (!box.value.trim()) throw new Error("Say what to change first.");
          await ctx.post("/studio/api/changer/start", { request: box.value, budget: Number(budget.value) });
          ctx.notify("The Planner is reading the code.");
        },
        { primary: true, busy: "Starting…" }
      ),
    ]);
  }

  function changesCard() {
    const changes = data.changes;
    if (!changes) return null;
    const diffBox = el("pre", { class: "changer-diff", hidden: true });
    const rows = [
      ...changes.changed.map((path) => ["changed", path]),
      ...changes.added.map((path) => ["added", path]),
      ...changes.deleted.map((path) => ["deleted", path]),
    ];
    const list = rows.length
      ? el(
          "ul",
          { class: "changer-files" },
          rows.map(([kind, path]) =>
            el("li", {}, [
              el("span", { class: `pill ${kind}`, text: kind }),
              el("button", {
                class: "link",
                text: path,
                onclick: async () => {
                  try {
                    const shown = await ctx.api(
                      `/studio/api/changer/diff?path=${encodeURIComponent(path)}`
                    );
                    diffBox.textContent = shown.diff || "(no differences)";
                    diffBox.hidden = false;
                  } catch (error) {
                    ctx.notify(error.message);
                  }
                },
              }),
            ])
          )
        )
      : el("p", { class: "muted", text: "Nothing changed in the copy yet." });
    const check = data.check;
    const note = el("input", {
      type: "text",
      maxlength: "4000",
      placeholder: "What changed (for the update's note)",
      "aria-label": "Update note",
    });
    return card("Changes in the copy", [
      list,
      diffBox,
      check
        ? el("div", { class: `changer-check ${check.passed ? "good" : "bad"}` }, [
            el("strong", { text: check.passed ? "Checks passed" : "Checks found problems" }),
            ...check.problems.map((line) => el("pre", { text: line })),
            ...check.lines.map((line) => el("p", { class: "muted", text: line })),
          ])
        : null,
      el("div", { class: "row wrap" }, [
        action("Check", () => ctx.post("/studio/api/changer/check"), { busy: "Checking…" }),
      ]),
      rows.length
        ? el("div", { class: "row wrap" }, [
            note,
            action(
              "Make update zip",
              async () => {
                const made = await ctx.post("/studio/api/changer/package", { note: note.value });
                blockedHits = made.blocked ? made.hits : null;
                if (!made.blocked) ctx.notify(`Packed ${made.name}.`);
              },
              { primary: true, busy: "Scanning and packing…" }
            ),
          ])
        : null,
      blockedHits
        ? el("div", { class: "changer-check bad" }, [
            el("strong", { text: "The security scan flagged these new lines. Read them before packing:" }),
            el("ul", {}, blockedHits.map((hit) => el("li", { text: hit }))),
            action(
              "Pack anyway",
              async () => {
                const made = await ctx.post("/studio/api/changer/package", { note: note.value, confirm: true });
                blockedHits = null;
                ctx.notify(`Packed ${made.name}.`);
              },
              { confirm: "Pack the update with these flagged lines?", busy: "Packing…" }
            ),
          ])
        : null,
    ]);
  }

  function shotsCard() {
    if (!data.copy) return null;
    const pages = el("input", {
      type: "text",
      value: DEFAULT_PAGES,
      "aria-label": "Pages to screenshot",
    });
    const phone = el("input", { type: "checkbox", "aria-label": "Phone size" });
    const stamp = Date.now();
    return card("Screenshots of the changed copy", [
      data.screenshots_ready
        ? el("p", {
            class: "muted",
            text: "Runs the changed copy on a spare port with no keys and empty data, then takes pictures of these pages.",
          })
        : el("p", {
            class: "warn",
            text: "Screenshots need Playwright's browser (run: uv run playwright install chromium).",
          }),
      el("div", { class: "row wrap" }, [
        pages,
        el("span", { class: "changer-phone" }, [phone, " Phone size"]),
        action(
          "Take screenshots",
          () =>
            ctx.post("/studio/api/changer/screenshots", {
              pages: pages.value.split(",").map((page) => page.trim()).filter(Boolean),
              phone: phone.checked,
            }),
          { busy: "Starting the copy…" }
        ),
      ]),
      data.shots_note ? el("p", { class: "warn", text: data.shots_note }) : null,
      data.shots.length
        ? el(
            "div",
            { class: "changer-shots" },
            data.shots.map((name) => {
              const src = withToken(`/studio/api/changer/shots/${encodeURIComponent(name)}?t=${stamp}`);
              return el("a", { href: src, target: "_blank", rel: "noopener" }, [
                el("img", { src, alt: `Screenshot: ${name}`, loading: "lazy" }),
                el("span", { text: name.replace(/\.png$/, "") }),
              ]);
            })
          )
        : null,
    ]);
  }

  function updatesCard() {
    const updates = data.updates || [];
    return card("Update zips", [
      updates.length
        ? el(
            "ul",
            { class: "changer-updates" },
            updates.map((update) =>
              el("li", {}, [
                el("a", {
                  class: "primary-link",
                  href: withToken(`/studio/api/changer/updates/${encodeURIComponent(update.name)}`),
                  download: update.name,
                  text: `⬇ ${update.name}`,
                }),
                el("a", {
                  class: "muted",
                  href: withToken(`/studio/api/changer/updates/${encodeURIComponent(update.backup)}`),
                  download: update.backup,
                  text: "backup (undo)",
                }),
                el("span", { class: "muted", text: when(update.at) }),
              ])
            )
          )
        : el("p", { class: "muted", text: "No update zips yet. The Changer makes one when its checks pass." }),
      el("p", {
        class: "muted",
        text: "To install: close FCC, unzip the update into the folder that holds your fcc folder (choose Replace), start FCC. To undo: unzip the backup the same way.",
      }),
    ]);
  }

  function runsCard() {
    const runs = data.runs || [];
    if (!runs.length) return null;
    return card("Past changes", [
      el(
        "ul",
        { class: "changer-runs" },
        runs.map((run) =>
          el("li", {}, [
            el("button", {
              class: "link",
              text: run.goal.length > 120 ? `${run.goal.slice(0, 120)}…` : run.goal,
              onclick: () => ctx.go(`task/${run.id}`),
            }),
            el("span", { class: `pill ${run.status}`, text: run.status }),
            run.result || run.error
              ? el("p", { class: "muted", text: (run.result || run.error).slice(0, 400) })
              : null,
          ])
        )
      ),
    ]);
  }

  window.FCCChanger = { render };
})();
