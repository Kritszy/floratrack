// FloraTrack service worker.
// Keeps a copy of the app page so the stock list opens even without internet.
// Plant identification (/identify) always needs the network and is never cached.
const CACHE = "floratrack-v2";
const SHELL = ["/", "/static/manifest.json", "/static/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // /identify uploads go straight to the network
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Network first (always the newest version), fall back to the saved copy when offline.
  event.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
  );
});
