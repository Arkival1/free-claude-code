// Memory: what the phone's agents remember, and what came from the PC.
import { state, save, changed, onChange, jarvis } from "../state.js";
import { el, button, card, ago } from "../ui.js";
import { remember, pcMemoryAllowed } from "../tools.js";
import { sync } from "../sync.js";

export function render(view) {
  const input = el("input", { placeholder: "Add a memory", "aria-label": "New memory" });
  const draw = () => {
    const pc = state.settings.pc;
    const agentName = (id) => (state.agents.find((agent) => agent.id === id) || { name: "deleted agent" }).name;
    view.replaceChildren(
      card("On this phone", [
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [input]),
          button("Add", async () => {
            if (!input.value.trim()) return;
            // What you add here is for the whole team.
            await remember(jarvis(), input.value, { share: true });
            input.value = "";
          }),
        ]),
        ...(state.memories.length
          ? state.memories.map((memory) =>
              el("div", { class: "item" }, [
                el("div", { class: "grow" }, [
                  el("strong", { text: memory.text }),
                  el("small", {
                    text: memory.own
                      ? `${agentName(memory.agent_id)}'s own memory · only ${agentName(memory.agent_id)} reads it · ${ago(memory.created_at)}`
                      : `${agentName(memory.agent_id)} · ${ago(memory.created_at)}${pc ? (memory.synced ? " · on your PC" : " · not synced yet") : ""}`,
                  }),
                ]),
                button("✕", async () => {
                  state.memories = state.memories.filter((item) => item.id !== memory.id);
                  await save.memories();
                  changed("memory");
                }, { class: "danger", "aria-label": "Forget this" }),
              ])
            )
          : [el("p", { class: "empty", text: "Nothing remembered yet. Tell an agent something about you, or add it here." })]),
        pc ? el("p", { class: "muted small", text: "Forgetting here doesn't remove what already went to your PC; forget it there too." }) : null,
      ]),
      card(
        "From my PC",
        pc
          ? [
              el("div", { class: "row" }, [
                el("span", { class: "grow muted", text: `${state.pcMemories.length} memories from ${pc.pcName || "your PC"} · synced ${ago(pc.lastSync)}` }),
                button("Sync now", () => sync().catch(() => {})),
              ]),
              el("p", {
                class: "warn",
                text: pcMemoryAllowed(jarvis()) ? "Agents here can use these." : "Kept private: only agents thinking on this phone or with your PC (when its AI runs on the PC) use these. Settings can change that.",
              }),
              ...(state.pcMemories.length
                ? state.pcMemories.slice(0, 300).map((memory) => el("div", { class: "item" }, [el("div", { class: "grow" }, [el("strong", { text: memory.text }), el("small", { text: memory.author || "PC" })])]))
                : [el("p", { class: "empty", text: "Nothing from the PC yet." })]),
            ]
          : [el("p", { class: "muted", text: "Pair your PC in Settings to share memories both ways." })]
      )
    );
  };
  draw();
  return onChange((what) => (what === "memory" || what === "pc") && draw());
}
