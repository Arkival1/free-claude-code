// Jarvis learns (#practice): his coding courses in FCC Linux, a Practise
// button with a time limit (or none), skills waiting for the user's OK, and
// his notes on what he can't do yet.
import { el, button, notify, go } from "../ui.js";
import { COURSES, LESSON_COUNT } from "../lessons.js";
import { practiceData, watchPractice, practising, startPractice, stopPractice, decideSkill } from "../practice.js";

const TIMES = [
  ["30 minutes", 30],
  ["1 hour", 60],
  ["3 hours", 180],
  ["8 hours", 480],
  ["No limit", 0],
];

export function render(view) {
  let chosen = new Set(Object.keys(COURSES));
  let minutes = 60;
  const draw = async () => {
    const data = await practiceData();
    const now = practising();
    const passed = Object.values(data.progress).reduce((sum, item) => sum + (item.passed || []).length, 0);
    const waiting = data.skills.filter((skill) => skill.status === "waiting");
    const languages = el("div", { class: "row practice-langs", role: "group", "aria-label": "Languages to practise" },
      Object.entries(COURSES).map(([key, course]) => {
        const progress = data.progress[key] || { passed: [] };
        return el("label", { class: "chip" }, [
          el("input", { type: "checkbox", checked: chosen.has(key) ? true : null, onchange: (event) => (event.target.checked ? chosen.add(key) : chosen.delete(key)) }),
          el("span", { text: ` ${course.name} ${(progress.passed || []).length}/${course.topics.length}` }),
        ]);
      }),
    );
    const time = el("select", { "aria-label": "How long to practise", onchange: (event) => (minutes = Number(event.target.value)) },
      TIMES.map(([label, value]) => el("option", { value: String(value), text: label, selected: value === minutes ? true : null })));
    view.replaceChildren(
      el("section", { class: "card" }, [
        el("h2", { text: "Jarvis learns to code" }),
        el("p", { class: "muted", text: `He teaches himself in FCC Linux: for each lesson he writes a program and its tests, runs them and fixes his code until they pass, then tests it for flaws. FCC runs his check itself, so only real passes count. ${passed} of ${LESSON_COUNT} lessons learned.` }),
        now
          ? el("div", {}, [
              el("p", { role: "status", text: `Practising now${now.current ? `: ${COURSES[now.current.lang].name}, lesson ${now.current.number} (${now.current.topic})` : ""}. ${now.passed} of ${now.done} passed so far${now.until !== Infinity ? `; stops at ${new Date(now.until).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}, once the lesson running then is finished and checked` : ""}. Keep FCC open (an iPhone pauses apps in the background).` }),
              button("Stop practising", () => {
                stopPractice();
                notify("Jarvis stops after this lesson.");
              }),
            ])
          : el("div", {}, [
              languages,
              el("div", { class: "row" }, [
                time,
                button("▶ Practise", async () => {
                  if (!chosen.size) return notify("Pick at least one language.");
                  try {
                    if (globalThis.Notification && Notification.permission === "default") await Notification.requestPermission();
                  } catch {
                    // Notes still come in chat and here.
                  }
                  try {
                    await startPractice({ languages: [...chosen], minutes });
                  } catch (error) {
                    notify(error.message);
                  }
                  draw();
                }, { class: "primary" }),
              ]),
            ]),
        el("div", { class: "row" }, [button("Open FCC Linux", () => go("lab/linux"))]),
      ]),
      el("section", { class: "card" }, [
        el("h2", { text: `Skills waiting for your OK (${waiting.length})` }),
        waiting.length
          ? el("ul", { class: "practice-skills" }, waiting.slice(0, 30).map((skill) =>
              el("li", {}, [
                el("strong", { text: skill.title }),
                el("p", { class: "small", text: skill.note }),
                el("p", { class: "small muted", text: `${COURSES[skill.lang] ? COURSES[skill.lang].name : skill.lang}, lesson ${skill.lesson} · example in FCC Linux: ${skill.folder}` }),
                el("div", { class: "row" }, [
                  button("OK, use it", async () => {
                    await decideSkill(skill.id, true);
                    notify("Jarvis will use this skill.");
                  }, { class: "primary", "aria-label": `Approve ${skill.title}` }),
                  button("No", () => decideSkill(skill.id, false), { "aria-label": `Reject ${skill.title}` }),
                ]),
              ])))
          : el("p", { class: "muted", text: "None yet: they come in as he passes lessons." }),
      ]),
      el("section", { class: "card" }, [
        el("h2", { text: "What he can't do yet" }),
        data.notes.length
          ? el("ul", { class: "small" }, data.notes.slice(0, 20).map((item) => el("li", { text: `${COURSES[item.lang] ? COURSES[item.lang].name : item.lang} ${item.lesson} (${item.topic}): ${item.text}` })))
          : el("p", { class: "muted", text: "Nothing: when he's stuck he says so here, in your chat and with a notification." }),
      ]),
    );
  };
  draw();
  return watchPractice(draw);
}
