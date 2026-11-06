// FCC Linux's screen (#lab/linux): the terminal, with keys a phone keyboard
// doesn't have, and Start, Keep my session, Start fresh, Stop. The machine
// lives in a dock on the page (not in this screen), so it keeps running when
// you look elsewhere and Jarvis can use the same one.
import { el, button, notify, go } from "../ui.js";
import { startLinux, runningLinux, forgetSession, hasSession, loadLinux, watchActivity } from "../linux.js";
import { status as filesStatus, getEverything } from "../linuxfiles.js";

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

// "Get everything now": one download at a time, for the whole app.
let gettingAll = null;

/** The system's files on this phone, and a button to get the rest now. */
function filesCard(onChange) {
  const line = el("p", { class: "small muted linux-files-line" });
  const box = el("div", { class: "linux-files" }, [line]);
  const show = async () => {
    try {
      await loadLinux();
    } catch {
      line.textContent = "";
      return;
    }
    const now = await filesStatus();
    const done = now.have === now.packs;
    line.textContent = done
      ? `Every language is on this phone (${(now.total / MB).toFixed(0)} MB): FCC Linux works with no internet.`
      : `On this phone: ${(now.bytes / MB).toFixed(0)} of ${(now.total / MB).toFixed(0)} MB. The rest comes the first time a program needs it (Rust, Go, Java, C++…).`;
    box.replaceChildren(
      line,
      done
        ? ""
        : gettingAll
          ? button("Stop getting files", () => (gettingAll.stop = true))
          : button(`Get everything now (${((now.total - now.bytes) / MB).toFixed(0)} MB, Wi-Fi best)`, async () => {
              gettingAll = { stop: false };
              show();
              try {
                await getEverything(
                  (got, total) => (line.textContent = `Getting FCC Linux's files: ${(got / MB).toFixed(0)} of ${(total / MB).toFixed(0)} MB…`),
                  () => gettingAll.stop,
                );
              } catch (error) {
                notify(error.message);
              } finally {
                gettingAll = null;
                show();
                onChange();
              }
            }),
    );
  };
  show();
  return box;
}

export function render(view) {
  const status = el("p", { class: "small muted linux-status", role: "status" });
  const host = dock();
  // While a pack downloads, a program waits: say what's coming.
  const stopWatching = watchActivity((text) => {
    if (text) status.textContent = text;
  });
  // The terminal fills the screen under the controls.
  const place = () => {
    const card = view.querySelector(".linux-card");
    if (card) host.style.top = `${Math.round(card.getBoundingClientRect().bottom + 8)}px`;
  };
  addEventListener("resize", place);
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
        filesCard(place),
        el("div", { class: "linux-keys", role: "group", "aria-label": "Keys" }, KEYS.map(([label, keys]) => el("button", { type: "button", text: label, disabled: on ? null : true, onclick: () => {
          const running = runningLinux();
          if (running) running.send(keys);
        } }))),
      ]),
    );
    host.classList.toggle("shown", on);
    host.setAttribute("aria-hidden", String(!on));
    place();
    if (!on && !starting) status.textContent = kept ? "Your kept session is waiting: Start opens it where you left off." : "FCC's own Linux on this phone, with every language: C/C++, Rust, Go, Java, Node.js, Python, Ruby, PHP, Perl, Lua and git. No internet inside, so nothing it runs can reach anything else.";
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
    stopWatching();
    removeEventListener("resize", place);
    host.classList.remove("shown");
    host.setAttribute("aria-hidden", "true");
  };
}
