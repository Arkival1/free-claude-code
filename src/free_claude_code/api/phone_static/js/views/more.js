// More: everything else, like the PC's More page.
import { state } from "../state.js";
import { el, card, go } from "../ui.js";

const ITEMS = [
  ["projects", "⚒", "Projects", "Websites and apps the Builder makes"],
  ["rooms", "◎", "Agent rooms", "Several agents in one conversation"],
  ["learn", "◈", "Learn", "Have Jarvis study a subject"],
  ["todos", "✓", "To-dos and reminders", "Your list, kept by Jarvis"],
  ["memory", "✦", "Memory", "What your agents remember, and your PC's"],
  ["agents/brains", "⚙", "Team brains", "Who thinks with what"],
  ["settings", "⚙", "Settings", "Free cloud brains, your PC, voice, backups"],
  ["help", "?", "Help", "How FCC Phone works"],
];

export function render(view) {
  view.replaceChildren(
    card(
      "More",
      ITEMS.map(([route, glyph, title, sub]) =>
        el("button", { class: "item as-button", type: "button", onclick: () => go(route), "aria-label": `${title}: ${sub}` }, [
          el("span", { class: "glyph", "aria-hidden": "true", text: glyph }),
          el("div", { class: "grow" }, [el("strong", { text: title }), el("small", { text: sub })]),
          route === "todos" && state.todos.some((item) => !item.done) ? el("span", { class: "pill gold", text: String(state.todos.filter((item) => !item.done).length) }) : null,
        ])
      )
    )
  );
}

export function renderHelp(view) {
  const topics = [
    ["Brains", "Agents need a brain to think with. Models (on this phone) is free, private, and works offline: download Qwen3 0.6B to start, or add any .gguf from Files. Settings takes a free Gemini, Groq, or OpenRouter key for faster, smarter answers. Paired with your PC, agents can also think with your PC's AI."],
    ["The team", "Jarvis runs the team: ask him anything, or say \"have Builder make…\". The Builder makes websites (see Projects) from starter templates, with free photos, and checks how they look on a phone and a computer before it finishes; the Researcher looks things up, the Helper plans, and the Tester checks projects. Each has its own tools; Agents, Edit lets you tick tools one by one or give Every tool."],
    ["Memory", "Agents remember facts with remember and look them up with recall. Memory lives on this phone. Paired with your PC, new memories go to the PC's team memory and the PC's come back; the PC's never go to a cloud brain unless you allow it."],
    ["Speed", "On-phone models run on the iPhone's graphics chip. Smaller models and smaller context are faster: Qwen3 0.6B answers quickest; 1.5B models are smarter but slower. Test speed on Models shows tokens per second."],
    ["Installing", "Open FCC Phone in Safari, then Share, Add to Home Screen. It then opens full screen and works offline (on-phone models and saved data; cloud brains and look-ups need the internet)."],
  ];
  view.replaceChildren(...topics.map(([title, body]) => card(title, [el("p", { text: body })])));
}
