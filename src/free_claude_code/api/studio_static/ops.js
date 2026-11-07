/* FCC Studio Ops: what the PC is doing right now. CPU, memory and graphics
   card load; the background worker lanes (web, data, local and server
   models, CPU jobs) with what's running and waiting; which agents are busy;
   the local model queue; and the trading desk. A 3D system pulse (ops3d.js)
   loads when WebGL is there; the panels below always work. It reads one
   light summary every few seconds, and nothing while the page is hidden.
   Studio calls FCCOps.render(ctx). */
(() => {
  "use strict";

  const POLL_MS = 2500;
  const LANES = {
    web: ["Web", "Searches and page reads"],
    data: ["Data", "Market prices and other look-ups"],
    model_local: ["Local model", "One turn at a time on the graphics card"],
    model_server: ["Server models", "NVIDIA NIM and other server models"],
    cpu: ["CPU jobs", "Heavier sums, one at a time"],
  };
  const BASE = document.currentScript ? new URL(".", document.currentScript.src).href : "";

  let ctx = null;
  let root = null;
  let timer = null;
  let loading3d = null;
  let last = null;

  const el = (...args) => ctx.el(...args);
  const fill = (node, ...children) => node.replaceChildren(...children.flat().filter((child) => child != null && child !== false));
  const percent = (value) => (typeof value === "number" ? `${Math.round(value)}%` : "—");
  const tone = (value) => (typeof value !== "number" ? "" : value > 85 ? "hot" : value > 65 ? "warm" : "cool");

  function stop() {
    clearInterval(timer);
    timer = null;
    window.FCCOps3D?.stop?.();
  }

  function stillHere() {
    if (ctx && ctx.alive()) return true;
    stop();
    return false;
  }

  async function render(context) {
    ctx = context;
    stop();
    root = el("div", { class: "ops" });
    ctx.view.replaceChildren(root);
    const data = await ctx.api("/studio/api/ops");
    if (!ctx.alive()) return;
    fill(
      root,
      el("section", { class: "card ops-pulse-card" }, [
        el("div", { class: "row-between" }, [el("h2", { text: "System pulse" }), el("span", { class: "muted", id: "ops-caption" })]),
        el("div", { class: "ops-pulse", id: "ops-pulse" }, [el("div", { class: "ops-flat", id: "ops-flat" })]),
      ]),
      el("div", { class: "ops-grid" }, [
        el("section", { class: "card", id: "ops-machine" }),
        el("section", { class: "card", id: "ops-lanes" }),
        el("section", { class: "card", id: "ops-jobs" }),
        el("section", { class: "card", id: "ops-team" }),
      ])
    );
    paint(data);
    timer = setInterval(async () => {
      if (!stillHere() || document.hidden) return;
      try {
        paint(await ctx.api("/studio/api/ops"));
      } catch {
        /* the next read tries again */
      }
    }, POLL_MS);
  }

  function paint(data) {
    last = data;
    machineCard(data);
    lanesCard(data.workers);
    jobsCard(data);
    teamCard(data);
    pulse(data);
  }

  /* ------------------------------------------------------------ 3D, or the flat view */

  function pulse(data) {
    const host = root.querySelector("#ops-pulse");
    const caption = root.querySelector("#ops-caption");
    const running = data.workers.running.length;
    const waiting = data.workers.lanes.reduce((sum, lane) => sum + lane.waiting, 0);
    if (caption) caption.textContent = `${running} running · ${waiting} waiting${data.low_power ? " · low-power mode" : ""}`;
    if (host && window.FCCOps3D?.show(host, data)) return;
    load3d();
    flat(data);
  }

  function load3d() {
    if (window.FCCOps3D || loading3d || !BASE) return;
    loading3d = import(`${BASE}ops3d.js`)
      .then(() => {
        if (last && stillHere()) pulse(last);
      })
      .catch(() => {
        loading3d = "unavailable"; // the flat view stays
      });
  }

  function flat(data) {
    const box = root.querySelector("#ops-flat");
    if (!box) return;
    const machine = data.machine;
    const bars = [
      ["CPU", machine.cpu],
      ["Memory", machine.memory],
      ...(machine.gpus || []).map((card, index) => [`GPU${machine.gpus.length > 1 ? ` ${index + 1}` : ""}`, card.load]),
      ...(machine.gpus || []).map((card, index) => [`VRAM${machine.gpus.length > 1 ? ` ${index + 1}` : ""}`, card.memory]),
    ];
    fill(
      box,
      el(
        "div",
        { class: "ops-bars" },
        bars.map(([label, value]) =>
          el("div", { class: `ops-bar ${tone(value)}` }, [
            el("i", { style: `height:${typeof value === "number" ? Math.max(2, Math.min(100, value)) : 2}%` }),
            el("strong", { text: percent(value) }),
            el("small", { text: label }),
          ])
        )
      ),
      el(
        "div",
        { class: "ops-dots" },
        data.agents.map((agent) => el("span", { class: `ops-dot${agent.busy ? " busy" : ""}`, title: `${agent.name}${agent.busy ? " (working)" : ""}`, text: agent.name.slice(0, 1) }))
      )
    );
  }

  /* ------------------------------------------------------------ panels */

  function meter(value) {
    return el("div", { class: `ops-meter ${tone(value)}` }, [el("i", { style: `width:${typeof value === "number" ? Math.max(0, Math.min(100, value)) : 0}%` })]);
  }

  function machineCard(data) {
    const box = root.querySelector("#ops-machine");
    if (!box) return;
    const machine = data.machine;
    const cards = machine.gpus || [];
    fill(
      box,
      el("h2", { text: "This PC" }),
      el("div", { class: "ops-reading" }, [el("span", { text: `CPU (${machine.cores} cores)` }), el("strong", { text: percent(machine.cpu) })]),
      meter(machine.cpu),
      el("div", { class: "ops-reading" }, [el("span", { text: `Memory${machine.memory_gb ? ` (${machine.memory_gb} GB)` : ""}` }), el("strong", { text: percent(machine.memory) })]),
      meter(machine.memory),
      ...cards.flatMap((card) => [
        el("div", { class: "ops-reading" }, [el("span", { text: card.name }), el("strong", { text: `${percent(card.load)}${card.temperature != null ? ` · ${Math.round(card.temperature)}°C` : ""}` })]),
        meter(card.load),
        el("div", { class: "ops-reading" }, [el("span", { text: "Graphics memory" }), el("strong", { text: card.memory_gb ? `${card.memory_used_gb} of ${card.memory_gb} GB` : "—" })]),
        meter(card.memory),
      ]),
      cards.length ? null : el("p", { class: "muted", text: "No NVIDIA card reading (nvidia-smi isn't on this PC)." }),
      el("div", { class: "ops-reading" }, [el("span", { text: `Disk${machine.disk_gb ? ` (${machine.disk_gb} GB)` : ""}` }), el("strong", { text: percent(machine.disk) })]),
      meter(machine.disk)
    );
  }

  function lanesCard(workers) {
    const box = root.querySelector("#ops-lanes");
    if (!box) return;
    fill(
      box,
      el("h2", { text: "Background lanes" }),
      el("p", {
        class: "muted",
        text: workers.low_power
          ? "Low-power mode: half the lanes, and quiet jobs wait while the PC is busy."
          : `Quiet jobs wait while the CPU is above ${Math.round(workers.busy_percent)}%${workers.quiet_waits ? ` (they waited ${workers.quiet_waits} times so far)` : ""}.`,
      }),
      ...workers.lanes.map((lane) => {
        const [name, help] = LANES[lane.name] || [lane.name, ""];
        return el("div", { class: "ops-lane" }, [
          el("div", { class: "ops-reading" }, [
            el("span", { text: name, title: help }),
            el("strong", { text: `${lane.running}/${lane.limit} running${lane.waiting ? ` · ${lane.waiting} waiting` : ""}` }),
          ]),
          el(
            "div",
            { class: "ops-slots" },
            Array.from({ length: lane.limit }, (_, index) => el("i", { class: index < lane.running ? "on" : "" }))
          ),
          el("small", { class: "muted", text: `${lane.done} done${lane.failed ? ` · ${lane.failed} failed` : ""}${lane.avg_ms ? ` · about ${(lane.avg_ms / 1000).toFixed(1)} s each` : ""}` }),
        ]);
      })
    );
  }

  function jobsCard(data) {
    const box = root.querySelector("#ops-jobs");
    if (!box) return;
    const running = data.workers.running;
    const recent = data.workers.recent.slice(-8).reverse();
    fill(
      box,
      el("h2", { text: "Running now" }),
      running.length
        ? el(
            "ul",
            { class: "ops-list" },
            running.map((job) => el("li", {}, [el("span", { class: "pulse-dot" }), el("strong", { text: job.label || job.lane }), el("small", { class: "muted", text: ` ${LANES[job.lane]?.[0] || job.lane} · ${Math.round(job.seconds)} s` })]))
          )
        : el("p", { class: "empty", text: "Nothing running in the background." }),
      recent.length ? el("h3", { text: "Just finished" }) : null,
      recent.length
        ? el(
            "ul",
            { class: "ops-list" },
            recent.map((job) => el("li", { class: job.ok === false ? "bad" : "" }, [el("strong", { text: job.label || job.lane }), el("small", { class: "muted", text: ` ${LANES[job.lane]?.[0] || job.lane}${job.ms != null ? ` · ${(job.ms / 1000).toFixed(1)} s` : ""}${job.ok === false ? " · failed" : ""}` })]))
          )
        : null
    );
  }

  function teamCard(data) {
    const box = root.querySelector("#ops-team");
    if (!box) return;
    const busy = data.agents.filter((agent) => agent.busy);
    const desk = data.trading || {};
    fill(
      box,
      el("h2", { text: "Agents and models" }),
      el(
        "div",
        { class: "ops-agents" },
        data.agents.map((agent) =>
          el("button", { class: `ops-agent${agent.busy ? " busy" : ""}`, type: "button", onclick: () => ctx.go(`agent/${agent.id}`) }, [el("strong", { text: agent.name }), el("small", { text: agent.busy ? "working" : agent.role || "idle" })])
        )
      ),
      el("p", { class: "muted", text: busy.length ? `${busy.length} agent${busy.length > 1 ? "s" : ""} working.` : "Every agent is idle." }),
      el("h3", { text: "Local model queue" }),
      el("p", {
        text: data.turns.working.length
          ? `Thinking: ${data.turns.working.join(", ")}${data.turns.waiting.length ? ` · waiting: ${data.turns.waiting.join(", ")}` : ""}`
          : "The graphics card is free.",
      }),
      el("h3", { text: "Trading desk" }),
      el("p", {
        text: `${desk.running ? "Running" : "Stopped"} · ${String(desk.mode || "paper").replace("_", " ")}${desk.activity?.stage ? ` · ${desk.activity.symbol || ""} ${desk.activity.stage}` : desk.busy ? " · working" : ""}`,
      }),
      el("button", { class: "secondary", type: "button", text: "Open the Trading Bank", onclick: () => ctx.go("trade") })
    );
  }

  window.FCCOps = { render };
})();
