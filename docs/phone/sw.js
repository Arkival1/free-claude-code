/* FCC Phone service worker: the app, and the on-phone engine once fetched,
   open with no connection. AI, weather, and PC calls are never cached. */
const VERSION = "2.0.0";
const CACHE = `fcc-phone-${VERSION}`;
const ENGINE_CACHE = "fcc-phone-engine-3.6.1";
const SHELL = [
  "./",
  "index.html",
  "phone.css",
  "manifest.webmanifest",
  "icon-180.png",
  "icon-192.png",
  "icon-512.png",
  "vendor/wllama.min.js",
  "js/app.js",
  "js/agents.js",
  "js/brains.js",
  "js/engine.js",
  "js/gguf.js",
  "js/learn.js",
  "js/orb.js",
  "js/projects.js",
  "js/rooms.js",
  "js/state.js",
  "js/store.js",
  "js/sync.js",
  "js/tools.js",
  "js/ui.js",
  "js/voice.js",
  "js/views/agents.js",
  "js/views/chat.js",
  "js/views/hud.js",
  "js/views/learn.js",
  "js/views/memory.js",
  "js/views/models.js",
  "js/views/more.js",
  "js/views/projects.js",
  "js/views/rooms.js",
  "js/views/settings.js",
  "js/views/todos.js",
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
            .filter((name) => name.startsWith("fcc-phone-") && name !== CACHE && name !== ENGINE_CACHE)
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
  if (url.origin !== self.location.origin || url.pathname.includes("/studio/api/")) return;
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
