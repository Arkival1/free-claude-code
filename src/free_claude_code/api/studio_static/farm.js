/* FCC Studio Content Farm — faceless short videos, idea to finished MP4.
   Channels (one per account and niche), a production line from idea to
   posted, a posting queue with captions ready to paste, every video in a
   phone frame, each channel's settings, and the Farm chat with the main AI,
   all on one page. Studio calls FCCFarm.render(ctx). */
(() => {
  "use strict";

  const MODES = [
    ["line", "Production line", "🏭"],
    ["queue", "Posting queue", "📅"],
    ["videos", "Videos", "🎬"],
    ["setup", "Channel settings", "⚙"],
  ];
  const MODE_KEY = "fcc.farm.mode";
  const CHANNEL_KEY = "fcc.farm.channel";
  const SUGGESTIONS = [
    "Make 3 reels about black holes",
    "Give me 5 video ideas",
    "Start a channel about gym motivation",
    "What's ready to post?",
    "Make a story video about a haunted lighthouse",
  ];
  const COLUMNS = [
    ["idea", "Ideas", "💡"],
    ["making", "Making", "⚙"],
    ["ready", "Ready to post", "✅"],
    ["posted", "Posted", "📤"],
  ];
  const VISUALS = [
    ["photos", "Free photos", "Real photos from Openverse, free to use. Needs the internet."],
    ["ai", "AI pictures", "Made on this PC by your Stable Diffusion (set its address in Settings)."],
    ["text", "Art cards", "Glowing gradient cards. Always works, even offline."],
  ];
  const LOOK_NOTES = {
    bold: "Big yellow pop words, the classic viral style",
    clean: "White pills, calm and readable",
    neon: "Glowing cyan and pink",
    cinema: "Movie bars and gold serif words",
  };

  const state = {
    mode: read(MODE_KEY, "line"),
    channelId: read(CHANNEL_KEY, ""),
    data: null,
    chatAfter: 0,
    chatMessages: [],
    chatBusy: false,
    agentName: "Jarvis",
  };

  let ctx = null;
  let stage = null;
  let header = null;
  let channelStrip = null;
  let chatLog = null;
  let chatTimer = null;
  let farmTimer = null;

  function read(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch {
      return fallback;
    }
  }

  function keep(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private mode: remembering the tab is only a convenience */
    }
  }

  /* ------------------------------------------------------------ helpers */

  const h = (...args) => ctx.el(...args);
  // Optional pieces are null; the DOM would print them as "null".
  const clean = (nodes) => nodes.flat().filter((node) => node != null && node !== false);

  function tone(text) {
    let hash = 0;
    for (const char of String(text || "")) hash = (hash * 31 + char.charCodeAt(0)) % 360;
    return hash;
  }

  function avatar(channel, size = "") {
    const letters = (channel.name || "?").replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "?";
    return h("span", { class: `farm-avatar ${size}`, style: `--hue:${tone(channel.name)}`, text: letters, "aria-hidden": "true" });
  }

  function slot(ms) {
    if (!ms) return "No time set";
    const date = new Date(ms);
    const today = new Date();
    const tomorrow = new Date(Date.now() + 86_400_000);
    const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (date.toDateString() === today.toDateString()) return `Today ${time}`;
    if (date.toDateString() === tomorrow.toDateString()) return `Tomorrow ${time}`;
    return `${date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} ${time}`;
  }

  const channels = () => (state.data && state.data.channels) || [];
  const posts = () => (state.data && state.data.posts) || [];
  const channel = () => channels().find((item) => item.id === state.channelId) || null;
  const channelName = (id) => {
    const found = channels().find((item) => item.id === id);
    return found ? `@${found.name}` : "";
  };

  function modal(heading, nodes) {
    const box = h("div", { class: "lab-modal farm-modal", role: "dialog", "aria-modal": "true", "aria-label": heading }, [
      h("div", { class: "lab-modal-card" }, [
        h("header", {}, [
          h("h3", { text: heading }),
          h("button", { class: "ghost-button", type: "button", "aria-label": "Close", text: "✕", onclick: () => box.remove() }),
        ]),
        ...nodes,
      ]),
    ]);
    box.addEventListener("click", (event) => {
      if (event.target === box) box.remove();
    });
    document.body.append(box);
    return box;
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = h("textarea", { class: "visually-hidden" });
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    ctx.notify("Caption copied. Paste it under the video.");
  }

  async function act(work, done) {
    try {
      const result = await work();
      if (done) ctx.notify(done);
      await refresh();
      return result;
    } catch (error) {
      ctx.notify(error.message);
      return null;
    }
  }

  /* ------------------------------------------------------------ layout */

  async function render(context) {
    ctx = context;
    state.data = await ctx.api("/studio/api/farm");
    if (!ctx.alive()) return;
    pickChannel();
    header = h("div", { class: "farm-hero" });
    channelStrip = h("div", { class: "farm-channels", role: "list", "aria-label": "Channels" });
    stage = h("div", { class: "farm-stage" });
    const modes = h(
      "div",
      { class: "lab-modes farm-modes", role: "tablist", "aria-label": "Content Farm" },
      MODES.map(([id, label, icon]) =>
        h("button", {
          class: `lab-mode ${state.mode === id ? "active" : ""}`,
          type: "button",
          role: "tab",
          "aria-selected": state.mode === id ? "true" : "false",
          "data-mode": id,
          onclick: () => switchMode(id),
        }, [h("span", { class: "lab-mode-icon", text: icon }), h("span", { text: label })])
      )
    );
    const layout = h("div", { class: "lab farm" }, [
      h("div", { class: "lab-main farm-main" }, [header, channelStrip, modes, stage]),
      chatPanel(),
    ]);
    ctx.view.replaceChildren(layout);
    draw();
    await refreshChat(true);
    watch();
  }

  function pickChannel() {
    if (!channel() && channels().length) {
      state.channelId = channels()[channels().length - 1].id;
      keep(CHANNEL_KEY, state.channelId);
    }
  }

  function switchMode(mode) {
    state.mode = mode;
    keep(MODE_KEY, mode);
    for (const button of document.querySelectorAll(".farm-modes .lab-mode")) {
      const on = button.dataset.mode === mode;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    }
    drawStage();
  }

  function chooseChannel(id) {
    state.channelId = id;
    keep(CHANNEL_KEY, id);
    draw();
  }

  function draw() {
    drawHeader();
    drawChannels();
    drawStage();
  }

  function drawStage() {
    if (!stage) return;
    const pages = { line: drawLine, queue: drawQueue, videos: drawVideos, setup: drawSetup };
    stage.replaceChildren();
    (pages[state.mode] || drawLine)();
  }

  async function refresh() {
    try {
      state.data = await ctx.api("/studio/api/farm");
    } catch {
      return;
    }
    if (!ctx.alive()) return;
    pickChannel();
    // Don't redraw a form the user is typing in.
    if (state.mode === "setup" && stage && stage.contains(document.activeElement)) {
      drawHeader();
      drawChannels();
    } else {
      draw();
    }
    watch();
  }

  // While a video is being made, check on it every couple of seconds. Only
  // its progress moves in place; the page redraws when something finishes.
  function watch() {
    clearTimeout(farmTimer);
    const making = posts().some((post) => post.status === "making");
    if (!making) return;
    farmTimer = setTimeout(async () => {
      if (!ctx.alive()) return;
      const before = statuses();
      let fresh;
      try {
        fresh = await ctx.api("/studio/api/farm");
      } catch {
        watch();
        return;
      }
      if (!ctx.alive()) return;
      state.data = fresh;
      if (statuses() !== before) {
        draw();
      } else {
        for (const post of posts().filter((item) => item.status === "making")) {
          const card = stage && stage.querySelector(`.farm-card[data-id="${post.id}"]`);
          if (!card) continue;
          const bar = card.querySelector(".farm-meter i");
          const stageText = card.querySelector("small");
          if (bar) bar.style.width = `${post.progress || 0}%`;
          if (stageText) stageText.textContent = post.stage || "Working…";
        }
      }
      watch();
    }, 2000);
  }

  function statuses() {
    return posts().map((post) => `${post.id}:${post.status}`).join(",");
  }

  /* ------------------------------------------------------------ header */

  function drawHeader() {
    if (!header) return;
    const all = posts();
    const count = (status) => all.filter((post) => post.status === status).length;
    const tools = state.data.tools || {};
    const today = new Date().toDateString();
    const postedToday = all.filter((post) => post.status === "posted" && post.posted_at && new Date(post.posted_at).toDateString() === today).length;
    const stats = [
      ["Channels", channels().length, "📡"],
      ["Ideas", count("idea"), "💡"],
      ["Making", count("making"), "⚙"],
      ["Ready", count("ready"), "✅"],
      ["Posted today", postedToday, "📤"],
    ];
    const warnings = [];
    if (!tools.video) {
      warnings.push(h("div", { class: "farm-warning" }, [
        h("strong", { text: "Videos can't be made yet. " }),
        `${tools.why || ""} On Windows, run the FCC Studio installer again: it adds Pillow and ffmpeg.`,
      ]));
    }
    if (!state.data.voice) {
      warnings.push(h("div", { class: "farm-note" }, [
        "No voiceover yet: turn on the built-in voice in Settings → Voice (it downloads once). Until then videos are captions only.",
      ]));
    }
    header.replaceChildren(...clean([
      h("div", { class: "farm-title" }, [
        h("span", { class: "farm-logo", "aria-hidden": "true", text: "🌾" }),
        h("div", {}, [
          h("h1", { text: "Content Farm" }),
          h("p", { class: "muted", text: "Faceless Reels, TikToks, and Shorts made on this PC: idea, script, voice, pictures, captions, finished MP4." }),
        ]),
      ]),
      h("div", { class: "farm-stats" }, stats.map(([label, value, icon]) =>
        h("div", { class: "farm-stat" }, [
          h("span", { class: "farm-stat-icon", text: icon, "aria-hidden": "true" }),
          h("strong", { text: String(value) }),
          h("small", { text: label }),
        ])
      )),
      ...warnings,
    ]));
  }

  function drawChannels() {
    if (!channelStrip) return;
    const items = channels().map((item) => {
      const counts = item.counts || {};
      return h("button", {
        class: `farm-channel ${item.id === state.channelId ? "active" : ""}`,
        type: "button",
        role: "listitem",
        "aria-pressed": item.id === state.channelId ? "true" : "false",
        onclick: () => chooseChannel(item.id),
      }, [
        avatar(item),
        h("span", { class: "farm-channel-text" }, [
          h("strong", { text: `@${item.name}` }),
          h("small", { text: `${item.platform_label} · ${item.style_label}` }),
          h("small", { class: "muted", text: `${counts.ready || 0} ready · ${counts.idea || 0} ideas${item.autopilot ? " · autopilot" : ""}` }),
        ]),
      ]);
    });
    items.push(h("button", {
      class: "farm-channel add",
      type: "button",
      onclick: () => {
        state.channelId = "";
        switchMode("setup");
        drawChannels();
      },
    }, [h("span", { class: "farm-avatar plus", text: "+" }), h("span", { text: "New channel" })]));
    channelStrip.replaceChildren(...items);
  }

  /* ------------------------------------------------------------ production line */

  function drawLine() {
    const chosen = channel();
    if (!chosen) {
      stage.append(welcome());
      return;
    }
    const idea = h("input", { type: "text", placeholder: "An idea or a topic, e.g. why cats knock things over", "aria-label": "New idea" });
    const counted = (chosen.counts || {});
    const actions = h("form", {
      class: "farm-actions",
      onsubmit: async (event) => {
        event.preventDefault();
        const title = idea.value.trim();
        if (!title) return;
        idea.value = "";
        await act(() => ctx.post(`/studio/api/farm/channels/${chosen.id}/posts`, { title }), "Idea added.");
      },
    }, [
      h("div", { class: "grow" }, [idea]),
      h("button", { class: "ghost-button", type: "submit", text: "Add idea" }),
      h("button", {
        class: "ghost-button",
        type: "button",
        text: "✨ 5 ideas",
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          button.textContent = "Thinking…";
          await act(() => ctx.post(`/studio/api/farm/channels/${chosen.id}/ideas`, { count: 5, topic: idea.value.trim() }), "New ideas on the board.");
          idea.value = "";
        },
      }),
      h("button", {
        class: "primary",
        type: "button",
        text: `▶ Make today's ${chosen.posts_per_day} video${chosen.posts_per_day === 1 ? "" : "s"}`,
        onclick: () => act(() => ctx.post(`/studio/api/farm/channels/${chosen.id}/fill`), "Making them now; watch the line."),
      }),
    ]);
    const mine = posts().filter((post) => post.channel_id === chosen.id);
    const board = h("div", { class: "farm-board" }, COLUMNS.map(([status, label, icon]) => {
      const cards = mine
        .filter((post) => post.status === status || (status === "idea" && post.status === "failed"))
        .sort((a, b) => (status === "ready" ? (a.scheduled_at || 0) - (b.scheduled_at || 0) : b.created_at - a.created_at));
      return h("section", { class: `farm-column col-${status}` }, [
        h("h3", {}, [h("span", { text: icon, "aria-hidden": "true" }), ` ${label}`, h("span", { class: "farm-count", text: String(cards.length) })]),
        ...(cards.length ? cards.map(postCard) : [h("p", { class: "muted small", text: emptyText(status) })]),
      ]);
    }));
    stage.append(h("section", { class: "card farm-line" }, [
      h("div", { class: "farm-line-head" }, [
        avatar(chosen, "big"),
        h("div", { class: "grow" }, [
          h("h2", { text: `@${chosen.name}` }),
          h("p", { class: "muted", text: `${chosen.niche || "No niche yet"} · ${chosen.style_label} · ${chosen.seconds}s · ${chosen.platform_label} · posts at ${chosen.post_times.join(", ")}` }),
        ]),
        h("span", { class: `pill ${chosen.autopilot ? "good" : ""}`, text: chosen.autopilot ? "Autopilot on" : `${counted.ready || 0} ready` }),
      ]),
      actions,
      board,
    ]));
  }

  function emptyText(status) {
    return {
      idea: "No ideas yet. Add one, or press ✨ 5 ideas.",
      making: "Nothing in the oven.",
      ready: "Finished videos wait here.",
      posted: "Mark videos posted once they're up.",
    }[status];
  }

  function postCard(post) {
    if (post.status === "making") {
      return h("article", { class: "farm-card is-making", "data-id": post.id }, [
        h("strong", { text: post.title }),
        h("small", { class: "muted", text: post.stage || "Working…" }),
        h("div", { class: "meter farm-meter" }, [h("i", { style: `width:${post.progress || 0}%` })]),
        h("button", { class: "ghost-button small", type: "button", text: "Stop", onclick: () => act(() => ctx.remove(`/studio/api/farm/posts/${post.id}`), "Stopped.") }),
      ]);
    }
    if (post.status === "ready" || post.status === "posted") {
      return h("article", { class: `farm-card is-${post.status}`, "data-id": post.id }, [
        h("button", { class: "farm-thumb", type: "button", "aria-label": `Watch ${post.title}`, onclick: () => openPost(post) }, [
          h("img", { src: post.cover_url, alt: "", loading: "lazy" }),
          h("span", { class: "farm-play", text: "▶", "aria-hidden": "true" }),
        ]),
        h("div", { class: "farm-card-text" }, [
          h("strong", { text: post.title }),
          h("small", { class: "muted", text: post.status === "posted" ? `Posted ${new Date(post.posted_at).toLocaleString()}` : `Post ${slot(post.scheduled_at)}` }),
        ]),
      ]);
    }
    const failed = post.status === "failed";
    return h("article", { class: `farm-card is-idea ${failed ? "is-failed" : ""}`, "data-id": post.id }, [
      h("strong", { text: post.title }),
      failed ? h("small", { class: "farm-error", text: post.error }) : h("small", { class: "muted", text: `by ${post.made_by}` }),
      h("div", { class: "row farm-card-buttons" }, [
        h("button", { class: "primary small", type: "button", text: failed ? "Try again" : "Make", onclick: () => act(() => ctx.post(`/studio/api/farm/posts/${post.id}/make`), "Making it now.") }),
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Rename ${post.title}`, text: "✎", onclick: () => renameIdea(post) }),
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Delete ${post.title}`, text: "🗑", onclick: () => act(() => ctx.remove(`/studio/api/farm/posts/${post.id}`)) }),
      ]),
    ]);
  }

  function renameIdea(post) {
    const input = h("input", { type: "text", value: post.title, "aria-label": "Idea" });
    const box = modal("Change the idea", [
      input,
      h("div", { class: "row" }, [
        h("button", {
          class: "primary",
          type: "button",
          text: "Save",
          onclick: async () => {
            box.remove();
            await act(() => ctx.patch(`/studio/api/farm/posts/${post.id}`, { title: input.value }));
          },
        }),
      ]),
    ]);
    input.focus();
  }

  function welcome() {
    return h("section", { class: "card farm-welcome" }, [
      h("h2", { text: "Start your farm" }),
      h("p", { text: "A channel is one account: a niche, a video style, a voice, and when it posts. Make one, and the farm fills its idea board, writes each script with your local AI, reads it aloud, finds pictures, and renders a vertical video with captions." }),
      h("ol", { class: "farm-steps" }, [
        h("li", { text: "Make a channel: pick a niche people binge (space facts, scary stories, gym motivation, money tips)." }),
        h("li", { text: "Press ✨ 5 ideas, or ask in the Farm chat." }),
        h("li", { text: "Press Make. Each video takes a minute or two." }),
        h("li", { text: "Post from the queue: download, paste the caption, mark it posted." }),
      ]),
      h("button", { class: "primary", type: "button", text: "Make my first channel", onclick: () => switchMode("setup") }),
    ]);
  }

  /* ------------------------------------------------------------ queue */

  function drawQueue() {
    const ready = posts().filter((post) => post.status === "ready").sort((a, b) => (a.scheduled_at || 0) - (b.scheduled_at || 0));
    if (!ready.length) {
      stage.append(h("section", { class: "card" }, [h("h2", { text: "Posting queue" }), h("p", { class: "muted", text: "No finished videos yet. Make some on the production line, or ask in the Farm chat." })]));
      return;
    }
    const days = new Map();
    for (const post of ready) {
      const day = post.scheduled_at ? new Date(post.scheduled_at).toDateString() : "Any time";
      if (!days.has(day)) days.set(day, []);
      days.get(day).push(post);
    }
    const sections = [...days.entries()].map(([day, list]) =>
      h("div", { class: "farm-day" }, [
        h("h3", { text: day === new Date().toDateString() ? "Today" : day === "Any time" ? day : new Date(day).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }) }),
        ...list.map(queueRow),
      ])
    );
    stage.append(h("section", { class: "card farm-queue" }, [
      h("h2", { text: "Posting queue" }),
      h("p", { class: "muted small", text: "Post each one at its time: download it, upload it in the app, paste the caption, add a trending sound, then mark it posted." }),
      ...sections,
    ]));
  }

  function queueRow(post) {
    return h("div", { class: "farm-row" }, [
      h("button", { class: "farm-thumb small", type: "button", "aria-label": `Watch ${post.title}`, onclick: () => openPost(post) }, [
        h("img", { src: post.cover_url, alt: "", loading: "lazy" }),
      ]),
      h("div", { class: "grow" }, [
        h("strong", { text: post.title }),
        h("small", { class: "muted", text: `${slot(post.scheduled_at)} · ${channelName(post.channel_id)} · ${post.data.duration || "?"}s` }),
      ]),
      h("div", { class: "row farm-row-buttons" }, [
        h("a", { class: "ghost-button small", href: `${post.video_url}?download=1`, download: "", text: "⬇ Download" }),
        h("button", { class: "ghost-button small", type: "button", text: "📋 Caption", onclick: () => copy(post.data.caption_full || "") }),
        h("button", { class: "primary small", type: "button", text: "✓ Posted", onclick: () => act(() => ctx.post(`/studio/api/farm/posts/${post.id}/posted`, { posted: true }), "Marked as posted.") }),
      ]),
    ]);
  }

  /* ------------------------------------------------------------ videos */

  function drawVideos() {
    const done = posts().filter((post) => post.video_url);
    if (!done.length) {
      stage.append(h("section", { class: "card" }, [h("h2", { text: "Videos" }), h("p", { class: "muted", text: "Finished videos show here in a phone frame." })]));
      return;
    }
    stage.append(h("section", { class: "card" }, [
      h("h2", { text: "Videos" }),
      h("div", { class: "farm-gallery" }, done.map((post) =>
        h("figure", { class: "farm-phone" }, [
          h("video", { src: post.video_url, poster: post.cover_url, controls: "", playsinline: "", preload: "none" }),
          h("figcaption", {}, [
            h("strong", { text: post.title }),
            h("small", { class: "muted", text: `${channelName(post.channel_id)} · ${post.status === "posted" ? "posted" : slot(post.scheduled_at)}` }),
            h("button", { class: "link-button", type: "button", text: "Details", onclick: () => openPost(post) }),
          ]),
        ])
      )),
    ]));
  }

  function openPost(post) {
    const caption = h("textarea", { rows: 6, "aria-label": "Caption" });
    caption.value = (post.data && post.data.caption_full) || "";
    const script = (post.data && post.data.script) || {};
    const scenes = (script.scenes || []).map((scene, index) =>
      h("li", {}, [h("strong", { text: `${index + 1}. ` }), scene.say, h("small", { class: "muted", text: `  [${scene.show}]` })])
    );
    const box = modal(post.title, [
      h("div", { class: "farm-detail" }, [
        h("div", { class: "farm-phone big" }, [
          h("video", { src: post.video_url, poster: post.cover_url, controls: "", playsinline: "", autoplay: "" }),
        ]),
        h("div", { class: "farm-detail-text" }, [
          h("p", { class: "muted", text: `${channelName(post.channel_id)} · ${post.data.duration || "?"} seconds · ${post.status === "posted" ? "posted" : `post ${slot(post.scheduled_at)}`}${post.data.voiced ? "" : " · no voice"}` }),
          h("label", {}, ["Caption and hashtags", caption]),
          h("div", { class: "row" }, [
            h("button", { class: "ghost-button small", type: "button", text: "📋 Copy", onclick: () => copy(caption.value) }),
            h("button", { class: "ghost-button small", type: "button", text: "Save caption", onclick: () => act(() => ctx.patch(`/studio/api/farm/posts/${post.id}`, { caption: caption.value }), "Caption saved.") }),
            h("a", { class: "ghost-button small", href: `${post.video_url}?download=1`, download: "", text: "⬇ Download" }),
          ]),
          h("details", {}, [h("summary", { text: "Script" }), h("ol", { class: "farm-script" }, scenes)]),
          h("div", { class: "row" }, [
            post.status === "posted"
              ? h("button", { class: "ghost-button small", type: "button", text: "Back to the queue", onclick: async () => { box.remove(); await act(() => ctx.post(`/studio/api/farm/posts/${post.id}/posted`, { posted: false })); } })
              : h("button", { class: "primary small", type: "button", text: "✓ Mark posted", onclick: async () => { box.remove(); await act(() => ctx.post(`/studio/api/farm/posts/${post.id}/posted`, { posted: true }), "Marked as posted."); } }),
            h("button", { class: "ghost-button small", type: "button", text: "↻ Make again", onclick: async () => { box.remove(); await act(() => ctx.post(`/studio/api/farm/posts/${post.id}/make`), "Making it again."); } }),
            h("button", { class: "ghost-button small danger", type: "button", text: "🗑 Delete", onclick: async () => { box.remove(); await act(() => ctx.remove(`/studio/api/farm/posts/${post.id}`)); } }),
          ]),
          post.data.credits && post.data.credits.length ? h("p", { class: "muted small", text: `Photos: ${post.data.credits.join("; ")}` }) : null,
        ]),
      ]),
    ]);
    return box;
  }

  /* ------------------------------------------------------------ settings */

  function drawSetup() {
    const chosen = channel();
    const value = (key, fallback) => (chosen && chosen[key] != null ? chosen[key] : fallback);
    const field = (label, input, hint) => h("label", { class: "farm-field" }, clean([label, input, hint ? h("small", { class: "muted", text: hint }) : null]));
    const name = h("input", { type: "text", value: value("name", ""), placeholder: "e.g. spacefacts.daily", "aria-label": "Channel name" });
    const niche = h("input", { type: "text", value: value("niche", ""), placeholder: "e.g. space facts, scary stories, gym motivation", "aria-label": "Niche" });
    const platform = h("select", { "aria-label": "Platform" }, Object.entries(state.data.platforms || {}).map(([key, label]) =>
      h("option", { value: key, text: label, selected: value("platform", "instagram") === key })
    ));
    let style = value("style", "facts");
    const styles = h("div", { class: "farm-styles", role: "radiogroup", "aria-label": "Video style" });
    const drawStyles = () => styles.replaceChildren(...(state.data.styles || []).map((item) =>
      h("button", {
        class: `farm-style ${item.key === style ? "on" : ""}`,
        type: "button",
        role: "radio",
        "aria-checked": item.key === style ? "true" : "false",
        onclick: () => { style = item.key; drawStyles(); },
      }, [h("strong", { text: item.label }), h("small", { text: item.pitch }), h("em", { text: `“${item.example}”` })])
    ));
    drawStyles();
    let look = value("look", "bold");
    const looks = h("div", { class: "farm-looks", role: "radiogroup", "aria-label": "Caption look" });
    const drawLooks = () => looks.replaceChildren(...(state.data.looks || []).map((key) =>
      h("button", {
        class: `farm-look look-${key} ${key === look ? "on" : ""}`,
        type: "button",
        role: "radio",
        "aria-checked": key === look ? "true" : "false",
        onclick: () => { look = key; drawLooks(); },
      }, [h("span", { class: "farm-look-sample" }, ["WAIT FOR ", h("b", { text: "IT" })]), h("strong", { text: key }), h("small", { text: LOOK_NOTES[key] || "" })])
    ));
    drawLooks();
    let visuals = value("visuals", "photos");
    const pictures = h("div", { class: "farm-visuals", role: "radiogroup", "aria-label": "Pictures" });
    const drawVisuals = () => pictures.replaceChildren(...VISUALS.map(([key, label, note]) =>
      h("button", {
        class: `farm-style ${key === visuals ? "on" : ""}`,
        type: "button",
        role: "radio",
        "aria-checked": key === visuals ? "true" : "false",
        onclick: () => { visuals = key; drawVisuals(); },
      }, [h("strong", { text: label }), h("small", { text: key === "ai" && !(state.data.tools || {}).image_maker ? `${note} Not set yet.` : note })])
    ));
    drawVisuals();
    const voice = h("select", { "aria-label": "Voice" }, [
      ...(state.data.voices || []).map((item) => h("option", { value: item, text: voiceName(item), selected: value("voice", "am_michael") === item })),
      h("option", { value: "none", text: "No voice (captions only)", selected: value("voice", "") === "none" }),
    ]);
    const seconds = h("input", { type: "range", min: 10, max: 90, step: 5, value: value("seconds", 30), "aria-label": "Length in seconds" });
    const secondsLabel = h("strong", { text: `${seconds.value}s` });
    seconds.addEventListener("input", () => { secondsLabel.textContent = `${seconds.value}s`; });
    const perDay = h("input", { type: "number", min: 1, max: 10, value: value("posts_per_day", 1), "aria-label": "Videos a day" });
    const times = h("input", { type: "text", value: value("post_times", ["18:00"]).join(", "), placeholder: "09:00, 18:00", "aria-label": "Posting times" });
    const tags = h("input", { type: "text", value: value("hashtags", []).join(" "), placeholder: "#space #facts", "aria-label": "Hashtags" });
    const cta = h("input", { type: "text", value: value("call_to_action", ""), placeholder: "Follow for a new fact every day", "aria-label": "Call to action" });
    const notes = h("textarea", { rows: 3, placeholder: "Tone, words to avoid, facts to always include…", "aria-label": "Notes for the writer" });
    notes.value = value("notes", "");
    const autopilot = h("input", { type: "checkbox", checked: Boolean(value("autopilot", false)), "aria-label": "Autopilot" });
    const save = async () => {
      const body = {
        name: name.value,
        niche: niche.value,
        platform: platform.value,
        style,
        look,
        visuals,
        voice: voice.value,
        seconds: Number(seconds.value),
        posts_per_day: Number(perDay.value) || 1,
        post_times: times.value.split(/[ ,;]+/).filter(Boolean),
        hashtags: tags.value.split(/[ ,]+/).filter(Boolean),
        call_to_action: cta.value,
        notes: notes.value,
        autopilot: autopilot.checked,
      };
      const saved = await act(
        () => (chosen ? ctx.api(`/studio/api/farm/channels/${chosen.id}`, { method: "PUT", body: JSON.stringify(body) }) : ctx.post("/studio/api/farm/channels", body)),
        chosen ? "Channel saved." : "Channel made. Fill its idea board next."
      );
      if (saved && !chosen) {
        state.channelId = saved.id;
        keep(CHANNEL_KEY, saved.id);
        switchMode("line");
        drawChannels();
      }
    };
    stage.append(h("section", { class: "card farm-setup" }, clean([
      h("h2", { text: chosen ? `@${chosen.name} settings` : "New channel" }),
      h("div", { class: "farm-grid" }, [
        field("Channel name", name, "Shown on every video as @name."),
        field("Niche", niche, "What the account is about. Specific beats broad."),
        field("Platform", platform),
        field("Voice", voice, state.data.voice ? "The built-in voice reads every script." : "Turn on the built-in voice in Settings first."),
      ]),
      h("h3", { text: "Video style" }),
      styles,
      h("h3", { text: "Caption look" }),
      looks,
      h("h3", { text: "Pictures" }),
      pictures,
      h("h3", { text: "Length and posting" }),
      h("div", { class: "farm-grid" }, [
        h("label", { class: "farm-field" }, ["Length ", secondsLabel, seconds]),
        field("Videos a day", perDay),
        field("Posting times", times, "Each finished video gets the next free time."),
        field("Hashtags", tags),
        field("Call to action", cta, "Said at the end and added to the caption."),
        field("Notes for the writer", notes),
      ]),
      h("label", { class: "check farm-autopilot" }, [
        autopilot,
        h("span", {}, [h("strong", { text: "Autopilot " }), "keeps a day of videos ready, making one at a time while the app is open."]),
      ]),
      h("div", { class: "row" }, clean([
        h("button", { class: "primary", type: "button", text: chosen ? "Save channel" : "Make channel", onclick: save }),
        chosen
          ? h("button", {
              class: "ghost-button danger",
              type: "button",
              text: "Delete channel",
              onclick: async () => {
                if (!window.confirm(`Delete @${chosen.name} and all its videos?`)) return;
                await act(() => ctx.remove(`/studio/api/farm/channels/${chosen.id}`), "Channel deleted.");
                state.channelId = "";
                pickChannel();
                draw();
              },
            })
          : null,
      ])),
      h("details", { class: "farm-tips" }, [
        h("summary", { text: "What works on short-video apps" }),
        h("ul", {}, [
          h("li", { text: "The first two seconds decide everything: open with a bold claim, a number, or a question." }),
          h("li", { text: "One niche per account, posted at the same times every day." }),
          h("li", { text: "Add a trending sound in the app when you post; keep the voice on top." }),
          h("li", { text: "Make your own videos and tell the truth: copied clips and fake facts get accounts banned." }),
        ]),
      ]),
    ])));
  }

  function voiceName(id) {
    const names = { bm_george: "George (British man)", bm_lewis: "Lewis (British man)", bm_daniel: "Daniel (British man)", bm_fable: "Fable (British man)", am_michael: "Michael (American man)", am_adam: "Adam (American man)", bf_emma: "Emma (British woman)", af_heart: "Heart (American woman)" };
    return names[id] || id;
  }

  /* ------------------------------------------------------------ farm chat */

  function chatPanel() {
    chatLog = h("div", { class: "lab-chat-log", "aria-live": "polite" });
    const input = h("input", { type: "text", placeholder: "Hey Jarvis, make 3 reels about sharks…", "aria-label": "Ask in the Farm chat" });
    const form = h("form", {
      class: "row",
      onsubmit: async (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        input.value = "";
        await say(text);
      },
    }, [h("div", { class: "grow" }, [input]), h("button", { class: "primary", type: "submit", text: "Send" })]);
    return h("aside", { class: "card lab-chat farm-chat" }, [
      h("h2", {}, [h("span", { class: "lab-orb", "aria-hidden": "true" }), " Farm chat"]),
      h("p", { class: "muted small", text: "Ask the main AI for videos, ideas, new channels, or advice. Videos are made in the background and land on the line." }),
      chatLog,
      h("div", { class: "chips" }, SUGGESTIONS.map((text) => h("button", { class: "chip", type: "button", text, onclick: () => say(text) }))),
      form,
    ]);
  }

  async function say(text) {
    state.chatMessages.push({ role: "user", text, sequence: -1 });
    state.chatBusy = true;
    drawChat();
    try {
      await ctx.post("/studio/api/farm/chat", { text });
    } catch (error) {
      ctx.notify(error.message);
      state.chatBusy = false;
      drawChat();
      return;
    }
    pollChat();
  }

  function pollChat() {
    clearTimeout(chatTimer);
    chatTimer = setTimeout(async () => {
      if (!ctx.alive()) return;
      await refreshChat(false);
      if (state.chatBusy) pollChat();
    }, 1200);
  }

  async function refreshChat(first) {
    let console_;
    try {
      console_ = await ctx.api(`/studio/api/farm/chat?after=${first ? 0 : state.chatAfter}`);
    } catch {
      return;
    }
    if (!ctx.alive()) return;
    if (first) state.chatMessages = [];
    state.chatMessages = state.chatMessages.filter((message) => message.sequence !== -1 || !console_.messages.some((m) => m.role === "user" && m.text === message.text));
    let changed = false;
    for (const message of console_.messages) {
      state.chatAfter = Math.max(state.chatAfter, message.sequence);
      state.chatMessages.push(message);
      if (!first && (message.author === "farm" || (message.data && message.data.tool === "farm"))) changed = true;
      if (!first && message.role === "event" && message.author === "farm") ctx.notify(message.text);
    }
    state.chatBusy = console_.busy;
    state.agentName = console_.agent;
    drawChat();
    if (changed) await refresh();
    if (first && console_.busy) pollChat();
  }

  function drawChat() {
    if (!chatLog) return;
    const shown = state.chatMessages.slice(-40).map((message) => {
      if (message.role === "user") return h("div", { class: "bubble user", text: message.text });
      if (message.role === "tool") {
        const data = message.data || {};
        if (data.tool !== "farm") return h("div", { class: "tool-line", text: `⚙ ${data.tool || message.author || "tool"}` });
        const first = String(message.text || "").split("\n")[0].replace(/:$/, ".");
        return h("div", { class: `tool-line lab farm-tool ${data.failed ? "failed" : ""}`, text: `🎬 ${first.length > 120 ? `${first.slice(0, 117)}…` : first}` });
      }
      if (message.role === "assistant") {
        if (!message.text) return null;
        return h("div", { class: "bubble assistant" }, [h("span", { class: "who", text: message.author || state.agentName || "Jarvis" }), message.text]);
      }
      if (message.role === "event") return h("div", { class: `tool-line ${message.author === "farm" ? "lab" : "muted"}`, text: message.text });
      return null;
    });
    if (state.chatBusy) shown.push(h("div", { class: "bubble assistant thinking" }, [h("span", { class: "dots" }, [h("i"), h("i"), h("i")]), " working on the farm…"]));
    if (!shown.filter(Boolean).length) shown.push(h("p", { class: "muted small", text: "Say “Make 3 reels about black holes” and watch the line." }));
    chatLog.replaceChildren(...clean(shown));
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  window.FCCFarm = { render, state };
})();
