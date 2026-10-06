/* FCC Studio Content Farm — YouTube Shorts, animated cartoon stories,
   beat-for-beat music edits, and two-hour sleep videos, idea to finished
   MP4. Channels (one per account and show), a production line from idea to
   posted, a posting queue with captions ready to paste, every video, a
   media library of your own clips, pictures, and songs, your cartoon
   characters, a scene editor (yours and the AI's), each channel's settings,
   and the Farm chat with the main AI, all on one page. Studio calls
   FCCFarm.render(ctx). */
(() => {
  "use strict";

  const MODES = [
    ["line", "Production line", "🏭"],
    ["queue", "Posting queue", "📅"],
    ["videos", "Videos", "🎬"],
    ["library", "Media library", "🎞"],
    ["cast", "Characters", "🎭"],
    ["setup", "Channel settings", "⚙"],
  ];
  const MODE_KEY = "fcc.farm.mode";
  const CHANNEL_KEY = "fcc.farm.channel";
  const SUGGESTIONS = [
    "Make 3 shorts about Breaking Bad lore",
    "Make a 2 hour sleep video about the entire lore of Breaking Bad",
    "Make a cartoon about the king who couldn't walk",
    "Make a music edit",
    "Give me 5 what-if video ideas",
    "Start a channel about scary stories over gameplay",
    "What's ready to post?",
  ];
  const COLUMNS = [
    ["idea", "Ideas", "💡"],
    ["making", "Making", "⚙"],
    ["ready", "Ready to post", "✅"],
    ["posted", "Posted", "📤"],
  ];
  const VISUALS = [
    ["auto", "Best fit", "Your library first, then the show's fandom wiki stills, stock, then AI pictures if allowed."],
    ["library", "Only my library", "Just the clips and pictures you gave the farm."],
    ["photos", "Stock photos", "Free photos from Openverse (and Pexels clips with a key)."],
    ["ai", "AI pictures first", "Made on this PC by your Stable Diffusion (set its address in Settings)."],
    ["text", "Art cards", "Glowing gradient cards. Always works, even offline."],
    ["none", "Background only", "Just the background video (gameplay) under the captions."],
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
    editing: "",
    editor: null,
    editChapter: 0,
    library: null,
    libraryShow: "",
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
  const channelKind = (id) => {
    const found = channels().find((item) => item.id === id);
    const style = found && (state.data.styles || []).find((item) => item.key === found.style);
    return (style && style.kind) || "narrated";
  };
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
    state.editing = "";
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
    if (state.editing) {
      drawEditor();
      return;
    }
    const pages = { line: drawLine, queue: drawQueue, videos: drawVideos, library: drawLibrary, cast: drawCast, setup: drawSetup };
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
    if ((state.mode === "setup" || state.editing || state.mode === "library") && stage && stage.contains(document.activeElement)) {
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
        // Never redraw over the editor or a form being typed in.
        if (state.editing || (stage && stage.contains(document.activeElement))) {
          drawHeader();
          drawChannels();
        } else {
          draw();
        }
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
          h("p", { class: "muted", text: "YouTube Shorts, animated cartoon stories with your own characters, music edits cut on the beat, and two-hour lore videos to fall asleep to, made on this PC. Edit any of it yourself." }),
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
          h("p", { class: "muted", text: `${chosen.fandom || chosen.niche || "No niche yet"} · ${chosen.style_label} · ${chosen.kind === "long" ? `${Math.round(chosen.minutes / 6) / 10} hours` : `${chosen.seconds}s`} · ${chosen.platform_label} · posts at ${chosen.post_times.join(", ")}` }),
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
        h("button", { class: "ghost-button small", type: "button", text: "Stop", onclick: () => act(() => ctx.post(`/studio/api/farm/posts/${post.id}/stop`), "Stopping; what's written and voiced is kept.") }),
      ]);
    }
    if (post.status === "ready" || post.status === "posted") {
      return h("article", { class: `farm-card is-${post.status}`, "data-id": post.id }, [
        h("button", { class: `farm-thumb ${post.kind === "long" ? "wide" : ""}`, type: "button", "aria-label": `Watch ${post.title}`, onclick: () => openPost(post) }, [
          h("img", { src: post.cover_url, alt: "", loading: "lazy" }),
          h("span", { class: "farm-play", text: "▶", "aria-hidden": "true" }),
        ]),
        h("div", { class: "farm-card-text" }, [
          h("strong", { text: post.title }),
          h("small", { class: "muted", text: post.status === "posted" ? `Posted ${new Date(post.posted_at).toLocaleString()}` : `Post ${slot(post.scheduled_at)}` }),
          post.data.edited ? h("small", { class: "farm-edited", text: "Edited: render to apply" }) : null,
          h("button", { class: "link-button small", type: "button", text: "✎ Edit", onclick: () => openEditor(post.id) }),
        ]),
      ]);
    }
    const failed = post.status === "failed";
    return h("article", { class: `farm-card is-idea ${failed ? "is-failed" : ""}`, "data-id": post.id }, [
      h("strong", { text: post.title }),
      failed ? h("small", { class: "farm-error", text: post.error }) : h("small", { class: "muted", text: `by ${post.made_by}` }),
      h("div", { class: "row farm-card-buttons" }, clean([
        h("button", { class: "primary small", type: "button", text: failed ? (post.scene_count ? "Carry on" : "Try again") : "Make", onclick: () => act(() => ctx.post(`/studio/api/farm/posts/${post.id}/make`), "Making it now.") }),
        post.scene_count ? h("button", { class: "ghost-button small", type: "button", "aria-label": `Edit ${post.title}`, text: "✎ Edit", onclick: () => openEditor(post.id) }) : null,
        !post.scene_count && channelKind(post.channel_id) === "edit" ? h("button", { class: "ghost-button small", type: "button", "aria-label": `Song and lyrics for ${post.title}`, text: "🎵 Song", onclick: () => openEditor(post.id) }) : null,
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Rename ${post.title}`, text: "✎", onclick: () => renameIdea(post) }),
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Delete ${post.title}`, text: "🗑", onclick: () => act(() => ctx.remove(`/studio/api/farm/posts/${post.id}`)) }),
      ])),
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
      h("p", { text: "A channel is one account: a show or niche, a video style, a voice, and when it posts. Shorts are vertical and quick; long videos are calm two-hour lore or what-if narrations to fall asleep to. The farm writes each script with your local AI and the show's fandom wiki, reads it aloud, picks your clips or real stills for every scene, and renders the video. Then edit anything you don't like." }),
      h("ol", { class: "farm-steps" }, [
        h("li", { text: "Add your clips and pictures in the Media library (or link a folder of them), and any gameplay to play under shorts." }),
        h("li", { text: "Make a channel: pick a show people binge (Breaking Bad, Star Wars, Halo) and a style." }),
        h("li", { text: "Press ✨ 5 ideas, or ask in the Farm chat." }),
        h("li", { text: "Press Make. A short takes a minute or two; a two-hour video a few hours." }),
        h("li", { text: "Edit it if the AI got something wrong, then post from the queue." }),
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
    const chapters = (post.data && post.data.chapters) || [];
    const box = modal(post.data.yt_title || post.title, [
      h("div", { class: `farm-detail ${post.kind === "long" ? "wide" : ""}` }, [
        h("div", { class: `farm-phone big ${post.kind === "long" ? "wide" : ""}` }, [
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
          chapters.length ? h("details", {}, [h("summary", { text: `${chapters.length} chapters` }), h("ol", { class: "farm-script" }, chapters.map((c) => h("li", { text: `${Math.floor(c.start / 60)}:${String(Math.floor(c.start % 60)).padStart(2, "0")} ${c.title}` })))]) : null,
          post.thumb_url ? h("a", { class: "ghost-button small", href: post.thumb_url, download: "thumbnail.jpg", text: "⬇ Thumbnail" }) : null,
          h("div", { class: "row" }, [
            post.status === "posted"
              ? h("button", { class: "ghost-button small", type: "button", text: "Back to the queue", onclick: async () => { box.remove(); await act(() => ctx.post(`/studio/api/farm/posts/${post.id}/posted`, { posted: false })); } })
              : h("button", { class: "primary small", type: "button", text: "✓ Mark posted", onclick: async () => { box.remove(); await act(() => ctx.post(`/studio/api/farm/posts/${post.id}/posted`, { posted: true }), "Marked as posted."); } }),
            h("button", { class: "primary small", type: "button", text: "✎ Edit video", onclick: () => { box.remove(); openEditor(post.id); } }),
            h("button", { class: "ghost-button small", type: "button", text: "↻ New script", onclick: async () => { if (!window.confirm("Write a new script and make it again? Your edits to this one are lost.")) return; box.remove(); await act(() => ctx.post(`/studio/api/farm/posts/${post.id}/make?rewrite=true`), "Making it again from a new script."); } }),
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
    const toggle = (label, input, hint) => h("label", { class: "check farm-toggle" }, [input, h("span", {}, [h("strong", { text: `${label} ` }), hint])]);
    const name = h("input", { type: "text", value: value("name", ""), placeholder: "e.g. lorebeforebed", "aria-label": "Channel name" });
    const niche = h("input", { type: "text", value: value("niche", ""), placeholder: "e.g. TV lore, scary stories, space facts", "aria-label": "Niche" });
    const fandom = h("input", { type: "text", value: value("fandom", ""), placeholder: "e.g. Breaking Bad, Star Wars, Halo", "aria-label": "Show, movie, or game" });
    const wiki = h("input", { type: "text", value: value("wiki", ""), placeholder: "Optional: https://breakingbad.fandom.com", "aria-label": "Fandom wiki" });
    const platform = h("select", { "aria-label": "Platform" }, Object.entries(state.data.platforms || {}).map(([key, label]) =>
      h("option", { value: key, text: label, selected: value("platform", "youtube") === key })
    ));
    let style = value("style", "lore");
    const isLong = () => Boolean((state.data.styles || []).find((item) => item.key === style && item.long));
    const kindOf = () => ((state.data.styles || []).find((item) => item.key === style) || {}).kind || "narrated";
    const longOnly = [];
    const shortOnly = [];
    const narratedOnly = [];
    const cartoonOnly = [];
    const editOnly = [];
    const animatedOnly = [];
    const styleButton = (item) => h("button", {
      class: `farm-style ${item.key === style ? "on" : ""}`,
      type: "button",
      role: "radio",
      "aria-checked": item.key === style ? "true" : "false",
      onclick: () => { style = item.key; drawStyles(); },
    }, clean([h("strong", { text: item.label }), h("small", { text: item.pitch }), h("em", { text: `“${item.example}”` }), item.fandom ? h("span", { class: "farm-badge", text: "fandom" }) : null]));
    const styles = h("div", { class: "farm-style-groups", role: "radiogroup", "aria-label": "Video style" });
    const drawStyles = () => {
      const all = state.data.styles || [];
      styles.replaceChildren(
        h("h4", { text: "Animated cartoons and music edits" }),
        h("div", { class: "farm-styles" }, all.filter((item) => item.kind && item.kind !== "narrated").map(styleButton)),
        h("h4", { text: "Shorts (9:16, under 3 minutes)" }),
        h("div", { class: "farm-styles" }, all.filter((item) => !item.long && (!item.kind || item.kind === "narrated")).map(styleButton)),
        h("h4", { text: "Long videos to fall asleep to (16:9, hours)" }),
        h("div", { class: "farm-styles" }, all.filter((item) => item.long).map(styleButton))
      );
      const kind = kindOf();
      for (const node of longOnly) node.hidden = !isLong();
      for (const node of shortOnly) node.hidden = isLong();
      for (const node of narratedOnly) node.hidden = kind !== "narrated";
      for (const node of cartoonOnly) node.hidden = kind !== "cartoon";
      for (const node of editOnly) node.hidden = kind !== "edit";
      for (const node of animatedOnly) node.hidden = kind === "narrated";
    };
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
    let visuals = value("visuals", "auto");
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
    const aiMedia = h("input", { type: "checkbox", checked: Boolean(value("ai_media", true)), "aria-label": "Allow AI-made pictures" });
    const aiPolish = h("input", { type: "checkbox", checked: Boolean(value("ai_polish", true)), "aria-label": "AI polishes each script" });
    const captions = h("input", { type: "checkbox", checked: Boolean(value("captions", true)), "aria-label": "Captions" });
    const backgrounds = ((state.data.library || {}).backgrounds) || [];
    const background = h("select", { "aria-label": "Background video" }, [
      h("option", { value: "", text: "None: pictures and clips fill the screen" }),
      ...backgrounds.map((item) => h("option", { value: item.id, text: item.name, selected: value("background", "") === item.id })),
    ]);
    const voice = h("select", { "aria-label": "Voice" }, [
      ...(state.data.voices || []).map((item) => h("option", { value: item, text: voiceName(item), selected: value("voice", "am_michael") === item })),
      h("option", { value: "none", text: "No voice (captions only)", selected: value("voice", "") === "none" }),
    ]);
    const seconds = h("input", { type: "range", min: 10, max: 180, step: 5, value: value("seconds", 45), "aria-label": "Length in seconds" });
    const secondsLabel = h("strong", { text: `${seconds.value}s` });
    seconds.addEventListener("input", () => { secondsLabel.textContent = `${seconds.value}s`; });
    const minutes = h("input", { type: "range", min: 10, max: 180, step: 10, value: value("minutes", 120), "aria-label": "Length in minutes" });
    const minutesLabel = h("strong", { text: `${minutes.value} min` });
    minutes.addEventListener("input", () => { minutesLabel.textContent = `${minutes.value} min`; });
    const perDay = h("input", { type: "number", min: 1, max: 10, value: value("posts_per_day", 1), "aria-label": "Videos a day" });
    const times = h("input", { type: "text", value: value("post_times", ["18:00"]).join(", "), placeholder: "09:00, 18:00", "aria-label": "Posting times" });
    const tags = h("input", { type: "text", value: value("hashtags", []).join(" "), placeholder: "#breakingbad #lore", "aria-label": "Hashtags" });
    const cta = h("input", { type: "text", value: value("call_to_action", ""), placeholder: "Subscribe for a new theory every day", "aria-label": "Call to action" });
    const notes = h("textarea", { rows: 3, placeholder: "Tone, words to avoid, facts to always include…", "aria-label": "Notes for the writer" });
    notes.value = value("notes", "");
    const autopilot = h("input", { type: "checkbox", checked: Boolean(value("autopilot", false)), "aria-label": "Autopilot" });
    const shortLength = h("label", { class: "farm-field" }, ["Length ", secondsLabel, seconds]);
    const longLength = h("label", { class: "farm-field" }, ["Length ", minutesLabel, minutes, h("small", { class: "muted", text: "Two hours takes a few hours to make on this PC; leave it overnight." })]);
    const backgroundField = field("Background video", background, backgrounds.length ? "Plays under every short, muted (gameplay, satisfying clips). Pick “Background only” pictures for the pure gameplay look." : "Upload gameplay in the Media library and tick “Background” to use it here.");
    const platformField = field("Platform", platform);
    // Cartoons and music edits.
    const library = state.data.library || {};
    const songs = library.songs || [];
    const songPick = (selected, none) => h("select", { "aria-label": "Song" }, [
      h("option", { value: "", text: none }),
      ...songs.map((item) => h("option", { value: item.id, text: `${item.name}${item.duration ? ` (${Math.round(item.duration)}s)` : ""}`, selected: selected === item.id })),
    ]);
    const song = songPick(value("song", ""), "None");
    const series = h("input", { type: "text", value: value("series", ""), placeholder: "e.g. Most Epic Comebacks in History", "aria-label": "Series title" });
    const texture = h("select", { "aria-label": "Board" }, (state.data.textures || ["wood"]).map((key) =>
      h("option", { value: key, text: { wood: "Wooden planks", paper: "Paper", dark: "Dark", brick: "Brick wall", none: "Black" }[key] || key, selected: value("texture", "wood") === key })
    ));
    const shape = h("select", { "aria-label": "Shape" }, [
      h("option", { value: "tall", text: "Tall 9:16 (Shorts, TikTok, Reels)", selected: value("shape", "tall") === "tall" }),
      h("option", { value: "wide", text: "Wide 16:9 (YouTube)", selected: value("shape", "tall") === "wide" }),
    ]);
    const theme = h("input", { type: "color", value: value("theme", "#ff5fc8"), "aria-label": "Big words colour" });
    const pace = h("select", { "aria-label": "Cuts" }, (state.data.paces || ["auto"]).map((key) =>
      h("option", { value: key, text: { auto: "Follow the music (more cuts when it's loud)", fast: "Fast: every beat or two", medium: "Medium", slow: "Slow: every bar" }[key] || key, selected: value("pace", "auto") === key })
    ));
    const characters = state.data.characters || [];
    const castSet = new Set(value("cast", []));
    const castBoxes = characters.map((item) => h("label", { class: "check farm-cast-pick" }, [
      h("input", { type: "checkbox", value: item.id, checked: castSet.has(item.id), "aria-label": item.name }),
      h("img", { src: `/studio/api/farm/characters/${item.id}/picture?v=${item.updated_at}`, alt: "", loading: "lazy" }),
      h("span", { text: item.name }),
    ]));
    const castField = h("div", { class: "farm-field" }, [
      h("strong", { text: "Characters in the stories" }),
      castBoxes.length
        ? h("div", { class: "farm-cast-picks" }, castBoxes)
        : h("p", { class: "muted small", text: "No characters yet: the writer makes some up. Add your own on the Characters tab." }),
    ]);
    const seriesField = field("Series title", series, "In the white box above every cartoon.");
    const textureField = field("Board under the cartoon", texture, "What the tall video shows around the cartoon.");
    const bedField = field("Quiet music under the story", songPick(value("song", ""), "None (or the music file in Settings)"), "A song from your library, very quiet.");
    const songField = field("Song", song, songs.length ? "Each edit cuts on this song's beat. A video's own song can be picked in its editor." : "Upload the song (MP3, WAV, M4A, or a video with it) in the Media library first.");
    const themeField = field("Big words colour", theme, "The huge letters spelled across the screen.");
    const paceField = field("Cuts", pace);
    const shapeField = field("Shape", shape);
    shortOnly.push(shortLength, platformField);
    const picturesHeading = h("h3", { text: "Pictures and clips" });
    narratedOnly.push(backgroundField, picturesHeading, pictures);
    longOnly.push(longLength);
    cartoonOnly.push(castField, seriesField, textureField, bedField);
    editOnly.push(songField, themeField, paceField);
    animatedOnly.push(shapeField);
    drawStyles();
    const save = async () => {
      const body = {
        name: name.value,
        niche: niche.value,
        fandom: fandom.value,
        wiki: wiki.value,
        platform: platform.value,
        style,
        look,
        visuals,
        voice: voice.value,
        seconds: Number(seconds.value),
        minutes: Number(minutes.value),
        posts_per_day: Number(perDay.value) || 1,
        post_times: times.value.split(/[ ,;]+/).filter(Boolean),
        hashtags: tags.value.split(/[ ,]+/).filter(Boolean),
        call_to_action: cta.value,
        notes: notes.value,
        autopilot: autopilot.checked,
        ai_media: aiMedia.checked,
        ai_polish: aiPolish.checked,
        captions: captions.checked,
        background: background.value,
        series: series.value,
        texture: texture.value,
        shape: shape.value,
        theme: theme.value,
        pace: pace.value,
        cast: castBoxes.map((label) => label.querySelector("input")).filter((box) => box.checked).map((box) => box.value),
      };
      const kind = kindOf();
      if (kind === "edit") body.song = song.value;
      else if (kind === "cartoon") body.song = bedField.querySelector("select").value;
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
        field("Show, movie, or game", fandom, "The farm reads its Fandom wiki for lore and real stills."),
        field("Fandom wiki", wiki, "Only if the farm can't find it by the show's name."),
        platformField,
        field("Voice", voice, state.data.voice ? "The built-in voice reads every script." : "Turn on the built-in voice in Settings first."),
      ]),
      h("h3", { text: "Video style" }),
      styles,
      h("div", { class: "farm-grid farm-animated" }, [castField, seriesField, textureField, bedField, songField, themeField, paceField, shapeField]),
      picturesHeading,
      pictures,
      h("div", { class: "farm-toggles" }, [
        toggle("Allow AI-made pictures", aiMedia, "Off: only your clips, real stills from the show, and stock photos. Nothing made up."),
        toggle("AI polishes each short", aiPolish, "The AI edits every short's script once more: a stronger hook, less filler."),
        toggle("Captions", captions, "Word-by-word captions. Sleep videos usually go without."),
      ]),
      h("div", { class: "farm-grid" }, [backgroundField]),
      h("h3", { text: "Caption look" }),
      looks,
      h("h3", { text: "Length and posting" }),
      h("div", { class: "farm-grid" }, [
        shortLength,
        longLength,
        field("Videos a day", perDay),
        field("Posting times", times, "Each finished video gets the next free time."),
        field("Hashtags", tags),
        field("Call to action", cta, "Said at the end and added to the description."),
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
        h("summary", { text: "What works on YouTube" }),
        h("ul", {}, [
          h("li", { text: "Shorts: the first two seconds decide everything. Open with a bold claim, a number, or a question." }),
          h("li", { text: "Go deep into one fandom per channel; fans binge, comment, and come back for the next theory." }),
          h("li", { text: "Sleep videos: calm voice, slow pictures, no loud music, a clear thumbnail title, and chapters (the farm writes them)." }),
          h("li", { text: "Show clips and stills are other people's work: use short pieces with your own commentary, and credit the wiki." }),
        ]),
      ]),
    ])));
  }

  /* ------------------------------------------------------------ editor */

  async function openEditor(postId) {
    state.editing = postId;
    state.editChapter = 0;
    try {
      state.editor = await ctx.api(`/studio/api/farm/posts/${postId}/editor`);
      const kind = channelKind(state.editor.channel_id);
      if (kind !== "narrated") state.editor.kind = kind;
    } catch (error) {
      ctx.notify(error.message);
      state.editing = "";
      return;
    }
    drawStage();
  }

  function sceneMediaLabel(media) {
    if (!media) return "The AI picks";
    if (media.type === "none") return "Background video";
    if (media.type === "card") return "Art card";
    const source = { library: "Your library", wiki: "Fandom wiki", openverse: "Stock photo", pexels: "Stock clip", ai: "AI picture", web: "Web" }[media.source] || media.source || "";
    return `${media.type === "clip" ? "🎞 Clip" : "🖼 Picture"} · ${source}${media.reused ? " (again)" : ""}`;
  }

  function drawEditor() {
    const post = state.editor;
    stage.replaceChildren();
    if (!post) return;
    const scenes = post.scenes || [];
    const long = post.kind === "long";
    const chapters = post.chapters || [];
    const visible = scenes
      .map((scene, index) => ({ scene, index }))
      .filter(({ scene }) => !long || Number(scene.chapter || 0) === state.editChapter);
    const instruction = h("textarea", { rows: 2, placeholder: long ? "e.g. make this chapter calmer and add more about Gray Matter" : "e.g. make the hook scarier, cut scene 3, end on a cliffhanger", "aria-label": "Tell the AI what to change" });
    const chapterPick = long
      ? h("select", { "aria-label": "Chapter", onchange: (event) => { state.editChapter = Number(event.target.value); drawEditor(); } },
          chapters.map((title, number) => h("option", { value: number, text: `Chapter ${number + 1}: ${title}`, selected: number === state.editChapter })))
      : null;
    const kind = post.kind;
    const rows = visible.map(({ scene, index }) => (kind === "edit" ? cutRow(scene, index) : sceneRow(scene, index, visible.length)));
    const music = kind === "edit" ? musicPanel(post) : null;
    const summary = kind === "edit"
      ? `${scenes.length} cuts on the beat${post.data.tempo ? ` (${post.data.tempo} BPM)` : ""} · lyrics ${post.data.lyrics_from || "not read yet"} · pick any cut's clip, change the song, the part of it, or the lyrics, then render.`
      : kind === "cartoon"
        ? `${scenes.length} shots · change any line, where it happens, who is in it and what they do, or the camera, then render. Voice clips are kept for lines you didn't change.`
        : `${scenes.length} scenes${long ? ` in ${chapters.length} chapters` : ""} · change any line, the words on screen, or a scene's picture or clip, then render. Voice clips are kept for lines you didn't change.`;
    stage.append(h("section", { class: "card farm-editor" }, clean([
      h("div", { class: "farm-editor-head" }, [
        h("button", { class: "ghost-button small", type: "button", text: "‹ Back", onclick: () => { state.editing = ""; state.editor = null; drawStage(); } }),
        h("div", { class: "grow" }, [
          h("h2", { text: `Edit: ${post.data.yt_title || post.title}` }),
          h("p", { class: "muted small", text: summary }),
        ]),
        post.data.edited ? h("span", { class: "pill warn", text: "Edited" }) : null,
      ]),
      music,
      kind === "edit" ? null : h("div", { class: "farm-ai-edit" }, clean([
        h("strong", { text: "🤖 Ask the AI to edit" }),
        chapterPick,
        instruction,
        h("button", {
          class: "ghost-button",
          type: "button",
          text: "Edit with AI",
          onclick: async (event) => {
            const text = instruction.value.trim();
            if (!text) return;
            const button = event.currentTarget;
            button.disabled = true;
            button.textContent = "Editing…";
            try {
              state.editor = await ctx.post(`/studio/api/farm/posts/${post.id}/ai-edit`, { instruction: text, chapter: long ? state.editChapter : null });
              ctx.notify("The AI edited it. Check it, then render.");
            } catch (error) {
              ctx.notify(error.message);
            }
            drawEditor();
          },
        }),
      ])),
      chapterPick && !rows.length ? h("p", { class: "muted", text: "No scenes in this chapter." }) : null,
      h("ol", { class: "farm-scenes" }, rows),
      h("div", { class: "row farm-editor-actions" }, [
        h("button", { class: "ghost-button", type: "button", text: "💾 Save edits", onclick: () => saveScenes(false) }),
        h("button", { class: "primary", type: "button", text: "▶ Save and render", onclick: () => saveScenes(true) }),
      ]),
    ])));
  }

  function musicPanel(post) {
    const data = post.data || {};
    const songs = ((state.data.library || {}).songs) || [];
    const fallback = (channels().find((item) => item.id === post.channel_id) || {}).song || "";
    const song = h("select", { "aria-label": "Song", "data-music": "song" }, [
      h("option", { value: "", text: fallback ? "The channel's song" : "No song yet" }),
      ...songs.map((item) => h("option", { value: item.id, text: item.name, selected: (data.song || "") === item.id })),
    ]);
    const span = data.song_window || [];
    const start = h("input", { type: "number", min: 0, step: 0.5, value: data.song_start >= 0 ? data.song_start : "", placeholder: span.length ? `auto (${span[0]}s)` : "auto", "aria-label": "Start in the song (seconds)", "data-music": "song_start" });
    const length = h("input", { type: "number", min: 8, max: 90, step: 1, value: data.song_length || "", placeholder: "channel length", "aria-label": "Length (seconds)", "data-music": "song_length" });
    const big = h("input", { type: "text", value: (data.big_words || []).join(", "), placeholder: [...new Set(data.big_words_used || [])].join(", ") || "e.g. STEVEN, MONEY, HERO", "aria-label": "Big words", "data-music": "big_words" });
    const lyrics = h("textarea", { rows: 6, placeholder: "Paste the lyrics, one line per sung line. Timed lyrics ([00:12.34] words) line up best; plain lyrics are timed by Whisper when the built-in ears are on.", "aria-label": "Lyrics", "data-music": "lyrics" });
    lyrics.value = data.lyrics || "";
    return h("div", { class: "farm-music" }, [
      h("strong", { text: "🎵 Song and lyrics" }),
      h("div", { class: "farm-grid" }, [
        h("label", { class: "farm-field" }, ["Song", song]),
        h("label", { class: "farm-field" }, ["Big words (spelled out huge)", big]),
        h("label", { class: "farm-field" }, ["Start in the song (seconds)", start]),
        h("label", { class: "farm-field" }, ["Length (seconds)", length]),
      ]),
      h("label", { class: "farm-field" }, ["Lyrics", lyrics]),
    ]);
  }

  function musicFields() {
    const body = {};
    for (const input of stage.querySelectorAll("[data-music]")) {
      const key = input.dataset.music;
      if (key === "song_start") body[key] = input.value === "" ? "auto" : Number(input.value);
      else if (key === "song_length") body[key] = input.value === "" ? 0 : Number(input.value);
      else if (key === "big_words") body[key] = input.value.split(",").map((word) => word.trim()).filter(Boolean);
      else body[key] = input.value;
    }
    return body;
  }

  function cutRow(scene, index) {
    const media = scene.media;
    const cut = scene.cut || {};
    const effects = [cut.punch ? "punch" : "", cut.flash ? "flash" : "", cut.shake ? "shake" : ""].filter(Boolean).join(" + ");
    const preview = media && media.preview
      ? h("img", { src: media.preview, alt: "", loading: "lazy" })
      : h("span", { class: "farm-scene-blank", text: "🎞" });
    return h("li", { class: "farm-scene farm-cut", "data-index": index }, [
      h("button", { class: "farm-scene-media", type: "button", "aria-label": `Change the clip for cut ${index + 1}`, onclick: () => chooseMedia(index, { show: scene.say === "♪" ? "" : scene.say }) }, [
        preview,
        h("small", { text: sceneMediaLabel(media) }),
      ]),
      h("div", { class: "farm-scene-text" }, [
        h("strong", { text: `${Number(cut.start || 0).toFixed(2)}s – ${Number(cut.end || 0).toFixed(2)}s` }),
        h("p", { class: "muted small", text: `${scene.say || "♪"}${effects ? ` · ${effects}` : ""}` }),
      ]),
    ]);
  }

  const SPOT_WORDS = ["far left", "center left", "centre left", "center right", "centre right", "far right", "left", "right", "middle", "center", "centre"];

  function castText(cast) {
    return (cast || []).map((actor) => [actor.name, actor.action && actor.action !== "stand" ? actor.action : "", actor.at || ""].filter(Boolean).join(" ")).join(", ");
  }

  // "Sundiata crawl left, Sogolon cry right" back into the shot's cast.
  function parseCast(text) {
    const actions = (state.data.character_options || {}).actions || [];
    return text.split(",").map((part) => part.trim()).filter(Boolean).slice(0, 4).map((part) => {
      let rest = part.toLowerCase();
      let at = "";
      for (const word of SPOT_WORDS) {
        if (rest.endsWith(` ${word}`)) {
          at = word;
          rest = rest.slice(0, -word.length - 1);
          break;
        }
      }
      const words = part.split(/\s+/).slice(0, rest.split(/\s+/).length);
      let action = "stand";
      if (words.length > 1 && actions.includes(words[words.length - 1].toLowerCase())) action = words.pop().toLowerCase();
      return { name: words.join(" "), action, at, feel: "" };
    });
  }

  function shotFields(scene, index) {
    const options = state.data.character_options || {};
    const place = h("select", { "aria-label": `Shot ${index + 1} place`, "data-field": "place" }, (options.places || ["hut"]).map((key) => h("option", { value: key, text: key, selected: (scene.place || "hut") === key })));
    const camera = h("select", { "aria-label": `Shot ${index + 1} camera`, "data-field": "camera" }, (options.cameras || ["wide"]).map((key) => h("option", { value: key, text: { wide: "Wide", medium: "Medium", close: "Close-up", push: "Push in", pan: "Pan" }[key] || key, selected: (scene.camera || "wide") === key })));
    const speaker = h("input", { type: "text", value: scene.speaker || "", placeholder: "Narrator", "aria-label": `Shot ${index + 1} speaker`, "data-field": "speaker" });
    const who = h("input", { type: "text", value: castText(scene.cast), placeholder: "Sundiata crawl left, Sogolon cry right", "aria-label": `Shot ${index + 1} characters`, "data-cast": "1" });
    return h("div", { class: "farm-shot-fields" }, [
      h("label", { class: "farm-field" }, ["Where", place]),
      h("label", { class: "farm-field" }, ["Camera", camera]),
      h("label", { class: "farm-field" }, ["Who says it", speaker]),
      h("label", { class: "farm-field farm-shot-cast" }, ["Who's in it (name, action, where)", who]),
    ]);
  }

  function sceneRow(scene, index, count) {
    const say = h("textarea", { rows: 2, "aria-label": `Scene ${index + 1} words`, "data-field": "say" });
    say.value = scene.say || "";
    const onScreen = h("input", { type: "text", value: scene.text || "", placeholder: "Big words on screen (optional)", "aria-label": `Scene ${index + 1} words on screen`, "data-field": "text" });
    const show = h("input", { type: "text", value: scene.show || "", placeholder: "What the picture shows", "aria-label": `Scene ${index + 1} picture`, "data-field": "show" });
    const media = scene.media;
    const preview = media && media.preview
      ? h("img", { src: media.preview, alt: "", loading: "lazy" })
      : h("span", { class: "farm-scene-blank", text: media && media.type === "clip" ? "🎞" : media && media.type === "none" ? "🎮" : "🖼" });
    const cartoon = state.editor.kind === "cartoon";
    return h("li", { class: `farm-scene ${cartoon ? "farm-shot" : ""}`, "data-index": index }, [
      cartoon
        ? h("span", { class: "farm-scene-media farm-shot-number", text: `🎬 ${index + 1}` })
        : h("button", { class: "farm-scene-media", type: "button", "aria-label": `Change the picture for scene ${index + 1}`, onclick: () => chooseMedia(index, scene) }, [
            preview,
            h("small", { text: sceneMediaLabel(media) }),
          ]),
      h("div", { class: "farm-scene-text" }, cartoon ? [say, shotFields(scene, index)] : [say, h("div", { class: "row" }, [onScreen, show])]),
      h("div", { class: "farm-scene-buttons" }, [
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Move scene ${index + 1} up`, text: "↑", disabled: index === 0, onclick: () => moveScene(index, -1) }),
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Move scene ${index + 1} down`, text: "↓", disabled: index === count - 1 && !(state.editor.kind === "long"), onclick: () => moveScene(index, 1) }),
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Add a scene after ${index + 1}`, text: "+", onclick: () => addScene(index) }),
        h("button", { class: "ghost-button small", type: "button", "aria-label": `Delete scene ${index + 1}`, text: "🗑", onclick: () => deleteScene(index) }),
      ]),
    ]);
  }

  // What the user typed goes back into the scenes before any change.
  function collectScenes() {
    const scenes = (state.editor.scenes || []).map((scene) => ({ ...scene }));
    for (const row of stage.querySelectorAll(".farm-scene")) {
      const index = Number(row.dataset.index);
      for (const input of row.querySelectorAll("[data-field]")) scenes[index][input.dataset.field] = input.value;
      const who = row.querySelector("[data-cast]");
      if (who) scenes[index].cast = parseCast(who.value);
    }
    return scenes;
  }

  function moveScene(index, step) {
    const scenes = collectScenes();
    const target = index + step;
    if (target < 0 || target >= scenes.length) return;
    [scenes[index], scenes[target]] = [scenes[target], scenes[index]];
    if (state.editor.kind === "long") scenes[target].chapter = scenes[index].chapter;
    state.editor.scenes = scenes;
    drawEditor();
  }

  function addScene(index) {
    const scenes = collectScenes();
    scenes.splice(index + 1, 0, { say: "", show: "", text: "", media: null, chapter: scenes[index].chapter });
    state.editor.scenes = scenes;
    drawEditor();
  }

  function deleteScene(index) {
    const scenes = collectScenes();
    if (scenes.length <= 1) return;
    scenes.splice(index, 1);
    state.editor.scenes = scenes;
    drawEditor();
  }

  async function saveScenes(renderToo) {
    const scenes = collectScenes().filter((scene) => String(scene.say || "").trim());
    try {
      if (state.editor.kind === "edit") {
        state.editor = await ctx.api(`/studio/api/farm/posts/${state.editing}/music`, { method: "PUT", body: JSON.stringify(musicFields()) });
      } else {
        state.editor = await ctx.api(`/studio/api/farm/posts/${state.editing}/scenes`, { method: "PUT", body: JSON.stringify({ scenes }) });
      }
    } catch (error) {
      ctx.notify(error.message);
      return;
    }
    if (renderToo) {
      const id = state.editing;
      state.editing = "";
      state.editor = null;
      await act(() => ctx.post(`/studio/api/farm/posts/${id}/make`), "Rendering your edit now.");
      switchMode("line");
    } else {
      ctx.notify("Edits saved. Render when you're ready.");
      drawEditor();
    }
  }

  function chooseMedia(index, scene) {
    const results = h("div", { class: "farm-candidates" }, [h("p", { class: "muted", text: "Looking…" })]);
    const search = h("input", { type: "search", value: scene.show || "", placeholder: "Who or what should it show?", "aria-label": "Search for a picture or clip" });
    const upload = h("input", { type: "file", accept: "image/*,video/*", class: "visually-hidden", "aria-label": "Upload a picture or clip for this scene" });
    const editing = state.editor && state.editor.kind === "edit";
    let box = null;
    const use = async (choice) => {
      const scenes = collectScenes();
      try {
        if (editing) await ctx.api(`/studio/api/farm/posts/${state.editing}/music`, { method: "PUT", body: JSON.stringify(musicFields()) });
        else await ctx.api(`/studio/api/farm/posts/${state.editing}/scenes`, { method: "PUT", body: JSON.stringify({ scenes }) });
        state.editor = await ctx.api(`/studio/api/farm/posts/${state.editing}/scenes/${index}/media`, { method: "PUT", body: JSON.stringify(choice) });
      } catch (error) {
        ctx.notify(error.message);
        return;
      }
      box.remove();
      drawEditor();
    };
    const find = async () => {
      results.replaceChildren(h("p", { class: "muted", text: "Looking…" }));
      let found = [];
      try {
        ({ candidates: found } = await ctx.api(`/studio/api/farm/posts/${state.editing}/candidates?q=${encodeURIComponent(search.value)}`));
      } catch (error) {
        results.replaceChildren(h("p", { class: "muted", text: error.message }));
        return;
      }
      results.replaceChildren(...(found.length ? found.map((item) =>
        h("button", { class: "farm-candidate", type: "button", title: item.title, onclick: () => use(item.asset_id ? { asset_id: item.asset_id } : { url: item.url, source: item.source, title: item.title, credit: item.credit }) }, [
          h("img", { src: item.preview, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }),
          h("small", { text: `${item.kind === "video" ? "🎞 " : ""}${item.title}` }),
          h("span", { class: "farm-badge", text: item.source === "library" ? "yours" : item.source }),
        ])
      ) : [h("p", { class: "muted", text: "Nothing found. Try other words, or upload your own." })]));
    };
    upload.addEventListener("change", async () => {
      const file = upload.files && upload.files[0];
      if (!file) return;
      results.replaceChildren(h("p", { class: "muted", text: `Uploading ${file.name}…` }));
      try {
        const asset = await uploadFile(file, { show: (channel() || {}).fandom || "" });
        await use({ asset_id: asset.id });
      } catch (error) {
        ctx.notify(error.message);
      }
    });
    box = modal(`Scene ${index + 1}: picture or clip`, [
      h("form", { class: "row", onsubmit: (event) => { event.preventDefault(); find(); } }, [h("div", { class: "grow" }, [search]), h("button", { class: "ghost-button", type: "submit", text: "Search" })]),
      h("div", { class: "row" }, [
        h("label", { class: "ghost-button small" }, ["⬆ Upload my own", upload]),
        h("button", { class: "ghost-button small", type: "button", text: "🎲 Let the AI pick", onclick: () => use({ auto: true }) }),
      ]),
      results,
    ]);
    find();
  }

  /* ------------------------------------------------------------ library */

  async function uploadFile(file, { show = "", background = false, tags = "" } = {}) {
    const params = new URLSearchParams({ name: file.name, show, background: String(background), tags });
    return ctx.api(`/studio/api/farm/media?${params}`, {
      method: "POST",
      body: file,
      headers: { "content-type": file.type || "application/octet-stream" },
    });
  }

  async function drawLibrary() {
    const list = h("div", { class: "farm-library" }, [h("p", { class: "muted", text: "Loading…" })]);
    const files = h("input", { type: "file", accept: "image/*,video/*,audio/*", multiple: true, class: "visually-hidden", "aria-label": "Add clips, pictures, and songs" });
    const show = h("input", { type: "text", value: state.libraryShow || (channel() || {}).fandom || "", placeholder: "Which show they're from (optional)", "aria-label": "Show for new files" });
    const asBackground = h("input", { type: "checkbox", "aria-label": "Background video" });
    const status = h("p", { class: "muted small", role: "status" });
    const folder = h("input", { type: "text", placeholder: "C:\\Users\\you\\Videos\\Breaking Bad clips", "aria-label": "Folder on this PC" });
    files.addEventListener("change", async () => {
      const chosen = [...(files.files || [])];
      for (const [number, file] of chosen.entries()) {
        status.textContent = `Uploading ${number + 1} of ${chosen.length}: ${file.name}…`;
        try {
          await uploadFile(file, { show: show.value, background: asBackground.checked });
        } catch (error) {
          ctx.notify(`${file.name}: ${error.message}`);
        }
      }
      status.textContent = `Added ${chosen.length} file${chosen.length === 1 ? "" : "s"}.`;
      files.value = "";
      await fillLibrary(list);
      await refresh();
    });
    stage.append(h("section", { class: "card farm-library-card" }, [
      h("h2", { text: "Media library" }),
      h("p", { class: "muted", text: "Your clips and pictures: the farm uses them first, matched by their names, tags, and notes, so name them for what they show (“walt teaching chemistry.mp4”). Clips play muted under the voice. Tick Background for gameplay to play under whole shorts. Songs (MP3, WAV, M4A) are for music edits and cartoons." }),
      h("div", { class: "farm-grid" }, [
        h("div", { class: "farm-field" }, [
          h("strong", { text: "Upload" }),
          show,
          h("label", { class: "check" }, [asBackground, " Background video (gameplay)"]),
          h("label", { class: "primary farm-upload" }, ["⬆ Add clips, pictures, and songs", files]),
          status,
        ]),
        h("form", {
          class: "farm-field",
          onsubmit: async (event) => {
            event.preventDefault();
            if (!folder.value.trim()) return;
            status.textContent = "Reading the folder…";
            try {
              const result = await ctx.post("/studio/api/farm/media/link", { folder: folder.value, show: show.value, background: asBackground.checked });
              status.textContent = `Linked ${result.added} file${result.added === 1 ? "" : "s"} (they stay where they are).`;
            } catch (error) {
              status.textContent = error.message;
            }
            await fillLibrary(list);
            await refresh();
          },
        }, [
          h("strong", { text: "Or link a folder on this PC" }),
          folder,
          h("small", { class: "muted", text: "Every clip and picture inside is added without copying; folder names become tags." }),
          h("button", { class: "ghost-button", type: "submit", text: "Link folder" }),
        ]),
      ]),
      list,
    ]));
    await fillLibrary(list);
  }

  async function fillLibrary(list) {
    let assets = [];
    try {
      ({ assets } = await ctx.api("/studio/api/farm/media"));
    } catch (error) {
      list.replaceChildren(h("p", { class: "muted", text: error.message }));
      return;
    }
    if (!ctx.alive()) return;
    if (!assets.length) {
      list.replaceChildren(h("p", { class: "muted", text: "Nothing yet. Add your clips and stills, or link a folder of them." }));
      return;
    }
    list.replaceChildren(...assets.map((asset) => {
      const note = h("input", { type: "text", value: asset.note || "", placeholder: "What it shows", "aria-label": `Note for ${asset.name}` });
      const tags = h("input", { type: "text", value: (asset.tags || []).join(", "), "aria-label": `Tags for ${asset.name}` });
      const background = h("input", { type: "checkbox", checked: Boolean(asset.background), "aria-label": `${asset.name} is a background video` });
      const save = () => ctx.patch(`/studio/api/farm/media/${asset.id}`, { note: note.value, tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean), background: background.checked }).then(() => ctx.notify("Saved.")).catch((error) => ctx.notify(error.message));
      note.addEventListener("change", save);
      tags.addEventListener("change", save);
      background.addEventListener("change", async () => { await save(); await refresh(); });
      return h("article", { class: "farm-asset" }, [
        h("div", { class: "farm-asset-thumb" }, [
          asset.kind === "audio"
            ? h("span", { class: "farm-asset-song", text: "🎵" })
            : h("img", { src: asset.thumb_url, alt: "", loading: "lazy" }),
          asset.kind === "video" ? h("span", { class: "farm-badge", text: `🎞 ${Math.round(asset.duration)}s` }) : null,
          asset.kind === "audio" ? h("span", { class: "farm-badge", text: `🎵 ${Math.round(asset.duration)}s` }) : null,
        ].filter(Boolean)),
        h("strong", { text: asset.name }),
        h("small", { class: "muted", text: [asset.show, asset.source === "folder" ? "linked" : ""].filter(Boolean).join(" · ") }),
        note,
        tags,
        h("div", { class: "row" }, [
          asset.kind === "video" ? h("label", { class: "check small" }, [background, " Background"]) : h("span"),
          h("button", { class: "ghost-button small", type: "button", "aria-label": `Remove ${asset.name}`, text: "🗑", onclick: async () => { await ctx.remove(`/studio/api/farm/media/${asset.id}`); await fillLibrary(list); } }),
        ]),
      ]);
    }));
  }

  /* ------------------------------------------------------------ characters */

  const HAIR_NAMES = { short: "Short", afro: "Afro", long: "Long", bald: "Bald", bun: "Bun", braids: "Braids", spiky: "Spiky", curly: "Curly" };
  const WEAR_NAMES = { none: "Nothing", wrap: "Head wrap", crown: "Crown", turban: "Turban", cap: "Cap", hood: "Hood", helmet: "Helmet", headband: "Headband", hat: "Hat" };

  function drawCast() {
    const characters = state.data.characters || [];
    const list = h("div", { class: "farm-cast" }, characters.length
      ? characters.map((item) => h("button", { class: "farm-cast-card", type: "button", "aria-label": `Edit ${item.name}`, onclick: () => editCharacter(item) }, [
          h("img", { src: `/studio/api/farm/characters/${item.id}/picture?v=${item.updated_at}`, alt: "", loading: "lazy" }),
          h("strong", { text: item.name }),
          h("small", { class: "muted", text: item.description || "No notes yet" }),
        ]))
      : [h("p", { class: "muted", text: "No characters yet. Add the people in your stories: the writer uses them by name, and each can have their own voice." })]);
    stage.append(h("section", { class: "card farm-cast-card-list" }, [
      h("div", { class: "row" }, [
        h("div", { class: "grow" }, [
          h("h2", { text: "Characters" }),
          h("p", { class: "muted", text: "Big heads on stick bodies, like the history cartoon accounts. Give each a look (or a picture of a face from your library) and a voice, then tick them in a cartoon channel's settings." }),
        ]),
        h("button", { class: "primary", type: "button", text: "+ Add character", onclick: () => editCharacter(null) }),
      ]),
      list,
    ]));
  }

  function editCharacter(item) {
    const options = state.data.character_options || {};
    const value = (key, fallback) => (item && item[key] != null && item[key] !== "" ? item[key] : fallback);
    const field = (label, input) => h("label", { class: "farm-field" }, [label, input]);
    const choose = (key, names, list, fallback) => h("select", { "aria-label": key, "data-key": key }, [
      h("option", { value: "", text: "Pick for me" }),
      ...(list || Object.keys(names)).map((option) => h("option", { value: option, text: names[option] || option, selected: value(key, fallback) === option })),
    ]);
    const colourPick = (key, label, fallback) => {
      const input = h("input", { type: "color", value: value(key, fallback), "aria-label": label, "data-key": key });
      const auto = h("input", { type: "checkbox", checked: !item || !item[key], "aria-label": `${label}: pick for me` });
      return { input, auto, node: h("div", { class: "farm-colour" }, [input, h("label", { class: "check small" }, [auto, " pick for me"])]) };
    };
    const name = h("input", { type: "text", value: value("name", ""), placeholder: "e.g. Sundiata", "aria-label": "Name" });
    const about = h("textarea", { rows: 2, placeholder: "Who they are, for the writer: a young prince who couldn't walk", "aria-label": "Who they are" });
    about.value = value("description", "");
    const age = h("select", { "aria-label": "Age" }, (options.ages || ["kid", "adult", "old"]).map((key) => h("option", { value: key, text: { kid: "Child", adult: "Grown-up", old: "Old" }[key] || key, selected: value("age", "adult") === key })));
    const skin = colourPick("skin", "Skin", "#c68a5a");
    const hair = choose("hair", HAIR_NAMES, options.hair, "");
    const hairColour = colourPick("hair_colour", "Hair colour", "#1d1a18");
    const wear = choose("wear", WEAR_NAMES, options.wear, "");
    const wearColour = colourPick("wear_colour", "Head wear colour", "#3fa9f5");
    const flags = ["beard", "earrings", "glasses"].map((key) => h("label", { class: "check" }, [h("input", { type: "checkbox", checked: Boolean(value(key, false)), "data-flag": key }), ` ${key[0].toUpperCase()}${key.slice(1)}`]));
    const pictures = (state.data.library || {}).pictures || [];
    const head = h("select", { "aria-label": "Face picture" }, [
      h("option", { value: "", text: "Drawn head" }),
      ...pictures.map((picture) => h("option", { value: picture.id, text: picture.name, selected: value("head_asset", "") === picture.id })),
    ]);
    const voice = h("select", { "aria-label": "Voice" }, [
      h("option", { value: "", text: "The narrator's voice" }),
      ...(state.data.voices || []).map((key) => h("option", { value: key, text: voiceName(key), selected: value("voice", "") === key })),
    ]);
    const preview = item ? h("img", { class: "farm-cast-preview", src: `/studio/api/farm/characters/${item.id}/picture?v=${item.updated_at}`, alt: `${item.name}` }) : null;
    let box = null;
    const save = async () => {
      const body = {
        name: name.value,
        description: about.value,
        age: age.value,
        hair: hair.value,
        wear: wear.value,
        head_asset: head.value,
        voice: voice.value,
        skin: skin.auto.checked ? "" : skin.input.value,
        hair_colour: hairColour.auto.checked ? "" : hairColour.input.value,
        wear_colour: wearColour.auto.checked ? "" : wearColour.input.value,
      };
      for (const flag of box.querySelectorAll("[data-flag]")) body[flag.dataset.flag] = flag.checked;
      const saved = await act(
        () => (item ? ctx.api(`/studio/api/farm/characters/${item.id}`, { method: "PUT", body: JSON.stringify(body) }) : ctx.post("/studio/api/farm/characters", body)),
        item ? "Character saved." : "Character added. Tick them in a cartoon channel's settings."
      );
      if (saved) box.remove();
    };
    box = modal(item ? `Edit ${item.name}` : "New character", clean([
      preview,
      h("div", { class: "farm-grid" }, [
        field("Name", name),
        field("Age", age),
        field("Who they are", about),
        field("Voice", voice),
        field("Skin", skin.node),
        field("Hair", hair),
        field("Hair colour", hairColour.node),
        field("On their head", wear),
        field("Head wear colour", wearColour.node),
        field("Face picture (optional)", head),
      ]),
      h("div", { class: "row" }, flags),
      h("p", { class: "muted small", text: "A face picture from the library replaces the drawn head: a plain background is cut away. Anything left on “pick for me” is chosen from the name, so they always look the same." }),
      h("div", { class: "row" }, clean([
        h("button", { class: "primary", type: "button", text: item ? "Save" : "Add character", onclick: save }),
        item ? h("button", {
          class: "ghost-button danger",
          type: "button",
          text: "Delete",
          onclick: async () => {
            if (!window.confirm(`Delete ${item.name}?`)) return;
            await act(() => ctx.remove(`/studio/api/farm/characters/${item.id}`), "Character deleted.");
            box.remove();
          },
        }) : null,
      ])),
    ]));
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

  window.FCCFarm = { render, state, openEditor };
})();
