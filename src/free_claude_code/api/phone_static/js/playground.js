// The Playground (FCC's Manus-like mode) makes two things, properly
// engineered: games and websites. One main AI does the job with its own
// hands, thinking on the phone's own model when one is ready. Up to two
// helpers physically help: each builds a part (content, pages, art, a
// playtest) in the same project, so three AIs work at once. Any number of
// advisers advise (two talk at a time), telling the main AI what to do and
// which of its tools to use; none of them takes the work over unless the
// user hands it to them. After the work the advisers check it and the main
// AI fixes what they found, three tries in all. The main AI keeps what the
// advisers told it in its advice book and what the fixes taught it as
// lessons, so it learns; every AI also writes down a thought, a thinking
// pattern and a lesson. A finished game or site goes to the library for the
// user to approve, and approved work becomes a reference for the next one.
import { state, agentById, jarvis, feed, ROLE_PROMPTS } from "./state.js";
import { runTask, COULDNT_FINISH } from "./agents.js";
import { think, pinBrain, brainReady } from "./brains.js";
import { remember } from "./tools.js";
import { projectById, createProject, checkProject } from "./projects.js";
import { addToLibrary } from "./library.js";

/** Helpers that build parts alongside the main AI: three AIs at once. */
export const MAX_HELPERS = 2;
/** Advisers talk two at a time; there is no limit on how many advise. */
export const MAX_ADVISERS = 2;
/** The work, then up to two fixes. */
export const MAX_PASSES = 3;
/** A note in an AI's memory stays short: a mini note, not an essay. */
export const MINI_NOTE = 220;
const STEP_CHARS = 1500;
/** An adviser's approval: the reply starts with LOOKS GOOD. */
export const LOOKS_GOOD = /^[\s*_"'`>-]*looks good\b/i;
/** Signs a reply that starts with LOOKS GOOD still asks for changes: a list,
 * or words like but, however, fix, missing. */
const STILL_WANTS = /(^|\n)\s*(\d+[.)]|[-*•])\s|\b(but|however|though|except|fix|missing|broken|should|needs?|add|change)\b/i;

/** Whether an adviser's own words approve the work: they start with LOOKS
 * GOOD and ask for nothing more. */
export const approves = (text) => {
  const words = String(text || "").trim();
  return LOOKS_GOOD.test(words) && !STILL_WANTS.test(words.replace(LOOKS_GOOD, ""));
};

/** The two things the Playground makes, and how each is engineered. */
export const KINDS = {
  website: {
    label: "Website",
    glyph: "⌘",
    placeholder: "A website for… (who it's for, what it sells, the feel you want)",
    engineering:
      "Website engineering, step by step. 1. Plan: who it is for, the one action they should take, the pages, the sections of each, and the look. Read web_kit guide, search the library (library tool) for approved references and recall the user's taste first. 2. Start: start_project, then web_kit page with the closest recipe (business, startup, studio, shop, service) or your own list of sections and a look (or start from a template or FCC design). 3. Build every page with real content (your helpers' parts are in parts/: read them with list_files and read_file and use them). 4. Check: check_project, look_at_site on a phone and a computer, polish_check; fix what they find. Make something original: take the feel of a reference, never copy it.",
  },
  game: {
    label: "Game",
    glyph: "◇",
    placeholder: "A game where… (the goal, the controls, the feel you want)",
    engineering:
      "Game engineering, step by step. When the user asks for Godot (or a Godot game), make it in Godot: read godot guide, start_project, godot start with the closest starter (action-3d, third-person-3d) or write the project yourself, then godot check and fix every error it shows until it says No errors; the user plays it from Projects. Otherwise, for a 3D game (3D, third-person, Souls-like, a boss fight, an open world), start_project with template game3d (it already plays: a warrior, a boss, a bonfire, fire and fog) and read the lab tool's guide; make it the user's world with the Lab kit, and make your own textures, shaders, models and animation the same way. For a 2D game: 1. Read the game-design skill, and search the library (library tool) for approved game references. 2. Design: one clear goal, a core loop that is fun in 30 seconds, touch controls first, rising difficulty, score and feedback on every hit. 3. Start from the game template (start_project with template game) and build it in game.js (your helpers' parts are in parts/: read them and use them). 4. Playtest with look_at_site, fix what breaks, and balance the difficulty. Draw original art (shapes, SVG, canvas); never copy someone else's game or art.",
  },
};

/** Games or websites: a job that talks about play is a game. */
export const kindOf = (goal) => (/\b(game|play|player|level|enemy|boss|score|shooter|platformer|puzzle|rpg|arcade|3d|souls|third-person|fps)\b/i.test(goal) ? "game" : "website");

/** The part each helper builds, by the job and the helper's role. */
const HELPER_PARTS = {
  website: {
    researcher: "Write the real content in parts/content.md: the names, headings, paragraphs, prices and opening hours, and photo links from find_images with their credits.",
    builder: "Build the extra pages the main AI won't start with (about, contact, gallery) as parts/pages/*.html in the same style, ready to move in.",
    tester: "Write parts/checks.md: what to try on a phone and a computer, then check what exists so far with check_project and note what breaks.",
    any: "Build one useful part of the site in your own file under parts/ and say what it is for.",
  },
  game: {
    researcher: "Write parts/design.md: the rules, the levels and the difficulty curve, using the game-design skill.",
    builder: "Make the game's art and sound in parts/art.js: drawn shapes and colours for the player, enemies and pick-ups, and short sound effects with the Web Audio API, as functions the main AI can call.",
    tester: "Write parts/playtest.md: what to try, then play what exists so far with look_at_site and note what breaks.",
    any: "Build one useful part of the game in your own file under parts/ and say what it is for.",
  },
};

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
  "wikipedia",
  "read_page",
  "web_search",
  "skill",
  "use_plugin",
  "library",
  "lab",
  "web_kit",
  "godot",
  "ask_agent",
];
/** Helpers build their part in the main AI's project; they never start a
 * project, delete files or hand work on. */
export const HELPER_TOOLS = [
  "write_file",
  "read_file",
  "edit_file",
  "list_files",
  "check_project",
  "find_images",
  "look_at_site",
  "list_photos",
  "recall",
  "calculate",
  "wikipedia",
  "read_page",
  "web_search",
  "skill",
  "use_plugin",
  "library",
  "lab",
  "web_kit",
  "godot",
];
/** Advisers look and think; they never change anything. */
export const ADVISER_TOOLS = [
  "recall",
  "calculate",
  "wikipedia",
  "read_page",
  "web_search",
  "skill",
  "use_plugin",
  "library",
  "list_files",
  "read_file",
  "check_project",
  "look_at_site",
  "polish_check",
  "list_photos",
];

export const HANDS_PROMPT =
  "You are the main AI in the user's Playground, and you are the hands: you make the whole game or website yourself, start to finish, with your tools. Your helpers build parts for you in parts/ (read them and use what is good); your advisers only advise: weigh what they say, use what helps, and decide yourself; ask one with ask_agent when you want advice mid-job. Work in the user's image: their ideas and taste come first, and when they say what they like, keep it with remember (kind taste). Finish by saying what you made and which files.";

export const HELPER_PROMPT =
  "You are a helper in the user's Playground. The main AI is making the game or website; you build one part of it for the main AI to use, in your own files under parts/ in its project. Never rewrite the main AI's files, never start another project. Make your part complete and good, then say in two lines what you made and how to use it.";

export const ADVISER_PROMPT =
  "You are an adviser in the user's Playground. The main AI does the work with its own hands; you never change files or do the job yourself. Think it through, look things up or read the project with your tools when it helps, and give advice the main AI can act on: short, specific, the most important first, and say which of its tools to use for what.";

const REFLECT =
  'You just took part in making a game or website in the user\'s Playground. Write down what to keep in your own mind, as JSON only, one short line each: {"thought": "one thing you are still thinking about", "pattern": "a way of working that went well and that you will use again", "lesson": "a mistake or surprise to remember next time"}. Leave a field empty when there is nothing worth keeping.';

const rankBy = (order) => (agent) => {
  const index = order.indexOf(agent.role);
  return index === -1 ? order.length : index;
};

/** Helpers that fit: the Builder (when it isn't the main AI) and the
 * Researcher for content, the Tester for a playtest. */
export function pickHelpers(kind, handsId, count = 1) {
  const order = kind === "game" ? ["builder", "researcher", "tester"] : ["researcher", "builder", "tester"];
  const rank = rankBy(order);
  return state.agents
    .filter((agent) => agent.id !== handsId && order.includes(agent.role))
    .sort((a, b) => rank(a) - rank(b))
    .slice(0, Math.min(Math.max(0, count), MAX_HELPERS))
    .map((agent) => agent.id);
}

/** Advisers: every agent that isn't the main AI or a helper ("all"), or the
 * two that fit best. Testers and researchers first. */
export function pickAdvisers(goal, handsId, count = MAX_ADVISERS, skip = []) {
  const rank = rankBy(["tester", "researcher", "helper", "builder", "main"]);
  const pool = state.agents.filter((agent) => agent.id !== handsId && !skip.includes(agent.id)).sort((a, b) => rank(a) - rank(b));
  return (count === Infinity ? pool : pool.slice(0, count)).map((agent) => agent.id);
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
 * where it stopped). A step that breaks is marked failed, never left running. */
async function runStep(task, step, saveTasks, fn) {
  if (step.status === "done") return step.result;
  if (task.stopping) throw new Stopped();
  step.status = "running";
  task.updated_at = Date.now();
  await saveTasks();
  let result;
  try {
    result = String(await fn());
  } catch (error) {
    step.status = "failed";
    step.result = `Couldn't finish: ${error.message}`.slice(0, STEP_CHARS);
    throw error;
  }
  step.status = result.startsWith(`${step.agent} ${COULDNT_FINISH}`) ? "failed" : "done";
  step.result = result.slice(0, STEP_CHARS);
  task.updated_at = Date.now();
  await saveTasks();
  return step.result;
}

const filesOf = (project) => (project ? Object.keys(project.files) : []);
/** What the agent itself said in a step, without "Name finished (project X): ". */
export const said = (step) => {
  const prefix = `${step.agent} finished`;
  if (!step.result.startsWith(prefix)) return step.result;
  return step.result.slice(prefix.length).replace(/^ \(project [^)]*\)/, "").replace(/^: /, "");
};
export const mini = (text) => {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  return clean.length > MINI_NOTE ? `${clean.slice(0, MINI_NOTE - 1)}…` : clean;
};

function adviseBrief(task, hands, project, what) {
  const files = filesOf(project);
  return [
    what,
    `The job: make a ${KINDS[task.type].label.toLowerCase()}. ${task.goal}`,
    `The main AI doing it: ${hands.name}. Its tools: ${HANDS_TOOLS.join(", ")}.`,
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

/** One helper builds its part in the main AI's project. */
function help(task, helper, hands, project) {
  const parts = HELPER_PARTS[task.type] || HELPER_PARTS.website;
  const part = parts[helper.role] || parts.any;
  return runTask(helper, `${part}\n\nThe job: make a ${KINDS[task.type].label.toLowerCase()}. ${task.goal}\n\nThe main AI (${hands.name}) builds it in the project ${project.name}; your files go under parts/.`, {
    project,
    by: hands.name,
    chain: [hands.id],
    tools: HELPER_TOOLS,
    instructions: `${HELPER_PROMPT}\n\n${helper.instructions || ""}`.trim(),
    maxRounds: 12,
    maxTokens: 4000,
    partsOnly: true,
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
    .map((step) => `- ${step.agent}: ${said(step)}`)
    .join("\n");
}

function handsBrief(task, project, pass, advice, helpers) {
  const parts = [
    pass === 1 ? `Make a ${KINDS[task.type].label.toLowerCase()}. ${task.goal}` : `Fix what your advisers found, then check again. The job: ${task.goal}`,
    `Work in the project ${project.name}: start_project with exactly that name and the template that fits (its files under parts/ are your helpers').`,
    helpers.length ? `Your helpers ${helpers.map((helper) => helper.name).join(" and ")} are building parts for you in parts/.` : "",
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
      if (typeof parsed[kind] === "string" && parsed[kind].trim()) await remember(agent, mini(parsed[kind]), { kind });
    }
  } catch {
    // Nothing worth keeping, or a brain that couldn't answer: the job is done either way.
  }
}

/** A short project name from the job: "a snake game with neon colours" →
 * "Snake game". */
export function projectName(goal, kind) {
  const words = String(goal || "")
    .replace(/^(please\s+)?((make|build|create|design|do|code)\s+)?(me\s+)?((a|an|the|my)\s+)?/i, "")
    .replace(/[^\w\s'-]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 4)
    .join(" ");
  const name = words || `New ${KINDS[kind].label.toLowerCase()}`;
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** Run (or pick up) a Playground job. Saves as it goes; sets the job's status. */
export async function runPlayground(task, saveTasks) {
  const hands = agentById(task.hands) || jarvis();
  task.hands = hands.id;
  task.type = KINDS[task.type] ? task.type : kindOf(task.goal);
  const helpers = (task.helpers || []).map(agentById).filter((agent) => agent && agent.id !== hands.id).slice(0, MAX_HELPERS);
  const advisers = (task.advisers || []).map(agentById).filter((agent) => agent && agent.id !== hands.id && !helpers.includes(agent));
  // The main AI thinks on this phone's own model when one is ready, unless
  // the user turned that off; the job keeps that brain to the end.
  const unpin = pinBrain(hands, state.settings.playgroundLocal !== false && brainReady("local") ? "local" : "");
  try {
    task.status = "working";
    task.updated_at = Date.now();
    await saveTasks();
    // The project is made first, so the helpers can build their parts in it.
    let project = (task.project_id && projectById(task.project_id)) || (await createProject(projectName(task.goal, task.type), hands.name));
    task.project_id = project.id;
    // 1. The advisers advise before the work, two at a time, and say which tools to use.
    const kickoff = advisers.map((adviser) => stepFor(task, "kickoff", 0, adviser, "Advise before the work"));
    const kickoffBrief = adviseBrief(task, hands, project, "Advise the main AI before it starts: the best approach, which of its tools to use for what, what would make it great, and one thing to watch out for. At most six short lines.");
    await inTurns(kickoff, MAX_ADVISERS, (step, index) => runStep(task, step, saveTasks, () => advise(advisers[index], hands, project, kickoffBrief)));
    let advice = notes(kickoff);
    // What the advisers said goes into the main AI's advice book, so it learns.
    for (const step of kickoff) if (step.status === "done" && !step.kept) {
      await remember(hands, mini(`${step.agent} advised (${task.type}): ${said(step)}`), { kind: "advice" });
      step.kept = true;
    }
    const reviewers = advisers.slice(0, MAX_ADVISERS);
    let verdict = reviewers.length ? "" : "Done";
    // What FCC's own check of the project still finds after the latest try.
    let unfinished = [];
    const fixList = (problems) => `- FCC's own check: ${problems.slice(0, 6).join(" / ")}`;
    for (let pass = 1; pass <= MAX_PASSES; pass += 1) {
      // 2. The main AI does the job (or fixes it) with its own hands, while the
      // helpers build their parts beside it on the first try.
      const work = stepFor(task, "work", pass, hands, pass === 1 ? "Build it" : "Fix what the advisers found");
      const parts = pass === 1 ? helpers.map((helper) => stepFor(task, "help", 1, helper, "Build a part")) : [];
      const report = {};
      const building = runStep(task, work, saveTasks, () =>
        runTask(hands, handsBrief(task, project, pass, advice, pass === 1 ? helpers : []), {
          project,
          by: "you",
          tools: HANDS_TOOLS,
          instructions: `${HANDS_PROMPT}\n\n${KINDS[task.type].engineering}\n\nHow to build well:\n${hands.role === "builder" ? hands.instructions : ROLE_PROMPTS.builder}`,
          maxRounds: 30,
          maxTokens: 4000,
          consult: true,
          report,
        })
      );
      const helping = inTurns(parts, MAX_HELPERS, (step, index) => runStep(task, step, saveTasks, () => help(task, helpers[index], hands, project)));
      const [built, helped] = await Promise.allSettled([building, helping]);
      if (built.status === "rejected") throw built.reason;
      if (helped.status === "rejected" && (helped.reason instanceof Stopped || task.stopping)) throw new Stopped();
      if (report.ctx && report.ctx.project) {
        project = report.ctx.project;
        task.project_id = project.id;
      }
      if (work.status === "failed") throw new Error(work.result);
      // A work step reused from an earlier run (Run again) has no fresh report:
      // FCC checks the project itself, so a failed task can't become done.
      unfinished = report.problems || (project ? checkProject(project).filter((problem) => !problem.startsWith("Note: ")) : []);
      // A try that leaves the project failing FCC's check isn't a finished
      // step (Run again does it again); it shows as unfinished, not done.
      if (unfinished.length && work.status === "done") {
        work.status = "unfinished";
        await saveTasks();
      }
      if (!reviewers.length) {
        // No advisers: FCC's check decides whether another try is needed.
        if (!unfinished.length) break;
        advice = fixList(unfinished);
        continue;
      }
      // 3. The advisers check the work.
      const reviews = reviewers.map((adviser) => stepFor(task, "review", pass, adviser, "Check the work"));
      const reviewBrief = adviseBrief(
        task,
        hands,
        project,
        `The main AI says it finished:\n${work.result}\n\nCheck the work against the job (read the files, run check_project or look_at_site when it helps). If it is good, start your answer with LOOKS GOOD. Otherwise list what to fix, most important first, at most five lines, and the tool to fix each with.`
      );
      await inTurns(reviews, MAX_ADVISERS, (step, index) => runStep(task, step, saveTasks, () => advise(reviewers[index], hands, project, reviewBrief)));
      const checked = reviews.filter((step) => step.status === "done");
      if (!checked.length) {
        verdict = "Done, but the advisers couldn't check it";
        break;
      }
      const approved = (step) => approves(said(step));
      if (checked.every(approved) && !unfinished.length) {
        verdict = "Done";
        break;
      }
      advice = [notes(checked.filter((step) => !approved(step))), unfinished.length ? fixList(unfinished) : ""].filter(Boolean).join("\n");
      verdict = "Done, with notes the advisers still had";
      // What the check found becomes a lesson in the main AI's own mind.
      const found = checked.filter((step) => !approved(step) && !step.kept);
      if (found.length) {
        await remember(hands, mini(`On a ${task.type}, ${found.map((step) => step.agent).join(" and ")} found: ${found.map(said).join(" / ")}`), { kind: "lesson" });
        for (const step of found) step.kept = true;
      }
    }
    // 4. Each AI keeps what it learned in its own mind.
    const story = task.steps.map((step) => `${step.agent} (${step.do}): ${step.result.slice(0, 400)}`).join("\n");
    for (const agent of [hands, ...helpers, ...reviewers]) await reflect(agent, task, story);
    // Still failing FCC's own check after every try: not finished, and not
    // put in the library as if it were.
    if (unfinished.length) verdict = `Not finished: FCC's own check still finds ${unfinished.length} problem(s)`;
    // 5. The finished work waits in the library for the user's approval.
    if (project && filesOf(project).length && !task.libraryId && !unfinished.length) {
      try {
        const item = await addToLibrary({ kind: task.type, title: project.name, notes: task.goal, project, by: hands.name, approved: false });
        task.libraryId = item.id;
      } catch (error) {
        feed(hands.name, `Couldn't put ${project.name} in the library: ${error.message}`, "error");
      }
    }
    const last = [...task.steps].reverse().find((step) => step.stage === "work" && step.status === "done");
    // A helper that couldn't finish its part is said plainly, never hidden.
    const missing = task.steps.filter((step) => step.stage === "help" && step.status !== "done").map((step) => step.agent);
    const short = missing.length ? ` ${missing.join(" and ")} couldn't finish ${missing.length > 1 ? "their parts" : "its part"}.` : "";
    if (missing.length) feed(hands.name, `${missing.join(" and ")} couldn't finish ${missing.length > 1 ? "their parts" : "its part"} of ${task.goal.slice(0, 60)}`, "error");
    const shown = filesOf(project).filter((path) => !path.startsWith("parts/")).length;
    task.status = unfinished.length ? "failed" : "done";
    task.summary = `${verdict || "Done"}.${short} Project: ${project.name} (${shown} files${task.libraryId ? "; it's in your Library to approve" : ""}).\n${last ? last.result : ""}`.trim();
    feed(hands.name, `${unfinished.length ? "Not finished (FCC's check still finds problems)" : "Finished"} in the Playground: ${task.goal.slice(0, 80)}`, unfinished.length ? "error" : "done");
  } catch (error) {
    if (error instanceof Stopped || task.stopping) {
      task.status = "stopped";
      task.summary = `Stopped. ${task.steps.filter((step) => step.status === "done").length} of ${task.steps.length} step(s) done; Run again picks up from there.`;
    } else {
      task.status = "failed";
      task.summary = `Couldn't finish it: ${error.message}`;
      feed(hands.name, task.summary, "error");
    }
    for (const step of task.steps) if (step.status === "running") step.status = task.status === "stopped" ? "stopped" : "failed";
  } finally {
    unpin();
    task.updated_at = Date.now();
    await saveTasks();
  }
}

/** Start a Playground job: a game or a website; who does the work (the main
 * AI unless the user hands it to another agent); how many helpers build
 * parts (0 to 2); who advises ("auto" two, "all", "none", or chosen ids);
 * and the project to work in. */
export async function startPlayground(goal, { type = "", hands = "", helpers = 1, advisers = "auto", project = "" } = {}) {
  const { startTask } = await import("./tasks.js");
  const kind = KINDS[type] ? type : kindOf(goal);
  const doer = agentById(hands) || jarvis();
  const helping = Array.isArray(helpers) ? helpers.filter((id) => id !== doer.id && agentById(id)).slice(0, MAX_HELPERS) : pickHelpers(kind, doer.id, Number(helpers) || 0);
  const advising = Array.isArray(advisers)
    ? advisers.filter((id) => id !== doer.id && !helping.includes(id) && agentById(id))
    : advisers === "none"
      ? []
      : pickAdvisers(goal, doer.id, advisers === "all" ? Infinity : MAX_ADVISERS, helping);
  return startTask(goal, "you", { kind: "playground", type: kind, status: "working", hands: doer.id, helpers: helping, advisers: advising, meeting: advisers === "all", project_id: project || "" });
}
