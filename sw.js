// UCI Calendar 2026 - Service Worker
const CACHE_NAME = 'uci-calendar-v57';
const STATIC = ['./manifest.json', './icon-192.png', './icon-512.png'];

// Install: pre-cache only truly static assets (NOT index.html or data.json)
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      cache.addAll(STATIC.filter(u => {
        try { new URL(u, self.location.origin); return true; } catch { return false; }
      }))
    ).catch(() => {})
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
//   index.html + data.json → network-first (always fresh)
//   everything else        → cache-first (icons, manifest)
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  const isHtml = url.pathname.endsWith('/') || url.pathname.endsWith('.html');
  const isData = url.pathname.endsWith('data.json') || url.pathname.endsWith('pcs_stats.json') || url.pathname.endsWith('rider_profiles.json') || url.pathname.endsWith('pcs_enrichment.json');

  if (isHtml || isData) {
    // Network-first: try live, fall back to cache
    event.respondWith(
      fetch(event.request)
        .then(resp => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
          }
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
  } else {
    // Cache-first for static assets
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request))
    );
  }
});

// ── Push notifications ─────────────────────────────────────────────────────────
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch(e) {}

  const title   = data.title  || '🚴 UCI Calendar';
  const options = {
    body  : data.body  || 'New update',
    icon  : './icon-192.png',
    badge : './icon-192.png',
    tag   : data.tag   || 'uci-update',
    renotify: false,
    data  : { url: './' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Tap notification → bring app to front (or open it)
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const existing = list.find(c => c.url.includes('index.html') || c.url.endsWith('/'));
     