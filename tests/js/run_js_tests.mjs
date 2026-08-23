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
test('parseQuickCommand: weight states the unit it will store', () => {
  // Default preference is kg, so a bare number is kg and the label says so.
  eq(S.parseQuickCommand('weight 72.5').label, 'Log weight 72.5 kg');
  eq(S.parseQuickCommand('weight 90kg').label, 'Log weight 90 kg');
  // An EXPLICIT unit must win and be reflected honestly in the label — a user
  // who says "lb" must never be told (or have stored) kg.
  eq(S.parseQuickCommand('weight 154 lb').label, 'Log weight 154 lb');
  eq(S.parseQuickCommand('weight 154 pounds').label, 'Log weight 154 lb');
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

// ── Unit converters ──
// Data is stored canonically (kg / mg-dL / °C-or-°F as logged); these only
// convert at the display and input edges. A round-trip must not drift, or a
// user toggling units would slowly corrupt their own record.
test('kg↔lb converts and round-trips without drift', () => {
  eq(S.kgToLb(70), 154.3);
  eq(S.lbToKg(154.3), 69.99);
  // a realistic entry survives a there-and-back trip within a rounding step
  const back = S.lbToKg(S.kgToLb(82.5));
  eq(Math.abs(back - 82.5) < 0.05, true);
});
test('mg/dL ↔ mmol/L uses the 18 factor and round-trips', () => {
  eq(S.mgdlToMmol(180), 10);
  eq(S.mmolToMgdl(10), 180);
  eq(S.mgdlToMmol(99), 5.5);
  const back = S.mmolToMgdl(S.mgdlToMmol(126));
  eq(Math.abs(back - 126) <= 2, true);          // within one 0.1 mmol step
});
test('°C ↔ °F converts at the known anchors', () => {
  eq(S.cToF(37), 98.6);
  eq(S.fToC(98.6), 37);
  eq(S.cToF(0), 32);
  eq(S.fToC(212), 100);
});
test('converters treat blank/garbage as zero, never NaN', () => {
  for (const f of ['kgToLb', 'lbToKg', 'cToF', 'mgdlToMmol', 'mmolToMgdl']) {
    eq(Number.isNaN(S[f](null)), false);
    eq(Number.isNaN(S[f]('abc')), false);
  }
});
// The INPUT converters decide what is written to the database. A missed or
// doubled conversion here silently corrupts a health record, so they are tested
// at a NON-default preference — the gap that let the first cut ship broken.
test('weightInputToKg converts only when the preference is lb', () => {
  S.setUserUnits({ weight: 'kg' });
  eq(S.weightInputToKg(70), 70);                 // kg user: stored as typed
  S.setUserUnits({ weight: 'lb' });
  eq(S.weightInputToKg(154.3), 69.99);           // lb user: converted to kg
  S.setUserUnits({ weight: 'kg' });               // restore
});
test('glucoseInputToMgdl converts only when the preference is mmol', () => {
  S.setUserUnits({ glucose: 'mgdl' });
  eq(S.glucoseInputToMgdl(110), 110);            // mg/dL user: stored as typed
  S.setUserUnits({ glucose: 'mmol' });
  eq(S.glucoseInputToMgdl(7.2), 130);            // mmol user: 7.2 → 130 mg/dL
  eq(S.glucoseInputToMgdl(22), 396);             // a high reading stays high
  S.setUserUnits({ glucose: 'mgdl' });            // restore
});
test('an mmol reading never lands in the mg/dL "low" band', () => {
  // The bug this guards: 22 mmol/L (an emergency) stored raw as 22 mg/dL would
  // be flagged "low" — the exact inverse of the truth.
  S.setUserUnits({ glucose: 'mmol' });
  const stored = S.glucoseInputToMgdl(22);
  eq(stored > 125, true);                        // reads as high, not low
  S.setUserUnits({ glucose: 'mgdl' });
});
test('display helpers follow the preference without an explicit opt', () => {
  S.setUserUnits({ weight: 'lb', glucose: 'mmol' });
  eq(S.fmtWeight(70), '154.3 lb');
  eq(S.fmtGlucose(180), '10 mmol/L');
  eq(S.weightUnitLabel(), 'lb');
  eq(S.glucoseUnitLabel(), 'mmol/L');
  S.setUserUnits({ weight: 'kg', glucose: 'mgdl' });
  eq(S.fmtWeight(70), '70 kg');
  eq(S.fmtGlucose(180), '180 mg/dL');
});
test('quick-command glucose converts and labels in the user unit', () => {
  S.setUserUnits({ glucose: 'mmol' });
  const c = S.parseQuickCommand('sugar 7.2');
  eq(c.label, 'Log blood sugar 7.2 mmol/L');     // honest label
  eq(/130/.test(c.ev), true);                    // stores canonical mg/dL
  S.setUserUnits({ glucose: 'mgdl' });
});
test('voice weight honours a spoken unit over the preference', () => {
  S.setUserUnits({ weight: 'kg' });
  const spoken = S.parseVoiceCommand('weight 154 pounds');
  eq(spoken.label, 'Weight 154 lb');              // says what it heard
  eq(Math.abs(spoken.kg - 69.85) < 0.2, true);    // stores kg
});

test('fmtWeight / fmtGlucose render the requested unit', () => {
  eq(S.fmtWeight(70, {unit: 'kg'}), '70 kg');
  eq(S.fmtWeight(70, {unit: 'lb'}), '154.3 lb');
  eq(S.fmtGlucose(180, {unit: 'mgdl'}), '180 mg/dL');
  eq(S.fmtGlucose(180, {unit: 'mmol'}), '10 mmol/L');
  // nothing logged → nothing shown (never a fabricated 0)
  eq(S.fmtWeight(null), '');
  eq(S.fmtGlucose(null), '');
});

// ── Voice command parser (natural spoken phrasing) ──
test('parseVoiceCommand: blood pressure, natural phrasing', () => {
  const c = S.parseVoiceCommand('blood pressure 120 over 80');
  eq(c.kind, 'vital'); eq(c.type, 'blood_pressure'); eq(c.value1, 120); eq(c.value2, 80);
  eq(S.parseVoiceCommand('BP 128 / 82').value1, 128);
});
test('parseVoiceCommand: sugar / heart rate / oxygen / weight', () => {
  eq(S.parseVoiceCommand('blood sugar 110').type, 'blood_sugar');
  eq(S.parseVoiceCommand('my heart rate is 72').type, 'heart_rate');
  eq(S.parseVoiceCommand('pulse 58').value1, 58);
  eq(S.parseVoiceCommand('oxygen 97').type, 'spo2');
  eq(S.parseVoiceCommand('weight 70 kilos').kg, 70);
});
test('parseVoiceCommand: water defaults to a glass, or uses the amount', () => {
  eq(S.parseVoiceCommand('a glass of water').ml, 250);
  eq(S.parseVoiceCommand('i drank 500 ml of water').ml, 500);
});
test('parseVoiceCommand: mark a dose taken', () => {
  eq(S.parseVoiceCommand('I took my morning pills').kind, 'dose');
  eq(S.parseVoiceCommand('marked my dose as taken').kind, 'dose');
});
test('parseVoiceCommand: spoken number-words fold to digits', () => {
  eq(S._spokenNumbers('seventy two'), '72');
  eq(S._spokenNumbers('one hundred twenty'), '120');
  eq(S.parseVoiceCommand('heart rate seventy two').value1, 72);
});
test('parseVoiceCommand: rejects chatter and impossible readings', () => {
  eq(S.parseVoiceCommand('hello how are you'), null);
  eq(S.parseVoiceCommand(''), null);
  eq(S.parseVoiceCommand('blood pressure 400 over 300'), null);   // out of range
  eq(S.parseVoiceCommand('blood pressure 80 over 120'), null);    // systolic must exceed diastolic
});
test('parseVoiceCommand: never fabricates a value it did not hear', () => {
  // a bare vital word with no number must not invent a reading
  eq(S.parseVoiceCommand('blood pressure'), null);
  eq(S.parseVoiceCommand('what is my sugar'), null);
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

// ── I6: lab reference-band gauge (_labBandBar) ──
function _bandMarkPct(html) {
  const m = /lab-band-mark[^"]*"[^>]*left:([\d.]+)%/.exec(html);
  return m ? parseFloat(m[1]) : null;
}
test('_labBandBar: value at range midpoint sits at 50%', () => {
  const html = S._labBandBar({ name: 'HbA1c', value: 4.8, ref_low: 4.0, ref_high: 5.6, status: 'in_range' });
  const pct = _bandMarkPct(html);
  if (Math.abs(pct - 50) > 0.5) throw new Error('midpoint not centered: ' + pct);
  if (!html.includes('lab-ok')) throw new Error('in-range should use lab-ok class');
});
test('_labBandBar: value above range marks past the zone and flags high', () => {
  const html = S._labBandBar({ name: 'LDL', value: 190, ref_low: 0, ref_high: 100, status: 'high' });
  const pct = _bandMarkPct(html);
  if (!(pct > 60)) throw new Error('high value should sit right of centre: ' + pct);
  if (!html.includes('lab-high')) throw new Error('high status should use lab-high class');
});
test('_labBandBar: renders nothing without a usable range', () => {
  eq(S._labBandBar({ name: 'X', value: 5, ref_low: null, ref_high: null, status: null }), '');
  eq(S._labBandBar({ name: 'X', value: 5, ref_low: 10, ref_high: 10, status: null }), '');   // degenerate
  eq(S._labBandBar({ name: 'X', value: NaN, ref_low: 1, ref_high: 2, status: null }), '');
});
test('_labBandBar: far-out value is clamped to the track edge', () => {
  const html = S._labBandBar({ name: 'TSH', value: 999, ref_low: 0.4, ref_high: 4.0, status: 'high' });
  const pct = _bandMarkPct(html);
  if (pct !== 100) throw new Error('should clamp to 100%: ' + pct);
  if (!html.includes('lab-band-mark--edge')) throw new Error('edge marker class missing');
});

test('_pageMatches: finds a page by its label and by a keyword', () => {
  // Label match.
  const byLabel = S._pageMatches('lab').map(t => t.v);
  if (!byLabel.includes('labs')) throw new Error('should match Lab results by label: ' + byLabel);
  // A plural query still finds the singular label ("labs" → "Lab results").
  const plural = S._pageMatches('labs').map(t => t.v);
  if (!plural.includes('labs')) throw new Error('plural query should still match: ' + plural);
  // Keyword-only match (the word "dentist" isn't in the label "Dental & vision").
  const byKw = S._pageMatches('dentist').map(t => t.v);
  if (!byKw.includes('dentalvision')) throw new Error('should match via keyword: ' + byKw);
});
test('_pageMatches: ranks a label-prefix hit above a keyword-only hit', () => {
  // "sleep" is the Sleep page's label and also a Body/Vitals-adjacent word; the
  // page whose label starts with the query must come first.
  const r = S._pageMatches('sleep');
  if (!r.length || r[0].v !== 'sleep') throw new Error('Sleep page should rank first: ' + JSON.stringify(r.map(t => t.v)));
});
test('_pageMatches: short/empty queries return nothing, and caps at 6', () => {
  eq(S._pageMatches('a').length, 0);
  eq(S._pageMatches('').length, 0);
  if (S._pageMatches('e').length > 6) throw new Error('should cap results at 6');
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
