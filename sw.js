// UCI Calendar 2026 - Service Worker
const CACHE_NAME = 'uci-calendar-v9';
const STATIC = ['./manifest.json', './icon-192.png', './icon-512.png'];

// Install: pre-cache only truly static assets (NOT index.html)
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      cache.addAll(STATIC.filter(u => {
        try { new URL(u, self.location.origin); return true; } catch { return false; }
      }))
    ).catch(() => {}) // ignore missing icons etc
  );
  self.skipWaiting();
});

// Activate: wipe old caches and claim clients
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Fetch strategy:
//   index.html + data.json → network-first (always fresh code + data)
//   everything else        → cache-first (icons, manifest)
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // External requests - pass through
  if (url.origin !== self.location.origin) return;

  const isHtml = url.pathname.endsWith('/') || url.pathname.endsWith('.html');
  const isData = url.pathname.endsWith('data.json');

  if (isHtml || isData) {
    // Network-first: always try to get fresh version, fall back to cache
    event.respondWith(
      fetch(event.request, { cache: 'no-cache' }).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match(event.request))
    );
    return;
  }

  // Static assets - cache-first
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
