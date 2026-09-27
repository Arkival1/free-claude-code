// How phone agents think, use tools, and hand work to each other.
import { state, save, chatOf, changed, feed, agentByName, toolsOf } from "./state.js";
import { think, brainOf, isPrivate, PROVIDERS, modelOf } from "./brains.js";
import { specsFor, runTool, recall, setHooks, pcMemoryAllowed } from "./tools.js";
import { startStudy } from "./learn.js";

const HISTORY_TURNS = 20;
const MAX_HANDOFF_DEPTH = 2;

export const isBusy = (agent) => state.busy.has(agent.id);

function setBusy(agent, busy) {
  if (busy) state.busy.add(agent.id);
  else state.busy.delete(agent.id);
  changed("team");
}

export function systemPrompt(agent, question, ctx = {}) {
  const now = new Date();
  const parts = [
    agent.role === "main" ? `You are ${agent.name}, the user's main AI.` : `You are ${agent.name}, one of the user's AI agents (${agent.role}).`,
    agent.instructions || "",
    `You run inside FCC Phone on the user's iPhone. It is ${now.toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })}.`,
    `Your tools: ${toolsOf(agent).join(", ") || "none"}. Use a tool whenever it gives a better answer than guessing. Keep replies short and easy to read on a phone.`,
  ];
  if (agent.role === "main") {
    const team = state.agents.filter((item) => item.id !== agent.id).map((item) => `${item.name} (${item.role})`);
    if (team.length) parts.push(`Your team on this phone: ${team.join(", ")}.`);
  }
  if (ctx.project) {
    const files = Object.keys(ctx.project.files);
    parts.push(`Current project: ${ctx.project.name}. Files: ${files.length ? files.join(", ") : "none yet"}.`);
  }
  const relevant = recall(agent, question, 6);
  const recent = state.memories.slice(0, 4).filter((memory) => !relevant.some((row) => row.text === memory.text));
  const lines = [...relevant.map((row) => `- ${row.text}${row.from ? ` (${row.from})` : ""}`), ...recent.map((memory) => `- ${memory.text}`)];
  if (lines.length) parts.push(`What you remember (use it when it helps):\n${lines.join("\n")}`);
  return parts.filter(Boolean).join("\n\n");
}

async function addTurn(agent, turn) {
  const chat = await chatOf(agent.id);
  chat.push({ ...turn, at: Date.now() });
  if (chat.length > 400) chat.splice(0, chat.length - 400);
  await save.chat(agent.id);
  changed(`chat:${agent.id}`);
}

async function history(agent) {
  const turns = (await chatOf(agent.id)).filter((turn) => turn.role === "user" || turn.role === "assistant");
  return turns.slice(-HISTORY_TURNS).map((turn) => ({ role: turn.role, content: turn.text }));
}

/** The tool loop: think, run the tools asked for, think again, until a reply. */
async function loop(agent, system, convo, ctx, { maxRounds, onTool }) {
  const tools = specsFor(agent);
  for (let round = 0; round < maxRounds; round += 1) {
    const reply = await think(agent, system, convo, round < maxRounds - 1 ? tools : [], { maxTokens: agent.role === "builder" ? 4000 : 1200 });
    if (!reply.tool_calls.length) return reply.text || "(no answer)";
    convo.push({
      role: "assistant",
      content: reply.text || "",
      tool_calls: reply.tool_calls.map((call) => ({ id: call.id, type: "function", function: { name: call.name, arguments: JSON.stringify(call.arguments || {}) } })),
    });
    for (const call of reply.tool_calls) {
      const result = await runTool(agent, call, ctx);
      if (onTool) await onTool(call, result);
      convo.push({ role: "tool", tool_call_id: call.id, content: result.slice(0, 16000) });
    }
  }
  return "I went round in circles there. Ask me again more simply?";
}

/** Answer one message in the agent's chat. */
export async function answer(agent, text, { project } = {}) {
  setBusy(agent, true);
  const convo = await history(agent);
  await addTurn(agent, { role: "user", text });
  convo.push({ role: "user", content: text });
  const ctx = { project: project || null, depth: 0, chain: [agent.id] };
  try {
    const said = await loop(agent, systemPrompt(agent, text, ctx), convo, ctx, {
      maxRounds: agent.role === "builder" ? 30 : 8,
      onTool: (call, result) => addTurn(agent, { role: "tool", text: `${call.name}: ${result.split("\n")[0].slice(0, 180)}` }),
    });
    await addTurn(agent, { role: "assistant", text: said });
    return said;
  } catch (error) {
    await addTurn(agent, { role: "error", text: error.message });
    throw error;
  } finally {
    setBusy(agent, false);
  }
}

/** A job done in the background: the agent works it through and reports. */
export async function runTask(agent, goal, { project = null, depth = 0, chain = [], by = "you" } = {}) {
  const job = { id: `${Date.now()}`, agent: agent.id, goal, by, status: "working", started_at: Date.now(), steps: 0, result: "" };
  state.jobs.unshift(job);
  state.jobs.length = Math.min(state.jobs.length, 30);
  setBusy(agent, true);
  feed(agent.name, `Started: ${goal.slice(0, 100)}`, "start");
  await addTurn(agent, { role: "task", text: `Job from ${by}: ${goal}` });
  const ctx = { project, depth, chain: [...chain, agent.id] };
  try {
    const result = await loop(agent, systemPrompt(agent, goal, ctx), [{ role: "user", content: goal }], ctx, {
      maxRounds: agent.role === "builder" ? 30 : agent.role === "tester" ? 20 : 10,
      onTool: async (call, output) => {
        job.steps += 1;
        feed(agent.name, `${call.name}: ${output.split("\n")[0].slice(0, 120)}`, "tool");
        await addTurn(agent, { role: "tool", text: `${call.name}: ${output.split("\n")[0].slice(0, 180)}` });
        changed("team");
      },
    });
    job.status = "done";
    job.result = result;
    await addTurn(agent, { role: "assistant", text: result });
    feed(agent.name, `Finished: ${result.split("\n")[0].slice(0, 120)}`, "done");
    return `${agent.name} finished${ctx.project ? ` (project ${ctx.project.name})` : ""}: ${result}`;
  } catch (error) {
    job.status = "failed";
    job.result = error.message;
    await addTurn(agent, { role: "error", text: error.message });
    feed(agent.name, `Stopped: ${error.message}`, "error");
    return `${agent.name} couldn't finish: ${error.message}`;
  } finally {
    job.ended_at = Date.now();
    setBusy(agent, false);
  }
}

async function delegate(from, name, task, projectName, ctx) {
  const worker = agentByName(name);
  if (!worker) return `No agent called ${name}. The team: ${state.agents.map((agent) => agent.name).join(", ")}.`;
  if (worker.id === from.id) return "That's you: do it yourself.";
  if ((ctx.chain || []).includes(worker.id)) return `${worker.name} handed you this job, so don't hand it back: finish it and report, or say what is missing.`;
  if ((ctx.depth || 0) >= MAX_HANDOFF_DEPTH) return "This job has already been handed down twice, so do this part yourself.";
  if (isBusy(worker)) return `${worker.name} is busy with another job. Try again in a moment, or do it yourself.`;
  let project = ctx.project;
  if (projectName) {
    const { findProject, createProject } = await import("./projects.js");
    project = findProject(projectName) || (await createProject(projectName, from.name));
  }
  return runTask(worker, task, { project, depth: (ctx.depth || 0) + 1, chain: ctx.chain || [from.id], by: from.name });
}

export function teamStatus() {
  const lines = state.agents.map((agent) => {
    const job = state.jobs.find((item) => item.agent === agent.id);
    const now = isBusy(agent) ? "working" : "idle";
    const last = job ? ` · last job: "${job.goal.slice(0, 60)}" (${job.status})` : "";
    return `- ${agent.name} (${agent.role}): ${now}, thinks with ${PROVIDERS[brainOf(agent)]?.label || "no brain yet"} ${modelOf(agent)}${last}`;
  });
  return lines.join("\n");
}

setHooks({
  delegate,
  teamStatus,
  learn: (topic, depth, by) => startStudy(topic, depth, by),
});

export { isPrivate, pcMemoryAllowed };
