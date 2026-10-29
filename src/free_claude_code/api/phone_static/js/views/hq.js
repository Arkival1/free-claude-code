// HQ: your PC's team as a little office, like the HQ on the PC. Every part of
// the work is a station; each agent stands at the station of the tool it is
// using (glowing while it works) and goes to the break room between jobs.
// Tap an agent to see what it's doing and tell it something.
import { state } from "../state.js";
import { el, button, card, go, notify, ago, meter, openSheet, closeSheet } from "../ui.js";
import { pcCall } from "../sync.js";

const REFRESH_MS = 5000;

const initials = (name) => String(name || "?").split(/\s+/).map((part) => part[0] || "").join("").slice(0, 2).toUpperCase();

function agentSheet(agent) {
  const text = el("textarea", { "aria-label": `Message for ${agent.name}`, rows: 3, placeholder: `Tell ${agent.name} what to do` });
  openSheet(agent.name, [
    el("p", { text: `${agent.role}${agent.main ? " · runs the team" : ""}${agent.subagent ? ` · subagent (${agent.active ? "on" : "off"})` : ""}` }),
    el("p", { class: "muted small", text: `Thinks with ${agent.model}${agent.local ? " on your PC" : " on a server"}` }),
    agent.busy ? el("p", { text: `Working${agent.tool ? ` with ${agent.tool}` : ""}${agent.task ? `: ${agent.task}` : ""}` }) : el("p", { class: "muted", text: "Free right now." }),
    agent.live ? el("p", { class: "small", text: `Writing: ${agent.live}` }) : null,
    text,
    button("Send", async () => {
      if (!text.value.trim()) return notify("Write something first.");
      try {
        await pcCall(`/studio/api/phone/hq/agents/${encodeURIComponent(agent.id)}/say`, { text: text.value.trim() });
        closeSheet();
        notify(`${agent.name} is on it, on your PC.`);
      } catch (error) {
        notify(error.message);
      }
    }, { class: "primary" }),
  ]);
}

export function render(view) {
  if (!state.settings.pc) {
    view.replaceChildren(
      card("HQ", [
        el("p", { text: "The HQ shows your PC's team at work. Pair this phone with your PC to see it." }),
        button("Pair with my PC", () => go("settings"), { class: "primary" }),
      ])
    );
    return null;
  }
  let hq = null;
  let problem = "";
  let timer = null;
  let gone = false;

  const draw = () => {
    if (gone) return;
    if (!hq) {
      view.replaceChildren(card("HQ", [el("p", { class: problem ? "warn" : "muted", text: problem || "Opening the office…" })]));
      return;
    }
    const agents = hq.agents || [];
    const at = (station) => agents.filter((agent) => agent.station === station);
    const busy = agents.filter((agent) => agent.busy).length;
    const tiles = (hq.stations || [])
      .filter((station) => at(station.id).length || station.count || station.note)
      .map((station) =>
        el("section", { class: "hq-station", "aria-label": station.name }, [
          el("strong", { text: station.name }),
          station.note ? el("small", { text: station.note }) : el("small", { text: station.what }),
          el("div", { class: "hq-people" }, at(station.id).map((agent) =>
            el("button", { class: `hq-person${agent.busy ? " busy" : ""}`, type: "button", onclick: () => agentSheet(agent), "aria-label": `${agent.name}: ${agent.busy ? "working" : "free"}` }, [
              el("span", { class: "hq-face", "aria-hidden": "true", text: initials(agent.name) }),
              el("span", { class: "small", text: agent.name }),
            ])
          )),
        ])
      );
    view.replaceChildren(
      card("The office", [
        el("p", { text: `${busy} of ${agents.length} agents working${problem ? "" : " · live"}` }),
        problem ? el("p", { class: "warn", text: problem }) : null,
        el("div", { class: "hq-map" }, tiles),
        ...(agents.some((agent) => agent.station === "approvals") || (hq.stations || []).some((s) => s.id === "approvals" && s.count)
          ? [el("p", { class: "muted small", text: "Commands waiting for your yes are answered on the PC." })]
          : []),
      ]),
      ...(hq.changer ? [card("The Changer", [el("p", { text: `${hq.changer.status}: ${hq.changer.request}` })])] : []),
      card("Jobs", (hq.plans || []).length ? hq.plans.map((task) =>
        el("button", { class: "item as-button", type: "button", onclick: () => go(`tasks/${task.id}`), "aria-label": `Open the job: ${task.goal}` }, [
          el("div", { class: "grow" }, [
            el("strong", { text: task.goal }),
            el("small", { text: `${task.running ? "working" : task.status} · ${task.done_steps}/${task.steps.length} steps` }),
            meter(task.steps.length ? task.done_steps / task.steps.length : 0),
          ]),
        ])
      ) : [el("p", { class: "empty", text: "No jobs right now. Start one on Tasks." })]),
      card("Newest steps", (hq.feed || []).length ? hq.feed.map((step) =>
        el("p", { class: "small", text: `${ago(step.at)} · ${step.agent}${step.tool ? ` (${step.tool})` : ""}: ${step.failed ? "failed: " : ""}${step.text}` })
      ) : [el("p", { class: "empty", text: "Nothing yet." })])
    );
  };

  const refresh = async () => {
    try {
      hq = await pcCall("/studio/api/phone/hq", undefined, "GET", 30000);
      problem = "";
    } catch (error) {
      problem = error.message;
    }
    draw();
    if (!gone) timer = setTimeout(refresh, REFRESH_MS);
  };
  draw();
  refresh();
  return () => {
    gone = true;
    clearTimeout(timer);
  };
}
