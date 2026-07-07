/* MedEasy service worker — app-shell caching.
 *
 * Strategy:
 *   - /api/ and /auth/ requests: network only (health data is never cached)
 *   - navigations: network first, cached shell as offline fallback
 *   - static assets (css/js/icons/fonts): stale-while-revalidate
 *
 * Bump CACHE_VERSION when the shell must be refreshed immediately.
 */
const CACHE_VERSION = 'medeasy-v1';
const SHELL = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // Never cache health data or auth flows
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) return;

  // Navigations: network first, offline falls back to the cached shell
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const copy = r.clone();
          caches.open(CACHE_VERSION).then(c => c.put('/', copy));
          return r;
        })
        .catch(() => caches.match('/'))
    );
    return;
  }

  // Static assets: stale-while-revalidate
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(cached => {
        const refresh = fetch(e.request)
          .then(r => {
            if (r.ok) {
              const copy = r.clone();
              caches.open(CACHE_VERSION).then(c => c.put(e.request, copy));
            }
            return r;
          })
          .catch(() => cached);
        return cached || refresh;
      })
    );
  }
});
