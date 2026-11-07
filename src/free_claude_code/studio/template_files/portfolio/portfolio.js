(() => {
  "use strict";
  const PROJECTS = [
    { id: "terrace", kind: "home", name: "Wattle Terrace", where: "Glebe", year: 2024, area: 186, star: 8.1, wide: true, storeys: 2, roof: "saw", text: "A narrow 1890s terrace opened to the north with a sawtooth roof that pulls winter sun into the kitchen." },
    { id: "library", kind: "public", name: "Riverbank Library", where: "Parramatta", year: 2023, area: 1240, star: 7.4, storeys: 2, roof: "flat", text: "A timber reading room on stilts above the flood line, with a shaded verandah along the river." },
    { id: "studio", kind: "work", name: "Ash Street Studio", where: "Redfern", year: 2022, area: 420, star: 7.0, storeys: 3, roof: "pitch", text: "A brick warehouse kept whole and fitted with a new mezzanine of cross-laminated timber." },
    { id: "pavilion", kind: "public", name: "School Pavilion", where: "Marrickville", year: 2024, area: 560, star: 7.6, storeys: 1, roof: "pitch", text: "Four classrooms around a covered yard, cross-ventilated so they need no air-conditioning." },
    { id: "cabin", kind: "home", name: "Bush Cabin", where: "Kangaroo Valley", year: 2021, area: 74, star: 8.6, storeys: 1, roof: "skillion", text: "A one-room cabin off the grid: rainwater, solar and a slow-combustion stove." },
    { id: "office", kind: "work", name: "Harbour Workrooms", where: "Pyrmont", year: 2025, area: 2800, star: 7.2, wide: true, storeys: 5, roof: "flat", text: "Offices in recycled brick with deep window reveals that shade the glass in summer." },
  ];
  const KIND = { home: "Home", public: "Public", work: "Workplace" };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // Each project drawn as a simple elevation from its own numbers.
  function elevation(p, w = 400, h = 300) {
    let seed = [...p.id].reduce((s, c) => s + c.charCodeAt(0), 0);
    const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
    const ink = css("--ink"), brick = css("--brick"), line = css("--line"), card = css("--card");
    const ground = h * 0.82, storey = Math.min(46, (h * 0.55) / p.storeys);
    const bw = Math.min(w * 0.78, 120 + p.area ** 0.5 * 5), x0 = (w - bw) / 2, top = ground - storey * p.storeys;
    let s = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Drawing of ${p.name}">`;
    s += `<rect x="${x0}" y="${top}" width="${bw}" height="${ground - top}" fill="${card}" stroke="${ink}" stroke-width="1.5"/>`;
    // Brick coursing on the ground floor.
    for (let y = ground - storey + 6; y < ground; y += 6) s += `<line x1="${x0}" x2="${x0 + bw}" y1="${y}" y2="${y}" stroke="${line}" stroke-width="1"/>`;
    // Windows, storey by storey.
    for (let f = 0; f < p.storeys; f++) {
      const y = ground - storey * (f + 1) + storey * 0.22, n = Math.max(2, Math.round(bw / 46));
      for (let i = 0; i < n; i++) {
        const ww = (bw / n) * (0.45 + rnd() * 0.2), wx = x0 + (bw / n) * i + (bw / n - ww) / 2;
        const tall = f === 0 && i === Math.floor(n / 2);
        s += `<rect x="${wx}" y="${y}" width="${ww}" height="${tall ? storey * 0.78 : storey * 0.5}" fill="${tall ? brick : "none"}" stroke="${ink}" stroke-width="1.2" ${tall ? 'opacity="0.85"' : ""}/>`;
      }
    }
    // Roof by type.
    if (p.roof === "pitch") s += `<path d="M${x0 - 8} ${top} L${w / 2} ${top - storey * 0.9} L${x0 + bw + 8} ${top}" fill="none" stroke="${ink}" stroke-width="1.5"/>`;
    if (p.roof === "skillion") s += `<path d="M${x0 - 10} ${top - storey * 0.5} L${x0 + bw + 10} ${top + 2}" stroke="${ink}" stroke-width="2"/>`;
    if (p.roof === "saw") { const t = 4, tw = bw / t; for (let i = 0; i < t; i++) s += `<path d="M${x0 + tw * i} ${top} L${x0 + tw * i} ${top - storey * 0.6} L${x0 + tw * (i + 1)} ${top}" fill="none" stroke="${ink}" stroke-width="1.5"/>`; }
    if (p.roof === "flat") s += `<rect x="${x0 - 6}" y="${top - 6}" width="${bw + 12}" height="6" fill="${ink}"/>`;
    // Ground, a tree, a person for scale.
    s += `<line x1="0" x2="${w}" y1="${ground}" y2="${ground}" stroke="${ink}" stroke-width="1.5"/>`;
    const tx = x0 + bw + 26 < w - 20 ? x0 + bw + 26 : x0 - 26;
    s += `<line x1="${tx}" x2="${tx}" y1="${ground}" y2="${ground - 40}" stroke="${ink}"/><circle cx="${tx}" cy="${ground - 50}" r="17" fill="none" stroke="${ink}"/>`;
    s += `<circle cx="${x0 + 18}" cy="${ground - 17}" r="3" fill="${ink}"/><line x1="${x0 + 18}" x2="${x0 + 18}" y1="${ground - 14}" y2="${ground - 4}" stroke="${ink}" stroke-width="1.5"/>`;
    return s + "</svg>";
  }

  const grid = document.getElementById("grid");
  function paint() {
    grid.replaceChildren();
    for (const p of PROJECTS) {
      const b = document.createElement("button");
      b.type = "button"; b.className = `project${p.wide ? " wide" : ""}`; b.dataset.kind = p.kind;
      b.innerHTML = `<div class="art">${elevation(p, p.wide ? 640 : 400, p.wide ? 360 : 300)}</div><div class="row"><h3></h3><span></span></div>`;
      b.querySelector("h3").textContent = p.name;
      b.querySelector("span").textContent = `${p.where} · ${p.year}`;
      b.setAttribute("aria-label", `${p.name}, ${KIND[p.kind]}, ${p.where} ${p.year}: open details`);
      b.addEventListener("click", () => open(p));
      grid.append(b);
    }
    filter(current);
  }
  let current = "all";
  function filter(kind) {
    current = kind;
    for (const el of grid.children) el.hidden = kind !== "all" && el.dataset.kind !== kind;
    document.querySelectorAll("[data-filter]").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.filter === kind)));
  }
  document.querySelectorAll("[data-filter]").forEach((c) => c.addEventListener("click", () => filter(c.dataset.filter)));

  const dialog = document.getElementById("detail");
  function open(p) {
    document.getElementById("dArt").innerHTML = elevation(p, 640, 360);
    document.getElementById("dKind").textContent = `${KIND[p.kind]} · ${p.where}`;
    document.getElementById("dTitle").textContent = p.name;
    document.getElementById("dText").textContent = p.text;
    const facts = document.getElementById("dFacts");
    facts.replaceChildren();
    for (const [k, v] of [["Completed", p.year], ["Floor area", `${p.area.toLocaleString("en-AU")} m²`], ["Storeys", p.storeys], ["Energy rating", `${p.star}★ NatHERS`]]) {
      const d = document.createElement("div"); d.innerHTML = "<dt></dt><dd></dd>";
      d.querySelector("dt").textContent = k; d.querySelector("dd").textContent = v; facts.append(d);
    }
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
  }
  document.getElementById("dClose").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);
  paint();
})();
