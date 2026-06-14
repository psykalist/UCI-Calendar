// UCI Calendar 2026 - Service Worker
const CACHE_NAME = 'uci-calendar-v8';
const ASSETS = [
  './',
  './index.html',
  './manifest.json'
];

// Install: cache core assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting(); // activate immediately, don't wait for old tabs to close
});

// Activate: wipe old caches, claim all clients, then tell them to reload
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ includeUncontrolled: true }))
      .then(clients => clients.forEach(c => c.postMessage({ type: 'SW_UPDATED', version: CACHE_NAME })))
  );
});

// Fetch strategy:
//   data.json  → network-first (always get fresh race data), fallback to cache
//   app shell  → cache-first (fast load), fallback to network
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // External requests - pass through
  if (url.origin !== self.location.origin) {
    return;
  }

  // data.json: network-first so updates appear immediately
  if (url.pathname.endsWith('data.json')) {
    event.respondWith(
      fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match(event.request))
    );
    return;
  }

  // App shell - cache first, fallback to network
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match('./index.html'));
    })
  );
});
