// Offline play: serve the game from the phone's cache, and refresh the cache
// in the background so the next launch gets any update.
const CACHE = "hearthbox-v2";
const FILES = [
  "./",
  "index.html",
  "style.css",
  "manifest.webmanifest",
  "icon-180.png",
  "icon-192.png",
  "icon-512.png",
  "js/main.js",
  "js/sim.js",
  "js/agent.js",
  "js/talk.js",
  "js/social.js",
  "js/animals.js",
  "js/world.js",
  "js/render.js",
  "js/ui.js",
  "js/ai.js",
  "js/data.js",
  "js/rng.js",
  "js/store.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("hearthbox-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  // Only the game's own files; AI voice calls and anything else go straight to the network.
  if (req.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req, { ignoreSearch: true });
      const fresh = fetch(req)
        .then((res) => {
          if (res.ok) c.put(req, res.clone());
          return res;
        })
        .catch(() => hit);
      return hit || fresh;
    }),
  );
});
