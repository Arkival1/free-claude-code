// Tasks on the phone itself, like Manus: Jarvis plans a whole job into steps,
// picks the plugin each step needs from the catalog, and his agents do the
// steps one at a time with their tools. Everything runs on the phone's own
// brains (a model on the phone, or a cloud key); no PC needed.
import { state, save, changed, feed, jarvis, agentByName } from "./state.js";
import { think } from "./brains.js";
import { runTask } from "./agents.js";
import { findPlugins } from "./plugins.js";
import { uid } from "./ui.js";

const MAX_STEPS = 6;
const STEP_RESULT_CHARS = 1500;

export const PLANNER =
  "You are Jarvis, planning a job for your team. Split it into 1 to 6 steps, in order. Give each step to the agent whose role fits it best, and when a step needs outside data, name the plugin from the list that fits it best (or none). Answer with JSON only, like " +
  '{"steps": [{"agent": "Researcher", "do": "what to do", "plugin": "Open-Meteo"}]}.';

export const REVIEWER =
  "You are Jarvis, checking a job between steps. Read what the steps found so far and the steps still to come. If the plan still fits, answer {\"next\": \"continue\"}. If what was found changes what should happen next, answer with the new remaining steps instead, like " +
  '{"steps": [{"agent": "Builder", "do": "what to do", "plugin": ""}]}. JSON only.';
const MAX_TOTAL_STEPS = 8;

const running = new Set();

function teamLines() {
  return state.agents.map((agent) => `- ${agent.name} (${agent.role}): ${(agent.tools || []).slice(0, 12).join(", ")}`).join("\n");
}

/** Read the planner's steps; anything unusable becomes one step for Jarvis. */
export function parseSteps(text, goal) {
  const found = String(text || "").match(/\{[\s\S]*\}/);
  let steps = [];
  try {
    const parsed = JSON.parse(found ? found[0] : "{}");
    steps = Array.isArray(parsed.steps) ? parsed.steps : [];
  } catch {
    steps = [];
  }
  const clean = steps
    .filter((step) => step && typeof step === "object" && String(step.do || "").trim())
    .slice(0, MAX_STEPS)
    .map((step, index) => {
      const agent = agentByName(String(step.agent || "")) || jarvis();
      return {
        id: `s${index + 1}`,
        agent: agent.name,
        do: String(step.do).trim().slice(0, 400),
        plugin: String(step.plugin || "").trim().slice(0, 80),
        status: "waiting",
        result: "",
      };
    });
  return clean.length ? clean : [{ id: "s1", agent: jarvis().name, do: goal, plugin: "", status: "waiting", result: "" }];
}

async function plan(task) {
  const plugins = findPlugins(task.goal, 8);
  const pluginLines = plugins.length
    ? plugins.map((item) => `- ${item.name}: ${item.about} (${item.on ? "switched on" : "off"}${item.needsKey ? ", needs a key" : ""})`).join("\n")
    : "- (none fit)";
  const reply = await think(
    jarvis(),
    PLANNER,
    [{ role: "user", content: `The job: ${task.goal}\n\nYour team:\n${teamLines()}\n\nPlugins that might help:\n${pluginLines}` }],
    [],
    { maxTokens: 700 }
  );
  return parseSteps(reply.text, task.goal);
}

/** Between steps Jarvis looks at what was found and keeps or changes the
 * steps still to come (like Manus re-planning as it learns). */
async function review(task, done) {
  const left = task.steps.filter((step) => step.status === "waiting");
  if (!left.length) return;
  const room = MAX_TOTAL_STEPS - task.steps.filter((step) => step.status !== "waiting").length;
  if (room <= 0) return;
  let reply;
  try {
    reply = await think(
      jarvis(),
      REVIEWER,
      [
        {
          role: "user",
          content: `The job: ${task.goal}\n\nFound so far:\n${done.join("\n").slice(-3000)}\n\nStill to come:\n${left.map((step) => `- ${step.agent}: ${step.do}`).join("\n")}\n\nYour team:\n${teamLines()}`,
        },
      ],
      [],
      { maxTokens: 500 }
    );
  } catch {
    return; // Can't check: keep the plan.
  }
  const text = String(reply.text || "");
  if (!/"steps"\s*:/.test(text)) return;
  const fresh = parseSteps(text, task.goal).slice(0, room);
  const kept = task.steps.filter((step) => step.status !== "waiting");
  task.steps = [...kept, ...fresh.map((step, index) => ({ ...step, id: `s${kept.length + index + 1}` }))];
  task.replanned = (task.replanned || 0) + 1;
  feed("Jarvis", `Changed the plan for: ${task.goal.slice(0, 80)}`, "tool");
}

function saveTasks() {
  changed("tasks");
  return save.tasks();
}

/** Start a job on the phone: plan it, then run its steps in the background. */
export async function startTask(goal, by = "you") {
  const clean = String(goal || "").trim();
  if (!clean) throw new Error("Say what the job is first.");
  const task = { id: uid(), goal: clean.slice(0, 2000), by, status: "planning", steps: [], summary: "", created_at: Date.now(), updated_at: Date.now() };
  state.tasks.unshift(task);
  state.tasks.length = Math.min(state.tasks.length, 30);
  await saveTasks();
  feed("Jarvis", `Planning: ${task.goal.slice(0, 90)}`, "start");
  work(task);
  return task;
}

/** Go again from the first step that isn't done. */
export function resumeTask(id) {
  const task = state.tasks.find((item) => item.id === id);
  if (!task) throw new Error("That job is gone.");
  if (running.has(task.id)) return task;
  task.status = task.steps.length ? "working" : "planning";
  for (const step of task.steps) if (step.status !== "done") step.status = "waiting";
  work(task);
  return task;
}

/** Stop after the step that is running now. */
export function stopTask(id) {
  const task = state.tasks.find((item) => item.id === id);
  if (!task) throw new Error("That job is gone.");
  task.stopping = true;
  return task;
}

async function work(task) {
  running.add(task.id);
  task.stopping = false;
  try {
    if (!task.steps.length) {
      task.steps = await plan(task);
      task.status = "working";
      task.updated_at = Date.now();
      await saveTasks();
    }
    const done = [];
    // The list can change as Jarvis re-plans, so walk it by position.
    for (let index = 0; index < task.steps.length; index += 1) {
      const step = task.steps[index];
      if (step.status === "done") {
        done.push(`${step.agent}: ${step.result}`);
        continue;
      }
      if (task.stopping) break;
      const agent = agentByName(step.agent) || jarvis();
      step.status = "running";
      task.updated_at = Date.now();
      await saveTasks();
      const brief = [
        step.do,
        `The whole job: ${task.goal}`,
        done.length ? `What the earlier steps found:\n${done.join("\n").slice(-3000)}` : "",
        step.plugin ? `Jarvis picked the plugin ${step.plugin} for this: use use_plugin (find, then call) if it helps.` : "",
      ]
        .filter(Boolean)
        .join("\n\n");
      const result = await runTask(agent, brief, { by: "Jarvis", chain: [jarvis().id] });
      const failed = result.startsWith(`${agent.name} couldn't finish`);
      step.status = failed ? "failed" : "done";
      step.result = result.slice(0, STEP_RESULT_CHARS);
      task.updated_at = Date.now();
      await saveTasks();
      if (failed) break;
      done.push(`${step.agent}: ${step.result}`);
      if (!task.stopping) {
        await review(task, done);
        await saveTasks();
      }
    }
    const all = task.steps.every((step) => step.status === "done");
    task.status = all ? "done" : task.stopping ? "stopped" : "failed";
    task.summary = all
      ? `Done: ${task.steps.length} step(s).\n${done.join("\n").slice(-3000)}`
      : `${task.steps.filter((step) => step.status === "done").length} of ${task.steps.length} step(s) done.`;
    feed("Jarvis", `${all ? "Finished" : "Stopped"}: ${task.goal.slice(0, 90)}`, all ? "done" : "error");
  } catch (error) {
    task.status = "failed";
    task.summary = `Couldn't plan or run it: ${error.message}`;
    feed("Jarvis", task.summary, "error");
  } finally {
    task.stopping = false;
    task.updated_at = Date.now();
    running.delete(task.id);
    await saveTasks();
  }
}

export const isRunning = (task) => running.has(task.id);
