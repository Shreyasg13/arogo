// tests/js/run_js_tests.mjs — unit tests for app.js pure logic.
//
// Loads the real static/js/app.js inside a Node VM with a minimal DOM
// stub, then exercises the functions that contain actual logic:
// the CSP-safe event dispatcher, the quick-command parser, and small
// helpers. No npm dependencies — plain `node tests/js/run_js_tests.mjs`.
//
// Exit code 0 = all pass, 1 = failures (used by pre-commit + CI).

import fs from 'fs';
import vm from 'vm';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'static', 'js', 'app.js'), 'utf8');

// ── Minimal DOM/browser stub — just enough for app.js top-level code ──
const noop = () => {};
const fakeEl = () => ({
  style: {}, classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
  addEventListener: noop, appendChild: noop, append: noop, remove: noop,
  setAttribute: noop, getAttribute: () => null, dataset: {},
});
const sandbox = {
  document: {
    addEventListener: noop, removeEventListener: noop,
    getElementById: () => null, querySelector: () => null,
    querySelectorAll: () => [], createElement: fakeEl,
    body: fakeEl(), documentElement: fakeEl(),
  },
  navigator: {},                                   // no serviceWorker → PWA block skipped
  localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  location: { search: '', pathname: '/', reload: noop },
  history: { replaceState: noop },
  fetch: () => Promise.resolve({ ok: false, json: async () => ({}), headers: { get: () => '' } }),
  setTimeout, clearTimeout, setInterval: noop, clearInterval: noop,
  console, atob: s => Buffer.from(s, 'base64').toString('binary'),
  URLSearchParams, Uint8Array, JSON, Math, Date, Promise, Object, Array,
  Intl, parseFloat, parseInt, isNaN, String, Number, Boolean, RegExp, Error,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.window.addEventListener = noop;
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: 'app.js' });

// ── Tiny test runner ──
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  PASS  ${name}`); }
  catch (e) { failed++; console.error(`  FAIL  ${name}\n        ${e.message}`); }
}
function eq(actual, expected, msg = '') {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${msg} expected ${b}, got ${a}`);
}

const S = sandbox;

// ── Dispatcher: tokenizer ──
test('_evTokenize splits statements on ; at depth 0', () => {
  eq(S._evTokenize("a('x');b(1,2)", ';'), ["a('x')", 'b(1,2)']);
});
test('_evTokenize keeps ; inside strings and brackets', () => {
  eq(S._evTokenize("f('a;b');g({\"k\":\"x;y\"})", ';'), ["f('a;b')", 'g({"k":"x;y"})']);
});
test('_evTokenize splits args on , respecting nesting', () => {
  eq(S._evTokenize("'a,b', 1, {\"x\":[1,2]}", ','), ["'a,b'", '1', '{"x":[1,2]}']);
});

// ── Dispatcher: argument evaluation ──
test('_evArg literals', () => {
  eq(S._evArg('42', null, null), 42);
  eq(S._evArg('-0.5', null, null), -0.5);
  eq(S._evArg('true', null, null), true);
  eq(S._evArg('null', null, null), null);
  eq(S._evArg("'hello'", null, null), 'hello');
});
test('_evArg this/event/this.value/this.checked', () => {
  const el = { value: 'v', checked: true }, ev = { type: 'click' };
  if (S._evArg('this', el, ev) !== el) throw new Error('this');
  if (S._evArg('event', el, ev) !== ev) throw new Error('event');
  eq(S._evArg('this.value', el, ev), 'v');
  eq(S._evArg('this.checked', el, ev), true);
});
test('_evArg JSON object', () => {
  eq(S._evArg('{"name":"Dal Tarka","cal":116}', null, null),
     { name: 'Dal Tarka', cal: 116 });
});

// ── Dispatcher: end-to-end statement execution ──
test('_evRun calls a global with parsed args', () => {
  let got = null;
  S.__t = (...args) => { got = args; };
  S._evRun("__t('id-1',30,true)", { tag: 'BTN' }, { type: 'click' });
  eq(got, ['id-1', 30, true]);
  delete S.__t;
});
test('_evRun handles stopPropagation + return false', () => {
  let stopped = false, prevented = false, called = false;
  S.__t = () => { called = true; };
  S._evRun("event.stopPropagation();__t();return false",
           {}, { stopPropagation: () => { stopped = true; },
                 preventDefault: () => { prevented = true; } });
  if (!stopped || !prevented || !called) throw new Error('sequence incomplete');
  delete S.__t;
});

// ── Quick commands ──
test('parseQuickCommand: water variants', () => {
  eq(S.parseQuickCommand('water 500').label, 'Log 500ml water');
  eq(S.parseQuickCommand('w 250').label, 'Log 250ml water');
  eq(S.parseQuickCommand('WATER 750ml').label, 'Log 750ml water');
});
test('parseQuickCommand: weight', () => {
  eq(S.parseQuickCommand('weight 72.5').label, 'Log weight 72.5kg');
  eq(S.parseQuickCommand('weight 90kg').label, 'Log weight 90kg');
});
test('parseQuickCommand: rejects out-of-range and normal queries', () => {
  eq(S.parseQuickCommand('water 9999'), null);
  eq(S.parseQuickCommand('weight 5'), null);
  eq(S.parseQuickCommand('headache'), null);
  eq(S.parseQuickCommand('waterfall hike'), null);
});

// ── Helpers ──
test('escapeHtml escapes the five specials', () => {
  eq(S.escapeHtml(`<img src="x" onerror='a&b'>`),
     '&lt;img src=&quot;x&quot; onerror=&#39;a&amp;b&#39;&gt;');
});
test('localToday returns YYYY-MM-DD', () => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(S.localToday())) throw new Error(S.localToday());
});
test('_urlB64ToUint8 decodes url-safe base64', () => {
  const out = S._urlB64ToUint8('AQID');   // bytes 1,2,3
  eq([...out], [1, 2, 3]);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
