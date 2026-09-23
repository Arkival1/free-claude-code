/* Studio service worker: instant launches and a readable offline screen.
   Registered only on secure origins, so plain-HTTP LAN installs skip it. */
const VERSION = "__FCC_VERSION__";
const CACHE = `studio-${VERSION}`;
const SHELL = [
  "/studio",
  `/studio/assets/${VERSION}/studio.css`,
  `/studio/assets/${VERSION}/studio.js`,
  `/studio/assets/${VERSION}/icon-180.png`,
  `/studio/assets/${VERSION}/icon-192.png`,
  "/studio/manifest.webmanifest",
];

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
        Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Live data and site previews always come from the server.
  if (url.pathname.startsWith("/studio/api/") || url.pathname.startsWith("/studio/sites/")) {
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match("/studio").then((cached) => cached || Response.error())
      )
    );
    return;
  }
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
    )
  );
});
