/* FCC Studio maths tutor — the maths on the path to an electrician's licence
   in NSW. Every question is made and marked by the server in code (so the
   answer and working are always right); the AI only explains, in plain
   words, and answers free questions, labelled as its own. Studio calls
   FCCTutor.render(ctx). */
(() => {
  "use strict";

  const TABS = [
    ["practice", "Practice", "✎"],
    ["test", "Practice test", "☑"],
    ["ask", "Ask the tutor", "?"],
    ["path", "Licence path", "⚡"],
  ];
  const TAB_KEY = "fcc.tutor.tab";

  let ctx = null;
  let root = null;
  const state = {
    tab: readTab(),
    overview: null,
    stage: "",
    topic: "",
    question: null,
    test: null,
  };

  function readTab() {
    try {
      const saved = localStorage.getItem(TAB_KEY);
      return TABS.some(([id]) => id === saved) ? saved : "practice";
    } catch {
      return "practice";
    }
  }

  function saveTab(id) {
    try {
      localStorage.setItem(TAB_KEY, id);
    } catch {
      /* private window: the tab just isn't remembered */
    }
  }

  const el = (...args) => ctx.el(...args);
  const topicById = (id) => state.overview.topics.find((topic) => topic.id === id);
  const progressOf = (id) =>
    (state.overview.progress.topics || []).find((row) => row.id === id) || {};
  const stageTitle = (id) =>
    (state.overview.stages.find((stage) => stage.id === id) || { title: "Everything" }).title;

  /* ------------------------------------------------------------ page */

  async function render(context) {
    ctx = context;
    root = el("div", { class: "tutor" });
    ctx.view.replaceChildren(root);
    const overview = await ctx.api("/studio/api/tutor");
    if (!ctx.alive()) return;
    state.overview = overview;
    if (!state.stage) state.stage = overview.stages[0].id;
    root.replaceChildren(
      el("div", { class: "tutor-summary", id: "tutor-summary" }),
      tabsBar(),
      el("div", { class: "tutor-panel", id: "tutor-panel" })
    );
    paintSummary();
    drawPanel();
  }

  async function refreshProgress() {
    const overview = await ctx.api("/studio/api/tutor");
    if (!ctx.alive()) return;
    state.overview = overview;
    paintSummary();
    const list = root.querySelector("#tutor-topics");
    if (list) list.replaceChildren(...topicButtons());
  }

  function paintSummary() {
    const box = root.querySelector("#tutor-summary");
    const progress = state.overview.progress;
    const strong = progress.topics.filter((row) => row.strong).length;
    const next = progress.suggested ? topicById(progress.suggested) : null;
    box.replaceChildren(
      el("div", { class: "tutor-stat" }, [
        el("strong", { text: `${strong} / ${progress.topics.length}` }),
        el("span", { text: "topics strong" }),
      ]),
      el("div", { class: "tutor-stat" }, [
        el("strong", { text: `${progress.right} / ${progress.answered}` }),
        el("span", { text: "answers right" }),
      ]),
      next
        ? el("button", {
            class: "primary",
            text: `Next: ${next.title}`,
            onclick: () => {
              state.stage = next.stage;
              openTopic(next.id);
            },
          })
        : el("span", { class: "good", text: "Every topic is strong. Try a practice test." })
    );
  }

  function tabsBar() {
    return el(
      "nav",
      { class: "tutor-tabs", role: "tablist" },
      TABS.map(([id, label, glyph]) =>
        el(
          "button",
          {
            class: `tutor-tab${state.tab === id ? " on" : ""}`,
            role: "tab",
            "data-tab": id,
            "aria-selected": state.tab === id ? "true" : "false",
            onclick: () => switchTab(id),
          },
          [el("span", { class: "glyph", text: glyph }), el("span", { text: label })]
        )
      )
    );
  }

  function switchTab(id) {
    state.tab = id;
    saveTab(id);
    root.querySelectorAll(".tutor-tab").forEach((node) => {
      const on = node.dataset.tab === id;
      node.classList.toggle("on", on);
      node.setAttribute("aria-selected", on ? "true" : "false");
    });
    drawPanel();
  }

  function drawPanel() {
    const panel = root.querySelector("#tutor-panel");
    const draw = { practice: practicePanel, test: testPanel, ask: askPanel, path: pathPanel }[
      state.tab
    ];
    panel.replaceChildren(...draw());
  }

  /* ------------------------------------------------------------ practice */

  function stageChips(onPick, withAll) {
    const stages = withAll
      ? [...state.overview.stages, { id: "all", title: "Everything" }]
      : state.overview.stages;
    return el(
      "div",
      { class: "tutor-chips" },
      stages.map((stage) =>
        el("button", {
          class: "chip",
          "aria-pressed": state.stage === stage.id ? "true" : "false",
          text: stage.title,
          onclick: () => onPick(stage.id),
        })
      )
    );
  }

  function practicePanel() {
    if (state.stage === "all") state.stage = state.overview.stages[0].id;
    const list = el("div", { class: "tutor-topics", id: "tutor-topics" }, topicButtons());
    return [
      stageChips((id) => {
        state.stage = id;
        state.topic = "";
        state.question = null;
        drawPanel();
      }),
      el("div", { class: "tutor-practice" }, [
        list,
        el("div", { class: "tutor-work", id: "tutor-work" }, workNodes()),
      ]),
    ];
  }

  function topicButtons() {
    const topics = state.overview.topics.filter((topic) => topic.stage === state.stage);
    return topics.map((topic) => {
      const row = progressOf(topic.id);
      const mastery = row.mastery == null ? null : row.mastery;
      return el(
        "button",
        {
          class: `tutor-topic${state.topic === topic.id ? " on" : ""}`,
          "data-topic": topic.id,
          onclick: () => openTopic(topic.id),
        },
        [
          el("strong", { text: topic.title }),
          el("span", { class: "muted", text: topic.why }),
          el("span", { class: "tutor-meter" }, [
            el("i", { style: `width:${mastery || 0}%` }),
          ]),
          el("span", {
            class: row.strong ? "good" : "muted",
            text: row.strong
              ? "Strong"
              : mastery == null
                ? "Not tried yet"
                : `${mastery}% of the last ${Math.min(row.answered, 10)}`,
          }),
        ]
      );
    });
  }

  async function openTopic(id) {
    state.topic = id;
    state.question = null;
    if (state.tab !== "practice") switchTab("practice");
    else drawPanel();
    await nextQuestion();
  }

  async function nextQuestion() {
    try {
      state.question = await ctx.api(
        `/studio/api/tutor/question?topic=${encodeURIComponent(state.topic)}`
      );
    } catch (error) {
      ctx.notify(error.message);
      return;
    }
    if (!ctx.alive()) return;
    paintWork();
  }

  function paintWork() {
    const box = root.querySelector("#tutor-work");
    if (box) box.replaceChildren(...workNodes());
    const input = root.querySelector("#tutor-answer");
    if (input) input.focus();
  }

  function workNodes() {
    const topic = state.topic ? topicById(state.topic) : null;
    if (!topic) {
      return [
        el("p", {
          class: "muted",
          text: "Pick a topic to see the lesson and get a question. Each question has new numbers.",
        }),
      ];
    }
    const lesson = el("section", { class: "card tutor-lesson" }, [
      el("h2", { text: topic.title }),
      el("p", { class: "muted", text: topic.why }),
      el("p", { text: topic.lesson }),
      el(
        "div",
        { class: "tutor-formulas" },
        topic.formulas.map((formula) => el("code", { text: formula }))
      ),
    ]);
    const question = state.question;
    if (!question) return [lesson, el("p", { class: "muted", text: "Getting a question…" })];
    const input = el("input", {
      id: "tutor-answer",
      type: "text",
      inputmode: "decimal",
      autocomplete: "off",
      placeholder: "Your answer",
      "aria-label": "Your answer",
    });
    const result = el("div", { class: "tutor-result", id: "tutor-result" });
    const hint = el("p", { class: "muted tutor-hint", hidden: true, text: question.hint });
    const check = async () => {
      if (!input.value.trim()) return ctx.notify("Type your answer first.");
      let marked;
      try {
        marked = await ctx.post("/studio/api/tutor/check", {
          question_id: question.id,
          answer: input.value,
        });
      } catch (error) {
        return ctx.notify(error.message);
      }
      if (!marked.understood) return ctx.notify(marked.message);
      result.replaceChildren(...resultNodes(marked, question, input.value));
      refreshProgress();
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") check();
    });
    return [
      lesson,
      el("section", { class: "card tutor-question" }, [
        el("p", { class: "tutor-prompt", text: question.prompt }),
        el("div", { class: "row" }, [
          input,
          question.unit ? el("span", { class: "tutor-unit", text: question.unit }) : null,
          el("button", { class: "primary", text: "Check", onclick: check }),
        ]),
        el("p", {
          class: "muted",
          text: `Round to ${question.places} decimal place${question.places === 1 ? "" : "s"} or more.`,
        }),
        hint,
        el("div", { class: "row wrap" }, [
          el("button", {
            class: "ghost",
            text: "Hint",
            onclick: () => {
              hint.hidden = false;
            },
          }),
          el("button", { class: "ghost", text: "New question", onclick: nextQuestion }),
        ]),
        result,
      ]),
    ];
  }

  function resultNodes(marked, question, given) {
    const explainBox = el("div", { class: "tutor-explain" });
    return [
      el("p", {
        class: `tutor-verdict ${marked.correct ? "good" : "bad"}`,
        text: marked.correct
          ? `Right: ${marked.answer}`
          : `Not quite. You gave ${marked.given}; the answer is ${marked.answer}.`,
      }),
      workingList(marked.steps),
      el("div", { class: "row wrap" }, [
        el("button", { class: "primary", text: "Next question", onclick: nextQuestion }),
        el("button", {
          class: "ghost",
          text: "Explain it to me",
          onclick: async (event) => {
            event.target.disabled = true;
            explainBox.replaceChildren(el("p", { class: "muted", text: "Asking the tutor…" }));
            try {
              const reply = await ctx.post("/studio/api/tutor/explain", {
                question_id: question.id,
                answer: given,
              });
              explainBox.replaceChildren(...explanationNodes(reply));
            } catch (error) {
              explainBox.replaceChildren(el("p", { class: "bad", text: error.message }));
            }
            event.target.disabled = false;
          },
        }),
      ]),
      explainBox,
    ];
  }

  function workingList(steps) {
    return el("ol", { class: "tutor-steps" }, steps.map((step) => el("li", { text: step })));
  }

  function explanationNodes(reply) {
    if (!reply.explanation) {
      return [el("p", { class: "muted", text: reply.note || "No AI is set up; the working is above." })];
    }
    return [
      el("p", { class: "tutor-ai-label", text: "The AI tutor explains (the answer above is worked out exactly):" }),
      el("p", { class: "tutor-ai", text: reply.explanation }),
    ];
  }

  /* ------------------------------------------------------------ test */

  function testPanel() {
    if (state.test && state.test.marked) return markedNodes(state.test.marked);
    if (state.test) return testNodes(state.test);
    return [
      el("section", { class: "card" }, [
        el("h2", { text: "Practice test" }),
        el("p", {
          class: "muted",
          text: "Ten questions from one stage (or everything). No hints; you see the score and the working at the end. Aim for 8 out of 10 before moving on.",
        }),
        stageChips((id) => {
          state.stage = id;
          drawPanel();
        }, true),
        el("button", {
          class: "primary",
          text: `Start a test: ${stageTitle(state.stage)}`,
          onclick: async () => {
            try {
              state.test = await ctx.api(
                `/studio/api/tutor/test?stage=${encodeURIComponent(state.stage)}`
              );
            } catch (error) {
              return ctx.notify(error.message);
            }
            drawPanel();
          },
        }),
      ]),
      recentTests(),
    ];
  }

  function recentTests() {
    const tests = state.overview.progress.tests || [];
    return el("section", { class: "card" }, [
      el("h2", { text: "Recent tests" }),
      tests.length
        ? el(
            "ul",
            { class: "tutor-tests" },
            tests.map((test) =>
              el("li", {
                text: `${stageTitle(test.stage)}: ${test.score} / ${test.total} · ${new Date(test.at).toLocaleString()}`,
              })
            )
          )
        : el("p", { class: "empty", text: "No tests yet." }),
    ]);
  }

  function testNodes(test) {
    const inputs = test.questions.map((question) =>
      el("input", {
        type: "text",
        inputmode: "decimal",
        autocomplete: "off",
        placeholder: "Answer",
        "data-question": question.id,
        "aria-label": `Answer to question`,
      })
    );
    return [
      el("section", { class: "card" }, [
        el("h2", { text: `Practice test: ${test.title}` }),
        el(
          "ol",
          { class: "tutor-test" },
          test.questions.map((question, index) =>
            el("li", {}, [
              el("p", { text: question.prompt }),
              el("div", { class: "row" }, [
                inputs[index],
                question.unit ? el("span", { class: "tutor-unit", text: question.unit }) : null,
              ]),
            ])
          )
        ),
        el("div", { class: "row wrap" }, [
          el("button", {
            class: "primary",
            text: "Mark my test",
            onclick: async () => {
              const answers = {};
              test.questions.forEach((question, index) => {
                answers[question.id] = inputs[index].value;
              });
              try {
                test.marked = await ctx.post("/studio/api/tutor/test", {
                  test_id: test.test_id,
                  answers,
                });
              } catch (error) {
                return ctx.notify(error.message);
              }
              drawPanel();
              refreshProgress();
            },
          }),
          el("button", {
            class: "ghost",
            text: "Give up this test",
            onclick: () => {
              state.test = null;
              drawPanel();
            },
          }),
        ]),
      ]),
    ];
  }

  function markedNodes(marked) {
    return [
      el("section", { class: "card" }, [
        el("h2", { text: `Score: ${marked.score} / ${marked.total} (${marked.percent}%)` }),
        el("p", { class: marked.percent >= 80 ? "good" : "warn", text: marked.advice }),
        el(
          "ol",
          { class: "tutor-test" },
          marked.results.map((row) =>
            el("li", { class: row.correct ? "right" : "wrong" }, [
              el("p", { text: row.prompt }),
              el("p", {
                class: row.correct ? "good" : "bad",
                text: row.correct
                  ? `Right: ${row.answer}`
                  : `${row.given ? `You gave ${row.given}` : "No answer"}; the answer is ${row.answer}.`,
              }),
              row.correct ? null : workingList(row.steps),
            ])
          )
        ),
        el("button", {
          class: "primary",
          text: "Another test",
          onclick: () => {
            state.test = null;
            drawPanel();
          },
        }),
      ]),
    ];
  }

  /* ------------------------------------------------------------ ask */

  function askPanel() {
    const box = el("textarea", {
      rows: "4",
      maxlength: "1000",
      placeholder: "e.g. How do I work out the current a 3.6 kW oven draws on 230 V?",
      "aria-label": "Your maths question",
    });
    const answer = el("div", { class: "tutor-explain" });
    return [
      el("section", { class: "card" }, [
        el("h2", { text: "Ask the tutor" }),
        el("p", {
          class: "muted",
          text: "Any maths question about electrical work. The AI answers with its working: check each step, and look up Standards values (AS/NZS 3000, 3008) yourself.",
        }),
        box,
        el("button", {
          class: "primary",
          text: "Ask",
          onclick: async (event) => {
            if (!box.value.trim()) return ctx.notify("Type a question.");
            event.target.disabled = true;
            answer.replaceChildren(el("p", { class: "muted", text: "Thinking…" }));
            try {
              const reply = await ctx.post("/studio/api/tutor/ask", { question: box.value });
              answer.replaceChildren(
                el("p", { class: "tutor-ai-label", text: "The AI tutor's answer (check the working):" }),
                el("p", { class: "tutor-ai", text: reply.answer })
              );
            } catch (error) {
              answer.replaceChildren(el("p", { class: "bad", text: error.message }));
            }
            event.target.disabled = false;
          },
        }),
        answer,
      ]),
    ];
  }

  /* ------------------------------------------------------------ path */

  function pathPanel() {
    const path = state.overview.pathway;
    return [
      el("section", { class: "card" }, [
        el("h2", { text: "Becoming an electrician in NSW" }),
        el(
          "ol",
          { class: "tutor-path" },
          path.steps.map((step) =>
            el("li", {}, [
              el("strong", { text: step.title }),
              el("p", { text: step.detail }),
              step.stage
                ? el("button", {
                    class: "ghost",
                    text: `Practise: ${stageTitle(step.stage)}`,
                    onclick: () => {
                      state.stage = step.stage;
                      state.topic = "";
                      state.question = null;
                      switchTab("practice");
                    },
                  })
                : null,
            ])
          )
        ),
        el("p", { class: "muted", text: path.note }),
        el(
          "ul",
          { class: "tutor-sources" },
          path.sources.map((source) =>
            el("li", {}, [
              el("a", { href: source.url, target: "_blank", rel: "noopener", text: source.title }),
            ])
          )
        ),
      ]),
    ];
  }

  window.FCCTutor = { render };
})();
