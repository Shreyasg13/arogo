// tests/js/run_sw_tests.mjs — unit tests for static/sw.js offline outbox.
//
// A notification action fires with no page open, so it can't reach the app's
// in-page outbox. Before this queue existed, tapping "💧 250ml" on a train hit
// a dead network, fell into .catch(), and the drink vanished — no row, and no
// hint to the user that anything was lost. That's the exact failure this file
// exists to keep fixed, so the tests drive the REAL sw.js through a fake
// IndexedDB and a controllable fetch rather than asserting on shapes.
//
// No npm dependencies — plain `node tests/js/run_sw_tests.mjs`.
// Exit code 0 = all pass, 1 = failures (used by pre-commit + CI).

import fs from 'fs';
import vm from 'vm';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'static', 'sw.js'), 'utf8');

// ── A tiny in-memory IndexedDB, faithful to the bits sw.js actually uses:
// open/onupgradeneeded, one autoIncrement store, add/getAll/delete, and a
// transaction whose oncomplete fires after the requests settle.
function makeIndexedDB() {
  const rows = new Map();
  let nextId = 1;
  const store = {
    add(item) { const id = nextId++; rows.set(id, Object.assign({ id }, item)); return { result: id }; },
    getAll() { return { result: [...rows.values()] }; },
    delete(id) { rows.delete(id); return { result: undefined }; },
  };
  const db = {
    objectStoreNames: { contains: () => true },
    createObjectStore: () => store,
    transaction() {
      const tx = { objectStore: () => store, oncomplete: null, onerror: null };
      queueMicrotask(() => { if (tx.oncomplete) tx.oncomplete(); });
      return tx;
    },
  };
  return {
    _rows: rows,
    open() {
      const req = { result: db, onsuccess: null, onerror: null, onupgradeneeded: null };
      queueMicrotask(() => { if (req.onsuccess) req.onsuccess(); });
      return req;
    },
  };
}

// ── Service-worker global stub. Captures listeners and notifications so a test
// can fire a notificationclick and read back what the user was told.
function makeSandbox(fetchImpl) {
  const notifications = [];
  const listeners = {};
  const syncTags = [];
  const idb = makeIndexedDB();
  const self = {
    addEventListener: (k, fn) => { (listeners[k] = listeners[k] || []).push(fn); },
    registration: {
      showNotification: (title, opts) => { notifications.push({ title, ...opts }); return Promise.resolve(); },
      sync: { register: tag => { syncTags.push(tag); return Promise.resolve(); } },
    },
    clients: { matchAll: () => Promise.resolve([]), openWindow: () => Promise.resolve() },
    caches: { open: () => Promise.resolve({ addAll: () => Promise.resolve(), put: () => {} }),
              keys: () => Promise.resolve([]), match: () => Promise.resolve(null), delete: () => {} },
    skipWaiting: () => Promise.resolve(),
    crypto: undefined,               // exercise the non-randomUUID fallback path
    indexedDB: idb,
    fetch: fetchImpl,
    location: { origin: 'https://arogo.test' },
    URL, Promise, JSON, Math, Date, Object, Array, Number, String, Boolean, RegExp, Error,
    setTimeout, clearTimeout, queueMicrotask, console,
  };
  self.self = self;
  self.globalThis = self;
  vm.createContext(self);
  vm.runInContext(src, self, { filename: 'sw.js' });
  return { self, listeners, notifications, syncTags, idb };
}

// Fire a notificationclick with the given action and wait for its waitUntil.
function click(env, action) {
  let waited = Promise.resolve();
  const e = {
    action,
    notification: { close: () => {}, data: {} },
    waitUntil: p => { waited = p; },
  };
  for (const fn of env.listeners.notificationclick) fn(e);
  return waited;
}

// ── Tiny test runner ──
let passed = 0, failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
function eq(actual, expected, msg = '') {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${msg} expected ${b}, got ${a}`);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'expected truthy'); }

const OFFLINE = () => Promise.reject(new TypeError('Failed to fetch'));
const ONLINE = calls => (url, opts) => { calls.push({ url, opts }); return Promise.resolve({ ok: true, status: 200 }); };
const STATUS = (code, calls) => (url, opts) => {
  if (calls) calls.push({ url, opts });
  return Promise.resolve({ ok: code >= 200 && code < 300, status: code });
};

// ── Online: the write goes straight out and the user is told it landed ──
test('online water tap posts and reports "Logged"', async () => {
  const calls = [];
  const env = makeSandbox(ONLINE(calls));
  await click(env, 'water-250');
  eq(calls.length, 1, 'one POST');
  ok(calls[0].url === '/api/hydration', 'hits the hydration endpoint');
  const body = JSON.parse(calls[0].opts.body);
  eq(body.amount_ml, 250);
  eq(body.source, 'notification', 'flags this as our suggested amount, not the user\'s');
  ok(body.idem_key && body.idem_key.length > 4, 'stamps an idempotency key');
  eq(calls[0].opts.credentials, 'include', 'session cookie must ride along');
  eq(env.notifications.length, 1);
  eq(env.notifications[0].title, '✓ Logged');
  eq(env.idb._rows.size, 0, 'nothing queued when it succeeded');
});

// ── The bug this file exists for: offline must QUEUE, not vanish ──
test('offline water tap is queued, not lost', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  eq(env.idb._rows.size, 1, 'the drink is in the outbox');
  const row = [...env.idb._rows.values()][0];
  eq(row.url, '/api/hydration');
  eq(row.method, 'POST');
  eq(JSON.parse(row.body).amount_ml, 250);
  eq(env.syncTags, ['arogo-outbox'], 'asks for a background sync');
});

// ── ...and the user is told the truth about it ──
test('offline tap says "Saved offline", never "Logged"', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  eq(env.notifications.length, 1);
  eq(env.notifications[0].title, '⏳ Saved offline');
  ok(/sync/i.test(env.notifications[0].body), 'explains it will sync later');
  ok(!/✓/.test(env.notifications[0].title), 'must not claim a confirmed write');
});

test('a real server rejection is reported as a failure, not as saved', async () => {
  const env = makeSandbox(STATUS(400));
  await click(env, 'water-250');
  eq(env.notifications[0].title, "Couldn't log that");
  eq(env.idb._rows.size, 0, 'a 400 is a bad request, not a connectivity problem');
});

test('401 keeps the write instead of discarding it', async () => {
  const env = makeSandbox(STATUS(401));
  await click(env, 'water-250');
  eq(env.idb._rows.size, 1, 'not signed in yet is not a reason to drop health data');
  eq(env.notifications[0].title, '⏳ Saved offline');
});

test('offline dose tap queues the dose log', async () => {
  const env = makeSandbox(OFFLINE);
  const mid = 'a'.repeat(32);
  await click(env, `dose-${mid}-08:30`);
  eq(env.idb._rows.size, 1);
  const row = [...env.idb._rows.values()][0];
  eq(row.url, `/api/medicines/${mid}/log`);
  const body = JSON.parse(row.body);
  eq(body.time, '08:30');
  eq(body.taken, true);
  ok(body.idem_key, 'carries a key so a replay cannot double-log');
});

test('offline mood tap queues the check-in with the app\'s own mood key', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'mood-happy');
  const body = JSON.parse([...env.idb._rows.values()][0].body);
  eq(body.mood, 'happy');
  ok(/feeling good/.test(body.content), 'reads like the journal entry it becomes');
  ok(body.idem_key, 'keyed, or a replay writes the user\'s words twice');
});

// ── Snooze is deliberately NOT queued: it is a request about the future ──
test('offline snooze is not queued and says so', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, `snooze-${'b'.repeat(32)}-09:00`);
  eq(env.idb._rows.size, 0, 'replaying a stale snooze would schedule a reminder for a passed dose');
  eq(env.notifications[0].title, "Couldn't snooze");
  ok(/offline/i.test(env.notifications[0].body), 'tells the user why');
});

// ── Draining the queue ──
test('sync drains the queue when connectivity returns', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  await click(env, 'mood-happy');
  eq(env.idb._rows.size, 2);

  const calls = [];
  env.self.fetch = ONLINE(calls);
  let waited = Promise.resolve();
  for (const fn of env.listeners.sync) fn({ tag: 'arogo-outbox', waitUntil: p => { waited = p; } });
  await waited;
  eq(env.idb._rows.size, 0, 'both writes landed and were removed');
  eq(calls.length, 2);
  eq(calls[0].opts.credentials, 'include',
     'replay without credentials 401s, and the 4xx branch would then delete the data');
});

test('sync ignores unrelated tags', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  let waited = Promise.resolve();
  for (const fn of env.listeners.sync) fn({ tag: 'something-else', waitUntil: p => { waited = p; } });
  await waited;
  eq(env.idb._rows.size, 1, 'still queued');
});

test('a 5xx during drain keeps the queue for next time', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  env.self.fetch = STATUS(503);
  let waited = Promise.resolve();
  for (const fn of env.listeners.sync) fn({ tag: 'arogo-outbox', waitUntil: p => { waited = p; } });
  await waited;
  eq(env.idb._rows.size, 1, 'a server hiccup must not consume the write');
});

test('a 401 during drain keeps the queue (the old bug deleted it)', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  env.self.fetch = STATUS(401);
  let waited = Promise.resolve();
  for (const fn of env.listeners.sync) fn({ tag: 'arogo-outbox', waitUntil: p => { waited = p; } });
  await waited;
  eq(env.idb._rows.size, 1);
});

test('two taps get distinct keys, so both real drinks are recorded', async () => {
  const env = makeSandbox(OFFLINE);
  await click(env, 'water-250');
  await click(env, 'water-250');
  const keys = [...env.idb._rows.values()].map(r => JSON.parse(r.body).idem_key);
  eq(keys.length, 2);
  ok(keys[0] !== keys[1], 'dedupe must not swallow a genuine second drink');
});

// ── Run them ──
(async () => {
  console.log('sw.js offline outbox');
  for (const [name, fn] of tests) {
    try { await fn(); passed++; console.log(`  PASS  ${name}`); }
    catch (e) { failed++; console.error(`  FAIL  ${name}\n        ${e.message}`); }
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
