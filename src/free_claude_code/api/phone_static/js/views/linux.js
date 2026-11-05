// FCC Linux's screen (#lab/linux): the terminal, with keys a phone keyboard
// doesn't have, and Start, Keep my session, Start fresh, Stop. The machine
// lives in a dock on the page (not in this screen), so it keeps running when
// you look elsewhere and Jarvis can use the same one.
import { el, button, notify, go } from "../ui.js";
import { startLinux, runningLinux, forgetSession, hasSession } from "../linux.js";

const MB = 1048576;
let dockNode = null;
let starting = null;

/** The dock the machine lives in (made once, kept on the page). */
export function dock() {
  if (!dockNode) {
    dockNode = el("div", { class: "linux-dock", "aria-hidden": "true" });
    document.body.append(dockNode);
  }
  return dockNode;
}

/** The running FCC Linux, or start one (in the dock). */
export async function ensureLinux({ onProgress, onStatus } = {}) {
  const running = runningLinux();
  if (running && running.ready) return running;
  if (!starting) {
    starting = startLinux(dock(), { onProgress, onStatus }).finally(() => (starting = null));
  }
  return starting;
}

const KEYS = [
  ["Esc", "\x1b"],
  ["Tab", "\t"],
  ["Ctrl-C", "\x03"],
  ["Ctrl-D", "\x04"],
  ["←", "\x1b[D"],
  ["↑", "\x1b[A"],
  ["↓", "\x1b[B"],
  ["→", "\x1b[C"],
  ["|", "|"],
  ["~", "~"],
  ["/", "/"],
];

export function render(view) {
  const status = el("p", { class: "small muted linux-status", role: "status" });
  const host = dock();
  const draw = async () => {
    const machine = runningLinux();
    const on = Boolean(machine && machine.ready);
    const kept = await hasSession();
    view.replaceChildren(
      el("section", { class: "card linux-card" }, [
        el("div", { class: "row linux-top" }, [
          button("← Lab", () => go("lab")),
          on
            ? button("Keep my session", async () => {
                status.textContent = "Keeping your session…";
                try {
                  const bytes = await machine.keep();
                  status.textContent = `Kept (${(bytes / MB).toFixed(1)} MB on this phone): next time it opens right here.`;
                } catch (error) {
                  status.textContent = error.message;
                }
              })
            : button("▶ Start FCC Linux", start, { class: "primary" }),
          on ? button("Stop", () => {
            machine.stop();
            draw();
          }) : null,
          kept ? button("Start fresh", async () => {
            if (!confirm("Forget the kept session (its files) and start fresh?")) return;
            await forgetSession();
            if (runningLinux()) runningLinux().stop();
            start();
          }) : null,
        ]),
        status,
        el("div", { class: "linux-keys", role: "group", "aria-label": "Keys" }, KEYS.map(([label, keys]) => el("button", { type: "button", text: label, disabled: on ? null : true, onclick: () => {
          const running = runningLinux();
          if (running) running.send(keys);
        } }))),
      ]),
    );
    host.classList.toggle("shown", on);
    host.setAttribute("aria-hidden", String(!on));
    if (!on && !starting) status.textContent = kept ? "Your kept session is waiting: Start opens it where you left off." : "A small Linux of FCC's own, on this phone: Python, Lua, bash, nano, tmux, SQLite, htop. No internet inside, so nothing it runs can reach anything else.";
  };
  const start = async () => {
    status.textContent = "Starting…";
    try {
      const machine = await ensureLinux({
        onProgress: (got, total) => (status.textContent = `Getting FCC Linux (first time only): ${(got / MB).toFixed(1)} of ${(total / MB).toFixed(1)} MB`),
        onStatus: (text) => (status.textContent = text),
      });
      status.textContent = `${machine.booted === "boot" ? "Booted" : machine.booted === "session" ? "Back where you left off" : "Opened"} in ${machine.seconds} s. Tap the terminal to type.`;
    } catch (error) {
      status.textContent = error.message;
      notify(error.message);
    }
    draw();
  };
  draw();
  return () => {
    host.classList.remove("shown");
    host.setAttribute("aria-hidden", "true");
  };
}
