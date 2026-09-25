"""Starter projects the Builder begins from: correct, mobile-first, and small."""

from collections.abc import Mapping
from string import Template

_HEAD = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <meta name="description" content="$title">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✨</text></svg>">
  <link rel="stylesheet" href="styles.css">
</head>
"""

_BASE_CSS = """*, *::before, *::after { box-sizing: border-box; }
:root {
  --bg: #0f172a;
  --surface: #1e293b;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --accent: #38bdf8;
  --radius: 14px;
  --gap: clamp(16px, 4vw, 32px);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  line-height: 1.6;
  color-scheme: dark;
}
body { margin: 0; background: var(--bg); color: var(--text); }
img, svg { max-width: 100%; display: block; }
a { color: var(--accent); transition: color 0.2s, opacity 0.2s; }
a:hover { opacity: 0.8; }
button, input, select, textarea { font: inherit; }
.container { width: min(1100px, 100% - 2 * var(--gap)); margin-inline: auto; }
.button {
  display: inline-block; padding: 12px 22px; border: 0; border-radius: 999px;
  background: var(--accent); color: #04121c; font-weight: 700; text-decoration: none;
  cursor: pointer; min-height: 44px; transition: transform 0.15s, filter 0.2s;
}
.button:hover { filter: brightness(1.1); transform: translateY(-1px); }
.button:focus-visible, a:focus-visible, button:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.card { background: var(--surface); border-radius: var(--radius); padding: var(--gap); }
.grid { display: grid; gap: var(--gap); grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.muted { color: var(--muted); }
"""

_WEBSITE = {
    "index.html": _HEAD
    + """<body>
  <header class="site-header">
    <div class="container nav">
      <a class="brand" href="#top" id="top">$title</a>
      <button class="nav-toggle" aria-expanded="false" aria-controls="menu">Menu</button>
      <nav id="menu" class="menu" aria-label="Main">
        <a href="#about">About</a>
        <a href="#services">Services</a>
        <a href="#contact">Contact</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="hero container">
      <h1>$title</h1>
      <p class="muted">A short line that says what this is and who it is for.</p>
      <a class="button" href="#contact">Get in touch</a>
    </section>
    <section id="about" class="container section">
      <h2>About</h2>
      <p>Tell the story here.</p>
    </section>
    <section id="services" class="container section">
      <h2>Services</h2>
      <div class="grid">
        <article class="card"><h3>First</h3><p class="muted">What it is.</p></article>
        <article class="card"><h3>Second</h3><p class="muted">What it is.</p></article>
        <article class="card"><h3>Third</h3><p class="muted">What it is.</p></article>
      </div>
    </section>
    <section id="contact" class="container section">
      <h2>Contact</h2>
      <form class="card contact" id="contact-form">
        <label>Name <input name="name" required autocomplete="name"></label>
        <label>Email <input name="email" type="email" required autocomplete="email"></label>
        <label>Message <textarea name="message" rows="4" required></textarea></label>
        <button class="button" type="submit">Send</button>
        <p class="muted" id="form-status" role="status"></p>
      </form>
    </section>
  </main>
  <footer class="container footer muted">&copy; <span id="year"></span> $title</footer>
  <script src="app.js"></script>
</body>
</html>
""",
    "styles.css": _BASE_CSS
    + """.site-header { position: sticky; top: 0; background: rgb(15 23 42 / 0.9); backdrop-filter: blur(8px); z-index: 10; }
.nav { display: flex; align-items: center; justify-content: space-between; min-height: 64px; }
.brand { font-weight: 800; text-decoration: none; color: var(--text); }
.menu { display: flex; gap: 20px; }
.menu a { text-decoration: none; color: var(--text); }
.nav-toggle { display: none; background: none; color: var(--text); border: 1px solid var(--muted); border-radius: 8px; padding: 8px 12px; min-height: 44px; }
.hero { padding-block: clamp(48px, 12vw, 120px); }
.hero h1 { font-size: clamp(2rem, 7vw, 3.6rem); line-height: 1.1; margin: 0 0 12px; }
.section { padding-block: clamp(32px, 8vw, 72px); }
.contact { display: grid; gap: 14px; max-width: 560px; }
.contact label { display: grid; gap: 6px; }
.contact input, .contact textarea { padding: 12px; border-radius: 10px; border: 1px solid #334155; background: #0b1220; color: var(--text); }
.footer { padding-block: 32px; }
@media (max-width: 640px) {
  .nav-toggle { display: block; }
  .menu { display: none; position: absolute; top: 64px; left: 0; right: 0; flex-direction: column; padding: 16px var(--gap); background: var(--bg); }
  .menu.open { display: flex; }
}
""",
    "app.js": """const toggle = document.querySelector(".nav-toggle");
const menu = document.getElementById("menu");
toggle.addEventListener("click", () => {
  const open = menu.classList.toggle("open");
  toggle.setAttribute("aria-expanded", String(open));
});
menu.addEventListener("click", (event) => {
  if (event.target.closest("a")) menu.classList.remove("open");
});

document.getElementById("year").textContent = new Date().getFullYear();

document.getElementById("contact-form").addEventListener("submit", (event) => {
  event.preventDefault();
  document.getElementById("form-status").textContent = "Thanks! We'll be in touch.";
  event.target.reset();
});
""",
    "README.md": """# $title

A mobile-first website. Open `index.html` in a browser, or use the Studio preview.

- `index.html`: the page
- `styles.css`: colors and layout (change the variables at the top)
- `app.js`: menu, contact form, and footer year
""",
}

_LANDING = {
    **_WEBSITE,
    "index.html": _HEAD
    + """<body>
  <main>
    <section class="hero container">
      <p class="eyebrow">New</p>
      <h1>$title</h1>
      <p class="muted lead">One sentence on the problem it solves and why it is better.</p>
      <div class="actions">
        <a class="button" href="#pricing">Get started</a>
        <a href="#features">See how it works</a>
      </div>
    </section>
    <section id="features" class="container section">
      <h2>Why people love it</h2>
      <div class="grid">
        <article class="card"><h3>Fast</h3><p class="muted">A benefit, not a feature.</p></article>
        <article class="card"><h3>Simple</h3><p class="muted">A benefit, not a feature.</p></article>
        <article class="card"><h3>Friendly</h3><p class="muted">A benefit, not a feature.</p></article>
      </div>
    </section>
    <section class="container section">
      <h2>What customers say</h2>
      <blockquote class="card">"It changed how I work." <cite class="muted">— A happy customer</cite></blockquote>
    </section>
    <section id="pricing" class="container section">
      <h2>Pricing</h2>
      <div class="grid">
        <article class="card"><h3>Starter</h3><p class="price">$$0</p><a class="button" href="#contact">Start free</a></article>
        <article class="card"><h3>Pro</h3><p class="price">$$9/mo</p><a class="button" href="#contact">Go Pro</a></article>
      </div>
    </section>
    <section id="contact" class="container section">
      <h2>Get early access</h2>
      <form class="card contact" id="contact-form">
        <label>Email <input name="email" type="email" required autocomplete="email"></label>
        <button class="button" type="submit">Join the list</button>
        <p class="muted" id="form-status" role="status"></p>
      </form>
    </section>
  </main>
  <footer class="container footer muted">&copy; <span id="year"></span> $title</footer>
  <script src="app.js"></script>
</body>
</html>
""",
    "styles.css": _BASE_CSS
    + """.hero { padding-block: clamp(64px, 14vw, 140px); text-align: center; }
.hero h1 { font-size: clamp(2.2rem, 8vw, 4rem); line-height: 1.05; margin: 0 0 16px; }
.eyebrow { color: var(--accent); font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
.lead { font-size: 1.2rem; max-width: 640px; margin-inline: auto; }
.actions { display: flex; gap: 20px; justify-content: center; align-items: center; flex-wrap: wrap; margin-top: 24px; }
.section { padding-block: clamp(32px, 8vw, 80px); }
.price { font-size: 2rem; font-weight: 800; margin: 8px 0 16px; }
blockquote { margin: 0; font-size: 1.2rem; }
.contact { display: grid; gap: 14px; max-width: 480px; }
.contact label { display: grid; gap: 6px; }
.contact input { padding: 12px; border-radius: 10px; border: 1px solid #334155; background: #0b1220; color: var(--text); }
.footer { padding-block: 32px; text-align: center; }
""",
    "app.js": """document.getElementById("year").textContent = new Date().getFullYear();

document.getElementById("contact-form").addEventListener("submit", (event) => {
  event.preventDefault();
  document.getElementById("form-status").textContent = "You're on the list!";
  event.target.reset();
});
""",
}

_WEBAPP = {
    "index.html": _HEAD
    + """<body>
  <main class="container app">
    <h1>$title</h1>
    <form id="add-form" class="add">
      <label class="sr-only" for="new-item">New item</label>
      <input id="new-item" placeholder="Add something…" required autocomplete="off">
      <button class="button" type="submit">Add</button>
    </form>
    <div class="filters" role="group" aria-label="Show">
      <button type="button" data-filter="all" aria-pressed="true">All</button>
      <button type="button" data-filter="open" aria-pressed="false">Open</button>
      <button type="button" data-filter="done" aria-pressed="false">Done</button>
    </div>
    <ul id="list" class="list"></ul>
    <p id="empty" class="muted">Nothing here yet.</p>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
    "styles.css": _BASE_CSS
    + """.app { max-width: 640px; padding-block: 40px; }
.add { display: flex; gap: 10px; }
.add input { flex: 1; padding: 12px; border-radius: 10px; border: 1px solid #334155; background: #0b1220; color: var(--text); min-height: 44px; }
.filters { display: flex; gap: 8px; margin: 16px 0; }
.filters button { background: var(--surface); color: var(--text); border: 0; border-radius: 999px; padding: 8px 16px; min-height: 44px; cursor: pointer; }
.filters button[aria-pressed="true"] { background: var(--accent); color: #04121c; }
.list { list-style: none; padding: 0; display: grid; gap: 8px; }
.list li { display: flex; align-items: center; gap: 12px; background: var(--surface); border-radius: 10px; padding: 10px 14px; }
.list li.done span { text-decoration: line-through; color: var(--muted); }
.list li span { flex: 1; }
.list button { background: none; border: 0; color: var(--muted); cursor: pointer; min-height: 44px; min-width: 44px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
""",
    "app.js": """// State lives in one object, is saved to the browser, and render() draws it.
const KEY = "app-items";
const state = { items: load(), filter: "all" };

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || [];
  } catch {
    return [];
  }
}

function save() {
  localStorage.setItem(KEY, JSON.stringify(state.items));
}

function render() {
  const list = document.getElementById("list");
  const shown = state.items.filter((item) =>
    state.filter === "all" ? true : state.filter === "done" ? item.done : !item.done
  );
  list.replaceChildren(
    ...shown.map((item) => {
      const row = document.createElement("li");
      row.className = item.done ? "done" : "";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = item.done;
      box.setAttribute("aria-label", `Done: ${item.text}`);
      box.addEventListener("change", () => {
        item.done = box.checked;
        save();
        render();
      });
      const text = document.createElement("span");
      text.textContent = item.text;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", `Delete ${item.text}`);
      remove.addEventListener("click", () => {
        state.items = state.items.filter((other) => other.id !== item.id);
        save();
        render();
      });
      row.append(box, text, remove);
      return row;
    })
  );
  document.getElementById("empty").hidden = shown.length > 0;
}

document.getElementById("add-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("new-item");
  const text = input.value.trim();
  if (!text) return;
  state.items.push({ id: Date.now(), text, done: false });
  input.value = "";
  save();
  render();
});

for (const button of document.querySelectorAll("[data-filter]")) {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    for (const other of document.querySelectorAll("[data-filter]")) {
      other.setAttribute("aria-pressed", String(other === button));
    }
    render();
  });
}

render();
""",
    "README.md": """# $title

A single-page app with no build step. Open `index.html` or use the Studio preview.
Items are saved in the browser (localStorage). `app.js` keeps all state in one
object and redraws with `render()`.
""",
}

_GAME = {
    "index.html": _HEAD
    + """<body>
  <main class="stage">
    <h1 class="sr-only">$title</h1>
    <div class="hud"><span>Score: <strong id="score">0</strong></span><span>Best: <strong id="best">0</strong></span></div>
    <canvas id="game" width="480" height="640" aria-label="$title game"></canvas>
    <div id="overlay" class="overlay">
      <p id="message">Tap or press Space to start</p>
    </div>
    <div class="pad" aria-label="Controls">
      <button type="button" data-key="ArrowLeft" aria-label="Left">◀</button>
      <button type="button" data-key="ArrowUp" aria-label="Up">▲</button>
      <button type="button" data-key="ArrowDown" aria-label="Down">▼</button>
      <button type="button" data-key="ArrowRight" aria-label="Right">▶</button>
    </div>
  </main>
  <script src="game.js"></script>
</body>
</html>
""",
    "styles.css": _BASE_CSS
    + """body { min-height: 100dvh; display: grid; place-items: center; touch-action: manipulation; }
.stage { position: relative; width: min(480px, 100vw); }
canvas { width: 100%; height: auto; background: #020617; border-radius: var(--radius); display: block; }
.hud { display: flex; justify-content: space-between; padding: 8px 4px; }
.overlay { position: absolute; inset: 40px 0 72px; display: grid; place-items: center; text-align: center; pointer-events: none; font-size: 1.3rem; }
.overlay[hidden] { display: none; }
.pad { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 8px; }
.pad button { min-height: 56px; border-radius: 12px; border: 0; background: var(--surface); color: var(--text); font-size: 1.4rem; }
@media (hover: hover) and (pointer: fine) { .pad { display: none; } }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
""",
    "game.js": """// A fixed-step game loop: update() moves things, draw() paints them.
const canvas = document.getElementById("game");
const ctx = canvas.getContext("2d");
const W = canvas.width;
const H = canvas.height;
const keys = new Set();
const BEST_KEY = "game-best";

let state = fresh();
let running = false;
let last = 0;

function fresh() {
  return {
    player: { x: W / 2, y: H - 80, size: 28, speed: 280 },
    items: [],
    spawnIn: 0,
    score: 0,
  };
}

function start() {
  state = fresh();
  running = true;
  document.getElementById("overlay").hidden = true;
}

function gameOver() {
  running = false;
  const best = Math.max(state.score, Number(localStorage.getItem(BEST_KEY) || 0));
  localStorage.setItem(BEST_KEY, String(best));
  document.getElementById("best").textContent = best;
  document.getElementById("message").textContent = `Score ${state.score}. Tap or press Space to play again`;
  document.getElementById("overlay").hidden = false;
}

function update(dt) {
  const p = state.player;
  if (keys.has("ArrowLeft")) p.x -= p.speed * dt;
  if (keys.has("ArrowRight")) p.x += p.speed * dt;
  if (keys.has("ArrowUp")) p.y -= p.speed * dt;
  if (keys.has("ArrowDown")) p.y += p.speed * dt;
  p.x = Math.max(p.size / 2, Math.min(W - p.size / 2, p.x));
  p.y = Math.max(p.size / 2, Math.min(H - p.size / 2, p.y));

  state.spawnIn -= dt;
  if (state.spawnIn <= 0) {
    state.items.push({ x: Math.random() * (W - 20) + 10, y: -20, r: 10 + Math.random() * 12, v: 120 + state.score * 4 });
    state.spawnIn = Math.max(0.25, 0.9 - state.score * 0.01);
  }
  for (const item of state.items) item.y += item.v * dt;
  state.items = state.items.filter((item) => item.y < H + 40);

  for (const item of state.items) {
    if (Math.hypot(item.x - p.x, item.y - p.y) < item.r + p.size / 2) return gameOver();
  }
  state.scoreTime = (state.scoreTime || 0) + dt;
  if (state.scoreTime >= 0.5) {
    state.score += 1;
    state.scoreTime = 0;
  }
  document.getElementById("score").textContent = state.score;
}

function draw() {
  ctx.fillStyle = "#020617";
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#38bdf8";
  const p = state.player;
  ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
  ctx.fillStyle = "#f472b6";
  for (const item of state.items) {
    ctx.beginPath();
    ctx.arc(item.x, item.y, item.r, 0, Math.PI * 2);
    ctx.fill();
  }
}

function frame(time) {
  const dt = Math.min(0.05, (time - last) / 1000 || 0);
  last = time;
  if (running) update(dt);
  draw();
  requestAnimationFrame(frame);
}

addEventListener("keydown", (event) => {
  if (event.key === " ") {
    event.preventDefault();
    if (!running) start();
  }
  keys.add(event.key);
});
addEventListener("keyup", (event) => keys.delete(event.key));
canvas.addEventListener("pointerdown", () => {
  if (!running) start();
});
for (const button of document.querySelectorAll("[data-key]")) {
  const key = button.dataset.key;
  button.addEventListener("pointerdown", () => {
    if (!running) start();
    keys.add(key);
  });
  for (const end of ["pointerup", "pointerleave", "pointercancel"]) {
    button.addEventListener(end, () => keys.delete(key));
  }
}

document.getElementById("best").textContent = localStorage.getItem(BEST_KEY) || 0;
requestAnimationFrame(frame);
""",
    "README.md": """# $title

A canvas game with no build step. Open `index.html` or use the Studio preview.
Arrow keys (or the on-screen pad on phones) move; Space or a tap starts.

- `game.js`: `update(dt)` moves things, `draw()` paints them, `frame()` runs the loop
- The best score is saved in the browser
""",
}

_PYTHON_TOOL = {
    "main.py": '''"""$title: a small command-line tool."""

import argparse


def run(name: str, times: int) -> list[str]:
    """Do the work; kept separate from the command line so it is easy to test."""
    return [f"Hello, {name}!" for _ in range(times)]


def main() -> None:
    parser = argparse.ArgumentParser(description="$title")
    parser.add_argument("name", help="who to greet")
    parser.add_argument("--times", type=int, default=1, help="how many times")
    args = parser.parse_args()
    for line in run(args.name, args.times):
        print(line)


if __name__ == "__main__":
    main()
''',
    "test_main.py": """from main import run


def test_run_repeats():
    assert run("Ada", 2) == ["Hello, Ada!", "Hello, Ada!"]
""",
    "requirements.txt": "pytest\n",
    "README.md": """# $title

```
python main.py Ada --times 2
pip install -r requirements.txt
python -m pytest
```
""",
}

_PYTHON_WEB = {
    "app.py": '''"""$title: a small web API with a page, built on FastAPI."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="$title")
ITEMS: dict[int, str] = {}


class Item(BaseModel):
    text: str


@app.get("/")
def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/items")
def list_items() -> dict[int, str]:
    return ITEMS


@app.post("/api/items")
def add_item(item: Item) -> dict[str, int]:
    new_id = max(ITEMS, default=0) + 1
    ITEMS[new_id] = item.text
    return {"id": new_id}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int) -> dict[str, bool]:
    if item_id not in ITEMS:
        raise HTTPException(status_code=404, detail="No such item")
    del ITEMS[item_id]
    return {"deleted": True}
''',
    "index.html": """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✨</text></svg>">
  <style>
    body { font-family: system-ui, sans-serif; line-height: 1.6; margin: 0; background: #0f172a; color: #e2e8f0; }
    main { width: min(720px, 100% - 32px); margin: 40px auto; }
    button { padding: 10px 18px; border: 0; border-radius: 999px; background: #38bdf8; color: #04121c; font-weight: 700; cursor: pointer; transition: filter 0.2s; }
    button:hover { filter: brightness(1.1); }
    input { padding: 10px; border-radius: 8px; border: 1px solid #334155; background: #0b1220; color: inherit; }
    :focus-visible { outline: 3px solid #38bdf8; outline-offset: 2px; }
    @media (max-width: 480px) { main { margin: 20px auto; } }
  </style>
</head>
<body>
  <main>
  <header><h1>$title</h1></header>
  <form id="form"><input id="text" required aria-label="New item"><button>Add</button></form>
  <ul id="items"></ul>
  </main>
  <footer></footer>
  <script>
    async function load() {
      const items = await (await fetch("/api/items")).json();
      document.getElementById("items").replaceChildren(
        ...Object.values(items).map((text) => Object.assign(document.createElement("li"), { textContent: text }))
      );
    }
    document.getElementById("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.getElementById("text");
      await fetch("/api/items", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: input.value }) });
      input.value = "";
      load();
    });
    load();
  </script>
</body>
</html>
""",
    "requirements.txt": "fastapi\nuvicorn\n",
    "README.md": """# $title

```
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open http://127.0.0.1:8000. The API is at `/api/items`; docs at `/docs`.
""",
}

_NODE_API = {
    "server.js": """// $title: a small Node web server with a JSON API and no dependencies.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const items = [];
const page = fs.readFileSync(path.join(__dirname, "index.html"));

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "content-type": type });
  res.end(type === "application/json" ? JSON.stringify(body) : body);
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/") return send(res, 200, page, "text/html");
  if (req.method === "GET" && req.url === "/api/items") return send(res, 200, items);
  if (req.method === "POST" && req.url === "/api/items") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      try {
        const { text } = JSON.parse(raw);
        if (!text) return send(res, 400, { error: "text is required" });
        items.push(text);
        send(res, 201, { count: items.length });
      } catch {
        send(res, 400, { error: "invalid JSON" });
      }
    });
    return;
  }
  send(res, 404, { error: "not found" });
});

const port = Number(process.env.PORT) || 3000;
server.listen(port, () => console.log(`Listening on http://localhost:${port}`));
""",
    "index.html": """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✨</text></svg>">
  <style>
    body { font-family: system-ui, sans-serif; line-height: 1.6; margin: 0; background: #0f172a; color: #e2e8f0; }
    main { width: min(720px, 100% - 32px); margin: 40px auto; }
    button { padding: 10px 18px; border: 0; border-radius: 999px; background: #38bdf8; color: #04121c; font-weight: 700; cursor: pointer; transition: filter 0.2s; }
    button:hover { filter: brightness(1.1); }
    input { padding: 10px; border-radius: 8px; border: 1px solid #334155; background: #0b1220; color: inherit; }
    :focus-visible { outline: 3px solid #38bdf8; outline-offset: 2px; }
    @media (max-width: 480px) { main { margin: 20px auto; } }
  </style>
</head>
<body>
  <header></header>
  <main>
    <h1>$title</h1>
    <p>The API is at <code>/api/items</code>.</p>
  </main>
  <footer></footer>
</body>
</html>
""",
    "package.json": """{
  "name": "$slug",
  "version": "1.0.0",
  "private": true,
  "scripts": { "start": "node server.js" }
}
""",
    "README.md": """# $title

```
npm start
```

Then open http://localhost:3000.
""",
}

STARTER_TEXT: tuple[str, ...] = (
    "A short line that says what this is and who it is for.",
    "Tell the story here.",
    "What it is.",
    "One sentence on the problem it solves and why it is better.",
    "A benefit, not a feature.",
    "It changed how I work.",
    "A happy customer",
)
"""Placeholder copy in the templates, which a finished project replaces."""

TEMPLATES: Mapping[str, tuple[str, Mapping[str, str]]] = {
    "website": ("A multi-section website with a phone menu and contact form", _WEBSITE),
    "landing": (
        "A landing page: hero, features, testimonial, pricing, signup",
        _LANDING,
    ),
    "webapp": ("A single-page app with saved state (starts as a to-do list)", _WEBAPP),
    "game": ("A canvas game with a game loop, score, and touch controls", _GAME),
    "python-tool": ("A Python command-line tool with a test", _PYTHON_TOOL),
    "python-web": ("A Python web API with a page (FastAPI)", _PYTHON_WEB),
    "node-api": ("A Node web server with a JSON API, no dependencies", _NODE_API),
}


def template_files(name: str, title: str) -> dict[str, str]:
    """The files of one starter project, filled in with the project's title."""
    if name not in TEMPLATES:
        raise ValueError(
            f"No template called {name!r}. Pick one of: {', '.join(TEMPLATES)}."
        )
    slug = "-".join(title.lower().split()) or "project"
    values = {"title": title.replace("<", "").replace(">", ""), "slug": slug}
    return {
        path: Template(text).safe_substitute(values)
        for path, text in TEMPLATES[name][1].items()
    }
