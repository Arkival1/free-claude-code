/* FCC Studio bug scanner: scan FCC for things that are broken, once or
   endlessly, a different way each round; read what it found and send the
   bad ones to the Changer. The scanner only reads (GET routes, pages in a
   hidden browser, the log, the records, FCC's own files). Studio calls
   FCCScanner.render(ctx). */
(() => {
  "use strict";

  const POLL_MS = 3000;
  const INTERVALS = [
    [60, "every minute"],
    [300, "every 5 minutes"],
    [600, "every 10 minutes"],
    [1800, "every 30 minutes"],
    [3600, "every hour"],
  ];
  const SEVERITY = { high: "Bad", medium: "Check", low: "Small" };

  let ctx = null;
  let root = null;
  let timer = 0;
  let open = new Set();

  const el = (...args) => ctx.el(...args);
  const when = (ms) => (ms ? new Date(ms).toLocaleString() : "never");

  async function render(context) {
    ctx = context;
    root = el("div", { class: "scanner" });
    ctx.view.replaceChildren(root);
    await refresh();
  }

  async function refresh() {
    clearTimeout(timer);
    const data = await ctx.api("/studio/api/scanner");
    if (!ctx.alive()) return;
    paint(data);
    if (data.running) {
      timer = setTimeout(() => {
        if (ctx.alive()) refresh().catch(() => {});
      }, POLL_MS);
    }
  }

  function act(work) {
    return async () => {
      try {
        await work();
        await refresh();
      } catch (error) {
        ctx.notify(error.message);
      }
    };
  }

  function paint(data) {
    const keepModes = new Set(
      [...root.querySelectorAll("input[name=scan-mode]:checked")].map((box) => box.value)
    );
    const first = !root.childElementCount;
    const modes = data.modes.map((mode) =>
      el("label", { class: "scan-mode" }, [
        el("input", {
          type: "checkbox",
          name: "scan-mode",
          value: mode.id,
          checked: first || keepModes.has(mode.id),
        }),
        el("span", {}, [el("strong", { text: mode.id.replace("_", " ") }), el("small", { text: mode.about })]),
      ])
    );
    const interval = el(
      "select",
      { id: "scan-interval", "aria-label": "How often" },
      INTERVALS.map(([seconds, label]) =>
        el("option", { value: String(seconds), text: label, selected: seconds === data.interval_s })
      )
    );
    const chosen = () =>
      [...root.querySelectorAll("input[name=scan-mode]:checked")].map((box) => box.value);
    const start = (endless) =>
      act(() =>
        ctx.post("/studio/api/scanner/start", {
          modes: chosen(),
          endless,
          interval_s: Number(interval.value),
        })
      );
    const controls = data.running
      ? [
          el("span", { class: "scan-live", text: data.endless ? "Scanning endlessly" : "Scanning" }),
          el("button", { class: "secondary", text: "Stop", onclick: act(() => ctx.post("/studio/api/scanner/stop")) }),
        ]
      : [
          el("button", { class: "primary", text: "Scan once", onclick: start(false) }),
          el("button", { class: "secondary", text: "Scan endlessly", onclick: start(true) }),
          interval,
        ];
    root.replaceChildren(
      el("section", { class: "card scan-head" }, [
        el("div", { class: "row-between" }, [
          el("div", {}, [
            el("h2", { text: "Bug scanner" }),
            el("p", {
              class: "muted",
              text: "Looks for things in FCC that are broken or not working, a different way each round. It only reads: it never changes your data. Content Farm is left out.",
            }),
          ]),
          el("div", { class: "scan-count" }, [
            el("strong", { text: String(data.new) }),
            el("span", { text: data.new === 1 ? "new problem" : "new problems" }),
          ]),
        ]),
        el("div", { class: "scan-modes" }, modes),
        el("div", { class: "row" }, controls),
        el("p", { class: "muted", text: `${data.message || "Not scanned yet."} Last round: ${when(data.last_round_at)}. Rounds: ${data.rounds}.` }),
      ]),
      el("section", { class: "card" }, [
        el("h3", { text: "What it found" }),
        data.findings.length
          ? el("div", { class: "scan-list" }, data.findings.map(finding))
          : el("p", { class: "muted", text: "Nothing found yet. Scan endlessly and it keeps looking in new ways." }),
        data.closed
          ? el("p", { class: "muted", text: `${data.closed} dismissed or fixed, hidden.` })
          : null,
      ]),
      data.history.length
        ? el("section", { class: "card" }, [
            el("h3", { text: "Recent rounds" }),
            el(
              "ul",
              { class: "scan-history" },
              data.history.map((round) =>
                el("li", { text: `${when(round.at)}: ${round.mode.replace("_", " ")}, ${round.found} problems (${round.new} new), ${round.seconds} s` })
              )
            ),
          ])
        : null
    );
  }

  function finding(item) {
    const expanded = open.has(item.id);
    const mark = (status) => act(() => ctx.post(`/studio/api/scanner/findings/${item.id}`, { status }));
    return el("article", { class: `scan-item ${item.severity} ${item.status}` }, [
      el("button", {
        class: "scan-summary",
        "aria-expanded": String(expanded),
        onclick: () => {
          if (expanded) open.delete(item.id);
          else open.add(item.id);
          refresh().catch(() => {});
        },
      }, [
        el("span", { class: `pill scan-${item.severity}`, text: SEVERITY[item.severity] || item.severity }),
        el("span", { class: "grow" }, [
          el("strong", { text: item.title }),
          el("small", { text: `${item.place} · ${item.mode.replace("_", " ")} · found ${item.count}× · last ${when(item.last_seen)}` }),
        ]),
        item.status === "new" ? el("span", { class: "pill good", text: "New" }) : null,
        item.status === "sent" ? el("span", { class: "pill", text: "With the Changer" }) : null,
      ]),
      expanded ? el("pre", { class: "scan-detail", text: item.detail }) : null,
      expanded
        ? el("div", { class: "row" }, [
            el("button", {
              class: "primary",
              text: "Send to the Changer",
              disabled: item.status === "sent",
              onclick: act(async () => {
                await ctx.post(`/studio/api/scanner/findings/${item.id}/changer`);
                ctx.notify("Sent to the Changer. It plans the fix in its copy first.");
              }),
            }),
            el("button", { class: "secondary", text: "Seen", onclick: mark("seen") }),
            el("button", { class: "secondary", text: "Fixed", onclick: mark("fixed") }),
            el("button", { class: "secondary", text: "Not a problem", onclick: mark("dismissed") }),
          ])
        : null,
    ]);
  }

  window.FCCScanner = { render };
})();
