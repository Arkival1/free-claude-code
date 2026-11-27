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
  const COLORS = { idle: [63, 208, 255], listening: [80, 255, 170], thinking: [255, 196, 80], speaking: [90, 220, 255], error: [255, 90, 90] };
  let state = "idle", level = 0, target = 0, t = 0, busy = false;
  let voiceOn = store.get("voiceOn", true);
  let lastSay = 0;

  // ---------- orb drawing ----------
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  addEventListener("resize", resize); resize();

  function draw() {
    t += 0.016;
    if (state === "speaking") target = 0.35 + 0.65 * Math.abs(Math.sin(t * 7.3) * Math.sin(t * 3.1 + 1));
    else if (state === "thinking") target = 0.35 + 0.15 * Math.sin(t * 5);
    else if (state === "listening") target = 0.45 + 0.2 * Math.sin(t * 9);
    else target = 0.12 + 0.06 * Math.sin(t * 1.4);
    level += (target - level) * 0.12;
    const [r, g, b] = COLORS[state] || COLORS.idle;
    const w = innerWidth, h = innerHeight, cx = w / 2, cy = h * 0.44;
    const base = Math.min(w, h) * 0.17;
    ctx.clearRect(0, 0, w, h);
    const halo = ctx.createRadialGradient(cx, cy, base * 0.2, cx, cy, base * (2.6 + level));
    halo.addColorStop(0, `rgba(${r},${g},${b},${0.20 + level * 0.25})`);
    halo.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = halo; ctx.fillRect(0, 0, w, h);
    for (let ring = 0; ring < 5; ring++) {
      ctx.beginPath();
      const spin = t * (state === "thinking" ? 2.4 : 0.6) * (ring % 2 ? 1 : -1);
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
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, base * (0.72 + level * 0.18));
    core.addColorStop(0, "rgba(235,250,255,0.95)");
    core.addColorStop(0.35, `rgba(${r},${g},${b},0.75)`);
    core.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.shadowBlur = 0; ctx.fillStyle = core;
    ctx.beginPath(); ctx.arc(cx, cy, base * (0.72 + level * 0.18), 0, Math.PI * 2); ctx.fill();
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  // ---------- voice ----------
  const synth = window.speechSynthesis;
  const PREFERRED = [/george/i, /ryan/i, /thomas/i, /uk english male/i, /en-gb.*male/i, /oliver/i, /daniel/i];
  function voices() { return synth ? synth.getVoices() : []; }
  function pickVoice() {
    const all = voices(), saved = store.get("voice", "");
    const byName = all.find((v) => v.name === saved);
    if (byName) return byName;
    for (const re of PREFERRED) { const v = all.find((x) => re.test(x.name)); if (v) return v; }
    return all.find((v) => /^en-GB/i.test(v.lang)) || all.find((v) => /^en/i.test(v.lang)) || all[0] || null;
  }
  function fillVoices() {
    const sel = $("voice"), current = pickVoice();
    sel.innerHTML = "";
    for (const v of voices()) {
      const o = document.createElement("option");
      o.value = v.name; o.textContent = `${v.name} (${v.lang})`; o.selected = current && v.name === current.name;
      sel.appendChild(o);
    }
  }
  if (synth) synth.onvoiceschanged = fillVoices;

  function speakable(text) {
    return text.replace(/```[\s\S]*?```/g, " (code shown on screen) ")
      .replace(/`([^`]*)`/g, "$1").replace(/\[\[([^\]|]+)(\|[^\]]+)?\]\]/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/https?:\/\/\S+/g, "a link")
      .replace(/[#*_>|~]+/g, " ").replace(/\s+/g, " ").trim();
  }
  function speak(text) {
    return new Promise((resolve) => {
      const clean = speakable(text);
      if (!voiceOn || !synth || !clean) { resolve(); return; }
      synth.cancel();
      // Chrome/Edge stop long utterances, so speak sentence by sentence.
      const parts = clean.match(/[^.!?]+[.!?]*|.+$/g) || [clean];
      const voice = pickVoice(), rate = Number(store.get("rate", 1.0));
      let left = parts.length;
      setState("speaking");
      for (const part of parts) {
        const u = new SpeechSynthesisUtterance(part.trim());
        if (voice) u.voice = voice;
        u.rate = rate; u.pitch = 0.92;
        u.onend = u.onerror = () => { if (--left <= 0) { setState("idle"); resolve(); } };
        synth.speak(u);
      }
    });
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

  // ---------- microphone ----------
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  canvas.addEventListener("click", () => {
    if (state === "speaking") { synth && synth.cancel(); setState("idle"); return; }
    if (!Recognition) { input.focus(); caption.textContent = "This browser has no speech input. Type instead."; return; }
    if (rec) { rec.stop(); return; }
    rec = new Recognition(); rec.lang = store.get("lang", "en-GB"); rec.interimResults = true;
    setState("listening");
    let heard = "";
    rec.onresult = (e) => { heard = Array.from(e.results).map((r) => r[0].transcript).join(" "); you.textContent = heard; };
    rec.onerror = () => { setState("idle"); };
    rec.onend = () => { rec = null; if (state === "listening") setState("idle"); if (heard.trim()) ask(heard.trim()); };
    rec.start();
  });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && synth) { synth.cancel(); setState("idle"); } });

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
        + (s.last_error ? `\nLast error: ${s.last_error}` : "");
    } catch { $("dot").className = "bad"; }
  }

  // ---------- settings panel ----------
  function paintVoiceToggle() { const b = $("voiceToggle"); b.textContent = voiceOn ? "Voice on" : "Voice off"; b.classList.toggle("off", !voiceOn); }
  $("voiceToggle").onclick = () => { voiceOn = !voiceOn; store.set("voiceOn", voiceOn); if (!voiceOn && synth) synth.cancel(); paintVoiceToggle(); };
  $("gear").onclick = async () => {
    const p = $("panel"); p.hidden = !p.hidden; if (p.hidden) return;
    fillVoices(); $("rate").value = store.get("rate", 1.0); refreshStatus();
    try {
      const m = await api("/orb/api/models"), sel = $("model");
      sel.innerHTML = '<option value="">(loaded model)</option>';
      for (const x of m.models) { const o = document.createElement("option"); o.value = x.id; o.textContent = x.id + (x.loaded ? "  (loaded)" : ""); o.selected = x.id === m.current; sel.appendChild(o); }
    } catch (err) { $("info").textContent = err.message; }
  };
  $("voice").onchange = (e) => store.set("voice", e.target.value);
  $("rate").oninput = (e) => store.set("rate", Number(e.target.value));
  $("model").onchange = (e) => api("/orb/api/model", { model: e.target.value || null }).catch((err) => { $("info").textContent = err.message; });
  $("testVoice").onclick = () => speak("Good evening, sir. All systems are online.");
  $("newChat").onclick = async () => {
    $("info").textContent = "Saving this conversation to Obsidian...";
    try { const r = await api("/orb/api/new", {}); $("info").textContent = r.saved || "Started a new conversation."; you.textContent = ""; caption.textContent = ""; }
    catch (err) { $("info").textContent = err.message; }
  };
  $("reloadTools").onclick = async () => { $("info").textContent = "Restarting tool servers..."; try { await api("/orb/api/tools/reload", {}); } catch (err) { $("info").textContent = err.message; } refreshStatus(); };

  paintVoiceToggle(); refreshStatus(); setInterval(refreshStatus, 15000); pollInbox();
  caption.textContent = "Click the orb and speak, or type below.";
})();
