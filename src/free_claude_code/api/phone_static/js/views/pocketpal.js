// PocketPal: the PocketPal app thinks, FCC Phone does the work (its hands).
// The user starts each turn: copy the prompt (or run the "FCC PocketPal"
// shortcut), bring the reply back, run the step, approve any change.
import { state, onChange } from "../state.js";
import { el, card, button, notify, go } from "../ui.js";
import * as pal from "../pocketpal.js";
import { projectById } from "../projects.js";

const SHORTCUT = "shortcuts://run-shortcut?name=FCC%20PocketPal&input=clipboard";
const EXAMPLES = {
  website: "Make a one-page website for a small cafe called Sunrise: opening hours, a menu with prices, and a contact section.",
  game: "Make a small game I can play with touch: catch falling stars in a basket, with a score and a restart button.",
};

// The two "Run JavaScript on Webpage" actions of the Share Sheet shortcut.
export const SHARE_SCRIPT_1 = "var p = window.fccPocketPal ? window.fccPocketPal.prompt() : (document.getElementById('prompt') || {}).value;\ncompletion(p || '');";
export const SHARE_SCRIPT_2 =
  "var b = '[Base64 Encoded]';\n" +
  "var t = new TextDecoder().decode(Uint8Array.from(atob(b), function (c) { return c.charCodeAt(0); }));\n" +
  "if (window.fccPocketPal) { window.fccPocketPal.reply(t).then(function (s) { completion(s); }); }\n" +
  "else { document.getElementById('reply').value = t; document.getElementById('reply-form').requestSubmit(); completion('sent'); }";

export function render(view) {
  const draw = () => view.replaceChildren(...screen().filter(Boolean));
  draw();
  return onChange((what) => {
    // Not while the user is typing in it.
    const typing = view.contains(document.activeElement) && ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement.tagName);
    if (["pocketpal", "projects"].includes(what) && !typing) draw();
  });
}

function screen() {
  const current = pal.task();
  const active = Boolean(current.question) && !current.done;
  return [
    card("PocketPal + FCC", [
      el("p", { class: "muted small", text: "PocketPal (the AI app on your phone) thinks; FCC Phone is its hands: files, projects, memory, look-ups. You start every turn and approve anything that changes something. Nothing runs in the background." }),
    ]),
    taskCard(current),
    active ? handoffCard(current) : null,
    current.pending ? approvalCard(current) : null,
    current.result ? resultCard(current) : null,
    activityCard(current),
    setupCard(),
  ];
}

function taskCard(current) {
  const project = el("select", { "aria-label": "Project PocketPal may use" }, [
    el("option", { value: "", text: "No project (PocketPal can start one)" }),
    ...state.projects.map((item) => el("option", { value: item.id, text: item.name })),
  ]);
  const question = el("textarea", { id: "question", rows: 3, maxlength: 16000, "aria-label": "Ask Jarvis", placeholder: "What should PocketPal do?" });
  const form = el("form", { class: "stack", onsubmit: async (event) => {
    event.preventDefault();
    try {
      await pal.start(question.value, project.value);
      notify("Task started. Copy the prompt to PocketPal.");
    } catch (error) {
      notify(error.message);
    }
  } }, [
    el("label", {}, ["Project", project]),
    el("label", {}, ["Ask Jarvis", question]),
    el("div", { class: "row" }, [
      button("Website prompt", () => { question.value = EXAMPLES.website; }),
      button("Game prompt", () => { question.value = EXAMPLES.game; }),
    ]),
    el("button", { class: "primary", type: "submit", id: "start", text: current.question && !current.done ? "Start a new task" : "Start task" }),
  ]);
  return card("Task", [form]);
}

function handoffCard(current) {
  const prompt = el("textarea", { id: "prompt", rows: 5, readonly: true, "aria-label": "Prompt for PocketPal" });
  prompt.value = current.prompt;
  const reply = el("textarea", { id: "reply", rows: 4, maxlength: pal.MAX_REPLY, "aria-label": "PocketPal reply", placeholder: "Paste PocketPal's JSON reply here" });
  let copied = false;
  const shortcut = button("Run shortcut", () => {
    if (!copied) return notify("Copy the prompt first.");
    location.href = SHORTCUT;
  }, { disabled: true });
  return card("Send to PocketPal", [
    el("label", { for: "prompt", text: "Prompt for PocketPal" }),
    prompt,
    el("div", { class: "row" }, [
      button("Copy prompt", async () => {
        try {
          await navigator.clipboard.writeText(prompt.value);
          copied = true;
          shortcut.disabled = false;
          notify("Copied. Run the shortcut, or paste it into PocketPal.");
        } catch {
          prompt.focus();
          prompt.select();
          notify("Copy the selected prompt, then paste it into PocketPal.");
        }
      }, { class: "primary" }),
      shortcut,
    ]),
    el("form", { id: "reply-form", class: "stack", onsubmit: async (event) => {
      event.preventDefault();
      // Out of the box first, so the screen shows the step's result.
      reply.blur();
      await runReply(reply.value);
    } }, [
      el("label", { for: "reply", text: "PocketPal's reply" }),
      reply,
      el("div", { class: "row" }, [
        button("Paste", async () => {
          try {
            reply.value = await navigator.clipboard.readText();
          } catch {
            notify("Long-press the box and tap Paste.");
          }
        }),
        el("button", { class: "primary", type: "submit", text: "Run FCC step" }),
      ]),
    ]),
  ]);
}

async function runReply(text) {
  try {
    const result = await pal.step(text);
    notify(result.pending ? "PocketPal wants to change something: approve or say no." : result.artifact ? "Saved to Projects." : result.answer ? "Done." : result.error ? "Blocked: the next prompt tells PocketPal why." : "Step done. Send the next prompt.");
    return pal.task().status;
  } catch (error) {
    notify(error.message);
    return error.message;
  }
}

function approvalCard(current) {
  const { tool, args } = current.pending;
  const shown = Object.entries(args || {}).map(([key, value]) => `${key}: ${typeof value === "string" && value.length > 160 ? `${value.slice(0, 160)}… (${value.length.toLocaleString()} characters)` : JSON.stringify(value)}`);
  return card("Approve this step?", [
    el("p", { text: `PocketPal wants to ${tool.replace(/_/g, " ")}.` }),
    el("pre", { class: "small", text: shown.join("\n") || "(no details)" }),
    el("div", { class: "row" }, [
      button("Approve", async () => { await pal.approve(true); notify("Done. Send the next prompt."); }, { class: "primary" }),
      button("No", async () => { await pal.approve(false); notify("Told PocketPal no. Send the next prompt."); }, { class: "danger" }),
    ]),
  ]);
}

function resultCard(current) {
  if (current.result.answer !== undefined) return card("Jarvis's answer", [el("p", { text: current.result.answer })]);
  const project = projectById(current.result.artifact.projectId);
  if (!project) return null;
  // The build runs in a sealed box: its own scripts only, no access to FCC.
  const frame = el("iframe", { class: "pocketpal-preview", title: `${project.name} preview`, sandbox: "allow-scripts", srcdoc: project.files["index.html"] || "" });
  return card(`${project.name} (${current.result.artifact.kind})`, [
    frame,
    el("div", { class: "row" }, [button("Open in Projects", () => go(`projects/${project.id}`), { class: "primary" })]),
  ]);
}

function activityCard(current) {
  return card("What Jarvis did", [
    el("p", { class: "small" }, [el("span", { class: "pill", id: "pocketpal-state", text: current.label }), ` ${current.status}`]),
    current.log.length
      ? el("ol", { class: "pocketpal-log" }, current.log.slice(-12).map((row) => el("li", { class: row.kind }, [el("strong", { text: row.who }), el("span", { text: ` ${row.text}` })])))
      : el("p", { class: "muted small", text: "Nothing yet." }),
  ]);
}

function setupCard() {
  return el("details", { class: "card" }, [
    el("summary", { text: "Set up the FCC PocketPal shortcut" }),
    el("p", { class: "small", text: "Share Sheet (best: no copying and pasting). In Shortcuts make a shortcut named FCC PocketPal, turn on Show in Share Sheet and set it to receive Safari web pages. Actions, in order:" }),
    el("ol", { class: "small" }, [
      el("li", { text: "Run JavaScript on Webpage (input: Shortcut Input) with the first script below." }),
      el("li", { text: "Ask Pal: your Pal, Message: JavaScript Result." }),
      el("li", { text: "Base64 Encode the Ask Pal result, Line Breaks: None." }),
      el("li", { text: "Run JavaScript on Webpage (input: Shortcut Input again, the same Safari page) with the second script; put the Base64 Encoded variable where it says [Base64 Encoded]." }),
    ]),
    el("pre", { class: "small", text: SHARE_SCRIPT_1 }),
    el("pre", { class: "small", text: SHARE_SCRIPT_2 }),
    el("p", { class: "small", text: "Then: start a task here, tap Share, FCC PocketPal. The reply comes straight back and FCC runs the step. Run it again for each next step." }),
    el("p", { class: "small", text: "Clipboard instead: a shortcut named FCC PocketPal with Get Clipboard, Ask Pal (Message: Clipboard), Copy to Clipboard. Here: Copy prompt, Run shortcut, come back, Paste, Run FCC step." }),
  ]);
}
