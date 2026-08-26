/* Arogo service worker — app-shell caching.
 *
 * Strategy:
 *   - /api/ and /auth/ requests: network only (health data is never cached)
 *   - navigations: network first, cached shell as offline fallback
 *   - static assets (css/js/icons/fonts): stale-while-revalidate
 *
 * CACHE_VERSION is stamped with a content hash of the shell files by the
 * /sw.js route (see assets.py) — it changes automatically on every deploy, so
 * there is nothing to bump by hand. The literal below is only a fallback for
 * the (unused) case of serving this file raw.
 */
const CACHE_VERSION = 'arogo-dev';   // replaced per-deploy with 'arogo-<hash>'
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

/* ── Offline outbox (service-worker side) ──────────────────────────────────
 * A notification action fires with no page open, so it can't reach the app's
 * in-page outbox. Tapping "log water" on the train used to hit a dead network,
 * fall into .catch(), and vanish — no row, and no acknowledgement either.
 *
 * This is the SAME IndexedDB database and store the page uses ('arogo-outbox'
 * → 'writes'), so whichever context comes online first drains the one queue.
 * Every queued write carries the idempotency key stamped here, so replaying it
 * — from the SW, from the page, or from both — can only ever create one row.
 */
const OUTBOX_DB = 'arogo-outbox';
const OUTBOX_STORE = 'writes';
// The last signed-in user, written by the page. A queued write carries the id
// of whoever queued it so it can never be replayed into a different account.
const OUTBOX_META = 'meta';

function _obOpen() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(OUTBOX_DB, 2);
    r.onupgradeneeded = () => {
      if (!r.result.objectStoreNames.contains(OUTBOX_STORE)) {
        r.result.createObjectStore(OUTBOX_STORE, { keyPath: 'id', autoIncrement: true });
      }
      if (!r.result.objectStoreNames.contains(OUTBOX_META)) {
        r.result.createObjectStore(OUTBOX_META);
      }
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
function _obTx(mode, fn, storeName) {
  return _obOpen().then(db => new Promise((res, rej) => {
    const tx = db.transaction(storeName || OUTBOX_STORE, mode);
    const out = fn(tx.objectStore(storeName || OUTBOX_STORE));
    tx.oncomplete = () => res(out && out.result !== undefined ? out.result : out);
    tx.onerror = () => rej(tx.error);
  }));
}
const _obAdd = item => _obTx('readwrite', s => s.add(item));
const _obAll = () => _obTx('readonly', s => s.getAll());
const _obDel = id => _obTx('readwrite', s => s.delete(id));
// Written by the page on every boot; the worker only reads it.
// Normalised to a string or null: _obTx yields the request object when a get
// legitimately returns undefined, and stamping THAT onto a queued item would
// make it unserialisable — the write would fail to queue at all.
const _obUid = () => _obTx('readonly', s => s.get('uid'), OUTBOX_META)
                       .then(v => (typeof v === 'string' && v ? v : null))
                       .catch(() => null);

// A key per user action, so a replay is recognised as already-applied.
function _swIdemKey() {
  try { if (self.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, ''); }
  catch (e) {}
  return 'k' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

/* POST a notification action. Online → sends it. Offline (or a network error)
 * → queues it and asks for a background sync. Resolves to
 * {ok, queued} so the caller can tell the user the truth either way. */
function swPost(url, payload) {
  const body = JSON.stringify(Object.assign({ idem_key: _swIdemKey() }, payload));
  const opts = { method: 'POST', credentials: 'include',
                 headers: { 'Content-Type': 'application/json' }, body };
  return fetch(url, opts)
    .then(r => {
      if (r.ok) return { ok: true, queued: false };
      // 401/403 = the session isn't usable from here; keep the write rather
      // than dropping something the user asked us to record.
      if (r.status === 401 || r.status === 403) return _queue(url, body);
      return { ok: false, queued: false };
    })
    .catch(() => _queue(url, body));
}
function _queue(url, body) {
  // Stamp whoever is signed in. The queue lives in origin storage, not per
  // account, so without this a dose logged offline by one family member would
  // be replayed into whichever account happened to be signed in when the phone
  // came back online — a dose they never took, recorded against their name.
  return _obUid()
    .then(uid => _obAdd({ url, method: 'POST', body, uid: uid || null,
                          headers: { 'Content-Type': 'application/json' }, ts: Date.now() }))
    .then(() => { try { return self.registration.sync.register('arogo-outbox'); } catch (e) {} })
    .then(() => ({ ok: false, queued: true }))
    .catch(() => ({ ok: false, queued: false }));
}

/* Drain the shared queue. Mirrors the page's flushOutbox rules exactly:
 * credentials always sent, 401/403 means "retry later" (never discard), a real
 * 4xx is an unfixable row, 5xx/offline stops so the order is preserved.
 *
 * The page may be draining the same queue at the same moment (it flushes on
 * 'online' and on load). That's safe only because every queued write carries an
 * idempotency key: the worst case is the server seeing one POST twice and
 * recognising the second as already-applied. */
async function swFlushOutbox() {
  let items;
  try { items = await _obAll(); } catch (e) { return 0; }
  // Who is signed in right now. We're online (that's why we're flushing), so
  // this is answerable; if it isn't, we send nothing rather than guess.
  let currentUid = null;
  try {
    const me = await fetch('/auth/me', { credentials: 'include' });
    if (me.ok) currentUid = (await me.json()).id || null;
  } catch (e) { return 0; }
  let synced = 0;
  for (const it of (items || [])) {
    // Queued by someone else: keep it, skip it. It syncs when they sign back
    // in. Sending it now would file their dose under this account.
    if (it.uid && currentUid && it.uid !== currentUid) continue;
    try {
      const r = await fetch(it.url, { method: it.method, headers: it.headers,
                                      body: it.body, credentials: 'include' });
      if (r.ok) { await _obDel(it.id); synced++; }
      else if (r.status === 401 || r.status === 403) break;   // not signed in — keep it
      else if (r.status >= 400 && r.status < 500) { await _obDel(it.id); }  // unfixable row
      else break;                                             // server hiccup — next time
    } catch (e) { break; }                                    // still offline
  }
  if (synced > 0) {
    // Let any open tab refresh its badge and views instead of showing stale
    // "waiting to sync" counts for writes that have already landed.
    try {
      const list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const c of list) c.postMessage({ type: 'outbox-synced', synced });
    } catch (e) {}
  }
  return synced;
}

self.addEventListener('sync', e => {
  if (e.tag === 'arogo-outbox') e.waitUntil(swFlushOutbox());
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const act = e.action || '';

  // The device's own local day — never UTC (matches the app's localToday rule).
  const localToday = () => new Date().toLocaleDateString('en-CA');

  // Tell the user what actually happened — logged, saved-for-later, or failed.
  // Claiming "✓ Logged" for a write still sitting in a queue would be a lie.
  const ackR = (r, okBody, tag) => self.registration.showNotification(
    r.ok ? '✓ Logged' : (r.queued ? '⏳ Saved offline' : "Couldn't log that"),
    { body: r.ok ? okBody
          : (r.queued ? "It'll sync when you're back online."
                      : 'Open Arogo to log it.'),
      icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', tag });

  // "water-250" → log it from here; the app never has to open.
  const water = act.match(/^water-(\d+)$/);
  if (water) {
    const ml = Number(water[1]);
    e.waitUntil(
      // `source` marks this as a tap on OUR suggested amount, not a
      // container the user chose — the button's number comes from
      // usual_sip_ml, so counting it as a preference would feed the app's
      // own default back in as if it were theirs.
      swPost('/api/hydration', { amount_ml: ml, drink_type: 'water',
                                 date_key: localToday(), source: 'notification' })
      .then(r => ackR(r, `${ml}ml added to today.`, 'water-ack'))
      .catch(() => {})
    );
    return;
  }

  // "dose-<medId>-<HH:MM>" → mark the dose taken without opening the app.
  const dose = act.match(/^dose-([0-9a-f]{32})-(\d{1,2}:\d{2})$/);
  if (dose) {
    const [, medId, time] = dose;
    e.waitUntil(
      swPost(`/api/medicines/${medId}/log`, { date: localToday(), time, taken: true })
      .then(r => ackR(r, `Dose marked taken (${time}).`, 'dose-ack'))
      .catch(() => {})
    );
    return;
  }

  // "mood-happy" → journal the day's mood without opening the app. Keys match
  // the app's own scale (CI_MOODS) so it reads identically in the journal.
  const mood = act.match(/^mood-([a-z]+)$/);
  if (mood) {
    const key = mood[1];
    const words = { terrible: 'rough', sad: 'not great', neutral: 'okay',
                    happy: 'good', excited: 'great' };
    const word = words[key] || key;
    e.waitUntil(
      swPost('/api/thoughts', { content: `Check-in: feeling ${word}.`, mood: key,
                                date_key: localToday() })
      .then(r => ackR(r, `Noted — feeling ${word}.`, 'mood-ack'))
      .catch(() => {})
    );
    return;
  }

  // "snooze-<medId>-<HH:MM>" → a REAL snooze: ask the server to remind again
  // shortly. Tapping it repeatedly just pushes the reminder further out.
  //
  // Deliberately NOT queued. The three actions above record something that
  // happened, so replaying them later is still true. A snooze is a request
  // about the *future* — replaying it when connectivity returns two hours
  // later would fire a reminder for a dose whose moment has passed. Better to
  // say plainly that it didn't take than to schedule a lie.
  const snz = act.match(/^snooze-([0-9a-f]{32})-(\d{1,2}:\d{2})$/);
  if (snz) {
    const [, medId, time] = snz;
    e.waitUntil(
      fetch(`/api/medicines/${medId}/snooze`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ time, minutes: 15 }),
      })
      .then(r => self.registration.showNotification(
        r.ok ? '⏰ Snoozed' : "Couldn't snooze",
        { body: r.ok ? "We'll remind you again in 15 minutes." : 'Open Arogo to take it.',
          icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', tag: 'snooze-ack' }))
      .catch(() => self.registration.showNotification(
        "Couldn't snooze",
        { body: "You're offline — the reminder stays as it is.",
          icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', tag: 'snooze-ack' }))
    );
    return;
  }

  if (act === 'snooze') return;   // generic (water/mood): dismissed; the next pace check nudges again

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

/* ── Offline reading ────────────────────────────────────────────────────────
 * The rule this is built around: a cached answer must never be mistaken for a
 * live one. Every response served from the cache carries the moment it was
 * fetched, and the page prints "as of ..." from it. Silently handing back
 * yesterday's dose list is worse than showing nothing at all, because the whole
 * point of the list is that it is today's.
 */
const DATA_CACHE = 'arogo-data-v1';

// Reads worth having without a connection. Prefixes, matched in order.
const OFFLINE_READABLE = [
  '/api/medicines/today',      // which doses are due — the reason to open the app
  '/api/medicines',            // the list itself, dosages and times
  '/api/allergies',            // what a stranger would need to know
  '/api/health-id',            // the emergency card
  '/api/emergency',
  '/api/conditions',
  '/api/labs',                 // recent results, to show someone
  '/api/appointments',         // where you are meant to be
];

function _isOfflineReadable(pathname) {
  const p = pathname.startsWith('/api/v1/') ? '/api/' + pathname.slice(8) : pathname;
  return OFFLINE_READABLE.some(prefix => p === prefix || p.startsWith(prefix + '/')
                                          || p.startsWith(prefix + '?'));
}

/* Network first. On success, store a copy stamped with the moment and the user
 * it belongs to; on failure, hand back that copy clearly marked as old.
 *
 * The user stamp is not decoration. This cache is per-ORIGIN, so on a shared
 * phone a second account going offline would otherwise be served the first
 * account's medicines — the same cross-user mistake the write queue had. */
async function _dataFirstNetwork(request) {
  let uid = null;
  try { uid = await _obUid(); } catch (e) {}
  try {
    const res = await fetch(request);
    if (res && res.ok) {
      try {
        const cache = await caches.open(DATA_CACHE);
        const body = await res.clone().blob();
        const headers = new Headers(res.headers);
        headers.set('X-Arogo-Cached-At', new Date().toISOString());
        if (uid) headers.set('X-Arogo-Cached-For', uid);
        await cache.put(request, new Response(body, {
          status: res.status, statusText: res.statusText, headers,
        }));
      } catch (e) { /* a full cache must not break a working request */ }
    }
    return res;
  } catch (err) {
    const cached = await caches.match(request, { cacheName: DATA_CACHE });
    if (!cached) throw err;
    // Belongs to someone else on this device: refuse rather than answer wrongly.
    const owner = cached.headers.get('X-Arogo-Cached-For');
    if (owner && uid && owner !== uid) throw err;
    const headers = new Headers(cached.headers);
    headers.set('X-Arogo-Offline', '1');
    return new Response(await cached.blob(), {
      status: 200, statusText: 'OK (offline copy)', headers,
    });
  }
}

async function _clearDataCache() {
  try { await caches.delete(DATA_CACHE); } catch (e) {}
}

// Signing out must take the cached copies with it. Leaving them behind would
// let the next person on the device read the last one's records by pulling the
// plug — the cache is not protected by the session cookie.
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'arogo-signed-out') {
    e.waitUntil(_clearDataCache());
  }
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // A short, explicit list of reads worth having on a train. Offline, the app
  // used to open to an empty shell: you could log a dose from a notification
  // and had no way to see which ones were due.
  //
  // An ALLOW-list, not a deny-list. Caching health data by default and hoping
  // nothing sensitive slips through is exactly the shape of bug this codebase
  // keeps finding; anything not named here still goes network-only.
  //
  // Nothing under /auth/, /api/2fa, /api/account/ or /api/share is here, and
  // never should be: a stale answer to "am I signed in" or "is my second factor
  // on" is worse than no answer.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) {
    if (e.request.mode !== 'navigate' && _isOfflineReadable(url.pathname)) {
      e.respondWith(_dataFirstNetwork(e.request));
    }
    return;
  }

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
