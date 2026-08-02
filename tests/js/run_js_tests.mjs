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
test('parseQuickCommand: vitals — bp / sugar / hr', () => {
  eq(S.parseQuickCommand('bp 120/80').label, 'Log BP 120/80');
  eq(S.parseQuickCommand('BP 128 / 82').label, 'Log BP 128/82');
  eq(S.parseQuickCommand('sugar 110').label, 'Log blood sugar 110 mg/dL');
  eq(S.parseQuickCommand('glucose 95').label, 'Log blood sugar 95 mg/dL');
  eq(S.parseQuickCommand('hr 72').label, 'Log heart rate 72 bpm');
  eq(S.parseQuickCommand('pulse 58').label, 'Log heart rate 58 bpm');
});
test('parseQuickCommand: rejects out-of-range and normal queries', () => {
  eq(S.parseQuickCommand('water 9999'), null);
  eq(S.parseQuickCommand('weight 5'), null);
  eq(S.parseQuickCommand('headache'), null);
  eq(S.parseQuickCommand('waterfall hike'), null);
  // Must not hijack ordinary searches that merely start with a keyword
  eq(S.parseQuickCommand('bp monitor'), null);
  eq(S.parseQuickCommand('sugar free biscuits'), null);
  eq(S.parseQuickCommand('sugarcane juice'), null);
});

// ── Vital flags ──
// The rule: never vouch for a reading. A flag means "worth a look"; silence
// means "we're not judging this". A green "Normal" on a bad reading is the
// worst thing this app could say, so these tests exist to keep it impossible.
test('vitalFlag never returns a "you are fine" verdict', () => {
  const healthy = [
    ['blood_pressure', 118, 76], ['blood_sugar', 90], ['heart_rate', 72],
    ['spo2', 98], ['temperature', 98.6, null, '°F'], ['temperature', 36.8, null, '°C'],
  ];
  for (const [t, a, b, u] of healthy) {
    const f = S.vitalFlag(t, a, b, u);
    if (f !== null) throw new Error(`${t} ${a} should get no badge, got ${f}`);
  }
});
test('vitalFlag: low SpO2 is never called normal', () => {
  // The regression that shipped: spo2 rows missed the config (it was keyed
  // oxygen_sat) and fell back to a hardcoded 'normal' — 85% rendered green.
  eq(S.vitalFlag('spo2', 85), 'low');
  eq(S.vitalFlag('spo2', 94), 'low');
});
test('vitalFlag: agrees with the reference text shown under the input', () => {
  eq(S.vitalFlag('blood_pressure', 138, 88), 'high');   // ref says High >130/>80
  eq(S.vitalFlag('blood_pressure', 124, 78), 'elevated');
  eq(S.vitalFlag('blood_pressure', 85, 55), 'low');
  eq(S.vitalFlag('blood_sugar', 130), 'high');
  eq(S.vitalFlag('blood_sugar', 65), 'low');
  eq(S.vitalFlag('heart_rate', 110), 'high');
});
test('vitalFlag: temperature reads its unit, not a guess', () => {
  eq(S.vitalFlag('temperature', 37, null, '°C'), null);    // normal, was "Low"
  eq(S.vitalFlag('temperature', 39, null, '°C'), 'high');
  eq(S.vitalFlag('temperature', 101, null, '°F'), 'high');
  eq(S.vitalFlag('temperature', 96, null, '°F'), 'low');
  eq(S.vitalFlag('temperature', 37, null, 'kelvin'), null);  // unplaceable -> silent
});
test('vitalFlag: stays silent when it cannot know', () => {
  eq(S.vitalFlag('unknown_type', 999), null);
  eq(S.vitalFlag('blood_sugar', 110), null);   // fasting state never asked -> no verdict
  eq(S.vitalFlag('blood_pressure', 130, null), 'high');
  eq(S.vitalFlag('blood_pressure', 118, null), null);  // null diastolic != "Low"
  eq(S.vitalFlag('heart_rate', NaN), null);
  eq(S.vitalFlag('heart_rate', undefined), null);
});

// ── Moods ──
// One `mood` column means one vocabulary. It grew two, and the lowest rung of
// the capture scale (`terrible`) existed in neither display map — so a day
// logged as "Rough" rendered a literal "undefined" at the user.
test('every mood the app can capture renders as itself', () => {
  // The 5-point scale used by the check-in, the quick-log sheet and the push
  // notification actions (static/sw.js), plus the journal's categorical set.
  // Each must map to its OWN emoji — not the 😐 fallback, which is how
  // "Rough" used to read as an average day.
  const captured = ['terrible', 'sad', 'happy', 'excited',
                    'calm', 'anxious', 'tired', 'angry'];
  const seen = new Set();
  for (const m of captured) {
    const e = S.moodEmoji(m);
    if (e === '😐') throw new Error(`${m} falls back to neutral — it has no emoji of its own`);
    if (seen.has(e)) throw new Error(`${m} shares an emoji with another mood (${e})`);
    seen.add(e);
    if (S.moodColor(m) === '#4F8D74') throw new Error(`${m} falls back to the default colour`);
  }
  eq(S.moodEmoji('neutral'), '😐');
});
test('moodEmoji never returns undefined, even for an unknown mood', () => {
  // The regression: `terrible` was in the capture scale but neither display
  // map, so the week dots printed a literal "undefined".
  eq(S.moodEmoji('terrible'), '😩');
  eq(S.moodEmoji('nonsense'), '😐');
  eq(S.moodEmoji(undefined), '😐');
  eq(S.moodEmoji(''), '😐');
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

// ── Count-by-piece quantity conversions ──
test('pluralUnit handles regular, -y, -ch and "half" units', () => {
  eq(S.pluralUnit('almond'), 'almonds');
  eq(S.pluralUnit('cherry'), 'cherries');
  eq(S.pluralUnit('strawberry'), 'strawberries');
  eq(S.pluralUnit('sandwich'), 'sandwiches');
  eq(S.pluralUnit('walnut half'), 'walnut halves');
  eq(S.pluralUnit('date'), 'dates');
});
test('trimG drops trailing .0 but keeps real decimals', () => {
  eq(S.trimG(40), '40');
  eq(S.trimG(1.2), '1.2');
  eq(S.trimG(8.8), '8.8');
});
test('_toGrams: count multiplies pieces by per-piece weight', () => {
  eq(S._toGrams(25, 'primary', 'count', 1.2), 30);   // 25 almonds ≈ 30 g
  eq(S._toGrams(2, 'primary', 'count', 24), 48);      // 2 dates = 48 g
  eq(S._toGrams(30, 'secondary', 'count', 1.2), 30);  // grams entered directly
});
test('_fromGrams: count rounds to whole pieces, never below 1', () => {
  eq(S._fromGrams(30, 'primary', 'count', 1.2), 25);  // 30 g ≈ 25 almonds
  eq(S._fromGrams(48, 'primary', 'count', 24), 2);
  eq(S._fromGrams(0.4, 'primary', 'count', 1.2), 1);  // never rounds to 0 pieces
});
test('count round-trip lands on the calories the DB would scale', () => {
  // one almond = 1.2 g, DB per-100g calories = 579  →  1 almond ≈ 7 kcal
  const grams = S._toGrams(1, 'primary', 'count', 1.2);
  eq(Math.round(579 * grams / 100), 7);
});

test('composeSpokenBriefing: greets by hour and names the next dose', () => {
  const doses = [
    { med_name: 'Metformin', time: '09:00', taken: true },
    { med_name: 'Aspirin',   time: '21:00', taken: false, timing_text: 'with food' },
  ];
  const txt = S.composeSpokenBriefing(doses, [], 8);
  if (!txt.startsWith('Good morning.')) throw new Error(`greeting: ${txt}`);
  if (!txt.includes('1 dose left today')) throw new Error(`count: ${txt}`);
  if (!txt.includes('Your next is Aspirin at 9:00 PM, with food.')) throw new Error(`next: ${txt}`);
});
test('composeSpokenBriefing: praises when all doses are taken', () => {
  const txt = S.composeSpokenBriefing([{ time: '09:00', taken: true }], [], 14);
  eq(txt, 'Good afternoon. You have taken all your doses today. Well done.');
});
test('composeSpokenBriefing: mentions low stock and uses evening greeting', () => {
  const txt = S.composeSpokenBriefing([], [{ name: 'X' }, { name: 'Y' }], 20);
  if (!txt.startsWith('Good evening.')) throw new Error(txt);
  if (!txt.includes('no medicines scheduled today')) throw new Error(txt);
  if (!txt.includes('2 medicines are running low.')) throw new Error(txt);
});

test('t(): identity in English (no stored pref) and for untranslated keys', () => {
  eq(S.t('Home'), 'Home');                        // stub localStorage → 'en'
  eq(S.t('Something never translated'), 'Something never translated');
});
test('t(): translates the whole nav surface to Devanagari when lang=hi', () => {
  const orig = S.localStorage.getItem;
  S.localStorage.getItem = () => 'hi';            // force Hindi
  const dev = /[ऀ-ॿ]/;
  try {
    eq(S.t('Home'), 'होम');
    for (const k of ['Home','Food','Meds','Sleep','More','Dashboard','Medicines',
                     'Medical','Body & Vitals','Family','Fitness','Habits','Journal',
                     'Tasks','Progress','Alerts','Food & Water','Notifications',
                     'Care','Track']) {
      const v = S.t(k);
      if (v === k || !dev.test(v)) throw new Error(`"${k}" not translated → "${v}"`);
    }
  } finally { S.localStorage.getItem = orig; }
});

test('tformat: fills %1/%2 placeholders after translation', () => {
  eq(S.tformat('%1 of %2 doses taken', 3, 5), '3 of 5 doses taken');   // English: key verbatim
  const orig = S.localStorage.getItem;
  S.localStorage.getItem = () => 'hi';
  try {
    const out = S.tformat('%1 of %2 doses taken', 3, 5);
    if (!out.includes('3') || !out.includes('5')) throw new Error(out);   // numbers survive
    if (/%\d/.test(out)) throw new Error('placeholder left unfilled: ' + out);
    if (!/[ऀ-ॿ]/.test(out)) throw new Error('not translated: ' + out);
  } finally { S.localStorage.getItem = orig; }
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
