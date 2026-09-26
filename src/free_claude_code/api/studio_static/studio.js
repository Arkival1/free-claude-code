/* FCC Studio — a touch-first client for agents, models, tuning, and classes. */
(() => {
  "use strict";

  const TOKEN_KEY = "fcc.studio.token";
  const TAB_ROUTES = ["home", "chats", "agents", "learn", "more"];
  const POLL_MS = 2500;
  const HIDDEN_POLL_MS = 10000;

  const view = document.getElementById("view");
  const title = document.getElementById("view-title");
  const backButton = document.getElementById("back-button");
  const guideButton = document.getElementById("guide-button");
  const sheet = document.getElementById("sheet");
  const sheetTitle = document.getElementById("sheet-title");
  const sheetBody = document.getElementById("sheet-body");
  const toast = document.getElementById("toast");

  let poller = null;
  let renderGeneration = 0;
  let toastTimer = null;

  /* ------------------------------------------------------------------ utils */

  const el = (tag, props = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "html") node.innerHTML = value;
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, "");
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const child of [].concat(children)) {
      if (child == null) continue;
      node.append(child instanceof Node ? child : document.createTextNode(child));
    }
    return node;
  };

  const token = () => {
    const fromUrl = new URLSearchParams(location.search).get("token");
    if (fromUrl) localStorage.setItem(TOKEN_KEY, fromUrl);
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch {
      return "";
    }
  };

  const notify = (message) => {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.hidden = true;
    }, 3200);
  };

  class OfflineError extends Error {}

  async function api(path, options = {}) {
    const headers = { "content-type": "application/json", ...(options.headers || {}) };
    const key = token();
    if (key) headers["x-api-key"] = key;
    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch {
      throw new OfflineError("Can't reach your Studio server.");
    }
    if (response.status === 401) {
      askForToken();
      throw new Error("Studio needs the proxy token.");
    }
    const text = await response.text();
    const body = text ? JSON.parse(text) : {};
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }

  const post = (path, payload) =>
    api(path, { method: "POST", body: JSON.stringify(payload || {}) });
  const patch = (path, payload) =>
    api(path, { method: "PATCH", body: JSON.stringify(payload || {}) });
  const put = (path, payload) =>
    api(path, { method: "PUT", body: JSON.stringify(payload || {}) });
  const remove = (path) => api(path, { method: "DELETE" });

  const percent = (value) => `${Math.round((value || 0) * 100)}%`;
  const bytes = (value) => {
    if (!value) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }
    return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
  };
  const when = (ms) => (ms ? new Date(ms).toLocaleString() : "");

  const meter = (value) =>
    el("div", { class: "meter" }, [el("i", { style: `width:${percent(value)}` })]);

  const statusPill = (status) => {
    const good = ["ready", "succeeded", "passed"];
    const bad = ["failed", "cancelled"];
    const tone = good.includes(status) ? "good" : bad.includes(status) ? "bad" : "warn";
    return el("span", { class: `pill ${tone}`, text: status });
  };

  const empty = (message) => el("p", { class: "empty", text: message });

  const card = (heading, children, sub) =>
    el("section", { class: "card" }, [
      heading ? el("h2", { text: heading }) : null,
      sub ? el("p", { class: "muted", text: sub }) : null,
      ...[].concat(children),
    ]);

  function openSheet(heading, nodes) {
    sheetTitle.textContent = heading;
    sheetBody.replaceChildren(...[].concat(nodes));
    sheet.hidden = false;
  }

  function closeSheet() {
    sheet.hidden = true;
    sheetBody.replaceChildren();
  }

  sheet.addEventListener("click", (event) => {
    if (event.target.hasAttribute("data-close-sheet")) closeSheet();
  });

  function askForToken() {
    openSheet("Proxy token", [
      el("p", {
        class: "muted",
        text: "This server has proxy authentication on. Paste the token to use Studio from this device.",
      }),
      el("input", { type: "text", id: "token-input", placeholder: "token" }),
      el("button", {
        class: "primary",
        text: "Save token",
        onclick: () => {
          const value = document.getElementById("token-input").value.trim();
          if (!value) return;
          localStorage.setItem(TOKEN_KEY, value);
          closeSheet();
          render();
        },
      }),
    ]);
  }

  /* ----------------------------------------------------------------- router */

  const route = () => {
    const raw = location.hash.replace(/^#/, "") || "home";
    const [name, ...rest] = raw.split("/");
    return { name, id: rest.join("/") };
  };

  const go = (hash) => {
    location.hash = hash;
  };

  function setChrome(name, heading) {
    title.textContent = heading;
    backButton.hidden = TAB_ROUTES.includes(name);
    for (const tab of document.querySelectorAll(".tab")) {
      const active = tab.dataset.route === name;
      if (active) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    }
  }

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => go(tab.dataset.route));
  }
  backButton.addEventListener("click", () => history.back());
  guideButton.addEventListener("click", openGuide);
  // "?" opens the guide from anywhere, unless you are typing.
  document.addEventListener("keydown", (event) => {
    const typing = event.target.closest && event.target.closest("input, textarea, select, [contenteditable]");
    if (event.key === "?" && !typing && !event.ctrlKey && !event.metaKey && sheet.hidden) {
      event.preventDefault();
      openGuide();
    }
  });
  window.addEventListener("hashchange", render);

  function startPolling(job) {
    stopPolling();
    poller = setInterval(job, POLL_MS);
  }

  function stopPolling() {
    if (poller) clearInterval(poller);
    poller = null;
  }

  /* ------------------------------------------------------------------ guide */

  // The guide knows every page and button, and what is wrong right now.
  // Answers come with Open buttons for the pages they mention and a few
  // follow-up questions to tap.
  const guideText = (text) => {
    const nodes = [];
    for (const [index, piece] of text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/).entries()) {
      if (!piece) continue;
      if (index % 2 === 0) nodes.push(piece);
      else if (piece.startsWith("**")) nodes.push(el("strong", { text: piece.slice(2, -2) }));
      else nodes.push(el("em", { text: piece.slice(1, -1) }));
    }
    return nodes;
  };

  async function openGuide() {
    const log = el("div", { class: "transcript guide-log" });
    const history = [];
    const input = el("input", {
      type: "text",
      "aria-label": "Ask the guide",
      placeholder: "Ask anything about Studio…",
    });
    const openRoute = (route) => {
      closeSheet();
      go(route.replace("/studio#", ""));
    };
    const openButtons = (links) =>
      links.length
        ? el(
            "div",
            { class: "chips guide-links" },
            links.map((link) =>
              el("button", {
                class: "secondary",
                type: "button",
                text: `Open ${link.label}`,
                onclick: () => openRoute(link.route),
              })
            )
          )
        : null;
    const suggest = (questions) =>
      questions.length
        ? el(
            "div",
            { class: "chips guide-suggest" },
            questions.map((question) =>
              el("button", { class: "chip", type: "button", text: question, onclick: () => ask(question) })
            )
          )
        : null;
    const intro = el("div", { class: "guide-intro" }, [
      el("p", { class: "muted", text: "I know every page and button in Studio, and I check this PC for problems." }),
    ]);
    async function ask(asked) {
      const question = (asked || input.value).trim();
      if (!question) return;
      input.value = "";
      for (const old of log.querySelectorAll(".guide-suggest")) old.remove();
      log.append(el("div", { class: "bubble user", text: question }));
      const waiting = el("div", { class: "bubble assistant muted", text: "Thinking…" });
      log.append(waiting);
      waiting.scrollIntoView({ block: "end" });
      try {
        const answer = await post("/studio/api/guide/ask", { question, history: history.slice(-8) });
        history.push({ role: "user", text: question }, { role: "assistant", text: answer.text });
        const links = answer.links && answer.links.length
          ? answer.links
          : answer.route
            ? [{ label: answer.route.replace("/studio#", ""), route: answer.route }]
            : [];
        waiting.replaceWith(
          el("div", { class: "bubble assistant" }, [
            el("span", { class: "who", text: answer.offline ? "Guide (built-in help)" : "Guide" }),
            ...guideText(answer.text),
          ])
        );
        const extras = [openButtons(links), suggest(answer.suggestions || [])].filter(Boolean);
        log.append(...extras);
        (extras[extras.length - 1] || log.lastChild).scrollIntoView({ block: "end" });
      } catch (error) {
        waiting.remove();
        notify(error.message);
      }
    }
    openSheet("Guide", [
      intro,
      log,
      el("form", {
        class: "row guide-ask",
        onsubmit: (event) => {
          event.preventDefault();
          ask();
        },
      }, [
        el("div", { class: "grow" }, [input]),
        el("button", { class: "primary", type: "submit", text: "Ask" }),
      ]),
    ]);
    input.focus();
    let overview = null;
    try {
      overview = await api("/studio/api/guide");
    } catch {
      return;
    }
    if (!intro.isConnected) return;
    const parts = [
      el("p", {
        class: "muted",
        text: overview.offline
          ? "No model is running for me yet, so I answer from built-in help. Load a model in LM Studio and I answer in my own words."
          : `I know every page and button in Studio, and I check this PC for problems. Answering with ${overview.model}.`,
      }),
    ];
    if (overview.problems.length) {
      parts.push(
        el("div", { class: "guide-problems", role: "status" }, [
          el("strong", { text: "Needs attention right now" }),
          ...overview.problems.map((problem) =>
            el("div", { class: "guide-problem" }, [
              el("span", { class: "grow" }, [el("strong", { text: problem.title }), el("br"), problem.fix]),
              problem.route
                ? el("button", { class: "secondary", type: "button", text: `Open ${problem.page}`, onclick: () => openRoute(problem.route) })
                : null,
            ])
          ),
        ])
      );
    } else {
      parts.push(el("p", { class: "guide-ok", text: "All systems look good." }));
    }
    parts.push(suggest(overview.starters));
    parts.push(
      el("details", { class: "guide-map" }, [
        el("summary", { text: "Where everything is" }),
        ...overview.topics.map((topic) =>
          el("div", { class: "guide-place" }, [
            el("span", { class: "grow" }, [el("strong", { text: topic.title }), el("br"), topic.where]),
            topic.route
              ? el("button", { class: "secondary", type: "button", text: `Open ${topic.page}`, onclick: () => openRoute(topic.route) })
              : el("button", { class: "secondary", type: "button", text: "Ask", onclick: () => ask(`Tell me about ${topic.title}`) }),
          ])
        ),
      ])
    );
    intro.replaceChildren(...parts.filter(Boolean));
  }

  /* ------------------------------------------------------------------ views */

  // Every Free Claude Code setting, inside the app. The settings page only
  // answers on the PC running Studio, so a phone gets directions instead.
  async function renderSettings() {
    const generation = renderGeneration;
    let here = false;
    try {
      here = (await fetch("/admin/api/status", { cache: "no-store" })).ok;
    } catch {
      here = false;
    }
    if (generation !== renderGeneration) return;
    if (!here) {
      view.replaceChildren(
        card("Settings", [
          el("p", {
            class: "muted",
            text: "Settings change on the PC running Studio: open the FCC Studio app there and choose Settings. They are kept off other devices so nobody else on your network can change them.",
          }),
        ])
      );
      return;
    }
    view.replaceChildren(
      el("iframe", { class: "settings-frame", src: "/admin/studio", title: "Free Claude Code settings" })
    );
  }

  async function renderChats() {
    const generation = renderGeneration;
    const [{ chats }, { agents }, { sites }] = await Promise.all([
      api("/studio/api/chats"),
      api("/studio/api/agents"),
      api("/studio/api/sites"),
    ]);
    const picker = el(
      "select",
      { id: "chat-agent" },
      agents.map((agent) =>
        el("option", { value: agent.id, text: `${agent.name} · ${agent.model}` })
      )
    );
    const nodes = [
      roomCreator(agents, sites),
      card("New chat", [
        agents.length
          ? picker
          : el("p", { class: "muted", text: "Create an agent first." }),
        el("button", {
          class: "primary",
          text: "Start chat",
          onclick: async () => {
            if (!agents.length) return go("agents");
            const chat = await post("/studio/api/chats", {
              agent_id: picker.value,
            });
            go(`chat/${chat.id}`);
          },
        }),
      ]),
      card(
        "All chats",
        chats.length
          ? chats.map((chat) =>
              el("button", {
                class: "list-item",
                onclick: () => go(chat.kind === "room" ? `room/${chat.id}` : `chat/${chat.id}`),
              }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: chat.title }),
                  el("span", { text: `${chat.kind} · ${when(chat.updated_at)}` }),
                ]),
                chat.settings && chat.settings.light_tuning
                  ? el("span", { class: "pill good", text: "tuned" })
                  : null,
              ])
            )
          : empty("No chats yet.")
      ),
    ];
    if (generation !== renderGeneration) return;
    view.replaceChildren(...nodes);
  }

  const modelBadge = (model) =>
    el("span", {
      class: `pill ${String(model).startsWith("local/") ? "good" : ""}`,
      text: String(model).startsWith("local/") ? "local" : "server",
    });

  function roomCreator(agents, sites = []) {
    const members = agents.filter((agent) => agent.role !== "guide");
    const title = el("input", { type: "text", placeholder: "Room name (optional)" });
    const project = el("select", {}, [
      el("option", { value: "", text: "No project (just talk)" }),
      el("option", { value: "__new__", text: "New project for this room" }),
      ...sites.map((site) => el("option", { value: site.id, text: site.name })),
    ]);
    const boxes = members.map((agent) => {
      const box = el("input", { type: "checkbox", value: agent.id });
      box.checked = true;
      return el("label", { class: "switch" }, [
        el("span", { class: "row" }, [agent.name, modelBadge(agent.model)]),
        box,
      ]);
    });
    return card(
      "Agent room",
      [
        el("p", {
          class: "muted",
          text: "Talk to several agents at once. They answer each other, hand work off with @Name, and finish tasks together. Mix local and server models.",
        }),
        title,
        el("label", {}, ["Project the agents build in", project]),
        ...(members.length ? boxes : [empty("Create an agent first.")]),
        el("button", {
          class: "primary",
          text: "Open room",
          onclick: async () => {
            const memberIds = boxes
              .map((label) => label.querySelector("input"))
              .filter((box) => box.checked)
              .map((box) => box.value);
            if (!memberIds.length) return notify("Pick at least one agent.");
            let siteId = project.value || null;
            if (siteId === "__new__") {
              const site = await post("/studio/api/sites", {
                name: title.value.trim() || "Team project",
              });
              siteId = site.id;
            }
            const room = await post("/studio/api/rooms", {
              title: title.value.trim(),
              member_ids: memberIds,
              site_id: siteId,
            });
            go(`room/${room.id}`);
          },
        }),
      ]
    );
  }

  async function renderRoom(roomId) {
    const generation = renderGeneration;
    const [data] = await Promise.all([api(`/studio/api/rooms/${roomId}`), refreshPending()]);
    setChrome("room", data.room.title);
    const status = el("div", { class: "row-between" });
    const log = el("div", { class: "transcript" });
    let lastSequence = 0;

    const paint = (detail) => {
      const settings = detail.room.settings || {};
      const taskStatus = settings.task_status || "idle";
      status.replaceChildren(
        el("span", { class: "grow" }, [
          el("strong", { text: settings.goal ? `Task: ${settings.goal}` : "No task yet" }),
          settings.summary
            ? el("p", { class: "muted", text: settings.summary })
            : null,
        ]),
        detail.running
          ? el("span", { class: "pill warn", text: "agents talking…" })
          : statusPill(taskStatus === "idle" ? "ready" : taskStatus === "done" ? "succeeded" : taskStatus)
      );
      for (const message of detail.messages) {
        if (message.sequence > lastSequence) {
          log.append(messageBubble(message));
          lastSequence = message.sequence;
        }
      }
    };

    const refresh = async () => {
      await refreshPending();
      const detail = await api(`/studio/api/rooms/${roomId}?after=${lastSequence}`);
      paint(detail);
      if (!detail.running) stopPolling();
      return detail;
    };

    const watch = () => startPolling(() => refresh().catch(() => stopPolling()));

    const goal = el("input", { type: "text", placeholder: "Build a landing page for my bakery" });
    const input = el("textarea", { placeholder: "Message the room — @Name to ask one agent", rows: "1" });

    if (generation !== renderGeneration) return;
    view.replaceChildren(
      data.room.site_id
        ? el("button", {
            class: "secondary",
            text: "Open the room's project",
            onclick: () => go(`site/${data.room.site_id}`),
          })
        : null,
      card("Members", [
        el(
          "div",
          { class: "row" },
          data.members.map((agent) =>
            el("span", { class: "pill" }, [`@${agent.name} `, modelBadge(agent.model)])
          )
        ),
      ]),
      card("Task", [
        status,
        goal,
        el("div", { class: "row" }, [
          el("button", {
            class: "primary",
            text: "Start task",
            onclick: async () => {
              if (!goal.value.trim()) return notify("Describe the task.");
              await post(`/studio/api/rooms/${roomId}/task`, { goal: goal.value.trim() });
              goal.value = "";
              await refresh();
              watch();
            },
          }),
          el("button", {
            class: "secondary",
            text: "Continue",
            onclick: async () => {
              await post(`/studio/api/rooms/${roomId}/continue`);
              watch();
            },
          }),
          el("button", {
            class: "danger",
            text: "Stop",
            onclick: async () => {
              await post(`/studio/api/rooms/${roomId}/stop`);
              notify("The agents will stop after this turn.");
            },
          }),
        ]),
      ]),
      log,
      el("div", { class: "composer" }, [
        el("div", { class: "grow" }, [input]),
        el("button", {
          class: "primary",
          text: "Send",
          onclick: async () => {
            const text = input.value.trim();
            if (!text) return;
            input.value = "";
            await post(`/studio/api/rooms/${roomId}/messages`, { text });
            await refresh();
            watch();
          },
        }),
      ])
    );
    paint(data);
    log.lastElementChild?.scrollIntoView({ block: "end" });
    if (data.running) watch();
  }

  async function renderChat(chatId) {
    const generation = renderGeneration;
    const [data] = await Promise.all([api(`/studio/api/chats/${chatId}`), refreshPending()]);
    const chat = data.chat;
    setChrome("chat", chat.title);
    const log = el(
      "div",
      { class: "transcript" },
      data.messages.map(messageBubble)
    );
    const input = el("textarea", { placeholder: "Message", rows: "1" });
    const send = el("button", { class: "primary", text: "Send" });
    send.addEventListener("click", async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      log.append(el("div", { class: "bubble user", text }));
      send.disabled = true;
      send.textContent = "…";
      // Show tool steps and approval requests while the agent is still working.
      let seen = data.messages.length ? data.messages[data.messages.length - 1].sequence : 0;
      let sentShown = false;
      const live = setInterval(async () => {
        try {
          await refreshPending();
          const fresh = await api(`/studio/api/chats/${chatId}?after=${seen}`);
          for (const message of fresh.messages) {
            seen = message.sequence;
            if (message.role === "user" && !sentShown) {
              sentShown = true;
              continue;
            }
            log.append(messageBubble(message));
            log.lastElementChild?.scrollIntoView({ block: "end" });
          }
        } catch {
          /* the final reply below repaints everything */
        }
      }, 1500);
      try {
        const reply = await post(`/studio/api/chats/${chatId}/messages`, { text });
        await refreshPending();
        log.replaceChildren(...reply.messages.map(messageBubble));
        log.lastElementChild?.scrollIntoView({ block: "end" });
      } catch (error) {
        notify(error.message);
      } finally {
        clearInterval(live);
        send.disabled = false;
        send.textContent = "Send";
      }
    });

    if (generation !== renderGeneration) return;
    view.replaceChildren(
      el("div", { class: "row-between" }, [
        el("span", { class: "pill", text: chat.kind }),
        el("button", {
          class: "secondary",
          text: "Chat settings",
          onclick: () => openChatSettings(chat),
        }),
      ]),
      log,
      el("div", { class: "composer" }, [
        el("div", { class: "grow" }, [input]),
        send,
      ])
    );
    log.lastElementChild?.scrollIntoView({ block: "end" });
  }

  let pendingCommands = new Set();

  async function refreshPending() {
    try {
      const data = await api("/studio/api/commands/pending");
      pendingCommands = new Set(data.pending.map((item) => item.id));
      return data;
    } catch {
      return { pending: [], policy: "off" };
    }
  }

  function approvalButtons(requestId, holder) {
    const decide = (approve) => async () => {
      try {
        await post(`/studio/api/commands/${requestId}/${approve ? "approve" : "deny"}`);
        pendingCommands.delete(requestId);
        holder.replaceChildren(
          el("span", { class: `pill ${approve ? "good" : "bad"}`, text: approve ? "approved, running" : "denied" })
        );
      } catch (error) {
        notify(error.message);
      }
    };
    return [
      el("button", { class: "primary", text: "Run it", onclick: decide(true) }),
      el("button", { class: "danger", text: "Deny", onclick: decide(false) }),
    ];
  }

  function messageBubble(message) {
    const role = ["user", "assistant", "tool", "event"].includes(message.role)
      ? message.role
      : "event";
    if (message.data && message.data.kind === "approval") {
      const requestId = message.data.request_id;
      const actions = el("div", { class: "row" });
      if (pendingCommands.has(requestId)) {
        actions.append(...approvalButtons(requestId, actions));
      } else {
        actions.append(el("span", { class: "pill", text: "decided" }));
      }
      return el("div", { class: "bubble event approval" }, [
        el("span", { class: "who", text: "Command approval" }),
        el("code", { class: "command", text: message.data.command || message.text }),
        actions,
      ]);
    }
    const links = (message.data && message.data.links) || [];
    return el("div", { class: `bubble ${role}` }, [
      message.author && role !== "user"
        ? el("span", { class: "who", text: message.author })
        : null,
      ...(links.length ? guideText(message.text) : [message.text]),
      links.length
        ? el(
            "div",
            { class: "chips guide-links" },
            links.map((link) =>
              el("button", {
                class: "secondary",
                type: "button",
                text: `Open ${link.label}`,
                onclick: () => go(link.route.replace("/studio#", "")),
              })
            )
          )
        : null,
    ]);
  }

  function openChatSettings(chat) {
    const settings = chat.settings || {};
    const toggle = (key, label, hint) => {
      const input = el("input", { type: "checkbox" });
      input.checked = Boolean(settings[key]);
      input.addEventListener("change", async () => {
        try {
          const result = await post(`/studio/api/chats/${chat.id}/settings`, {
            settings: { [key]: input.checked },
          });
          if (result.note) notify(result.note);
          if (result.opened_chat) {
            closeSheet();
            go(`chat/${result.opened_chat.id}`);
          }
        } catch (error) {
          input.checked = !input.checked;
          notify(error.message);
        }
      });
      return el("div", {}, [
        el("label", { class: "switch" }, [label, input]),
        el("p", { class: "muted", text: hint }),
      ]);
    };
    openSheet("Chat settings", [
      toggle(
        "light_tuning",
        "Very light tuning",
        "Turning this on opens a fresh chat bound to a tune pack for this agent."
      ),
      toggle(
        "teacher_mode",
        "AI teacher",
        "Opens a classroom where the teacher agent teaches and then tests the student agent."
      ),
      el("button", {
        class: "secondary",
        text: "Save this chat to Obsidian",
        onclick: async () => {
          try {
            const result = await post("/studio/api/obsidian/sync", {
              chat_id: chat.id,
            });
            notify(`Wrote ${result.note}`);
          } catch (error) {
            notify(error.message);
          }
        },
      }),
      el("button", {
        class: "danger",
        text: "Delete chat",
        onclick: async () => {
          await remove(`/studio/api/chats/${chat.id}`);
          closeSheet();
          go("chats");
        },
      }),
    ]);
  }

  async function renderAgents() {
    const generation = renderGeneration;
    const [{ agents }, { sites }, { runs }] = await Promise.all([
      api("/studio/api/agents"),
      api("/studio/api/sites"),
      api("/studio/api/tasks"),
    ]);
    const nodes = [
      card("Run an agent task", [
        el("p", {
          class: "muted",
          text: "The agent searches the web, writes a whole website or app into a project, runs commands if you allow it, checks its work, then reports back.",
        }),
        ...taskForm(agents, sites),
      ]),
      card(
        "Agents",
        agents.length
          ? agents.map((agent) =>
              el(
                "button",
                { class: "list-item", onclick: () => go(`agent/${agent.id}`) },
                [
                  el("span", { class: "grow" }, [
                    el("strong", { text: agent.name }),
                    el("span", { text: `${agent.role} · ${agent.model}` }),
                  ]),
                  agent.tune_pack_id
                    ? el("span", { class: "pill good", text: "tuned" })
                    : null,
                ]
              )
            )
          : empty("No agents yet.")
      ),
      card("Team brains", [
        el("p", {
          class: "muted",
          text: "Give each agent its own AI model: a coding model for the Builder, a bigger one for the Researcher, a quick one for Jarvis.",
        }),
        el("button", { class: "primary", type: "button", text: "Choose each agent's model", onclick: () => openTeamBrains(() => render()) }),
      ]),
      card("Add an agent", [
        el("p", {
          class: "muted",
          text: "Give it a name, a role, a model, and the tools it may use: building, running code, the internet, deep research, or asking the Researcher for help.",
        }),
        el("button", { class: "primary", text: "+ New agent", onclick: () => openAddAgent() }),
      ]),
      card(
        "Recent tasks",
        runs.length
          ? runs
              .slice(0, 8)
              .map((run) =>
                el("button", { class: "list-item", onclick: () => go(`task/${run.id}`) }, [
                  el("span", { class: "grow" }, [
                    el("strong", { text: run.goal }),
                    el("span", { text: when(run.created_at) }),
                  ]),
                  statusPill(run.status),
                ])
              )
          : empty("No agent tasks yet.")
      ),
      card(
        "Projects",
        sites.length
          ? sites.map((site) =>
              el("button", { class: "list-item", onclick: () => go(`site/${site.id}`) }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: site.name }),
                  el("span", { text: `${site.file_count} files` }),
                ]),
                el("span", { class: "pill", text: "open" }),
              ])
            )
          : empty("No projects yet. Create one when you start a build task.")
      ),
    ];
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      ...nodes,
      el("button", { class: "fab", "aria-label": "Add an agent", text: "+", onclick: () => openAddAgent() })
    );
  }

  // Pick the model the main AI (or every agent) thinks with, from the models
  // on this PC, or from a .gguf file chosen in a normal file window.
  function openBrainPicker(mainName, onDone) {
    const who = mainName || "the main AI";
    const everyone = el("input", { type: "checkbox" });
    const status = el("p", { class: "muted", role: "status" });
    const list = el("div", { class: "stack" });
    const use = async (model) => {
      const name = model.replace(/^local\//, "");
      status.textContent = `Switching to ${name}…`;
      try {
        await post("/studio/api/models/use", { model, everyone: everyone.checked });
      } catch (error) {
        status.textContent = error.message;
        return;
      }
      closeSheet();
      notify(everyone.checked ? `Every agent now thinks with ${name}.` : `${who} now thinks with ${name}.`);
      if (onDone) onDone();
    };
    const load = async () => {
      list.replaceChildren(el("p", { class: "muted", text: "Looking for models on this PC…" }));
      let local;
      try {
        local = (await api("/studio/api/models/available")).local;
      } catch (error) {
        list.replaceChildren(el("p", { class: "muted", text: error.message }));
        return;
      }
      const models = local.models.filter((model) => !/embed/i.test(model));
      if (!local.reachable) {
        list.replaceChildren(
          el("p", {
            class: "muted",
            text: "LM Studio isn't answering. In LM Studio open Developer and set Status to Running, then press Refresh.",
          })
        );
      } else if (!models.length) {
        list.replaceChildren(
          el("p", { class: "muted", text: "No models in LM Studio yet. Use “Find a model file on this PC” below." })
        );
      } else {
        list.replaceChildren(
          ...models.map((model) =>
            el("div", { class: "list-item" }, [
              el("span", { class: "grow" }, [el("strong", { text: model.replace(/^local\//, "") })]),
              el("button", {
                class: "primary",
                type: "button",
                text: "Use",
                "aria-label": `Use ${model.replace(/^local\//, "")}`,
                onclick: () => use(model),
              }),
            ])
          )
        );
      }
    };
    const find = el("button", {
      class: "secondary",
      type: "button",
      text: "Find a model file on this PC…",
      onclick: async () => {
        find.disabled = true;
        status.textContent = "A file window opened on the PC running Studio. Choose a .gguf model file.";
        try {
          const body = await post("/studio/api/models/pick-file");
          if (!body.picked) status.textContent = "No file chosen.";
          else if (body.model) {
            status.textContent = `Added ${body.path}`;
            await use(body.model);
          } else {
            status.textContent = body.note;
            await load();
          }
        } catch (error) {
          status.textContent = error.message;
        } finally {
          find.disabled = false;
        }
      },
    });
    openSheet(`Choose ${who}'s brain`, [
      el("p", {
        class: "muted",
        text: "Pick a model on this PC. It runs in LM Studio, so nothing leaves your computer.",
      }),
      list,
      el("label", { class: "check" }, [everyone, "Use it for every agent too"]),
      el("div", { class: "row" }, [
        find,
        el("button", { class: "secondary", type: "button", text: "Refresh", onclick: () => load() }),
      ]),
      el("button", {
        class: "secondary",
        type: "button",
        text: "Give each agent its own brain…",
        onclick: () => openTeamBrains(onDone),
      }),
      status,
    ]);
    load();
  }

  // Team brains: a different model for each agent.
  async function openTeamBrains(onDone) {
    let data;
    try {
      data = await api("/studio/api/team-models");
    } catch (error) {
      notify(error.message);
      return;
    }
    const localModels = (data.local.models || []).filter((model) => !/embed/i.test(model));
    const serverModels = data.server || [];
    const label = (model) => model.replace(/^local\//, "");
    const pickers = new Map();
    const status = el("p", { class: "muted", role: "status" });
    const picker = (row) => {
      const known = new Set([...localModels, ...serverModels]);
      const groups = [
        el("optgroup", { label: "On this PC (LM Studio)" }, localModels.map((model) => el("option", { value: model, text: label(model) }))),
        el("optgroup", { label: "Server (needs a key)" }, serverModels.map((model) => el("option", { value: model, text: model }))),
      ];
      if (!known.has(row.model)) groups.unshift(el("option", { value: row.model, text: `${label(row.model)} (not found)` }));
      const select = el("select", { "aria-label": `Model for ${row.name}` }, groups);
      select.value = row.model;
      pickers.set(row.id, select);
      return select;
    };
    const rows = data.agents.map((row) =>
      el("div", { class: "brain-row" }, [
        el("div", { class: "brain-who" }, [
          el("strong", { text: row.name }),
          el("span", { class: "muted", text: row.role }),
        ]),
        picker(row),
        row.note ? el("p", { class: "muted brain-note", text: row.note }) : null,
        row.private
          ? el("p", { class: "muted brain-note brain-private", text: "Server AI: can't see your memory or Obsidian. Jarvis briefs it when you give it a job." })
          : null,
      ])
    );
    const distinct = () =>
      new Set([...pickers.values()].map((select) => select.value).filter((model) => model.startsWith("local/"))).size;
    const advice = el("p", { class: "muted brain-advice" });
    const explain = () => {
      const count = distinct();
      advice.textContent = !data.local.reachable
        ? "LM Studio isn't answering, so only server models can be picked. In LM Studio open Developer and set Status to Running."
        : localModels.length <= 1
        ? "LM Studio lists only one model. To give agents different ones, download more in LM Studio and turn on Just-in-Time model loading (Developer → Settings); then every downloaded model shows here."
        : count > 1
          ? `${count} different models on this PC. ${data.turns ? "They take turns (one works at a time) so an 8 GB card isn't swapping models on every step." : "Local Models Take Turns is off, so they may all try to load at once."} In LM Studio, turn on Just-in-Time model loading (Developer → Settings) so it can load whichever one an agent asks for.`
          : "Pick a model for each agent. Coding models suit the Builder and Tester; a bigger model suits the Researcher; a quick one suits Jarvis.";
    };
    for (const select of pickers.values()) select.addEventListener("change", explain);
    explain();
    const suggest = el("button", {
      class: "secondary",
      type: "button",
      text: "Suggest a mix",
      onclick: async () => {
        try {
          const { assignments } = await api("/studio/api/team-models/suggest");
          const entries = Object.entries(assignments);
          if (!entries.length) {
            status.textContent = "No models on this PC to suggest from. Download some in LM Studio first.";
            return;
          }
          for (const [agentId, model] of entries) {
            const select = pickers.get(agentId);
            if (select) select.value = model;
          }
          explain();
          status.textContent = "Suggested from the models on this PC. Change any, then Save.";
        } catch (error) {
          status.textContent = error.message;
        }
      },
    });
    const save = el("button", {
      class: "primary",
      type: "button",
      text: "Save",
      onclick: async () => {
        const assignments = {};
        for (const row of data.agents) {
          const value = pickers.get(row.id).value;
          if (value && value !== row.model) assignments[row.id] = value;
        }
        if (!Object.keys(assignments).length) {
          closeSheet();
          return;
        }
        save.disabled = true;
        try {
          const { changed } = await post("/studio/api/team-models", { assignments });
          closeSheet();
          notify(`${changed.length} agent${changed.length === 1 ? "" : "s"} switched model.`);
          if (onDone) onDone();
        } catch (error) {
          status.textContent = error.message;
          save.disabled = false;
        }
      },
    });
    openSheet("Team brains", [
      el("p", { class: "muted", text: "Give each agent its own AI model, so they aren't all the same AI." }),
      data.private_memory
        ? el("p", { class: "muted", text: "Your memory stays on this PC: agents on server AIs can't read it. Jarvis writes them a briefing with only what the job needs." })
        : null,
      ...rows,
      advice,
      el("div", { class: "row" }, [suggest, save]),
      status,
    ]);
  }

  async function openAddAgent(onCreated) {
    let options;
    try {
      options = await api("/studio/api/agent-options");
    } catch (error) {
      return notify(error.message);
    }
    modelList().catch(() => {});
    const name = el("input", { type: "text", placeholder: "e.g. Pixel", "aria-label": "Name" });
    const role = el(
      "select",
      { "aria-label": "Role" },
      options.roles.map((row) => el("option", { value: row.role, text: row.role }))
    );
    const roleNote = el("p", { class: "muted" });
    const model = el("input", {
      type: "text",
      list: "model-list",
      "aria-label": "Model",
      placeholder: "Leave empty for the default, or local/<model>",
    });
    const prompt = el("textarea", { "aria-label": "Instructions", placeholder: "What this agent is for and how it should work." });
    const boxes = new Map();
    const groups = options.tool_groups.map((group) =>
      el("fieldset", { class: "tool-group" }, [
        el("legend", { text: group.label }),
        ...group.tools.map((tool) => {
          const box = el("input", { type: "checkbox", value: tool.name });
          boxes.set(tool.name, box);
          return el("label", { class: "check", title: tool.description }, [box, el("span", { text: tool.name.replace(/_/g, " ") })]);
        }),
      ])
    );
    const showNote = () => {
      roleNote.textContent = (options.roles.find((row) => row.role === role.value) || {}).note || "";
    };
    role.addEventListener("change", showNote);
    const presetButtons = el("div", { class: "chips" });
    const applyPreset = (preset) => {
      role.value = preset.role;
      prompt.value = preset.prompt;
      for (const [tool, box] of boxes) box.checked = preset.tools.includes(tool);
      for (const chip of presetButtons.children) chip.setAttribute("aria-pressed", String(chip.dataset.name === preset.name));
      showNote();
    };
    presetButtons.append(
      ...options.presets.map((preset) =>
        el("button", { class: "chip", type: "button", "data-name": preset.name, "aria-pressed": "false", text: preset.name, onclick: () => applyPreset(preset) })
      )
    );
    applyPreset(options.presets[0]);
    openSheet("New agent", [
      el("p", { class: "muted", text: "Start from a preset, then change anything." }),
      presetButtons,
      el("label", {}, ["Name", name]),
      el("label", {}, ["Role", role]),
      roleNote,
      el("label", {}, ["Model", model]),
      el("label", {}, ["Instructions", prompt]),
      ...groups,
      el("button", {
        class: "primary",
        text: "Create agent",
        onclick: async () => {
          if (!name.value.trim()) return notify("Name the agent.");
          const tools = [...boxes].filter(([, box]) => box.checked).map(([tool]) => tool);
          try {
            const agent = await post("/studio/api/agents", {
              name: name.value.trim(),
              role: role.value,
              model: model.value.trim(),
              system_prompt: prompt.value.trim(),
              tools: [...tools, "finish"],
            });
            closeSheet();
            notify(`${agent.name} joined the team.`);
            if (onCreated) onCreated(agent);
            else go(`agent/${agent.id}`);
          } catch (error) {
            notify(error.message);
          }
        },
      }),
    ]);
  }

  function taskForm(agents, sites) {
    const agentPicker = el(
      "select",
      {},
      agents
        .filter((agent) => agent.role !== "guide")
        .map((agent) => el("option", { value: agent.id, text: agent.name }))
    );
    const sitePicker = el("select", {}, [
      el("option", { value: "", text: "No project" }),
      el("option", { value: "__new__", text: "Create a new project" }),
      ...sites.map((site) => el("option", { value: site.id, text: site.name })),
    ]);
    const goal = el("textarea", {
      placeholder: "Build a to-do app with a Python backend and a clean web UI.",
    });
    return [
      el("label", {}, ["Agent", agentPicker]),
      el("label", {}, ["Project", sitePicker]),
      goal,
      el("button", {
        class: "primary",
        text: "Start task",
        onclick: async () => {
          if (!goal.value.trim()) return notify("Give the agent a goal.");
          let siteId = sitePicker.value;
          if (siteId === "__new__") {
            const site = await post("/studio/api/sites", {
              name: goal.value.trim().slice(0, 32) || "New site",
            });
            siteId = site.id;
          }
          const run = await post("/studio/api/tasks", {
            agent_id: agentPicker.value,
            goal: goal.value.trim(),
            site_id: siteId || null,
          });
          go(`task/${run.id}`);
        },
      }),
    ];
  }

  async function renderAgent(agentId) {
    const generation = renderGeneration;
    const [{ agents }, { memories }, { skills }] = await Promise.all([
      api("/studio/api/agents"),
      api(`/studio/api/memory/${agentId}`),
      api(`/studio/api/agents/${agentId}/skills`),
    ]);
    const agent = agents.find((item) => item.id === agentId);
    if (!agent) return go("agents");
    setChrome("agent", agent.name);
    const memoryInput = el("input", { type: "text", placeholder: "Teach it a fact" });
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      card(agent.name, [
        el("div", { class: "kv" }, [
          el("span", { text: "Role" }),
          el("span", { text: agent.role }),
          el("span", { text: "Model" }),
          el("span", { text: agent.model }),
          el("span", { text: "Tools" }),
          el("span", { text: (agent.tools || []).join(", ") || "none" }),
          el("span", { text: "Memory" }),
          el("span", { text: agent.memory_enabled ? "on" : "off" }),
        ]),
        modelEditor(agent),
        el("div", { class: "row" }, [
          el("button", {
            class: "primary",
            text: "Chat",
            onclick: async () => {
              const chat = await post("/studio/api/chats", { agent_id: agent.id });
              go(`chat/${chat.id}`);
            },
          }),
          el("button", {
            class: "secondary",
            text: "Tune",
            onclick: () => go(`tune/${agent.id}`),
          }),
          el("button", {
            class: "secondary",
            text: "To Obsidian",
            onclick: async () => {
              const result = await post("/studio/api/obsidian/sync", {
                agent_id: agent.id,
              });
              notify(`Wrote ${result.note}`);
            },
          }),
        ]),
      ]),
      teachCard(agent, skills),
      card(
        "Memory",
        [
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [memoryInput]),
            el("button", {
              class: "secondary",
              text: "Add",
              onclick: async () => {
                if (!memoryInput.value.trim()) return;
                await post(`/studio/api/memory/${agent.id}`, {
                  text: memoryInput.value.trim(),
                });
                memoryInput.value = "";
                render();
              },
            }),
          ]),
          ...(memories.length
            ? memories.map((entry) =>
                el("div", { class: "list-item" }, [
                  el("span", { class: "grow" }, [
                    el("strong", { text: entry.text }),
                    el("span", { text: `${entry.scope} · ${entry.hits} recalls` }),
                  ]),
                  el("button", {
                    class: "danger",
                    text: "✕",
                    onclick: async () => {
                      await remove(`/studio/api/memory/entry/${entry.id}`);
                      render();
                    },
                  }),
                ])
              )
            : [empty("Nothing remembered yet.")]),
        ]
      )
    );
  }

  function teachCard(agent, skills) {
    const link = el("input", {
      type: "url",
      placeholder: "https://… docs page, Reddit thread, or YouTube video",
    });
    const notes = el("textarea", {
      placeholder: "Or write it out: a tool, a command, a code pattern, how you like things done.",
    });
    const button = el("button", {
      class: "primary",
      text: "Teach",
      onclick: async () => {
        if (!link.value.trim() && !notes.value.trim()) return notify("Add a link or some notes.");
        button.disabled = true;
        button.textContent = "Learning…";
        try {
          await post(`/studio/api/agents/${agent.id}/teach`, { url: link.value.trim(), text: notes.value.trim() });
          notify(`${agent.name} learned it.`);
          render();
        } catch (error) {
          notify(error.message);
          button.disabled = false;
          button.textContent = "Teach";
        }
      },
    });
    return card(
      "Teach a skill",
      [
        el("label", {}, ["Link", link]),
        el("label", {}, ["Notes", notes]),
        button,
        ...(skills.length
          ? skills.map((skill) =>
              el("div", { class: "list-item" }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: skill.text.split("\n")[0] }),
                  el("span", { class: "pre", text: skill.text.split("\n").slice(1).join("\n") }),
                ]),
                el("button", {
                  class: "danger",
                  "aria-label": "Forget this skill",
                  text: "✕",
                  onclick: async () => {
                    await remove(`/studio/api/memory/entry/${skill.id}`);
                    render();
                  },
                }),
              ])
            )
          : [empty("No skills yet.")]),
      ],
      `${agent.name} reads the link, keeps a short how-to, and follows it whenever it fits. Reddit threads and YouTube videos work too.`
    );
  }

  async function renderTask(runId) {
    const generation = renderGeneration;
    const [data] = await Promise.all([api(`/studio/api/tasks/${runId}`), refreshPending()]);
    setChrome("task", "Agent task");
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      card(data.run.goal, [
        el("div", { class: "row-between" }, [
          statusPill(data.run.status),
          el("span", {
            class: "pill",
            text: `${data.run.step}/${data.run.max_steps} steps`,
          }),
        ]),
        meter(data.run.step / Math.max(1, data.run.max_steps)),
        data.run.site_id
          ? el("button", {
              class: "secondary",
              text: "Open the site",
              onclick: () => go(`site/${data.run.site_id}`),
            })
          : null,
      ]),
      el("div", { class: "transcript" }, data.messages.map(messageBubble))
    );
    if (["queued", "running"].includes(data.run.status)) {
      startPolling(() => renderTask(runId).catch(() => stopPolling()));
    } else {
      stopPolling();
    }
  }

  async function renderSite(siteId) {
    const generation = renderGeneration;
    const data = await api(`/studio/api/sites/${siteId}/files`);
    setChrome("site", data.site.name);
    const key = token();
    const preview = `/studio/sites/${siteId}/index.html${key ? `?token=${encodeURIComponent(key)}` : ""}`;
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      card("Preview", [
        el("iframe", { class: "preview-frame", src: preview, title: "Site preview" }),
        el("div", { class: "row" }, [
          el("a", {
            class: "pill",
            href: preview,
            target: "_blank",
            rel: "noreferrer",
            text: "Open full screen",
          }),
          el("a", {
            class: "pill",
            href: `/studio/api/sites/${siteId}/archive${key ? `?token=${encodeURIComponent(key)}` : ""}`,
            text: "Download .zip",
          }),
        ]),
      ]),
      card(
        "Files",
        data.files.length
          ? data.files.map((file) =>
              el("div", { class: "list-item" }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: file.path }),
                  el("span", { text: bytes(file.size) }),
                ]),
                el("button", {
                  class: "secondary",
                  text: "Edit",
                  onclick: () => editSiteFile(siteId, file.path),
                }),
              ])
            )
          : empty("The agent has not written any files yet.")
      )
    );
  }

  async function editSiteFile(siteId, path) {
    const preview = await fetch(
      `/studio/sites/${siteId}/${path}${token() ? `?token=${encodeURIComponent(token())}` : ""}`
    );
    const body = await preview.text();
    const editor = el("textarea", { rows: "14" });
    editor.value = body;
    openSheet(path, [
      editor,
      el("button", {
        class: "primary",
        text: "Save",
        onclick: async () => {
          await put(`/studio/api/sites/${siteId}/files`, {
            path,
            content: editor.value,
          });
          closeSheet();
          notify("Saved.");
          render();
        },
      }),
    ]);
  }

  async function renderLearn() {
    const generation = renderGeneration;
    const [data, { agents }] = await Promise.all([
      api("/studio/api/school/courses"),
      api("/studio/api/agents"),
    ]);
    const candidates = agents.filter((agent) => agent.role !== "guide");
    const isLocal = (agent) => agent.model.startsWith("local/");
    const first = (test, exclude) =>
      candidates.find((agent) => agent.id !== exclude && test(agent));
    // Prefer a server teacher and a local student: the server teaches the local model.
    const teacherDefault =
      first((agent) => agent.role === "teacher") ||
      first((agent) => !isLocal(agent)) ||
      candidates[0];
    const teacherId = teacherDefault ? teacherDefault.id : "";
    const studentDefault =
      first((agent) => agent.role === "student", teacherId) ||
      first(isLocal, teacherId) ||
      first(() => true, teacherId);
    const agentPicker = (chosen) =>
      el(
        "select",
        {},
        candidates.map((agent) =>
          el("option", {
            value: agent.id,
            text: `${agent.name} · ${isLocal(agent) ? "local" : "server"} · ${agent.model}`,
            selected: chosen !== undefined && agent.id === chosen.id,
          })
        )
      );
    const teacherPicker = agentPicker(teacherDefault);
    const studentPicker = agentPicker(studentDefault);
    const topic = el("input", {
      type: "text",
      placeholder: "Tide prediction for beginners",
    });
    const count = el("input", { type: "number", value: "3", min: "2", max: "6" });
    const nodes = [
      card(
        "Open a class",
        [
          el("p", {
            class: "muted",
            text: "The teacher agent plans lessons, teaches the student agent in a shared chat, then tests it and grades every answer.",
          }),
          el("label", {}, ["Topic", topic]),
          el("label", {}, ["Teacher", teacherPicker]),
          el("label", {}, ["Student", studentPicker]),
          el("p", {
            class: "muted",
            text: "A server model teaching a local model works best: the teacher plans, explains, writes the test, and grades; what the student learns goes into its memory.",
          }),
          el("label", {}, ["Lessons", count]),
          el("button", {
            class: "primary",
            text: "Start class",
            onclick: async () => {
              if (!topic.value.trim()) return notify("Pick a topic.");
              const course = await post("/studio/api/school/courses", {
                topic: topic.value.trim(),
                lesson_count: Number(count.value) || 3,
                start: true,
                teacher_id: teacherPicker.value,
                student_id: studentPicker.value,
              });
              go(`class/${course.id}`);
            },
          }),
          data.enabled
            ? null
            : el("p", {
                class: "muted",
                text: "Tip: turn on AI teacher in Studio settings to show the classroom on the home screen.",
              }),
        ]
      ),
      card(
        "Classes",
        data.courses.length
          ? data.courses.map((course) =>
              el("button", { class: "list-item", onclick: () => go(`class/${course.id}`) }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: course.topic }),
                  el("span", {
                    text:
                      course.score != null
                        ? `${percent(course.score)} · ${course.lesson_done}/${course.lesson_total} lessons`
                        : `${course.lesson_done}/${course.lesson_total} lessons`,
                  }),
                ]),
                statusPill(course.status),
              ])
            )
          : empty("No classes yet.")
      ),
    ];
    if (generation !== renderGeneration) return;
    view.replaceChildren(...nodes);
  }

  async function renderClass(courseId) {
    const generation = renderGeneration;
    const data = await api(`/studio/api/school/courses/${courseId}`);
    const course = data.course;
    setChrome("class", course.topic);
    const questions = data.questions || [];
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      card("Progress", [
        el("div", { class: "row-between" }, [
          statusPill(course.status),
          el("span", {
            class: "pill",
            text: `${course.lesson_done}/${course.lesson_total} lessons`,
          }),
        ]),
        meter(data.progress || 0),
        course.score != null
          ? el("p", {
              class: "muted",
              text: `Test score ${percent(course.score)} — ${course.passed ? "passed" : "below the pass mark"}.`,
            })
          : null,
        el("div", { class: "row" }, [
          el("button", {
            class: "secondary",
            text: "Run again",
            onclick: async () => {
              await post(`/studio/api/school/courses/${courseId}/start`);
              notify("Class started.");
            },
          }),
          el("button", {
            class: "secondary",
            text: "To Obsidian",
            onclick: async () => {
              const result = await post("/studio/api/obsidian/sync", {
                course_id: courseId,
              });
              notify(`Wrote ${result.note}`);
            },
          }),
        ]),
      ]),
      card(
        "Lessons",
        (data.lessons || []).length
          ? data.lessons.map((lesson) =>
              el("div", { class: "list-item" }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: `${lesson.ordinal}. ${lesson.topic}` }),
                  el("span", { text: lesson.notes || lesson.objective }),
                ]),
                statusPill(lesson.status),
              ])
            )
          : empty("The teacher is still planning.")
      ),
      questions.length
        ? card(
            "Test",
            questions.map((question) =>
              el("div", { class: "card" }, [
                el("div", { class: "row-between" }, [
                  el("strong", { text: `Q${question.ordinal}` }),
                  el("span", {
                    class: `pill ${question.score >= course.pass_mark ? "good" : "bad"}`,
                    text: question.score == null ? "—" : percent(question.score),
                  }),
                ]),
                el("p", { class: "muted", text: question.prompt }),
                el("p", { text: question.answer }),
                question.feedback
                  ? el("p", { class: "muted", text: question.feedback })
                  : null,
              ])
            )
          )
        : null,
      card(
        "Classroom",
        el("div", { class: "transcript" }, (data.messages || []).map(messageBubble))
      )
    );
    if (["planning", "teaching", "examining"].includes(course.status)) {
      startPolling(() => renderClass(courseId).catch(() => stopPolling()));
    } else {
      stopPolling();
    }
  }

  // Model Control: the built-in engine, like LM Studio inside Studio.
  const CONTEXT_STEPS = [2048, 4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 131072];
  let engineTimer = 0;

  async function renderEngine() {
    const generation = renderGeneration;
    clearTimeout(engineTimer);
    const data = await api("/studio/api/engine");
    if (generation !== renderGeneration) return;
    const status = el("p", { class: "muted", role: "status" });
    const act = async (label, work) => {
      status.textContent = `${label}…`;
      try {
        await work();
        status.textContent = "";
        render();
      } catch (error) {
        status.textContent = error.message;
      }
    };
    const install = data.install;
    const installing = ["checking", "downloading", "unpacking"].includes(install.state);
    const use = el("input", { type: "checkbox", checked: data.on, "aria-label": "Use the built-in engine" });
    use.addEventListener("change", () =>
      act(use.checked ? "Switching to the built-in engine" : "Going back to LM Studio", () =>
        post("/studio/api/engine/use", { on: use.checked })
      )
    );
    const state = !data.installed
      ? "Not installed"
      : data.running
      ? `Running · llama.cpp ${data.version || ""} · ${data.url}`
      : `Stopped · llama.cpp ${data.version || ""}`;
    const engineCard = card("Engine", [
      el("p", { class: "engine-state" }, [
        el("span", { class: `hud-dot${data.running ? " on" : ""}`, "aria-hidden": "true" }),
        el("strong", { text: state }),
      ]),
      el("label", { class: "check" }, [use, "Use the built-in engine for local models (instead of LM Studio)"]),
      installing
        ? el("div", {}, [
            el("p", { class: "muted", text: `${install.state === "downloading" ? `Downloading llama.cpp ${install.version}` : install.state === "unpacking" ? "Unpacking" : "Finding the latest llama.cpp"}… ${install.total ? `${bytes(install.done)} of ${bytes(install.total)}` : ""}` }),
            meter(install.total ? install.done / install.total : 0),
          ])
        : null,
      install.state === "failed" ? el("p", { class: "muted", text: `Download failed: ${install.error}` }) : null,
      el("div", { class: "row" }, [
        data.version === "your own build" ? null : el("button", {
          class: data.installed ? "secondary" : "primary",
          type: "button",
          text: data.installed ? "Update engine" : "Install engine",
          disabled: installing,
          onclick: () => act("Starting the download", () => post("/studio/api/engine/install")),
        }),
        data.installed
          ? el("button", {
              class: data.running ? "secondary" : "primary",
              type: "button",
              text: data.running ? "Stop" : "Start",
              onclick: () =>
                act(data.running ? "Stopping" : "Starting the engine", () =>
                  post(`/studio/api/engine/${data.running ? "stop" : "start"}`)
                ),
            })
          : null,
        el("button", { class: "secondary", type: "button", text: "Team brains", onclick: () => openTeamBrains(() => render()) }),
      ]),
      status,
    ], `Studio runs your models itself with llama.cpp (${data.build === "cpu" ? "processor build" : "graphics card build, Vulkan"}). Models load when an agent needs them; ${data.models_at_once} at a time.`);

    const models = data.models.length
      ? data.models.map((model) => engineModelRow(model, data, act))
      : [empty("No .gguf models found. Download some in LM Studio or on the Models page, or add a folder in Settings (Extra Model Folders).")];
    const folders = card(
      "Model folders",
      data.folders.map((folder) =>
        el("div", { class: "list-item" }, [
          el("span", { class: "grow engine-folder" }, [el("strong", { text: folder.source }), el("br"), el("span", { class: "muted", text: folder.path })]),
          el("span", { class: `pill ${folder.exists ? "good" : "warn"}`, text: folder.exists ? "found" : "missing" }),
        ])
      ),
      "Studio finds models in these folders. Add more in Settings: Extra Model Folders."
    );
    const log = el("pre", { class: "engine-log", text: "" });
    const logs = el("details", { class: "card engine-logs" }, [
      el("summary", { text: "Engine log" }),
      log,
    ]);
    logs.addEventListener("toggle", async () => {
      if (!logs.open) return;
      try {
        const { lines } = await api("/studio/api/engine/logs");
        log.textContent = lines.join("\n") || "Nothing yet.";
        log.scrollTop = log.scrollHeight;
      } catch (error) {
        log.textContent = error.message;
      }
    });
    view.replaceChildren(
      engineCard,
      card("Models on this PC", models, `Graphics memory: ${data.gpu_budget_gb} GB (change in Settings). Each model shows what its settings need.`),
      folders,
      logs
    );
    const busy = installing || data.models.some((model) => model.state === "loading");
    engineTimer = setTimeout(() => {
      if (generation === renderGeneration && location.hash === "#engine") render();
    }, busy ? 1500 : 6000);
  }

  // The same estimate the server makes (gguf_info.estimate_memory), redone
  // live as settings change, so the bar moves before anything is saved.
  const KV_BYTES = { f16: 2, q8_0: 34 / 32, q4_0: 18 / 32 };
  function estimateMemory(shape, context, gpuLayers, kvCache) {
    const layers = shape.layers || 32;
    const onGpu = gpuLayers < 0 ? layers : Math.min(gpuLayers, layers);
    const share = onGpu / layers;
    const heads = shape.heads || 32;
    const headSize = shape.embedding ? Math.floor(shape.embedding / heads) : 128;
    const key = shape.key_length || headSize;
    const value = shape.value_length || key;
    const kv = layers * context * (shape.kv_heads || heads) * (key + value) * (KV_BYTES[kvCache] || 2);
    const overhead = 0.3e9 + context * Math.max(shape.embedding, 2048) * 4 * 1.5;
    const gb = 1024 ** 3;
    const round = (value) => Math.round((value / gb) * 100) / 100;
    return {
      gpu_gb: round(shape.size * share + kv * share + (onGpu ? overhead : 0)),
      cpu_gb: round(shape.size * (1 - share) + kv * (1 - share)),
      kv_gb: round(kv),
      weights_gb: round(shape.size),
    };
  }

  function engineModelRow(model, data, act) {
    const settings = model.settings;
    const estimate = model.estimate;
    const loaded = model.state === "loaded";
    const tone = { loaded: "good", loading: "warn", failed: "bad" }[model.state] || "";
    const speed = model.speed && model.speed.predicted_per_second
      ? `${model.speed.predicted_per_second.toFixed(1)} tokens/s writing · ${Math.round(model.speed.prompt_per_second || 0)} tokens/s reading`
      : "";
    const context = el("select", { "aria-label": `Context for ${model.name}` },
      CONTEXT_STEPS.filter((size) => !model.context_max || size <= model.context_max || size === settings.context).map((size) =>
        el("option", { value: String(size), text: `${size.toLocaleString()} tokens`, selected: size === settings.context })
      )
    );
    const allLayers = model.layers || 99;
    const layers = el("input", {
      type: "range",
      min: "0",
      max: String(allLayers),
      value: String(settings.gpu_layers < 0 ? allLayers : settings.gpu_layers),
      "aria-label": `Layers on the graphics card for ${model.name}`,
    });
    const layersLabel = el("span", { class: "muted" });
    const showLayers = () => {
      layersLabel.textContent = Number(layers.value) >= allLayers ? `All ${allLayers} on the graphics card` : `${layers.value} of ${allLayers} on the graphics card`;
    };
    layers.addEventListener("input", showLayers);
    showLayers();
    const flash = el("select", { "aria-label": `Flash attention for ${model.name}` }, [
      ["auto", "Auto"], ["on", "On (faster, less memory)"], ["off", "Off"],
    ].map(([value, text]) => el("option", { value, text, selected: settings.flash_attention === value })));
    const kv = el("select", { "aria-label": `Memory for context for ${model.name}` }, [
      ["f16", "Full quality"], ["q8_0", "Half the memory (q8)"], ["q4_0", "Quarter memory (q4)"],
    ].map(([value, text]) => el("option", { value, text, selected: settings.kv_cache === value })));
    const threads = el("input", { type: "number", min: "0", max: "256", value: String(settings.threads), "aria-label": `CPU threads for ${model.name}` });
    const save = el("button", {
      class: "primary",
      type: "button",
      text: loaded ? "Save and reload" : "Save",
      onclick: () =>
        act(`Saving ${model.name}`, () =>
          put(`/studio/api/engine/models/${encodeURIComponent(model.name)}`, {
            context: Number(context.value),
            gpu_layers: Number(layers.value) >= allLayers ? -1 : Number(layers.value),
            flash_attention: flash.value,
            kv_cache: kv.value,
            threads: Number(threads.value) || 0,
          })
        ),
    });
    const memoryBar = el("div", { class: "meter" }, [el("i")]);
    const memoryText = el("small");
    const memory = el("div", { class: "engine-memory" }, [memoryBar, memoryText]);
    const showMemory = (shown) => {
      const fits = shown.gpu_gb <= data.gpu_budget_gb;
      memory.classList.toggle("over", !fits);
      memoryBar.firstChild.style.width = percent(Math.min(1, shown.gpu_gb / Math.max(0.1, data.gpu_budget_gb)));
      memoryText.textContent = `Needs about ${shown.gpu_gb} GB of ${data.gpu_budget_gb} GB graphics memory (${shown.weights_gb} GB model + ${shown.kv_gb} GB context)${shown.cpu_gb ? `, ${shown.cpu_gb} GB in system memory` : ""}.${fits ? "" : " Too big: lower the context, use q8 memory for context, or put fewer layers on the card."}`;
    };
    const liveEstimate = () =>
      model.shape
        ? estimateMemory(
            model.shape,
            Number(context.value),
            Number(layers.value) >= allLayers ? -1 : Number(layers.value),
            kv.value
          )
        : estimate;
    for (const input of [context, layers, kv]) input.addEventListener("input", () => showMemory(liveEstimate()));
    showMemory(estimate);
    return el("article", { class: `engine-model${loaded ? " loaded" : ""}` }, [
      el("div", { class: "engine-model-head" }, [
        el("div", { class: "grow" }, [
          el("strong", { text: model.name }),
          el("div", { class: "chips" }, [
            model.params ? el("span", { class: "pill", text: model.params }) : null,
            model.quant ? el("span", { class: "pill", text: model.quant }) : null,
            el("span", { class: "pill", text: `${model.size_gb} GB` }),
            el("span", { class: "pill", text: model.source }),
            el("span", { class: `pill ${tone}`, text: model.state }),
          ]),
        ]),
        el("button", {
          class: loaded ? "secondary" : "primary",
          type: "button",
          text: loaded ? "Unload" : model.state === "loading" ? "Loading…" : "Load",
          disabled: model.state === "loading",
          "aria-label": `${loaded ? "Unload" : "Load"} ${model.name}`,
          onclick: () =>
            act(loaded ? `Unloading ${model.name}` : `Loading ${model.name}`, () =>
              post(`/studio/api/engine/models/${encodeURIComponent(model.name)}/${loaded ? "unload" : "load"}`)
            ),
        }),
      ]),
      memory,
      speed ? el("small", { class: "muted", text: `Last reply: ${speed}` }) : null,
      el("details", { class: "engine-settings" }, [
        el("summary", { text: "Settings" }),
        el("label", {}, ["Context (how much it remembers at once)", context]),
        el("label", {}, ["Graphics card layers", layers, layersLabel]),
        el("label", {}, ["Flash attention", flash]),
        el("label", {}, ["Memory for context", kv]),
        el("label", {}, ["CPU threads (0 = automatic)", threads]),
        save,
      ]),
    ]);
  }

  async function renderModels() {
    const generation = renderGeneration;
    const [data, available] = await Promise.all([
      api("/studio/api/models"),
      api("/studio/api/models/available"),
    ]);
    setChrome("models", "Local models");
    const local = available.local;
    const served = card("Served by your local runtime", [
      el("p", {
        class: "muted",
        text: local.reachable
          ? `${local.base_url} is serving ${local.models.length} model(s). Use these as an agent's model to run it locally.`
          : `Nothing answered at ${local.base_url}. Start LM Studio, llama-server, or Ollama, or change Local Model Server in settings.`,
      }),
      el("button", {
        class: "primary",
        type: "button",
        text: "Choose a model from this PC",
        onclick: () => openBrainPicker("", () => render()),
      }),
      el("button", {
        class: "secondary",
        type: "button",
        text: "Give each agent its own model",
        onclick: () => openTeamBrains(() => render()),
      }),
      el("button", {
        class: "secondary",
        type: "button",
        text: "Open Model Control",
        onclick: () => go("engine"),
      }),
      ...local.models.map((model) =>
        el("div", { class: "list-item" }, [
          el("span", { class: "grow" }, [el("strong", { text: model })]),
          el("span", { class: "pill good", text: "local" }),
        ])
      ),
    ]);
    const url = el("input", { type: "url", placeholder: "https://…/model.gguf" });
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      served,
      card("Curated small models", [
        el("p", {
          class: "muted",
          text: `Files land in ${data.models_dir}. Point your local runtime at that folder, then use local/<model id> as an agent model.`,
        }),
        ...data.catalog.map((entry) =>
          el("div", { class: "list-item" }, [
            el("span", { class: "grow" }, [
              el("strong", { text: entry.name }),
              el("span", {
                text: `${entry.parameters} · ${entry.quantization} · ~${bytes(entry.approx_bytes)} — ${entry.note}`,
              }),
            ]),
            el("button", {
              class: "primary",
              text: "Get",
              onclick: async () => {
                await post("/studio/api/models/download", { catalog_id: entry.id });
                notify("Download started.");
                render();
              },
            }),
          ])
        ),
      ]),
      card("Download any model file", [
        el("p", {
          class: "muted",
          text: "Direct http(s) links only. Zip and tar archives are unpacked after the download finishes.",
        }),
        url,
        el("div", { class: "row" }, [
          el("button", {
            class: "primary",
            text: "Download",
            onclick: async () => {
              if (!url.value.trim()) return notify("Paste a download URL.");
              await post("/studio/api/models/download", { url: url.value.trim() });
              url.value = "";
              notify("Download started.");
              render();
            },
          }),
          el("button", {
            class: "secondary",
            text: "Scan folder",
            onclick: async () => {
              const result = await post("/studio/api/models/scan");
              notify(`Adopted ${result.adopted.length} file(s).`);
              render();
            },
          }),
        ]),
      ]),
      card(
        "Downloads",
        data.assets.length
          ? data.assets.map((asset) =>
              el("div", { class: "card" }, [
                el("div", { class: "row-between" }, [
                  el("strong", { text: asset.name }),
                  statusPill(asset.status),
                ]),
                meter(asset.progress),
                el("p", {
                  class: "muted",
                  text: `${bytes(asset.bytes_done)} of ${bytes(asset.bytes_total)}${asset.error ? ` — ${asset.error}` : ""}`,
                }),
                el("div", { class: "row" }, [
                  ["queued", "downloading"].includes(asset.status)
                    ? el("button", {
                        class: "secondary",
                        text: "Pause",
                        onclick: async () => {
                          await post(`/studio/api/models/${asset.id}/cancel`);
                          render();
                        },
                      })
                    : null,
                  ["cancelled", "failed"].includes(asset.status)
                    ? el("button", {
                        class: "primary",
                        text: "Resume",
                        onclick: async () => {
                          await post("/studio/api/models/download", {
                            url: asset.source_url,
                            name: asset.name,
                          });
                          render();
                        },
                      })
                    : null,
                  el("button", {
                    class: "danger",
                    text: "Delete",
                    onclick: async () => {
                      await remove(`/studio/api/models/${asset.id}`);
                      render();
                    },
                  }),
                ]),
              ])
            )
          : empty("No downloads yet.")
      )
    );
    if (data.assets.some((asset) => ["queued", "downloading", "extracting"].includes(asset.status))) {
      startPolling(() => renderModels().catch(() => stopPolling()));
    } else {
      stopPolling();
    }
  }

  async function renderTuning(agentId) {
    const generation = renderGeneration;
    const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    const [data, { agents }, lora] = await Promise.all([
      api(`/studio/api/tuning${query}`),
      api("/studio/api/agents"),
      api("/studio/api/lora"),
    ]);
    setChrome("tune", "Tuning");
    const coach = el("input", { type: "text", list: "model-list", placeholder: "none" });
    modelList().catch(() => {});
    const picker = el(
      "select",
      {},
      agents.map((agent) =>
        el("option", {
          value: agent.id,
          text: agent.name,
          selected: agent.id === agentId,
        })
      )
    );
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      loraCard(agents, lora),
      card("Two ways to tune", [
        el("div", { class: "list-item" }, [
          el("span", { class: "grow" }, [
            el("strong", { text: "Local (very light)" }),
            el("span", { text: data.options.local.note }),
          ]),
          el("span", {
            class: `pill ${data.options.local.enabled ? "good" : ""}`,
            text: data.options.local.enabled ? "on" : "per chat",
          }),
        ]),
        el("div", { class: "list-item" }, [
          el("span", { class: "grow" }, [
            el("strong", { text: "Server (weights)" }),
            el("span", { text: data.options.server.note }),
          ]),
          el("span", {
            class: `pill ${data.options.server.enabled ? "good" : "bad"}`,
            text: data.options.server.enabled ? "ready" : "no trainer set",
          }),
        ]),
        el("p", {
          class: "muted",
          text: "Local tuning searches for the shortest instruction pack and scores it on held-out examples. Give it a coach model and a server model writes the candidates while your local model is scored — server teaching local.",
        }),
      ]),
      card("Make a tune pack", [
        el("label", {}, ["Agent", picker]),
        el("label", {}, ["Coach model (optional, e.g. a server model)", coach]),
        el("button", {
          class: "primary",
          text: "Create pack",
          onclick: async () => {
            const pack = await post("/studio/api/tuning/packs", {
              agent_id: picker.value,
              teacher_model: coach.value.trim() || null,
            });
            notify(`Created ${pack.name}`);
            go(`tune/${picker.value}`);
          },
        }),
      ]),
      card(
        "Packs",
        data.packs.length
          ? data.packs.map((pack) =>
              el("div", { class: "card" }, [
                el("div", { class: "row-between" }, [
                  el("strong", { text: pack.name }),
                  pack.active
                    ? el("span", { class: "pill good", text: "active" })
                    : el("span", { class: "pill", text: `v${pack.version}` }),
                ]),
                pack.metrics && pack.metrics.score != null
                  ? el("p", {
                      class: "muted",
                      text: `Held-out score ${pack.metrics.baseline_score} → ${pack.metrics.score} over ${pack.metrics.eval_samples} examples.`,
                    })
                  : el("p", { class: "muted", text: "Not tuned yet." }),
                el("div", { class: "row" }, [
                  el("button", {
                    class: "secondary",
                    text: "Add examples",
                    onclick: () => openSampleSheet(pack),
                  }),
                  tuneButton(pack, "local_light", "Tune locally", data.options.local.enabled || pack.opted_in),
                  tuneButton(pack, "cloud", "Tune on server", data.options.server.enabled),
                  pack.teacher_model
                    ? el("span", { class: "pill", text: `coach: ${pack.teacher_model}` })
                    : null,
                ]),
              ])
            )
          : empty("No packs yet.")
      ),
      card(
        "Runs",
        data.jobs.length
          ? data.jobs.map((job) =>
              el("button", { class: "list-item", onclick: () => go(`job/${job.id}`) }, [
                el("span", { class: "grow" }, [
                  el("strong", { text: job.message || job.backend }),
                  el("span", { text: when(job.created_at) }),
                ]),
                statusPill(job.status),
              ])
            )
          : empty("No tuning runs yet.")
      )
    );
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, children = []) => {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    for (const child of children) node.append(child);
    return node;
  };

  const niceCeil = (value) => {
    if (value <= 0) return 1;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    const step = [1, 2, 2.5, 5, 10].find((n) => n * magnitude >= value) || 10;
    return step * magnitude;
  };

  // Training loss per step: one series, so no legend; the card title names it.
  function lossChart(curve) {
    if (!curve || curve.length < 2) {
      return el("p", { class: "muted", text: "The loss curve appears after the first training steps." });
    }
    const width = 340, height = 170;
    const pad = { left: 34, right: 46, top: 12, bottom: 26 };
    const steps = curve.map((point) => point[0]);
    const losses = curve.map((point) => point[1]);
    const top = niceCeil(Math.max(...losses));
    const x0 = steps[0], x1 = steps[steps.length - 1] || x0 + 1;
    const x = (step) => pad.left + ((step - x0) / Math.max(1, x1 - x0)) * (width - pad.left - pad.right);
    const y = (loss) => pad.top + (1 - loss / top) * (height - pad.top - pad.bottom);
    const grid = [0, top / 2, top].map((tick) =>
      svg("g", {}, [
        svg("line", { x1: pad.left, x2: width - pad.right, y1: y(tick), y2: y(tick), class: "chart-grid" }),
        svg("text", { x: pad.left - 6, y: y(tick) + 4, "text-anchor": "end", class: "chart-tick" }, [
          document.createTextNode(String(Number(tick.toPrecision(3)))),
        ]),
      ])
    );
    const path = curve
      .map((point, index) => `${index ? "L" : "M"}${x(point[0]).toFixed(1)},${y(point[1]).toFixed(1)}`)
      .join(" ");
    const last = curve[curve.length - 1];
    const crosshair = svg("line", { y1: pad.top, y2: height - pad.bottom, class: "chart-crosshair", visibility: "hidden" });
    const focus = svg("circle", { r: 4, class: "chart-dot", visibility: "hidden" });
    const plot = svg("svg", {
      viewBox: `0 0 ${width} ${height}`,
      class: "chart",
      role: "img",
      "aria-label": `Training loss fell from ${losses[0]} to ${last[1]} over ${last[0]} steps`,
    }, [
      ...grid,
      svg("text", { x: pad.left, y: height - 6, class: "chart-tick" }, [document.createTextNode(`step ${x0}`)]),
      svg("text", { x: width - pad.right, y: height - 6, "text-anchor": "end", class: "chart-tick" }, [
        document.createTextNode(`step ${x1}`),
      ]),
      svg("path", { d: path, class: "chart-line" }),
      svg("circle", { cx: x(last[0]), cy: y(last[1]), r: 4, class: "chart-dot" }),
      svg("text", { x: x(last[0]) + 8, y: y(last[1]) + 4, class: "chart-label" }, [
        document.createTextNode(String(last[1])),
      ]),
      crosshair,
      focus,
    ]);
    const tip = el("div", { class: "chart-tip", hidden: true });
    const wrap = el("div", { class: "chart-wrap" }, [plot, tip]);
    const hide = () => {
      crosshair.setAttribute("visibility", "hidden");
      focus.setAttribute("visibility", "hidden");
      tip.hidden = true;
    };
    plot.addEventListener("pointermove", (event) => {
      const box = plot.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      let nearest = curve[0];
      for (const point of curve) {
        if (Math.abs(x(point[0]) - px) < Math.abs(x(nearest[0]) - px)) nearest = point;
      }
      const cx = x(nearest[0]);
      crosshair.setAttribute("x1", cx);
      crosshair.setAttribute("x2", cx);
      crosshair.setAttribute("visibility", "visible");
      focus.setAttribute("cx", cx);
      focus.setAttribute("cy", y(nearest[1]));
      focus.setAttribute("visibility", "visible");
      tip.replaceChildren(el("strong", { text: String(nearest[1]) }), ` loss · step ${nearest[0]}`);
      tip.style.left = `${(cx / width) * 100}%`;
      tip.hidden = false;
    });
    plot.addEventListener("pointerleave", hide);
    const table = el("details", { class: "chart-table" }, [
      el("summary", { text: "Show as table" }),
      el("table", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Step" }), el("th", { text: "Loss" })])]),
        el("tbody", {}, curve.map((point) =>
          el("tr", {}, [el("td", { text: String(point[0]) }), el("td", { text: String(point[1]) })])
        )),
      ]),
    ]);
    return el("div", {}, [wrap, table]);
  }

  function figure(label, value) {
    return el("div", { class: "figure" }, [
      el("span", { class: "figure-label", text: label }),
      el("strong", { class: "figure-value", text: value == null ? "—" : Number(value).toFixed(3) }),
    ]);
  }

  function loraCard(agents, lora) {
    const students = agents.filter((agent) => agent.role !== "guide");
    const student = el(
      "select",
      {},
      students.map((agent) =>
        el("option", {
          value: agent.id,
          text: `${agent.name} · ${agent.model}`,
          selected: agent.role === "student",
        })
      )
    );
    const base = el("select", {}, [
      ...lora.bases.map((item) =>
        el("option", { value: item.repo, text: `${item.size} · ${item.repo} → ${item.ollama}` })
      ),
      el("option", { value: "__other__", text: "Another Hugging Face model…" }),
    ]);
    const note = el("p", { class: "muted", text: lora.bases[0] ? lora.bases[0].note : "" });
    const otherRepo = el("input", { type: "text", placeholder: "org/model on Hugging Face", hidden: true });
    const otherOllama = el("input", { type: "text", placeholder: "matching Ollama tag, e.g. mistral:7b", hidden: true });
    base.addEventListener("change", () => {
      const other = base.value === "__other__";
      otherRepo.hidden = !other;
      otherOllama.hidden = !other;
      const known = lora.bases.find((item) => item.repo === base.value);
      note.textContent = known ? known.note : "Pick the Ollama build of the same weights so the result can run locally.";
    });
    const where = el("select", {}, [
      el("option", { value: "local", text: "This computer" }),
      el("option", { value: "remote", text: "Rented GPU or VPS (run a worker there)" }),
    ]);
    const exportKind = el("select", {}, [
      el("option", { value: "merged", text: "A full model with the new weights (LM Studio or Ollama)" }),
      el("option", { value: "adapter", text: "A small adapter on top of the base model (Ollama only)" }),
    ]);
    const quant = el("select", {}, [
      el("option", { value: "Q4_K_M", text: "Q4_K_M: smallest, fits 8 GB GPUs like the RX 580 (recommended)" }),
      el("option", { value: "Q5_K_M", text: "Q5_K_M: a little sharper, needs about 6 GB" }),
      el("option", { value: "Q8_0", text: "Q8_0: near-original quality, about 8 GB for a 7B model" }),
    ]);
    const quantRow = el("label", {}, ["Model file size", quant]);
    exportKind.addEventListener("change", () => {
      quantRow.hidden = exportKind.value !== "merged";
    });
    const rentGuide = el("details", { class: "guide", open: true }, [
      el("summary", { text: "How training on a rented GPU works" }),
      el("ol", {}, [
        el("li", { text: "Install Tailscale (free) on this PC and sign in. Copy this PC's Tailscale address, like 100.x.y.z." }),
        el("li", { text: "In admin settings → Studio, set Address For Remote Trainers to http://100.x.y.z:8082 (your Tailscale address)." }),
        el("li", { text: "Rent a GPU with 24 GB or more (for example an RTX 4090 or A5000 on RunPod or Vast.ai) using a PyTorch template. A 7B model trains in well under an hour." }),
        el("li", { text: "Press Start below. The job page shows commands: open the rented machine's terminal and paste them. On RunPod or Vast, run the Tailscale block first with an auth key from the Tailscale admin page." }),
        el("li", { text: "Watch the loss drop here. When it finishes, the new model downloads to this PC, installs into LM Studio and Ollama, and the student switches to it." }),
        el("li", { text: "Stop the rented machine so it stops billing." }),
      ]),
    ]);
    const syncGuide = () => {
      rentGuide.hidden = where.value !== "remote";
    };
    where.addEventListener("change", syncGuide);
    const env = el("p", { class: "muted", text: "Checking what this computer can train with…" });
    api("/studio/api/lora/environment")
      .then((info) => {
        const trains = info.ready
          ? `This computer can train: ${info.accelerator}.`
          : "This computer can't train yet (no torch/transformers/peft). Install the training extra, or use a rented GPU.";
        const serves = info.ollama ? "Ollama found: results install automatically." : "Ollama not found: install it to run results locally.";
        const gguf = info.llama_cpp_ready ? "" : " Set the llama.cpp folder in settings to make Ollama-ready files.";
        env.textContent = `${trains} ${serves}${gguf}`;
        if (!info.ready) where.value = "remote";
        syncGuide();
      })
      .catch(() => {
        env.textContent = "Could not check this computer.";
      });
    const source = (value, label, checked) => {
      const box = el("input", { type: "checkbox", value });
      box.checked = checked;
      return { box, row: el("label", { class: "switch" }, [label, box]) };
    };
    const sources = [
      source("topics", "Teacher writes lessons on topics", true),
      source("tools", "Tool-use lessons (files, web, memory)", true),
      source("classes", "Everything from this agent's classes", true),
      source("examples", "Examples from its tune packs", true),
    ];
    const topics = el("textarea", {
      rows: "4",
      placeholder: "Python web apps\nReact and TypeScript UI\nHTML and CSS layout\nDebugging and tests",
    });
    const perTopic = el("input", { type: "number", value: "12", min: "1", max: "50" });
    const teacher = el("input", { type: "text", list: "model-list", placeholder: "default teacher (a server model)" });
    modelList().catch(() => {});
    const epochs = el("input", { type: "number", value: "2", min: "1", max: "10" });
    const rank = el("input", { type: "number", value: "16", min: "4", max: "128" });
    const maxLen = el("input", { type: "number", value: "1024", min: "256", max: "8192" });
    return card(
      "LoRA: train the weights",
      [
        el("p", {
          class: "muted",
          text: "Real training that changes the model's weights: server teachers write lessons, a LoRA is trained on them, then merged into the model. Train here if this computer has an NVIDIA GPU, or on a rented GPU. The new model installs into LM Studio and Ollama, and the student switches to it.",
        }),
        env,
        el("label", {}, ["Student", student]),
        el("label", {}, ["Model to train (Hugging Face)", base]),
        note,
        otherRepo,
        otherOllama,
        el("label", {}, ["Where to train", where]),
        rentGuide,
        el("label", {}, ["What to make", exportKind]),
        quantRow,
        ...sources.map((item) => item.row),
        el("label", {}, ["Topics, one per line", topics]),
        el("label", {}, ["Lessons per topic", perTopic]),
        el("label", {}, ["Teacher model", teacher]),
        el("details", {}, [
          el("summary", { text: "Advanced" }),
          el("label", {}, ["Epochs", epochs]),
          el("label", {}, ["LoRA rank", rank]),
          el("label", {}, ["Max tokens per example", maxLen]),
        ]),
        el("button", {
          class: "primary",
          text: "Start LoRA training",
          onclick: async () => {
            const chosen = sources.filter((item) => item.box.checked).map((item) => item.box.value);
            const topicList = topics.value.split("\n").map((line) => line.trim()).filter(Boolean);
            const other = base.value === "__other__";
            try {
              const job = await post("/studio/api/lora/jobs", {
                agent_id: student.value,
                base_model: other ? otherRepo.value.trim() : base.value,
                ollama_base: other ? otherOllama.value.trim() : "",
                runner: where.value,
                export: exportKind.value,
                gguf_quant: quant.value,
                sources: chosen,
                topics: topicList,
                examples_per_topic: Number(perTopic.value) || 12,
                teacher_model: teacher.value.trim() || null,
                epochs: Number(epochs.value) || 2,
                rank: Number(rank.value) || 16,
                max_seq_len: Number(maxLen.value) || 1024,
              });
              go(`lora/${job.id}`);
            } catch (error) {
              notify(error.message);
            }
          },
        }),
        ...(lora.jobs.length
          ? [
              el("h3", { text: "LoRA runs" }),
              ...lora.jobs.slice(0, 8).map((job) =>
                el("button", { class: "list-item", onclick: () => go(`lora/${job.id}`) }, [
                  el("span", { class: "grow" }, [
                    el("strong", { text: job.base_model }),
                    el("span", { text: `${job.runner === "local" ? "this computer" : "remote worker"} · ${when(job.created_at)}` }),
                  ]),
                  statusPill(job.status),
                ])
              ),
            ]
          : []),
      ]
    );
  }

  async function renderLoraJob(jobId) {
    const generation = renderGeneration;
    const job = await api(`/studio/api/lora/jobs/${jobId}`);
    setChrome("lora", "LoRA training");
    const active = ["queued", "running"].includes(job.status);
    const busy = /^(Trained\. Installing|Downloading the base|Creating the (tuned )?model|Adding the model)/.test(job.message);
    const nodes = [
      card(job.base_model, [
        el("div", { class: "row-between" }, [
          statusPill(job.status),
          el("span", { class: "pill", text: `${job.step}/${job.total_steps || "?"} steps` }),
        ]),
        meter(job.progress),
        el("p", { class: "muted", text: job.message }),
        job.error ? el("p", { class: "error-text", text: job.error }) : null,
        el("div", { class: "figures" }, [
          figure("Held-out loss before", job.eval_loss_before),
          figure("Held-out loss after", job.eval_loss_after),
        ]),
        el("p", {
          class: "muted",
          text: `${job.train_examples} training examples, ${job.eval_examples} held out · ${job.runner === "local" ? "this computer" : "remote worker"}${job.metrics.device ? ` · ${job.metrics.device}` : ""}`,
        }),
      ]),
      card("Training loss per step", [lossChart(job.metrics.loss_curve)]),
    ];
    if (job.commands && job.runner === "remote") {
      const block = (label, text) =>
        el("div", {}, [
          el("div", { class: "row-between" }, [
            el("strong", { text: label }),
            el("button", {
              class: "secondary",
              text: "Copy",
              onclick: async () => {
                try {
                  await navigator.clipboard.writeText(text);
                  notify("Copied.");
                } catch {
                  notify("Select the text and copy it.");
                }
              },
            }),
          ]),
          el("pre", { class: "command-block", text }),
        ]);
      nodes.push(
        card("Run it on a rented GPU or VPS", [
          el("p", {
            class: "muted",
            text: `On the GPU machine, run these. It must be able to reach ${job.commands.studio_url} (Tailscale on both machines is the easy way). For gated models, set HF_TOKEN there first.`,
          }),
          job.commands.warning ? el("p", { class: "error-text", text: job.commands.warning }) : null,
          block("Linux (RunPod, Vast.ai, most rented GPUs)", job.commands.bash),
          el("p", {
            class: "muted",
            text: "Rented containers can't reach your PC directly. Run this first, after setting TS_AUTHKEY to a key from login.tailscale.com (Settings, Keys; tick Ephemeral):",
          }),
          block("Tailscale for containers (run first)", job.commands.tailscale),
          block("Windows PowerShell", job.commands.powershell),
        ])
      );
    }
    if (job.status === "succeeded") {
      const hasModel = job.files.includes("model.gguf");
      const quantUsed = job.metrics.model_quant || job.gguf_quant;
      const rows = [
        el("p", {
          text: hasModel
            ? `model.gguf: ${job.base_model} with the training merged into its weights (${quantUsed}${job.metrics.model_gb ? `, ${job.metrics.model_gb} GB` : ""}).`
            : "This run made an adapter, not a full model.",
        }),
        job.metrics.model_error
          ? el("p", { class: "error-text", text: `The full model couldn't be made: ${job.metrics.model_error}` })
          : null,
        job.lmstudio_path ? el("p", { class: "muted", text: `In LM Studio: ${job.lmstudio_path}` }) : null,
        job.served_model ? el("p", { class: "muted", text: `In Ollama as: ${job.served_model}` }) : null,
        el("p", {
          class: "muted",
          text: job.agent_model ? `${job.agent_name} runs ${job.agent_model} right now.` : "",
        }),
        el("div", { class: "row" }, [
          el("button", {
            class: "primary",
            text: `Switch ${job.agent_name || "the student"} to it`,
            onclick: async () => {
              try {
                const updated = await post(`/studio/api/lora/jobs/${jobId}/switch`);
                notify(updated.message);
                render();
              } catch (error) {
                notify(error.message);
              }
            },
          }),
          el("button", {
            class: "secondary",
            text: "Install again",
            onclick: async () => {
              await post(`/studio/api/lora/jobs/${jobId}/install`);
              render();
            },
          }),
        ]),
        el("p", {
          class: "muted",
          text: "To use it by hand: in LM Studio open My Models and load it; in Ollama run the model named above. Any agent can use it: set its model to local/ plus the name LM Studio or Ollama shows.",
        }),
      ];
      nodes.splice(1, 0, card(job.in_use ? "Your new model (in use)" : "Your new model", rows));
    }
    const actions = [];
    if (active) {
      actions.push(el("button", {
        class: "danger",
        text: "Stop",
        onclick: async () => {
          await post(`/studio/api/lora/jobs/${jobId}/cancel`);
          render();
        },
      }));
    }
    if (job.previous_model) {
      actions.push(el("button", {
        class: "secondary",
        text: `Switch the student back to ${job.previous_model}`,
        onclick: async () => {
          await post(`/studio/api/lora/jobs/${jobId}/revert`);
          render();
        },
      }));
    }
    const key = token();
    const suffix = key ? `?token=${encodeURIComponent(key)}` : "";
    nodes.push(
      card("Files", [
        ...(job.files.length
          ? job.files.map((name) =>
              el("a", { class: "list-item", href: `/studio/api/lora/jobs/${jobId}/files/${name}${suffix}` }, [
                el("span", { class: "grow" }, [el("strong", { text: name })]),
                el("span", { class: "pill", text: "download" }),
              ])
            )
          : [empty("Files appear here as the job runs.")]),
        actions.length ? el("div", { class: "row" }, actions) : null,
      ])
    );
    if (generation !== renderGeneration) return;
    view.replaceChildren(...nodes);
    if (active || busy) {
      startPolling(() => renderLoraJob(jobId).catch(() => stopPolling()));
    } else {
      stopPolling();
    }
  }

  function tuneButton(pack, backend, label, available) {
    return el("button", {
      class: backend === "cloud" ? "secondary" : "primary",
      text: label,
      disabled: !available,
      title: available ? "" : "Not set up yet",
      onclick: async () => {
        try {
          const job = await post(`/studio/api/tuning/packs/${pack.id}/start`, { backend });
          notify(backend === "cloud" ? "Sent to the trainer." : "Tuning started.");
          go(`job/${job.id}`);
        } catch (error) {
          notify(error.message);
        }
      },
    });
  }

  function openSampleSheet(pack) {
    const prompt = el("textarea", { placeholder: "Example request" });
    const completion = el("textarea", { placeholder: "The answer you want" });
    openSheet(`Examples · ${pack.name}`, [
      el("p", {
        class: "muted",
        text: "Two examples are enough to start. The last few become a held-out set the tune is scored on.",
      }),
      prompt,
      completion,
      el("button", {
        class: "primary",
        text: "Add example",
        onclick: async () => {
          if (!prompt.value.trim() || !completion.value.trim()) {
            return notify("Fill both boxes.");
          }
          const result = await post(
            `/studio/api/tuning/packs/${pack.id}/samples`,
            { pairs: [[prompt.value.trim(), completion.value.trim()]] }
          );
          prompt.value = "";
          completion.value = "";
          notify(`${result.total} examples in this pack.`);
        },
      }),
    ]);
  }

  async function renderJob(jobId) {
    const generation = renderGeneration;
    const job = await api(`/studio/api/tuning/jobs/${jobId}`);
    setChrome("job", "Tuning run");
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      card(job.message || "Tuning", [
        el("div", { class: "row-between" }, [
          statusPill(job.status),
          el("span", { class: "pill", text: `${job.step}/${job.total_steps}` }),
        ]),
        meter(job.progress),
        el("div", { class: "kv" }, [
          el("span", { text: "Backend" }),
          el("span", { text: job.backend }),
          el("span", { text: "Baseline" }),
          el("span", { text: job.baseline_score == null ? "—" : job.baseline_score }),
          el("span", { text: "Tuned" }),
          el("span", { text: job.score == null ? "—" : job.score }),
        ]),
        job.error ? el("p", { class: "muted", text: job.error }) : null,
        job.backend === "cloud" && ["queued", "running"].includes(job.status)
          ? el("button", {
              class: "secondary",
              text: "Check the trainer now",
              onclick: async () => {
                await post(`/studio/api/tuning/jobs/${jobId}/refresh`);
                render();
              },
            })
          : null,
        ["queued", "running"].includes(job.status)
          ? el("button", {
              class: "danger",
              text: "Stop",
              onclick: async () => {
                await post(`/studio/api/tuning/jobs/${jobId}/cancel`);
                render();
              },
            })
          : null,
      ])
    );
    if (["queued", "running"].includes(job.status)) {
      startPolling(() => renderJob(jobId).catch(() => stopPolling()));
    } else {
      stopPolling();
    }
  }

  // Learn mode: Jarvis teaches himself a subject, lesson by lesson.
  function learningCard(studies) {
    const topic = el("input", { type: "text", placeholder: "What should Jarvis learn? (e.g. electrical engineering)", "aria-label": "Topic to learn" });
    const focus = el("input", { type: "text", placeholder: "Focus (optional, e.g. circuits for home projects)", "aria-label": "Focus" });
    const depth = el("select", { "aria-label": "Depth" }, [
      el("option", { value: "quick", text: "Quick: 4 lessons" }),
      el("option", { value: "normal", text: "Normal: 7 lessons", selected: true }),
      el("option", { value: "deep", text: "Deep: 10 lessons" }),
    ]);
    const status = el("p", { class: "muted", hidden: true });
    const form = el("form", {
      class: "video-study",
      onsubmit: async (event) => {
        event.preventDefault();
        if (!topic.value.trim()) return;
        try {
          await post("/studio/api/studies", { topic: topic.value.trim(), focus: focus.value.trim(), depth: depth.value });
          render();
        } catch (error) {
          status.hidden = false;
          status.textContent = error.message;
        }
      },
    }, [topic, focus, el("div", { class: "row" }, [depth, el("button", { class: "primary", type: "submit", text: "Start learning" })]), status]);
    const rows = studies.length
      ? studies.map((study) =>
          el("div", { class: "list-item study-row" }, [
            el("span", { class: "grow" }, [
              el("strong", { text: study.topic }),
              el("br"),
              el("span", { class: "muted", text: `${study.status} · ${study.done}/${study.plan.length || "?"} lessons${study.understanding != null ? ` · understanding ${Math.round(study.understanding * 100)}%` : ""}` }),
              meter(study.progress),
            ]),
            el("button", { class: "secondary", type: "button", text: "Open", onclick: () => openStudy(study.id) }),
          ])
        )
      : [empty("Nothing learned yet. Tell Jarvis \"learn electrical engineering\", or start one here.")];
    return card(
      "Learning",
      [form, ...rows],
      "Jarvis plans a course, researches each lesson on the web, Reddit, and YouTube, writes his own notes, and quizzes himself. Everything he learns goes into memory for the whole team."
    );
  }

  async function openStudy(studyId) {
    let data;
    try {
      data = await api(`/studio/api/studies/${studyId}`);
    } catch (error) {
      notify(error.message);
      return;
    }
    const { study, lessons } = data;
    const running = study.status === "planning" || study.status === "learning";
    openSheet(`Learning: ${study.topic}`, [
      el("p", { class: "muted", text: `${study.status} · ${Math.round(study.progress * 100)}% · ${study.step}` }),
      meter(study.progress),
      study.summary ? el("pre", { class: "conversation-notes", text: study.summary }) : null,
      study.plan.length
        ? el("ol", { class: "study-plan" }, study.plan.map((title, index) =>
            el("li", { class: index < study.done ? "done" : "", text: title })
          ))
        : null,
      ...lessons.map((lesson) =>
        el("details", { class: "video-details" }, [
          el("summary", { text: `Lesson ${lesson.ordinal + 1}: ${lesson.title} · self-check ${Math.round(lesson.score * 100)}%` }),
          el("pre", { class: "conversation-notes", text: lesson.notes }),
          lesson.quiz.length
            ? el("div", { class: "study-quiz" }, lesson.quiz.map(([question, answer]) =>
                el("p", {}, [el("strong", { text: `Q: ${question}` }), el("br"), `A: ${answer}`])
              ))
            : null,
          lesson.sources.length
            ? el("ul", { class: "study-sources" }, lesson.sources.map((line) => el("li", { text: line })))
            : null,
        ])
      ),
      el("div", { class: "row" }, [
        running
          ? el("button", {
              class: "secondary",
              type: "button",
              text: "Stop learning",
              onclick: async () => {
                try {
                  await post(`/studio/api/studies/${study.id}/stop`);
                  closeSheet();
                  render();
                } catch (error) {
                  notify(error.message);
                }
              },
            })
          : null,
        el("button", {
          class: "danger",
          type: "button",
          text: "Forget this study",
          onclick: async () => {
            try {
              await remove(`/studio/api/studies/${study.id}`);
              closeSheet();
              render();
            } catch (error) {
              notify(error.message);
            }
          },
        }),
      ]),
    ]);
  }

  // The user's to-do list. Jarvis and the Helper add to it too, and Jarvis
  // announces reminders on the HUD when they are due.
  function todoCard(items) {
    const text = el("input", { type: "text", placeholder: "Add a to-do", "aria-label": "New to-do" });
    const due = el("input", { type: "text", placeholder: "Remind me… (in 20 minutes, tomorrow 9am)", "aria-label": "Reminder time" });
    const status = el("p", { class: "muted", hidden: true });
    const form = el("form", {
      class: "video-study",
      onsubmit: async (event) => {
        event.preventDefault();
        if (!text.value.trim()) return;
        try {
          await post("/studio/api/todos", { text: text.value.trim(), due: due.value.trim() });
          render();
        } catch (error) {
          status.hidden = false;
          status.textContent = error.message;
        }
      },
    }, [text, due, el("div", { class: "row" }, [el("button", { class: "primary", type: "submit", text: "Add" })]), status]);
    const when = (ms) => {
      const date = new Date(ms);
      const today = new Date();
      const sameDay = date.toDateString() === today.toDateString();
      const clock = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return sameDay ? `today ${clock}` : `${date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} ${clock}`;
    };
    const rows = items.length
      ? items.map((item) =>
          el("div", { class: "list-item todo-row" }, [
            el("input", {
              type: "checkbox",
              "aria-label": `Done: ${item.text}`,
              onchange: async () => {
                try {
                  await post(`/studio/api/todos/${item.id}/done`);
                  render();
                } catch (error) {
                  notify(error.message);
                }
              },
            }),
            el("span", { class: "grow" }, [
              item.text,
              item.due_at
                ? el("span", { class: `muted todo-due${item.due_at < Date.now() ? " overdue" : ""}`, text: ` · ${when(item.due_at)}` })
                : null,
            ]),
            el("button", {
              class: "secondary",
              type: "button",
              text: "Remove",
              "aria-label": `Remove ${item.text}`,
              onclick: async () => {
                try {
                  await remove(`/studio/api/todos/${item.id}`);
                  render();
                } catch (error) {
                  notify(error.message);
                }
              },
            }),
          ])
        )
      : [empty("Nothing to do. Add something here, or tell Jarvis \"remind me to call Sam at 5pm\".")];
    return card(
      "To-dos and reminders",
      [form, ...rows],
      "Jarvis and the Helper add to this list too. Reminders are announced on the HUD when they are due."
    );
  }

  // Videos the Researcher turned into notes for the team. Paste a link to
  // study one; open a note to read it and jump to any moment of the video.
  function videoCard(videos) {
    const link = el("input", { type: "url", placeholder: "Paste a YouTube link", "aria-label": "YouTube link" });
    const focus = el("input", { type: "text", placeholder: "What should the team learn from it? (optional)", "aria-label": "Focus" });
    const status = el("p", { class: "muted", hidden: true });
    const study = el("button", {
      class: "primary",
      type: "submit",
      text: "Study it",
    });
    const form = el("form", {
      class: "video-study",
      onsubmit: async (event) => {
        event.preventDefault();
        if (!link.value.trim()) return;
        study.disabled = true;
        status.hidden = false;
        status.textContent = "Reading the transcript and writing notes… a local model can take a minute.";
        try {
          const note = await post("/studio/api/videos", { url: link.value.trim(), focus: focus.value.trim() });
          link.value = "";
          focus.value = "";
          status.hidden = true;
          await render();
          openVideo(note);
        } catch (error) {
          status.textContent = error.message;
        } finally {
          study.disabled = false;
        }
      },
    }, [link, focus, el("div", { class: "row" }, [study]), status]);
    const rows = videos.length
      ? videos.map((video) =>
          el("div", { class: "list-item video-row" }, [
            el("span", { class: "grow" }, [
              el("strong", { text: video.title }),
              el("br"),
              el("span", { class: "muted", text: `${video.length ? `${video.length} · ` : ""}${video.source === "research" ? "from research" : video.source === "user" ? "from you" : "studied by an agent"}` }),
              video.summary ? el("p", { class: "muted video-summary", text: video.summary }) : null,
            ]),
            el("button", {
              class: "secondary",
              type: "button",
              text: "Open",
              onclick: async () => {
                try {
                  openVideo(await api(`/studio/api/videos/${video.id}`));
                } catch (error) {
                  notify(error.message);
                }
              },
            }),
          ])
        )
      : [empty("No videos yet. Research saves every video it reads here, or paste one above.")];
    return card(
      "Video notes",
      [form, ...rows],
      "Videos turned into notes the agents use: summary, key points, steps, and the transcript with times. Every note is also in the team's memory."
    );
  }

  function openVideo(note) {
    const list = (label, items, numbered) =>
      items && items.length
        ? [
            el("h3", { text: label }),
            el(numbered ? "ol" : "ul", {}, items.map((item) => el("li", { text: item }))),
          ]
        : [];
    const moment = (line) =>
      el("div", { class: "video-line" }, [
        el("a", {
          class: "pill",
          href: `${note.url}&t=${line.seconds}s`,
          target: "_blank",
          rel: "noopener",
          text: line.at,
        }),
        el("span", { text: line.text }),
      ]);
    const find = el("input", { type: "search", placeholder: "Find in the transcript", "aria-label": "Find in the transcript" });
    const lines = el("div", { class: "video-transcript" }, (note.transcript || []).map(moment));
    find.addEventListener("input", () => {
      const query = find.value.trim().toLowerCase();
      for (const row of lines.children) {
        row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
      }
    });
    openSheet(note.title, [
      el("p", {}, [el("a", { href: note.url, target: "_blank", rel: "noopener", text: "Watch on YouTube" })]),
      note.focus ? el("p", { class: "muted", text: `Studied for: ${note.focus}` }) : null,
      note.summary ? el("p", { text: note.summary }) : null,
      ...list("Key points", note.points),
      ...list("Steps", note.steps, true),
      ...list("Names", note.names),
      ...list("Watch out", note.cautions),
      el("details", { class: "video-details" }, [
        el("summary", { text: `Transcript (${note.lines} lines${note.length ? `, ${note.length}` : ""})` }),
        find,
        lines,
      ]),
      el("button", {
        class: "danger",
        type: "button",
        text: "Forget this video",
        onclick: async () => {
          try {
            await remove(`/studio/api/videos/${note.id}`);
            closeSheet();
            render();
          } catch (error) {
            notify(error.message);
          }
        },
      }),
    ]);
  }

  async function renderMore() {
    const generation = renderGeneration;
    const [overview, vault, { agents }, connect, voiceInfo, videos, todos, studies] = await Promise.all([
      api("/studio/api/overview"),
      api("/studio/api/obsidian"),
      api("/studio/api/agents"),
      api("/studio/api/connect"),
      api("/studio/api/voice"),
      api("/studio/api/videos").catch(() => ({ videos: [] })),
      api("/studio/api/todos").catch(() => ({ todos: [] })),
      api("/studio/api/studies").catch(() => ({ studies: [] })),
    ]);
    const picker = el("select", {}, [
      overview.settings.shared_memory
        ? el("option", { value: "shared", text: "Team memory (shared)" })
        : null,
      ...agents.map((agent) => el("option", { value: agent.id, text: agent.name })),
    ]);
    if (generation !== renderGeneration) return;
    const finder = el("input", {
      type: "search",
      class: "page-search",
      autocomplete: "off",
      "aria-label": "Search settings",
      placeholder: "Search settings…",
    });
    const nothing = el("p", { class: "muted", hidden: true, text: "Nothing here matches. Admin settings on the PC have the rest." });
    finder.addEventListener("input", () => {
      const query = finder.value.trim().toLowerCase();
      let shown = 0;
      for (const node of view.querySelectorAll(":scope > .card")) {
        const hit = !query || node.textContent.toLowerCase().includes(query);
        node.hidden = !hit;
        if (hit) shown += 1;
      }
      nothing.hidden = shown > 0;
    });
    view.replaceChildren(
      finder,
      nothing,
      card("Settings", [
        el("p", {
          class: "muted",
          text: "Every Free Claude Code option: providers and keys, models, messaging, Studio, and voice.",
        }),
        el("button", { class: "primary", type: "button", text: "Open settings", onclick: () => go("settings") }),
      ]),
      learningCard(studies.studies || []),
      todoCard(todos.todos || []),
      videoCard(videos.videos || []),
      voiceCard(voiceInfo),
      webCard(overview.settings.web),
      connectCard(connect),
      card("Tuning", [
        el("p", { class: "muted", text: "Very light tuning, on device or in the cloud." }),
        el("button", {
          class: "primary",
          text: "Open tuning",
          onclick: () => go("tune"),
        }),
      ]),
      card("Local models", [
        el("p", {
          class: "muted",
          text: `${overview.assets.length} tracked download(s).`,
        }),
        el("button", {
          class: "primary",
          text: "Open models",
          onclick: () => go("models"),
        }),
      ]),
      card("Obsidian", [
        el("div", { class: "kv" }, [
          el("span", { text: "Vault" }),
          el("span", { text: vault.path || "not configured" }),
          el("span", { text: "Folder" }),
          el("span", { text: vault.folder }),
          el("span", { text: "Writable" }),
          el("span", { text: vault.writable ? "yes" : "no" }),
          el("span", { text: "Notes" }),
          el("span", { text: String(vault.note_count) }),
        ]),
        vault.candidates.length
          ? el("p", {
              class: "muted",
              text: `Vaults found on this device: ${vault.candidates.join(", ")}`,
            })
          : el("p", {
              class: "muted",
              text: "Set STUDIO_OBSIDIAN_VAULT in the admin settings to the vault folder. On iOS that is usually in iCloud Drive under iCloud~md~obsidian.",
            }),
        el("p", {
          class: "muted",
          text: vault.memory_sync
            ? "Memory mirroring is on: every agent's memory is kept in the vault as linked notes, one per memory. Edit a note or move it between the Working and Long-term folders, then sync to bring the change back."
            : "Mirror every agent's memory into the vault as linked notes — one per memory, grouped by agent and by working vs long-term. Turn on Mirror Memory Into Obsidian in settings to keep it updated automatically.",
        }),
        el("div", { class: "row" }, [
          el("button", {
            class: "primary",
            text: "Sync memory",
            onclick: async () => {
              try {
                const result = await post("/studio/api/obsidian/memory/sync");
                notify(`Pulled ${result.pulled} edit(s), wrote ${result.written} note(s).`);
              } catch (error) {
                notify(error.message);
              }
            },
          }),
          el("button", {
            class: "secondary",
            text: "Pull edits only",
            onclick: async () => {
              try {
                const result = await post("/studio/api/obsidian/memory/pull");
                notify(`Pulled ${result.pulled} edit(s) from Obsidian.`);
              } catch (error) {
                notify(error.message);
              }
            },
          }),
        ]),
        el("label", {}, ["Import Inbox notes into", picker]),
        el("button", {
          class: "secondary",
          text: "Import notes to memory",
          onclick: async () => {
            try {
              const result = await post("/studio/api/obsidian/import", {
                agent_id: picker.value,
              });
              notify(`Imported ${result.imported} note lines.`);
            } catch (error) {
              notify(error.message);
            }
          },
        }),
      ]),
      card("Settings", [
        el("p", {
          class: "muted",
          text: "Models, tuning backend, teacher, and Obsidian all live in the Studio section of the admin settings.",
        }),
        el("a", { class: "pill", href: "/admin", text: "Open admin settings" }),
      ])
    );
  }

  /* -------------------------------------------------------------------- hud */

  const VOICE_KEY = "fcc.studio.voice";
  /* A living gold core: a sphere of glowing filaments that breathes, swirls,
     and answers to voice. Pure canvas, so it runs on phones and old GPUs. */
  const ORB_STATES = {
    idle: { spin: 0.14, swirl: 0.0, heat: 0.75, spread: 0.02, streak: 0.25 },
    thinking: { spin: 0.55, swirl: 0.9, heat: 1.0, spread: 0.04, streak: 0.8 },
    listening: { spin: 0.2, swirl: 0.15, heat: 0.95, spread: 0.1, streak: 0.35 },
    hearing: { spin: 0.4, swirl: 0.5, heat: 1.05, spread: 0.06, streak: 0.6 },
    speaking: { spin: 0.28, swirl: 0.25, heat: 1.1, spread: 0.12, streak: 0.55 },
    offline: { spin: 0.04, swirl: 0.0, heat: 0.3, spread: 0.0, streak: 0.05 },
  };

  function createCoreOrb(canvas) {
    const ctx = canvas.getContext("2d");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const small = Math.min(window.innerWidth, window.innerHeight) < 700;
    // Fewer particles and 30 frames a second on phones and older PCs keep
    // the core smooth and leave the processor for the AI.
    const modest = small || (navigator.hardwareConcurrency || 4) <= 4;
    const frameGap = modest ? 1000 / 30 : 0;
    let lastFrame = 0;
    const count = small ? 900 : modest ? 1400 : 2200;
    const golden = Math.PI * (3 - Math.sqrt(5));
    const points = Array.from({ length: count }, (_, i) => {
      const y = 1 - (i / (count - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = golden * i;
      const shell = Math.random() < 0.22 ? 0.25 + Math.random() * 0.6 : 0.86 + Math.random() * 0.18;
      return {
        x: Math.cos(theta) * r,
        y,
        z: Math.sin(theta) * r,
        shell,
        size: 0.6 + Math.random() * 1.5,
        phase: Math.random() * Math.PI * 2,
        streak: Math.random() < 0.22,
      };
    });
    const rings = [0.35, -0.6, 1.1].map((tilt, index) => ({
      tilt,
      speed: 0.25 + index * 0.18,
      radius: 1.08 + index * 0.07,
      dots: Array.from({ length: small ? 60 : 110 }, (_, i) => ({
        angle: (i / (small ? 60 : 110)) * Math.PI * 2,
        jitter: Math.random() * 0.05,
      })),
    }));
    // Filaments: glowing strands wrapped around the sphere on tilted circles.
    const filaments = Array.from({ length: small ? 16 : 28 }, () => ({
      tilt: Math.random() * Math.PI,
      turn: Math.random() * Math.PI * 2,
      radius: 0.55 + Math.random() * 0.5,
      length: 0.8 + Math.random() * 2.2,
      offset: Math.random() * Math.PI * 2,
      speed: (Math.random() - 0.5) * 0.9,
    }));
    const state = { name: "idle", current: { ...ORB_STATES.idle }, level: 0, burst: 0, tiltX: 0, tiltY: 0, targetX: 0, targetY: 0 };
    let width = 0;
    let height = 0;
    let frame = 0;
    let last = performance.now();
    let spin = 0;
    let visible = true;

    const resize = () => {
      const box = canvas.getBoundingClientRect();
      const dpr = Math.min(modest ? 1.25 : 2, window.devicePixelRatio || 1);
      width = Math.max(1, box.width);
      height = Math.max(1, box.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (still) draw(0);
    };
    const sizer = new ResizeObserver(resize);
    sizer.observe(canvas);
    const watcher = new IntersectionObserver((entries) => {
      visible = entries.some((entry) => entry.isIntersecting);
    });
    watcher.observe(canvas);
    const onPointer = (event) => {
      const box = canvas.getBoundingClientRect();
      state.targetX = ((event.clientY - box.top) / box.height - 0.5) * 0.6;
      state.targetY = ((event.clientX - box.left) / box.width - 0.5) * 0.6;
    };
    canvas.addEventListener("pointermove", onPointer);

    function project(x, y, z, radius, cx, cy) {
      // Rotate around Y (spin + pointer) then X (tilt), then perspective.
      const ay = spin + state.tiltY;
      const cosY = Math.cos(ay);
      const sinY = Math.sin(ay);
      const x1 = x * cosY + z * sinY;
      const z1 = -x * sinY + z * cosY;
      const ax = 0.35 + state.tiltX;
      const cosX = Math.cos(ax);
      const sinX = Math.sin(ax);
      const y2 = y * cosX - z1 * sinX;
      const z2 = y * sinX + z1 * cosX;
      const scale = 2.6 / (2.6 + z2);
      return { px: cx + x1 * radius * scale, py: cy + y2 * radius * scale, depth: z2, scale };
    }

    function draw(time) {
      const t = time / 1000;
      const goal = ORB_STATES[state.name] || ORB_STATES.idle;
      for (const key of Object.keys(goal)) {
        state.current[key] += (goal[key] - state.current[key]) * 0.05;
      }
      const c = state.current;
      const speakPulse = state.name === "speaking" ? 0.35 + 0.35 * Math.abs(Math.sin(t * 8.5)) * (0.6 + 0.4 * Math.sin(t * 2.3)) : 0;
      const level = Math.max(state.level, speakPulse);
      state.burst *= 0.93;
      state.tiltX += (state.targetX - state.tiltX) * 0.04;
      state.tiltY += (state.targetY - state.tiltY) * 0.04;
      // The core drifts a little, like it is floating, and leans toward you.
      const cx = width / 2 + Math.sin(t * 0.37) * width * 0.035 + state.tiltY * width * 0.05;
      const cy = height / 2 + Math.cos(t * 0.29) * height * 0.03 + state.tiltX * height * 0.05;
      const base = Math.min(width, height) * 0.34;
      const breathe = 1 + 0.025 * Math.sin(t * 1.3) + level * 0.18 + state.burst * 0.25;
      const radius = base * breathe;

      ctx.clearRect(0, 0, width, height);
      ctx.globalCompositeOperation = "lighter";

      // Halo and core glow.
      const halo = ctx.createRadialGradient(cx, cy, radius * 0.6, cx, cy, radius * 1.7);
      halo.addColorStop(0, `rgba(255, 170, 60, ${0.1 * c.heat})`);
      halo.addColorStop(1, "rgba(255, 140, 20, 0)");
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, width, height);
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * (0.8 + level * 0.3));
      glow.addColorStop(0, `rgba(255, 250, 230, ${0.85 * c.heat})`);
      glow.addColorStop(0.12, `rgba(255, 214, 130, ${0.6 * c.heat})`);
      glow.addColorStop(0.45, `rgba(230, 140, 40, ${0.2 * c.heat})`);
      glow.addColorStop(1, "rgba(120, 50, 0, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, width, height);

      // Energy filaments.
      for (const f of filaments) {
        f.offset += f.speed * 0.012 * (1 + c.swirl * 3);
        const steps = 26;
        const cosT = Math.cos(f.tilt);
        const sinT = Math.sin(f.tilt);
        let previous = null;
        for (let i = 0; i <= steps; i += 1) {
          const a = f.offset + (i / steps) * f.length;
          const wave = 1 + 0.05 * Math.sin(a * 5 + t * 2) + level * 0.1;
          const x0 = Math.cos(a) * f.radius * wave;
          const y0 = Math.sin(a) * f.radius * wave;
          const x = x0 * Math.cos(f.turn) - y0 * sinT * Math.sin(f.turn);
          const y = y0 * cosT;
          const z = x0 * Math.sin(f.turn) + y0 * sinT * Math.cos(f.turn);
          const q = project(x, y, z, radius, cx, cy);
          if (previous) {
            const near = (1 - q.depth) / 2;
            const fade = Math.sin((i / steps) * Math.PI);
            ctx.strokeStyle = `rgba(255, ${180 + Math.round(near * 60)}, 90, ${(0.05 + near * 0.3) * fade * c.heat + level * 0.1})`;
            ctx.lineWidth = 0.6 + near * 0.9;
            ctx.beginPath();
            ctx.moveTo(previous.px, previous.py);
            ctx.lineTo(q.px, q.py);
            ctx.stroke();
          }
          previous = q;
        }
      }

      // Shell particles.
      for (const p of points) {
        const wobble = 1 + c.spread * Math.sin(t * 3 + p.phase) + level * 0.12 * Math.sin(t * 11 + p.phase * 3);
        const swirl = c.swirl * Math.sin(t * 0.8 + p.y * 3) * 0.6;
        const cs = Math.cos(swirl);
        const sn = Math.sin(swirl);
        const x = (p.x * cs - p.z * sn) * p.shell * wobble;
        const z = (p.x * sn + p.z * cs) * p.shell * wobble;
        const q = project(x, p.y * p.shell * wobble, z, radius, cx, cy);
        const near = (1 - q.depth) / 2;
        const flicker = 0.55 + 0.45 * Math.sin(t * 2.2 + p.phase);
        const alpha = Math.min(1, (0.2 + near * 0.85) * flicker * c.heat);
        const size = p.size * q.scale * (1 + level * 0.6);
        ctx.fillStyle = `rgba(255, ${170 + Math.round(near * 70)}, ${60 + Math.round(near * 90)}, ${alpha})`;
        if (p.streak && c.streak > 0.1) {
          const tail = project(x * 0.94, p.y * p.shell * wobble * 0.94, z * 0.94, radius, cx, cy);
          ctx.strokeStyle = ctx.fillStyle;
          ctx.lineWidth = size * 0.7;
          ctx.beginPath();
          ctx.moveTo(q.px, q.py);
          ctx.lineTo(q.px + (q.px - tail.px) * c.streak * 3, q.py + (q.py - tail.py) * c.streak * 3);
          ctx.stroke();
        } else {
          ctx.fillRect(q.px - size / 2, q.py - size / 2, size, size);
        }
      }

      // Orbital rings.
      for (const ring of rings) {
        const turn = t * ring.speed * (1 + c.swirl);
        for (const dot of ring.dots) {
          const a = dot.angle + turn;
          const rx = Math.cos(a) * ring.radius;
          const rz = Math.sin(a) * ring.radius;
          const ry = rz * Math.sin(ring.tilt);
          const q = project(rx, ry + dot.jitter, rz * Math.cos(ring.tilt), radius, cx, cy);
          const near = (1 - q.depth) / 2;
          ctx.fillStyle = `rgba(255, 200, 110, ${(0.08 + near * 0.35) * c.heat})`;
          ctx.fillRect(q.px, q.py, 1.4 * q.scale, 1.4 * q.scale);
        }
      }
      ctx.globalCompositeOperation = "source-over";
    }

    function loop(now) {
      frame = requestAnimationFrame(loop);
      if (!visible || document.hidden) return;
      if (frameGap && now - lastFrame < frameGap) return;
      lastFrame = now;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      spin += dt * (state.current.spin + state.burst * 2);
      draw(now);
    }
    resize();
    if (!still) frame = requestAnimationFrame(loop);

    return {
      setState(name) {
        if (state.name === name) return;
        state.name = name;
        if (still) draw(performance.now());
      },
      setLevel(value) {
        state.level = Math.max(0, Math.min(1, value || 0));
      },
      burst() {
        state.burst = 1;
        if (still) draw(performance.now());
      },
      destroy() {
        cancelAnimationFrame(frame);
        sizer.disconnect();
        watcher.disconnect();
        canvas.removeEventListener("pointermove", onPointer);
      },
    };
  }

  const hud = {
    lastSeq: 0,
    spokenSeq: 0,
    chatId: null,
    name: "Jarvis",
    thinking: false,
    speaking: false,
    listening: false,
    offline: false,
    unlocked: false,
    recognizer: null,
    optimistic: null,
    keys: {},
    orb: null,
    clockTimer: null,
    roomId: null,
  };

  const storedGet = (key) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  };
  const storedSet = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private mode: the choice lasts for this visit only */
    }
  };

  const voiceOn = () => storedGet(VOICE_KEY) !== "off";
  const speechSupported = () => "speechSynthesis" in window;
  const Recognition = () => window.SpeechRecognition || window.webkitSpeechRecognition;
  const SILENT_WAV =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
  const SPOKEN_CHUNK = 220;
  const FIRST_SPOKEN = 90;
  const TURN_SILENCE_SECONDS = 1.1;
  const TURN_MAX_SECONDS = 20;
  const TURN_WAIT_SECONDS = 8;
  const voice = {
    status: null,
    audio: null,
    unlocked: false,
    token: 0,
    talk: false,
    stream: null,
    ctx: null,
    stopRecording: null,
    setupRequested: false,
  };

  function authHeaders(extra = {}) {
    const headers = { ...extra };
    const key = token();
    if (key) headers["x-api-key"] = key;
    return headers;
  }

  function voiceStatus() {
    return voice.status || { speak: "browser", listen: "browser", speak_ready: false, listen_ready: false };
  }

  const renderedVoice = () => {
    const status = voiceStatus();
    return status.speak !== "browser" && status.speak_ready;
  };

  const recordedEars = () => {
    const status = voiceStatus();
    return (
      status.listen !== "browser" &&
      status.listen_ready &&
      window.isSecureContext &&
      Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
    );
  };

  function pickVoice() {
    const voices = speechSynthesis.getVoices();
    const english = voices.filter((item) => /^en[-_]GB/i.test(item.lang));
    return (
      english.find((item) => /daniel|arthur|george|ryan|male/i.test(item.name)) ||
      english[0] ||
      voices.find((item) => /^en/i.test(item.lang)) ||
      null
    );
  }

  function unlockSpeech() {
    // iOS only lets a page make sound after a tap has started some once.
    if (!voice.audio) voice.audio = new Audio();
    if (voice.unlocked) return;
    voice.unlocked = true;
    voice.audio.src = SILENT_WAV;
    voice.audio.play().catch(() => {});
    if (speechSupported()) {
      const silent = new SpeechSynthesisUtterance(" ");
      silent.volume = 0;
      speechSynthesis.speak(silent);
    }
  }

  function spokenParts(text) {
    const clean = text
      .replace(/```[\s\S]*?(```|$)/g, " I've put the code on screen. ")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/https?:\/\/\S+/g, "the link on screen")
      .replace(/\s*\[\d+\]/g, "")
      .replace(/[*_#>|`~]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    const sentences = clean.match(/[^.!?]+[.!?]+["')\]]*|[^.!?]+$/g) || [];
    const parts = [];
    let current = "";
    // The first piece is one short sentence (or its first clause), so the
    // voice starts as soon as possible; later pieces are longer and flow.
    const pieces = sentences.map((item) => item.trim()).filter(Boolean);
    if (pieces.length) {
      const first = pieces[0];
      const comma = first.length > FIRST_SPOKEN ? first.slice(0, FIRST_SPOKEN).lastIndexOf(", ") : -1;
      if (comma > 20) pieces.splice(0, 1, first.slice(0, comma + 1), first.slice(comma + 2));
      parts.push(pieces.shift());
    }
    for (const sentence of pieces) {
      if (current && `${current} ${sentence}`.length > SPOKEN_CHUNK) {
        parts.push(current);
        current = sentence;
      } else {
        current = current ? `${current} ${sentence}` : sentence;
      }
    }
    if (current) parts.push(current);
    return parts.slice(0, 14);
  }

  function setSpeaking(on, refs) {
    hud.speaking = on;
    if (refs) hudState(refs);
  }

  function stopSpeaking(refs) {
    voice.token += 1;
    voice.speech = null;
    if (voice.audio && voice.unlocked) voice.audio.pause();
    if (speechSupported()) speechSynthesis.cancel();
    setSpeaking(false, refs);
  }

  function playBlob(blob, turn) {
    return new Promise((resolve) => {
      const audio = voice.audio || (voice.audio = new Audio());
      const url = URL.createObjectURL(blob);
      let watch = null;
      const finish = () => {
        audio.onended = audio.onerror = null;
        clearInterval(watch);
        URL.revokeObjectURL(url);
        resolve();
      };
      watch = setInterval(() => {
        if (turn !== voice.token) {
          audio.pause();
          finish();
        }
      }, 100);
      audio.onended = finish;
      audio.onerror = finish;
      audio.src = url;
      audio.play().catch(finish);
    });
  }

  function speakWithBrowser(text, refs, done) {
    if (!speechSupported() || !voice.unlocked) return done?.();
    const turn = voice.token;
    const parts = spokenParts(text);
    if (!parts.length) return done?.();
    setSpeaking(true, refs);
    parts.forEach((part, index) => {
      const utterance = new SpeechSynthesisUtterance(part);
      const chosen = pickVoice();
      if (chosen) utterance.voice = chosen;
      utterance.rate = 1.1;
      utterance.pitch = 0.95;
      if (index === parts.length - 1) {
        utterance.onend = utterance.onerror = () => {
          if (turn !== voice.token) return;
          setSpeaking(false, refs);
          done?.();
        };
      }
      speechSynthesis.speak(utterance);
    });
  }

  const renderSpeech = (part) =>
    fetch("/studio/api/voice/speak", {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({ text: part }),
    }).then((response) => (response.ok ? response.blob() : Promise.reject(new Error(`voice ${response.status}`))));

  function speakBrowserPart(part, turn) {
    return new Promise((resolve) => {
      if (!speechSupported() || !voice.unlocked || turn !== voice.token) return resolve();
      const utterance = new SpeechSynthesisUtterance(part);
      const chosen = pickVoice();
      if (chosen) utterance.voice = chosen;
      utterance.rate = 1.1;
      utterance.pitch = 0.95;
      utterance.onend = utterance.onerror = () => resolve();
      speechSynthesis.speak(utterance);
    });
  }

  // Speak a reply while it is still being written: each finished sentence is
  // voiced as soon as it appears (rendering the next while one plays), and
  // finishSpeaking adds the rest once the reply is complete.
  function speakAhead(text, refs) {
    if (!voiceOn() || !text.trim()) return;
    let stream = voice.speech;
    if (!stream || stream.turn !== voice.token) {
      stopSpeaking(refs);
      stream = voice.speech = { turn: voice.token, chain: Promise.resolve() };
      setSpeaking(true, refs);
    }
    const turn = stream.turn;
    for (const part of spokenParts(text)) {
      if (renderedVoice() && voice.unlocked) {
        // Voice one piece at a time, in order: the first piece gets the whole
        // voice engine instead of sharing it with every later sentence.
        const blob = (stream.rendering || Promise.resolve())
          .catch(() => {})
          .then(() => (turn === voice.token ? renderSpeech(part) : Promise.reject(new Error("stopped"))));
        stream.rendering = blob;
        blob.catch(() => {});
        stream.chain = stream.chain.then(async () => {
          if (turn !== voice.token) return;
          try {
            await playBlob(await blob, turn);
          } catch {
            await speakBrowserPart(part, turn);
          }
        });
      } else {
        stream.chain = stream.chain.then(() => speakBrowserPart(part, turn));
      }
    }
  }

  function finishSpeaking(refs, done) {
    const stream = voice.speech;
    voice.speech = null;
    if (!stream) return done?.();
    stream.chain.then(() => {
      if (stream.turn !== voice.token) return;
      setSpeaking(false, refs);
      done?.();
    });
  }

  // Where the last whole sentence of a reply being written ends (0 if none).
  function sentenceCut(text) {
    let cut = 0;
    for (const match of text.matchAll(/[.!?]["')\]]*\s/g)) cut = match.index + match[0].length;
    const fences = text.slice(0, cut).split("```").length - 1;
    if (fences % 2 === 1) cut = text.slice(0, cut).lastIndexOf("```");
    return Math.max(0, cut);
  }

  async function sayAloud(text, refs, done) {
    if (!voiceOn() || !text) return done?.();
    stopSpeaking(refs);
    if (!renderedVoice() || !voice.unlocked) return speakWithBrowser(text, refs, done);
    const turn = voice.token;
    const parts = spokenParts(text);
    if (!parts.length) return done?.();
    const render = renderSpeech;
    setSpeaking(true, refs);
    // Render the next sentence while this one plays, so speech flows.
    let next = render(parts[0]);
    for (let index = 0; index < parts.length; index += 1) {
      let blob;
      try {
        blob = await next;
      } catch {
        if (turn !== voice.token) return;
        setSpeaking(false, refs);
        return speakWithBrowser(parts.slice(index).join(" "), refs, done);
      }
      if (turn !== voice.token) return;
      next = index + 1 < parts.length ? render(parts[index + 1]) : null;
      next?.catch(() => {});
      await playBlob(blob, turn);
      if (turn !== voice.token) return;
    }
    setSpeaking(false, refs);
    done?.();
  }

  function encodeWav(chunks, rate, target = 16000) {
    const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const input = new Float32Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      input.set(chunk, offset);
      offset += chunk.length;
    }
    const ratio = rate / target;
    const count = Math.floor(length / ratio);
    const view = new DataView(new ArrayBuffer(44 + count * 2));
    const text = (at, value) => [...value].forEach((ch, i) => view.setUint8(at + i, ch.charCodeAt(0)));
    text(0, "RIFF");
    view.setUint32(4, 36 + count * 2, true);
    text(8, "WAVE");
    text(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, target, true);
    view.setUint32(28, target * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    text(36, "data");
    view.setUint32(40, count * 2, true);
    for (let i = 0; i < count; i += 1) {
      const start = Math.floor(i * ratio);
      const end = Math.min(length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j += 1) sum += input[j];
      const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
      view.setInt16(44 + i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  async function recordTurn(refs) {
    if (!voice.stream) {
      voice.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    }
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!voice.ctx) voice.ctx = new Context();
    if (voice.ctx.state === "suspended") await voice.ctx.resume();
    const ctx = voice.ctx;
    const source = ctx.createMediaStreamSource(voice.stream);
    const processor = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    let heard = false;
    let silence = 0;
    let elapsed = 0;
    let floor = 0.004;
    return new Promise((resolve) => {
      const finish = (keep) => {
        processor.onaudioprocess = null;
        source.disconnect();
        processor.disconnect();
        voice.stopRecording = null;
        refs.root.style.setProperty("--level", "0");
        hud.orb?.setLevel(0);
        resolve(keep && heard ? encodeWav(chunks, ctx.sampleRate) : null);
      };
      voice.stopRecording = finish;
      processor.onaudioprocess = (event) => {
        const data = event.inputBuffer.getChannelData(0);
        chunks.push(new Float32Array(data));
        let power = 0;
        for (let i = 0; i < data.length; i += 1) power += data[i] * data[i];
        const level = Math.sqrt(power / data.length);
        const seconds = data.length / ctx.sampleRate;
        elapsed += seconds;
        if (elapsed < 0.3) floor = Math.max(floor, level);
        refs.root.style.setProperty("--level", Math.min(1, level * 12).toFixed(2));
        hud.orb?.setLevel(Math.min(1, level * 12));
        if (level > Math.max(0.015, floor * 3)) {
          heard = true;
          silence = 0;
        } else if (heard) {
          silence += seconds;
        }
        if ((heard && silence > TURN_SILENCE_SECONDS) || elapsed > TURN_MAX_SECONDS) finish(true);
        else if (!heard && elapsed > TURN_WAIT_SECONDS) finish(false);
      };
      source.connect(processor);
      processor.connect(ctx.destination);
    });
  }

  function releaseMicrophone() {
    voice.stream?.getTracks().forEach((track) => track.stop());
    voice.stream = null;
  }

  function stopListening() {
    if (hud.recognizer) {
      try {
        hud.recognizer.abort();
      } catch {
        /* already stopped */
      }
    }
    hud.recognizer = null;
    voice.stopRecording?.(false);
    hud.listening = false;
  }

  function voiceHelp() {
    openSheet("Talking to your main AI", [
      el("p", {
        text: "Browsers only share the microphone with secure pages. On this PC, open Studio at http://localhost:8082/studio and the microphone works.",
      }),
      el("p", {
        text: "On your iPhone, Studio needs an https:// address. The easy way is Tailscale, which is free:",
      }),
      el("ol", {}, [
        el("li", { text: "Install Tailscale on the PC and on the iPhone, and sign in to both with the same account." }),
        el("li", { text: "On the PC, in a terminal, run: tailscale serve --bg 8082" }),
        el("li", { text: "It prints an address like https://your-pc.tail1234.ts.net. Open that plus /studio on the iPhone and add it to the Home Screen." }),
      ]),
      el("p", {
        class: "muted",
        text: "Only your own devices on your Tailscale account can open that address.",
      }),
    ]);
  }

  async function transcribeTurn(blob) {
    const response = await fetch("/studio/api/voice/transcribe", {
      method: "POST",
      headers: authHeaders({ "content-type": "audio/wav" }),
      body: blob,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Could not hear that (${response.status})`);
    return (body.text || "").trim();
  }

  function hudState(refs) {
    const state = hud.offline
      ? "offline"
      : hud.listening
        ? "listening"
        : hud.hearing
          ? "hearing"
          : hud.speaking
            ? "speaking"
            : hud.thinking
              ? "thinking"
              : "idle";
    refs.root.dataset.state = state;
    refs.root.dataset.talk = voice.talk ? "on" : "off";
    hud.orb?.setState(state);
    if (refs.voiceState) {
      refs.voiceState.textContent = {
        offline: "Link lost",
        listening: "Listening…",
        hearing: "Understanding you",
        speaking: "Speaking",
        thinking: "Thinking",
        idle: voice.talk ? "Talk mode on" : "Tap the core to talk",
      }[state];
    }
    refs.status.textContent = {
      offline: "LINK LOST — RETRYING",
      listening: voice.talk ? "LISTENING · TALK MODE" : "LISTENING",
      hearing: "HEARING YOU",
      speaking: "SPEAKING",
      thinking: "WORKING",
      idle: voice.talk ? "TALK MODE · STANDING BY" : "STANDING BY",
    }[state];
    if (refs.talk) {
      refs.talk.textContent = voice.talk ? "END TALK" : "TALK";
      refs.talk.setAttribute("aria-pressed", String(voice.talk));
    }
  }

  const shortModel = (model) => (model || "").replace(/^local\//, "").split("/").pop();

  function hudTag(text) {
    return el("span", { class: "hud-tag", text });
  }

  function hudLine(message) {
    const data = message.data || {};
    if (data.kind === "approval") {
      const actions = el("div", { class: "row" });
      if (pendingCommands.has(data.request_id)) {
        actions.append(...approvalButtons(data.request_id, actions));
      }
      return el("div", { class: "hud-line approval" }, [
        hudTag("APPROVE?"),
        el("code", { text: data.command || message.text }),
        actions,
      ]);
    }
    if (message.role === "user") {
      return el("div", { class: "hud-line you" }, [hudTag("YOU"), message.text]);
    }
    if (message.role === "assistant") {
      return el("div", { class: `hud-line ai${data.partial ? " partial" : ""}` }, [
        hudTag((message.author || hud.name).toUpperCase()),
        message.text,
      ]);
    }
    if (message.role === "tool") {
      const team = data.tool === "team_task";
      const target = team && data.room_id ? `room/${data.room_id}` : data.chat_id ? `chat/${data.chat_id}` : "";
      const summary = message.text.split("\n")[0].slice(0, 220);
      if ((data.tool === "ask_agent" || team) && target) {
        return el(
          "button",
          { class: `hud-line handoff ${data.failed ? "bad" : "good"}`, onclick: () => go(target) },
          [hudTag(team ? "TEAM" : "AGENT"), summary]
        );
      }
      return el("div", { class: `hud-line tool${data.failed ? " bad" : ""}` }, [
        hudTag((message.author || "tool").toUpperCase()),
        summary,
      ]);
    }
    return el("div", { class: "hud-line event" }, [hudTag("SYS"), message.text]);
  }

  function voicePillKey(status) {
    const setup = status.setup || {};
    return [status.speak, status.speak_ready, status.listen_ready, setup.phase, Math.round((setup.progress || 0) * 20)];
  }

  function voicePill(status) {
    const setup = status.setup || {};
    if (setup.phase === "running") {
      return el("span", { class: "hud-pill warn", title: setup.message || "" }, [
        `VOICE ${Math.round((setup.progress || 0) * 100)}%`,
      ]);
    }
    if (setup.phase === "failed" && !status.speak_ready) {
      return el("span", { class: "hud-pill bad", title: setup.message || "" }, ["VOICE SETUP FAILED"]);
    }
    if (status.speak === "browser" || !status.speak_ready) {
      return el("span", { class: "hud-pill", title: "Using the browser's voice" }, ["VOICE BROWSER"]);
    }
    const where = status.speak === "builtin" ? "OFFLINE" : "SERVER";
    return el("span", { class: "hud-pill good", title: `Ears: ${status.listen}` }, [`VOICE ${where}`]);
  }

  function webPill(web) {
    if (web.access === "off") return el("span", { class: "hud-pill bad" }, ["WEB OFF"]);
    if (web.online === false) {
      return el("span", { class: "hud-pill warn", title: "No internet: agents work from memory until it is back" }, [
        "WEB OFFLINE",
      ]);
    }
    const name = (web.provider || "web").toUpperCase();
    if (web.problem) return el("span", { class: "hud-pill warn", title: web.problem }, [`WEB ${name}?`]);
    return el("span", { class: `hud-pill ${web.provider === "duckduckgo" ? "" : "good"}`, title: web.label || "" }, [
      `WEB ${name}`,
    ]);
  }

  function webCard(web) {
    const query = el("input", {
      type: "text",
      "aria-label": "Test search",
      placeholder: "Try a search, e.g. weather in London",
    });
    const results = el("div", { class: "stack" });
    const access = {
      all: "Every agent can search the web and read pages, local models included. Studio does the browsing for them.",
      listed: "Only agents that have web_search or web_fetch in their tools can use the internet.",
      off: "No agent can use the internet.",
    }[web.access];
    const connection =
      web.online === false
        ? "This PC is offline right now, so web tools are paused and agents work from memory and project files. They come back on their own when the internet does."
        : "This PC is online. If the internet drops, agents switch to memory and project files until it is back.";
    const service =
      web.provider === "duckduckgo"
        ? "DuckDuckGo, no key needed. It often blocks automated searches, so a key is more reliable."
        : web.problem
          ? `${web.label}: ${web.problem} Searches use DuckDuckGo until it is set.`
          : `${web.label}${web.keyed ? ", key set" : ""}. If it fails, searches fall back to DuckDuckGo.`;
    return card(
      "Internet access",
      [
        el("p", {}, [el("strong", { text: "Agents: " }), access]),
        el("p", {}, [el("strong", { text: "Connection: " }), connection]),
        el("p", {}, [el("strong", { text: "Search: " }), service]),
        el("p", {}, [
          el("strong", { text: "Research: " }),
          `${web.sources} sources per question. Every run reads at least ${(web.mix || {}).web ?? 3} web pages, ${(web.mix || {}).reddit ?? 2} Reddit threads that are on topic and have real replies (${web.reddit}), and ${(web.mix || {}).youtube ?? 2} YouTube videos whose transcripts could be read (${web.youtube}), each with its link. Coding questions add Stack Overflow, GitHub, MDN, and dev.to. Ask for a different mix any time, like "research this with no YouTube".`,
        ]),
        el("p", {
          class: "muted",
          text: "Keys go in admin settings on the computer running Studio, under Studio. Web Search API Key: Brave Search (starts with BSA), Tavily (tvly-), or Serper for Google results. YouTube API Key (optional): from Google Cloud; without it research uses YouTube's own search page. Reddit App ID and Secret: from reddit.com/prefs/apps, a free 'script' app, so Reddit doesn't block research.",
        }),
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [query]),
          el("button", {
            class: "secondary",
            text: "Test search",
            onclick: async () => {
              results.replaceChildren(el("p", { class: "muted", text: "Searching…" }));
              try {
                const body = await post("/studio/api/web/test", { query: query.value });
                if (!body.ok) {
                  results.replaceChildren(el("p", { class: "muted", text: body.error }));
                  return;
                }
                results.replaceChildren(
                  el("p", {
                    class: "muted",
                    text: `${body.results.length} result(s) from ${body.used}.${body.note ? ` ${body.note}` : ""}`,
                  }),
                  ...body.results.map((hit) =>
                    el("div", { class: "list-item" }, [
                      el("span", { class: "grow" }, [
                        el("strong", { text: hit.title }),
                        el("span", { text: hit.snippet || hit.url }),
                      ]),
                    ])
                  )
                );
              } catch (error) {
                results.replaceChildren(el("p", { class: "muted", text: error.message }));
              }
            },
          }),
        ]),
        results,
      ],
      "How your agents reach the web."
    );
  }

  function hudPanel(heading, body, extra) {
    return el("section", { class: "hud-panel" }, [
      el("header", {}, [el("h2", { text: heading }), extra || null]),
      body,
    ]);
  }

  function changed(key, value) {
    const serial = JSON.stringify(value);
    if (hud.keys[key] === serial) return false;
    hud.keys[key] = serial;
    return true;
  }

  const NAV_ITEMS = [
    ["Command Center", "home", "◈"],
    ["Agents", "agents", "◎"],
    ["Chats", "chats", "◌"],
    ["Classroom", "learn", "✎"],
    ["Models", "models", "▣"],
    ["Model Control", "engine", "⚡"],
    ["Tuning & LoRA", "tune", "⟁"],
    ["Knowledge & Memory", "more", "✦"],
    ["Settings", "settings", "⚙"],
  ];

  function ringGauge(label, value, detail) {
    const known = typeof value === "number";
    const pct = known ? Math.max(0, Math.min(100, value)) : 0;
    const circumference = 2 * Math.PI * 34;
    const tone = pct > 85 ? "hot" : pct > 65 ? "warm" : "cool";
    return el("div", { class: `hud-gauge ${tone}`, role: "img", "aria-label": `${label} ${known ? `${Math.round(pct)}%` : "unknown"}` }, [
      el("div", {
        class: "hud-gauge-ring",
        html: `<svg viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="34" class="track"/><circle cx="40" cy="40" r="34" class="fill" stroke-dasharray="${(circumference * pct) / 100} ${circumference}" transform="rotate(-90 40 40)"/></svg>`,
      }),
      el("strong", { text: known ? `${Math.round(pct)}%` : "—" }),
      el("span", { text: label }),
      detail ? el("small", { text: detail }) : null,
    ]);
  }

  function agentGlyph(role) {
    return { builder: "⌘", researcher: "⌕", helper: "✧", teacher: "✎", student: "◌", guide: "?", assistant: "◇" }[role] || "◆";
  }

  function timeAgo(ms) {
    const seconds = Math.max(0, (Date.now() - ms) / 1000);
    if (seconds < 60) return "now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
  }

  function updateHud(refs, data) {
    hud.name = data.agent.name;
    hud.thinking = Boolean(data.thinking);
    hud.offline = false;
    refs.name.textContent = data.agent.name.toUpperCase();
    refs.coreName.textContent = data.agent.name.toUpperCase();

    const local = data.systems.local || {};
    const web = data.systems.web || {};
    voice.status = data.systems.voice || voice.status;
    const spoken = voiceStatus();
    if (
      spoken.speak === "builtin" &&
      !spoken.speak_ready &&
      spoken.setup &&
      spoken.setup.phase === "idle" &&
      !voice.setupRequested
    ) {
      voice.setupRequested = true;
      post("/studio/api/voice/setup").catch(() => {});
    }
    const healthy = local.reachable !== false && !data.error;
    refs.health.textContent = healthy ? "OPTIMAL" : local.reachable === false ? "LOCAL MODELS OFFLINE" : "ATTENTION";
    refs.health.className = `hud-health ${healthy ? "good" : "warn"}`;
    if (changed("pills", [local.reachable, data.systems.main_model, data.memory, data.approvals.length, data.systems.commands, web, voicePillKey(spoken)])) {
      refs.pills.replaceChildren(
        voicePill(spoken),
        webPill(web),
        el("span", { class: `hud-pill ${local.reachable ? "good" : "bad"}`, title: local.base_url || "" }, [
          `LOCAL ${local.reachable ? `ONLINE · ${(local.models || []).length}` : "OFFLINE"}`,
        ]),
        el("span", { class: "hud-pill", title: data.systems.main_model }, [`CORE ${shortModel(data.systems.main_model)}`]),
        el("span", { class: `hud-pill ${data.memory.enabled ? "good" : ""}` }, [
          data.memory.enabled ? `SHARED MEM ${data.memory.count}` : "SHARED MEM OFF",
        ]),
        data.approvals.length
          ? el("span", { class: "hud-pill warn" }, [`APPROVALS ${data.approvals.length}`])
          : el("span", { class: "hud-pill" }, [`CMD ${data.systems.commands.toUpperCase()}`])
      );
    }

    // AI core overview.
    const busy = data.team.filter((member) => member.busy).length;
    const insights = data.insights || {};
    if (changed("overview", [data.systems.main_model, insights.memories, spoken.speak, spoken.speak_ready, busy, local.reachable, healthy])) {
      const row = (label, value, tone) =>
        el("div", { class: `hud-overview-row ${tone || ""}` }, [el("span", { text: label }), el("strong", { text: value })]);
      refs.overview.replaceChildren(
        row("AI Core", shortModel(data.systems.main_model) || "—", "good"),
        row("Memory", `${insights.memories ?? 0} stored`, "good"),
        row("Voice", spoken.speak_ready ? (spoken.speak === "builtin" ? "Offline voice" : "Online") : "Browser", spoken.speak_ready ? "good" : ""),
        row("Agents", `${busy} running · ${data.team.length} total`, busy ? "warn" : "good"),
        row("Local brain", local.reachable ? `${(local.models || []).length} models` : "Offline", local.reachable ? "good" : "bad"),
        row("System", healthy ? "Optimal" : "Check", healthy ? "good" : "warn")
      );
    }

    // Conversation.
    if (data.chat.id !== hud.chatId) {
      hud.chatId = data.chat.id;
      hud.lastSeq = 0;
      refs.log.replaceChildren();
    }
    const fresh = data.messages.filter((message) => message.sequence > hud.lastSeq);
    if (fresh.length) {
      if (hud.optimistic && fresh.some((message) => message.role === "user")) {
        hud.optimistic.remove();
        hud.optimistic = null;
      }
      refs.log.querySelector(".hud-empty")?.remove();
      refs.log.append(...fresh.map(hudLine));
      hud.lastSeq = fresh[fresh.length - 1].sequence;
      refs.log.scrollTop = refs.log.scrollHeight;
      for (const message of fresh) {
        const meta = message.data || {};
        const fromMain = message.role === "assistant" && !meta.partial && message.author === hud.name;
        const finishedWork = message.role === "event" && meta.kind === "background_done";
        if ((fromMain || finishedWork) && message.sequence > hud.spokenSeq) {
          hud.spokenSeq = message.sequence;
          hud.orb?.burst();
          const said = hud.liveSpoken;
          hud.liveSpoken = "";
          if (fromMain && said && voice.speech && message.text.startsWith(said)) {
            speakAhead(message.text.slice(said.length), refs);
            finishSpeaking(refs, () => hud.afterReply?.());
          } else {
            sayAloud(message.text, refs, () => hud.afterReply?.());
          }
        }
      }
    }
    // The reply being written right now, word by word.
    const live = (data.live || "").trim();
    if (live) {
      if (!refs.live) {
        refs.live = el("div", { class: "hud-line ai live" }, [hudTag(hud.name.toUpperCase()), el("span")]);
      }
      refs.live.lastChild.textContent = live;
      // Start talking at the first finished sentence instead of the last.
      if (!live.startsWith(hud.liveSpoken)) hud.liveSpoken = "";
      const cut = sentenceCut(live);
      if (cut > hud.liveSpoken.length) {
        const piece = live.slice(hud.liveSpoken.length, cut);
        hud.liveSpoken = live.slice(0, cut);
        speakAhead(piece, refs);
      }
      refs.log.querySelector(".hud-empty")?.remove();
      if (refs.log.lastElementChild !== refs.live) refs.log.append(refs.live);
      refs.log.scrollTop = refs.log.scrollHeight;
    } else if (refs.live) {
      refs.live.remove();
      refs.live = null;
    }
    if (!refs.log.childElementCount) {
      refs.log.append(
        el("p", {
          class: "hud-empty",
          text: `${data.agent.name} is online. Ask a question, or give the team a job: “Have Builder make a landing page for my bakery.”`,
        })
      );
    }

    // Agents at work: pick one to watch its steps. Until you pick, the
    // first agent that starts working is shown.
    if (!hud.watch && hud.watchAuto) {
      const working = data.team.find((member) => member.busy);
      if (working) refs.watchAgent(working.id, true);
    }
    if (changed("team", [data.team, hud.watch])) {
      refs.team.replaceChildren(
        ...(data.team.length
          ? data.team.map((member) =>
              el(
                "button",
                {
                  class: `hud-agent${member.busy ? " busy" : ""}${member.id === hud.watch ? " watched" : ""}`,
                  "aria-pressed": String(member.id === hud.watch),
                  "data-agent-id": member.id,
                  onclick: () => refs.watchAgent(member.id),
                },
                [
                el("span", { class: "hud-agent-icon", "aria-hidden": "true", text: agentGlyph(member.role) }),
                el("span", { class: "grow" }, [
                  el("strong", { text: member.name }),
                  el("small", {
                    text: `${member.role} · ${member.local ? "local" : member.private ? "server · no memory" : "server"} · ${shortModel(member.using || member.model)}`,
                    title: member.using && member.using !== member.model ? `Set to ${member.model}; using ${member.using} because it isn't available` : member.model,
                  }),
                ]),
                el("span", { class: "hud-agent-state" }, [el("span", { class: "hud-dot" }), member.busy ? "ACTIVE" : "READY"]),
                ]
              )
            )
          : [el("p", { class: "hud-empty", text: "No agents yet." })])
      );
    }

    // Learning: what Jarvis is teaching himself, and how far along he is.
    const learning = data.learning || [];
    if (changed("learning", learning.map((s) => [s.id, s.status, Math.round(s.progress * 1000), s.step]))) {
      refs.learning.replaceChildren(
        ...learning.map((study) =>
          el("button", { class: `hud-study ${study.status}`, type: "button", onclick: () => openStudy(study.id) }, [
            el("span", { class: "hud-study-head" }, [
              el("strong", { text: `LEARNING · ${study.topic.toUpperCase()}` }),
              el("span", { text: `${Math.round(study.progress * 100)}%` }),
            ]),
            el("span", { class: "hud-study-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(study.progress * 100)) }, [
              el("i", { style: `width:${Math.round(study.progress * 100)}%` }),
            ]),
            el("small", {
              text:
                study.status === "done"
                  ? `Finished ${study.lessons} lessons · understanding ${Math.round((study.understanding || 0) * 100)}%`
                  : study.status === "cancelled"
                    ? "Stopped"
                    : `${study.step}${study.understanding != null ? ` · understanding ${Math.round(study.understanding * 100)}%` : ""}`,
            }),
          ])
        )
      );
    }

    // Mission timeline.
    const timeline = data.timeline || [];
    if (changed("timeline", timeline.map((item) => [item.title, item.status, Math.floor(item.at / 60000)]))) {
      refs.timeline.replaceChildren(
        ...(timeline.length
          ? timeline.map((item) =>
              el("button", { class: `hud-mission ${item.status}`, onclick: () => go(item.route) }, [
                el("time", { text: timeAgo(item.at) }),
                el("span", { class: "hud-mission-bar", "aria-hidden": "true" }),
                el("span", { class: "grow" }, [el("strong", { text: item.title }), el("small", { text: `${item.who} · ${item.status}` })]),
              ])
            )
          : [el("p", { class: "hud-empty", text: "No missions yet. Give the team a job." })])
      );
    }

    // System monitor.
    const monitor = data.monitor || {};
    if (changed("monitor", [monitor.cpu, monitor.memory, monitor.disk])) {
      refs.monitor.replaceChildren(
        ringGauge("CPU", monitor.cpu, monitor.cores ? `${monitor.cores} cores` : ""),
        ringGauge("RAM", monitor.memory, monitor.memory_gb ? `${monitor.memory_gb} GB` : ""),
        ringGauge("Disk", monitor.disk, monitor.disk_gb ? `${monitor.disk_gb} GB` : "")
      );
    }

    // Memory insights.
    if (changed("insights", insights)) {
      const stat = (value, label) => el("div", { class: "hud-stat" }, [el("strong", { text: String(value ?? 0) }), el("span", { text: label })]);
      refs.insights.replaceChildren(
        el("div", { class: "hud-constellation", "aria-hidden": "true", html: constellation(insights.memories || 0) }),
        el("div", { class: "hud-stats" }, [
          stat(insights.memories, "memories"),
          stat(insights.shared, "shared"),
          stat(insights.skills, "skills"),
          stat(insights.conversations, "conversations"),
        ]),
        el("button", { class: "hud-link", type: "button", text: "Open memory & Obsidian ›", onclick: () => go("more") })
      );
    }

    // Model status.
    const voiceInfo = spoken;
    const llm = [
      ["Local brain", local.reachable ? `${(local.models || []).length} models` : "offline", local.reachable],
      ["Main core", shortModel(data.systems.main_model), true],
      ["Server model", shortModel(data.systems.server_model), !String(data.systems.server_model || "").startsWith("local/")],
      [
        "Web search",
        web.access === "off" ? "off" : web.online === false ? "offline · memory only" : web.label || "web",
        web.access !== "off" && web.online !== false && !web.problem,
      ],
      ["Voice", voiceInfo.speak_ready ? voiceInfo.speak : "browser", Boolean(voiceInfo.speak_ready)],
      ["Ears", voiceInfo.listen_ready ? voiceInfo.listen : "browser", Boolean(voiceInfo.listen_ready)],
    ];
    if (changed("llm", llm)) {
      refs.llm.replaceChildren(
        ...llm.map(([name, value, ok]) =>
          el("div", { class: `hud-llm ${ok ? "good" : "idle"}` }, [el("span", { class: "hud-dot" }), el("strong", { text: name }), el("small", { text: value })])
        )
      );
    }

    // Agent chat room.
    const room = data.room;
    if (changed("room", room)) {
      hud.roomId = room ? room.id : null;
      refs.roomTitle.textContent = room ? room.title : "No room yet";
      refs.roomMeta.textContent = room
        ? `${room.members.join(", ")}${room.running ? " · talking" : ""}${room.task_status ? ` · ${room.task_status}` : ""}`
        : "Start one and the agents can talk to you and to each other.";
      refs.roomInput.disabled = !room;
      refs.roomLog.replaceChildren(
        ...(room && room.messages.length
          ? room.messages.map((message) =>
              el("div", { class: `hud-room-line ${message.role}` }, [
                el("span", { class: "hud-tag", text: message.role === "user" ? "YOU" : (message.author || "").toUpperCase() }),
                message.text,
              ])
            )
          : [
              room
                ? el("p", { class: "hud-empty", text: "Quiet for now. Say something to the team." })
                : el("button", { class: "hud-button", type: "button", text: "START TEAM ROOM", onclick: refs.startRoom }),
            ])
      );
      refs.roomLog.scrollTop = refs.roomLog.scrollHeight;
    }

    // Live feed: approvals first, then recent jobs.
    if (changed("activity", [data.runs, data.approvals])) {
      pendingCommands = new Set(data.approvals.map((request) => request.id));
      const names = Object.fromEntries(data.team.map((member) => [member.id, member.name]));
      const rows = [
        ...data.approvals.map((request) => {
          const actions = el("div", { class: "row" });
          actions.append(...approvalButtons(request.id, actions));
          return el("div", { class: "hud-item approval" }, [
            el("small", { text: `${request.agent_id ? names[request.agent_id] || "Agent" : "Agent"} wants to run` }),
            el("code", { text: request.command }),
            actions,
          ]);
        }),
        ...data.runs.map((run) =>
          el("button", { class: `hud-item run ${run.status}`, onclick: () => go(`task/${run.id}`) }, [
            el("small", { text: `${names[run.agent_id] || "Agent"} · ${run.status}${run.status === "running" ? ` · step ${run.step}` : ""} · ${timeAgo(run.updated_at)}` }),
            el("span", { text: run.goal.slice(0, 120) }),
          ])
        ),
      ];
      refs.activity.replaceChildren(...(rows.length ? rows : [el("p", { class: "hud-empty", text: "No jobs yet." })]));
    }

    if (changed("memory", data.memory)) {
      refs.memory.replaceChildren(
        ...(data.memory.recent.length
          ? data.memory.recent.map((entry) =>
              el("div", { class: "hud-item" }, [
                el("span", { text: entry.text }),
                entry.author ? el("small", { text: `— ${entry.author}` }) : null,
              ])
            )
          : [
              el("p", {
                class: "hud-empty",
                text: data.memory.enabled
                  ? "Nothing shared yet. Agents add what they learn here."
                  : "Shared memory is off in Studio settings.",
              }),
            ])
      );
    }
    hudState(refs);
  }

  function processLine(step) {
    const tool = (step.tool || "tool").replace(/_/g, " ").toUpperCase();
    const [tag, kind] =
      step.role === "user"
        ? ["TASK", "task"]
        : step.role === "tool"
          ? [tool, step.failed ? "tool bad" : "tool"]
          : step.role === "assistant"
            ? step.partial
              ? ["THINKING", "think"]
              : ["REPORT", "done"]
            : ["SYS", "event"];
    const when = new Date(step.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const text = step.text.split("\n").slice(0, 8).join("\n");
    return el("div", { class: `hud-step ${kind}` }, [
      el("span", { class: "hud-step-meta" }, [el("span", { class: "hud-tag", text: tag }), el("time", { text: when })]),
      text.length > 700 ? `${text.slice(0, 700)}…` : text,
    ]);
  }

  function constellation(count) {
    // A little star map whose size follows how much the team remembers.
    const stars = Math.max(6, Math.min(26, 6 + Math.round(Math.sqrt(count) * 2)));
    let seed = 7;
    const rand = () => {
      seed = (seed * 9301 + 49297) % 233280;
      return seed / 233280;
    };
    const points = Array.from({ length: stars }, () => [8 + rand() * 144, 8 + rand() * 64]);
    const lines = points
      .slice(1)
      .map((point, index) => `<line x1="${points[index][0].toFixed(1)}" y1="${points[index][1].toFixed(1)}" x2="${point[0].toFixed(1)}" y2="${point[1].toFixed(1)}"/>`)
      .join("");
    const dots = points.map(([x, y], index) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${index % 5 === 0 ? 2.2 : 1.3}"/>`).join("");
    return `<svg viewBox="0 0 160 80">${lines}${dots}</svg>`;
  }

  function teardownHud() {
    hud.orb?.destroy();
    hud.orb = null;
    clearInterval(hud.clockTimer);
    hud.clockTimer = null;
    clearInterval(hud.fastTimer);
    hud.fastTimer = null;
  }

  const BRIEFING_PROMPT =
    "Executive briefing, please: what the team is working on, what finished, what failed, anything that needs my approval, and what you suggest next.";

  async function renderHud() {
    const generation = renderGeneration;
    const data = await api("/studio/api/main");
    if (generation !== renderGeneration) return;
    document.body.dataset.ui = "hud";
    teardownHud();
    hud.keys = {};
    hud.chatId = null;
    hud.optimistic = null;
    hud.roomId = null;
    hud.watch = null;
    hud.watchAuto = true;
    hud.liveSpoken = "";
    hud.watchSeq = 0;
    const last = data.messages[data.messages.length - 1];
    hud.spokenSeq = last ? last.sequence : 0;

    const input = el("input", {
      type: "text",
      id: "hud-input",
      autocomplete: "off",
      enterkeyhint: "send",
      "aria-label": `Talk to ${data.agent.name}`,
      placeholder: `Talk to ${data.agent.name}…`,
    });
    const roomInput = el("input", {
      type: "text",
      autocomplete: "off",
      enterkeyhint: "send",
      "aria-label": "Message the agent room",
      placeholder: "Message the agents…",
    });
    const canvas = el("canvas", { class: "hud-orb-canvas", "aria-hidden": "true" });
    const refs = {
      talk: el("button", {
        class: "hud-button hud-talk",
        type: "button",
        text: "TALK",
        "aria-pressed": "false",
        onclick: () => toggleTalk(),
      }),
      name: el("span", { class: "hud-name" }),
      coreName: el("strong", { class: "hud-core-name" }),
      health: el("button", {
        class: "hud-health good",
        type: "button",
        text: "OPTIMAL",
        title: "Ask the Guide what needs attention",
        onclick: () => openGuide(),
      }),
      date: el("span", { class: "hud-date" }),
      clock: el("span", { class: "hud-clock" }),
      pills: el("div", { class: "hud-pills" }),
      status: el("p", { class: "hud-status", role: "status" }),
      voiceState: el("strong", { class: "hud-voice-state" }),
      overview: el("div", { class: "hud-overview" }),
      log: el("div", { class: "hud-log", "aria-live": "polite" }),
      team: el("div", { class: "hud-agents" }),
      processHead: el("div", { class: "hud-process-head" }),
      processLog: el("div", { class: "hud-process-log", "aria-live": "polite" }),
      timeline: el("div", { class: "hud-list" }),
      learning: el("div", { class: "hud-learning", "aria-live": "polite" }),
      monitor: el("div", { class: "hud-gauges" }),
      insights: el("div", { class: "hud-insights" }),
      llm: el("div", { class: "hud-llms" }),
      roomTitle: el("strong", { class: "hud-room-title" }),
      roomMeta: el("small", { class: "hud-room-meta" }),
      roomInput,
      roomLog: el("div", { class: "hud-room-log", "aria-live": "polite" }),
      activity: el("div", { class: "hud-list" }),
      memory: el("div", { class: "hud-list" }),
    };

    const tick = () => {
      const now = new Date();
      refs.date.textContent = now
        .toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" })
        .toUpperCase();
      refs.clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    };
    tick();
    hud.clockTimer = setInterval(tick, 1000);

    const watchWork = async () => {
      const id = hud.watch;
      if (!id) {
        hud.watchBusy = false;
        refs.processHead.replaceChildren(
          el("p", { class: "hud-empty", text: "Pick an agent to watch its work live: each search, file, and step as it happens." })
        );
        refs.processLog.replaceChildren();
        return;
      }
      let work;
      try {
        work = await api(`/studio/api/agents/${id}/activity?after=${hud.watchSeq}`);
      } catch {
        return;
      }
      if (generation !== renderGeneration || hud.watch !== id) return;
      const who = work.agent;
      const run = work.run;
      hud.watchBusy = Boolean(who.busy);
      const header = [
        el("div", { class: `hud-process-title${who.busy ? " busy" : ""}` }, [
          el("span", { class: "hud-agent-icon", "aria-hidden": "true", text: agentGlyph(who.role) }),
          el("span", { class: "grow" }, [
            el("strong", { text: who.name }),
            el("small", { text: `${who.busy ? "WORKING NOW" : "IDLE"} · ${shortModel(who.model)}` }),
          ]),
          work.chat
            ? el("button", { class: "hud-link", type: "button", text: "OPEN ›", onclick: () => go(`chat/${work.chat.id}`) })
            : null,
        ]),
      ];
      if (run) {
        header.push(
          el("p", { class: "hud-process-goal" }, [
            el("small", { text: `TASK · ${run.status}${run.status === "running" ? ` · STEP ${run.step}` : ""}` }),
            run.goal.slice(0, 240),
          ])
        );
      }
      refs.processHead.replaceChildren(...header);
      const log = refs.processLog;
      if (work.messages.length) {
        log.querySelector(".hud-empty")?.remove();
        log.append(...work.messages.map(processLine));
        hud.watchSeq = work.messages[work.messages.length - 1].sequence;
        while (log.childElementCount > 120) log.firstElementChild.remove();
        log.scrollTop = log.scrollHeight;
      }
      const writing = (work.live || "").trim();
      let liveStep = log.querySelector(".hud-step.live");
      if (writing) {
        if (!liveStep) {
          liveStep = el("div", { class: "hud-step think live" }, [
            el("span", { class: "hud-step-meta" }, [el("span", { class: "hud-tag", text: "WRITING" })]),
            el("span"),
          ]);
        }
        liveStep.lastChild.textContent = writing.length > 700 ? `…${writing.slice(-700)}` : writing;
        if (log.lastElementChild !== liveStep) log.append(liveStep);
        log.querySelector(".hud-empty")?.remove();
        log.scrollTop = log.scrollHeight;
      } else {
        liveStep?.remove();
      }
      if (!log.childElementCount) {
        log.append(el("p", { class: "hud-empty", text: `${who.name} hasn't worked on anything yet.` }));
      }
    };

    refs.watchAgent = (id, automatic = false) => {
      if (!automatic) hud.watchAuto = false;
      if (hud.watch === id) return;
      hud.watch = id;
      hud.watchSeq = 0;
      refs.processLog.replaceChildren();
      hud.keys.team = "";
      for (const button of refs.team.querySelectorAll(".hud-agent")) {
        const picked = button.dataset.agentId === id;
        button.classList.toggle("watched", picked);
        button.setAttribute("aria-pressed", String(picked));
      }
      watchWork();
    };

    let polling = false;
    const poll = async () => {
      if (generation !== renderGeneration) return stopPolling();
      if (polling) return;
      polling = true;
      try {
        const next = await api(`/studio/api/main?after=${hud.lastSeq}`);
        if (generation !== renderGeneration) return;
        updateHud(refs, next);
        await watchWork();
      } catch {
        if (generation !== renderGeneration) return;
        hud.offline = true;
        hudState(refs);
      } finally {
        polling = false;
      }
    };

    const send = async (raw) => {
      const text = raw.trim();
      if (!text) return;
      input.value = "";
      unlockSpeech();
      stopSpeaking(refs);
      hud.orb?.burst();
      hud.optimistic?.remove();
      hud.optimistic = el("div", { class: "hud-line you pending" }, [hudTag("YOU"), text]);
      refs.log.querySelector(".hud-empty")?.remove();
      refs.log.append(hud.optimistic);
      refs.log.scrollTop = refs.log.scrollHeight;
      hud.thinking = true;
      hudState(refs);
      try {
        await post("/studio/api/main/messages", { text });
      } catch (error) {
        hud.thinking = false;
        hudState(refs);
        notify(error.message);
        return;
      }
      poll();
    };

    const hearWithBrowser = () => {
      const Engine = Recognition();
      const recognizer = new Engine();
      let heard = "";
      recognizer.lang = navigator.language || "en-US";
      recognizer.interimResults = true;
      recognizer.continuous = false;
      recognizer.onresult = (event) => {
        heard = Array.from(event.results)
          .map((result) => result[0].transcript)
          .join("");
        input.value = heard;
        hud.orb?.setLevel(0.6);
      };
      recognizer.onerror = (event) => {
        if (event.error === "aborted" || event.error === "no-speech") return;
        // Anything else would just fail again, so leave talk mode.
        voice.talk = false;
        if (event.error === "not-allowed" || event.error === "service-not-allowed") voiceHelp();
        else notify(`Microphone: ${event.error}`);
      };
      recognizer.onend = () => {
        const finished = hud.recognizer === recognizer;
        hud.recognizer = null;
        hud.listening = false;
        hud.orb?.setLevel(0);
        hudState(refs);
        if (finished && heard.trim()) send(heard);
        else if (finished && voice.talk) setTimeout(() => voice.talk && hear(), 250);
      };
      hud.recognizer = recognizer;
      hud.listening = true;
      hudState(refs);
      recognizer.start();
    };

    const hear = async () => {
      if (generation !== renderGeneration) return;
      if (hud.listening) {
        stopListening();
        hudState(refs);
        return;
      }
      unlockSpeech();
      stopSpeaking(refs);
      if (recordedEars()) {
        hud.listening = true;
        hudState(refs);
        let blob = null;
        try {
          blob = await recordTurn(refs);
        } catch (error) {
          hud.listening = false;
          voice.talk = false;
          hudState(refs);
          if (error && error.name === "NotAllowedError") voiceHelp();
          else notify(`Microphone: ${error.message || error}`);
          return;
        }
        hud.listening = false;
        hudState(refs);
        if (generation !== renderGeneration) return;
        if (!blob) {
          if (voice.talk) setTimeout(() => voice.talk && hear(), 250);
          return;
        }
        hud.hearing = true;
        hudState(refs);
        let text = "";
        try {
          text = await transcribeTurn(blob);
        } catch (error) {
          notify(error.message);
        }
        hud.hearing = false;
        hudState(refs);
        if (text) send(text);
        else if (voice.talk) hear();
        return;
      }
      if (Recognition() && window.isSecureContext) return hearWithBrowser();
      voice.talk = false;
      hudState(refs);
      voiceHelp();
    };

    const toggleTalk = () => {
      voice.talk = !voice.talk;
      hud.orb?.burst();
      if (voice.talk) {
        storedSet(VOICE_KEY, "on");
        voiceButton.textContent = "VOICE ON";
        voiceButton.setAttribute("aria-pressed", "true");
        hear();
      } else {
        stopListening();
        stopSpeaking(refs);
        releaseMicrophone();
      }
      hudState(refs);
    };

    // In talk mode, listen again once the reply has been spoken and the
    // main AI has finished working.
    hud.afterReply = () => {
      const resume = () => {
        if (generation !== renderGeneration || !voice.talk) return;
        if (hud.thinking || hud.speaking || hud.listening || hud.hearing) {
          setTimeout(resume, 300);
          return;
        }
        hear();
      };
      resume();
    };

    const voiceButton = el("button", {
      class: "hud-button",
      type: "button",
      text: voiceOn() ? "VOICE ON" : "VOICE OFF",
      "aria-pressed": String(voiceOn()),
      onclick: () => {
        const next = !voiceOn();
        storedSet(VOICE_KEY, next ? "on" : "off");
        unlockSpeech();
        if (!next) stopSpeaking(refs);
        voiceButton.textContent = next ? "VOICE ON" : "VOICE OFF";
        voiceButton.setAttribute("aria-pressed", String(next));
      },
    });

    const memoryInput = el("input", {
      type: "text",
      autocomplete: "off",
      "aria-label": "Tell the team to remember",
      placeholder: "Tell the team to remember…",
    });

    const startRoom = async () => {
      try {
        await post("/studio/api/rooms", { title: "Team room" });
        hud.keys.room = "";
        poll();
      } catch (error) {
        notify(error.message);
      }
    };
    refs.startRoom = startRoom;

    const rethink = () => {
      hud.keys = {};
      poll();
    };

    const prefill = (text) => {
      input.value = text;
      input.focus();
      input.setSelectionRange(text.length, text.length);
    };

    const quick = (label, detail, action) =>
      el("button", { class: "hud-quick", type: "button", onclick: action }, [
        el("strong", { text: label }),
        el("small", { text: detail }),
      ]);

    const nav = el("nav", { class: "hud-nav", "aria-label": "Studio sections" }, [
      el("div", { class: "hud-nav-brand", "aria-hidden": "true" }, [
        el("span", { class: "hud-nav-mark", text: "◉" }),
        el("span", { text: "STUDIO" }),
      ]),
      el(
        "div",
        { class: "hud-nav-items" },
        NAV_ITEMS.map(([label, target, glyph]) =>
          el(
            "button",
            {
              class: `hud-nav-item${target === "home" ? " active" : ""}`,
              type: "button",
              "aria-current": target === "home" ? "page" : null,
              onclick: () => (target === "home" ? render() : go(target)),
            },
            [el("span", { class: "hud-nav-glyph", "aria-hidden": "true", text: glyph }), label]
          )
        )
      ),
      el("div", { class: "hud-voice-box" }, [
        el("small", { text: "VOICE STATUS" }),
        refs.voiceState,
        el(
          "div",
          { class: "hud-wave", "aria-hidden": "true" },
          Array.from({ length: 14 }, (_, index) => el("span", { style: `--i:${index}` }))
        ),
      ]),
      el("button", {
        class: "hud-button",
        type: "button",
        text: "ASK THE GUIDE",
        onclick: () => openGuide(),
      }),
    ]);

    const root = el("div", { class: "hud", "data-state": "idle" }, [
      nav,
      el("header", { class: "hud-top" }, [
        el("div", { class: "hud-brand" }, [refs.name, el("small", { text: "COMMAND CENTER" })]),
        el("div", { class: "hud-sys" }, [el("small", { text: "SYSTEM STATUS" }), refs.health]),
        el("div", { class: "hud-time" }, [refs.date, refs.clock]),
        refs.pills,
      ]),
      el("div", { class: "hud-area-overview" }, [
        hudPanel(
          "AI CORE OVERVIEW",
          refs.overview,
          el("button", {
            class: "hud-link",
            type: "button",
            text: "CHOOSE BRAIN",
            onclick: () => openBrainPicker(hud.name, rethink),
          })
        ),
      ]),
      el("section", { class: "hud-core" }, [
        el("button", {
          class: "hud-orb",
          type: "button",
          "aria-label": "Talk mode: speak with your main AI",
          onclick: () => toggleTalk(),
        }, [canvas]),
        el("div", { class: "hud-core-label" }, [refs.coreName, el("small", { text: "AI CORE" })]),
        refs.status,
      ]),
      refs.log,
      el(
        "form",
        {
          class: "hud-command",
          onsubmit: (event) => {
            event.preventDefault();
            send(input.value);
          },
        },
        [
          el("div", { class: "hud-command-row" }, [
            el("button", {
              class: "hud-mic",
              type: "button",
              "aria-label": "Speak one message",
              text: "●",
              onclick: () => hear(),
            }),
            input,
            el("button", { class: "hud-send", type: "submit", text: "SEND" }),
          ]),
          el("div", { class: "hud-foot" }, [
            refs.talk,
            voiceButton,
            el("button", {
              class: "hud-button",
              type: "button",
              text: "NEW TALK",
              onclick: async () => {
                try {
                  await post("/studio/api/main/new");
                  render();
                } catch (error) {
                  notify(error.message);
                }
              },
            }),
            el("button", {
              class: "hud-button",
              type: "button",
              text: "NOTES",
              title: "What Jarvis keeps from earlier in this conversation",
              onclick: () => openConversationNotes(hud.chatId || data.chat.id),
            }),
            el("button", { class: "hud-button", type: "button", text: "MENU", onclick: () => go("more") }),
          ]),
        ]
      ),
      el("div", { class: "hud-area-room" }, [
        el("section", { class: "hud-panel hud-room" }, [
          el("header", {}, [
            el("h2", { text: "AGENT CHAT ROOM" }),
            el("button", {
              class: "hud-link",
              type: "button",
              text: "OPEN ›",
              onclick: () => (hud.roomId ? go(`room/${hud.roomId}`) : go("chats")),
            }),
          ]),
          el("div", { class: "hud-room-head" }, [refs.roomTitle, refs.roomMeta]),
          refs.roomLog,
          el(
            "form",
            {
              class: "hud-remember",
              onsubmit: async (event) => {
                event.preventDefault();
                const text = roomInput.value.trim();
                if (!text || !hud.roomId) return;
                try {
                  await post(`/studio/api/rooms/${hud.roomId}/messages`, { text });
                  roomInput.value = "";
                  hud.keys.room = "";
                  poll();
                } catch (error) {
                  notify(error.message);
                }
              },
            },
            [roomInput, el("button", { class: "hud-button", type: "submit", text: "POST" })]
          ),
        ]),
      ]),
      el("div", { class: "hud-area-feed" }, [hudPanel("LIVE INTELLIGENCE FEED", refs.activity)]),
      el("div", { class: "hud-area-team" }, [
        hudPanel(
          "AGENTS AT WORK",
          el("div", { class: "hud-work" }, [
            refs.team,
            el("div", { class: "hud-process" }, [refs.processHead, refs.processLog]),
          ]),
          el("button", {
            class: "hud-add",
            type: "button",
            "aria-label": "Add an agent",
            text: "+",
            onclick: () =>
              openAddAgent(() => {
                hud.keys.team = "";
                poll();
              }),
          })
        ),
      ]),
      el("div", { class: "hud-area-timeline" }, [
        hudPanel("MISSION TIMELINE", el("div", {}, [refs.learning, refs.timeline])),
      ]),
      el("div", { class: "hud-area-commands" }, [
        hudPanel(
          "QUICK COMMANDS",
          el("div", { class: "hud-quicks" }, [
            quick("Voice chat", "Talk hands-free", () => toggleTalk()),
            quick("Executive briefing", "What the team is up to", () => send(BRIEFING_PROMPT)),
            quick("Build", "Give Builder a job", () => prefill("Have Builder ")),
            quick("Research", "10+ sources, checked", () => prefill("Have Researcher look into ")),
            quick("Brainstorm", "Helper turns it into a plan", () => prefill("Ask Helper for ideas on ")),
            quick("Learn", "Jarvis teaches himself", () => prefill("Learn about ")),
            quick("Team room", "All agents together", () =>
              hud.roomId ? go(`room/${hud.roomId}`) : startRoom()
            ),
            quick("Choose brain", "A model on this PC", () => openBrainPicker(hud.name, rethink)),
            quick("Team brains", "A model for each agent", () => openTeamBrains(rethink)),
            quick("Model control", "Load models, settings, speed", () => go("engine")),
          ])
        ),
      ]),
      el("div", { class: "hud-area-monitor" }, [hudPanel("SYSTEM MONITOR", refs.monitor)]),
      el("div", { class: "hud-area-insights" }, [hudPanel("MEMORY INSIGHTS", refs.insights)]),
      el("div", { class: "hud-area-llm" }, [hudPanel("BRAIN STATUS", refs.llm)]),
      el("div", { class: "hud-area-memory" }, [
        hudPanel(
          "SHARED MEMORY",
          el("div", {}, [
            refs.memory,
            el(
              "form",
              {
                class: "hud-remember",
                onsubmit: async (event) => {
                  event.preventDefault();
                  const text = memoryInput.value.trim();
                  if (!text) return;
                  try {
                    await post("/studio/api/memory/shared", { text });
                    memoryInput.value = "";
                    notify("The team will remember that.");
                    poll();
                  } catch (error) {
                    notify(error.message);
                  }
                },
              },
              [memoryInput, el("button", { class: "hud-button", type: "submit", text: "SAVE" })]
            ),
          ])
        ),
      ]),
    ]);
    refs.root = root;
    view.replaceChildren(root);
    hud.orb = createCoreOrb(canvas);
    updateHud(refs, data);
    watchWork();
    // A hidden, idle window checks in less often, leaving the processor to
    // the AI; talk mode and replies being written keep the usual pace.
    const quiet = () => document.hidden && !voice.talk && !hud.thinking;
    startPolling(() => {
      if (quiet() && Date.now() - (hud.lastPoll || 0) < HIDDEN_POLL_MS) return;
      hud.lastPoll = Date.now();
      poll();
    });
    // While someone is working, check more often so replies appear as they
    // are written instead of in jumps.
    hud.fastTimer = setInterval(() => {
      if (document.hidden && !voice.talk && !hud.thinking) return;
      if (hud.thinking || hud.watchBusy || refs.live) poll();
    }, 250);
  }

  // The running notes Studio keeps once a conversation outgrows the view.
  async function openConversationNotes(chatId) {
    let notes = { text: "", until: 0 };
    try {
      notes = await api(`/studio/api/chats/${chatId}/notes`);
    } catch (error) {
      notify(error.message);
      return;
    }
    openSheet("Conversation notes", [
      el("p", {
        class: "muted",
        text: "Every message is kept word for word. Whenever you speak, the earlier messages that match are handed to Jarvis exactly as they were said, and he can search or reread any message himself. These notes are his summary on top, with a timeline, updated every 20 or so messages.",
      }),
      notes.text
        ? el("pre", { class: "conversation-notes", text: notes.text })
        : el("p", { class: "empty", text: "No notes yet: the whole conversation still fits in view." }),
    ]);
  }

  function voiceCard(status) {
    const setup = status.setup || {};
    const builtin = status.builtin || {};
    const lines = [];
    if (status.speak === "builtin") {
      lines.push(
        status.speak_ready
          ? `Built-in voice ready: ${builtin.voice === "jarvis" ? "Jarvis (a blend of two British voices)" : builtin.voice}, ${builtin.effect === "jarvis" ? "with the AI-in-the-room effect" : "dry"}. It runs on this PC and works offline.`
          : setup.phase === "running"
            ? `Downloading the voice: ${Math.round((setup.progress || 0) * 100)}%. ${setup.message || ""}`
            : `The built-in voice needs a one-time download (${Math.round((builtin.download_bytes || 0) / 1e6)} MB), then it works offline.`
      );
    } else if (status.speak === "server") {
      lines.push(`Speaking through the voice server at ${status.server.speak_url}.`);
    } else {
      lines.push(
        builtin.speech_package
          ? "Using the browser's voice."
          : "Using the browser's voice. For the built-in Jarvis voice, start Studio with the Windows launcher (it installs the voice), or install the studio_voice extra."
      );
    }
    lines.push(
      status.listen === "builtin"
        ? status.listen_ready
          ? `Your voice is understood on this PC (Whisper ${builtin.whisper}), offline.`
          : "Speech recognition downloads with the voice."
        : status.listen === "server"
          ? "Your voice is understood by the speech-to-text server."
          : "Your voice is understood by the browser's recognizer (needs internet)."
    );
    if (setup.phase === "failed") lines.push(`Last download failed: ${setup.message}`);
    const hearButton = el("button", {
      class: "primary",
      text: "Hear him",
      onclick: () => {
        unlockSpeech();
        voice.status = status;
        sayAloud("Good evening. All systems are online, and the team is standing by.", null);
      },
    });
    const setupButton = el("button", {
      class: "secondary",
      text: setup.phase === "running" ? "Downloading…" : "Download the voice",
      disabled: setup.phase === "running",
      onclick: async () => {
        try {
          await post("/studio/api/voice/setup");
          notify("Downloading the voice in the background.");
          render();
        } catch (error) {
          notify(error.message);
        }
      },
    });
    const needsSetup = status.speak === "builtin" && (!status.speak_ready || (status.listen === "builtin" && !status.listen_ready));
    return card(
      "Main AI voice",
      [
        ...lines.map((line) => el("p", { class: "muted", text: line })),
        setup.phase === "running" ? meter(setup.progress || 0) : null,
        el("div", { class: "row" }, [hearButton, needsSetup ? setupButton : null]),
        el("button", { class: "secondary", text: "Using your voice on the iPhone", onclick: () => voiceHelp() }),
      ],
      "In the HUD, tap the orb or TALK to have a spoken conversation: you talk, he answers out loud, then he listens again."
    );
  }

  /* ----------------------------------------------------------------- render */

  async function render() {
    renderGeneration += 1;
    const generation = renderGeneration;
    stopPolling();
    stopListening();
    teardownHud();
    if (!sheet.hidden) closeSheet();
    const { name, id } = route();
    const hudView = name === "hud" || name === "home";
    if (!hudView) {
      voice.talk = false;
      releaseMicrophone();
      stopSpeaking(null);
    }
    document.body.dataset.ui = hudView ? "hud" : "page";
    document.body.dataset.page = name;
    setChrome(name, headingFor(name));
    if (generation !== renderGeneration) return;
    view.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      switch (name) {
        case "home":
        case "hud": return await renderHud();
        case "chats": return await renderChats();
        case "chat": return await renderChat(id);
        case "room": return await renderRoom(id);
        case "agents": return await renderAgents();
        case "agent": return await renderAgent(id);
        case "task": return await renderTask(id);
        case "site": return await renderSite(id);
        case "learn": return await renderLearn();
        case "class": return await renderClass(id);
        case "models": return await renderModels();
        case "engine": return await renderEngine();
        case "tune": return await renderTuning(id);
        case "job": return await renderJob(id);
        case "lora": return await renderLoraJob(id);
        case "more": return await renderMore();
        case "settings": return await renderSettings();
        default: return go("home");
      }
    } catch (error) {
      if (generation !== renderGeneration) return;
      view.replaceChildren(
        error instanceof OfflineError ? offlineCard() : errorCard(error)
      );
    }
  }

  function connectCard(connect) {
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
    const rows = connect.urls.map((url) =>
      el("div", { class: "list-item" }, [
        el("span", { class: "grow" }, [
          el("strong", { text: url }),
          el("span", {
            text: url.includes("localhost")
              ? "this computer only"
              : "use this one from your phone",
          }),
        ]),
        el("button", {
          class: "secondary",
          text: "Copy",
          onclick: async () => {
            try {
              await navigator.clipboard.writeText(url);
              notify("Address copied.");
            } catch {
              notify(url);
            }
          },
        }),
      ])
    );
    return card("Install on your iPhone", [
      el("p", {
        class: "muted",
        text: standalone
          ? "Studio is installed on this device. These are the addresses it answers on."
          : "On the iPhone, open one of these in Safari, tap Share, then Add to Home Screen. Studio then runs full screen with its own icon.",
      }),
      ...rows,
      connect.loopback_only
        ? el("p", {
            class: "muted",
            text: "The server is bound to localhost, so no other device can reach it. Set HOST to 0.0.0.0 in admin settings and restart to allow your phone in.",
          })
        : null,
      connect.auth_required
        ? el("p", {
            class: "muted",
            text: "Proxy authentication is on, so these addresses carry the token. Open one once on the phone and it is remembered there.",
          })
        : el("p", {
            class: "muted",
            text: "Anyone on this network can open Studio. On a shared network, turn on proxy authentication in admin settings.",
          }),
    ]);
  }

  function modelEditor(agent) {
    const input = el("input", { type: "text", list: "model-list", value: agent.model });
    modelList().catch(() => {});
    return el("div", { class: "row" }, [
      el("div", { class: "grow" }, [el("label", {}, ["Model (server, or local/<id>)", input])]),
      el("button", {
        class: "secondary",
        text: "Save",
        onclick: async () => {
          if (!input.value.trim()) return notify("Pick a model.");
          await patch(`/studio/api/agents/${agent.id}`, { updates: { model: input.value.trim() } });
          notify("Model updated.");
          render();
        },
      }),
    ]);
  }

  async function modelList() {
    const data = await api("/studio/api/models/available");
    const list = el("datalist", { id: "model-list" }, [
      ...data.local.models.map((model) => el("option", { value: model, label: "local" })),
      ...data.server.map((model) => el("option", { value: model, label: "server" })),
    ]);
    document.getElementById("model-list")?.remove();
    document.body.append(list);
    return data;
  }

  function errorCard(error) {
    return card("Something went wrong", [
      el("p", { class: "muted", text: error.message }),
      el("button", { class: "primary", text: "Retry", onclick: render }),
    ]);
  }

  function offlineCard() {
    return card("Can't reach your Studio server", [
      el("p", {
        class: "muted",
        text: `This app talks to the server at ${location.host}. Check that the computer running it is awake, on the same network, and still serving.`,
      }),
      el("button", { class: "primary", text: "Try again", onclick: render }),
      el("p", {
        class: "muted",
        text: "Everything you have made is stored on that computer, so nothing is lost while it is offline.",
      }),
    ]);
  }

  function registerWorker() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
    navigator.serviceWorker
      .register("/studio/sw.js", { scope: "/studio" })
      .catch(() => {});
  }

  function headingFor(name) {
    return (
      {
        home: "Studio",
        hud: "HUD",
        chats: "Chats",
        chat: "Chat",
        room: "Room",
        agents: "Agents",
        agent: "Agent",
        task: "Agent task",
        site: "Site",
        learn: "Classroom",
        class: "Class",
        models: "Local models",
        engine: "Model Control",
        tune: "Tuning",
        job: "Tuning run",
        lora: "LoRA training",
        more: "More",
        settings: "Settings",
      }[name] || "Studio"
    );
  }

  registerWorker();
  render();
})();
