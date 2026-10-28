// Trading: the Trading Bank on your PC, through the PC link. The phone reads
// the desk and can start practice, stop, deny any waiting order, approve a
// practice order, and use the kill switch. Real money is switched on, and
// real-money orders approved, on the PC only.
import { state } from "../state.js";
import { el, button, card, notify, openSheet, closeSheet, go, ago } from "../ui.js";
import { pcCall } from "../sync.js";

const REFRESH_MS = 10000;
const FLATTEN_PHRASE = "CLOSE EVERYTHING";

const money = (value, currency) =>
  typeof value === "number" ? `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ""}` : "–";
const pct = (value) => (typeof value === "number" ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : "–");

export function render(view) {
  if (!state.settings.pc) {
    view.replaceChildren(
      card("Trading", [
        el("p", { text: "The Trading Bank runs on your PC. Pair this phone with your PC to watch it and control it from here." }),
        button("Pair with my PC", () => go("settings"), { class: "primary" }),
      ])
    );
    return null;
  }
  let desk = null;
  let feed = [];
  let last = 0;
  let timer = null;
  let gone = false;
  let problem = "";

  const act = async (path, payload, done) => {
    try {
      await pcCall(`/studio/api/phone/trading${path}`, payload ?? {});
      if (done) notify(done);
    } catch (error) {
      notify(error.message);
    }
    await refresh();
  };

  const killSheet = () => {
    const flatten = el("input", { type: "checkbox", "aria-label": "Also close every position" });
    const phrase = el("input", { "aria-label": "Type the phrase to close everything", placeholder: FLATTEN_PHRASE, autocomplete: "off" });
    openSheet("Kill switch", [
      el("p", { text: "Stops the desk on every account and cancels every waiting order. It stays on until you release it on the PC." }),
      el("label", { class: "row" }, [flatten, el("span", { text: " Also close every position" })]),
      el("p", { class: "muted small", text: `To close every position too, type ${FLATTEN_PHRASE}.` }),
      phrase,
      button("Stop everything", async () => {
        closeSheet();
        await act("/kill", { flatten: flatten.checked, confirm: phrase.value }, "Kill switch on.");
      }, { class: "danger" }),
    ]);
  };

  const orderRow = (order) =>
    el("div", { class: "item" }, [
      el("div", { class: "grow" }, [
        el("strong", { text: `${order.side} ${order.qty} ${order.symbol}` }),
        el("small", {
          text: `${order.status.replaceAll("_", " ")} · ${order.mode === "paper" ? "practice" : "REAL MONEY"}${order.seconds_left != null ? ` · ${order.seconds_left}s left` : ""}${order.reason ? ` · ${order.reason}` : ""}`,
        }),
      ]),
      order.status === "awaiting_approval" && order.mode === "paper"
        ? button("Approve", () => act(`/orders/${encodeURIComponent(order.id)}/approve`, {}, "Approved."), { class: "primary", "aria-label": `Approve ${order.side} ${order.symbol}` })
        : null,
      order.status === "awaiting_approval"
        ? button("Deny", () => act(`/orders/${encodeURIComponent(order.id)}/deny`, {}, "Denied."), { class: "danger", "aria-label": `Deny ${order.side} ${order.symbol}` })
        : null,
    ]);

  const draw = () => {
    if (gone) return;
    if (!desk) {
      view.replaceChildren(card("Trading", [el("p", { class: problem ? "warn" : "muted", text: problem || "Reading your PC's desk…" })]));
      return;
    }
    const account = desk.account || {};
    const currency = account.currency || desk.currency || "";
    const summary = desk.summary || {};
    const waiting = (desk.orders || []).filter((order) => order.status === "awaiting_approval");
    const others = (desk.orders || []).filter((order) => order.status !== "awaiting_approval");
    view.replaceChildren(
      ...(desk.live ? [el("p", { class: "banner danger", role: "alert", text: "REAL MONEY is switched on (from the PC)." })] : []),
      ...(desk.kill ? [el("p", { class: "banner danger", role: "alert", text: `Kill switch on${desk.kill.reason ? `: ${desk.kill.reason}` : ""}. Release it on the PC.` })] : []),
      ...(desk.breaker ? [el("p", { class: "banner warn", text: `Paused by the safety breaker: ${desk.breaker.reason || desk.breaker.kind}` })] : []),
      card("Desk", [
        el("p", { text: `${desk.running ? "Running" : "Stopped"} · ${desk.mode_label || desk.mode} · ${desk.broker_name || ""}` }),
        desk.busy ? el("p", { class: "muted small", text: `Working: ${Object.values(desk.activity || {}).join(", ") || "a round"}` }) : null,
        problem ? el("p", { class: "warn", text: problem }) : null,
        el("div", { class: "row" }, [
          desk.running
            ? button("Stop", () => act("/stop", {}, "Stopped. Open positions are still watched."))
            : button("Start practice", () => act("/start", {}, "Practice started."), { class: "primary", disabled: Boolean(desk.kill) }),
          button("Kill switch", killSheet, { class: "danger" }),
        ]),
        el("p", { class: "muted small", text: "Real money, keys and settings are changed on the PC only." }),
      ]),
      card("Account", [
        account.error ? el("p", { class: "warn", text: account.error }) : null,
        el("p", { text: `Value ${money(account.equity_base ?? account.equity, currency)} · cash ${money(account.cash, currency)}` }),
        el("p", { text: `Today ${pct(account.day_change_pct)} · ${account.trades_today ?? 0} trades · invested ${money(account.invested, currency)}` }),
        el("p", { text: `Closed trades ${summary.closed_trades ?? 0} · profit ${money(summary.realised, currency)} · win rate ${summary.win_rate == null ? "–" : `${Math.round(summary.win_rate * 100)}%`}` }),
      ]),
      card(`Waiting for you (${waiting.length})`, waiting.length ? waiting.map(orderRow) : [el("p", { class: "empty", text: "No orders are waiting." })]),
      card("Positions", [
        desk.positions_problem ? el("p", { class: "warn", text: desk.positions_problem }) : null,
        ...((desk.positions || []).length
          ? desk.positions.map((item) =>
              el("div", { class: "item" }, [
                el("div", { class: "grow" }, [
                  el("strong", { text: `${item.symbol} × ${item.qty}` }),
                  el("small", { text: `${pct(item.change_pct)} · stop ${item.stop_loss ?? "–"} · target ${item.take_profit ?? "–"}` }),
                ]),
              ])
            )
          : [el("p", { class: "empty", text: "No open positions." })]),
      ]),
      ...(others.length ? [card("Recent orders", others.slice(0, 8).map(orderRow))] : []),
      card("Feed", feed.length ? feed.slice(-25).reverse().map((event) => el("p", { class: "small", text: `${ago(event.at)} · ${event.symbol ? `${event.symbol}: ` : ""}${event.text}` })) : [el("p", { class: "empty", text: "Nothing yet." })])
    );
  };

  const refresh = async () => {
    if (gone) return;
    try {
      const fresh = await pcCall(`/studio/api/phone/trading?after=${last}`, undefined, "GET", 30000);
      desk = fresh;
      feed = feed.concat(fresh.events || []).slice(-60);
      last = fresh.last || last;
      problem = "";
    } catch (error) {
      problem = error.message;
    }
    draw();
  };

  const loop = async () => {
    await refresh();
    if (!gone) timer = setTimeout(loop, REFRESH_MS);
  };
  draw();
  loop();
  return () => {
    gone = true;
    clearTimeout(timer);
  };
}
