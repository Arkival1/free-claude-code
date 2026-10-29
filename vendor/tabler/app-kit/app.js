// Screens, the player's numbers, a leaderboard and settings, all kept on this
// device. Replace the sample numbers and names with the app's own.
(() => {
  "use strict";
  const KEY = "app-kit";
  const read = () => {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; }
  };
  const write = (data) => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch { /* private window */ }
  };
  const state = Object.assign(
    { level: 1, lives: 3, progress: 0, coins: 0, best: 0,
      board: [["Nova", 9840], ["Kai", 8710], ["Mila", 8095]],
      settings: { sound: true, vibrate: false, volume: 70, level: "normal" } },
    read()
  );

  // Screens follow the address (#home, #leaderboard, #settings).
  const screens = [...document.querySelectorAll(".screen")];
  function show() {
    const id = (location.hash || "#home").slice(1);
    const target = screens.some((s) => s.id === id) ? id : "home";
    screens.forEach((s) => { s.hidden = s.id !== target; });
    document.querySelectorAll("[data-screen-link]").forEach((a) => {
      a.classList.toggle("active", a.dataset.screenLink === target);
    });
  }
  window.addEventListener("hashchange", show);

  function paint() {
    document.getElementById("home-sub").textContent = `Level ${state.level} · ${state.lives} lives`;
    document.getElementById("home-progress").style.width = `${state.progress}%`;
    const stats = [["Coins", state.coins], ["Best score", state.best], ["Level", state.level], ["Lives", state.lives]];
    document.getElementById("stats").replaceChildren(...stats.map(([label, value]) => {
      const col = document.createElement("div");
      col.className = "col-6";
      col.innerHTML = '<div class="card card-sm"><div class="card-body"><div class="text-secondary"></div><div class="h2 m-0"></div></div></div>';
      col.querySelector(".text-secondary").textContent = label;
      col.querySelector(".h2").textContent = value.toLocaleString();
      return col;
    }));
    const rows = [...state.board, ["You", state.best]].sort((a, b) => b[1] - a[1]);
    document.getElementById("board").replaceChildren(...rows.map(([name, score], index) => {
      const row = document.createElement("div");
      row.className = "list-group-item d-flex align-items-center gap-3";
      row.innerHTML = '<span class="avatar avatar-sm"></span><span class="flex-fill"></span><strong></strong>';
      row.querySelector(".avatar").textContent = index + 1;
      row.querySelector(".flex-fill").textContent = name;
      row.querySelector("strong").textContent = score.toLocaleString();
      return row;
    }));
    const s = state.settings;
    document.getElementById("opt-sound").checked = s.sound;
    document.getElementById("opt-vibrate").checked = s.vibrate;
    document.getElementById("opt-volume").value = s.volume;
    document.getElementById("opt-level").value = s.level;
  }

  // Play: a stand-in for the real game; it earns coins and moves progress on.
  document.getElementById("play").addEventListener("click", () => {
    state.coins += 10;
    state.progress = Math.min(100, state.progress + 20);
    state.best = Math.max(state.best, state.coins * 10);
    if (state.progress === 100) { state.level += 1; state.progress = 0; }
    write(state);
    paint();
  });
  document.getElementById("save").addEventListener("click", () => {
    state.settings = {
      sound: document.getElementById("opt-sound").checked,
      vibrate: document.getElementById("opt-vibrate").checked,
      volume: Number(document.getElementById("opt-volume").value),
      level: document.getElementById("opt-level").value,
    };
    write(state);
    document.getElementById("saved").hidden = false;
  });

  // Light or dark, as the device is set.
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const theme = () => document.documentElement.setAttribute("data-bs-theme", media.matches ? "dark" : "light");
  media.addEventListener("change", theme);
  theme();
  paint();
  show();
})();
