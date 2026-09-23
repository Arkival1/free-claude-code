/* FCC Studio — a touch-first client for agents, models, tuning, and classes. */
(() => {
  "use strict";

  const TOKEN_KEY = "fcc.studio.token";
  const TAB_ROUTES = ["home", "chats", "agents", "learn", "more"];
  const POLL_MS = 2500;

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

  async function openGuide() {
    const log = el("div", { class: "transcript" });
    const input = el("input", {
      type: "text",
      placeholder: "How do I tune a model on my phone?",
    });
    const ask = async () => {
      const question = input.value.trim();
      if (!question) return;
      input.value = "";
      log.append(el("div", { class: "bubble user", text: question }));
      try {
        const answer = await post("/studio/api/guide/ask", { question });
        const bubble = el("div", { class: "bubble assistant" }, [
          el("span", {
            class: "who",
            text: answer.offline ? "Guide (built-in help)" : "Guide",
          }),
          answer.text,
        ]);
        log.append(bubble);
        if (answer.route) {
          log.append(
            el("button", {
              class: "secondary",
              text: `Open ${answer.route.replace("/studio#", "")}`,
              onclick: () => {
                closeSheet();
                go(answer.route.replace("/studio#", ""));
              },
            })
          );
        }
      } catch (error) {
        notify(error.message);
      }
      log.scrollIntoView({ block: "end" });
    };
    openSheet("Guide", [
      el("p", {
        class: "muted",
        text: "The guide runs on the small preloaded model and knows how this app works.",
      }),
      log,
      el("div", { class: "row" }, [
        el("div", { class: "grow" }, [input]),
        el("button", { class: "primary", text: "Ask", onclick: ask }),
      ]),
    ]);
    input.focus();
  }

  /* ------------------------------------------------------------------ views */

  async function renderHome() {
    const generation = renderGeneration;
    let data = await api("/studio/api/overview");
    const waiting = (await refreshPending()).pending;
    if (!data.agents.length) {
      await post("/studio/api/bootstrap");
      data = await api("/studio/api/overview");
    }
    const settings = data.settings || {};
    const readyModels = (data.assets || []).filter(
      (asset) => asset.status === "ready"
    ).length;
    const nodes = [];

    nodes.push(
      card("Welcome", [
        el("p", {
          class: "muted",
          text: "Agents that search the web and build sites, local models you own, very light tuning, and a classroom where one AI teaches another.",
        }),
        el("div", { class: "row" }, [
          el("button", {
            class: "primary",
            text: "Ask the guide",
            onclick: openGuide,
          }),
          el("button", {
            class: "secondary",
            text: "New chat",
            onclick: () => go("chats"),
          }),
        ]),
      ])
    );

    if (!readyModels && settings.guide_model.startsWith("local/")) {
      nodes.push(
        card("Preload the guide model", [
          el("p", {
            class: "muted",
            text: "The guide answers from built-in help until its small model is on this device. Downloading it also gives you an offline model to chat with and to tune.",
          }),
          el("button", {
            class: "primary",
            text: "Download the guide model",
            onclick: async () => {
              const result = await post("/studio/api/bootstrap", {
                download_guide: true,
              });
              notify(
                result.guide_download
                  ? "Downloading the guide model."
                  : "A local model is already available."
              );
              go("models");
            },
          }),
        ])
      );
    }

    if (waiting.length) {
      nodes.push(
        card(
          `${waiting.length} command${waiting.length === 1 ? "" : "s"} waiting for you`,
          waiting.map((item) => {
            const actions = el("div", { class: "row" });
            actions.append(...approvalButtons(item.id, actions));
            return el("div", { class: "card" }, [
              el("code", { class: "command", text: item.command }),
              actions,
            ]);
          }),
          "An agent paused until you decide."
        )
      );
    }

    const active = [
      ...(data.jobs || []).filter((job) => ["queued", "running"].includes(job.status)),
      ...(data.courses || []).filter((course) =>
        ["planning", "teaching", "examining"].includes(course.status)
      ),
      ...(data.assets || []).filter((asset) =>
        ["queued", "downloading", "extracting"].includes(asset.status)
      ),
    ];
    if (active.length) {
      nodes.push(
        card(
          "In progress",
          active.map((item) =>
            el("div", { class: "card" }, [
              el("div", { class: "row-between" }, [
                el("strong", {
                  text: item.topic || item.name || item.message || "Working",
                }),
                statusPill(item.status),
              ]),
              meter(item.progress || 0),
            ])
          )
        )
      );
    }

    nodes.push(
      card(
        "Recent chats",
        (data.chats || []).length
          ? (data.chats || [])
              .slice(0, 6)
              .map((chat) =>
                el(
                  "button",
                  { class: "list-item", onclick: () => go(`chat/${chat.id}`) },
                  [
                    el("span", { class: "grow" }, [
                      el("strong", { text: chat.title }),
                      el("span", { text: `${chat.kind} · ${when(chat.updated_at)}` }),
                    ]),
                    el("span", { class: "pill", text: "open" }),
                  ]
                )
              )
          : empty("No chats yet. Start one from the Chats tab.")
      )
    );

    nodes.push(
      card("This install", [
        el("div", { class: "kv" }, [
          el("span", { text: "Default model" }),
          el("span", { text: settings.default_model || "—" }),
          el("span", { text: "Guide model" }),
          el("span", { text: settings.guide_model || "—" }),
          el("span", { text: "Light tuning" }),
          el("span", { text: settings.light_tuning_enabled ? "on" : "off" }),
          el("span", { text: "AI teacher" }),
          el("span", { text: settings.teacher_enabled ? "on" : "off" }),
          el("span", { text: "Obsidian" }),
          el("span", { text: settings.obsidian_configured ? "configured" : "not set" }),
        ]),
      ])
    );

    if (generation !== renderGeneration) return;
    view.replaceChildren(...nodes);
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
    return el("div", { class: `bubble ${role}` }, [
      message.author && role !== "user"
        ? el("span", { class: "who", text: message.author })
        : null,
      message.text,
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
      card("New agent", newAgentForm()),
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
    view.replaceChildren(...nodes);
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

  function newAgentForm() {
    const name = el("input", { type: "text", placeholder: "Researcher" });
    const model = el("input", {
      type: "text",
      list: "model-list",
      placeholder: "provider/model or local/my-model",
    });
    modelList().catch(() => {});
    const prompt = el("textarea", { placeholder: "What this agent is for." });
    return [
      el("label", {}, ["Name", name]),
      el("label", {}, ["Model", model]),
      el("label", {}, ["Instructions", prompt]),
      el("button", {
        class: "primary",
        text: "Create agent",
        onclick: async () => {
          if (!name.value.trim()) return notify("Name the agent.");
          await post("/studio/api/agents", {
            name: name.value.trim(),
            model: model.value.trim(),
            system_prompt: prompt.value.trim(),
          });
          notify("Agent created.");
          render();
        },
      }),
    ];
  }

  async function renderAgent(agentId) {
    const generation = renderGeneration;
    const [{ agents }, { memories }] = await Promise.all([
      api("/studio/api/agents"),
      api(`/studio/api/memory/${agentId}`),
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
          text: "Real training: server teachers write lessons, and a LoRA adapter changes the student model's weights. Train here if this computer has a GPU, or on a rented GPU or VPS; the result installs into Ollama and the student switches to it.",
        }),
        env,
        el("label", {}, ["Student", student]),
        el("label", {}, ["Model to train (Hugging Face)", base]),
        note,
        otherRepo,
        otherOllama,
        el("label", {}, ["Where to train", where]),
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
    const busy = /^(Trained\. Installing|Downloading the base|Creating the tuned)/.test(job.message);
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
          block("Linux or macOS", job.commands.bash),
          block("Windows PowerShell", job.commands.powershell),
        ])
      );
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
    if (job.status === "succeeded" && !job.served_model && !busy) {
      actions.push(el("button", {
        class: "secondary",
        text: "Try installing into Ollama again",
        onclick: async () => {
          await post(`/studio/api/lora/jobs/${jobId}/install`);
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

  async function renderMore() {
    const generation = renderGeneration;
    const [overview, vault, { agents }, connect] = await Promise.all([
      api("/studio/api/overview"),
      api("/studio/api/obsidian"),
      api("/studio/api/agents"),
      api("/studio/api/connect"),
    ]);
    const picker = el(
      "select",
      {},
      agents.map((agent) => el("option", { value: agent.id, text: agent.name }))
    );
    if (generation !== renderGeneration) return;
    view.replaceChildren(
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

  /* ----------------------------------------------------------------- render */

  async function render() {
    renderGeneration += 1;
    const generation = renderGeneration;
    stopPolling();
    const { name, id } = route();
    setChrome(name, headingFor(name));
    if (generation !== renderGeneration) return;
    view.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      switch (name) {
        case "home": return await renderHome();
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
        case "tune": return await renderTuning(id);
        case "job": return await renderJob(id);
        case "lora": return await renderLoraJob(id);
        case "more": return await renderMore();
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
        tune: "Tuning",
        job: "Tuning run",
        lora: "LoRA training",
        more: "More",
      }[name] || "Studio"
    );
  }

  registerWorker();
  render();
})();
