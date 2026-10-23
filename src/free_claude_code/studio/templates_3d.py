"""The Builder's 3D starters: a landing page with a 3D hero and a live 3D
dashboard, both on the FCC web kit (fcc-kit.css and fcc-kit.js).

three.js isn't written out as template text: start_project copies Studio's
own verified copy (vendor/three in the repo) into the project's
vendor/three/ folder, so the site works offline and zips up whole.
"""

from collections.abc import Mapping
from pathlib import Path

from .templates_business import FORM_JS

LIBRARY_DIR = Path(__file__).resolve().parents[1] / "api" / "studio_static"
"""Where Studio keeps the three.js files it serves (checked against
vendor/three/SHA256SUMS by the tests)."""

THREE_FILES: Mapping[str, str] = {
    "vendor/three/three.module.js": "three.module.js",
    "vendor/three/three.core.js": "three.core.js",
    "vendor/three/OrbitControls.js": "three-orbit.js",
}
"""Project path → Studio's copy, for the templates that draw in 3D."""

THREE_LICENSE = """The MIT License

Copyright © 2010-2026 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

PLACEHOLDER_3D: tuple[str, ...] = (
    "Say what you offer in one line: who it is for, and why it is better.",
    "A clear benefit your customer cares about.",
    "Replace these with your own numbers.",
    "Tell visitors what to do next.",
    "Say what this dashboard watches, and where its numbers come from.",
    "14 Kiln Street",
    "(02) 9550 0418",
    "Bread that rose",
    "+61295500418",
    "yourbakery.example",
)
"""Placeholder copy in the 3D starters, which a finished project replaces."""

_IMPORT_MAP = """  <script type="importmap">
    {
      "imports": {
        "three": "./vendor/three/three.module.js",
        "three/addons/controls/OrbitControls.js": "./vendor/three/OrbitControls.js"
      }
    }
  </script>
"""

_HEAD_3D = (
    """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>
  <meta name="description" content="$title">
  <meta name="theme-color" content="#070b14">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>$initial</text></svg>">
  <link rel="stylesheet" href="fcc-kit.css">
  <link rel="stylesheet" href="styles.css">
"""
    + _IMPORT_MAP
    + """  <script src="fcc-kit.js" defer></script>
</head>
"""
)

KIT_CSS = """/* FCC web kit: one small stylesheet for professional pages.
   Design tokens (colours, type scale, spacing), a responsive grid, cards, a
   sticky nav that folds into a phone menu, buttons, stats, scroll reveals,
   and page transitions. Light and dark follow the visitor's setting;
   data-theme="light" or "dark" on <html> overrides it. Change the tokens
   at the top to restyle the whole site. */
*, *::before, *::after { box-sizing: border-box; }

:root {
  --bg: #070b14;
  --surface: #0f172a;
  --surface-2: #16213a;
  --text: #e6edf7;
  --muted: #93a4bd;
  --accent: #5eead4;
  --accent-2: #a78bfa;
  --accent-ink: #04201c;
  --line: rgb(148 163 184 / 0.18);
  --good: #4ade80;
  --warn: #fbbf24;
  --bad: #f87171;
  --radius: 16px;
  --gap: clamp(16px, 3.5vw, 32px);
  --step--1: clamp(0.83rem, 0.8rem + 0.15vw, 0.9rem);
  --step-0: clamp(1rem, 0.96rem + 0.2vw, 1.1rem);
  --step-1: clamp(1.25rem, 1.15rem + 0.5vw, 1.5rem);
  --step-2: clamp(1.6rem, 1.4rem + 1vw, 2.2rem);
  --step-3: clamp(2.1rem, 1.7rem + 2vw, 3.4rem);
  --step-4: clamp(2.6rem, 2rem + 3.4vw, 4.8rem);
  --ease: cubic-bezier(0.2, 0.7, 0.2, 1);
  --shadow: 0 20px 50px -24px rgb(0 0 0 / 0.65);
  color-scheme: dark;
  font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: var(--step-0);
  line-height: 1.6;
}

@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #f6f8fc;
    --surface: #ffffff;
    --surface-2: #eef2f8;
    --text: #0f172a;
    --muted: #526077;
    --accent: #0d9488;
    --accent-2: #7c3aed;
    --accent-ink: #ffffff;
    --line: rgb(15 23 42 / 0.12);
    --shadow: 0 20px 50px -28px rgb(15 23 42 / 0.35);
    color-scheme: light;
  }
}

:root[data-theme="light"] {
  --bg: #f6f8fc;
  --surface: #ffffff;
  --surface-2: #eef2f8;
  --text: #0f172a;
  --muted: #526077;
  --accent: #0d9488;
  --accent-2: #7c3aed;
  --accent-ink: #ffffff;
  --line: rgb(15 23 42 / 0.12);
  --shadow: 0 20px 50px -28px rgb(15 23 42 / 0.35);
  color-scheme: light;
}

html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased; }
img, svg, canvas, video { max-width: 100%; display: block; }
img { height: auto; }
a { color: var(--accent); text-underline-offset: 3px; }
button, input, select, textarea { font: inherit; color: inherit; }
h1, h2, h3 { line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 0.5em; }
h1 { font-size: var(--step-4); }
h2 { font-size: var(--step-3); }
h3 { font-size: var(--step-1); }
p { margin: 0 0 1em; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }

.container { width: min(1160px, 100% - 2 * var(--gap)); margin-inline: auto; }
.section { padding-block: clamp(48px, 9vw, 112px); }
.muted { color: var(--muted); }
.eyebrow { color: var(--accent); font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; font-size: var(--step--1); }
.lead { font-size: var(--step-1); color: var(--muted); max-width: 46ch; }
.grid { display: grid; gap: var(--gap); grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); }

.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: clamp(18px, 3vw, 28px);
  box-shadow: var(--shadow);
  transition: transform 0.3s var(--ease), border-color 0.3s;
}
.card:hover { border-color: color-mix(in srgb, var(--accent) 40%, var(--line)); }

.button {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  min-height: 46px; padding: 0 22px; border-radius: 999px; border: 1px solid transparent;
  background: var(--accent); color: var(--accent-ink); font-weight: 700; text-decoration: none; cursor: pointer;
  transition: transform 0.2s var(--ease), filter 0.2s;
}
.button:hover { filter: brightness(1.08); transform: translateY(-1px); }
.button.ghost { background: transparent; color: var(--text); border-color: var(--line); }

.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line); font-size: var(--step--1); color: var(--muted); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 60%, transparent); animation: kit-ping 1.6s infinite; }
@keyframes kit-ping { to { box-shadow: 0 0 0 9px transparent; } }

/* The sticky nav, folding into a menu on phones. */
.site-header { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(14px); border-bottom: 1px solid var(--line); }
.nav { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; }
.brand { font-weight: 800; color: var(--text); text-decoration: none; display: inline-flex; align-items: center; gap: 10px; min-height: 44px; }
.menu { display: flex; align-items: center; gap: 22px; }
.menu a { color: var(--text); text-decoration: none; opacity: 0.85; }
.menu a:hover { opacity: 1; }
.nav-toggle, .theme-toggle { min-height: 44px; min-width: 44px; padding: 0 12px; border-radius: 12px; border: 1px solid var(--line); background: transparent; cursor: pointer; }
.nav-toggle { display: none; }
@media (max-width: 760px) {
  .nav-toggle { display: inline-flex; align-items: center; }
  .menu { display: none; position: absolute; inset: 64px 0 auto; flex-direction: column; align-items: stretch; gap: 0; padding: 8px var(--gap) 16px; background: var(--bg); border-bottom: 1px solid var(--line); }
  .menu.open { display: flex; }
  .menu a { padding: 12px 0; }
}

/* Numbers that count up (fcc-kit.js fills data-count). */
.stat strong { display: block; font-size: var(--step-3); font-weight: 800; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); }

/* Forms. */
.form { display: grid; gap: 14px; max-width: 520px; }
.form label { display: grid; gap: 6px; color: var(--muted); }
.form input, .form textarea, .form select { min-height: 46px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface-2); }

/* Scroll reveals and tilt cards (fcc-kit.js). */
.reveal { opacity: 0; transform: translateY(18px); transition: opacity 0.7s var(--ease), transform 0.7s var(--ease); }
.reveal.is-in { opacity: 1; transform: none; }
[data-tilt] { transform-style: preserve-3d; will-change: transform; }

.footer { padding-block: 40px; border-top: 1px solid var(--line); color: var(--muted); }

/* Pages cross-fade when moving between them (browsers that support it). */
@view-transition { navigation: auto; }
::view-transition-old(root), ::view-transition-new(root) { animation-duration: 220ms; }

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .reveal { opacity: 1; transform: none; }
}
"""

KIT_JS = """// FCC web kit: small helpers every page can use, all switched off for
// visitors who prefer reduced motion.
// - .reveal elements fade up when scrolled into view
// - [data-count] numbers count up when seen (data-decimals, data-prefix, data-suffix)
// - [data-tilt] cards lean toward the pointer (mouse only)
// - .nav-toggle opens the phone menu; [data-theme-toggle] switches light/dark
// - [data-year] shows this year
(() => {
  "use strict";
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = window.matchMedia("(pointer: fine)").matches;

  function reveal() {
    const items = document.querySelectorAll(".reveal");
    if (still || !("IntersectionObserver" in window)) {
      items.forEach((item) => item.classList.add("is-in"));
      return;
    }
    const watcher = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-in");
        watcher.unobserve(entry.target);
      }
    }, { rootMargin: "0px 0px -8% 0px" });
    items.forEach((item) => watcher.observe(item));
  }

  function format(node, value) {
    const decimals = Number(node.dataset.decimals || 0);
    const text = value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    node.textContent = (node.dataset.prefix || "") + text + (node.dataset.suffix || "");
  }

  function countTo(node, target, duration = 1400) {
    const from = Number(node.dataset.shown || 0);
    node.dataset.shown = String(target);
    if (still) return format(node, target);
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      format(node, from + (target - from) * eased);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function counters() {
    const items = document.querySelectorAll("[data-count]");
    if (!("IntersectionObserver" in window)) {
      items.forEach((item) => countTo(item, Number(item.dataset.count)));
      return;
    }
    const watcher = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        countTo(entry.target, Number(entry.target.dataset.count));
        watcher.unobserve(entry.target);
      }
    });
    items.forEach((item) => watcher.observe(item));
  }

  function tilt() {
    if (still || !finePointer) return;
    for (const card of document.querySelectorAll("[data-tilt]")) {
      let frame = 0;
      card.addEventListener("pointermove", (event) => {
        const box = card.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width - 0.5;
        const y = (event.clientY - box.top) / box.height - 0.5;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          card.style.transform = "perspective(900px) rotateX(" + (-y * 7).toFixed(2) + "deg) rotateY(" + (x * 9).toFixed(2) + "deg) translateY(-3px)";
        });
      });
      card.addEventListener("pointerleave", () => {
        cancelAnimationFrame(frame);
        card.style.transform = "";
      });
    }
  }

  function menu() {
    const toggle = document.querySelector(".nav-toggle");
    const list = document.getElementById(toggle ? toggle.getAttribute("aria-controls") : "");
    if (!toggle || !list) return;
    toggle.addEventListener("click", () => {
      const open = list.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    list.addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        list.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  function theme() {
    const root = document.documentElement;
    try {
      const saved = localStorage.getItem("fcc-kit-theme");
      if (saved) root.dataset.theme = saved;
    } catch {
      /* private mode: the visitor's setting is used */
    }
    for (const button of document.querySelectorAll("[data-theme-toggle]")) {
      button.addEventListener("click", () => {
        const dark = root.dataset.theme ? root.dataset.theme === "dark" : !window.matchMedia("(prefers-color-scheme: light)").matches;
        root.dataset.theme = dark ? "light" : "dark";
        try {
          localStorage.setItem("fcc-kit-theme", root.dataset.theme);
        } catch {
          /* not remembered, still switched */
        }
        document.dispatchEvent(new CustomEvent("themechange"));
      });
    }
  }

  document.querySelectorAll("[data-year]").forEach((node) => (node.textContent = String(new Date().getFullYear())));
  reveal();
  counters();
  tilt();
  menu();
  theme();
  window.FCCKit = { still, countTo };
})();
"""

_LANDING_SCENE = """// The hero's 3D scene: a slowly turning constellation of linked points that
// leans toward the pointer. Light on any device: at most 60 frames a second
// (30 on phones and slower machines), a pixel ratio of at most 1.5, and
// nothing drawn while the hero is off-screen or the tab is hidden. Without
// WebGL, or with reduced motion, the hero keeps its CSS glow instead.
import * as THREE from "three";

const canvas = document.getElementById("hero-3d");
const hero = canvas ? canvas.closest(".hero-3d") : null;

function canDraw() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  try {
    const probe = document.createElement("canvas");
    return Boolean(probe.getContext("webgl2") || probe.getContext("webgl"));
  } catch {
    return false;
  }
}

function token(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function dotTexture() {
  const size = 64;
  const paint = document.createElement("canvas");
  paint.width = paint.height = size;
  const brush = paint.getContext("2d");
  const glow = brush.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  glow.addColorStop(0, "rgba(255,255,255,1)");
  glow.addColorStop(0.3, "rgba(255,255,255,0.8)");
  glow.addColorStop(1, "rgba(255,255,255,0)");
  brush.fillStyle = glow;
  brush.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(paint);
}

function start() {
  const small = Math.min(window.innerWidth, window.innerHeight) < 700 || (navigator.hardwareConcurrency || 8) <= 4;
  const step = 1000 / (small ? 30 : 60);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !small, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
  camera.position.set(0, 0, 9);

  const group = new THREE.Group();
  scene.add(group);
  const count = small ? 80 : 160;
  const spots = [];
  for (let index = 0; index < count; index += 1) {
    spots.push(new THREE.Vector3().randomDirection().multiplyScalar(2.4 + Math.random() * 1.8));
  }
  const positions = new Float32Array(count * 3);
  const colours = new Float32Array(count * 3);
  const paints = [new THREE.Color(), new THREE.Color()];
  const recolour = () => {
    paints[0].set(token("--accent", "#5eead4"));
    paints[1].set(token("--accent-2", "#a78bfa"));
    spots.forEach((spot, index) => {
      const colour = paints[0].clone().lerp(paints[1], (spot.y + 4) / 8);
      colours.set([colour.r, colour.g, colour.b], index * 3);
    });
    if (points) points.geometry.attributes.color.needsUpdate = true;
    if (links) links.material.color.copy(paints[0]);
  };
  spots.forEach((spot, index) => positions.set([spot.x, spot.y, spot.z], index * 3));

  // Each point links to its two nearest neighbours.
  const joined = [];
  spots.forEach((spot, index) => {
    const near = spots
      .map((other, at) => ({ at, distance: spot.distanceTo(other) }))
      .filter((other) => other.at > index && other.distance < 1.7)
      .sort((a, b) => a.distance - b.distance)
      .slice(0, 2);
    for (const other of near) joined.push(spot.x, spot.y, spot.z, spots[other.at].x, spots[other.at].y, spots[other.at].z);
  });

  let points = null;
  let links = null;
  const pointGeometry = new THREE.BufferGeometry();
  pointGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  pointGeometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
  const dot = dotTexture();
  points = new THREE.Points(pointGeometry, new THREE.PointsMaterial({ size: 0.14, map: dot, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  const linkGeometry = new THREE.BufferGeometry();
  linkGeometry.setAttribute("position", new THREE.Float32BufferAttribute(joined, 3));
  links = new THREE.LineSegments(linkGeometry, new THREE.LineBasicMaterial({ transparent: true, opacity: 0.22, depthWrite: false, blending: THREE.AdditiveBlending }));
  group.add(points, links);
  recolour();
  document.addEventListener("themechange", recolour);

  const lean = { x: 0, y: 0 };
  window.addEventListener("pointermove", (event) => {
    lean.x = (event.clientX / window.innerWidth - 0.5) * 0.6;
    lean.y = (event.clientY / window.innerHeight - 0.5) * 0.4;
  }, { passive: true });

  const resize = () => {
    const width = Math.max(1, hero.clientWidth);
    const height = Math.max(1, hero.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.position.z = width < height ? 12 : 9;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(hero);
  resize();

  let shown = true;
  let frame = 0;
  let last = 0;
  const loop = (now) => {
    frame = 0;
    if (!shown || document.hidden) return;
    frame = requestAnimationFrame(loop);
    if (last && now - last < step - 1) return;
    const seconds = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    group.rotation.y += seconds * 0.08;
    group.rotation.x += (lean.y - group.rotation.x) * 0.04;
    group.rotation.z += (-lean.x * 0.3 - group.rotation.z) * 0.04;
    const fade = Math.max(0, 1 - window.scrollY / Math.max(1, hero.clientHeight));
    renderer.domElement.style.opacity = String(0.35 + fade * 0.65);
    renderer.render(scene, camera);
  };
  const wake = () => {
    if (!frame && shown && !document.hidden) {
      last = 0;
      frame = requestAnimationFrame(loop);
    }
  };
  new IntersectionObserver((entries) => {
    shown = entries.some((entry) => entry.isIntersecting);
    wake();
  }).observe(hero);
  document.addEventListener("visibilitychange", wake);
  hero.classList.add("has-3d");
  wake();
}

if (canvas && hero && canDraw()) {
  try {
    start();
  } catch {
    hero.classList.add("no-3d");
  }
} else if (hero) {
  hero.classList.add("no-3d");
}
"""

LANDING_3D: Mapping[str, str] = {
    "index.html": _HEAD_3D
    + """<body>
  <header class="site-header">
    <div class="container nav">
      <a class="brand" href="#top">$title</a>
      <button class="nav-toggle" aria-expanded="false" aria-controls="menu">Menu</button>
      <nav id="menu" class="menu" aria-label="Main">
        <a href="#features">Features</a>
        <a href="#numbers">Numbers</a>
        <a href="#contact">Contact</a>
        <button class="theme-toggle" type="button" data-theme-toggle aria-label="Switch light or dark">◐</button>
      </nav>
    </div>
  </header>
  <main id="top">
    <section class="hero-3d">
      <canvas id="hero-3d" aria-hidden="true"></canvas>
      <div class="container hero-copy">
        <p class="eyebrow reveal">$title</p>
        <h1 class="reveal">$title</h1>
        <p class="lead reveal">Say what you offer in one line: who it is for, and why it is better.</p>
        <div class="actions reveal">
          <a class="button" href="#contact">Get started</a>
          <a class="button ghost" href="#features">See how it works</a>
        </div>
      </div>
    </section>

    <section id="features" class="section container">
      <p class="eyebrow reveal">Why it works</p>
      <h2 class="reveal">Built for people who want results</h2>
      <div class="grid">
        <article class="card reveal" data-tilt><h3>Fast</h3><p class="muted">A clear benefit your customer cares about.</p></article>
        <article class="card reveal" data-tilt><h3>Simple</h3><p class="muted">A clear benefit your customer cares about.</p></article>
        <article class="card reveal" data-tilt><h3>Trusted</h3><p class="muted">A clear benefit your customer cares about.</p></article>
      </div>
    </section>

    <section id="numbers" class="section container">
      <div class="grid stats">
        <div class="stat reveal"><strong data-count="1200" data-suffix="+">0</strong><span>Customers</span></div>
        <div class="stat reveal"><strong data-count="98" data-suffix="%">0</strong><span>Would recommend</span></div>
        <div class="stat reveal"><strong data-count="4.9" data-decimals="1">0</strong><span>Average rating</span></div>
      </div>
      <p class="muted reveal">Replace these with your own numbers.</p>
    </section>

    <section id="contact" class="section container">
      <h2 class="reveal">Ready when you are</h2>
      <p class="lead reveal">Tell visitors what to do next.</p>
      <form class="card form reveal" id="contact-form" data-endpoint="" data-email="">
        <label>Name <input id="name" name="name" required autocomplete="name"></label>
        <label>Email <input id="email" name="email" type="email" required autocomplete="email"></label>
        <label>Message <textarea id="message" name="message" rows="4" required></textarea></label>
        <button class="button" type="submit">Send</button>
        <p class="muted" id="form-status" role="status"></p>
      </form>
    </section>
  </main>
  <footer class="footer"><div class="container">&copy; <span data-year></span> $title</div></footer>
  <script src="app.js"></script>
  <script type="module" src="scene.js"></script>
</body>
</html>
""",
    "styles.css": """/* This page's own styles; the shared look is in fcc-kit.css. */
.hero-3d { position: relative; min-height: min(92vh, 860px); display: grid; align-items: center; overflow: hidden; isolation: isolate; }
.hero-3d canvas { position: absolute; inset: 0; width: 100%; height: 100%; z-index: -1; transition: opacity 0.4s; }
.hero-3d::before {
  content: ""; position: absolute; inset: -20%; z-index: -2;
  background:
    radial-gradient(40% 40% at 70% 40%, color-mix(in srgb, var(--accent-2) 32%, transparent), transparent 70%),
    radial-gradient(45% 45% at 25% 60%, color-mix(in srgb, var(--accent) 26%, transparent), transparent 70%);
  filter: blur(10px);
}
.hero-3d.has-3d::before { opacity: 0.55; }
.hero-copy { padding-block: 96px; }
.hero-copy h1 { max-width: 14ch; background: linear-gradient(120deg, var(--text), color-mix(in srgb, var(--accent) 70%, var(--text))); -webkit-background-clip: text; background-clip: text; color: transparent; }
.actions { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 28px; }
.stats { text-align: center; }
""",
    "app.js": """// The contact form (scene.js draws the 3D hero; fcc-kit.js does the rest).
"""
    + FORM_JS,
    "scene.js": _LANDING_SCENE,
    "vendor/three/LICENSE": THREE_LICENSE,
    "README.md": """# $title

A landing page with a 3D hero, built on the FCC web kit.

- `index.html`: the page (sections: hero, features, numbers, contact)
- `styles.css`: this page's styles; `fcc-kit.css`: the shared look (change
  the tokens at the top to restyle it, light and dark included)
- `fcc-kit.js`: scroll reveals, counting numbers, tilt cards, the phone
  menu, and the light/dark switch
- `scene.js`: the 3D hero (three.js); it pauses off-screen and falls back to
  a soft glow without WebGL or with reduced motion
- `app.js`: the contact form
- `vendor/three/`: three.js (MIT), kept in the project so it works offline

Open `index.html` through a web server (the Studio preview is one): the 3D
modules don't load from a plain file.
""",
}

_DASHBOARD_JS = """// The live dashboard: numbers, a 3D view of the services (glowing nodes,
// with bars for their load and light running along their links), and an
// activity log, all updated as data arrives.
//
// Data comes from data.json (or the address in data-source on <body>) every
// few seconds. While data-demo="on" (the starter's setting) the sample
// numbers drift gently so the page looks alive while it's built. To show
// real numbers, remove data-demo and point data-source at your API (same
// JSON shape as data.json), or call window.dashboard.push({...}) from your
// own code, for example from a WebSocket.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const body = document.body;
const SOURCE = body.dataset.source || "data.json";
const EVERY = Math.max(1, Number(body.dataset.every || 4)) * 1000;
const STATUS = { ok: "#4ade80", warn: "#fbbf24", down: "#f87171" };
const state = { data: null, paused: false, demo: body.dataset.demo === "on", reached: true };
const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ------------------------------------------------------------ numbers and log */

function showKpis(kpis) {
  const box = document.getElementById("kpis");
  for (const kpi of kpis) {
    let card = box.querySelector('[data-kpi="' + kpi.id + '"]');
    if (!card) {
      card = document.createElement("article");
      card.className = "card stat";
      card.dataset.kpi = kpi.id;
      card.innerHTML = '<span class="muted"></span><strong>0</strong><small class="muted"></small>';
      box.append(card);
    }
    card.querySelector("span").textContent = kpi.label;
    const number = card.querySelector("strong");
    number.dataset.suffix = kpi.unit || "";
    number.dataset.decimals = String(kpi.decimals || 0);
    if (window.FCCKit) window.FCCKit.countTo(number, Number(kpi.value), 900);
    else number.textContent = String(kpi.value) + (kpi.unit || "");
    const change = card.querySelector("small");
    change.textContent = kpi.change == null ? "" : (kpi.change >= 0 ? "▲ " : "▼ ") + Math.abs(kpi.change) + "%";
    change.className = kpi.change == null ? "muted" : kpi.change >= 0 ? "up" : "down";
  }
}

function showLog(events) {
  const list = document.getElementById("log");
  for (const event of events) {
    const item = document.createElement("li");
    item.className = "level-" + (event.level || "info");
    const when = document.createElement("time");
    when.textContent = event.at || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const text = document.createElement("span");
    text.textContent = event.text;
    item.append(when, text);
    list.prepend(item);
  }
  while (list.children.length > 30) list.lastElementChild.remove();
}

function showServicesFlat(services) {
  const box = document.getElementById("services-flat");
  box.replaceChildren(
    ...services.map((service) => {
      const row = document.createElement("div");
      row.className = "service-row";
      row.innerHTML = '<span></span><div class="bar"><i></i></div><strong></strong>';
      row.querySelector("span").textContent = service.label;
      const fill = row.querySelector("i");
      fill.style.width = Math.max(2, Math.min(100, service.load)) + "%";
      fill.style.background = STATUS[service.status] || STATUS.ok;
      row.querySelector("strong").textContent = Math.round(service.load) + "%";
      return row;
    })
  );
}

/* ------------------------------------------------------------ the 3D view */

const view = (() => {
  const host = document.getElementById("dash-3d");
  if (!host || still) return null;
  let renderer;
  try {
    const probe = document.createElement("canvas");
    if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) return null;
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  host.append(renderer.domElement);
  host.classList.add("has-3d");
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 6, 9);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.6;
  controls.maxPolarAngle = Math.PI * 0.48;
  if (!window.matchMedia("(pointer: fine)").matches) {
    controls.enableRotate = false;
    controls.enableZoom = false;
    renderer.domElement.style.touchAction = "pan-y";
  }
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const lamp = new THREE.PointLight(0xffffff, 30, 30);
  lamp.position.set(0, 6, 0);
  scene.add(lamp);
  const floor = new THREE.PolarGridHelper(5, 12, 4, 64, 0x334155, 0x1e293b);
  scene.add(floor);

  const nodes = new Map();
  const lines = [];
  const pulses = [];
  const ball = new THREE.SphereGeometry(0.32, 24, 16);
  const column = new THREE.CylinderGeometry(0.16, 0.16, 1, 16);
  const spark = new THREE.SphereGeometry(0.09, 10, 8);

  function layout(services, links) {
    for (const node of nodes.values()) {
      scene.remove(node.group);
      node.orb.material.dispose();
      node.bar.material.dispose();
    }
    nodes.clear();
    for (const line of lines) {
      scene.remove(line);
      line.geometry.dispose();
      line.material.dispose();
    }
    lines.length = 0;
    services.forEach((service, index) => {
      const angle = (index / services.length) * Math.PI * 2;
      const group = new THREE.Group();
      group.position.set(Math.cos(angle) * 3.4, 0, Math.sin(angle) * 3.4);
      const colour = new THREE.Color(STATUS[service.status] || STATUS.ok);
      const orb = new THREE.Mesh(ball, new THREE.MeshStandardMaterial({ color: 0x0f172a, emissive: colour, emissiveIntensity: 0.9 }));
      const bar = new THREE.Mesh(column, new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.35, transparent: true, opacity: 0.8 }));
      group.add(orb, bar);
      scene.add(group);
      nodes.set(service.id, { group, orb, bar, height: 0.1, want: 0.1, colour });
    });
    for (const [from, to] of links) {
      const a = nodes.get(from);
      const b = nodes.get(to);
      if (!a || !b) continue;
      const geometry = new THREE.BufferGeometry().setFromPoints([a.group.position.clone().setY(0.4), b.group.position.clone().setY(0.4)]);
      const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0x64748b, transparent: true, opacity: 0.5 }));
      line.userData = { from, to };
      lines.push(line);
      scene.add(line);
    }
  }

  function update(services) {
    for (const service of services) {
      const node = nodes.get(service.id);
      if (!node) continue;
      node.want = 0.1 + (Math.max(0, Math.min(100, service.load)) / 100) * 2.6;
      node.colour.set(STATUS[service.status] || STATUS.ok);
      node.orb.material.emissive.copy(node.colour);
      node.bar.material.color.copy(node.colour);
      node.bar.material.emissive.copy(node.colour);
    }
  }

  // Light runs from a service to everything it links to.
  function ping(serviceId) {
    const origin = nodes.get(serviceId);
    if (!origin) return;
    for (const line of lines) {
      const { from, to } = line.userData;
      if (from !== serviceId && to !== serviceId) continue;
      const start = origin.group.position.clone().setY(0.4);
      const end = nodes.get(from === serviceId ? to : from).group.position.clone().setY(0.4);
      const dot = new THREE.Mesh(spark, new THREE.MeshBasicMaterial({ color: origin.colour }));
      scene.add(dot);
      pulses.push({ dot, start, end, t: 0 });
    }
  }

  const resize = () => {
    const width = Math.max(1, host.clientWidth);
    const height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.position.setLength(width < height ? 13 : 10);
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(host);
  resize();

  let shown = true;
  let frame = 0;
  let last = 0;
  const loop = (now) => {
    frame = 0;
    if (!shown || document.hidden) return;
    frame = requestAnimationFrame(loop);
    if (last && now - last < 1000 / 45) return;
    const seconds = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    for (const node of nodes.values()) {
      node.height += (node.want - node.height) * Math.min(1, seconds * 3);
      node.bar.scale.y = node.height;
      node.bar.position.y = node.height / 2;
      node.orb.position.y = node.height + 0.35;
    }
    for (let index = pulses.length - 1; index >= 0; index -= 1) {
      const pulse = pulses[index];
      pulse.t += seconds * 0.9;
      if (pulse.t >= 1) {
        scene.remove(pulse.dot);
        pulse.dot.material.dispose();
        pulses.splice(index, 1);
        continue;
      }
      pulse.dot.position.lerpVectors(pulse.start, pulse.end, pulse.t);
    }
    controls.update(seconds);
    renderer.render(scene, camera);
  };
  const wake = () => {
    if (!frame && shown && !document.hidden) {
      last = 0;
      frame = requestAnimationFrame(loop);
    }
  };
  new IntersectionObserver((entries) => {
    shown = entries.some((entry) => entry.isIntersecting);
    wake();
  }).observe(host);
  document.addEventListener("visibilitychange", wake);
  wake();
  return { layout, update, ping };
})();

/* ------------------------------------------------------------ data */

let shape = "";

function show(data) {
  state.data = data;
  showKpis(data.kpis || []);
  showServicesFlat(data.services || []);
  const key = (data.services || []).map((service) => service.id).join(",");
  if (view && key !== shape) {
    shape = key;
    view.layout(data.services || [], data.links || []);
  }
  if (view) view.update(data.services || []);
  const events = data.events || [];
  showLog(events);
  if (view) for (const event of events) if (event.service) view.ping(event.service);
  document.getElementById("updated").textContent = "Updated " + new Date().toLocaleTimeString();
  document.getElementById("mode").textContent = state.demo ? "Demo data" : state.reached ? "Live" : "Can't reach the data";
}

function demo(previous) {
  const data = JSON.parse(JSON.stringify(previous));
  for (const kpi of data.kpis) {
    const move = (Math.random() - 0.45) * 0.04;
    kpi.value = Math.max(0, Number((kpi.value * (1 + move)).toFixed(kpi.decimals || 0)));
    if (kpi.unit === "%") kpi.value = Math.min(100, kpi.value);
    kpi.change = Number((move * 100).toFixed(1));
  }
  for (const service of data.services) {
    service.load = Math.max(3, Math.min(99, service.load + (Math.random() - 0.5) * 14));
    service.status = service.load > 90 ? "down" : service.load > 75 ? "warn" : "ok";
  }
  const busy = data.services[Math.floor(Math.random() * data.services.length)];
  data.events = Math.random() < 0.7 ? [{ text: busy.label + " handled a burst of requests", service: busy.id, level: busy.status === "ok" ? "info" : "warn" }] : [];
  return data;
}

async function read() {
  if (state.paused) return;
  if (state.demo && state.data) {
    show(demo(state.data));
    return;
  }
  try {
    const response = await fetch(SOURCE, { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    state.reached = true;
    show(await response.json());
  } catch {
    state.reached = false;
    document.getElementById("mode").textContent = "Can't reach the data";
  }
}

window.dashboard = {
  push(data) {
    state.demo = false;
    state.reached = true;
    show({ ...(state.data || {}), ...data });
  },
  pause() {
    state.paused = true;
  },
  resume() {
    state.paused = false;
  },
};

const pause = document.getElementById("pause");
pause.addEventListener("click", () => {
  state.paused = !state.paused;
  pause.textContent = state.paused ? "Resume" : "Pause";
  pause.setAttribute("aria-pressed", String(state.paused));
});

read();
setInterval(read, EVERY);
"""

DASHBOARD_3D: Mapping[str, str] = {
    "index.html": _HEAD_3D
    + """<body data-source="data.json" data-every="4" data-demo="on">
  <header class="site-header">
    <div class="container nav">
      <a class="brand" href="#top"><span class="dot" aria-hidden="true"></span>$title</a>
      <div class="menu-tools">
        <span class="badge"><span id="mode">Live</span> · <span id="updated">Starting…</span></span>
        <button class="button ghost" id="pause" type="button" aria-pressed="false">Pause</button>
        <button class="theme-toggle" type="button" data-theme-toggle aria-label="Switch light or dark">◐</button>
      </div>
    </div>
  </header>
  <main id="top" class="container dash">
    <p class="lead dash-intro">Say what this dashboard watches, and where its numbers come from.</p>
    <section class="kpis" id="kpis" aria-label="Key numbers"></section>
    <section class="card panel-3d" aria-label="Services">
      <div class="panel-head"><h2>Services</h2><p class="muted">Height shows load; light runs along the links as work moves.</p></div>
      <div id="dash-3d" class="dash-3d"></div>
      <div id="services-flat" class="services-flat"></div>
    </section>
    <section class="card panel-log" aria-label="Activity">
      <div class="panel-head"><h2>Activity</h2></div>
      <ol id="log" class="log" aria-live="polite"></ol>
    </section>
  </main>
  <footer class="footer"><div class="container">&copy; <span data-year></span> $title</div></footer>
  <script type="module" src="dashboard.js"></script>
</body>
</html>
""",
    "styles.css": """/* This dashboard's own layout; the shared look is in fcc-kit.css. */
.menu-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.dash { display: grid; gap: var(--gap); padding-block: var(--gap); grid-template-columns: minmax(0, 1fr); }
.dash-intro { margin: 0; }
.kpis { display: grid; gap: var(--gap); grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr)); }
.kpis .stat { display: grid; gap: 4px; }
.kpis .stat strong { font-size: var(--step-2); }
.kpis .up { color: var(--good); }
.kpis .down { color: var(--bad); }
.panel-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; }
.panel-head h2 { font-size: var(--step-1); margin: 0; }
.panel-head p { margin: 0; }
.dash-3d { position: relative; height: clamp(300px, 46vh, 520px); margin-top: 12px; border-radius: 12px; background: radial-gradient(circle at 50% 60%, var(--surface-2), transparent 70%); }
.dash-3d canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.dash-3d:not(.has-3d) { display: none; }
.services-flat { display: grid; gap: 10px; margin-top: 12px; }
.dash-3d.has-3d + .services-flat { display: none; }
.service-row { display: grid; grid-template-columns: 110px minmax(0, 1fr) 48px; gap: 10px; align-items: center; }
.service-row .bar { height: 10px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
.service-row .bar i { display: block; height: 100%; border-radius: 999px; transition: width 0.6s var(--ease); }
.log { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 8px; max-height: 420px; overflow: auto; }
.log li { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 10px; padding: 8px 10px; border-radius: 10px; background: var(--surface-2); animation: log-in 0.4s var(--ease); }
.log time { color: var(--muted); font-variant-numeric: tabular-nums; }
.log .level-warn { box-shadow: inset 3px 0 0 var(--warn); }
.log .level-error { box-shadow: inset 3px 0 0 var(--bad); }
@keyframes log-in { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
@media (min-width: 1000px) {
  .dash { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
  .kpis, .dash-intro { grid-column: 1 / -1; }
}
""",
    "dashboard.js": _DASHBOARD_JS,
    "data.json": """{
  "kpis": [
    { "id": "visitors", "label": "Visitors today", "value": 1284 },
    { "id": "orders", "label": "Orders", "value": 86 },
    { "id": "revenue", "label": "Revenue", "value": 4210, "unit": " AUD" },
    { "id": "uptime", "label": "Uptime", "value": 99.9, "unit": "%", "decimals": 1 }
  ],
  "services": [
    { "id": "web", "label": "Website", "load": 38, "status": "ok" },
    { "id": "api", "label": "API", "load": 52, "status": "ok" },
    { "id": "db", "label": "Database", "load": 61, "status": "ok" },
    { "id": "jobs", "label": "Background jobs", "load": 27, "status": "ok" },
    { "id": "mail", "label": "Email", "load": 12, "status": "ok" }
  ],
  "links": [["web", "api"], ["api", "db"], ["api", "jobs"], ["jobs", "mail"], ["jobs", "db"]],
  "events": [{ "text": "Dashboard started", "service": "web", "level": "info" }]
}
""",
    "vendor/three/LICENSE": THREE_LICENSE,
    "README.md": """# $title

A live dashboard with a 3D view, built on the FCC web kit.

- `index.html`: the layout (numbers, the 3D services view, the activity log)
- `dashboard.js`: reads the data and draws everything (three.js); it pauses
  off-screen, and shows plain bars without WebGL or with reduced motion
- `data.json`: the data's shape. While `data-demo="on"` (on `<body>`) the
  sample numbers drift so the page looks alive. For real numbers, remove
  `data-demo`, point `data-source` at your own API that answers the same
  JSON, and set `data-every` (seconds between reads); or call
  `window.dashboard.push({...})` from your code (a WebSocket, say).
- `styles.css` and `fcc-kit.css`: the look (tokens at the top of the kit)
- `vendor/three/`: three.js (MIT), kept in the project so it works offline

Open it through a web server (the Studio preview is one): the 3D modules
and data.json don't load from a plain file.
""",
}

KIT_FILES: Mapping[str, str] = {"fcc-kit.css": KIT_CSS, "fcc-kit.js": KIT_JS}
"""The web kit, part of every 3D starter."""

SHOP_DIR = Path(__file__).resolve().parent / "template_files" / "3d-shop"
SHOP_3D: Mapping[str, str] = {
    **{
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(SHOP_DIR.iterdir())
        if path.is_file()
    },
    "vendor/three/LICENSE": THREE_LICENSE,
}
"""A shop or bakery site with a live 3D product scene: products built from
shapes that turn by hand, card photos rendered from the same models that
tilt and float, a step-by-step process, hours and an order form (its own
design tokens; three.js from the project's copy)."""

SHOP_LIBRARIES: Mapping[str, str] = {
    path: source
    for path, source in THREE_FILES.items()
    if not path.endswith("OrbitControls.js")
}
"""The 3D shop turns its scene by hand, so it needs no OrbitControls."""
