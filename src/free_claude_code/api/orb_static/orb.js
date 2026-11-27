"use strict";
// JARVIS Orb: draw the orb, type the reply out, then speak it with a local voice.
(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("orb"), ctx = canvas.getContext("2d");
  const caption = $("caption"), you = $("you"), input = $("text");
  const store = {
    get: (k, d) => { try { const v = localStorage.getItem("orb." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem("orb." + k, JSON.stringify(v)); } catch { /* private mode */ } },
  };
  // Looks the owner can switch between (gear > Look). Gold is the default.
  const THEMES = {
    core: { name: "Gold core (original)", style: "core", bg: ["#0b1a28", "#02070d"], accent: "#ffc861",
      colors: { idle: [255, 200, 97], listening: [255, 220, 140], thinking: [255, 170, 60], speaking: [255, 214, 130], error: [255, 93, 108] } },
    gold: { name: "Gold", style: "gold", bg: ["#1a1203", "#050301"], accent: "#f5c24a",
      colors: { idle: [255, 190, 70], listening: [255, 236, 160], thinking: [255, 150, 40], speaking: [255, 214, 110], error: [255, 90, 70] } },
    sun: { name: "Gold sun", style: "rays", bg: ["#170d02", "#040201"], accent: "#ffb43c",
      colors: { idle: [255, 176, 60], listening: [255, 230, 150], thinking: [255, 130, 30], speaking: [255, 205, 90], error: [255, 80, 60] } },
    arc: { name: "Arc blue", style: "rings", bg: ["#061423", "#020409"], accent: "#3fd0ff",
      colors: { idle: [63, 208, 255], listening: [80, 255, 170], thinking: [255, 196, 80], speaking: [90, 220, 255], error: [255, 90, 90] } },
    holo: { name: "Hologram", style: "sphere", bg: ["#04161a", "#010506"], accent: "#5cf2e6",
      colors: { idle: [92, 242, 230], listening: [150, 255, 200], thinking: [255, 200, 90], speaking: [120, 250, 240], error: [255, 90, 90] } },
    crimson: { name: "Crimson", style: "rings", bg: ["#1c0406", "#060102"], accent: "#ff4d5e",
      colors: { idle: [255, 70, 90], listening: [255, 170, 120], thinking: [255, 190, 70], speaking: [255, 110, 120], error: [255, 255, 255] } },
  };
  const params = new URLSearchParams(location.search);
  let theme = THEMES[params.get("look")] || THEMES[store.get("look", "core")] || THEMES.core;
  const coreCanvas = $("core");
  let coreOrb = null;
  function applyTheme() {
    const useCore = theme.style === "core" && window.FCCCoreOrb;
    coreCanvas.hidden = !useCore;
    if (useCore && !coreOrb) coreOrb = window.FCCCoreOrb.createCoreOrb(coreCanvas);
    const root = document.documentElement.style;
    root.setProperty("--glow", theme.accent);
    root.setProperty("--bg1", theme.bg[0]); root.setProperty("--bg2", theme.bg[1]);
  }
  applyTheme();
  const sparks = Array.from({ length: 70 }, () => ({ a: Math.random() * Math.PI * 2, r: 1 + Math.random() * 1.6, s: 0.1 + Math.random() * 0.5, z: Math.random() }));
  let state = "idle", level = 0, target = 0, t = 0, busy = false;
  let voiceOn = store.get("voiceOn", true);
  let audioLevel = 0;
  let lastSay = 0;

  // ---------- orb drawing ----------
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  addEventListener("resize", resize); resize();

  function glowCore(cx, cy, rad, r, g, b) {
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
    core.addColorStop(0, "rgba(255,252,240,0.97)");
    core.addColorStop(0.3, `rgba(${r},${g},${b},0.85)`);
    core.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.shadowBlur = 0; ctx.fillStyle = core;
    ctx.beginPath(); ctx.arc(cx, cy, rad, 0, Math.PI * 2); ctx.fill();
  }
  function wobblyRings(cx, cy, base, r, g, b, count, speed) {
    for (let ring = 0; ring < count; ring++) {
      ctx.beginPath();
      const spin = t * speed * (ring % 2 ? 1 : -1);
      for (let i = 0; i <= 120; i++) {
        const a = (i / 120) * Math.PI * 2;
        const wob = Math.sin(a * (3 + ring) + spin) * base * 0.06 * (1 + level * 3)
          + Math.sin(a * 7 - spin * 1.7) * base * 0.03 * level * 4;
        const rad = base * (0.78 + ring * 0.07) + wob;
        const x = cx + Math.cos(a) * rad, y = cy + Math.sin(a) * rad;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.strokeStyle = `rgba(${r},${g},${b},${0.55 - ring * 0.08})`;
      ctx.lineWidth = 1.4 + level * 2.2; ctx.shadowBlur = 18; ctx.shadowColor = `rgb(${r},${g},${b})`;
      ctx.stroke();
    }
  }
  function draw() {
    t += 0.016;
    if (state === "speaking") target = 0.35 + 0.65 * Math.abs(Math.sin(t * 7.3) * Math.sin(t * 3.1 + 1));
    else if (state === "thinking") target = 0.35 + 0.15 * Math.sin(t * 5);
    else if (state === "listening") target = 0.45 + 0.2 * Math.sin(t * 9);
    else target = 0.12 + 0.06 * Math.sin(t * 1.4);
    if (state === "speaking" && audioLevel > 0) target = 0.3 + audioLevel;
    level += (target - level) * 0.12;
    if (theme.style === "core" && coreOrb) {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      coreOrb.setState(state === "error" ? "offline" : state);
      coreOrb.setLevel(audioLevel);
      return requestAnimationFrame(draw);
    }
    const [r, g, b] = theme.colors[state] || theme.colors.idle;
    const w = innerWidth, h = innerHeight, cx = w / 2, cy = h * 0.44;
    const base = Math.min(w, h) * 0.17;
    const spin = state === "thinking" ? 2.4 : 0.6;
    ctx.clearRect(0, 0, w, h);
    const halo = ctx.createRadialGradient(cx, cy, base * 0.2, cx, cy, base * (2.6 + level));
    halo.addColorStop(0, `rgba(${r},${g},${b},${0.20 + level * 0.25})`);
    halo.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = halo; ctx.fillRect(0, 0, w, h);

    if (theme.style === "gold") {
      // molten gold sphere: shaded body, slow golden bands and drifting sparks
      const body = ctx.createRadialGradient(cx - base * 0.3, cy - base * 0.35, base * 0.1, cx, cy, base * 0.95);
      body.addColorStop(0, "rgba(255,246,214,1)");
      body.addColorStop(0.35, `rgba(${r},${g},${b},0.95)`);
      body.addColorStop(0.8, `rgba(${Math.round(r * 0.55)},${Math.round(g * 0.4)},${Math.round(b * 0.2)},0.95)`);
      body.addColorStop(1, "rgba(40,22,4,0.0)");
      ctx.shadowBlur = 40 + level * 60; ctx.shadowColor = `rgb(${r},${g},${b})`;
      ctx.fillStyle = body; ctx.beginPath(); ctx.arc(cx, cy, base * (0.9 + level * 0.08), 0, Math.PI * 2); ctx.fill();
      ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, base * (0.9 + level * 0.08), 0, Math.PI * 2); ctx.clip();
      for (let k = 0; k < 6; k++) {
        ctx.beginPath();
        const yy = cy + Math.sin(t * spin * 0.6 + k * 1.1) * base * 0.7;
        ctx.ellipse(cx, yy, base * 0.95, base * (0.08 + 0.05 * Math.sin(t + k)), 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,236,180,${0.12 + level * 0.18})`; ctx.lineWidth = 2; ctx.shadowBlur = 0; ctx.stroke();
      }
      ctx.restore();
      for (const p of sparks) {
        p.a += 0.004 * p.s * (1 + level * 6);
        const rad = base * (1.05 + p.z * 0.9 + level * 0.4);
        const x = cx + Math.cos(p.a) * rad, y = cy + Math.sin(p.a) * rad * 0.92;
        ctx.fillStyle = `rgba(255,${200 + Math.round(p.z * 50)},120,${0.35 + 0.5 * (1 - p.z)})`;
        ctx.shadowBlur = 8; ctx.shadowColor = "#ffcc55";
        ctx.beginPath(); ctx.arc(x, y, p.r * (1 + level), 0, Math.PI * 2); ctx.fill();
      }
      ctx.lineWidth = 1.2; ctx.strokeStyle = `rgba(${r},${g},${b},0.5)`; ctx.shadowBlur = 14;
      ctx.beginPath(); ctx.arc(cx, cy, base * (1.25 + level * 0.25), t * spin, t * spin + Math.PI * 1.3); ctx.stroke();
      ctx.beginPath(); ctx.arc(cx, cy, base * (1.38 + level * 0.3), -t * spin * 0.7, -t * spin * 0.7 + Math.PI * 0.8); ctx.stroke();
    } else if (theme.style === "rays") {
      for (let i = 0; i < 48; i++) {
        const a = (i / 48) * Math.PI * 2 + t * spin * 0.2;
        const len = base * (0.35 + 0.25 * Math.abs(Math.sin(i * 1.7 + t * 3)) * (0.4 + level * 2));
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * base * 0.95, cy + Math.sin(a) * base * 0.95);
        ctx.lineTo(cx + Math.cos(a) * (base * 0.95 + len), cy + Math.sin(a) * (base * 0.95 + len));
        ctx.strokeStyle = `rgba(${r},${g},${b},${0.35 + level * 0.4})`; ctx.lineWidth = 2.2;
        ctx.shadowBlur = 16; ctx.shadowColor = `rgb(${r},${g},${b})`; ctx.stroke();
      }
      glowCore(cx, cy, base * (0.95 + level * 0.15), r, g, b);
      return requestAnimationFrame(draw);
    } else if (theme.style === "sphere") {
      ctx.lineWidth = 1; ctx.shadowBlur = 10; ctx.shadowColor = `rgb(${r},${g},${b})`;
      const R = base * (0.95 + level * 0.12);
      for (let k = 0; k < 9; k++) {                       // meridians
        const ph = (k / 9) * Math.PI + t * spin * 0.5;
        ctx.beginPath(); ctx.ellipse(cx, cy, Math.abs(Math.cos(ph)) * R, R, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${r},${g},${b},${0.25 + level * 0.3})`; ctx.stroke();
      }
      for (let k = 1; k < 6; k++) {                       // parallels
        const y = cy - R + (2 * R * k) / 6, half = Math.sqrt(Math.max(0, R * R - (y - cy) ** 2));
        ctx.beginPath(); ctx.ellipse(cx, y, half, half * 0.18, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${r},${g},${b},0.3)`; ctx.stroke();
      }
      glowCore(cx, cy, R * (0.45 + level * 0.25), r, g, b);
      return requestAnimationFrame(draw);
    } else {
      wobblyRings(cx, cy, base, r, g, b, 5, spin);
    }
    glowCore(cx, cy, base * (theme.style === "gold" ? 0.42 + level * 0.2 : 0.72 + level * 0.18), r, g, b);
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  // ---------- voice ----------
  // "kokoro:<name>" = Jarvis's own offline voice (served by FCC); "web:<name>" = a Windows voice.
  const synth = window.speechSynthesis;
  const PREFERRED = [/george/i, /ryan/i, /thomas/i, /uk english male/i, /en-gb.*male/i, /oliver/i, /daniel/i];
  const KOKORO_NAMES = { jarvis: "Jarvis (original: George + Lewis, offline)", bm_george: "George (British)", bm_lewis: "Lewis (British)",
    bm_daniel: "Daniel (British)", bm_fable: "Fable (British)", am_michael: "Michael (American)", am_adam: "Adam (American)",
    bf_emma: "Emma (British)", af_heart: "Heart (American)" };
  let kokoro = { ready: false, voices: [] };
  let player = null, stopAll = false;
  function chosen() { return store.get("voiceChoice", "kokoro:jarvis"); }
  function webVoices() { return synth ? synth.getVoices() : []; }
  function pickWebVoice() {
    const all = webVoices(), saved = chosen().startsWith("web:") ? chosen().slice(4) : "";
    const byName = all.find((v) => v.name === saved);
    if (byName) return byName;
    for (const re of PREFERRED) { const v = all.find((x) => re.test(x.name)); if (v) return v; }
    return all.find((v) => /^en-GB/i.test(v.lang)) || all.find((v) => /^en/i.test(v.lang)) || all[0] || null;
  }
  function fillVoices() {
    const sel = $("voice"), current = chosen();
    sel.innerHTML = "";
    const offline = document.createElement("optgroup"); offline.label = kokoro.ready ? "Jarvis's own voice (offline)" : "Jarvis's own voice (downloading...)";
    for (const name of kokoro.voices.length ? kokoro.voices : ["jarvis"]) {
      const o = document.createElement("option"); o.value = "kokoro:" + name; o.textContent = KOKORO_NAMES[name] || name;
      o.selected = o.value === current; offline.appendChild(o);
    }
    sel.appendChild(offline);
    const win = document.createElement("optgroup"); win.label = "Windows voices";
    for (const v of webVoices()) {
      const o = document.createElement("option"); o.value = "web:" + v.name; o.textContent = `${v.name} (${v.lang})`;
      o.selected = o.value === current; win.appendChild(o);
    }
    sel.appendChild(win);
  }
  if (synth) synth.onvoiceschanged = fillVoices;

  async function refreshVoice(startDownload) {
    try {
      kokoro = await api("/orb/api/voice");
      if (startDownload && !kokoro.ready && !kokoro.downloading && chosen().startsWith("kokoro:")) {
        kokoro = await api("/orb/api/voice/setup", {});
      }
      $("voiceInfo").textContent = kokoro.ready ? "Jarvis's voice runs on this PC, offline."
        : kokoro.downloading ? `Downloading Jarvis's voice (one time, ${kokoro.download_mb} MB): ${Math.round(kokoro.progress * 100)}%. A Windows voice speaks until then.`
        : kokoro.error || `Jarvis's voice needs a one-time ${kokoro.download_mb} MB download.`;
      $("effect").checked = kokoro.effect !== false;
      if (kokoro.downloading) setTimeout(() => refreshVoice(false), 3000);
    } catch { kokoro = { ready: false, voices: [] }; }
  }

  function speakable(text) {
    return text.replace(/```[\s\S]*?```/g, " (code shown on screen) ")
      .replace(/`([^`]*)`/g, "$1").replace(/\[\[([^\]|]+)(\|[^\]]+)?\]\]/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/https?:\/\/\S+/g, "a link")
      .replace(/[#*_>|~]+/g, " ").replace(/\s+/g, " ").trim();
  }
  function sentences(clean) { return (clean.match(/[^.!?]+[.!?]*|.+$/g) || [clean]).map((p) => p.trim()).filter(Boolean); }

  function stopSpeaking() {
    stopAll = true;
    if (synth) synth.cancel();
    if (player) { player.pause(); player = null; }
    audioLevel = 0; setState("idle");
  }

  let audioCtx = null;
  function playWav(blob) {
    return new Promise((resolve) => {
      const audio = new Audio(URL.createObjectURL(blob));
      player = audio;
      try {
        audioCtx = audioCtx || new AudioContext();
        const src = audioCtx.createMediaElementSource(audio), an = audioCtx.createAnalyser();
        an.fftSize = 512; src.connect(an); an.connect(audioCtx.destination);
        const buf = new Uint8Array(an.fftSize);
        const meter = () => {
          if (player !== audio) return;
          an.getByteTimeDomainData(buf);
          let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
          audioLevel = Math.min(1, peak / 70); requestAnimationFrame(meter);
        };
        meter();
      } catch { /* no Web Audio: the orb pulses on its own */ }
      audio.onended = audio.onerror = () => { URL.revokeObjectURL(audio.src); resolve(); };
      audio.play().catch(() => resolve());
    });
  }
  async function fetchSpeech(part) {
    const res = await fetch("/orb/api/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: part }) });
    if (!res.ok) throw new Error("voice not ready");
    return res.blob();
  }
  async function speakKokoro(parts) {
    let next = fetchSpeech(parts[0]);
    for (let i = 0; i < parts.length && !stopAll; i++) {
      const blob = await next;
      if (i + 1 < parts.length) next = fetchSpeech(parts[i + 1]);   // make the next sentence while this one plays
      await playWav(blob);
    }
  }
  function speakWeb(parts) {
    return new Promise((resolve) => {
      if (!synth) { resolve(); return; }
      const voice = pickWebVoice(), rate = Number(store.get("rate", 1.0));
      let left = parts.length;
      for (const part of parts) {
        const u = new SpeechSynthesisUtterance(part);
        if (voice) u.voice = voice;
        u.rate = rate; u.pitch = 0.92;
        u.onend = u.onerror = () => { if (--left <= 0) resolve(); };
        synth.speak(u);
      }
    });
  }
  async function speak(text) {
    const clean = speakable(text);
    if (!voiceOn || !clean) return;
    stopSpeaking(); stopAll = false;
    const parts = sentences(clean);
    setState("speaking");
    try {
      if (chosen().startsWith("kokoro:") && kokoro.ready) await speakKokoro(parts);
      else await speakWeb(parts);
    } catch { if (!stopAll) await speakWeb(parts); }    // offline voice failed: a Windows voice says it
    audioLevel = 0; player = null;
    if (state === "speaking") setState("idle");
  }

  // ---------- typing then speaking ----------
  async function typeOut(text) {
    caption.textContent = "";
    const step = Math.max(1, Math.ceil(text.length / 160));
    for (let i = 0; i < text.length; i += step) {
      caption.textContent = text.slice(0, i + step);
      caption.scrollTop = caption.scrollHeight;
      await new Promise((r) => setTimeout(r, 14));
    }
    caption.textContent = text;
  }
  async function deliver(text) { await typeOut(text); await speak(text); }

  function setState(s) { state = s; }

  // ---------- talking to the server ----------
  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  async function ask(text) {
    if (!text || busy) return;
    busy = true; if (synth) synth.cancel();
    you.textContent = text; caption.textContent = ""; setState("thinking");
    try {
      const data = await api("/orb/api/chat", { text });
      const extra = data.tools_used && data.tools_used.length ? `\n\n(used: ${data.tools_used.join(", ")})` : "";
      if (data.compacted) $("info").textContent = "Older conversation saved to Obsidian memory.";
      setState("idle");
      await typeOut(data.reply + extra);
      await speak(data.reply);
    } catch (err) {
      setState("error"); caption.textContent = "Problem: " + err.message;
      setTimeout(() => state === "error" && setState("idle"), 4000);
    } finally { busy = false; }
  }

  $("ask").addEventListener("submit", (e) => { e.preventDefault(); const v = input.value.trim(); input.value = ""; ask(v); });

  // ---------- microphone: recorded here, understood by Whisper on this PC ----------
  let ears = { ready: false };
  let recorder = null;
  async function refreshEars(startDownload) {
    try {
      ears = await api("/orb/api/ears");
      if (startDownload && !ears.ready && !ears.downloading) ears = await api("/orb/api/ears/setup", {});
      $("earsInfo").textContent = ears.ready ? "Ears: Whisper on this PC, offline."
        : ears.downloading ? `Ears downloading (one time, about ${ears.download_mb} MB). Type until then.`
        : ears.error || "Ears not set up yet.";
      if (ears.downloading) setTimeout(() => refreshEars(false), 4000);
    } catch { ears = { ready: false }; }
  }
  async function orbClick() {
    if (state === "speaking") { stopSpeaking(); return; }
    if (recorder) { recorder.stop(); return; }
    if (busy) return;
    if (!ears.ready) {
      caption.textContent = ears.downloading ? "My ears are still downloading, sir. Type for now." : "My ears are not set up yet. Type for now.";
      input.focus(); return;
    }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch { caption.textContent = "I can't use the microphone. Allow it for this window, or type."; return; }
    const chunks = [], started = performance.now();
    const rec = new MediaRecorder(stream);
    recorder = rec;
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    // Stop by itself after you finish speaking (1.4 s of quiet) or after 30 s.
    let heard = false, quietSince = 0;
    try {
      const ctxA = new AudioContext(), an = ctxA.createAnalyser(), buf = new Uint8Array(512);
      an.fftSize = 512; ctxA.createMediaStreamSource(stream).connect(an);
      const watch = () => {
        if (recorder !== rec) { ctxA.close(); return; }
        an.getByteTimeDomainData(buf);
        let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        audioLevel = Math.min(1, peak / 60);
        const now = performance.now();
        if (peak > 12) { heard = true; quietSince = now; }
        if ((heard && now - quietSince > 1400) || now - started > 30000) { rec.stop(); return; }
        requestAnimationFrame(watch);
      };
      watch();
    } catch { /* no level meter: click the orb to stop */ }
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      recorder = null; audioLevel = 0;
      if (!heard && !chunks.length) { setState("idle"); you.textContent = ""; return; }
      setState("thinking"); you.textContent = "...";
      try {
        const res = await fetch("/orb/api/listen", { method: "POST", headers: { "Content-Type": rec.mimeType || "audio/webm" }, body: new Blob(chunks, { type: rec.mimeType || "audio/webm" }) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        setState("idle");
        if (data.text) ask(data.text); else { you.textContent = ""; caption.textContent = "I didn't catch that, sir."; }
      } catch (err) { setState("idle"); you.textContent = ""; caption.textContent = "Problem: " + err.message; }
    };
    rec.start(250);
    setState("listening"); you.textContent = "Listening... (click the orb when you're done)";
  }
  canvas.addEventListener("click", orbClick);
  coreCanvas.addEventListener("click", orbClick);
  addEventListener("keydown", (e) => { if (e.key === "Escape") stopSpeaking(); });

  // ---------- JARVIS speaking from LM Studio (fcc_say) ----------
  async function pollInbox() {
    try {
      const data = await api(`/orb/api/inbox?after=${lastSay}`);
      for (const item of data.items || []) {
        lastSay = Math.max(lastSay, item.id);
        if (!busy) { you.textContent = ""; await deliver(item.text); }
      }
    } catch { /* server restarting */ }
    setTimeout(pollInbox, 1200);
  }

  async function refreshStatus() {
    try {
      const s = await api("/orb/api/status");
      $("dot").className = s.last_error ? "bad" : "ok";
      if (!lastSay) lastSay = s.last_say_id || 0;
      $("info").textContent = `FCC ${s.version} | model: ${s.model || "(loaded model)"} | tool servers: ${(s.servers || []).join(", ") || "none"}`
        + (s.tool_problems && s.tool_problems.length ? `\n${s.tool_problems.join("\n")}` : "")
        + `\nAdvisor: ${s.advisor_model ? s.advisor_model + " (read-only)" : "off"}`
        + `\n${s.local_only === false ? "Local only: OFF (an API advisor may be used)" : "Local only: everything stays on this PC"}`
        + (s.last_error ? `\nLast error: ${s.last_error}` : "");
    } catch { $("dot").className = "bad"; }
  }

  // ---------- settings panel ----------
  function paintVoiceToggle() { const b = $("voiceToggle"); b.textContent = voiceOn ? "Voice on" : "Voice off"; b.classList.toggle("off", !voiceOn); }
  $("voiceToggle").onclick = () => { voiceOn = !voiceOn; store.set("voiceOn", voiceOn); if (!voiceOn) stopSpeaking(); paintVoiceToggle(); };
  $("gear").onclick = async () => {
    const p = $("panel"); p.hidden = !p.hidden; if (p.hidden) return;
    await refreshVoice(false); await refreshEars(false); fillVoices(); $("rate").value = store.get("rate", 1.0); refreshStatus();
    try {
      const m = await api("/orb/api/models"), sel = $("model");
      sel.innerHTML = '<option value="">(loaded model)</option>';
      for (const x of m.models) { const o = document.createElement("option"); o.value = x.id; o.textContent = x.id + (x.loaded ? "  (loaded)" : ""); o.selected = x.id === m.current; sel.appendChild(o); }
    } catch (err) { $("info").textContent = err.message; }
  };
  const lookSel = $("look");
  for (const [key, th] of Object.entries(THEMES)) {
    const o = document.createElement("option"); o.value = key; o.textContent = th.name; o.selected = th === theme; lookSel.appendChild(o);
  }
  lookSel.onchange = (e) => { theme = THEMES[e.target.value] || THEMES.gold; store.set("look", e.target.value); applyTheme(); };
  $("voice").onchange = (e) => {
    const value = e.target.value; store.set("voiceChoice", value);
    if (value.startsWith("kokoro:")) api("/orb/api/voice/settings", { voice: value.slice(7) }).then(() => refreshVoice(true)).catch(() => {});
  };
  $("effect").onchange = (e) => api("/orb/api/voice/settings", { effect: e.target.checked }).catch(() => {});
  $("rate").oninput = (e) => store.set("rate", Number(e.target.value));
  $("rate").onchange = (e) => api("/orb/api/voice/settings", { speed: Number(e.target.value) }).catch(() => {});
  $("model").onchange = (e) => api("/orb/api/model", { model: e.target.value || null }).catch((err) => { $("info").textContent = err.message; });
  $("testVoice").onclick = () => speak("Good evening, sir. All systems are online.");
  $("newChat").onclick = async () => {
    $("info").textContent = "Saving this conversation to Obsidian...";
    try { const r = await api("/orb/api/new", {}); $("info").textContent = r.saved || "Started a new conversation."; you.textContent = ""; caption.textContent = ""; }
    catch (err) { $("info").textContent = err.message; }
  };
  $("reloadTools").onclick = async () => { $("info").textContent = "Restarting tool servers..."; try { await api("/orb/api/tools/reload", {}); } catch (err) { $("info").textContent = err.message; } refreshStatus(); };

  // ---------- read-only advisor (off unless the owner turns it on) ----------
  function sendAdvisor() {
    const on = store.get("advisorOn", false), model = store.get("advisorModel", "");
    return api("/orb/api/advisor", { model: on && model ? model : null }).catch((err) => {
      $("info").textContent = err.message; store.set("advisorOn", false); $("advisorOn").checked = false;
    });
  }
  async function sendPrivacy() {
    try { await api("/orb/api/privacy", { local_only: store.get("localOnly", true) }); } catch { /* older FCC */ }
    $("advisorModel").placeholder = store.get("localOnly", true) ? "lmstudio/<model name>" : "lmstudio/<model> or an API model";
  }
  $("localOnly").checked = store.get("localOnly", true);
  $("localOnly").onchange = async (e) => { store.set("localOnly", e.target.checked); await sendPrivacy(); sendAdvisor(); };
  $("advisorOn").checked = store.get("advisorOn", false);
  $("advisorModel").value = store.get("advisorModel", "");
  $("advisorOn").onchange = (e) => { store.set("advisorOn", e.target.checked); sendAdvisor(); };
  $("advisorModel").onchange = (e) => { store.set("advisorModel", e.target.value.trim()); sendAdvisor(); };
  sendPrivacy().then(sendAdvisor);
  refreshEars(true);

  refreshVoice(true).then(() => {
    const kv = chosen().startsWith("kokoro:") ? chosen().slice(7) : null;
    if (kv) api("/orb/api/voice/settings", { voice: kv, speed: Number(store.get("rate", 1.0)) }).catch(() => {});
  });
  paintVoiceToggle(); refreshStatus(); setInterval(refreshStatus, 15000); pollInbox();
  caption.textContent = "Click the orb and speak, or type below.";
})();
