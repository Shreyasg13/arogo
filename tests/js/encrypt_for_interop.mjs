// tests/js/encrypt_for_interop.mjs — write an encrypted export using the REAL
// browser-side code, so Python can try to open it.
//
//   node tests/js/encrypt_for_interop.mjs "<plaintext>" "<passphrase>"
//
// Used by tests/test_export_encryption.py. The point is that neither side
// reimplements the format: this loads static/js/app.js exactly as the browser
// runs it, and scripts/decrypt_export.py reads the result with nothing but the
// header. If the two ever drift, that test fails — which is the only way to
// keep "your export opens without Arogo" an honest claim rather than a hope.
import fs from 'fs';
import vm from 'vm';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'static', 'js', 'app.js'), 'utf8');

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
  navigator: {},
  localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  location: { search: '', pathname: '/', reload: noop },
  history: { replaceState: noop },
  fetch: () => Promise.resolve({ ok: false, json: async () => ({}), headers: { get: () => '' } }),
  setTimeout, clearTimeout, setInterval: noop, clearInterval: noop,
  console, atob: s => Buffer.from(s, 'base64').toString('binary'),
  btoa: s => Buffer.from(s, 'binary').toString('base64'),
  URLSearchParams, Uint8Array, JSON, Math, Date, Promise, Object, Array,
  Intl, parseFloat, parseInt, isNaN, String, Number, Boolean, RegExp, Error,
  crypto: globalThis.crypto, TextEncoder, TextDecoder,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.window.addEventListener = noop;
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: 'app.js' });

const [plaintext, passphrase] = process.argv.slice(2);
sandbox.arogoEncrypt(plaintext, passphrase).then(out => {
  process.stdout.write(out);
}).catch(e => {
  console.error(String(e && e.message || e));
  process.exit(1);
});
