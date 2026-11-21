/* KathaPulse AI — offline shell service worker.
 *
 * Goal: a rural pharmacy with one bar of signal should still get an instant
 * first paint and the last-known taxonomy, instead of a white screen.
 *
 * Strategy
 * --------
 * * Navigation ("/"): network-first, fall back to the cached shell. A deploy is
 *   therefore visible immediately on a good connection, and the app still opens
 *   with no connection at all.
 * * Static assets + /taxonomy.json: stale-while-revalidate. The cached copy
 *   paints instantly, the fresh copy lands in the background for next time.
 * * Everything else, and every non-GET request: untouched. Verification POSTs
 *   carry a photo and must never be cached, replayed or queued.
 *
 * The Cache API is client storage, not server persistence: nothing here leaves
 * the phone, and no scan result or image is ever stored. Bump CACHE_VERSION on
 * any asset change so the old copy is dropped on activate.
 */

const CACHE_VERSION = "kathapulse-v1";
const SHELL_URL = "/";
const PRECACHE = [
  SHELL_URL,
  "/static/css/styles.css",
  "/static/js/state.js",
  "/static/js/capture.js",
  "/static/js/speech.js",
  "/static/js/app.js",
  "/static/favicon.svg",
  "/taxonomy.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_VERSION);
      // addAll() rejects the whole batch if one URL fails; add individually so
      // a single 404 cannot leave the app with no cache at all.
      await Promise.all(
        PRECACHE.map((url) =>
          cache.add(new Request(url, { cache: "reload" })).catch(() => undefined)
        )
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.filter((name) => name !== CACHE_VERSION).map((name) => caches.delete(name))
      );
      await self.clients.claim();
    })()
  );
});

function isCacheableAsset(url) {
  return url.pathname.startsWith("/static/") || url.pathname === "/taxonomy.json";
}

async function networkFirstNavigation(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) cache.put(SHELL_URL, fresh.clone());
    return fresh;
  } catch (err) {
    const cached = (await cache.match(SHELL_URL)) || (await cache.match("/static/index.html"));
    if (cached) return cached;
    return new Response(
      "<!doctype html><meta charset=utf-8><title>KathaPulse AI</title>" +
        "<body style='font:18px system-ui;background:#060a0f;color:#e8f1f8;padding:24px'>" +
        "<h1>ഓഫ്‌ലൈൻ / Offline</h1><p>ഇന്റർനെറ്റ് ഇല്ല. വീണ്ടും ശ്രമിക്കുക.</p></body>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => undefined);
  if (cached) {
    // Do not await the refresh: the cached copy is the answer.
    void network;
    return cached;
  }
  const fresh = await network;
  return (
    fresh ||
    new Response("", { status: 504, statusText: "offline and not cached" })
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // never cache or replay a scan POST

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirstNavigation(request));
    return;
  }
  if (isCacheableAsset(url)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
