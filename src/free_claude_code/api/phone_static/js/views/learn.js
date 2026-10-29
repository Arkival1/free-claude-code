// Learn: have Jarvis study a subject, and read what he learned.
import { state, onChange } from "../state.js";
import { el, button, card, go, notify, meter, ago } from "../ui.js";
import { startStudy, stopStudy, studyById } from "../learn.js";

export function render(view, id) {
  if (id) return renderStudy(view, id);
  const topic = el("input", { "aria-label": "Subject", placeholder: "Electrical engineering" });
  const depth = el("select", { "aria-label": "How deep" }, [
    el("option", { value: "quick", text: "Quick (3 lessons)" }),
    el("option", { value: "normal", text: "Normal (5 lessons)" }),
    el("option", { value: "deep", text: "In depth (8 lessons)" }),
  ]);
  depth.value = "normal";
  const draw = () =>
    view.replaceChildren(
      card("Learn something", [
        el("p", { class: "muted", text: "Jarvis plans lessons from the basics up, reads up on each one, writes notes with an example and a self-check, and keeps them in memory for every agent. Or just tell him: \"learn astronomy\"." }),
        el("label", {}, ["Subject", topic]),
        el("label", {}, ["How deep", depth]),
        button("Start learning", async () => {
          try {
            notify(await startStudy(topic.value, depth.value, "you"));
            topic.value = "";
          } catch (error) {
            notify(error.message);
          }
        }, { class: "primary" }),
      ]),
      card(
        "Studies",
        state.studies.length
          ? state.studies.map((study) =>
              el("button", { class: "item as-button study", type: "button", onclick: () => go(`learn/${study.id}`), "aria-label": `Open ${study.topic}` }, [
                el("div", { class: "grow" }, [
                  el("strong", { text: study.topic }),
                  meter(study.progress),
                  el("small", { text: `${study.status} · ${Math.round(study.progress * 100)}% · ${study.step}` }),
                ]),
              ])
            )
          : [el("p", { class: "empty", text: "Nothing learned yet." })]
      )
    );
  draw();
  return onChange((what) => what === "learn" && draw());
}

function renderStudy(view, id) {
  const draw = () => {
    const study = studyById(id);
    if (!study) return go("learn");
    view.replaceChildren(
      card(study.topic, [
        meter(study.progress),
        el("p", { class: "muted", text: `${study.status} · ${Math.round(study.progress * 100)}% · ${study.step} · started ${ago(study.created_at)}` }),
        study.status === "learning" ? button("Stop learning", () => stopStudy(study)) : null,
      ]),
      ...study.lessons.map((lesson, index) =>
        card(`Lesson ${index + 1}: ${lesson.title}`, [
          lesson.notes ? el("pre", { class: "notes", text: lesson.notes }) : el("p", { class: "muted", text: "Not studied yet." }),
          lesson.source ? el("a", { href: lesson.source, target: "_blank", rel: "noopener", text: "Source" }) : null,
        ])
      )
    );
  };
  draw();
  return onChange((what) => what === "learn" && draw());
}
