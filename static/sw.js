/* Arogo service worker — app-shell caching.
 *
 * Strategy:
 *   - /api/ and /auth/ requests: network only (health data is never cached)
 *   - navigations: network first, cached shell as offline fallback
 *   - static assets (css/js/icons/fonts): stale-while-revalidate
 *
 * Bump CACHE_VERSION when the shell must be refreshed immediately.
 */
const CACHE_VERSION = 'arogo-v3';   // v3: dose + water quick-log from notifications
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

// ── Web Push ──
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (_) {}
  const opts = {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    data: { url: data.url || '/' },
  };
  // Optional action buttons (e.g. "💧 250ml" on a hydration reminder) so the
  // user can act straight from the notification. Most browsers render 2.
  if (Array.isArray(data.actions) && data.actions.length) {
    opts.actions = data.actions.slice(0, 2);
  }
  e.waitUntil(self.registration.showNotification(data.title || 'Arogo', opts));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const act = e.action || '';

  // The device's own local day — never UTC (matches the app's localToday rule).
  const localToday = () => new Date().toLocaleDateString('en-CA');

  const ack = (ok, okBody, tag) => self.registration.showNotification(
    ok ? '✓ Logged' : "Couldn't log that",
    { body: ok ? okBody : 'Open Arogo to log it.',
      icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', tag });

  // "water-250" → log it from here; the app never has to open.
  const water = act.match(/^water-(\d+)$/);
  if (water) {
    const ml = Number(water[1]);
    e.waitUntil(
      fetch('/api/hydration', {
        method: 'POST',
        credentials: 'include',          // same-origin session cookie
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount_ml: ml, drink_type: 'water', date_key: localToday() }),
      })
      .then(r => ack(r.ok, `${ml}ml added to today.`, 'water-ack'))
      .catch(() => {})
    );
    return;
  }

  // "dose-<medId>-<HH:MM>" → mark the dose taken without opening the app.
  const dose = act.match(/^dose-([0-9a-f]{32})-(\d{1,2}:\d{2})$/);
  if (dose) {
    const [, medId, time] = dose;
    e.waitUntil(
      fetch(`/api/medicines/${medId}/log`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: localToday(), time, taken: true }),
      })
      .then(r => ack(r.ok, `Dose marked taken (${time}).`, 'dose-ack'))
      .catch(() => {})
    );
    return;
  }

  if (act === 'snooze') return;   // dismissed; the next pace check will nudge again

  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if ('focus' in c) { c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
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
