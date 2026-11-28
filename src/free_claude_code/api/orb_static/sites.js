"use strict";
// Site Studio: knobs on the left, live preview on the right. JARVIS's edits show up live too.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, kids = []) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") n.textContent = v; else if (k.startsWith("on")) n[k] = v; else n.setAttribute(k, v);
    }
    for (const kid of [].concat(kids)) if (kid) n.append(kid);
    return n;
  };
  let lib = null, spec = null, slug = "", savedJson = "", dirty = false, previewTimer = 0, saveTimer = 0;

  async function api(path, method = "GET", body) {
    const res = await fetch(path, body === undefined ? { method } : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }
  function toast(text) { const t = $("toast"); t.textContent = text; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, 4500); }

  // ---------- preview + saving ----------
  function changed() {
    dirty = true; $("saved").textContent = "Unsaved changes...";
    clearTimeout(previewTimer); previewTimer = setTimeout(refreshPreview, 200);
    clearTimeout(saveTimer); saveTimer = setTimeout(save, 900);
  }
  async function refreshPreview() {
    if (!spec) return;
    try {
      const { html } = await api("/orb/api/sites/render", "POST", { spec });
      const frame = $("preview"), y = frame.contentWindow ? frame.contentWindow.scrollY : 0;
      frame.srcdoc = html;
      frame.onload = () => { try { frame.contentWindow.scrollTo(0, y); } catch { /* fine */ } };
    } catch (err) { toast(err.message); }
  }
  async function save() {
    if (!spec || !slug) return;
    try {
      spec = await api(`/orb/api/sites/${slug}`, "PUT", { spec });
      savedJson = JSON.stringify(spec); dirty = false;
      $("saved").textContent = "Saved " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (err) { $("saved").textContent = "Not saved: " + err.message; }
  }
  // JARVIS (in LM Studio) can edit the same site: pick up his changes live.
  async function watch() {
    if (slug && !dirty) {
      try {
        const latest = await api(`/orb/api/sites/${slug}`);
        const json = JSON.stringify(latest);
        if (savedJson && json !== savedJson) { spec = latest; savedJson = json; drawAll(); refreshPreview(); toast("Updated by JARVIS"); }
      } catch { /* server restarting */ }
    }
    setTimeout(watch, 2500);
  }

  // ---------- Look tab ----------
  function fillSelect(sel, names, current) {
    sel.replaceChildren(...names.map((n) => el("option", { value: n, text: n })));
    if (current !== undefined) sel.value = current;
  }
  function drawLook() {
    const t = spec.theme;
    const pals = Object.keys(lib.palettes);
    const custom = typeof t.palette === "object";
    fillSelect($("palette"), custom ? ["(your original palette)", ...pals] : pals, custom ? "(your original palette)" : t.palette);
    const colours = custom ? t.palette : lib.palettes[t.palette] || {};
    $("swatches").replaceChildren(...["bg", "surface", "text", "primary", "accent"].map((k) => el("span", { title: k, style: `background:${colours[k] || "#888"}` })));
    fillSelect($("font"), Object.keys(lib.fonts), t.font);
    fillSelect($("button"), Object.keys(lib.buttons), t.button);
    $("buttonDemo").textContent = lib.buttons[t.button] || "";
    for (const key of ["radius", "spacing", "scale", "shadow", "width"]) {
      const input = $(key); input.value = t[key]; input.nextElementSibling.textContent = t[key];
    }
  }
  $("palette").onchange = (e) => { if (lib.palettes[e.target.value]) { spec.theme.palette = e.target.value; drawLook(); changed(); } };
  $("font").onchange = (e) => { spec.theme.font = e.target.value; changed(); };
  $("button").onchange = (e) => { spec.theme.button = e.target.value; drawLook(); changed(); };
  for (const key of ["radius", "spacing", "scale", "shadow", "width"]) {
    $(key).oninput = (e) => { spec.theme[key] = Number(e.target.value); e.target.nextElementSibling.textContent = e.target.value; changed(); };
  }
  $("makePalette").onclick = async () => {
    try {
      const made = await api("/orb/api/sites/palette", "POST", { base: $("baseColour").value, harmony: $("harmony").value, mode: $("mode").value });
      spec.theme.palette = made.colours; drawLook(); changed(); toast(`${made.name}: an original palette, made just now.`);
    } catch (err) { toast(err.message); }
  };

  // ---------- Sections tab ----------
  function rowsToText(rows) { return (rows || []).map((r) => r.join(" | ")).join("\n"); }
  function textToRows(text, width) {
    return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const cells = l.split("|").map((c) => c.trim());
      while (cells.length < width) cells.push("");
      return cells.slice(0, width);
    });
  }
  function drawSections(open = new Set()) {
    const list = $("sectionList");
    list.replaceChildren();
    spec.sections.forEach((s, i) => {
      const info = lib.sections[s.kind];
      const variant = el("select", { "aria-label": "Style" }, info.variants.map((v) => el("option", { value: v, text: v })));
      variant.value = s.variant;
      variant.onchange = () => { s.variant = variant.value; changed(); };
      const body = el("div", { class: "body" });
      body.hidden = !open.has(i);
      for (const [name, type] of Object.entries(info.fields)) {
        const label = name.replace(/_/g, " ");
        if (typeof type === "object") {
          const ta = el("textarea", { rows: "5" });
          ta.value = rowsToText(s.fields[name]);
          ta.oninput = () => { s.fields[name] = textToRows(ta.value, type.columns.length); changed(); };
          body.append(el("label", {}, [`${label} (one per line: ${type.columns.join(" | ")})`, ta]));
        } else if (type === "long") {
          const ta = el("textarea", { rows: "3" }); ta.value = s.fields[name] || "";
          ta.oninput = () => { s.fields[name] = ta.value; changed(); };
          body.append(el("label", {}, [label, ta]));
        } else {
          const input = el("input", { value: s.fields[name] || "" });
          input.oninput = () => { s.fields[name] = input.value; changed(); };
          body.append(el("label", {}, [label, input]));
        }
      }
      const move = (d) => () => {
        const j = i + d; if (j < 0 || j >= spec.sections.length) return;
        [spec.sections[i], spec.sections[j]] = [spec.sections[j], spec.sections[i]]; drawSections(); changed();
      };
      const head = el("div", { class: "head" }, [
        el("b", { text: info.label, title: "Click to edit", onclick: () => { body.hidden = !body.hidden; } }), variant,
        el("button", { type: "button", text: "↑", title: "Move up", onclick: move(-1) }),
        el("button", { type: "button", text: "↓", title: "Move down", onclick: move(1) }),
        el("button", { type: "button", text: "✕", title: "Remove", onclick: () => { spec.sections.splice(i, 1); drawSections(); changed(); } }),
      ]);
      list.append(el("li", {}, [head, body]));
    });
  }
  $("addSection").onclick = () => {
    const kind = $("addKind").value, info = lib.sections[kind];
    const fields = Object.fromEntries(Object.entries(info.fields).map(([k, t]) => [k, typeof t === "object" ? [] : ""]));
    const footer = spec.sections.findIndex((s) => s.kind === "footer");
    const at = footer < 0 ? spec.sections.length : footer;
    spec.sections.splice(at, 0, { kind, variant: info.variants[0], fields });
    drawSections(new Set([at])); changed();
  };

  // ---------- Library tab ----------
  function drawLibrary() {
    const items = Object.entries(lib.credits || {});
    $("libraryList").replaceChildren(...(items.length ? items.map(([key, c]) => el("div", { class: "lib-item" }, [
      el("b", { text: key.replace(":", ": ") }), el("div", { class: "hint", text: `${c.licence} · ${c.source}` })]))
      : [el("p", { class: "hint", text: "Nothing added yet. Ask JARVIS: \"find a free-licence colour palette for a bakery and add it to my site library\"." })]));
  }

  function drawAll() { drawLook(); drawSections(); drawLibrary(); }

  // ---------- sites ----------
  async function loadSites(select) {
    const { sites } = await api("/orb/api/sites");
    $("sitePick").replaceChildren(...sites.map((s) => el("option", { value: s.slug, text: s.name })));
    if (!sites.length) { $("newDialog").showModal(); return; }
    await openSite(select || sites[0].slug);
  }
  async function openSite(which) {
    slug = which; $("sitePick").value = which;
    spec = await api(`/orb/api/sites/${which}`); savedJson = JSON.stringify(spec); dirty = false;
    $("saved").textContent = "";
    drawAll(); refreshPreview();
  }
  $("sitePick").onchange = async (e) => { if (dirty) await save(); openSite(e.target.value); };
  $("newSite").onclick = () => $("newDialog").showModal();
  $("cancelNew").onclick = () => $("newDialog").close();
  $("newForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const made = await api("/orb/api/sites", "POST", { name: $("newName").value, kind: $("newKind").value, description: $("newDesc").value });
      $("newDialog").close(); await loadSites(made.slug); toast(`Created ${made.name}. Change anything on the left; it saves by itself.`);
    } catch (err) { toast(err.message); }
  };
  $("openPreview").onclick = () => { if (slug) window.open(`/orb/site/${slug}`, "_blank"); };
  $("export").onclick = async () => {
    if (!slug) return;
    await save();
    try {
      const out = await api(`/orb/api/sites/${slug}/export`, "POST", {});
      const a = el("a", { href: URL.createObjectURL(new Blob([out.html], { type: "text/html" })), download: `${slug}.html` });
      document.body.append(a); a.click(); a.remove();
      toast(`Exported: ${out.file}`);
    } catch (err) { toast(err.message); }
  };
  for (const b of document.querySelectorAll(".seg button")) {
    b.onclick = () => { document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b)); $("preview").style.width = b.dataset.w; };
  }
  for (const b of document.querySelectorAll(".tabs button")) {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      for (const name of ["look", "sections", "library"]) $(`tab-${name}`).hidden = name !== b.dataset.tab;
    };
  }

  (async () => {
    try {
      lib = await api("/orb/api/sites/library");
      fillSelect($("newKind"), Object.keys(lib.starters));
      [...$("newKind").options].forEach((o) => { o.textContent = lib.starters[o.value]; });
      fillSelect($("addKind"), Object.keys(lib.sections));
      [...$("addKind").options].forEach((o) => { o.textContent = lib.sections[o.value].label; });
      await loadSites(new URLSearchParams(location.search).get("site"));
    } catch (err) { toast(err.message); }
    watch();
  })();
})();
