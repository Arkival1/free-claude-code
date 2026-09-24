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

  async function renderMore() {
    const generation = renderGeneration;
    const [overview, vault, { agents }, connect, voiceInfo] = await Promise.all([
      api("/studio/api/overview"),
      api("/studio/api/obsidian"),
      api("/studio/api/agents"),
      api("/studio/api/connect"),
      api("/studio/api/voice"),
    ]);
    const picker = el("select", {}, [
      overview.settings.shared_memory
        ? el("option", { value: "shared", text: "Team memory (shared)" })
        : null,
      ...agents.map((agent) => el("option", { value: agent.id, text: agent.name })),
    ]);
    if (generation !== renderGeneration) return;
    view.replaceChildren(
      appearanceCard(),
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

  const UI_KEY = "fcc.studio.ui";
  const VOICE_KEY = "fcc.studio.voice";
  const ORB_SVG = `
    <svg viewBox="0 0 200 200" aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id="hud-glow">
          <stop offset="0" stop-color="#ffffff" stop-opacity="0.95" />
          <stop offset="0.35" stop-color="currentColor" stop-opacity="0.9" />
          <stop offset="1" stop-color="currentColor" stop-opacity="0" />
        </radialGradient>
      </defs>
      <circle class="orb-ring orb-outer" cx="100" cy="100" r="94" />
      <circle class="orb-ring orb-ticks" cx="100" cy="100" r="84" />
      <circle class="orb-ring orb-arc" cx="100" cy="100" r="72" />
      <circle class="orb-ring orb-arc-2" cx="100" cy="100" r="60" />
      <circle class="orb-ring orb-inner" cx="100" cy="100" r="48" />
      <circle class="orb-core" cx="100" cy="100" r="40" fill="url(#hud-glow)" />
    </svg>`;

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

  function uiMode() {
    const chosen = storedGet(UI_KEY);
    if (chosen === "hud" || chosen === "classic") return chosen;
    return document.body.dataset.uiDefault === "hud" ? "hud" : "classic";
  }

  function setUiMode(mode) {
    storedSet(UI_KEY, mode);
    if (route().name === "home") render();
    else go("home");
  }

  const voiceOn = () => storedGet(VOICE_KEY) !== "off";
  const speechSupported = () => "speechSynthesis" in window;
  const Recognition = () => window.SpeechRecognition || window.webkitSpeechRecognition;
  const SILENT_WAV =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
  const SPOKEN_CHUNK = 220;
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
    for (const sentence of sentences.map((item) => item.trim()).filter(Boolean)) {
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
      utterance.rate = 1.02;
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

  async function sayAloud(text, refs, done) {
    if (!voiceOn() || !text) return done?.();
    stopSpeaking(refs);
    if (!renderedVoice() || !voice.unlocked) return speakWithBrowser(text, refs, done);
    const turn = voice.token;
    const parts = spokenParts(text);
    if (!parts.length) return done?.();
    const render = (part) =>
      fetch("/studio/api/voice/speak", {
        method: "POST",
        headers: authHeaders({ "content-type": "application/json" }),
        body: JSON.stringify({ text: part }),
      }).then((response) => (response.ok ? response.blob() : Promise.reject(new Error(`voice ${response.status}`))));
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
        el("p", {}, [el("strong", { text: "Search: " }), service]),
        el("p", {}, [
          el("strong", { text: "Research: " }),
          `${web.sources} sources per question from the web, Reddit (${web.reddit}), YouTube (${web.youtube}, transcripts when captioned), Stack Overflow, GitHub, MDN, and dev.to.`,
        ]),
        el("p", {
          class: "muted",
          text: "Keys go in admin settings on the computer running Studio, under Studio. Web Search API Key: Brave Search (starts with BSA), Tavily (tvly-), or Serper for Google results. YouTube API Key: from Google Cloud, lets research search YouTube directly. Reddit App ID and Secret: from reddit.com/prefs/apps, a free 'script' app, so Reddit doesn't block research.",
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

  function updateHud(refs, data) {
    hud.name = data.agent.name;
    hud.thinking = Boolean(data.thinking);
    hud.offline = false;
    refs.name.textContent = data.agent.name.toUpperCase();
    refs.clock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

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
          sayAloud(message.text, refs, () => hud.afterReply?.());
        }
      }
    }
    if (!refs.log.childElementCount) {
      refs.log.append(
        el("p", {
          class: "hud-empty",
          text: `${data.agent.name} is online. Ask a question, or give the team a job: “Have Builder make a landing page for my bakery.”`,
        })
      );
    }

    if (changed("team", data.team)) {
      refs.team.replaceChildren(
        ...(data.team.length
          ? data.team.map((member) =>
              el("button", { class: `hud-agent${member.busy ? " busy" : ""}`, onclick: () => go(`agent/${member.id}`) }, [
                el("span", { class: "hud-dot" }),
                el("span", { class: "grow" }, [
                  el("strong", { text: member.name }),
                  el("small", { text: `${member.role} · ${member.local ? "local" : "server"} · ${shortModel(member.model)}` }),
                ]),
                el("span", { class: "hud-agent-state", text: member.busy ? "ACTIVE" : "READY" }),
              ])
            )
          : [el("p", { class: "hud-empty", text: "No agents yet." })])
      );
    }

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
            el("small", { text: `${names[run.agent_id] || "Agent"} · ${run.status}${run.status === "running" ? ` · step ${run.step}` : ""}` }),
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

  async function renderHud() {
    const generation = renderGeneration;
    const data = await api("/studio/api/main");
    if (generation !== renderGeneration) return;
    document.body.dataset.ui = "hud";
    hud.keys = {};
    hud.chatId = null;
    hud.optimistic = null;
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
    const refs = {
      talk: el("button", {
        class: "hud-button hud-talk",
        type: "button",
        text: "TALK",
        "aria-pressed": "false",
        onclick: () => toggleTalk(),
      }),
      name: el("span", { class: "hud-name" }),
      clock: el("span", { class: "hud-clock" }),
      pills: el("div", { class: "hud-pills" }),
      status: el("p", { class: "hud-status", role: "status" }),
      log: el("div", { class: "hud-log", "aria-live": "polite" }),
      team: el("div", { class: "hud-list" }),
      activity: el("div", { class: "hud-list" }),
      memory: el("div", { class: "hud-list" }),
    };

    const poll = async () => {
      if (generation !== renderGeneration) return stopPolling();
      try {
        const next = await api(`/studio/api/main?after=${hud.lastSeq}`);
        if (generation !== renderGeneration) return;
        updateHud(refs, next);
      } catch {
        if (generation !== renderGeneration) return;
        hud.offline = true;
        hudState(refs);
      }
    };

    const send = async (raw) => {
      const text = raw.trim();
      if (!text) return;
      input.value = "";
      unlockSpeech();
      stopSpeaking(refs);
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

    const root = el("div", { class: "hud", "data-state": "idle" }, [
      el("header", { class: "hud-top" }, [
        el("div", { class: "hud-brand" }, [refs.name, refs.clock]),
        refs.pills,
      ]),
      el("section", { class: "hud-core" }, [
        el("button", {
          class: "hud-orb",
          type: "button",
          "aria-label": "Talk mode: speak with your main AI",
          html: ORB_SVG,
          onclick: () => toggleTalk(),
        }),
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
          el("button", {
            class: "hud-mic",
            type: "button",
            "aria-label": "Speak one message",
            text: "●",
            onclick: () => hear(),
          }),
          input,
          el("button", { class: "hud-send", type: "submit", text: "SEND" }),
        ]
      ),
      el("div", { class: "hud-team" }, [
        hudPanel(
          "TEAM",
          refs.team,
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
      el("div", { class: "hud-side" }, [
        hudPanel("ACTIVITY", refs.activity),
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
      el("footer", { class: "hud-foot" }, [
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
        refs.talk,
        voiceButton,
        el("button", { class: "hud-button", type: "button", text: "MENU", onclick: () => go("more") }),
        el("button", {
          class: "hud-button",
          type: "button",
          text: "CLASSIC UI",
          onclick: () => setUiMode("classic"),
        }),
      ]),
    ]);
    refs.root = root;
    view.replaceChildren(root);
    updateHud(refs, data);
    startPolling(poll);
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

  function appearanceCard() {
    const mode = uiMode();
    return card(
      "Appearance",
      [
        el("div", { class: "row" }, [
          el("button", {
            class: mode === "classic" ? "primary" : "secondary",
            text: "Classic app",
            "aria-pressed": String(mode === "classic"),
            onclick: () => setUiMode("classic"),
          }),
          el("button", {
            class: mode === "hud" ? "primary" : "secondary",
            text: "HUD console",
            "aria-pressed": String(mode === "hud"),
            onclick: () => setUiMode("hud"),
          }),
        ]),
      ],
      "HUD turns Home into a console for your main AI, which runs the other agents for you. All agents share one team memory. This choice is saved on this device."
    );
  }

  /* ----------------------------------------------------------------- render */

  async function render() {
    renderGeneration += 1;
    const generation = renderGeneration;
    stopPolling();
    stopListening();
    const { name, id } = route();
    const hudView = name === "hud" || (name === "home" && uiMode() === "hud");
    if (!hudView) {
      voice.talk = false;
      releaseMicrophone();
      stopSpeaking(null);
    }
    document.body.dataset.ui = hudView ? "hud" : "classic";
    setChrome(name, headingFor(name));
    if (generation !== renderGeneration) return;
    view.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      switch (name) {
        case "home": return hudView ? await renderHud() : await renderHome();
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
