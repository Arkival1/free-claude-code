// How phone agents think, use tools, and hand work to each other.
import { state, save, chatOf, changed, feed, agentByName, toolsFor, MIND_KINDS } from "./state.js";
import { think, brainOf, isPrivate, pinBrain, PROVIDERS, modelOf } from "./brains.js";
import { specsFor, runTool, recall, setHooks, pcMemoryAllowed, canRead } from "./tools.js";
import { startStudy } from "./learn.js";
import { words } from "./ui.js";
import { benchNow, benchBusy } from "./workshop.js";

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
    ctx.instructions || agent.instructions || "",
    `You run inside FCC Phone on the user's iPhone. It is ${now.toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })}.`,
    `Your tools: ${toolsFor(agent, ctx).join(", ") || "none"}. Use a tool whenever it gives a better answer than guessing. Keep replies short and easy to read on a phone.`,
    "Hold what you make to a business level: polished, complete, and ready for a real business to use, never a rough draft or a placeholder.",
  ];
  if (agent.role === "main") {
    const team = state.agents.filter((item) => item.id !== agent.id).map((item) => `${item.name} (${item.role})`);
    if (team.length) parts.push(`Your team on this phone: ${team.join(", ")}.`);
    if (toolsFor(agent, ctx).includes("lab")) {
      parts.push("The Lab is yours to work in person: when the user asks you to mix, wire, build or invent something, or to save, reload or improve a chip, mixture, invention or blueprint, do it yourself with the lab tool (you walk to that room in the Lab box). Don't hand Lab work to another agent. The benches are shared: build on what the user has there (lab add or remove) unless they ask for something new.");
      // What the user is working on in the Lab, so "what do you think of my circuit?" just works.
      if (benchBusy()) parts.push(`The Lab benches right now (lab look gives the full readout):\n${benchNow({ full: false, steps: 5 })}`);
    }
  }
  if (ctx.project) {
    const files = Object.keys(ctx.project.files);
    parts.push(`Current project: ${ctx.project.name}. Files: ${files.length ? files.join(", ") : "none yet"}.`);
  }
  // The AI's own mind: the few notes from its advice book, lessons and
  // patterns that fit this job (found by search, never all of them), then the
  // user's taste, which every AI follows.
  const mind = mindNotes(agent, question);
  if (mind.length) parts.push(`Your own notes that fit this job (advice you were given, lessons, ways that work; recall with a kind finds more):\n${mind.map((memory) => `- ${memory.text}`).join("\n")}`);
  const taste = state.memories.filter((memory) => memory.kind === "taste").slice(0, 8);
  if (taste.length) parts.push(`The user's taste (make things in their image):\n${taste.map((memory) => `- ${memory.text}`).join("\n")}`);
  const shown = new Set([...mind, ...taste].map((memory) => memory.text));
  const relevant = recall(agent, question, 6).filter((row) => !shown.has(row.text));
  const recent = state.memories
    .filter((memory) => canRead(agent, memory) && !MIND_KINDS.has(memory.kind) && memory.kind !== "taste")
    .slice(0, 4)
    .filter((memory) => !relevant.some((row) => row.text === memory.text));
  const lines = [...relevant.map((row) => `- ${row.text}${row.from ? ` (${row.from})` : ""}`), ...recent.map((memory) => `- ${memory.text}`)];
  if (lines.length) parts.push(`What you remember (use it when it helps):\n${lines.join("\n")}`);
  return parts.filter(Boolean).join("\n\n");
}

/** The notes in an AI's own mind (advice book, lessons, patterns) that share
 * the most words with the job; with no match, its newest few patterns and
 * lessons. Mini notes only, so the prompt stays small. */
export function mindNotes(agent, question, limit = 5) {
  const own = state.memories.filter((memory) => memory.agent_id === agent.id && ["advice", "lesson", "pattern"].includes(memory.kind));
  const terms = new Set(words(question));
  const scored = own
    .map((memory) => [words(memory.text).reduce((sum, word) => sum + (terms.has(word) ? 1 : 0), 0), memory])
    .filter(([score]) => score > 0)
    .sort((a, b) => b[0] - a[0] || b[1].created_at - a[1].created_at)
    .map(([, memory]) => memory);
  const picked = scored.length ? scored : own.filter((memory) => memory.kind !== "advice");
  return picked.slice(0, limit);
}

async function addTurn(agent, turn) {
  const chat = await chatOf(agent.id);
  chat.push({ ...turn, at: Date.now() });
  if (chat.length > 400) chat.splice(0, chat.length - 400);
  await save.chat(agent.id);
  changed(`chat:${agent.id}`);
}

/** A message from an agent in its chat with the user (e.g. Jarvis's practice notes). */
export const tell = (agent, text) => addTurn(agent, { role: "assistant", text });

// Tools that change a project's files: a turn that used one hands the
// project over to download, like a file in a chat.
const BUILDING_TOOLS = new Set(["start_project", "write_file", "edit_file", "delete_file", "use_photo", "restore_file"]);

function noteBuilt(ctx, call) {
  if (BUILDING_TOOLS.has(call.name) && ctx.project) ctx.built.add(ctx.project.id);
}

/** Put a download card for each project built in the agent's chat, unless
 * the chat already offers it unchanged. */
async function handOver(agent, projectIds) {
  if (!agent || !projectIds.size) return;
  const { projectById } = await import("./projects.js");
  const chat = await chatOf(agent.id);
  for (const id of projectIds) {
    const project = projectById(id);
    if (!project) continue;
    const names = Object.keys(project.files);
    if (!names.length) continue;
    const bytes = names.reduce((sum, name) => sum + new TextEncoder().encode(String(project.files[name])).length, 0);
    const offered = [...chat].reverse().find((turn) => turn.role === "download" && turn.project_id === id);
    if (offered && offered.files === names.length && offered.bytes === bytes) continue;
    await addTurn(agent, {
      role: "download",
      project_id: id,
      name: project.name,
      file_name: `${project.slug}.zip`,
      files: names.length,
      bytes,
      text: `${project.name} is ready to download.`,
    });
  }
}

async function history(agent) {
  const turns = (await chatOf(agent.id)).filter((turn) => turn.role === "user" || turn.role === "assistant");
  return turns.slice(-HISTORY_TURNS).map((turn) => ({ role: turn.role, content: turn.text }));
}

/** The tool loop: think, run the tools asked for, think again, until a reply. */
/** Tools whose answer doesn't change within one turn. */
/** Tools that can change a project's files (a job with any of them is a build
 * job, so FCC checks the project after it). */
const CHANGES_FILES = new Set(["start_project", "write_file", "edit_file", "delete_file", "restore_file", "use_photo", "game_art", "web_kit", "linux", "godot"]);
// recall isn't one: a teammate can save a shared memory mid-turn.
const LOOKUPS = new Set(["skill", "wikipedia", "read_page", "web_search", "library", "game_art", "find_images", "list_photos"]);

async function loop(agent, system, convo, ctx, { maxRounds, onTool }) {
  const tools = specsFor(agent, ctx);
  const seen = new Set();
  const maxTokens = ctx.maxTokens || (agent.role === "builder" ? 4000 : 1200);
  for (let round = 0; round < maxRounds; round += 1) {
    const reply = await think(agent, system, convo, round < maxRounds - 1 ? tools : [], { maxTokens });
    if (!reply.tool_calls.length) return reply.text || "(no answer)";
    convo.push({
      role: "assistant",
      content: reply.text || "",
      ...(reply.reasoning_content ? { reasoning_content: reply.reasoning_content } : {}),
      tool_calls: reply.tool_calls.map((call) => ({ id: call.id, type: "function", function: { name: call.name, arguments: JSON.stringify(call.arguments || {}) } })),
    });
    for (const call of reply.tool_calls) {
      // A look-up repeated word for word gives the same answer: say so
      // instead of fetching it again (small models go round in circles).
      const key = LOOKUPS.has(call.name) && !(call.name === "game_art" && call.arguments && call.arguments.action === "add") ? `${call.name}:${JSON.stringify(call.arguments || {})}` : "";
      const repeat = key && seen.has(key);
      if (key) seen.add(key);
      const result = repeat ? `You already did exactly this (${call.name}); its answer is above. Don't repeat it: use what you found and do the next step.` : await runTool(agent, call, ctx);
      if (onTool) await onTool(call, result);
      convo.push({ role: "tool", tool_call_id: call.id, content: result.slice(0, 16000) });
    }
  }
  return "I went round in circles there. Ask me again more simply?";
}

/** When the app starts, a message it closed on before answering gets a note
 * saying so (and why, when known) instead of silence. */
export async function markUnanswered(reason = "") {
  for (const agent of state.agents) {
    const chat = await chatOf(agent.id);
    const last = chat[chat.length - 1];
    if (!last || !["user", "tool", "task"].includes(last.role)) continue;
    await addTurn(agent, {
      role: "error",
      text: reason ? `No reply to your last message. ${reason}` : "No reply to your last message: the app closed before the answer came. Send it again.",
    });
  }
}

/** Answer one message in the agent's chat. */
export async function answer(agent, text, { project } = {}) {
  setBusy(agent, true);
  const unpin = pinBrain(agent);
  const ctx = { project: project || null, depth: 0, chain: [agent.id], built: new Set() };
  try {
    const convo = await history(agent);
    await addTurn(agent, { role: "user", text });
    convo.push({ role: "user", content: text });
    const said = await loop(agent, systemPrompt(agent, text, ctx), convo, ctx, {
      maxRounds: agent.role === "builder" ? 30 : 8,
      onTool: (call, result) => {
        noteBuilt(ctx, call);
        return addTurn(agent, { role: "tool", text: `${call.name}: ${result.split("\n")[0].slice(0, 180)}` });
      },
    });
    await addTurn(agent, { role: "assistant", text: said });
    await handOver(agent, ctx.built);
    return said;
  } catch (error) {
    await addTurn(agent, { role: "error", text: error.message });
    throw error;
  } finally {
    unpin();
    setBusy(agent, false);
  }
}

/** How a job that failed starts its report (Tasks reads it). */
export const COULDNT_FINISH = "couldn't finish";

/** A job done in the background: the agent works it through and reports.
 * A job can give the agent its own tools, instructions and step limit for
 * this one job (the Playground does), and a report object gets the job's
 * context (report.ctx), so the caller sees the project it worked in. With
 * consult, the agent's ask_agent only gets advice: the other agent never
 * takes the work over. With partsOnly (a Playground helper), it writes only
 * under parts/. */
export async function runTask(agent, goal, { project = null, depth = 0, chain = [], by = "you", tools = null, instructions = "", maxRounds = 0, maxTokens = 0, consult = false, partsOnly = false, report = null } = {}) {
  const job = { id: `${Date.now()}`, agent: agent.id, goal, by, status: "working", started_at: Date.now(), steps: 0, result: "" };
  state.jobs.unshift(job);
  state.jobs.length = Math.min(state.jobs.length, 30);
  setBusy(agent, true);
  const unpin = pinBrain(agent);
  feed(agent.name, `Started: ${goal.slice(0, 100)}`, "start");
  const ctx = { project, depth, chain: [...chain, agent.id], built: new Set(), tools, instructions, maxTokens, consult, partsOnly };
  if (report) report.ctx = ctx;
  try {
    await addTurn(agent, { role: "task", text: `Job from ${by}: ${goal}` });
    const result = await loop(agent, systemPrompt(agent, goal, ctx), [{ role: "user", content: goal }], ctx, {
      maxRounds: maxRounds || (agent.role === "builder" ? 30 : agent.role === "tester" ? 20 : 10),
      onTool: async (call, output) => {
        noteBuilt(ctx, call);
        job.steps += 1;
        feed(agent.name, `${call.name}: ${output.split("\n")[0].slice(0, 120)}`, "tool");
        await addTurn(agent, { role: "tool", text: `${call.name}: ${output.split("\n")[0].slice(0, 180)}` });
        changed("team");
      },
    });
    // FCC checks the project itself, so an agent can't report a job done
    // while the project still fails FCC's checks (small models do): the job's
    // own record, its feed line and the report all say so.
    // A check that breaks (say a file restored from an odd backup) keeps the
    // agent's work and handover, and says the check couldn't run.
    // Only for jobs that build: a helper's parts and an adviser's read-only
    // turn aren't the finished project.
    let still = "";
    let problems = [];
    const builds = !ctx.partsOnly && (!ctx.tools || ctx.tools.some((name) => CHANGES_FILES.has(name)));
    if (builds && ctx.project && Object.keys(ctx.project.files || {}).length) {
      try {
        const { checkProject } = await import("./projects.js");
        problems = checkProject(ctx.project).filter((problem) => !problem.startsWith("Note: "));
        if (problems.length) still = `\n\nFCC's own check of ${ctx.project.name} still finds ${problems.length} problem(s), so it isn't finished:\n${problems.slice(0, 6).map((problem) => `- ${problem}`).join("\n")}\nDon't tell the user it's done: have them fixed first.`;
      } catch (error) {
        still = `\n\nFCC couldn't check ${ctx.project.name} (${error.message}), so whether it works isn't known yet.`;
      }
    }
    if (report) report.problems = problems;
    job.status = problems.length ? "unfinished" : "done";
    job.result = `${result}${still}`;
    job.problems = Boolean(still);
    await addTurn(agent, { role: "assistant", text: `${result}${still}` });
    // The agent that did the work and every agent that handed the job down
    // (Jarvis included) get the app to download.
    for (const id of ctx.chain) await handOver(state.agents.find((item) => item.id === id), ctx.built);
    feed(agent.name, still ? `Finished, but FCC's check still finds problems in ${ctx.project.name}` : `Finished: ${result.split("\n")[0].slice(0, 120)}`, still ? "error" : "done");
    // The check comes first, so a long answer cut short never hides it.
    return `${agent.name} finished${ctx.project ? ` (project ${ctx.project.name})` : ""}: ${still ? `${still.trim()}\n\n` : ""}${result}`;
  } catch (error) {
    job.status = "failed";
    job.result = error.message;
    await addTurn(agent, { role: "error", text: error.message });
    feed(agent.name, `Stopped: ${error.message}`, "error");
    return `${agent.name} ${COULDNT_FINISH}: ${error.message}`;
  } finally {
    job.ended_at = Date.now();
    unpin();
    setBusy(agent, false);
  }
}

async function delegate(from, name, task, projectName, ctx) {
  const worker = agentByName(name);
  if (!worker) return `No agent called ${name}. The team: ${state.agents.map((agent) => agent.name).join(", ")}.`;
  if (worker.id === from.id) return "That's you: do it yourself.";
  if ((ctx.chain || []).includes(worker.id)) return `${worker.name} handed you this job, so don't hand it back: finish it and report, or say what is missing.`;
  if ((ctx.depth || 0) >= MAX_HANDOFF_DEPTH) return "This job has already been handed down twice, so do this part yourself.";
  // Agents on a cloud AI never direct the agents on this phone (or the PC),
  // which read the user's memory; those take jobs from Jarvis and each other.
  if (!isPrivate(from) && isPrivate(worker)) {
    return `${worker.name} thinks on this phone and takes jobs from Jarvis and the other agents here, not from agents on a cloud AI. Ask Jarvis if you need it.`;
  }
  if (isBusy(worker)) return `${worker.name} is busy with another job. Try again in a moment, or do it yourself.`;
  // In the Playground the main AI keeps the work: asking another agent gets
  // its advice, never its hands.
  if (ctx.consult) {
    const { consult } = await import("./playground.js");
    return consult(from, worker, task, ctx);
  }
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
