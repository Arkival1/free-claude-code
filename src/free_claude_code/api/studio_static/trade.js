/* FCC Studio Trading Bank — five model seats research, debate, and decide;
   a risk assessment period, hard limits, and an account check guard every
   order; the desk trades on paper or on the owner's platform.

   Tabs: Desk (the seats, waiting orders, holdings, the engine's health),
   Debate (the live feed, round by round), Risk (the latest risk
   assessment), Orders (orders, rounds, decision records, the audit trail),
   Debriefs (leaderboard, learning, backtests, debriefs), and Setup (mode,
   markets, seats, limits, platforms). The feed is read a few
   lines at a time and only while the page is visible. Studio calls
   FCCTrade.render(ctx). */
(() => {
  "use strict";

  const SEATS = {
    0: { name: "Desk", short: "Desk", colour: "#7fa9ba" },
    1: { name: "Technical Analyst", short: "Chart", colour: "#40d6ff" },
    2: { name: "Researcher", short: "News", colour: "#c792ff" },
    3: { name: "Macro & Sentiment", short: "Macro", colour: "#4dffa6" },
    4: { name: "Risk Guardian", short: "Guardian", colour: "#ff5d6c" },
    5: { name: "Portfolio Manager", short: "PM", colour: "#ffc861" },
  };
  const TABS = [
    ["desk", "Desk", "◆"],
    ["debate", "Debate", "⇄"],
    ["risk", "Risk", "⛨"],
    ["orders", "Orders", "≡"],
    ["debriefs", "Debriefs", "✎"],
    ["setup", "Setup", "⚙"],
  ];
  const TAB_KEY = "fcc.trade.tab";
  const FEED_MS = 2000;
  const STATUS_MS = 5000;
  const MAX_EVENTS = 600;
  const POSITIONS_MS = 30000;
  const ENGINE_MS = 30000;
  const SEAT_NAMES = { 1: "Technical Analyst", 2: "Researcher", 3: "Macro & Sentiment", 4: "Risk Guardian", 5: "Portfolio Manager" };
  const STANCE_COLOURS = { buy: "#4dffa6", hold: "#ffb547", sell: "#ff5d6c", avoid: "#ff5d6c" };
  const MODES = [
    ["paper", "Practice", "Fake money on real live prices; the desk trades on its own."],
    ["alert_only", "Alert only", "The desk analyses and alerts you, but never places an order."],
    ["live_approve", "Live: I approve", "Real orders wait for your Approve (PC or phone), after a fresh account check."],
    ["live_auto", "Live: automatic", "Real orders go through on their own, still inside every hard limit."],
  ];
  const DEPTHS = [
    ["fast", "Fast", "Shorter answers, 1 rebuttal round, 1 web search between rounds, no closing statements. Fewest model calls."],
    ["balanced", "Balanced", "Cross-examination, up to 2 rebuttal rounds, closing statements, 3 web searches and 1 page read between rounds."],
    ["max", "Max", "Longest answers, each opening asked 3 times and averaged, up to 4 rebuttal rounds, 2 page reads between rounds. Best with server models."],
  ];
  const MARKETS = [
    ["asx", "ASX shares"],
    ["us", "US shares"],
    ["crypto", "Crypto"],
    ["meme", "Meme coins"],
  ];

  const state = {
    tab: readTab(),
    after: 0,
    events: [],
    status: null,
    config: null,
    brokers: null,
    models: null,
    orders: null,
    debriefs: null,
    stats: null,
    rounds: null,
    summary: null,
    filter: "",
    shown: {},
    positions: null,
    positionsError: "",
    positionsAt: 0,
    engine: null,
    engineError: "",
    engineAt: 0,
  };
  // What each desk box last showed, so a poll redraws only what changed (and
  // an opened account check stays open).
  const painted = new WeakMap();

  // The 3D arena (trade3d.js, with three.js) loads only when the desk is
  // shown, from the same folder as this script.
  const BASE = document.currentScript ? new URL(".", document.currentScript.src).href : "";
  let arenaLoading = null;

  let ctx = null;
  let root = null;
  let feedTimer = null;
  let statusTimer = null;
  let clockTimer = null;

  function readTab() {
    try {
      const saved = localStorage.getItem(TAB_KEY);
      return TABS.some(([id]) => id === saved) ? saved : "desk";
    } catch {
      return "desk";
    }
  }

  function saveTab(tab) {
    try {
      localStorage.setItem(TAB_KEY, tab);
    } catch {
      /* private mode: the tab just isn't remembered */
    }
  }

  const el = (...args) => ctx.el(...args);
  const money = (value, currency) =>
    value == null || Number.isNaN(Number(value))
      ? "—"
      : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}${currency ? ` ${currency}` : ""}`;
  const pct = (value, digits = 1) =>
    value == null || Number.isNaN(Number(value)) ? "—" : `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(digits)}%`;
  const chance = (value) => (value == null ? "—" : `${Math.round(Number(value) * 100)}%`);
  const num = (value) =>
    value == null ? "—" : Number(value).toLocaleString(undefined, { maximumSignificantDigits: 8 });
  const ago = (ms) => {
    if (!ms) return "";
    const seconds = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    return new Date(ms).toLocaleString();
  };
  const seat = (number) => SEATS[number] || SEATS[0];
  const fill = (node, ...children) => node.replaceChildren(...children.flat().filter((child) => child != null && child !== false));

  /* ------------------------------------------------------------ polling */

  function stopTimers() {
    clearInterval(feedTimer);
    clearInterval(statusTimer);
    clearInterval(clockTimer);
    feedTimer = statusTimer = clockTimer = null;
    window.FCCTradeArena?.stop?.();
  }

  function stillHere() {
    if (ctx && ctx.alive()) return true;
    stopTimers();
    return false;
  }

  function startTimers() {
    feedTimer = setInterval(() => {
      if (!stillHere() || document.hidden) return;
      pullFeed().catch(() => {});
    }, FEED_MS);
    statusTimer = setInterval(() => {
      if (!stillHere() || document.hidden) return;
      pullStatus().catch(() => {});
    }, STATUS_MS);
    clockTimer = setInterval(() => {
      if (!stillHere() || document.hidden) return;
      for (const node of root.querySelectorAll("[data-due]")) {
        const left = Math.max(0, Math.round((Number(node.dataset.due) - Date.now()) / 1000));
        node.textContent = left > 0 ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "now";
      }
    }, 1000);
  }

  async function pullFeed() {
    const data = await ctx.api(`/studio/api/trading/feed?after=${state.after}`);
    if (!data.events.length) {
      paintActivity(data.pulse);
      return;
    }
    state.after = data.last;
    state.events = state.events.concat(data.events).slice(-MAX_EVENTS);
    paintActivity(data.pulse);
    if (state.tab === "debate") appendEvents(data.events);
    else if (state.tab === "desk") paintArena();
    else if (state.tab === "risk" && data.events.some((e) => e.kind.startsWith("risk"))) drawPanel();
    window.FCCTradeArena?.feed?.(data.events);
  }

  async function pullStatus() {
    state.status = await ctx.api("/studio/api/trading");
    paintStrip();
    if (state.tab === "desk") paintDesk();
  }

  /* ------------------------------------------------------------ page */

  async function render(context) {
    ctx = context;
    stopTimers();
    root = el("div", { class: "trade" });
    ctx.view.replaceChildren(root);
    const [status, config, feed] = await Promise.all([
      ctx.api("/studio/api/trading"),
      ctx.api("/studio/api/trading/config"),
      ctx.api("/studio/api/trading/feed?after=0"),
    ]);
    if (!ctx.alive()) return;
    state.status = status;
    state.config = config;
    state.events = feed.events;
    state.after = feed.last;
    root.replaceChildren(
      el("div", { class: "trade-strip", id: "trade-strip" }),
      el("div", { class: "trade-activity", id: "trade-activity" }),
      tabsBar(),
      el("div", { class: "trade-panel", id: "trade-panel" })
    );
    paintStrip();
    paintActivity(feed.pulse);
    await drawPanel();
    startTimers();
  }

  function tabsBar() {
    return el(
      "nav",
      { class: "trade-tabs", role: "tablist" },
      TABS.map(([id, label, glyph]) =>
        el(
          "button",
          {
            class: `trade-tab${state.tab === id ? " on" : ""}`,
            role: "tab",
            "aria-selected": state.tab === id ? "true" : "false",
            onclick: async () => {
              state.tab = id;
              saveTab(id);
              root.querySelectorAll(".trade-tab").forEach((node, index) => {
                const on = TABS[index][0] === id;
                node.classList.toggle("on", on);
                node.setAttribute("aria-selected", on ? "true" : "false");
              });
              await drawPanel();
            },
          },
          [el("span", { class: "glyph", text: glyph }), el("span", { text: label })]
        )
      )
    );
  }

  async function drawPanel() {
    const panel = root.querySelector("#trade-panel");
    if (!panel) return;
    window.FCCTradeArena?.stop?.();
    panel.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      const builders = { desk: deskPanel, debate: debatePanel, risk: riskPanel, orders: ordersPanel, debriefs: debriefsPanel, setup: setupPanel };
      const nodes = await builders[state.tab]();
      if (!ctx.alive()) return;
      fill(panel, nodes);
      if (state.tab === "debate") {
        appendEvents(state.events);
        scrollFeed(true);
      }
      if (state.tab === "desk") paintDesk();
    } catch (error) {
      panel.replaceChildren(el("p", { class: "trade-error", text: error.message }));
    }
  }

  /* ------------------------------------------------------------ the strip */

  function paintStrip() {
    const strip = root.querySelector("#trade-strip");
    const status = state.status;
    if (!strip || !status) return;
    const account = status.account || {};
    const live = !!status.live;
    const startStop = el("button", {
      class: status.running ? "secondary" : "primary",
      text: status.running ? "Stop" : "Start",
      onclick: async () => {
        try {
          state.status = await ctx.post(`/studio/api/trading/${status.running ? "stop" : "start"}`, {});
          paintStrip();
        } catch (error) {
          ctx.notify(error.message);
        }
      },
    });
    const kill = el("button", {
      class: "danger",
      text: "Kill switch",
      title: "Stop the desk and cancel every waiting order",
      onclick: () => killSwitch(),
    });
    fill(
      strip,
      el("div", { class: `mode-badge ${status.mode}` }, [
        el("strong", { text: live ? (status.mode === "live_auto" ? "LIVE · AUTO" : "LIVE · APPROVE") : status.alert_only ? "ALERT ONLY" : "PRACTICE" }),
        el("span", { text: status.broker_name }),
      ]),
      status.mode === "live_auto"
        ? el("div", { class: "trade-error wide live-warning", role: "alert" }, [
            el("strong", { text: "Real money, automatic. " }),
            el("span", { text: "Orders go through on their own, inside every hard limit. Press the kill switch to stop everything at once." }),
          ])
        : null,
      stat("Equity", account.error ? "—" : money(account.equity_base, status.currency)),
      stat("Today", account.error ? "—" : pct(account.day_change_pct, 2), toneOf(account.day_change_pct)),
      stat("Invested", account.error ? "—" : money(account.invested, status.currency)),
      stat("Trades today", account.error ? "—" : String(account.trades_today ?? 0)),
      el("div", { class: "strip-actions" }, [startStop, kill]),
      status.kill
        ? el("div", { class: "trade-error wide" }, [
            el("strong", { text: "Kill switch is on. " }),
            el("span", { text: `Since ${new Date(status.kill.at * 1000).toLocaleString()}: ${status.kill.reason || "pressed"}. Nothing new trades until you release it. ` }),
            el("button", { class: "secondary", text: "Release kill switch", onclick: () => protection("kill/release", "Kill switch released. Press Start when ready.") }),
          ])
        : null,
      status.breaker
        ? el("div", { class: "trade-error wide" }, [
            el("strong", { text: "Circuit breaker: new trades paused. " }),
            el("span", { text: `${status.breaker.reason}. Open positions are still managed; it clears by itself after ${new Date(status.breaker.until * 1000).toLocaleTimeString()} once the cause is gone. ` }),
            el("button", {
              class: "secondary",
              text: "Reset now",
              onclick: () => {
                // Orders FCC couldn't match are the owner's to check first.
                if (
                  status.breaker.kind === "reconciliation" &&
                  !window.confirm("Have you checked the account? Orders FCC couldn't match will be marked unconfirmed (not open), and FCC won't track them.")
                )
                  return;
                protection("breaker/reset", "Circuit breaker reset.");
              },
            }),
          ])
        : null,
      !status.breaker && status.unmatched?.length
        ? el("p", { class: "trade-error wide", text: `New trades paused: FCC couldn't match ${status.unmatched.join("; ")}. It asks the account again every few minutes.` })
        : null,
      account.error ? el("p", { class: "trade-error wide", text: `Account: ${account.error}` }) : null,
      status.running && status.next_scan_in != null
        ? el("p", { class: "muted wide", text: `${status.next_scan_in > 0 ? `Next scan in ${Math.ceil(status.next_scan_in / 60)} min` : "Scanning"} · ${sessionsLine(status.sessions)}` })
        : el("p", { class: "muted wide", text: `${status.running ? "Running" : "Stopped"} · ${sessionsLine(status.sessions)}` })
    );
  }

  function sessionsLine(sessions) {
    if (!sessions) return "";
    return ["asx", "us"]
      .map((market) => {
        const s = sessions[market];
        if (!s) return "";
        return `${market.toUpperCase()} ${s.open ? "open" : "closed"} (${s.local})`;
      })
      .filter(Boolean)
      .concat(["crypto 24/7"])
      .join(" · ");
  }

  function toneOf(value) {
    if (value == null) return "";
    return Number(value) >= 0 ? "good" : "bad";
  }

  function stat(label, value, tone = "") {
    return el("div", { class: `trade-stat ${tone}` }, [el("small", { text: label }), el("strong", { text: value })]);
  }

  async function killSwitch() {
    if (!window.confirm("Kill switch: stop the desk on every account and cancel every waiting order? It stays on until you release it.")) return;
    // The second step: closing every position needs the typed phrase.
    const phrase = window.prompt("Also close EVERY position at market? Type CLOSE EVERYTHING to sell all, or leave empty to keep holdings.", "") || "";
    const flatten = phrase.trim() === "CLOSE EVERYTHING";
    try {
      state.status = await ctx.post("/studio/api/trading/kill", { flatten, confirm: phrase.trim(), reason: "pressed on the PC" });
      paintStrip();
      ctx.notify(flatten ? "Stopped, orders cancelled, holdings being sold." : "Stopped and orders cancelled; holdings kept and still watched.");
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  async function protection(path, done) {
    try {
      state.status = await ctx.post(`/studio/api/trading/${path}`, {});
      paintStrip();
      ctx.notify(done);
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  function paintActivity(pulse) {
    const line = root?.querySelector("#trade-activity");
    if (!line) return;
    const activity = (pulse && pulse.activity) || state.status?.activity || {};
    if (!activity.stage) {
      fill(
        line,
        el("span", { class: "muted", text: pulse?.busy ? "Working…" : "Idle. Ask the desk about a symbol, or Start it." }),
        askBox()
      );
      return;
    }
    const who = seat(activity.seat);
    fill(
      line,
      el("span", { class: "pulse-dot" }),
      el("strong", { text: activity.symbol || "Desk" }),
      el("span", { text: ` · ${activity.stage}` }),
      activity.seat ? el("span", { style: `color:${who.colour}`, text: ` · ${who.name} thinking` }) : null,
      askBox()
    );
  }

  function askBox() {
    const input = el("input", { type: "text", placeholder: "Ask about… e.g. BHP.AX, NVDA, BTC", "aria-label": "Symbol to debate", maxlength: "60" });
    const form = el("form", { class: "ask-box" }, [input, el("button", { class: "secondary", type: "submit", text: "Debate" })]);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const symbol = input.value.trim();
      if (!symbol) return;
      try {
        const queued = await ctx.post("/studio/api/trading/debate", { symbol });
        ctx.notify(`Debating ${queued.queued}; watch the Debate tab.`);
        input.value = "";
      } catch (error) {
        ctx.notify(error.message);
      }
    });
    return form;
  }

  /* ------------------------------------------------------------ desk */

  function latestRound() {
    for (let index = state.events.length - 1; index >= 0; index -= 1) {
      const event = state.events[index];
      if (event.round_id) return event.round_id;
    }
    return "";
  }

  function arenaState() {
    const round = latestRound();
    const seats = {};
    let symbol = "";
    let stage = "";
    let decision = null;
    for (const event of state.events) {
      if (event.round_id !== round) continue;
      symbol = event.symbol || symbol;
      stage = event.stage || stage;
      const forecast = event.data?.forecast || event.data?.premortem || event.data?.reply;
      if (forecast && event.seat) seats[event.seat] = { ...forecast, kind: event.kind };
      if (event.kind === "decision") decision = event.data?.decision || null;
    }
    const weights = {};
    for (const s of state.status?.seats || []) weights[s.seat] = s.record?.weight ?? 1;
    return { round, symbol, stage, seats, decision, weights, activity: state.status?.activity || {} };
  }

  async function deskPanel() {
    const arena = el("div", { class: "arena-host", id: "trade-arena" }, [el("div", { class: "arena-ring", id: "arena-ring" })]);
    return [
      el("section", { class: "card arena-card" }, [
        el("div", { class: "arena-head" }, [el("h2", { text: "The desk" }), el("span", { class: "muted", id: "arena-caption" })]),
        arena,
      ]),
      el("div", { class: "desk-live" }, [
        el("div", { id: "desk-orders" }),
        el("div", { id: "desk-seats" }),
        el("div", { id: "positions-host" }, [el("p", { class: "muted", text: "Loading holdings…" })]),
        el("div", { id: "desk-engine" }),
      ]),
    ];
  }

  async function refreshEngine() {
    state.engineAt = Date.now();
    try {
      state.engine = await ctx.api("/studio/api/trading/health");
      state.engineError = "";
    } catch (error) {
      state.engineError = error.message;
    }
    if (stillHere()) repaint("#desk-engine", [state.engine, state.engineError], () => engineCard());
  }

  function engineCard() {
    if (state.engineError) return el("section", { class: "card" }, [el("h2", { text: "Engine" }), el("p", { class: "trade-error", text: state.engineError })]);
    const health = state.engine;
    if (!health) return el("p", { class: "muted", text: "Reading the engine…" });
    const metrics = health.metrics || {};
    const steps = Object.entries(health.steps || {})
      .filter(([, step]) => step.failures)
      .sort((a, b) => b[1].failures - a[1].failures)
      .slice(0, 3);
    const sources = Object.entries(health.data_sources || {}).filter(([, value]) => value && value !== "ok");
    const loop = !health.looping ? "stopped" : health.stalled ? "stalled" : "running";
    return el("section", { class: "card engine-card" }, [
      el("h2", { text: "Engine" }),
      el("div", { class: "risk-stats" }, [
        stat("Loop", loop, loop === "running" ? "good" : "bad"),
        stat("Last pass", health.heartbeat_age_s == null ? "—" : `${Math.round(health.heartbeat_age_s)} s ago`),
        stat("Cycle (median)", metrics.cycle_seconds_median == null ? "—" : `${Math.round(metrics.cycle_seconds_median)} s`),
        stat("Fill rate", metrics.fill_rate_pct == null ? "—" : `${metrics.fill_rate_pct}%`),
        stat("Refused", metrics.reject_rate_pct == null ? "—" : `${metrics.reject_rate_pct}%`),
        stat("Slippage (avg)", metrics.slippage_pct_average == null ? "—" : `${metrics.slippage_pct_average}%`),
        stat("Fees", metrics.fees_total == null ? "—" : money(metrics.fees_total)),
      ]),
      health.lease ? el("p", { class: "trade-error", text: `Another FCC holds the desk (${health.lease}); this one waits.` }) : null,
      (health.unmatched || []).length ? el("p", { class: "trade-error", text: `Not matched with the account yet: ${health.unmatched.join("; ")}` }) : null,
      (health.retries || []).length ? el("p", { class: "muted", text: `${health.retries.length} background job(s) waiting to be tried again.` }) : null,
      (health.dead_letters || []).length ? el("p", { class: "trade-error", text: `${health.dead_letters.length} background job(s) failed every try and were set aside (see the audit trail).` }) : null,
      sources.length ? el("p", { class: "muted", text: `Data sources: ${sources.map(([name, value]) => `${name} ${value}`).join("; ")}` }) : null,
      steps.length
        ? el("ul", { class: "round-list" }, steps.map(([name, step]) => el("li", {}, [el("strong", { text: name }), ` failed ${step.failures} of ${step.runs}: `, el("span", { class: "muted", text: step.last_error })])))
        : el("p", { class: "muted", text: "Every step of the loop is running cleanly." }),
    ]);
  }

  function paintDesk() {
    const status = state.status || {};
    const waiting = (status.orders || []).filter((order) => ["awaiting_approval", "cooling", "submitting", "submitted"].includes(order.status));
    // seconds_left changes every poll; the countdown ticks on its own.
    repaint("#desk-orders", waiting.map(({ seconds_left, ...order }) => order), () => waitingCard(waiting));
    repaint("#desk-seats", status.seats || [], () => seatCards(status));
    if (Date.now() - state.positionsAt > POSITIONS_MS) refreshPositions();
    else paintPositions();
    if (Date.now() - state.engineAt > ENGINE_MS) refreshEngine();
    else repaint("#desk-engine", [state.engine, state.engineError], () => engineCard());
    paintArena();
  }

  function repaint(selector, value, draw) {
    const host = root.querySelector(selector);
    if (!host) return;
    const key = JSON.stringify(value);
    if (painted.get(host) === key) return;
    painted.set(host, key);
    host.replaceChildren(draw());
  }

  function paintArena() {
    const caption = root.querySelector("#arena-caption");
    const snapshot = arenaState();
    if (caption) caption.textContent = snapshot.symbol ? `${snapshot.symbol} · ${snapshot.stage || ""}` : "Waiting for a debate";
    const host = root.querySelector("#trade-arena");
    if (host && window.FCCTradeArena?.show(host, { ...snapshot, lowPower: Boolean(state.status?.low_power) })) return;
    loadArena();
    const ring = root.querySelector("#arena-ring");
    if (!ring) return;
    const speaking = Number(snapshot.activity.seat || 0);
    ring.replaceChildren(
      ...[1, 2, 3, 4, 5].map((number) => {
        const view = snapshot.seats[number];
        const s = seat(number);
        const stance = (snapshot.decision && number === 5 ? snapshot.decision.action : view?.stance) || "";
        return el(
          "div",
          {
            class: `ring-seat seat-${number}${speaking === number ? " speaking" : ""}`,
            style: `--seat:${s.colour};--stance:${STANCE_COLOURS[stance] || "#30495a"}`,
          },
          [
            el("strong", { text: s.short }),
            el("span", { text: stance ? `${stance} · ${chance(view?.p_up ?? snapshot.decision?.p_up)}` : "—" }),
            el("small", { text: `weight ×${Number(snapshot.weights[number] ?? 1).toFixed(2)}` }),
          ]
        );
      })
    );
  }

  function loadArena() {
    if (window.FCCTradeArena || arenaLoading || !BASE) return;
    arenaLoading = import(`${BASE}trade3d.js`)
      .then(() => {
        if (state.tab === "desk" && stillHere()) paintArena();
      })
      .catch(() => {
        arenaLoading = "unavailable"; // the 2D ring stays
      });
  }

  function waitingCard(waiting) {
    return el("section", { class: "card" }, [
      el("h2", { text: "Waiting orders" }),
      waiting.length
        ? el("div", { class: "order-list" }, waiting.map(orderCard))
        : el("p", { class: "empty", text: "Nothing waiting. Orders pass a cooling-off wait and an account check, then trade (paper or auto) or wait here for your Approve (live)." }),
    ]);
  }

  // Holdings need live prices, so they're asked for every 30 seconds at most.
  async function refreshPositions() {
    state.positionsAt = Date.now();
    try {
      state.positions = (await ctx.api("/studio/api/trading/positions")).positions;
      state.positionsError = "";
    } catch (error) {
      state.positionsError = error.message;
    }
    if (stillHere()) paintPositions();
  }

  function paintPositions() {
    if (state.positions === null && !state.positionsError) return;
    repaint("#positions-host", [state.positions, state.positionsError], () =>
      state.positionsError ? el("p", { class: "trade-error", text: state.positionsError }) : positionsCard(state.positions || [])
    );
  }

  function positionsCard(positions) {
    if (!positions.length) return el("section", { class: "card" }, [el("h2", { text: "Holdings" }), el("p", { class: "empty", text: "Nothing held yet." })]);
    return el("section", { class: "card" }, [
      el("h2", { text: "Holdings" }),
      el("div", { class: "table-wrap" }, [
        el("table", { class: "trade-table" }, [
          el("thead", {}, [el("tr", {}, ["Symbol", "Qty", "Avg", "Now", "Change", "Stop", "Target"].map((h) => el("th", { text: h })))]),
          el(
            "tbody",
            {},
            positions.map((p) =>
              el("tr", {}, [
                el("td", { text: p.symbol }),
                el("td", { text: num(p.qty) }),
                el("td", { text: num(p.avg_price) }),
                el("td", { text: num(p.price) }),
                el("td", { class: toneOf(p.change_pct), text: pct(p.change_pct, 2) }),
                el("td", { text: num(p.stop_loss) }),
                el("td", { text: num(p.take_profit) }),
              ])
            )
          ),
        ]),
      ]),
    ]);
  }

  function orderCard(order) {
    const assessment = order.data?.assessment || {};
    const check = order.data?.check;
    const due = order.due_at ? Number(order.due_at) : null;
    const actions =
      order.status === "awaiting_approval"
        ? el("div", { class: "row" }, [
            el("button", {
              class: "primary",
              text: "Approve",
              onclick: async (event) => {
                event.target.disabled = true;
                try {
                  const result = await ctx.post(`/studio/api/trading/orders/${order.id}/approve`, {});
                  ctx.notify(`Order ${result.status.replace(/_/g, " ")}.`);
                  await pullStatus();
                } catch (error) {
                  ctx.notify(error.message);
                  event.target.disabled = false;
                }
              },
            }),
            el("button", {
              class: "secondary",
              text: "Deny",
              onclick: async () => {
                try {
                  await ctx.post(`/studio/api/trading/orders/${order.id}/deny`, {});
                  await pullStatus();
                } catch (error) {
                  ctx.notify(error.message);
                }
              },
            }),
          ])
        : null;
    return el("article", { class: `order-card ${order.status}` }, [
      el("header", {}, [
        el("strong", { text: `${order.side.toUpperCase()} ${num(order.qty)} ${order.symbol}` }),
        el("span", { class: "pill warn", text: order.status.replace(/_/g, " ") }),
        due ? el("span", { class: "countdown", "data-due": String(due), text: "" }) : null,
      ]),
      el("p", {
        class: "muted",
        text: `${order.order_type} near ${num(order.entry_price)} ${order.currency} · stop ${num(order.stop_loss)} · target ${num(order.take_profit)} · ${order.broker}`,
      }),
      assessment.grade
        ? el("p", {
            text: `Risk grade ${assessment.grade} · ${money(assessment.at_risk)} at risk (${Number(assessment.at_risk_pct || 0).toFixed(2)}% of equity) · reward ${Number(assessment.reward_risk || 0).toFixed(2)} to 1 · EV ${money(assessment.ev)}`,
          })
        : null,
      order.reason ? el("p", { class: "muted", text: order.reason }) : null,
      check ? checkList(check) : null,
      actions,
    ]);
  }

  function checkList(check) {
    return el("details", { class: "check-list" }, [
      el("summary", { text: `Account check: ${check.passed ? "passed" : "failed"} (${check.items.length} checks)` }),
      el(
        "ul",
        {},
        check.items.map((item) => el("li", { class: item.ok ? "good" : item.blocking ? "bad" : "warn" }, [el("strong", { text: `${item.ok ? "✓" : "✕"} ${item.name}: ` }), item.detail]))
      ),
      check.account?.number ? el("p", { class: "muted", text: `Account ${check.account.number} · ${check.account.currency} · equity ${money(check.account.equity)}` }) : null,
    ]);
  }

  function seatCards(status) {
    const seats = status.seats || [];
    return el("section", { class: "card" }, [
      el("h2", { text: "The five seats" }),
      el(
        "div",
        { class: "seat-grid" },
        seats.map((s) => {
          const record = s.record || {};
          return el("article", { class: "seat-card", style: `--seat:${seat(s.seat).colour}` }, [
            el("header", {}, [el("strong", { text: s.name }), s.on ? null : el("span", { class: "pill bad", text: "off" })]),
            el("p", { class: "muted", text: s.model || "Studio's server model" }),
            el("p", { text: record.scored ? `${record.scored} scored · right ${chance(record.hit_rate)} · skill ${Number(record.skill ?? 0).toFixed(2)} · ×${Number(record.weight ?? 1).toFixed(2)}` : "No scored forecasts yet (weight ×1)." }),
            record.buckets?.length ? calibration(record.buckets) : null,
          ]);
        })
      ),
      el("p", { class: "muted", text: "Vote weights come from each seat's scored forecasts (×0.5 to ×2 after 20). Change models in Setup." }),
    ]);
  }

  function calibration(buckets) {
    return el(
      "div",
      { class: "calibration", title: "Said vs happened, by confidence" },
      buckets.map((b) =>
        el("span", { class: "cal-bar", title: `said ${chance(b.said)}, happened ${chance(b.happened)} (${b.count})` }, [
          el("i", { class: "said", style: `height:${Math.round(b.said * 100)}%` }),
          el("i", { class: "happened", style: `height:${Math.round(b.happened * 100)}%` }),
        ])
      )
    );
  }

  /* ------------------------------------------------------------ debate */

  async function debatePanel() {
    const symbols = [...new Set(state.events.map((e) => e.symbol).filter(Boolean))];
    const filter = el(
      "select",
      { "aria-label": "Show one symbol" },
      [el("option", { value: "", text: "All symbols" }), ...symbols.map((s) => el("option", { value: s, text: s }))]
    );
    filter.value = state.filter;
    filter.addEventListener("change", () => {
      state.filter = filter.value;
      const feed = root.querySelector("#trade-feed");
      feed.replaceChildren(feedEmpty());
      state.shown = {};
      appendEvents(state.events);
      scrollFeed(true);
    });
    const download = el("button", {
      class: "secondary",
      text: "Download the log",
      onclick: () => downloadLog(),
    });
    const feed = el("div", { class: "trade-feed", id: "trade-feed", "aria-live": "polite" }, [feedEmpty()]);
    state.shown = {};
    return [el("div", { class: "row feed-tools" }, [filter, download]), feed];
  }

  function feedEmpty() {
    return el("p", { class: "empty feed-empty", text: "No debate lines yet. Ask the desk about a symbol above, or Start it." });
  }

  function scrollFeed(force) {
    const feed = root.querySelector("#trade-feed");
    if (!feed) return;
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
    if (force || nearBottom) feed.scrollTop = feed.scrollHeight;
  }

  function appendEvents(events) {
    const feed = root.querySelector("#trade-feed");
    if (!feed) return;
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
    for (const event of events) {
      if (state.filter && event.symbol !== state.filter) continue;
      if (state.shown[event.seq]) continue;
      state.shown[event.seq] = true;
      feed.querySelector(".feed-empty")?.remove();
      let block = feed.querySelector(`[data-round="${CSS.escape(event.round_id || "desk")}"]`);
      if (!block) {
        block = el("section", { class: "round-block", "data-round": event.round_id || "desk" }, [
          el("header", {}, [el("strong", { text: event.round_id ? event.symbol || "Round" : "Desk" }), el("span", { class: "muted", text: ago(event.at) })]),
        ]);
        feed.append(block);
      }
      if (event.stage && block.dataset.stage !== event.stage) {
        block.dataset.stage = event.stage;
        block.append(el("div", { class: "stage-label", text: event.stage }));
      }
      block.append(bubble(event));
    }
    while (feed.children.length > 40) feed.firstElementChild.remove();
    if (atBottom) feed.scrollTop = feed.scrollHeight;
  }

  function bubble(event) {
    const who = seat(event.seat);
    const lines = String(event.text || "").split("\n");
    return el("article", { class: `seat-bubble kind-${event.kind}`, style: `--seat:${who.colour}` }, [
      el("header", {}, [el("strong", { text: who.name }), el("span", { class: "muted", text: event.kind.replace(/_/g, " ") })]),
      ...lines.map((line) => el("p", { text: line })),
    ]);
  }

  async function downloadLog() {
    const round = latestRound();
    let payload = { events: state.events };
    if (round) {
      try {
        payload = await ctx.api(`/studio/api/trading/rounds/${round}`);
      } catch {
        /* the feed we have is better than nothing */
      }
    }
    saveFile(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }), `fcc-debate-${round || "feed"}.json`);
  }

  // The CSV comes with Studio's token in a header, never in the address.
  async function downloadCsv() {
    let key = "";
    try {
      key = localStorage.getItem("fcc.studio.token") || "";
    } catch {
      /* no saved token: the server may not need one */
    }
    try {
      const response = await fetch("/studio/api/trading/export.csv", { headers: key ? { "x-api-key": key } : {} });
      if (!response.ok) throw new Error(`The CSV didn't download (${response.status}).`);
      saveFile(await response.blob(), "fcc-trades.csv");
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  function saveFile(blob, name) {
    const link = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(link);
    link.click();
    setTimeout(() => {
      URL.revokeObjectURL(link.href);
      link.remove();
    }, 1000);
  }

  /* ------------------------------------------------------------ risk */

  async function riskPanel() {
    let latest = null;
    for (let index = state.events.length - 1; index >= 0; index -= 1) {
      const event = state.events[index];
      if (event.kind === "risk_report" || (event.kind === "risk_gate" && event.data?.assessment)) {
        latest = event;
        break;
      }
    }
    if (!latest) {
      return el("section", { class: "card" }, [
        el("h2", { text: "Risk assessment period" }),
        el("p", { class: "empty", text: "No buy has reached the risk period yet. Every buy gets a risk report, stress tests, an event check, a five-seat risk round with an A–F grade, a size review (down only), and a cooling-off wait with a fresh check." }),
      ]);
    }
    const a = latest.data.assessment;
    const notes = state.events.filter((e) => e.round_id === latest.round_id && e.kind === "risk_note");
    const worst = Math.max(1, ...(a.stress || []).map((s) => s.pct_of_equity));
    return [
      el("section", { class: "card risk-card" }, [
        el("header", { class: "risk-head" }, [
          el("div", { class: `grade grade-${a.grade}`, text: a.grade }),
          el("div", {}, [
            el("h2", { text: `${latest.symbol}: buy ${num(a.qty)} near ${num(a.entry)}` }),
            el("p", { class: "muted", text: `Stop ${num(a.stop)} · target ${num(a.target)} · code grade ${a.code_grade}${a.guardian_grade ? ` · Guardian ${a.guardian_grade}` : ""} · ${a.passed ? "passed" : "stopped"}` }),
          ]),
        ]),
        el("div", { class: "risk-stats" }, [
          stat("At risk", `${money(a.at_risk)} (${Number(a.at_risk_pct || 0).toFixed(2)}%)`),
          stat("Reward : risk", a.reward_risk == null ? "—" : `${Number(a.reward_risk).toFixed(2)} : 1`),
          stat("Chance target first", chance(a.p_target)),
          stat("Expected value", money(a.ev), toneOf(a.ev)),
          stat("¼ Kelly", a.kelly == null ? "—" : `${(a.kelly * 100).toFixed(1)}%`),
          stat("Stop distance", a.stop_atr == null ? "—" : `${Number(a.stop_atr).toFixed(2)} ATR`),
          stat("Of daily volume", a.adv_pct == null ? "—" : `${Number(a.adv_pct).toFixed(3)}%`),
          stat("Size factor", `×${Number(a.size_factor ?? 1).toFixed(2)}`),
        ]),
        el("h3", { text: "Stress tests" }),
        el(
          "div",
          { class: "stress" },
          (a.stress || []).map((s) =>
            el("div", { class: "stress-row" }, [
              el("span", { text: s.name }),
              el("span", { class: "bar" }, [el("i", { style: `width:${Math.min(100, (s.pct_of_equity / worst) * 100)}%` })]),
              el("strong", { text: `−${money(s.loss)} (${Number(s.pct_of_equity).toFixed(2)}%)` }),
            ])
          )
        ),
        a.events?.length ? el("h3", { text: "Events in the holding window" }) : null,
        a.events?.length ? el("ul", {}, a.events.map((e) => el("li", { class: e.in_window ? "warn" : "", text: `${e.name}: ${e.date || "date unknown"}${e.days_away != null ? ` (${e.days_away} days)` : ""}` }))) : null,
        a.meme_warnings?.length ? el("p", { class: "trade-error", text: `Meme-coin warnings: ${a.meme_warnings.join(", ")}` }) : null,
        a.blockers?.length ? el("p", { class: "trade-error", text: `Stopped: ${a.blockers.join("; ")}` }) : null,
        a.cautions?.length ? el("p", { class: "muted", text: `Cautions: ${a.cautions.join("; ")}` }) : null,
        a.conditions?.length ? el("p", { text: `Conditions: ${a.conditions.join("; ")}` }) : null,
        a.fx_note ? el("p", { class: "muted", text: a.fx_note }) : null,
      ]),
      el("section", { class: "card" }, [
        el("h2", { text: "The seats' risk notes" }),
        notes.length ? el("div", {}, notes.map(bubble)) : el("p", { class: "empty", text: "No notes." }),
      ]),
    ];
  }

  /* ------------------------------------------------------------ orders */

  async function ordersPanel() {
    const [orders, rounds, summary] = await Promise.all([
      ctx.api("/studio/api/trading/orders"),
      ctx.api("/studio/api/trading/rounds"),
      ctx.api("/studio/api/trading/summary"),
    ]);
    return [
      el("section", { class: "card" }, [
        el("h2", { text: "Results" }),
        el("div", { class: "risk-stats" }, [
          stat("Realised", money(summary.realised, state.status?.currency), toneOf(summary.realised)),
          stat("Closed trades", String(summary.closed_trades)),
          stat("Win rate", chance(summary.win_rate)),
        ]),
        el("button", { class: "secondary", text: `Download the tax CSV (capital gains, ${state.status?.currency || "AUD"})`, onclick: () => downloadCsv() }),
        el("p", { class: "muted", text: "First-in, first-out, with the held-over-12-months flag for the CGT discount. A record for your accountant, not tax advice." }),
      ]),
      el("section", { class: "card" }, [
        el("h2", { text: "Orders" }),
        orders.orders.length
          ? el("div", { class: "table-wrap" }, [
              el("table", { class: "trade-table" }, [
                el("thead", {}, [el("tr", {}, ["When", "Order", "Status", "Fill", "Fees", "Platform", "Why"].map((h) => el("th", { text: h })))]),
                el(
                  "tbody",
                  {},
                  orders.orders.map((o) =>
                    el("tr", {}, [
                      el("td", { text: ago(o.created_at) }),
                      el("td", { text: `${o.side} ${num(o.qty)} ${o.symbol}` }),
                      el("td", { text: o.status.replace(/_/g, " ") }),
                      el("td", { text: o.fill_price ? `${num(o.fill_price)} ${o.currency}` : "—" }),
                      el("td", { text: o.fees ? money(o.fees) : "—" }),
                      el("td", { text: o.broker }),
                      el("td", { class: "muted", text: o.reason || "" }),
                    ])
                  )
                ),
              ]),
            ])
          : el("p", { class: "empty", text: "No orders yet." }),
      ]),
      decisionsCard(),
      el("section", { class: "card" }, [
        el("h2", { text: "Rounds" }),
        rounds.rounds.length
          ? el(
              "ul",
              { class: "round-list" },
              rounds.rounds.map((r) => el("li", {}, [el("strong", { text: r.symbol }), ` ${r.status} · consensus ${chance(r.consensus)} · ${ago(r.created_at)}`, r.note ? el("span", { class: "muted", text: ` — ${r.note}` }) : null]))
            )
          : el("p", { class: "empty", text: "No rounds yet." }),
      ]),
    ];
  }

  function decisionsCard() {
    const words = el("input", { type: "search", placeholder: "Words, e.g. stale or BTC", "aria-label": "Search decisions" });
    const symbol = el("input", { type: "text", placeholder: "Symbol", "aria-label": "Symbol", size: "8" });
    const status = el(
      "select",
      { "aria-label": "Decision status" },
      [
        ["", "Any status"],
        ["no_trade", "No trade"],
        ["blocked", "Blocked"],
        ["discarded", "Discarded (stale)"],
        ["rejected", "Rejected"],
        ["alert", "Alert"],
        ["order_submitted", "Order sent"],
        ["position_open", "Position open"],
        ["position_closed", "Closed"],
      ].map(([value, label]) => el("option", { value, text: label }))
    );
    const list = el("div", { class: "decision-list" }, [el("p", { class: "muted", text: "Every cycle's record: the evidence, each seat, every rule checked, and what happened." })]);
    const search = async () => {
      const query = new URLSearchParams({ q: words.value, symbol: symbol.value, status: status.value, limit: "50" });
      try {
        const found = await ctx.api(`/studio/api/trading/decisions?${query}`);
        fill(list, found.decisions.length ? found.decisions.map(decisionRow) : [el("p", { class: "empty", text: "No decisions match." })]);
      } catch (error) {
        fill(list, el("p", { class: "trade-error", text: error.message }));
      }
    };
    return el("section", { class: "card" }, [
      el("h2", { text: "Decision records" }),
      el("div", { class: "row" }, [
        words,
        symbol,
        status,
        el("button", { class: "secondary", text: "Search", onclick: search }),
        el("button", { class: "ghost", text: "Download the audit trail (CSV)", onclick: () => downloadFile("/studio/api/trading/audit.csv", "fcc-audit.csv") }),
      ]),
      list,
    ]);
  }

  function decisionRow(record) {
    const data = record.data || {};
    const failed = (data.risk_checks || []).filter((check) => check && check.passed === false);
    const result = data.result || null;
    return el("details", { class: "decision" }, [
      el("summary", {}, [
        el("strong", { text: record.symbol }),
        ` ${record.status.replace(/_/g, " ")} · ${ago(record.created_at)}`,
        record.pnl != null ? el("span", { class: `pill ${record.pnl >= 0 ? "good" : "warn"}`, text: money(record.pnl) }) : null,
      ]),
      record.reason ? el("p", { text: record.reason }) : null,
      (data.rejection_reasons || []).length ? el("p", { class: "muted", text: `Why not: ${data.rejection_reasons.join("; ")}` }) : null,
      failed.length
        ? el("ul", { class: "round-list" }, failed.map((check) => el("li", { text: `${check.rule}: measured ${check.measured ?? "—"}${check.unit ? ` ${check.unit}` : ""}, limit ${check.limit ?? "—"}${check.detail ? ` (${check.detail})` : ""}` })))
        : null,
      result
        ? el("p", { class: "muted", text: `Result: ${result.exit || ""}; entry ${num(result.entry)} → exit ${num(result.exit_price)}; worst ${result.mae_pct ?? "—"}%, best ${result.mfe_pct ?? "—"}%; fees ${result.fees ?? "—"}.` })
        : null,
      el("p", { class: "muted", text: `Rules ${record.config_version} · FCC ${record.system_version} · evidence ${record.pack_id || "—"}` }),
    ]);
  }

  async function downloadFile(path, name) {
    let key = "";
    try {
      key = localStorage.getItem("fcc.studio.token") || "";
    } catch {
      /* no saved token: the server may not need one */
    }
    try {
      const response = await fetch(path, { headers: key ? { "x-api-key": key } : {} });
      if (!response.ok) throw new Error(`The file didn't download (${response.status}).`);
      saveFile(await response.blob(), name);
    } catch (error) {
      ctx.notify(error.message);
    }
  }

  /* ------------------------------------------------------------ debriefs */

  async function debriefsPanel() {
    const [debriefs, stats, learning, backtests] = await Promise.all([
      ctx.api("/studio/api/trading/debriefs"),
      ctx.api("/studio/api/trading/seats/stats"),
      ctx.api("/studio/api/trading/learning"),
      ctx.api("/studio/api/trading/backtests"),
    ]);
    const market = el("select", { "aria-label": "Debrief" }, [
      ["weekly", "Weekly review"],
      ["asx", "ASX session"],
      ["us", "US session"],
      ["crypto", "Crypto day"],
    ].map(([value, label]) => el("option", { value, text: label })));
    return [
      el("section", { class: "card" }, [
        el("h2", { text: "Leaderboard" }),
        el(
          "div",
          { class: "seat-grid" },
          stats.seats.map((s) =>
            el("article", { class: "seat-card", style: `--seat:${seat(s.seat).colour}` }, [
              el("strong", { text: s.name }),
              el("p", { text: s.all.line }),
              s.all.buckets?.length ? calibration(s.all.buckets) : null,
            ])
          )
        ),
      ]),
      learningCard(learning),
      backtestCard(backtests),
      el("section", { class: "card" }, [
        el("h2", { text: "Debriefs" }),
        el("div", { class: "row" }, [
          market,
          el("button", {
            class: "secondary",
            text: "Run now",
            onclick: async () => {
              try {
                await ctx.post("/studio/api/trading/debrief", { market: market.value });
                ctx.notify("Debrief queued; it runs when the desk is free.");
              } catch (error) {
                ctx.notify(error.message);
              }
            },
          }),
        ]),
        debriefs.debriefs.length ? el("div", { class: "debrief-list" }, debriefs.debriefs.map(debriefCard)) : el("p", { class: "empty", text: "No debriefs yet: they come after closed trades, forecasts that come due, each market close, and each week." }),
      ]),
    ];
  }

  function learningCard(learning) {
    const versions = learning.versions || [];
    return el("section", { class: "card" }, [
      el("h2", { text: learning.active_version ? `Learning: vote weights v${learning.active_version}` : "Learning: every seat counts the same" }),
      el("div", { class: "risk-stats" }, Object.entries(learning.weights || {}).map(([number, weight]) => stat(SEAT_NAMES[number] || `Seat ${number}`, `×${Number(weight).toFixed(2)}`))),
      el("p", { class: "muted", text: learning.rules }),
      versions.length
        ? el("ul", { class: "round-list" }, versions.slice(0, 8).map((v) => el("li", {}, [el("strong", { text: `v${v.version} ${v.status.replace(/_/g, " ")}` }), ` · ${ago(v.created_at)} — `, el("span", { class: "muted", text: v.reason })])))
        : el("p", { class: "empty", text: "No learned versions yet: weights only move after 50+ scored forecasts per seat, and only if they test better." }),
      learning.active_version
        ? el("button", {
            class: "secondary",
            text: "Roll back to the previous weights",
            onclick: async () => {
              if (!window.confirm("Undo the active vote weights?")) return;
              try {
                await ctx.post("/studio/api/trading/learning/rollback", {});
                ctx.notify("Rolled back.");
                await drawPanel();
              } catch (error) {
                ctx.notify(error.message);
              }
            },
          })
        : null,
    ]);
  }

  function backtestCard(kept) {
    const market = el("select", { "aria-label": "Backtest market" }, [["us", "US shares"], ["asx", "ASX shares"], ["crypto", "Crypto"]].map(([value, label]) => el("option", { value, text: label })));
    const days = el("input", { type: "number", min: "30", max: "1500", step: "30", value: "365", "aria-label": "Days" });
    const symbols = el("input", { type: "text", placeholder: "Symbols (optional), e.g. AAPL, MSFT", "aria-label": "Symbols" });
    const out = el("div", { class: "backtest-result" });
    const show = (result) => {
      const m = result.metrics || {};
      fill(
        out,
        el("p", { class: "muted", text: result.label || "" }),
        result.error
          ? el("p", { class: "trade-error", text: result.error })
          : el("div", { class: "risk-stats" }, [
              stat("Return", m.return_pct == null ? "—" : `${m.return_pct}%`, toneOf(m.return_pct)),
              stat("Worst drawdown", m.max_drawdown_pct == null ? "—" : `${m.max_drawdown_pct}%`, "bad"),
              stat("Trades", String(m.trades ?? 0)),
              stat("Win rate", m.win_rate_pct == null ? "—" : `${m.win_rate_pct}%`),
              stat("Average R", m.average_r == null ? "—" : String(m.average_r)),
              stat("Fees", m.fees == null ? "—" : money(m.fees)),
            ])
      );
    };
    const run = el("button", {
      class: "secondary",
      text: "Run backtest",
      onclick: async () => {
        run.disabled = true;
        fill(out, el("p", { class: "muted", text: "Replaying the rules on past prices…" }));
        try {
          const list = symbols.value.split(",").map((text) => text.trim()).filter(Boolean);
          show(await ctx.post("/studio/api/trading/backtest", { market: market.value, days: Number(days.value), symbols: list }));
        } catch (error) {
          fill(out, el("p", { class: "trade-error", text: error.message }));
        } finally {
          run.disabled = false;
        }
      },
    });
    if (kept.length) show(kept[0]);
    return el("section", { class: "card" }, [
      el("h2", { text: "Backtest" }),
      el("p", { class: "muted", text: "The desk's own rules on past daily prices (closed candles only, filled at the next open, with fees, spread and slippage). The seats' debate isn't replayed. Past results are not a prediction." }),
      el("div", { class: "row" }, [market, el("label", {}, ["Days ", days]), symbols, run]),
      out,
      kept.length > 1 ? el("p", { class: "muted", text: `${kept.length} backtests kept (newest shown).` }) : null,
    ]);
  }

  function debriefCard(item) {
    const suggestions = item.data?.suggestions || [];
    const notes = item.data?.notes || {};
    return el("article", { class: `debrief kind-${item.kind}` }, [
      el("header", {}, [el("strong", { text: item.title }), el("span", { class: "muted", text: `${item.kind} · ${ago(item.created_at)}` })]),
      el("p", { text: item.summary }),
      item.lesson ? el("p", { class: "lesson", text: `Lesson: ${item.lesson}` }) : null,
      Object.keys(notes).length
        ? el(
            "details",
            {},
            [el("summary", { text: "Each seat's notes" })].concat(
              Object.entries(notes).map(([number, note]) =>
                el("p", { style: `--seat:${seat(Number(number)).colour}`, class: "seat-note" }, [
                  el("strong", { text: `${seat(Number(number)).name}: ` }),
                  note.missed ? `Missed: ${note.missed}. ` : "",
                  note.lesson ? `Lesson: ${note.lesson}` : (note.notes || []).join("; "),
                ])
              )
            )
          )
        : null,
      ...suggestions.map((s, index) =>
        el("div", { class: "suggestion" }, [
          el("span", { text: `${s.text} → set ${s.setting} to ${s.value}` }),
          s.accepted
            ? el("span", { class: "pill good", text: "accepted" })
            : el("button", {
                class: "secondary",
                text: "Accept",
                onclick: async (event) => {
                  try {
                    await ctx.post(`/studio/api/trading/debriefs/${item.id}/suggestions/${index}`, {});
                    event.target.replaceWith(el("span", { class: "pill good", text: "accepted" }));
                    state.config = await ctx.api("/studio/api/trading/config");
                  } catch (error) {
                    ctx.notify(error.message);
                  }
                },
              }),
        ])
      ),
    ]);
  }

  /* ------------------------------------------------------------ setup */

  async function setupPanel() {
    const [config, brokers, models] = await Promise.all([
      ctx.api("/studio/api/trading/config"),
      ctx.api("/studio/api/trading/brokers"),
      state.models ? Promise.resolve(state.models) : ctx.api("/studio/api/models/available").catch(() => ({ server: [], local: { models: [] } })),
    ]);
    state.config = config;
    state.brokers = brokers.brokers;
    state.models = models;
    const modelList = el(
      "datalist",
      { id: "trade-models" },
      [...(models.server || []), ...((models.local && models.local.models) || [])].map((m) => el("option", { value: m }))
    );
    return [
      modelList,
      modeCard(config),
      marketsCard(config),
      seatsCard(config),
      limitsCard(config),
      paperCard(config),
      platformsCard(config),
      el("section", { class: "card honest" }, [
        el("h2", { text: "Before real money" }),
        el("p", { text: "No system can promise returns, and model debates can be confidently wrong. Run paper mode for a few weeks, read the debriefs and the leaderboard, and start live with small limits. Hard limits are plain code that no model can talk past; keys never need withdrawal rights." }),
      ]),
    ];
  }

  async function saveConfig(values, confirm = "") {
    try {
      state.config = await ctx.api("/studio/api/trading/config", { method: "PUT", body: JSON.stringify({ values, confirm }) });
      state.status = await ctx.api("/studio/api/trading");
      paintStrip();
      ctx.notify("Saved.");
      return true;
    } catch (error) {
      ctx.notify(error.message);
      return false;
    }
  }

  function modeCard(config) {
    const brokerSelect = el(
      "select",
      { "aria-label": "Platform" },
      state.brokers.map((b) => el("option", { value: b.id, text: `${b.name}${b.id !== "paper" && !b.verified ? " (not verified)" : ""}` }))
    );
    brokerSelect.value = config.broker;
    const phrase = el("input", { type: "text", placeholder: "Type the phrase to allow live automatic orders", "aria-label": "Confirmation phrase" });
    const choices = el(
      "div",
      { class: "mode-choices" },
      MODES.map(([id, label, help]) =>
        el("label", { class: `mode-choice${config.mode === id ? " on" : ""}` }, [
          el("input", { type: "radio", name: "trade-mode", value: id, checked: config.mode === id }),
          el("strong", { text: label }),
          el("small", { text: help }),
        ])
      )
    );
    return el("section", { class: "card" }, [
      el("h2", { text: "Mode and platform" }),
      choices,
      el("label", {}, ["Platform ", brokerSelect]),
      el("p", { class: "muted", text: 'Live automatic needs the phrase: "I accept real-money trades". Switching to live works only on the PC, after the platform\'s keys are saved and its account verified.' }),
      phrase,
      el("button", {
        class: "primary",
        text: "Save mode",
        onclick: () => {
          const mode = choices.querySelector("input:checked")?.value || "paper";
          saveConfig({ mode, broker: brokerSelect.value }, phrase.value);
        },
      }),
    ]);
  }

  function marketsCard(config) {
    const toggles = MARKETS.map(([id, label]) => el("label", { class: "check" }, [el("input", { type: "checkbox", "data-market": id, checked: !!config.markets[id] }), label]));
    const watch = el("textarea", { rows: "2", placeholder: "BHP.AX, CBA.AX, NVDA, BTC, PEPE…", "aria-label": "Watchlist" });
    watch.value = (config.watchlist || []).join(", ");
    const scan = el("input", { type: "number", min: "5", max: "1440", value: String(config.scan_minutes), "aria-label": "Scan every (minutes)" });
    const candidates = el("input", { type: "number", min: "1", max: "5", value: String(config.candidates), "aria-label": "Debates per scan" });
    const rounds = el("input", { type: "number", min: "1", max: "6", value: String(config.debate_rounds ?? 4), "aria-label": "Debate rounds" });
    const depth = el(
      "div",
      { class: "mode-choices" },
      DEPTHS.map(([id, label, help]) =>
        el("label", { class: `mode-choice${config.depth === id ? " on" : ""}` }, [
          el("input", { type: "radio", name: "trade-depth", value: id, checked: config.depth === id }),
          el("strong", { text: label }),
          el("small", { text: help }),
        ])
      )
    );
    return el("section", { class: "card" }, [
      el("h2", { text: "Markets and prediction depth" }),
      el("div", { class: "row wrap" }, toggles),
      el("label", {}, ["Watchlist (always scanned first)", watch]),
      el("div", { class: "row wrap" }, [el("label", {}, ["Scan every (min) ", scan]), el("label", {}, ["Debates per scan ", candidates]), el("label", {}, ["Debate rounds ", rounds])]),
      el("p", { class: "muted", text: "Each debate runs this many rounds. Between rounds the seats' questions are researched, their ideas sorted, and their plans simulated on past prices (not a prediction)." }),
      depth,
      el("button", {
        class: "primary",
        text: "Save",
        onclick: () => {
          const markets = {};
          for (const box of toggles.map((t) => t.querySelector("input"))) markets[box.dataset.market] = box.checked;
          saveConfig({
            markets,
            watchlist: watch.value,
            scan_minutes: Number(scan.value),
            candidates: Number(candidates.value),
            debate_rounds: Number(rounds.value),
            depth: depth.querySelector("input:checked")?.value || "balanced",
          });
        },
      }),
    ]);
  }

  function seatsCard(config) {
    const rows = config.seats.map((s) => {
      const model = el("input", { type: "text", list: "trade-models", value: s.model || "", placeholder: "Studio's server model", "aria-label": `${s.name} model` });
      const temperature = el("input", { type: "number", step: "0.1", min: "0", max: "1.5", value: String(s.temperature), "aria-label": `${s.name} temperature` });
      const on = el("input", { type: "checkbox", checked: s.on, disabled: s.seat >= 4 });
      return { s, model, temperature, on, node: el("div", { class: "seat-row", style: `--seat:${seat(s.seat).colour}` }, [el("strong", { text: s.name }), model, el("label", {}, ["temp ", temperature]), el("label", { class: "check" }, [on, s.seat >= 4 ? "always on" : "on"])]) };
    });
    return el("section", { class: "card" }, [
      el("h2", { text: "Seats and their models" }),
      el("p", { class: "muted", text: "Each seat can think with its own model: a server model (fast, many in parallel) or one on this PC (local seats take turns on the graphics card)." }),
      ...rows.map((r) => r.node),
      el("button", {
        class: "primary",
        text: "Save seats",
        onclick: () =>
          saveConfig({
            seats: rows.map((r) => ({ seat: r.s.seat, name: r.s.name, model: r.model.value.trim(), temperature: Number(r.temperature.value), on: r.on.checked })),
          }),
      }),
    ]);
  }

  function numberField(label, value, path, attrs = {}) {
    const input = el("input", { type: "number", value: String(value), step: attrs.step || "any", min: attrs.min, max: attrs.max, "data-path": path, "aria-label": label });
    return el("label", { class: "limit" }, [el("span", { text: label }), input]);
  }

  function limitsCard(config) {
    const r = config.risk;
    const a = config.assessment;
    const fields = [
      numberField("Risk per trade (% of equity at the stop)", r.risk_per_trade_pct, "risk.risk_per_trade_pct", { step: "0.1", min: "0.1", max: "5" }),
      numberField("Max in one position (%)", r.max_position_pct, "risk.max_position_pct", { min: "1", max: "50" }),
      numberField(`Max order value (${config.currency})`, r.max_order_value, "risk.max_order_value", { min: "10" }),
      numberField("Max open positions", r.max_open_positions, "risk.max_open_positions", { step: "1", min: "1", max: "50" }),
      numberField("Max trades a day", r.max_trades_per_day, "risk.max_trades_per_day", { step: "1", min: "1", max: "100" }),
      numberField("Stop trading after a daily loss of (%)", r.max_daily_loss_pct, "risk.max_daily_loss_pct", { step: "0.5", min: "0.5", max: "20" }),
      numberField("Min confidence", r.min_confidence, "risk.min_confidence", { step: "0.05", min: "0.3", max: "0.95" }),
      numberField("Min weighted chance of a rise", r.min_consensus, "risk.min_consensus", { step: "0.05", min: "0.5", max: "0.9" }),
      numberField("Cool-down per symbol (min)", r.cooldown_minutes, "risk.cooldown_minutes", { step: "5", min: "0" }),
      numberField("Price move allowed vs decision (%)", r.slippage_pct, "risk.slippage_pct", { step: "0.1", min: "0.1", max: "10" }),
      numberField("Meme coin: max per coin (%)", r.meme_position_pct, "risk.meme_position_pct", { step: "0.1", min: "0.1", max: "10" }),
      numberField("Meme coins: max in total (%)", r.meme_total_pct, "risk.meme_total_pct", { step: "0.5", min: "0.5", max: "25" }),
      numberField("Meme coin: min liquidity (USD)", r.meme_min_liquidity_usd, "risk.meme_min_liquidity_usd", { step: "10000", min: "10000" }),
      numberField("Min reward for risk (x to 1)", a.min_reward_risk, "assessment.min_reward_risk", { step: "0.1", min: "0.5", max: "10" }),
      numberField("Max correlation with a holding", a.max_correlation, "assessment.max_correlation", { step: "0.05", min: "0.3", max: "1" }),
      numberField("Max share of a day's volume (%)", a.max_adv_pct, "assessment.max_adv_pct", { step: "0.1", min: "0.01", max: "25" }),
      numberField("Earnings blackout (days)", a.earnings_blackout_days, "assessment.earnings_blackout_days", { step: "1", min: "0", max: "30" }),
      numberField("Cooling-off, shares (min)", a.cooling_stocks_minutes, "assessment.cooling_stocks_minutes", { step: "0.5", min: "0", max: "15" }),
      numberField("Cooling-off, crypto (min)", a.cooling_crypto_minutes, "assessment.cooling_crypto_minutes", { step: "0.5", min: "0", max: "15" }),
    ];
    const grade = el("select", { "aria-label": "Minimum risk grade" }, ["A", "B", "C", "D"].map((g) => el("option", { value: g, text: g })));
    grade.value = a.min_grade;
    const lists = el("textarea", { rows: "2", placeholder: "Never trade: symbols separated by commas", "aria-label": "Do-not-trade list" });
    lists.value = (r.deny || []).join(", ");
    return el("section", { class: "card" }, [
      el("h2", { text: "Hard limits and the risk period" }),
      el("p", { class: "muted", text: "Plain code enforces these on every order. The weekly review may suggest changes; none happen without your Accept." }),
      el("div", { class: "limits-grid" }, [...fields, el("label", { class: "limit" }, [el("span", { text: "Minimum risk grade" }), grade])]),
      el("label", {}, ["Do-not-trade list", lists]),
      el("button", {
        class: "primary",
        text: "Save limits",
        onclick: () => {
          const values = { risk: { deny: lists.value }, assessment: { min_grade: grade.value } };
          for (const input of fields.map((f) => f.querySelector("input"))) {
            const [group, key] = input.dataset.path.split(".");
            values[group][key] = Number(input.value);
          }
          saveConfig(values);
        },
      }),
    ]);
  }

  function paperCard(config) {
    const cash = el("input", { type: "number", min: "100", step: "100", value: String(config.paper_cash), "aria-label": "Paper cash" });
    return el("section", { class: "card" }, [
      el("h2", { text: "Paper account" }),
      el("p", { class: "muted", text: `Practice money on real prices, in ${config.currency}; fees ${config.fee_pct}% (min ${config.min_fee}).` }),
      el("label", {}, [
        "Practice coin prices from ",
        el(
          "select",
          {
            "aria-label": "Practice coin prices",
            onchange: (event) => saveConfig({ practice_book: event.target.value }),
          },
          [
            ["exchanges", "Coin exchanges (Coinbase, Kraken)"],
            ["hyperliquid", "Hyperliquid's live book (Invo)"],
          ].map(([value, label]) => el("option", { value, text: label, selected: config.practice_book === value }))
        ),
      ]),
      el("label", {}, [`Start again with (${config.currency}) `, cash]),
      el("button", {
        class: "secondary",
        text: "Reset the paper account",
        onclick: async () => {
          if (!window.confirm("Reset the paper account? Its holdings are cleared.")) return;
          try {
            state.status = await ctx.post("/studio/api/trading/paper/reset", { cash: Number(cash.value) });
            paintStrip();
            ctx.notify("Paper account reset.");
          } catch (error) {
            ctx.notify(error.message);
          }
        },
      }),
    ]);
  }

  function platformsCard(config) {
    return el("section", { class: "card" }, [
      el("h2", { text: "Platforms" }),
      el("p", { class: "muted", text: "Keys are encrypted on this PC (Windows' own protection), never shown back, and blanked out of every log. Saving keys and verifying accounts works only on the PC. Keys that can withdraw or transfer money are refused." }),
      state.status?.vault && !state.status.vault.available ? el("p", { class: "trade-error", text: state.status.vault.note }) : null,
      ...state.brokers.filter((b) => b.id !== "paper").map((b) => brokerCard(b, config)),
    ]);
  }

  function brokerCard(broker, config) {
    const inputs = broker.fields.map((field) => {
      const input = field.choices.length
        ? el("select", { "aria-label": field.label }, [el("option", { value: "", text: field.placeholder ? `${field.placeholder} (default)` : "—" }), ...field.choices.map((c) => el("option", { value: c, text: c }))])
        : field.key === "template"
          ? el("textarea", { rows: "3", placeholder: "JSON with {symbol} {qty} {side} {price} {stop} {take_profit}…", "aria-label": field.label })
          : el("input", {
              type: field.secret ? "password" : "text",
              autocomplete: "off",
              placeholder: field.secret ? (field.set ? "•••••• (saved; type to replace)" : field.placeholder || "") : field.placeholder || "",
              "aria-label": field.label,
            });
      if (!field.secret && field.value) input.value = field.value;
      return { field, input };
    });
    const result = el("div", { class: "broker-result" });
    const save = el("button", {
      class: "primary",
      text: "Save keys",
      onclick: async () => {
        const values = {};
        for (const { field, input } of inputs) if (input.value.trim()) values[field.key] = input.value.trim();
        try {
          await ctx.api(`/studio/api/trading/brokers/${broker.id}`, { method: "PUT", body: JSON.stringify({ values }) });
          ctx.notify(`${broker.name} keys saved. Test, then verify the account.`);
          await drawPanel();
        } catch (error) {
          ctx.notify(error.message);
        }
      },
    });
    const test = el("button", {
      class: "secondary",
      text: "Test",
      onclick: async () => {
        result.replaceChildren(el("p", { class: "muted", text: "Connecting…" }));
        try {
          const shown = await ctx.post(`/studio/api/trading/brokers/${broker.id}/test`, {});
          const account = shown.account;
          fill(
            result,
            el("p", { text: `Account ${account.number} · ${account.currency} · equity ${money(account.equity)} · buying power ${money(account.buying_power)} · ${account.status}` }),
            account.note ? el("p", { class: "muted", text: account.note }) : null,
            el("button", {
              class: "primary",
              text: "Yes, this is my account",
              onclick: async () => {
                try {
                  await ctx.post(`/studio/api/trading/brokers/${broker.id}/confirm`, { fingerprint: account.fingerprint });
                  ctx.notify("Verified: every order checks it's still this account.");
                  await drawPanel();
                } catch (error) {
                  ctx.notify(error.message);
                }
              },
            })
          );
        } catch (error) {
          result.replaceChildren(el("p", { class: "trade-error", text: error.message }));
        }
      },
    });
    const forget = el("button", {
      class: "ghost",
      text: "Remove keys",
      onclick: async () => {
        if (!window.confirm(`Remove the ${broker.name} keys?`)) return;
        try {
          await ctx.remove(`/studio/api/trading/brokers/${broker.id}`);
          await drawPanel();
        } catch (error) {
          ctx.notify(error.message);
        }
      },
    });
    return el("details", { class: "broker", open: config.broker === broker.id }, [
      el("summary", {}, [
        el("strong", { text: broker.name }),
        el("span", { class: "muted", text: ` ${broker.markets.join(", ")}` }),
        broker.connected ? el("span", { class: `pill ${broker.verified ? "good" : "warn"}`, text: broker.verified ? "verified" : "keys saved" }) : null,
      ]),
      el("p", { text: broker.what }),
      el("p", { class: "muted", text: broker.australia }),
      el("p", { class: "muted", text: `Keys: ${broker.get_keys}` }),
      ...inputs.map(({ field, input }) => el("label", {}, [`${field.label}${field.optional ? " (optional)" : ""} `, input])),
      el("div", { class: "row" }, [save, test, broker.connected ? forget : null]),
      result,
    ]);
  }

  window.FCCTrade = { render };
})();
