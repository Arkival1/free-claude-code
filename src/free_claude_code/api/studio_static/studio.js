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

  async function api(path, options = {}) {
    const headers = { "content-type": "application/json", ...(options.headers || {}) };
    const key = token();
    if (key) headers["x-api-key"] = key;
    const response = await fetch(path, { ...options, headers });
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
    let data = await api("/studio/api/overview");
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

    view.replaceChildren(...nodes);
  }

  async function renderChats() {
    const [{ chats }, { agents }] = await Promise.all([
      api("/studio/api/chats"),
      api("/studio/api/agents"),
    ]);
    const picker = el(
      "select",
      { id: "chat-agent" },
      agents.map((agent) =>
        el("option", { value: agent.id, text: `${agent.name} · ${agent.model}` })
      )
    );
    const nodes = [
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
              el("button", { class: "list-item", onclick: () => go(`chat/${chat.id}`) }, [
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
    view.replaceChildren(...nodes);
  }

  async function renderChat(chatId) {
    const data = await api(`/studio/api/chats/${chatId}`);
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
      try {
        const reply = await post(`/studio/api/chats/${chatId}/messages`, { text });
        log.replaceChildren(...reply.messages.map(messageBubble));
        log.lastElementChild?.scrollIntoView({ block: "end" });
      } catch (error) {
        notify(error.message);
      } finally {
        send.disabled = false;
        send.textContent = "Send";
      }
    });

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

  function messageBubble(message) {
    const role = ["user", "assistant", "tool", "event"].includes(message.role)
      ? message.role
      : "event";
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
    const [{ agents }, { sites }, { runs }] = await Promise.all([
      api("/studio/api/agents"),
      api("/studio/api/sites"),
      api("/studio/api/tasks"),
    ]);
    const nodes = [
      card("Run an agent task", [
        el("p", {
          class: "muted",
          text: "The agent searches the web, reads pages, writes files into a site, checks its work, then reports back.",
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
        "Sites",
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
          : empty("No sites yet. Create one when you start a build task.")
      ),
    ];
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
      el("option", { value: "", text: "No site" }),
      el("option", { value: "__new__", text: "Create a new site" }),
      ...sites.map((site) => el("option", { value: site.id, text: site.name })),
    ]);
    const goal = el("textarea", {
      placeholder: "Build a one-page site about local tide times, with sources.",
    });
    return [
      el("label", {}, ["Agent", agentPicker]),
      el("label", {}, ["Website workspace", sitePicker]),
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
      placeholder: "provider/model or local/my-model",
    });
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
    const [{ agents }, { memories }] = await Promise.all([
      api("/studio/api/agents"),
      api(`/studio/api/memory/${agentId}`),
    ]);
    const agent = agents.find((item) => item.id === agentId);
    if (!agent) return go("agents");
    setChrome("agent", agent.name);
    const memoryInput = el("input", { type: "text", placeholder: "Teach it a fact" });
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
    const data = await api(`/studio/api/tasks/${runId}`);
    setChrome("task", "Agent task");
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
    const data = await api(`/studio/api/sites/${siteId}/files`);
    setChrome("site", data.site.name);
    const key = token();
    const preview = `/studio/sites/${siteId}/index.html${key ? `?token=${encodeURIComponent(key)}` : ""}`;
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
    const data = await api("/studio/api/school/courses");
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
    view.replaceChildren(...nodes);
  }

  async function renderClass(courseId) {
    const data = await api(`/studio/api/school/courses/${courseId}`);
    const course = data.course;
    setChrome("class", course.topic);
    const questions = data.questions || [];
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
    const data = await api("/studio/api/models");
    setChrome("models", "Local models");
    const url = el("input", { type: "url", placeholder: "https://…/model.gguf" });
    view.replaceChildren(
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
    const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    const [data, { agents }] = await Promise.all([
      api(`/studio/api/tuning${query}`),
      api("/studio/api/agents"),
    ]);
    setChrome("tune", "Very light tuning");
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
    view.replaceChildren(
      card("How this works", [
        el("p", {
          class: "muted",
          text: "On-device tuning searches for the shortest instruction pack — a preamble, a few rules, and the clearest examples — and scores each candidate against held-out pairs. It is a handful of small calls, so it finishes on a phone. Pick the cloud backend in settings for real weight training.",
        }),
        el("div", { class: "row-between" }, [
          el("span", { class: "pill", text: `backend: ${data.backend}` }),
          el("span", {
            class: `pill ${data.enabled ? "good" : "bad"}`,
            text: data.enabled ? "tuning on" : "tuning off",
          }),
        ]),
      ]),
      card("Make a tune pack", [
        el("label", {}, ["Agent", picker]),
        el("button", {
          class: "primary",
          text: "Create pack",
          onclick: async () => {
            const pack = await post("/studio/api/tuning/packs", {
              agent_id: picker.value,
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
                  el("button", {
                    class: "primary",
                    text: "Run tune",
                    onclick: async () => {
                      try {
                        const job = await post(
                          `/studio/api/tuning/packs/${pack.id}/start`
                        );
                        notify("Tuning started.");
                        go(`job/${job.id}`);
                      } catch (error) {
                        notify(error.message);
                      }
                    },
                  }),
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
    const job = await api(`/studio/api/tuning/jobs/${jobId}`);
    setChrome("job", "Tuning run");
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
    const [overview, vault, { agents }] = await Promise.all([
      api("/studio/api/overview"),
      api("/studio/api/obsidian"),
      api("/studio/api/agents"),
    ]);
    const picker = el(
      "select",
      {},
      agents.map((agent) => el("option", { value: agent.id, text: agent.name }))
    );
    view.replaceChildren(
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
      card("Install on iPhone", [
        el("p", {
          class: "muted",
          text: "Open this page in Safari, tap Share, then Add to Home Screen. Studio then runs full screen with its own icon.",
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
    stopPolling();
    const { name, id } = route();
    setChrome(name, headingFor(name));
    view.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      switch (name) {
        case "home": return await renderHome();
        case "chats": return await renderChats();
        case "chat": return await renderChat(id);
        case "agents": return await renderAgents();
        case "agent": return await renderAgent(id);
        case "task": return await renderTask(id);
        case "site": return await renderSite(id);
        case "learn": return await renderLearn();
        case "class": return await renderClass(id);
        case "models": return await renderModels();
        case "tune": return await renderTuning(id);
        case "job": return await renderJob(id);
        case "more": return await renderMore();
        default: return go("home");
      }
    } catch (error) {
      view.replaceChildren(
        card("Something went wrong", [
          el("p", { class: "muted", text: error.message }),
          el("button", { class: "primary", text: "Retry", onclick: render }),
        ])
      );
    }
  }

  function headingFor(name) {
    return (
      {
        home: "Studio",
        chats: "Chats",
        chat: "Chat",
        agents: "Agents",
        agent: "Agent",
        task: "Agent task",
        site: "Site",
        learn: "Classroom",
        class: "Class",
        models: "Local models",
        tune: "Tuning",
        job: "Tuning run",
        more: "More",
      }[name] || "Studio"
    );
  }

  render();
})();
