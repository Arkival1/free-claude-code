/* FCC Phone service worker: the app, and the on-phone engine once fetched,
   open with no connection. AI, weather, and PC calls are never cached. */
const VERSION = "2.13.0";
const CACHE = `fcc-phone-${VERSION}`;
const ENGINE_CACHE = "fcc-phone-engine-3.6.1";
// Godot's web player (about 10 MB): fetched the first time a game runs, then
// kept on the phone across app updates (js/godot.js checks its checksums).
const GODOT_CACHE = "fcc-phone-godot-4.7.2";
// FCC Linux's engine, kernel and manifest: fetched the first time it starts,
// then kept. Its system packs (linux/fs/) skip this worker: js/linuxfiles.js
// checks and keeps them itself, so they aren't stored twice.
const LINUX_CACHE = "fcc-phone-linux-2.0";
const LINUX_FILES = [
  "linux/libv86.js",
  "linux/v86.wasm",
  "linux/seabios.bin",
  "linux/vgabios.bin",
  "linux/xterm.js",
  "linux/xterm.css",
  "linux/fcc-linux.kernel",
  "linux/fcc-linux.initrd",
  "linux/fcc-linux.json",
];
const GODOT_FILES = [
  "godot/godot.js",
  "godot/godot.wasm.gz",
  "godot/godot.audio.worklet.js",
  "godot/godot.audio.position.worklet.js",
];
const SHELL = [
  "./",
  "index.html",
  "phone.css",
  "manifest.webmanifest",
  "icon-180.png",
  "icon-192.png",
  "icon-512.png",
  "vendor/wllama.min.js",
  "vendor/three/three.module.js",
  "vendor/three/three.core.js",
  "lab/kit.js",
  "lab/look3d.js",
  "lab/science.js",
  "lab/science-data.js",
  "lab/tutorials-data.js",
  "lab/circuit3d.js",
  "lab/chem3d.js",
  "lab/jarvis3d.js",
  "lab/world3d.js",
  "lab/board.js",
  "web/kit.css",
  "web/kit.js",
  "web/sections.js",
  "lab/souls/index.html",
  "lab/souls/styles.css",
  "lab/souls/game.js",
  "js/app.js",
  "js/tasks.js",
  "js/playground.js",
  "js/library.js",
  "js/lab.js",
  "js/workshop.js",
  "js/views/workshop.js",
  "js/webkit.js",
  "js/godot.js",
  "js/sha256.js",
  "js/linuxfiles.js",
  "js/linux.js",
  "js/views/linux.js",
  "js/views/godot.js",
  "godot/pack.js",
  "godot/starters.js",
  "js/views/webkit.js",
  "js/plugins.js",
  "js/apis.js",
  "js/skills.js",
  "js/agents.js",
  "js/brains.js",
  "js/engine.js",
  "js/gguf.js",
  "js/inspect.js",
  "js/learn.js",
  "js/orb.js",
  "js/photos.js",
  "js/polish.js",
  "js/projects.js",
  "js/rooms.js",
  "js/state.js",
  "js/store.js",
  "js/sync.js",
  "js/templates.js",
  "js/tools.js",
  "js/ui.js",
  "js/voice.js",
  "js/views/agents.js",
  "js/views/chat.js",
  "js/views/hud.js",
  "js/views/hq.js",
  "js/views/learn.js",
  "js/views/memory.js",
  "js/views/models.js",
  "js/views/more.js",
  "js/views/plugins.js",
  "js/views/projects.js",
  "js/views/rooms.js",
  "js/views/settings.js",
  "js/views/tasks.js",
  "js/views/playground.js",
  "js/views/library.js",
  "js/views/lab.js",
  "js/views/todos.js",
  "js/views/trade.js",
];
// The engine's large files come from jsDelivr once, then stay on the phone.
const ENGINE_PREFIX = "https://cdn.jsdelivr.net/npm/@wllama/";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith("fcc-phone-") && ![CACHE, ENGINE_CACHE, GODOT_CACHE, LINUX_CACHE].includes(name))
            .map((name) => caches.delete(name))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (request.url.startsWith(ENGINE_PREFIX)) {
    event.respondWith(
      caches.open(ENGINE_CACHE).then((cache) =>
        cache.match(request).then(
          (cached) =>
            cached ||
            fetch(request).then((response) => {
              if (response.ok) cache.put(request, response.clone());
              return response;
            })
        )
      )
    );
    return;
  }
  if (url.origin !== self.location.origin || url.pathname.includes("/studio/api/") || url.pathname.includes("/linux/fs/")) return;
  const heavy = GODOT_FILES.some((name) => url.pathname.endsWith(`/${name}`)) ? GODOT_CACHE : LINUX_FILES.some((name) => url.pathname.endsWith(`/${name}`)) ? LINUX_CACHE : "";
  if (heavy) {
    event.respondWith(
      caches.open(heavy).then((cache) =>
        cache.match(request, { ignoreSearch: true }).then(
          (cached) =>
            cached ||
            fetch(request).then((response) => {
              if (response.ok) cache.put(request, response.clone());
              return response;
            })
        )
      )
    );
    return;
  }
  // The newest app when online; the saved copy when not.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() =>
        caches
          .match(request, { ignoreSearch: true })
          .then((cached) => cached || caches.match("index.html"))
          .then((cached) => cached || Response.error())
      )
  );
});
