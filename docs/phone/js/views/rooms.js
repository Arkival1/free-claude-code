// Rooms: you and several agents in one conversation.
import { state, onChange, agentById } from "../state.js";
import { el, button, card, go, notify, ago } from "../ui.js";
import * as rooms from "../rooms.js";

export function render(view, id) {
  if (id) return renderRoom(view, id);
  const boxes = state.agents.map((agent) => [agent, el("input", { type: "checkbox", checked: agent.role !== "main", "aria-label": `${agent.name} in the room` })]);
  const title = el("input", { "aria-label": "Room name", placeholder: "Room name (optional)" });
  const draw = () =>
    view.replaceChildren(
      card("New room", [
        el("p", { class: "muted", text: "A group chat with several agents. Write @Name to talk to one; otherwise they answer in turn. Give the room a goal and they work it through together." }),
        title,
        el("div", { class: "tool-group" }, boxes.map(([agent, box]) => el("label", { class: "check" }, [box, el("span", { text: agent.name })]))),
        button("Open the room", async () => {
          try {
            const room = await rooms.createRoom(title.value.trim(), boxes.filter(([, box]) => box.checked).map(([agent]) => agent.id));
            go(`rooms/${room.id}`);
          } catch (error) {
            notify(error.message);
          }
        }, { class: "primary" }),
      ]),
      card(
        "Rooms",
        state.rooms.length
          ? state.rooms.map((room) =>
              el("button", { class: "item as-button", type: "button", onclick: () => go(`rooms/${room.id}`), "aria-label": `Open room ${room.title}` }, [
                el("div", { class: "grow" }, [
                  el("strong", { text: room.title }),
                  el("small", { text: `${room.members.map((member) => agentById(member)?.name).filter(Boolean).join(", ")} · ${room.status} · ${ago((room.messages.at(-1) || room).at || room.created_at)}` }),
                ]),
              ])
            )
          : [el("p", { class: "empty", text: "No rooms yet." })]
      )
    );
  draw();
  return onChange((what) => what === "rooms" && draw());
}

function renderRoom(view, id) {
  const room = rooms.roomById(id);
  if (!room) {
    go("rooms");
    return null;
  }
  const log = el("div", { class: "messages" });
  const input = el("textarea", { rows: 1, "aria-label": "Message the room", placeholder: "Message the agents… (@Name for one)" });
  let busy = false;
  const send = button("Send", async () => {
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    busy = true;
    send.disabled = true;
    try {
      await rooms.say(room, text);
    } finally {
      busy = false;
      send.disabled = false;
    }
  }, { class: "primary" });
  const goal = el("input", { "aria-label": "Room goal", placeholder: "Goal: plan and build a landing page for my bakery" });
  const draw = () => {
    log.replaceChildren(
      ...(room.messages.length
        ? room.messages.map((message) =>
            el("div", { class: `msg ${message.kind === "user" || message.kind === "goal" ? "user" : message.kind === "error" || message.kind === "event" ? "tool" : "assistant"}` }, [
              message.kind === "user" ? null : el("span", { class: "who", text: message.author }),
              message.text,
            ])
          )
        : [el("p", { class: "muted", text: "Say hello, or give the room a goal below." })])
    );
    requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight));
  };
  view.replaceChildren(
    card(room.title, [
      el("p", { class: "muted", text: `In the room: ${room.members.map((member) => agentById(member)?.name).filter(Boolean).join(", ")}` }),
      el("div", { class: "row" }, [
        el("div", { class: "grow" }, [goal]),
        button("Start task", () => {
          if (!goal.value.trim()) return notify("Give the room a goal.");
          rooms.startTask(room, goal.value.trim());
          goal.value = "";
        }),
        button("Stop", () => rooms.stopRoom(room)),
      ]),
    ]),
    log,
    el("div", { class: "composer" }, [input, send]),
    el("div", { class: "row end" }, [
      button("Delete room", async () => {
        if (!confirm("Delete this room?")) return;
        await rooms.deleteRoom(room);
        go("rooms");
      }, { class: "danger" }),
    ])
  );
  draw();
  return onChange((what) => (what === `room:${room.id}` || what === "rooms") && draw());
}
