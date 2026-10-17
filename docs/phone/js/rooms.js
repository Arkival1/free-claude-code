// Rooms: you and several agents in one conversation. Write @Name to talk to
// one; otherwise everyone answers in turn. A goal lets them work it through.
import { state, save, changed, feed, agentById, agentByName } from "./state.js";
import { think } from "./brains.js";
import { uid } from "./ui.js";

const MAX_TASK_TURNS = 8;
const running = new Set();

export const roomById = (id) => state.rooms.find((room) => room.id === id);

export async function createRoom(title, memberIds) {
  const members = memberIds.filter((id) => agentById(id));
  if (!members.length) throw new Error("Pick at least one agent.");
  const room = {
    id: uid(),
    title: (title || members.map((id) => agentById(id).name).join(" & ")).slice(0, 60),
    members,
    messages: [],
    goal: "",
    status: "idle",
    created_at: Date.now(),
  };
  state.rooms.unshift(room);
  await save.rooms();
  changed("rooms");
  return room;
}

async function post(room, author, text, kind = "agent") {
  room.messages.push({ author, text, kind, at: Date.now() });
  if (room.messages.length > 300) room.messages.splice(0, room.messages.length - 300);
  await save.rooms();
  changed(`room:${room.id}`);
}

function transcript(room, limit = 24) {
  return room.messages
    .slice(-limit)
    .map((message) => `${message.author}: ${message.text}`)
    .join("\n");
}

async function speak(room, agent, extra = "") {
  const others = room.members.filter((id) => id !== agent.id).map((id) => agentById(id)?.name).filter(Boolean);
  const system = [
    `You are ${agent.name} (${agent.role}) in a group chat with the user${others.length ? ` and ${others.join(", ")}` : ""}.`,
    agent.instructions,
    "Reply with just your message: short, in your own voice, building on what others said. Write @Name to hand a question to another agent.",
    extra,
  ]
    .filter(Boolean)
    .join("\n\n");
  const reply = await think(agent, system, [{ role: "user", content: `The chat so far:\n${transcript(room)}\n\nYour turn, ${agent.name}.` }], [], { maxTokens: 700 });
  const text = (reply.text || "…").replace(new RegExp(`^${agent.name}:\\s*`, "i"), "");
  await post(room, agent.name, text);
  return text;
}

/** You wrote in the room: whoever you named answers, or everyone in turn. */
export async function say(room, text) {
  await post(room, "You", text, "user");
  const named = [...text.matchAll(/@([A-Za-z][\w-]*)/g)].map((match) => agentByName(match[1])).filter((agent) => agent && room.members.includes(agent.id));
  const speakers = named.length ? named : room.members.map((id) => agentById(id)).filter(Boolean);
  for (const agent of speakers) {
    try {
      const said = await speak(room, agent);
      const handed = [...said.matchAll(/@([A-Za-z][\w-]*)/g)]
        .map((match) => agentByName(match[1]))
        .find((next) => next && next.id !== agent.id && room.members.includes(next.id) && !speakers.includes(next));
      if (handed) await speak(room, handed);
    } catch (error) {
      await post(room, agent.name, `(couldn't answer: ${error.message})`, "error");
    }
  }
}

/** Give the room a goal: the first member leads, and they work until done. */
export async function startTask(room, goal) {
  room.goal = goal.trim();
  room.status = "working";
  running.add(room.id);
  await post(room, "You", `Goal: ${room.goal}`, "goal");
  feed(room.title, `The room started on: ${room.goal.slice(0, 90)}`, "start");
  const members = room.members.map((id) => agentById(id)).filter(Boolean);
  try {
    for (let turn = 0; turn < MAX_TASK_TURNS && running.has(room.id); turn += 1) {
      const agent = members[turn % members.length];
      const said = await speak(
        room,
        agent,
        `The room's goal: ${room.goal}\n${turn === 0 ? "You lead: plan the steps and hand parts to the others with @Name." : "Do your part."} When the goal is fully met, start your message with TASK COMPLETE: and a summary.`
      );
      if (/^TASK COMPLETE:/i.test(said.trim())) {
        room.status = "done";
        feed(room.title, `Done: ${said.slice(14, 120)}`, "done");
        return;
      }
    }
    room.status = running.has(room.id) ? "paused" : "stopped";
    await post(room, "Studio", room.status === "paused" ? `Paused after ${MAX_TASK_TURNS} turns so the agents don't loop. Write to carry on.` : "Stopped.", "event");
  } catch (error) {
    room.status = "failed";
    await post(room, "Studio", `Stopped: ${error.message}`, "error");
  } finally {
    running.delete(room.id);
    await save.rooms();
    changed("rooms");
  }
}

export async function stopRoom(room) {
  running.delete(room.id);
  room.status = "stopped";
  await save.rooms();
  changed("rooms");
}

export async function deleteRoom(room) {
  running.delete(room.id);
  state.rooms = state.rooms.filter((item) => item.id !== room.id);
  await save.rooms();
  changed("rooms");
}
