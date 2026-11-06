// Jarvis teaches himself to code in FCC Linux (owner: "he will be teaching
// himself"). A practice session works through the courses in js/lessons.js:
// for each lesson Jarvis writes a program, its tests and a check.sh in
// /root/learn/<language>/<n>, runs them and fixes his code until they pass.
// FCC then runs check.sh itself: only a passing check counts. What he learned
// becomes a skill that waits for the user's OK before he uses it; if he's stuck
// after his tries, he sends the user a note on what he can and can't do.
// Sessions run while FCC is open (an iPhone pauses apps in the background),
// for the time the user picks or with no limit, on Jarvis's own brain (the
// phone model first).
import { state, changed, feed, jarvis } from "./state.js";
import { store } from "./store.js";
import { COURSES } from "./lessons.js";

const KEY = "practice";
const DRAFTS_KEPT = 200;
let data = null;
let session = null;
const watchers = new Set();

/** Progress, skills and notes: { progress: {lang: {next, passed, stuck}}, skills: [], notes: [] }. */
export async function practiceData() {
  if (!data) data = Object.assign({ progress: {}, skills: [], notes: [] }, await store.get(KEY, {}));
  return data;
}
async function keep() {
  await store.set(KEY, data);
  for (const watch of watchers) watch();
  changed("practice");
}
/** Watch practice changes (the learning page); returns a stop function. */
export function watchPractice(watch) {
  watchers.add(watch);
  return () => watchers.delete(watch);
}
export const practising = () => session;

function notify(title, body) {
  try {
    if (globalThis.Notification && Notification.permission === "granted") new Notification(title, { body: body.slice(0, 180), tag: "fcc-practice" });
  } catch {
    // No notifications here.
  }
}

/** The next lesson for a language (or the language with the fewest passed). */
function nextLesson(languages) {
  const progress = data.progress;
  const open = languages
    .map((lang) => ({ lang, at: (progress[lang] || {}).next || 0 }))
    .filter((item) => COURSES[item.lang] && item.at < COURSES[item.lang].topics.length);
  if (!open.length) return null;
  open.sort((a, b) => a.at - b.at);
  const { lang, at } = open[0];
  return { lang, number: at + 1, topic: COURSES[lang].topics[at] };
}

const RULES = `You are teaching yourself to code in FCC Linux (the linux tool) and nobody is waiting on you: take your time and check your own work.
For the lesson:
1. In the lesson's folder, write a small program that uses the topic for real, and tests for it.
2. Write check.sh in that folder: it builds and runs the tests and exits 0 only if they all pass (bash; no keyboard input; under a minute).
3. Run bash check.sh. Read every error, fix your code (not the test's expectations, unless the test is wrong), and run it again until it passes.
4. Before you finish, test your code for flaws: edge cases, bad input, empty input; add a test for each and keep check.sh passing.
5. Finish with exactly these lines:
RESULT: passed  (or RESULT: stuck)
SKILL: one line naming what you can now do
NOTE: two to five sentences: how to do it right in this language, the mistakes you made and how you fixed them, and what to watch for.
If you're stuck after several real tries, say RESULT: stuck and in NOTE say exactly what you can't do yet and what you'd need.`;

function parse(text) {
  const result = /RESULT:\s*(passed|stuck)/i.exec(text);
  // No RESULT line (an error, a brain that stopped, rounds ran out): the
  // lesson wasn't done, so it isn't counted either way.
  if (!result) return { result: "incomplete", skill: "", note: text.slice(-600) };
  const skill = /SKILL:\s*(.+)/i.exec(text);
  const note = /NOTE:\s*([\s\S]+)/i.exec(text);
  return { result: result ? result[1].toLowerCase() : "stuck", skill: skill ? skill[1].trim().slice(0, 160) : "", note: note ? note[1].trim().slice(0, 1200) : text.slice(-600) };
}

async function runLesson(lesson, signal) {
  const { runTask, tell } = await import("./agents.js");
  const { ensureLinux } = await import("./views/linux.js");
  const machine = await ensureLinux();
  const course = COURSES[lesson.lang];
  const folder = `/root/learn/${lesson.lang}/${String(lesson.number).padStart(2, "0")}`;
  await machine.run(`mkdir -p ${folder}`);
  const goal = `Lesson ${lesson.number} of ${course.name}: ${lesson.topic}. Work in ${folder} (the ${course.name} tools are installed: ${course.run}).`;
  const answer = await runTask(jarvis(), goal, { tools: ["linux", "remember", "recall"], instructions: RULES, maxRounds: 40, by: "practice" });
  const got = parse(answer);
  if (got.result === "incomplete") throw new Error(`Lesson ${lesson.number} of ${course.name} didn't finish: ${got.note.slice(-200)}`);
  // FCC checks it itself: the lesson counts only if check.sh passes now (its
  // exit code on the last line, after the log, so the log can't fake it).
  const check = await machine.run(`cd ${folder} && [ -f check.sh ] && timeout 300 bash check.sh >/tmp/.fcc-check.log 2>&1; code=$?; tail -5 /tmp/.fcc-check.log; echo "check=$code"`, { timeoutMs: 360000 }).catch((error) => ({ code: 1, text: error.message }));
  const passed = /^check=0$/m.test(check.text) && got.result === "passed";
  const progress = (data.progress[lesson.lang] = data.progress[lesson.lang] || { next: 0, passed: [], stuck: [] });
  if (passed) {
    progress.passed.push(lesson.number);
    progress.next = lesson.number;
    data.skills.unshift({ id: `${Date.now()}`, lang: lesson.lang, lesson: lesson.number, topic: lesson.topic, title: got.skill || `${course.name}: ${lesson.topic}`, note: got.note, folder, status: "waiting", at: Date.now() });
    data.skills.length = Math.min(data.skills.length, DRAFTS_KEPT);
    feed(jarvis().name, `Learned ${course.name}: ${lesson.topic} (waiting for your OK)`, "done");
  } else {
    progress.stuck.push(lesson.number);
    progress.next = lesson.number; // move on; it stays on the list of what he can't do yet
    const why = got.result === "passed" ? `His tests said passed, but FCC's own check didn't: ${check.text.slice(-300)}` : got.note;
    data.notes.unshift({ id: `${Date.now()}`, lang: lesson.lang, lesson: lesson.number, topic: lesson.topic, text: why, at: Date.now() });
    data.notes.length = Math.min(data.notes.length, DRAFTS_KEPT);
    const message = `I'm stuck on ${course.name}, lesson ${lesson.number} (${lesson.topic}). ${why.slice(0, 500)}`;
    await tell(jarvis(), message);
    notify("Jarvis is stuck on a lesson", message);
  }
  await keep();
  return passed;
}

/**
 * Start a practice session: languages (keys of COURSES, or all), minutes
 * (0 = no limit). One session at a time; it stops at the time limit, when
 * every lesson is done, or with stopPractice().
 */
export async function startPractice({ languages = Object.keys(COURSES), minutes = 60 } = {}) {
  await practiceData();
  if (session) return session;
  const wanted = languages.filter((lang) => COURSES[lang]);
  if (!wanted.length) throw new Error(`Pick languages from: ${Object.keys(COURSES).join(", ")}.`);
  const until = minutes > 0 ? Date.now() + minutes * 60000 : Infinity;
  const signal = { stopped: false };
  session = { languages: wanted, until, started: Date.now(), done: 0, passed: 0, current: null, signal };
  for (const watch of watchers) watch();
  feed(jarvis().name, `Started practising ${wanted.map((lang) => COURSES[lang].name).join(", ")}${minutes > 0 ? ` for ${minutes} min` : ""}`, "start");
  (async () => {
    try {
      while (!signal.stopped && Date.now() < until) {
        const lesson = nextLesson(wanted);
        if (!lesson) break;
        session.current = lesson;
        for (const watch of watchers) watch();
        const passed = await runLesson(lesson, signal);
        if (passed === null) break;
        session.done += 1;
        if (passed) session.passed += 1;
      }
    } catch (error) {
      feed(jarvis().name, `Practice stopped: ${error.message}`, "error");
    } finally {
      const summary = session ? `Practice finished: ${session.passed} of ${session.done} lessons passed.` : "";
      session = null;
      for (const watch of watchers) watch();
      if (summary) {
        feed(jarvis().name, summary, "done");
        notify("Jarvis finished practising", summary);
      }
    }
  })();
  return session;
}

export function stopPractice() {
  if (session) session.signal.stopped = true;
}

/** The user's OK (or no) on a learned skill. An OK'd skill goes into Jarvis's
 * lessons (his memory), so he uses it on later jobs. */
export async function decideSkill(id, ok) {
  await practiceData();
  const skill = data.skills.find((item) => item.id === id);
  if (!skill || skill.status !== "waiting") return null;
  skill.status = ok ? "approved" : "rejected";
  if (ok) {
    const { remember } = await import("./tools.js");
    await remember(jarvis(), `Skill (${COURSES[skill.lang] ? COURSES[skill.lang].name : skill.lang}): ${skill.title}. ${skill.note} (Worked example in FCC Linux: ${skill.folder})`, { kind: "lesson" });
  }
  await keep();
  return skill;
}
