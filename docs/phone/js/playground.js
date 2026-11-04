// The Playground (FCC's Manus-like mode). One main AI does the job with its
// own hands, thinking on the phone's own model when one is ready; up to two
// advisers think alongside it (three AIs at once), a team meeting brings more
// in to advise (still two at a time), and none of them touches the work unless
// the user hands it to them. After the work the advisers check it and the main
// AI fixes what they found (up to three tries in all). Each AI then writes
// down what to keep in its own mind: a thought, a thinking pattern, a lesson.
import { state, agentById, jarvis, feed, ROLE_PROMPTS } from "./state.js";
import { runTask, COULDNT_FINISH } from "./agents.js";
import { think, pinBrain, brainReady } from "./brains.js";
import { remember } from "./tools.js";
import { projectById } from "./projects.js";

/** Advisers thinking at the same time as the main AI: three AIs at once. */
export const MAX_ADVISERS = 2;
/** Advisers in a team meeting (they take turns, two at a time). */
export const MAX_MEETING = 5;
/** The work, then up to two fixes. */
export const MAX_PASSES = 3;
const STEP_CHARS = 1500;
const LOOKS_GOOD = /\blooks good\b/i;

/** The main AI's hands: every tool that makes or finds things. */
export const HANDS_TOOLS = [
  "start_project",
  "write_file",
  "read_file",
  "edit_file",
  "list_files",
  "delete_file",
  "check_project",
  "restore_file",
  "find_images",
  "polish_check",
  "look_at_site",
  "list_photos",
  "use_photo",
  "remember",
  "recall",
  "calculate",
  "weather",
  "wikipedia",
  "read_page",
  "web_search",
  "todo",
  "skill",
  "use_plugin",
  "ask_agent",
];
/** Advisers look and think; they never change anything. */
export const ADVISER_TOOLS = [
  "recall",
  "calculate",
  "weather",
  "wikipedia",
  "read_page",
  "web_search",
  "skill",
  "use_plugin",
  "list_files",
  "read_file",
  "check_project",
  "look_at_site",
  "polish_check",
  "list_photos",
];

export const HANDS_PROMPT =
  "You are the main AI in the user's Playground, and you are the hands: you do the whole job yourself, start to finish, with your tools (research, plans, writing, code, websites, games). Your advisers only advise: weigh what they say, use what helps, and decide yourself; ask one with ask_agent when you want advice mid-job. Work in the user's image: their ideas and taste come first, and when they say what they like, keep it with remember (kind taste). When a job makes files, use the current project or start_project, write complete files, then check_project and look_at_site and fix what they find. Read a skill when a job needs depth (game-design before a game, web-design-engineer or frontend-design for a look). Finish by saying what you made and where.";

export const ADVISER_PROMPT =
  "You are an adviser in the user's Playground. The main AI does the work with its own hands; you never change files or do the job yourself. Think it through, look things up or read the project with your tools when it helps, and give advice the main AI can act on: short, specific, the most important first.";

const REFLECT =
  'You just took part in a job in the user\'s Playground. Write down what to keep in your own mind, as JSON only: {"thought": "one thing you are still thinking about after this job", "pattern": "a way of working that went well and that you will use again", "lesson": "a mistake or surprise to remember next time"}. Leave a field empty when there is nothing worth keeping.';

/** Advisers that fit a job: testers and researchers for things to build,
 * researchers and planners for the rest. The main AI is never its own adviser. */
export function pickAdvisers(goal, handsId, count = MAX_ADVISERS) {
  const making = /\b(game|site|website|web|app|page|code|build|make|design|shop|landing)\b/i.test(goal);
  const order = making ? ["tester", "researcher", "helper", "builder", "main"] : ["researcher", "helper", "tester", "builder", "main"];
  const rank = (agent) => {
    const index = order.indexOf(agent.role);
    return index === -1 ? order.length : index;
  };
  return state.agents
    .filter((agent) => agent.id !== handsId)
    .sort((a, b) => rank(a) - rank(b))
    .slice(0, count)
    .map((agent) => agent.id);
}

/** Run fn over the items with at most `size` running at once. If one fails
 * (or the job is stopped), no new one starts, the ones running finish, and
 * then the first error is thrown. */
export async function inTurns(items, size, fn) {
  const results = new Array(items.length);
  let next = 0;
  let failure = null;
  const lane = async () => {
    while (next < items.length && !failure) {
      const index = next;
      next += 1;
      try {
        results[index] = await fn(items[index], index);
      } catch (error) {
        failure = failure || error;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.max(0, Math.min(size, items.length)) }, lane));
  if (failure) throw failure;
  return results;
}

class Stopped extends Error {}

function stepFor(task, stage, pass, agent, what) {
  let step = task.steps.find((item) => item.stage === stage && item.pass === pass && item.agent_id === agent.id);
  if (!step) {
    step = { id: `s${task.steps.length + 1}`, stage, pass, agent: agent.name, agent_id: agent.id, do: what, plugin: "", status: "waiting", result: "" };
    task.steps.push(step);
  }
  return step;
}

/** Run one step unless it is already done (a job that runs again picks up
 * where it stopped). Returns the step's result. */
async function runStep(task, step, saveTasks, fn) {
  if (step.status === "done") return step.result;
  if (task.stopping) throw new Stopped();
  step.status = "running";
  task.updated_at = Date.now();
  await saveTasks();
  const result = String(await fn());
  step.status = result.startsWith(`${step.agent} ${COULDNT_FINISH}`) ? "failed" : "done";
  step.result = result.slice(0, STEP_CHARS);
  task.updated_at = Date.now();
  await saveTasks();
  return step.result;
}

const filesOf = (project) => (project ? Object.keys(project.files) : []);

function adviseBrief(task, hands, project, what) {
  const files = filesOf(project);
  return [
    what,
    `The job: ${task.goal}`,
    `The main AI doing it: ${hands.name}.`,
    project ? `The project: ${project.name} (files: ${files.length ? files.join(", ") : "none yet"}).` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

/** One adviser's turn: advice only, with read-only tools. */
function advise(adviser, hands, project, brief) {
  return runTask(adviser, brief, {
    project,
    by: hands.name,
    chain: [hands.id],
    tools: ADVISER_TOOLS,
    instructions: `${ADVISER_PROMPT}\n\n${adviser.instructions || ""}`.trim(),
    maxRounds: 4,
  });
}

/** The main AI asked an agent for advice mid-job (ask_agent in the
 * Playground): the agent answers with advice and never takes the work over. */
export function consult(from, worker, question, ctx) {
  return runTask(worker, `Advice wanted by ${from.name}, who is doing the job with its own hands: ${question}\n\nAnswer with advice only.`, {
    project: ctx.project,
    depth: (ctx.depth || 0) + 1,
    chain: ctx.chain || [from.id],
    by: from.name,
    tools: ADVISER_TOOLS,
    instructions: `${ADVISER_PROMPT}\n\n${worker.instructions || ""}`.trim(),
    maxRounds: 4,
  });
}

function notes(steps) {
  return steps
    .filter((step) => step && step.status === "done" && step.result)
    .map((step) => `- ${step.agent}: ${step.result.replace(/^\S+ finished(?: \(project [^)]*\))?: /, "")}`)
    .join("\n");
}

function handsBrief(task, project, pass, advice) {
  const parts = [
    pass === 1 ? task.goal : `Fix what your advisers found, then check again. The job: ${task.goal}`,
    project ? `Work in the project ${project.name}.` : "If the job makes files, start a project with start_project.",
    advice ? `${pass === 1 ? "Your advisers said" : "Your advisers found"}:\n${advice}\nUse what helps; you decide.` : "",
  ];
  return parts.filter(Boolean).join("\n\n");
}

async function reflect(agent, task, story) {
  try {
    const reply = await think(agent, REFLECT, [{ role: "user", content: `The job: ${task.goal}\n\nWhat happened:\n${story.slice(-3000)}` }], [], { maxTokens: 300 });
    const found = String(reply.text || "").match(/\{[\s\S]*\}/);
    const parsed = JSON.parse(found ? found[0] : "{}");
    for (const kind of ["thought", "pattern", "lesson"]) {
      if (typeof parsed[kind] === "string" && parsed[kind].trim()) await remember(agent, parsed[kind], { kind });
    }
  } catch {
    // Nothing worth keeping, or a brain that couldn't answer: the job is done either way.
  }
}

/** Run (or pick up) a Playground job. Saves as it goes; sets the job's status. */
export async function runPlayground(task, saveTasks) {
  const hands = agentById(task.hands) || jarvis();
  task.hands = hands.id;
  const advisers = (task.advisers || []).map(agentById).filter((agent) => agent && agent.id !== hands.id);
  // The main AI thinks on this phone's own model when one is ready, unless
  // the user turned that off; the job keeps that brain to the end.
  const unpin = pinBrain(hands, state.settings.playgroundLocal !== false && brainReady("local") ? "local" : "");
  task.status = "working";
  task.updated_at = Date.now();
  await saveTasks();
  try {
    let project = task.project_id ? projectById(task.project_id) || null : null;
    // 1. The advisers advise before the work (a team meeting: everyone, two at a time).
    const kickoff = advisers.map((adviser) => stepFor(task, "kickoff", 0, adviser, "Advise before the work"));
    const kickoffBrief = adviseBrief(task, hands, project, "Advise the main AI before it starts: the best approach, what would make the result great, and one thing to watch out for. At most six short lines.");
    await inTurns(kickoff, MAX_ADVISERS, (step, index) => runStep(task, step, saveTasks, () => advise(advisers[index], hands, project, kickoffBrief)));
    let advice = notes(kickoff);
    const reviewers = advisers.slice(0, MAX_ADVISERS);
    let clean = !reviewers.length;
    for (let pass = 1; pass <= MAX_PASSES; pass += 1) {
      // 2. The main AI does the job (or fixes it) with its own hands.
      const work = stepFor(task, "work", pass, hands, pass === 1 ? "Do the job" : "Fix what the advisers found");
      const report = {};
      await runStep(task, work, saveTasks, () =>
        runTask(hands, handsBrief(task, project, pass, advice), {
          project,
          by: "you",
          tools: HANDS_TOOLS,
          instructions: `${HANDS_PROMPT}\n\nHow to build sites and games well:\n${hands.role === "builder" ? hands.instructions : ROLE_PROMPTS.builder}`,
          maxRounds: 30,
          maxTokens: 4000,
          consult: true,
          report,
        })
      );
      if (report.ctx && report.ctx.project) {
        project = report.ctx.project;
        task.project_id = project.id;
      }
      if (work.status === "failed") throw new Error(work.result);
      if (!reviewers.length) break;
      // 3. The advisers check the work.
      const reviews = reviewers.map((adviser) => stepFor(task, "review", pass, adviser, "Check the work"));
      const reviewBrief = adviseBrief(
        task,
        hands,
        project,
        `The main AI says it finished:\n${work.result}\n\nCheck the work against the job (read the files, run check_project or look_at_site when it helps). If it is good, answer exactly: LOOKS GOOD. Otherwise list what to fix, most important first, at most five lines.`
      );
      await inTurns(reviews, MAX_ADVISERS, (step, index) => runStep(task, step, saveTasks, () => advise(reviewers[index], hands, project, reviewBrief)));
      clean = reviews.every((step) => step.status !== "done" || LOOKS_GOOD.test(step.result));
      if (clean) break;
      advice = notes(reviews.filter((step) => !LOOKS_GOOD.test(step.result)));
    }
    // 4. Each AI keeps what it learned in its own mind.
    const story = task.steps.map((step) => `${step.agent} (${step.do}): ${step.result.slice(0, 400)}`).join("\n");
    for (const agent of [hands, ...advisers.slice(0, MAX_ADVISERS)]) await reflect(agent, task, story);
    const made = project ? ` Project: ${project.name} (${filesOf(project).length} files).` : "";
    const last = [...task.steps].reverse().find((step) => step.stage === "work" && step.status === "done");
    task.status = "done";
    task.summary = `${clean ? "Done" : "Done, with notes the advisers still had"}.${made}\n${last ? last.result : ""}`.trim();
    feed(hands.name, `Finished in the Playground: ${task.goal.slice(0, 80)}`, "done");
  } catch (error) {
    if (error instanceof Stopped || task.stopping) {
      task.status = "stopped";
      task.summary = `Stopped. ${task.steps.filter((step) => step.status === "done").length} of ${task.steps.length} step(s) done; Run again picks up from there.`;
    } else {
      task.status = "failed";
      task.summary = `Couldn't finish it: ${error.message}`;
      feed(hands.name, task.summary, "error");
    }
  } finally {
    unpin();
    task.updated_at = Date.now();
    await saveTasks();
  }
}

/** Start a Playground job: who does the work (the main AI unless the user
 * handed it to another agent), who advises, and the project to work in. */
export async function startPlayground(goal, { hands = "", advisers = "auto", project = "" } = {}) {
  const { startTask } = await import("./tasks.js");
  const doer = agentById(hands) || jarvis();
  const count = advisers === "meeting" ? MAX_MEETING : advisers === "none" ? 0 : MAX_ADVISERS;
  const picked = Array.isArray(advisers) ? advisers.filter((id) => id !== doer.id && agentById(id)).slice(0, MAX_MEETING) : pickAdvisers(goal, doer.id, count);
  return startTask(goal, "you", { kind: "playground", status: "working", hands: doer.id, advisers: picked, meeting: advisers === "meeting", project_id: project || "" });
}
