/* Minimal service worker: makes the app installable and caches the shell.
 * API calls are never cached — a stale reply would be worse than none. */

const SHELL = "jarvis-shell-v1";
const ASSETS = ["/", "/app.css", "/app.js", "/manifest.webmanifest",
                "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Never cache the API or non-GET requests.
  if (url.pathname.startsWith("/api/") || e.request.method !== "GET") return;

  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request))
  );
});
