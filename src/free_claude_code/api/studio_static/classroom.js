/* FCC Studio classroom, in the look of the PocketPal AI app (MIT): a drawer
   of classes, a quiet chat column and a dark rounded input bar.
   The classroom itself is watch-only: the teacher and the student talk,
   the teacher steps out to learn more, the student's test question waits
   for it, and the teacher grades. "Talk to the teacher" opens the teacher
   chat, where the owner plans the class, confirms the plan, asks how the
   student is doing, trains the student (this PC, Kaggle or Colab) and
   gives it its trained model. Studio calls FCCClassroom.render(ctx). */
(() => {
  "use strict";

  const POLL_MS = 2000;
  const TEACHER_CHAT = new Set([
    "owner",
    "teacher_reply",
    "plan_proposed",
    "plan_confirmed",
    "teacher_back_notes",
    "training",
    "trained_in_use",
    "class_error",
    "teacher_handover",
  ]);
  const EVENT_KINDS = new Set([
    "course_opened",
    "teacher_left",
    "teacher_back",
    "student_waiting",
    "exam_started",
    "tune_queued",
    "course_failed",
    "teacher_handover",
    "plan_confirmed",
    "training",
    "trained_in_use",
    "class_error",
  ]);
  const PLACES = { local: "This PC", notebook: "Cloud notebook", cloud: "Server AI" };
  const QUESTION_STATES = {
    pending: "Not started",
    working: "Answering",
    waiting: "Waiting for the teacher",
    answered: "Answered",
    graded: "Graded",
  };

  let ctx = null;
  let root = null;
  let timer = 0;
  const state = { courseId: "", pane: "class", data: null, courses: [], drawer: false, sheet: "" };

  // Studio's el, with every click handler's error shown instead of lost.
  const el = (tag, props = {}, children = []) => {
    const safe = {};
    for (const [key, value] of Object.entries(props)) {
      safe[key] =
        key.startsWith("on") && typeof value === "function" ? guarded(value) : value;
    }
    return ctx.el(tag, safe, children);
  };
  const guarded = (handler) => (...args) => {
    try {
      const result = handler(...args);
      if (result && typeof result.catch === "function") {
        result.catch((error) => ctx.notify(error.message));
      }
    } catch (error) {
      ctx.notify(error.message);
    }
  };
  // Downloads are plain links, so they carry the proxy token like Training's.
  const withToken = (href) => {
    const key = ctx.token ? ctx.token() : "";
    return key ? `${href}${href.includes("?") ? "&" : "?"}token=${encodeURIComponent(key)}` : href;
  };
  const percent = (value) => `${Math.round((value || 0) * 100)}%`;
  const busy = () =>
    Boolean(state.data) &&
    (state.data.busy || ["planning", "teaching", "examining"].includes(state.data.course.status));

  /* ------------------------------------------------------------ page */

  async function render(context) {
    ctx = context;
    state.courseId = context.courseId;
    state.pane = context.pane === "teacher" ? "teacher" : "class";
    state.drawer = false;
    state.sheet = "";
    root = el("div", { class: "pp" });
    ctx.view.replaceChildren(root);
    await refresh();
  }

  async function refresh() {
    clearTimeout(timer);
    const [data, list] = await Promise.all([
      ctx.api(`/studio/api/school/courses/${state.courseId}`),
      ctx.api("/studio/api/school/courses"),
    ]);
    if (!ctx.alive()) return;
    state.data = data;
    state.courses = list.courses || [];
    paint();
    if (busy() || (data.training && ["queued", "running"].includes(data.training.status))) {
      timer = setTimeout(() => {
        if (ctx.alive()) refresh().catch(() => {});
      }, POLL_MS);
    }
  }

  function paint() {
    const draft = root.querySelector(".pp-input textarea");
    const kept = draft ? draft.value : "";
    const list = root.querySelector(".pp-messages");
    const nearBottom = !list || list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    root.replaceChildren(
      ...[
        header(),
        state.pane === "teacher" ? teacherChat() : classroom(),
        state.drawer ? drawer() : null,
        state.sheet ? sheet() : null,
      ].filter(Boolean)
    );
    const box = root.querySelector(".pp-input textarea");
    if (box) box.value = kept;
    const fresh = root.querySelector(".pp-messages");
    if (fresh && nearBottom) fresh.scrollTop = fresh.scrollHeight;
  }

  function header() {
    const { course } = state.data;
    const inTeacher = state.pane === "teacher";
    return el("header", { class: "pp-header" }, [
      inTeacher
        ? iconButton("‹", "Back to the classroom", () => switchPane("class"))
        : iconButton("☰", "Classes", () => {
            state.drawer = true;
            paint();
          }),
      el("div", { class: "pp-title" }, [
        el("strong", { text: inTeacher ? "Teacher" : course.topic }),
        el("span", { text: inTeacher ? course.topic : statusLine(course) }),
      ]),
      inTeacher
        ? iconButton("⚙", "Teacher and student settings", () => openSheet("settings"))
        : iconButton("✎", "Talk to the teacher", () => switchPane("teacher")),
    ]);
  }

  function iconButton(text, label, onclick) {
    return el("button", { class: "pp-icon", text, title: label, "aria-label": label, onclick });
  }

  function switchPane(pane) {
    state.pane = pane;
    state.sheet = "";
    paint();
  }

  function openSheet(name) {
    state.sheet = name;
    paint();
  }

  function statusLine(course) {
    const words = {
      planning: "Planning",
      proposed: "Plan waiting for you",
      teaching: `Lesson ${Math.min(course.lesson_done + 1, course.lesson_total)} of ${course.lesson_total}`,
      examining: "Test in progress",
      passed: `Passed · ${percent(course.score)}`,
      failed: course.score != null ? `Below the pass mark · ${percent(course.score)}` : "Stopped",
      cancelled: "Cancelled",
    };
    return words[course.status] || course.status;
  }

  /* ------------------------------------------------------- classroom */

  function classroom() {
    const { course, pals, questions } = state.data;
    const messages = state.data.messages.filter(
      (message) => !TEACHER_CHAT.has(message.data.kind) || EVENT_KINDS.has(message.data.kind)
    );
    return el("section", { class: "pp-pane" }, [
      el("div", { class: "pp-stage" }, [
        seat("teacher", pals.teacher, course.teacher_present ? "In class" : `Out: ${course.teacher_away || "learning more"}`, !course.teacher_present),
        el("div", { class: "pp-now" }, [
          el("span", { class: "pp-now-dot" + (busy() ? " live" : "") }),
          el("span", { text: course.activity || (busy() ? "Working…" : "Quiet") }),
          el("div", { class: "pp-meter" }, [
            el("span", { style: `width:${Math.round((state.data.progress || 0) * 100)}%` }),
          ]),
        ]),
        seat("student", pals.student, studentState(questions), false),
      ]),
      el(
        "div",
        { class: "pp-messages", role: "log", "aria-live": "polite" },
        messages.length ? messages.map(classMessage) : [emptyNote("The class hasn't started. Talk to the teacher to plan it.")]
      ),
      questions.length ? testStrip(questions, course) : null,
      el("button", { class: "pp-input pp-watch", onclick: () => switchPane("teacher") }, [
        el("span", { text: "You're watching. Talk to the teacher…" }),
        el("span", { class: "pp-send", text: "›" }),
      ]),
    ]);
  }

  function seat(role, pal, note, away) {
    return el("div", { class: `pp-seat ${role}${away ? " away" : ""}` }, [
      el("span", { class: "pp-avatar", text: role === "teacher" ? "T" : "S", "aria-hidden": "true" }),
      el("span", { class: "pp-seat-text" }, [
        el("strong", { text: role === "teacher" ? "Teacher" : "Student" }),
        el("span", { class: "pp-model", text: pal.model || "no model", title: pal.model }),
        el("span", { class: "pp-where", text: `${PLACES[pal.where] || ""} · ${note}` }),
      ]),
    ]);
  }

  function studentState(questions) {
    const waiting = questions.find((item) => item.state === "waiting");
    if (waiting) return `Waiting on Q${waiting.ordinal}`;
    const working = questions.find((item) => item.state === "working");
    if (working) return `Answering Q${working.ordinal}`;
    return "Listening";
  }

  function classMessage(message) {
    const kind = message.data.kind || "";
    if (message.role === "event" || EVENT_KINDS.has(kind)) {
      return el("div", { class: `pp-chip pp-k-${kind}` }, [el("span", { text: message.text })]);
    }
    const student = message.data.role === "student" || kind === "student_answer" || kind === "exam_answer";
    const label = {
      lesson: "Lesson",
      review: "Review",
      plan: "Plan",
      grade: "Grade",
      result: "Result",
      teacher_help: "Answers the question",
      exam_answer: "Test answer",
      student_answer: "Answer",
    }[kind];
    return el("article", { class: `pp-msg ${student ? "student" : "teacher"}` }, [
      el("span", { class: "pp-who", text: `${student ? "Student" : "Teacher"}${label ? ` · ${label}` : ""}` }),
      el("div", { class: "pp-text", text: message.text }),
    ]);
  }

  function testStrip(questions, course) {
    return el(
      "div",
      { class: "pp-test", "aria-label": "Test" },
      questions.map((item) =>
        el(
          "span",
          {
            class: `pp-q ${item.state}${item.score != null ? (item.score >= course.pass_mark ? " good" : " bad") : ""}`,
            title: item.prompt,
          },
          [
            el("strong", { text: `Q${item.ordinal}` }),
            el("span", { text: item.score != null ? percent(item.score) : QUESTION_STATES[item.state] || item.state }),
          ]
        )
      )
    );
  }

  function emptyNote(text) {
    return el("p", { class: "pp-empty", text });
  }

  /* ---------------------------------------------------- teacher chat */

  function teacherChat() {
    const { course, lessons } = state.data;
    const messages = state.data.messages.filter((message) => TEACHER_CHAT.has(message.data.kind));
    const box = el("textarea", {
      rows: "1",
      placeholder: course.plan_confirmed
        ? "Ask the teacher how the student is doing…"
        : "Tell the teacher what the student should learn…",
      "aria-label": "Message the teacher",
    });
    const send = async () => {
      const text = box.value.trim();
      if (!text) return;
      box.value = "";
      await ctx.post(`/studio/api/school/courses/${course.id}/talk`, { text });
      await refresh();
    };
    box.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        guarded(send)();
      }
    });
    return el("section", { class: "pp-pane" }, [
      el(
        "div",
        { class: "pp-messages", role: "log", "aria-live": "polite" },
        [
          ...(messages.length
            ? messages.map(chatMessage)
            : [emptyNote("Say what the student should learn. The teacher writes a lesson plan for you to confirm.")]),
          lessons.length && !course.plan_confirmed ? planCard(course, lessons) : null,
          trainingCard(),
        ]
      ),
      el("div", { class: "pp-quick" }, quickActions(course)),
      el("div", { class: "pp-input" }, [
        box,
        el("button", {
          class: "pp-send",
          text: "›",
          title: "Send",
          "aria-label": "Send",
          onclick: send,
        }),
      ]),
    ]);
  }

  function chatMessage(message) {
    const kind = message.data.kind;
    if (kind === "owner") {
      return el("article", { class: "pp-msg mine" }, [el("div", { class: "pp-text", text: message.text })]);
    }
    if (message.role === "event") {
      return el("div", { class: `pp-chip pp-k-${kind}` }, [el("span", { text: message.text })]);
    }
    return el("article", { class: "pp-msg teacher" }, [
      el("div", { class: "pp-text", text: message.text }),
      el("div", { class: "pp-foot" }, [
        el("button", {
          class: "pp-copy",
          text: "⧉",
          title: "Copy",
          "aria-label": "Copy",
          onclick: () => navigator.clipboard.writeText(message.text).then(() => ctx.notify("Copied.")),
        }),
        el("span", { text: message.author }),
      ]),
    ]);
  }

  function planCard(course, lessons) {
    return el("div", { class: "pp-card" }, [
      el("strong", { text: "Lesson plan" }),
      el(
        "ol",
        {},
        lessons.map((lesson) =>
          el("li", {}, [
            el("span", { text: lesson.topic }),
            lesson.objective ? el("small", { text: lesson.objective }) : null,
            lesson.research ? el("small", { class: "pp-research", text: `Looks up: ${lesson.research}` }) : null,
          ])
        )
      ),
      el("p", { class: "pp-hint", text: "Reply to change it, or confirm to start the class." }),
      el("button", {
        class: "pp-primary",
        text: "Confirm plan and start",
        disabled: state.data.busy,
        onclick: async () => {
          await ctx.post(`/studio/api/school/courses/${course.id}/confirm`);
          ctx.notify("Plan confirmed. The class has started.");
          state.pane = "class";
          await refresh();
        },
      }),
    ]);
  }

  function quickActions(course) {
    const chips = [];
    if (course.plan_confirmed) {
      chips.push(chip("How is the student doing?", () => talk("How is the student doing?")));
    }
    chips.push(chip("Send the teacher out to learn…", () => openSheet("out")));
    if (course.status === "passed") chips.push(chip("Train the student", () => openSheet("train")));
    return chips;
  }

  function chip(text, onclick) {
    return el("button", { class: "pp-chipbtn", text, onclick });
  }

  async function talk(text) {
    await ctx.post(`/studio/api/school/courses/${state.courseId}/talk`, { text });
    await refresh();
  }

  function trainingCard() {
    const job = state.data.training;
    if (!job) return null;
    const done = job.status === "succeeded";
    const place = job.runner === "local" ? "this PC" : "a cloud notebook";
    return el("div", { class: "pp-card" }, [
      el("strong", { text: "Student training" }),
      el("p", { text: `${job.base_model} on ${place}: ${job.status}` }),
      job.total_steps ? el("div", { class: "pp-meter" }, [el("span", { style: `width:${Math.round((job.step / job.total_steps) * 100)}%` })]) : null,
      job.message ? el("p", { class: "pp-hint", text: job.message }) : null,
      job.error ? el("p", { class: "pp-hint bad", text: job.error }) : null,
      job.runner === "remote" && !done
        ? el("div", { class: "pp-row" }, [
            downloadLink(`/studio/api/lora/jobs/${job.id}/notebook?target=kaggle`, "Kaggle notebook"),
            downloadLink(`/studio/api/lora/jobs/${job.id}/notebook?target=colab`, "Colab notebook"),
          ])
        : null,
      done && !job.in_use
        ? el("button", {
            class: "pp-primary",
            text: "Give the student its trained model",
            onclick: async () => {
              await ctx.post(`/studio/api/school/courses/${state.courseId}/use-trained`);
              await refresh();
            },
          })
        : null,
      job.in_use ? el("p", { class: "pp-hint good", text: "The student is using its trained model." }) : null,
    ]);
  }

  function downloadLink(href, text) {
    return el("a", { class: "pp-ghost", href: withToken(href), download: "", text });
  }

  /* ---------------------------------------------------------- sheets */

  function sheet() {
    const close = () => {
      state.sheet = "";
      paint();
    };
    const body = { out: outSheet, train: trainSheet, settings: settingsSheet }[state.sheet]();
    return el("div", { class: "pp-backdrop", onclick: (event) => event.target === event.currentTarget && close() }, [
      el("div", { class: "pp-sheet", role: "dialog", "aria-modal": "true" }, [
        el("div", { class: "pp-grip" }),
        body,
        el("button", { class: "pp-ghost", text: "Close", onclick: close }),
      ]),
    ]);
  }

  function outSheet() {
    const query = el("input", { type: "text", placeholder: "e.g. AS/NZS 3000 cable sizing rules", "aria-label": "What to look up" });
    return el("div", {}, [
      el("h3", { text: "Send the teacher out" }),
      el("p", { class: "pp-hint", text: "The teacher leaves the classroom, reads up, and brings back notes for the next lessons and the marking." }),
      query,
      el("button", {
        class: "pp-primary",
        text: "Send out",
        onclick: async () => {
          if (!query.value.trim()) return ctx.notify("Say what to look up.");
          await ctx.post(`/studio/api/school/courses/${state.courseId}/send-out`, { query: query.value.trim() });
          state.sheet = "";
          await refresh();
        },
      }),
    ]);
  }

  function trainSheet() {
    const option = (where, title, note) =>
      el("button", {
        class: "pp-option",
        onclick: async () => {
          const job = await ctx.post(`/studio/api/school/courses/${state.courseId}/train`, { where });
          state.sheet = "";
          if (job.notebook_url) {
            const link = el("a", { href: withToken(job.notebook_url), download: "" });
            document.body.append(link);
            link.click();
            link.remove();
            ctx.notify(`Notebook downloaded: open it on ${where === "kaggle" ? "Kaggle" : "Colab"} and press Run all.`);
          } else {
            ctx.notify("Training started on this PC.");
          }
          await refresh();
        },
      }, [el("strong", { text: title }), el("span", { text: note })]);
    return el("div", {}, [
      el("h3", { text: "Train the student" }),
      el("p", { class: "pp-hint", text: "The teacher writes worked examples for every lesson, then the student's weights are trained (LoRA) on them and on this class." }),
      option("pc", "This PC", "Your graphics card, with the teacher's model (local if it runs here). Qwen3 4B, 4-bit."),
      option("kaggle", "Kaggle", "Free T4 GPU, about 30 hours a week. Downloads a notebook. Qwen3 8B."),
      option("colab", "Google Colab", "Free T4 GPU. Downloads a notebook. Qwen3 8B."),
    ]);
  }

  function settingsSheet() {
    const { pals, course } = state.data;
    const modelBox = el("input", { type: "text", value: pals.teacher.model, "aria-label": "Teacher model" });
    return el("div", {}, [
      el("h3", { text: "Teacher" }),
      el("p", { class: "pp-hint", text: `Runs on ${PLACES[pals.teacher.where] || "?"}. Every teacher call carries short class notes, so if an API switches its model mid-class the next one carries on.` }),
      el("label", { class: "pp-label" }, ["Teacher model", modelBox]),
      el("div", { class: "pp-row" }, [
        el("button", {
          class: "pp-primary",
          text: "Save",
          onclick: async () => {
            if (!modelBox.value.trim()) return ctx.notify("Pick a model.");
            await ctx.api(`/studio/api/agents/${pals.teacher.id}`, {
              method: "PATCH",
              body: JSON.stringify({ updates: { model: modelBox.value.trim() } }),
            });
            ctx.notify("Teacher model saved.");
            await refresh();
          },
        }),
        el("button", { class: "pp-ghost", text: "Use the cloud notebook", onclick: () => (modelBox.value = "notebook/teacher") }),
      ]),
      el("p", { class: "pp-hint", text: "Teacher on Kaggle or Colab: download a notebook, press Run all, then paste the address and key it prints into Settings › Providers › Cloud notebook." }),
      el("div", { class: "pp-row" }, [
        downloadLink("/studio/api/school/teacher-notebook?target=kaggle", "Kaggle notebook"),
        downloadLink("/studio/api/school/teacher-notebook?target=colab", "Colab notebook"),
      ]),
      el("h3", { text: "Student" }),
      el("p", { class: "pp-hint", text: `${pals.student.name} · ${pals.student.model} (${PLACES[pals.student.where] || "?"})` }),
      course.status === "passed"
        ? el("button", { class: "pp-primary", text: "Train the student", onclick: () => openSheet("train") })
        : el("p", { class: "pp-hint", text: "Training opens once the student passes the class test." }),
    ]);
  }

  /* ---------------------------------------------------------- drawer */

  function drawer() {
    const close = () => {
      state.drawer = false;
      paint();
    };
    return el("div", { class: "pp-backdrop left", onclick: (event) => event.target === event.currentTarget && close() }, [
      el("nav", { class: "pp-drawer", "aria-label": "Classes" }, [
        el("strong", { class: "pp-brand", text: "Classroom" }),
        el("button", { class: "pp-new", text: "+ New class", onclick: () => ctx.go("learn") }),
        el("span", { class: "pp-section", text: "Classes" }),
        ...state.courses.map((course) =>
          el(
            "button",
            {
              class: `pp-session${course.id === state.courseId ? " active" : ""}`,
              onclick: () => ctx.go(`class/${course.id}`),
            },
            [el("span", { text: course.topic }), el("small", { text: course.status })]
          )
        ),
      ]),
    ]);
  }

  window.FCCClassroom = { render };
})();
