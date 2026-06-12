// AdaptaAI Service Worker — network-first app shell
// Version this string whenever you deploy a new build (also clears old caches)
const CACHE = 'adapta-v1';

// App shell: only PUBLIC assets are precached on install. The other b2c
// screens are auth-gated (StaticAuthMiddleware → 401 for anonymous), so
// precaching them would make cache.addAll() reject and abort install on the
// first anonymous visit. They get cached lazily by the fetch handler below
// once the user is logged in and navigates to them.
const APP_SHELL = [
  '01-welcome.html',
  '../design-tokens.css',
  '../i18n.js',
  '../mock-data.js',
  'icon-192.png',
  'icon-512.png',
  'manifest.json',
];

// ── Install: precache the public app shell ──────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    // Tolerate individual failures so one missing asset never aborts install.
    caches.open(CACHE).then((cache) =>
      Promise.allSettled(APP_SHELL.map((url) => cache.add(url)))
    )
  );
  // Activate immediately without waiting for old clients to close
  self.skipWaiting();
});

// ── Activate: clean up stale caches ─────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
      )
    )
  );
  // Take control of all open clients immediately
  self.clients.claim();
});

// ── Fetch: network-first for app shell; network-only for API calls ───────────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Network-only: API requests (never cache auth / mutations)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Network-only: non-GET requests
  if (event.request.method !== 'GET') {
    event.respondWith(fetch(event.request));
    return;
  }

  // Network-first: always try the network so a fresh deploy shows immediately;
  // fall back to cache only when offline. Same-origin successful GETs are
  // cached as the offline fallback.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && url.origin === self.location.origin) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.open(CACHE).then((cache) => cache.match(event.request))
      )
  );
});
