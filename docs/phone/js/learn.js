// Learn mode on the phone: plan lessons on a subject, read up on each on
// Wikipedia, write notes, and keep them in memory, with a progress bar.
import { state, save, changed, feed, jarvis } from "./state.js";
import { think } from "./brains.js";
import { uid } from "./ui.js";
import { wikipedia, remember } from "./tools.js";

const LESSONS = { quick: 3, normal: 5, deep: 8 };
const running = new Set();

export function studyById(id) {
  return state.studies.find((study) => study.id === id);
}

export async function startStudy(topic, depth = "normal", by = "you") {
  const clean = String(topic || "").trim();
  if (clean.length < 3) throw new Error("Say what to learn, like 'electrical engineering'.");
  const study = {
    id: uid(),
    topic: clean.slice(0, 120),
    depth: LESSONS[depth] ? depth : "normal",
    status: "learning",
    progress: 0,
    step: "Planning the lessons…",
    lessons: [],
    by,
    created_at: Date.now(),
  };
  state.studies.unshift(study);
  await save.studies();
  changed("learn");
  feed("Learn", `Started learning ${study.topic}.`, "start");
  run(study).catch(() => {});
  return `Started learning ${study.topic} (${LESSONS[study.depth]} lessons). The progress bar is on the Home screen and in Learn.`;
}

export async function stopStudy(study) {
  running.delete(study.id);
  if (study.status === "learning") study.status = "stopped";
  study.step = "Stopped. Finished lessons are kept.";
  await save.studies();
  changed("learn");
}

function jsonList(text) {
  const match = String(text).match(/\[[\s\S]*\]/);
  if (!match) return [];
  try {
    const items = JSON.parse(match[0]);
    return Array.isArray(items) ? items.map((item) => String(item).trim()).filter(Boolean) : [];
  } catch {
    return [];
  }
}

async function update(study, fields) {
  Object.assign(study, fields);
  await save.studies();
  changed("learn");
}

async function run(study) {
  running.add(study.id);
  const teacher = jarvis();
  const count = LESSONS[study.depth];
  try {
    const plan = await think(
      teacher,
      "You plan short courses. Reply with only a JSON list of lesson titles, from the basics to hands-on skill.",
      [{ role: "user", content: `Plan ${count} lessons to learn ${study.topic}.` }],
      [],
      { maxTokens: 300 }
    );
    let titles = jsonList(plan.text).slice(0, count);
    if (titles.length < 2) titles = [`What ${study.topic} is`, `Key ideas in ${study.topic}`, `Using ${study.topic} in practice`].slice(0, count);
    await update(study, { lessons: titles.map((title) => ({ title, notes: "", source: "", done: false })), progress: 0.05, step: `Lesson 1 of ${titles.length}: ${titles[0]}` });
    for (let i = 0; i < study.lessons.length; i += 1) {
      if (!running.has(study.id)) return;
      const lesson = study.lessons[i];
      await update(study, { step: `Reading up: ${lesson.title}` });
      let reading = "";
      try {
        reading = await wikipedia(`${study.topic} ${lesson.title}`);
      } catch {
        reading = "";
      }
      if (!running.has(study.id)) return;
      await update(study, { step: `Writing notes: ${lesson.title}`, progress: (i + 0.5) / study.lessons.length });
      const notes = await think(
        teacher,
        "You write clear study notes: a short explanation, the key ideas as bullet points, any formulas with units, a worked example, and one self-check question with its answer. Plain text, no more than 250 words.",
        [{ role: "user", content: `Subject: ${study.topic}\nLesson: ${lesson.title}\n\nWhat Wikipedia says:\n${reading.slice(0, 3000) || "(nothing found)"}` }],
        [],
        { maxTokens: 700 }
      );
      lesson.notes = notes.text;
      lesson.source = (reading.match(/Source: (\S+)/) || [])[1] || "";
      lesson.done = true;
      await remember(teacher, `Learned (${study.topic}, ${lesson.title}): ${notes.text.split("\n").find((line) => line.trim().length > 30)?.trim().slice(0, 300) || lesson.title}`);
      await update(study, { progress: (i + 1) / study.lessons.length, step: i + 1 < study.lessons.length ? `Lesson ${i + 2} of ${study.lessons.length}: ${study.lessons[i + 1].title}` : "Done" });
    }
    await update(study, { status: "done", step: `Finished all ${study.lessons.length} lessons.` });
    feed("Learn", `Finished learning ${study.topic}.`, "done");
  } catch (error) {
    await update(study, { status: "failed", step: error.message });
    feed("Learn", `Learning ${study.topic} stopped: ${error.message}`, "error");
  } finally {
    running.delete(study.id);
  }
}
