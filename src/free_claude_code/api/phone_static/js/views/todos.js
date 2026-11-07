// To-dos and reminders: added here or by Jarvis ("remind me to call Sam at 5").
import { state, save, changed, onChange } from "../state.js";
import { el, button, card, notify } from "../ui.js";
import { addTodo } from "../tools.js";

export function render(view) {
  const text = el("input", { "aria-label": "To-do", placeholder: "Buy milk" });
  const due = el("input", { "aria-label": "Reminder", placeholder: "Reminder: in 20 minutes, tomorrow 9am, 17:30 (optional)" });
  const draw = () => {
    const open = state.todos.filter((item) => !item.done);
    const done = state.todos.filter((item) => item.done).slice(0, 20);
    view.replaceChildren(
      card("Add a to-do", [
        text,
        due,
        button("Add", async () => {
          try {
            await addTodo(text.value, due.value, "you");
            text.value = "";
            due.value = "";
          } catch (error) {
            notify(error.message);
          }
        }, { class: "primary" }),
        el("p", { class: "muted small", text: "Reminders show and speak while FCC Phone is open (iPhones don't let web apps set alarms when they're closed)." }),
      ]),
      card("To do", open.length ? open.map(row) : [el("p", { class: "empty", text: "Nothing to do." })]),
      ...(done.length ? [card("Done", done.map(row))] : [])
    );
  };
  const row = (item) =>
    el("div", { class: `item${item.done ? " done" : ""}` }, [
      el("input", { type: "checkbox", checked: item.done, "aria-label": `Done: ${item.text}`, onchange: async (event) => {
        item.done = event.target.checked;
        await save.todos();
        changed("todos");
      } }),
      el("div", { class: "grow" }, [
        el("strong", { text: item.text }),
        el("small", { text: `${item.due_at ? `reminder ${new Date(item.due_at).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : "no reminder"} · added by ${item.by}` }),
      ]),
      button("✕", async () => {
        state.todos = state.todos.filter((other) => other.id !== item.id);
        await save.todos();
        changed("todos");
      }, { class: "danger", "aria-label": `Remove ${item.text}` }),
    ]);
  draw();
  return onChange((what) => what === "todos" && draw());
}
