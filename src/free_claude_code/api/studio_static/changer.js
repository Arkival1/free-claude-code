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
    if (working()) {
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
      ...[introCard(), askCard(), changesCard(), shotsCard(), updatesCard(), runsCard()].filter(
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
    return card("What should it change?", [
      box,
      action(
        "Start the change",
        async () => {
          if (!box.value.trim()) throw new Error("Say what to change first.");
          await ctx.post("/studio/api/changer/start", { request: box.value });
          ctx.notify("The Changer is on it.");
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
              () => ctx.post("/studio/api/changer/package", { note: note.value }),
              { primary: true, busy: "Packing…" }
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
