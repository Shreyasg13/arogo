// ════════════════════════════════════════════════════════════════
// AUTH — login / register / session management
// Runs before anything else. Shows auth screen if unauthenticated.
// ════════════════════════════════════════════════════════════════

let _currentUser = null;

// ── Theme (light / dark) ──────────────────────────────────────────
// Applied as early as possible; stored choice wins, otherwise the OS
// preference decides. (Inline <script> is blocked by CSP, so a brief
// first-paint flash on the very first load is expected.)
(function initTheme() {
  const stored = localStorage.getItem('me_theme');
  const dark = stored ? stored === 'dark'
    : (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  if (dark) document.documentElement.dataset.theme = 'dark';
})();

function _syncThemeToggleUI() {
  const dark = document.documentElement.dataset.theme === 'dark';
  const icon = document.getElementById('theme-toggle-icon');
  const label = document.getElementById('theme-toggle-label');
  if (icon)  icon.textContent  = dark ? '☀️' : '🌙';
  if (label) label.textContent = dark ? 'Light mode' : 'Dark mode';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#191612' : '#20362D';
}

function toggleTheme() {
  const el = document.documentElement;
  const dark = el.dataset.theme !== 'dark';
  if (dark) el.dataset.theme = 'dark';
  else delete el.dataset.theme;
  localStorage.setItem('me_theme', dark ? 'dark' : 'light');
  _syncThemeToggleUI();
}

document.addEventListener('DOMContentLoaded', _syncThemeToggleUI);
document.addEventListener('DOMContentLoaded', _syncSimpleToggleUI);

// ── Simple View (senior / large-type mode) ────────────────────────
// A second display axis alongside dark/light. 'simple' enlarges text and
// tap targets, raises contrast, and collapses the nav to the essentials.
// localStorage me_ui_mode is the source of truth for a no-flash first paint;
// the profile.ui_mode column mirrors it so the choice follows the user across
// devices (and lets a caregiver set it for the patient). Values:
//   'simple'   → large UI on
//   'standard' → explicitly declined (do not re-prompt)
//   (absent)   → never chosen (age>=60 prompt may still offer it)
(function initUiMode() {
  try {
    if (localStorage.getItem('me_ui_mode') === 'simple')
      document.documentElement.dataset.mode = 'simple';
  } catch (e) {}
})();

function _syncSimpleToggleUI() {
  const on = document.documentElement.dataset.mode === 'simple';
  const icon  = document.getElementById('simple-toggle-icon');
  const label = document.getElementById('simple-toggle-label');
  if (icon)  icon.textContent  = on ? '🔎' : '🔍';
  if (label) label.textContent = on ? 'Standard view' : 'Simple view';
}

function applyUiMode(mode) {
  const el = document.documentElement;
  if (mode === 'simple') el.dataset.mode = 'simple';
  else delete el.dataset.mode;
  _syncSimpleToggleUI();
}

// Persist a choice both locally (instant, no-flash next load) and to the
// profile (cross-device). `mode` is 'simple' or 'standard'.
function setUiMode(mode) {
  applyUiMode(mode);
  try { localStorage.setItem('me_ui_mode', mode); } catch (e) {}
  fetch('/api/food/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ ui_mode: mode }),
  }).catch(() => {});
}

function toggleSimpleMode() {
  setUiMode(document.documentElement.dataset.mode === 'simple' ? 'standard' : 'simple');
  dismissSimplePrompt();
}

// One-time offer shown to users aged 60+ who haven't chosen a view yet.
function offerSimpleMode() {
  if (document.getElementById('simple-prompt')) return;
  const card = document.createElement('div');
  card.id = 'simple-prompt';
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', 'Simple view offer');
  card.innerHTML =
    '<div class="simple-prompt-inner">' +
      '<div class="simple-prompt-icon">🔎</div>' +
      '<div class="simple-prompt-title">Prefer bigger text?</div>' +
      '<div class="simple-prompt-body">Simple View makes text larger, buttons easier to tap, ' +
        'and keeps just the essentials on screen. You can switch back any time in Settings.</div>' +
      '<div class="simple-prompt-actions">' +
        '<button class="simple-prompt-yes" type="button">Turn on Simple View</button>' +
        '<button class="simple-prompt-no" type="button">No thanks</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(card);
  card.querySelector('.simple-prompt-yes').addEventListener('click', () => { setUiMode('simple'); dismissSimplePrompt(); });
  card.querySelector('.simple-prompt-no').addEventListener('click', () => { setUiMode('standard'); dismissSimplePrompt(); });
}

function dismissSimplePrompt() {
  const card = document.getElementById('simple-prompt');
  if (card) card.remove();
}

// Reconcile with the server profile: adopt a cross-device choice if this
// device hasn't decided, then offer Simple View to 60+ users who never have.
function reconcileUiMode(profile) {
  if (!profile) return;
  let local = null;
  try { local = localStorage.getItem('me_ui_mode'); } catch (e) {}
  const server = profile.ui_mode || null;   // 'simple' | 'standard' | null
  if (!local && server) {
    // Another device chose for this account — honour it here too.
    applyUiMode(server);
    try { localStorage.setItem('me_ui_mode', server); } catch (e) {}
    local = server;
  }
  const decided = local || server;          // any explicit choice, anywhere
  const age = parseInt(profile.age, 10);
  if (!decided && Number.isFinite(age) && age >= 60) offerSimpleMode();
}

// ── CSP-safe event dispatch ───────────────────────────────────────
// Inline on*="…" attributes are blocked by our Content-Security-Policy
// (script-src carries no 'unsafe-inline'). Markup uses data-ev-click /
// data-ev-change / data-ev-input / data-ev-keydown instead, and this
// dispatcher interprets the expression WITHOUT eval: semicolon-separated
// calls fn(arg,…) where each arg is a string/number/bool literal, `this`,
// `event`, `this.value`, `this.checked`, or a JSON object/array.

function _evTokenize(expr, sep) {
  // Split on `sep` at bracket depth 0, outside quotes
  const parts = [];
  let depth = 0, q = null, cur = '';
  for (let i = 0; i < expr.length; i++) {
    const ch = expr[i];
    if (q) {
      cur += ch;
      if (ch === '\\') cur += expr[++i] || '';
      else if (ch === q) q = null;
    } else if (ch === "'" || ch === '"') { q = ch; cur += ch; }
    else if ('([{'.includes(ch)) { depth++; cur += ch; }
    else if (')]}'.includes(ch)) { depth--; cur += ch; }
    else if (ch === sep && depth === 0) { parts.push(cur); cur = ''; }
    else cur += ch;
  }
  if (cur.trim()) parts.push(cur);
  return parts.map(s => s.trim()).filter(Boolean);
}

function _evArg(a, el, ev) {
  if (a === 'this')         return el;
  if (a === 'event')        return ev;
  if (a === 'this.value')   return el.value;
  if (a === 'this.checked') return el.checked;
  if (a === 'true')  return true;
  if (a === 'false') return false;
  if (a === 'null')  return null;
  if (/^-?\d+(\.\d+)?$/.test(a)) return parseFloat(a);
  if ((a[0] === "'" || a[0] === '"') && a[a.length - 1] === a[0])
    return a.slice(1, -1).replace(/\\(['"\\])/g, '$1');
  if (a[0] === '{' || a[0] === '[') return JSON.parse(a);
  console.warn('[ev] unsupported arg:', a);
  return undefined;
}

function _evRun(expr, el, ev) {
  for (const stmt of _evTokenize(expr, ';')) {
    if (stmt === 'return false' ||
        stmt === 'event.preventDefault()') { ev.preventDefault(); continue; }
    if (stmt === 'event.stopPropagation()') { ev.stopPropagation(); continue; }
    const m = stmt.match(/^([A-Za-z_$][\w$]*)\((.*)\)$/s);
    if (!m || typeof window[m[1]] !== 'function') {
      console.warn('[ev] unsupported statement:', stmt);
      continue;
    }
    window[m[1]].apply(el, _evTokenize(m[2], ',').map(a => _evArg(a, el, ev)));
  }
}

for (const _t of ['click', 'change', 'input', 'keydown']) {
  document.addEventListener(_t, ev => {
    const el = ev.target && ev.target.closest && ev.target.closest(`[data-ev-${_t}]`);
    if (!el) return;
    if (el.tagName === 'A') ev.preventDefault();
    try { _evRun(el.getAttribute(`data-ev-${_t}`), el, ev); }
    catch (err) { console.error('[ev]', el.getAttribute(`data-ev-${_t}`), err); }
  });
}

// Named replacements for what used to be inline JS expressions
function hideEl(id)  { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
function clickEl(id) { const el = document.getElementById(id); if (el) el.click(); }
function backdropClose(ev, el, fnName) { if (ev.target === el) window[fnName](); }
function quickAdd(view) {
  switchView(view);
  const openers = { food: 'openAddFoodModal', fitness: 'openActivityModal', todos: 'openTodoModal' };
  setTimeout(() => { const f = window[openers[view]]; if (f) f(); }, 200);
}
function enterAddCustomSymptom(ev) {
  if (ev.key === 'Enter') { addCustomSymptom(); ev.preventDefault(); }
}
function setGymField(subId, i, field, val) {
  if (typeof gymSets !== 'undefined' && gymSets[subId] && gymSets[subId][i])
    gymSets[subId][i][field] = val;
}

// ── Undo toast (replaces confirm() dialogs) ──────────────────────
// Destructive actions run after a short grace window with a visible
// Undo button, instead of interrupting with a browser confirm().
let _pendingUndoable = null;

function undoable(message, commit, delayMs = 4500) {
  // Starting a new action commits any still-pending one immediately
  if (_pendingUndoable) _pendingUndoable.flush();

  const bar = document.createElement('div');
  bar.style.cssText =
    'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
    'background:var(--gray-900);color:#fff;padding:12px 18px;border-radius:12px;' +
    'display:flex;align-items:center;gap:16px;font-size:13px;z-index:10000;' +
    'box-shadow:0 8px 24px rgba(0,0,0,.28);font-family:inherit;max-width:90vw';
  const txt = document.createElement('span');
  txt.textContent = message;
  const btn = document.createElement('button');
  btn.textContent = 'Undo';
  btn.style.cssText =
    'background:none;border:none;color:#5EEAD4;font-weight:700;font-size:13px;' +
    'cursor:pointer;padding:0;font-family:inherit';
  bar.append(txt, btn);
  document.body.appendChild(bar);

  let settled = false;
  const timer = setTimeout(run, delayMs);

  async function run() {
    if (settled) return;
    settled = true;
    bar.remove();
    _pendingUndoable = null;
    try { await commit(); }
    catch (e) { showToast('Action failed', 'error'); console.error('[undoable]', e); }
  }
  btn.addEventListener('click', () => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    bar.remove();
    _pendingUndoable = null;
  });
  _pendingUndoable = { flush: () => { clearTimeout(timer); run(); } };
}

// ── Date helpers — always use LOCAL date, never UTC ───────────
// new Date().toISOString() returns UTC — wrong for users in UTC+N timezones.
// Example: in India (UTC+5:30) at 11pm, toISOString() gives yesterday's date.
function localToday() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function localDatetime(date) {
  // Return YYYY-MM-DDTHH:MM in local time for datetime-local inputs
  const d = date || new Date();
  const y  = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  const h  = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${mo}-${da}T${h}:${mi}`;
}

function browserTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

// Called on page load — check if we have a valid session
async function initAuth() {
  // Arriving from a password-reset email link (/?reset=TOKEN)
  const resetToken = new URLSearchParams(location.search).get('reset');
  if (resetToken) {
    _resetToken = resetToken;
    showAuthScreen();
    showAuthForm('auth-form-reset');
    return;
  }
  // Arriving from a family invite link (/?family_invite=TOKEN) —
  // stash it; it's redeemed in showApp() once the user is signed in
  const inviteToken = new URLSearchParams(location.search).get('family_invite');
  if (inviteToken) {
    sessionStorage.setItem('me_family_invite', inviteToken);
    history.replaceState({}, '', location.pathname);
  }
  // Landing back from the email verification link (/?verified=1|0)
  const verified = new URLSearchParams(location.search).get('verified');
  if (verified !== null) {
    history.replaceState({}, '', location.pathname);
    setTimeout(() => showToast(
      verified === '1' ? 'Email verified ✅'
                       : 'Verification link is invalid or expired', verified === '1' ? '' : 'error'), 400);
  }
  const r = await fetch('/auth/me', {credentials: 'same-origin'}).catch(() => null);
  if (r && r.ok) {
    _currentUser = await r.json();
    showApp();
  } else {
    showAuthScreen();
  }
}

function showAuthScreen() {
  const screen = document.getElementById('auth-screen');
  const sidebar = document.getElementById('app-sidebar');
  const main    = document.getElementById('app-main');
  if (screen)  screen.style.display = '';
  if (sidebar) sidebar.style.display = 'none';
  if (main)    main.style.display    = 'none';
  const fab = document.getElementById('quick-fab');
  if (fab) fab.style.display = 'none';
  const tabbar = document.getElementById('mobile-tabbar');
  if (tabbar) tabbar.style.visibility = 'hidden';
}

function showApp() {
  const screen  = document.getElementById('auth-screen');
  const sidebar = document.getElementById('app-sidebar');
  const main    = document.getElementById('app-main');
  if (screen)  screen.style.display  = 'none';
  if (sidebar) sidebar.style.display = '';
  if (main)    main.style.display    = '';
  const fab = document.getElementById('quick-fab');
  if (fab) fab.style.display = 'flex';
  const tabbar = document.getElementById('mobile-tabbar');
  if (tabbar) tabbar.style.visibility = '';

  // Populate user name in header
  const nameEl = document.getElementById('header-user-name');
  if (nameEl && _currentUser) nameEl.textContent = _currentUser.name || _currentUser.email;

  // Nudge unverified accounts (banner has a resend button)
  const vBanner = document.getElementById('verify-banner');
  if (vBanner) vBanner.style.display =
    (_currentUser && _currentUser.verified === false) ? 'flex' : 'none';

  // Sync browser timezone to profile (silently, no await needed)
  fetch('/api/food/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({ timezone: browserTimezone() }),
  }).then(r => r.ok ? r.json() : null)
    .then(d => { if (d && d.profile) reconcileUiMode(d.profile); })
    .catch(() => {});

  // Run all setup functions that DOMContentLoaded used to run
  try { setGreeting(); }             catch(e) {}
  try { setDates(); }                catch(e) {}
  try { setupNavigation(); }         catch(e) {}
  try { setupDropzone(); }           catch(e) {}
  try { setupTagPicker(); }          catch(e) {}
  try { setupUploadForm(); }         catch(e) {}
  try { setupMedForm(); }            catch(e) {}
  try { setupActivityForm(); }       catch(e) {}
  try { setupIconColorPicker(); }    catch(e) {}
  try { setupFreqPicker(); }         catch(e) {}
  try { setupActivityTypePicker(); } catch(e) {}
  try { setupFilters(); }            catch(e) {}
  try { updateSidebarUser(); }       catch(e) {}
  try { checkNotifPermission(); }    catch(e) {}
  try { setupPushSubscription(); }   catch(e) {}
  try { scheduleTodoReminderChecks(); } catch(e) {}

  const tdp = document.getElementById('thoughts-date-picker');
  if (tdp) tdp.value = localToday();

  // Redeem a pending family invite (user arrived via emailed link)
  const inviteToken = sessionStorage.getItem('me_family_invite');
  if (inviteToken) {
    sessionStorage.removeItem('me_family_invite');
    fetch('/api/family/invite/accept', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin', body: JSON.stringify({token: inviteToken}),
    }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (r.ok) { showToast('You joined the family group 🎉'); switchView('family'); }
      else      { showToast(d.error || 'Invite could not be accepted', 'error'); switchView('dashboard'); }
    }).catch(() => switchView('dashboard'));
    return;
  }

  // Load the dashboard
  switchView('dashboard');
}

// Show one auth form, hide the others (login / register / forgot / reset)
function showAuthForm(id) {
  for (const f of ['auth-form-login', 'auth-form-register', 'auth-form-forgot', 'auth-form-reset']) {
    const el = document.getElementById(f);
    if (el) el.style.display = (f === id) ? '' : 'none';
  }
  hideAuthError();
  hideAuthSuccess();
}

function switchAuthTab(tab) {
  const isLogin = tab === 'login';
  showAuthForm(isLogin ? 'auth-form-login' : 'auth-form-register');
  document.getElementById('auth-tab-login').style.background    = isLogin ? 'var(--gray-0)' : 'transparent';
  document.getElementById('auth-tab-login').style.color         = isLogin ? 'var(--gray-800)' : 'var(--gray-400)';
  document.getElementById('auth-tab-register').style.background = isLogin ? 'transparent' : 'var(--gray-0)';
  document.getElementById('auth-tab-register').style.color      = isLogin ? 'var(--gray-400)' : 'var(--gray-800)';
}

function showForgotForm() { showAuthForm('auth-form-forgot'); }
function backToLogin()    { switchAuthTab('login'); }

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  if (el) { el.textContent = msg; el.style.display = ''; }
}
function hideAuthError() {
  const el = document.getElementById('auth-error');
  if (el) el.style.display = 'none';
}
function showAuthSuccess(msg) {
  const el = document.getElementById('auth-success');
  if (el) { el.textContent = msg; el.style.display = ''; }
}
function hideAuthSuccess() {
  const el = document.getElementById('auth-success');
  if (el) el.style.display = 'none';
}

function setAuthBtnLoading(id, loading, label) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.disabled    = loading;
  btn.textContent = loading ? 'Please wait…' : label;
}

async function submitLogin() {
  hideAuthError();
  const email = (document.getElementById('login-email')?.value || '').trim();
  const pw    = document.getElementById('login-password')?.value || '';
  if (!email || !pw) { showAuthError('Please enter your email and password'); return; }

  setAuthBtnLoading('login-btn', true, 'Sign in');

  let r, data;
  try {
    r = await fetch('/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({email, password: pw}),
    });
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      data = await r.json();
    } else {
      const text = await r.text();
      data = { error: `Server error (${r.status}): route not found. Check Flask is running the latest app.py.` };
    }
  } catch (err) {
    setAuthBtnLoading('login-btn', false, 'Sign in');
    showAuthError('Could not reach server. Is Flask running?');
    console.error('Login fetch error:', err);
    return;
  }

  setAuthBtnLoading('login-btn', false, 'Sign in');

  if (!r.ok) {
    showAuthError(data.error || 'Login failed');
    return;
  }

  _currentUser = data.user;
  await new Promise(res => setTimeout(res, 50));
  showApp();
}

async function submitRegister() {
  hideAuthError();
  const email = (document.getElementById('reg-email')?.value || '').trim();
  const pw    = document.getElementById('reg-password')?.value || '';
  const name  = (document.getElementById('reg-name')?.value || '').trim();

  if (!email) { showAuthError('Please enter your email address'); return; }
  if (!pw)    { showAuthError('Please enter a password (8+ characters)'); return; }

  setAuthBtnLoading('register-btn', true, 'Create account');

  let r, data;
  try {
    r = await fetch('/auth/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({ name: name || email.split('@')[0], email, password: pw }),
    });
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      data = await r.json();
    } else {
      const text = await r.text();
      data = { error: `Server error (${r.status}): ${text.slice(0, 120)}` };
    }
  } catch (err) {
    setAuthBtnLoading('register-btn', false, 'Create account');
    showAuthError('Could not reach server. Is Flask running?');
    console.error('Register fetch error:', err);
    return;
  }

  setAuthBtnLoading('register-btn', false, 'Create account');

  if (!r.ok) {
    showAuthError(data.error || 'Registration failed');
    return;
  }

  _currentUser = data.user;
  await new Promise(res => setTimeout(res, 50));
  // New users go through onboarding before seeing the dashboard
  showOnboarding();
}

let _resetToken = null;

async function submitForgot() {
  hideAuthError(); hideAuthSuccess();
  const email = (document.getElementById('forgot-email')?.value || '').trim();
  if (!email) { showAuthError('Please enter your email address'); return; }

  setAuthBtnLoading('forgot-btn', true, 'Send reset link');
  try {
    const r = await fetch('/auth/forgot-password', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({email}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { showAuthError(data.error || 'Could not send reset link'); return; }
    showAuthSuccess(data.message || 'If that email is registered, a reset link is on its way.');
  } catch (err) {
    showAuthError('Could not reach server. Is Flask running?');
    console.error('Forgot-password fetch error:', err);
  } finally {
    setAuthBtnLoading('forgot-btn', false, 'Send reset link');
  }
}

async function submitReset() {
  hideAuthError(); hideAuthSuccess();
  const pw = document.getElementById('reset-password')?.value || '';
  if (!pw)          { showAuthError('Please choose a new password (8+ characters)'); return; }
  if (!_resetToken) { showAuthError('Reset link missing — open the link from your email again.'); return; }

  setAuthBtnLoading('reset-btn', true, 'Set new password');
  try {
    const r = await fetch('/auth/reset-password', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({token: _resetToken, password: pw}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { showAuthError(data.error || 'Password reset failed'); return; }
    _resetToken = null;
    history.replaceState({}, '', location.pathname);   // drop ?reset=… from the URL
    switchAuthTab('login');
    showAuthSuccess(data.message || 'Password updated. You can log in now.');
  } catch (err) {
    showAuthError('Could not reach server. Is Flask running?');
    console.error('Reset-password fetch error:', err);
  } finally {
    setAuthBtnLoading('reset-btn', false, 'Set new password');
  }
}

async function resendVerification() {
  const r = await fetch('/auth/resend-verification', {method: 'POST', credentials: 'same-origin'})
    .catch(() => null);
  const d = r ? await r.json().catch(() => ({})) : {};
  if (r && r.ok) showToast(d.message || 'Verification email sent');
  else           showToast(d.error || 'Could not send verification email', 'error');
}

async function signOut() {
  await fetch('/auth/logout', {method: 'POST', credentials: 'same-origin'});
  _currentUser = null;
  showAuthScreen();
}

// ── Celebrations: confetti + milestone card ───────────────────────
const STREAK_MILESTONES = [7, 30, 100, 365];

function confettiBurst() {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colors = ['#4F8D74', '#5E8299', '#E0A34E', '#D07D4E', '#C15646', '#5A9E70'];
  const n = 42;
  for (let i = 0; i < n; i++) {
    const p = document.createElement('div');
    const size = 6 + Math.random() * 6;
    p.style.cssText =
      `position:fixed;top:-12px;left:${8 + Math.random() * 84}vw;z-index:10001;` +
      `width:${size}px;height:${size * 0.6}px;pointer-events:none;` +
      `background:${colors[i % colors.length]};border-radius:2px`;
    document.body.appendChild(p);
    const fall = p.animate([
      { transform: 'translateY(0) rotate(0deg)', opacity: 1 },
      { transform: `translateY(${70 + Math.random() * 25}vh) ` +
                   `translateX(${(Math.random() - 0.5) * 30}vw) ` +
                   `rotate(${360 + Math.random() * 540}deg)`, opacity: 0 },
    ], { duration: 1600 + Math.random() * 1200, easing: 'cubic-bezier(.2,.6,.4,1)' });
    fall.onfinish = () => p.remove();
  }
}

function celebrate(title, sub = '') {
  confettiBurst();
  const card = document.createElement('div');
  card.style.cssText =
    'position:fixed;top:38%;left:50%;transform:translate(-50%,-50%) scale(.9);' +
    'background:var(--gray-0);border:1px solid var(--gray-100);border-radius:18px;' +
    'padding:26px 34px;text-align:center;z-index:10002;' +
    'box-shadow:0 20px 60px rgba(0,0,0,.25);transition:transform .25s, opacity .3s';
  card.innerHTML =
    `<div style="font-size:34px;margin-bottom:8px">🎉</div>` +
    `<div style="font-size:16px;font-weight:700;color:var(--gray-900)">${escapeHtml(title)}</div>` +
    (sub ? `<div style="font-size:12.5px;color:var(--gray-400);margin-top:5px">${escapeHtml(sub)}</div>` : '');
  document.body.appendChild(card);
  requestAnimationFrame(() => { card.style.transform = 'translate(-50%,-50%) scale(1)'; });
  setTimeout(() => { card.style.opacity = '0'; setTimeout(() => card.remove(), 350); }, 2600);
}

function _celebrateOnce(key, title, sub) {
  const k = `me_celebrated_${_currentUser?.id || 'x'}_${key}`;
  if (localStorage.getItem(k)) return;
  localStorage.setItem(k, '1');
  celebrate(title, sub);
}

// Called after any habit toggle — fires on streak milestones and
// on completing every habit for the day (each at most once)
async function checkHabitCelebrations() {
  const d = await fetch('/api/habits', {credentials: 'same-origin'})
    .then(r => r.json()).catch(() => null);
  const habits = d?.habits || [];
  if (!habits.length) return;
  for (const h of habits) {
    if (h.done_today && STREAK_MILESTONES.includes(h.streak || 0)) {
      _celebrateOnce(`streak_${h.id}_${h.streak}`,
                     `${h.streak}-day streak!`,
                     `“${h.name}” — that's real consistency`);
      return;
    }
  }
  if (habits.every(h => h.done_today)) {
    _celebrateOnce(`allhabits_${localToday()}`,
                   'All habits done today ✅',
                   `${habits.length} of ${habits.length} — clean sweep`);
  }
}

// ── Barcode food scanner ──────────────────────────────────────────
let _bcStream = null;      // active MediaStream (must be stopped on close)
let _bcScanning = false;

async function openBarcodeScanner() {
  const modal = document.getElementById('barcode-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  document.getElementById('bc-result').style.display = 'none';
  document.getElementById('bc-manual').value = '';

  const stage = document.getElementById('bc-scan-stage');
  const hint = document.getElementById('bc-scan-hint');

  // BarcodeDetector is Chrome/Android only; elsewhere use manual entry
  if (!('BarcodeDetector' in window)) {
    stage.style.display = 'none';
    return;
  }
  stage.style.display = '';
  try {
    _bcStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' } });
    const video = document.getElementById('bc-video');
    video.srcObject = _bcStream;
    await video.play();
    const detector = new BarcodeDetector({
      formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39'] });
    _bcScanning = true;
    _scanLoop(video, detector, hint);
  } catch (e) {
    // Permission denied or no camera — fall back to manual entry
    stage.style.display = 'none';
    console.warn('[barcode] camera unavailable:', e);
  }
}

async function _scanLoop(video, detector, hint) {
  if (!_bcScanning) return;
  try {
    const codes = await detector.detect(video);
    if (codes && codes.length) {
      const code = codes[0].rawValue;
      hint.textContent = 'Found: ' + code;
      _stopBarcodeCamera();
      lookupBarcode(code);
      return;
    }
  } catch (e) { /* transient detect errors are fine */ }
  requestAnimationFrame(() => _scanLoop(video, detector, hint));
}

function _stopBarcodeCamera() {
  _bcScanning = false;
  if (_bcStream) {
    _bcStream.getTracks().forEach(t => t.stop());
    _bcStream = null;
  }
}

function closeBarcodeScanner() {
  _stopBarcodeCamera();
  const modal = document.getElementById('barcode-modal');
  if (modal) modal.style.display = 'none';
}

function lookupBarcodeManual() {
  const code = (document.getElementById('bc-manual')?.value || '').trim();
  if (!/^\d{8,14}$/.test(code)) { showToast('Enter a valid 8–14 digit barcode', 'error'); return; }
  _stopBarcodeCamera();
  lookupBarcode(code);
}

async function lookupBarcode(code) {
  const box = document.getElementById('bc-result');
  box.style.display = '';
  box.innerHTML = '<div style="font-size:13px;color:var(--gray-400)">Looking up…</div>';
  const r = await fetch(`/api/food/barcode/${encodeURIComponent(code)}`,
                        {credentials: 'same-origin'});
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.found) {
    box.innerHTML = `
      <div style="font-size:13px;color:var(--gray-600);margin-bottom:8px">
        ${escapeHtml(d.error || 'Not found.')}</div>
      <button class="qlg-chip" data-ev-click="renderScanForm({&quot;barcode&quot;:&quot;${escapeHtml(code)}&quot;,&quot;name&quot;:&quot;&quot;,&quot;serving_g&quot;:100})">Add manually</button>`;
    return;
  }
  renderScanForm(d.food, d.food.source);
}

function renderScanForm(food, source) {
  const box = document.getElementById('bc-result');
  const f = k => Number(food[k] || 0);
  const src = source === 'saved'
    ? '<span style="color:var(--teal-600)">✓ Saved earlier</span>'
    : source === 'openfoodfacts'
      ? '<span style="color:var(--gray-400)">from Open Food Facts</span>' : '';
  window._scanBarcode = food.barcode || '';
  box.innerHTML = `
    <div style="border-top:1px solid var(--gray-100);padding-top:12px">
      <div class="qlg-label">Name ${src}</div>
      <input type="text" class="form-input" id="bc-name" value="${escapeHtml(food.name || '')}"
             placeholder="Food name" style="width:100%;margin-bottom:6px">
      <div style="font-size:11px;color:var(--gray-400);margin-bottom:6px">Per ${f('serving_g') || 100}g</div>
      <div class="bc-nutri-grid">
        <div><label>Calories</label><input type="number" class="form-input" id="bc-cal" value="${f('calories')}"></div>
        <div><label>Protein (g)</label><input type="number" class="form-input" id="bc-protein" value="${f('protein')}"></div>
        <div><label>Carbs (g)</label><input type="number" class="form-input" id="bc-carbs" value="${f('carbs')}"></div>
        <div><label>Fat (g)</label><input type="number" class="form-input" id="bc-fat" value="${f('fat')}"></div>
        <div><label>Fiber (g)</label><input type="number" class="form-input" id="bc-fiber" value="${f('fiber')}"></div>
        <div><label>Sugar (g)</label><input type="number" class="form-input" id="bc-sugar" value="${f('sugar')}"></div>
        <div><label>Sodium (mg)</label><input type="number" class="form-input" id="bc-sodium" value="${f('sodium')}"></div>
      </div>
      <button class="btn-primary" style="width:100%" data-ev-click="saveScannedFood()">Save to my foods</button>
    </div>`;
}

async function saveScannedFood() {
  const val = id => parseFloat(document.getElementById(id)?.value) || 0;
  const name = (document.getElementById('bc-name')?.value || '').trim();
  if (!name) { showToast('Give the food a name', 'error'); return; }
  const payload = {
    name, barcode: window._scanBarcode || '', serving_g: 100,
    calories: val('bc-cal'), protein: val('bc-protein'), carbs: val('bc-carbs'),
    fat: val('bc-fat'), fiber: val('bc-fiber'), sugar: val('bc-sugar'),
    sodium: val('bc-sodium'), category: 'Scanned',
  };
  const r = await fetch('/api/food/custom', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify(payload),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.success) { showToast(d.error || 'Could not save', 'error'); return; }
  closeBarcodeScanner();
  showToast(`📷 ${name} saved to your foods`);
  try { if (document.getElementById('view-food')?.classList.contains('active')) loadFoodTracker(); } catch (e) {}
}

// ── Quick-log FAB + sheet ─────────────────────────────────────────
function toggleQuickLog() {
  const sheet = document.getElementById('quick-log-sheet');
  if (!sheet) return;
  if (sheet.style.display === 'none') openQuickLog();
  else closeQuickLog();
}
function closeQuickLog() {
  const sheet = document.getElementById('quick-log-sheet');
  if (sheet) sheet.style.display = 'none';
}

async function openQuickLog() {
  const sheet = document.getElementById('quick-log-sheet');
  if (!sheet) return;
  sheet.style.display = 'flex';

  // Habits: toggle chips for today
  const habitsBox = document.getElementById('qlg-habits');
  fetch('/api/habits', {credentials: 'same-origin'}).then(r => r.json()).then(d => {
    const habits = (d.habits || []).filter(h => h.active !== 0);
    habitsBox.innerHTML = habits.length
      ? habits.map(h =>
          `<button class="qlg-chip${h.done_today ? ' done' : ''}" id="qlg-habit-${h.id}"
                   data-ev-click="quickToggleHabit('${h.id}')">${h.emoji || '⭐'} ${escapeHtml(h.name)}</button>`).join('')
      : '<span style="font-size:12px;color:var(--gray-400)">No habits yet — add one in the Habits view</span>';
  }).catch(() => { habitsBox.innerHTML = ''; });

  // Yesterday's meals shortcut
  const yBox = document.getElementById('qlg-yesterday');
  fetch('/api/food/recent-meals', {credentials: 'same-origin'}).then(r => r.json()).then(d => {
    const items = Object.values(d.yesterday || {}).flat();
    if (!items.length) { yBox.innerHTML = ''; return; }
    window._qlgYesterday = items;
    yBox.innerHTML =
      `<button class="qlg-chip" style="width:100%" data-ev-click="quickCopyYesterday()">
         🍽️ Copy yesterday's meals — ${items.length} item(s), ${Math.round(d.yesterday_total_cal || 0)} kcal
       </button>`;
  }).catch(() => { yBox.innerHTML = ''; });
}

async function quickWater(ml) {
  const r = await fetch('/api/hydration', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({amount_ml: ml, drink_type: 'water', date_key: localToday()}),
  }).then(r => r.json()).catch(() => null);
  if (r?.success === false) { showToast('Could not log water', 'error'); return; }
  closeQuickLog();
  showToast(`💧 +${ml}ml logged`);
  try { loadWellnessStrip(); } catch (e) {}
}

async function quickMood(mood) {
  const r = await fetch('/api/thoughts', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({content: `Quick check-in — feeling ${mood}`, mood, date_key: localToday()}),
  }).then(r => r.json()).catch(() => null);
  if (!r || r.error) { showToast(r?.error || 'Could not log mood', 'error'); return; }
  closeQuickLog();
  showToast('Mood logged 😊');
}

async function quickWeight() {
  const val = parseFloat(document.getElementById('qlg-weight')?.value);
  if (!val || val < 20 || val > 400) { showToast('Enter a weight in kg', 'error'); return; }
  const r = await fetch('/api/body-metrics', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({date_key: localToday(), weight_kg: val}),
  }).then(r => r.json()).catch(() => null);
  if (!r || r.error) { showToast('Could not save weight', 'error'); return; }
  document.getElementById('qlg-weight').value = '';
  closeQuickLog();
  showToast(`⚖️ ${val}kg saved`);
}

async function quickToggleHabit(id) {
  const r = await fetch(`/api/habits/${id}/toggle`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({date_key: localToday()}),
  }).then(r => r.json()).catch(() => null);
  const chip = document.getElementById(`qlg-habit-${id}`);
  if (chip && r) chip.classList.toggle('done', !!r.done);
  try { loadWellnessStrip(); } catch (e) {}
  if (r?.done) { try { checkHabitCelebrations(); } catch (e) {} }
}

async function quickCopyYesterday() {
  const items = window._qlgYesterday || [];
  if (!items.length) return;
  await Promise.all(items.map(item => fetch('/api/food/log', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({
      food_id: item.food_id, food_name: item.food_name, meal_type: item.meal_type,
      date_key: localToday(), quantity_g: item.quantity_g,
      calories: item.calories, protein: item.protein, carbs: item.carbs,
      fat: item.fat, fiber: item.fiber,
    }),
  }).catch(() => {})));
  closeQuickLog();
  showToast(`🍽️ ${items.length} item(s) copied from yesterday`);
  try { if (document.getElementById('view-food').classList.contains('active')) loadFoodTracker(); } catch (e) {}
}

// ── Web Push subscription ─────────────────────────────────────────
function _urlB64ToUint8(b64) {
  const pad = '='.repeat((4 - b64.length % 4) % 4);
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

// The only reminder path. The client used to run a second one beside it — a
// setInterval loop that fired its own dose/water/habit/sleep/mood
// notifications whenever the tab was open. It was strictly worse and actively
// harmful, so it's gone; don't bring it back:
//
//   - Two notifications for one dose, worded differently, whenever the tab
//     happened to be open. Only the server's had a working button.
//   - Its "✓ Mark as Taken" button emitted the action `taken`, which the
//     service worker doesn't handle — so it fell through to "open the app"
//     and the dose was never logged. The user believed it was.
//   - It registered a second, blob-built service worker at scope '/', which
//     would have displaced the real /sw.js — killing push and offline — if
//     browsers hadn't rejected blob: script URLs.
//
// scheduler.py covers every one of those reminders, works with the tab closed,
// and its action buttons write straight through the service worker.
async function setupPushSubscription() {
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    if (Notification.permission !== 'granted') return;
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      const cfg = await fetch('/api/push/vapid-public-key', {credentials: 'same-origin'})
        .then(r => r.json()).catch(() => null);
      if (!cfg || !cfg.enabled || !cfg.key) return;
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: _urlB64ToUint8(cfg.key),
      });
    }
    await fetch('/api/push/subscribe', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({subscription: sub.toJSON()}),
    });
  } catch (e) {
    console.warn('[push] subscription setup failed:', e);
  }
}

// ── PWA: register the service worker ─────────────────────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err =>
      console.warn('[pwa] service worker registration failed:', err));
  });
}

// ── Keyboard: Enter submits the active form ──────────────────────
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const screen = document.getElementById('auth-screen');
  if (!screen || screen.style.display === 'none') return;
  const visible = id => document.getElementById(id)?.style.display !== 'none';
  if      (visible('auth-form-reset'))  submitReset();
  else if (visible('auth-form-forgot')) submitForgot();
  else if (visible('auth-form-login'))  submitLogin();
  else                                  submitRegister();
});

// ── Accessibility: Escape closes the topmost open overlay ──
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const open = [...document.querySelectorAll('.modal-overlay, .checkin-overlay, .global-search-wrap')]
    .filter(el => getComputedStyle(el).display !== 'none');
  if (open.length) { open[open.length - 1].style.display = 'none'; e.preventDefault(); }
});

// ── Accessibility: label modals + icon-only controls for screen readers ──
function _applyA11yLabels() {
  document.querySelectorAll('.modal').forEach(m => {
    m.setAttribute('role', 'dialog');
    m.setAttribute('aria-modal', 'true');
    const title = m.querySelector('.modal-title');
    if (title && !m.getAttribute('aria-label')) m.setAttribute('aria-label', title.textContent.trim());
  });
  document.querySelectorAll('.modal-close').forEach(b => {
    if (!b.getAttribute('aria-label')) b.setAttribute('aria-label', 'Close');
  });
}
document.addEventListener('DOMContentLoaded', _applyA11yLabels);

// ── State ──
let selectedTags = [], selectedFile = null, selectedIcon = '💊', selectedColor = 'teal', selectedActivityType = 'running';
let notifPermission = 'default';

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  // Gate the entire app behind auth check
  initAuth();
  return; // rest of boot runs inside showApp() → switchView('dashboard')
  // --- unreachable code below kept for reference ---
  setGreeting();
  setDates();
  setupNavigation();
  setupDropzone();
  setupTagPicker();
  setupUploadForm();
  setupMedForm();
  setupActivityForm();
  setupIconColorPicker();
  setupFreqPicker();
  setupActivityTypePicker();
  setupFilters();
  loadDashboard();
  updateSidebarUser();
  checkNotifPermission();
  scheduleTodoReminderChecks();
  // Init date pickers
  const tdp = document.getElementById('thoughts-date-picker');
  if (tdp) tdp.value = localToday();
});

// ── Greeting & Date ──
function setGreeting() {
  const h = new Date().getHours();
  const g = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  const el = document.getElementById('greeting');
  if (el) el.textContent = g;
  const hd = document.getElementById('header-date');
  if (hd) hd.textContent = new Date().toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric', year:'numeric' });
  const mt = document.getElementById('med-today-date');
  if (mt) mt.textContent = new Date().toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric' });
}

function setDates() {
  const today = localToday();
  ['report-date','med-start-date','activity-date'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = today;
  });
}

// ── Navigation ──
function setupNavigation() {
  // Sidebar items, mobile tab bar and the mobile "More" sheet all navigate
  document.querySelectorAll('[data-view]').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      switchView(item.dataset.view);
    });
  });
}

// ── Mobile "More" sheet ──
function toggleMobileMore() {
  const sheet = document.getElementById('mobile-more-sheet');
  if (sheet) sheet.style.display = sheet.style.display === 'none' ? '' : 'none';
}
function closeMobileMore() {
  const sheet = document.getElementById('mobile-more-sheet');
  if (sheet) sheet.style.display = 'none';
}

function switchView(view) {
  // Redirect removed/merged views
  const REDIRECT = {
    'consistency': 'habits',
    'report':      'progress',
    'export':      'progress',
  };
  view = REDIRECT[view] || view;

  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('[data-view]').forEach(n => n.classList.remove('active'));
  const viewEl = document.getElementById('view-' + view);
  if (viewEl) viewEl.classList.add('active');
  document.querySelectorAll('[data-view="' + view + '"]')
    .forEach(n => n.classList.add('active'));
  closeMobileMore();   // navigating always dismisses the mobile sheet

  if (view === 'dashboard')     { loadDashboard(); loadWellnessStrip(); }
  if (view === 'food')          { loadFoodTracker(); loadHydration(localToday()); }
  if (view === 'fitness')       { loadFitness(); loadConnectedServices(); }
  if (view === 'medicines')     loadMedicines();
  if (view === 'reports')       loadReports();
  if (view === 'habits')        loadHabits();
  if (view === 'thoughts')      { loadWellness(); setTimeout(() => switchWellnessTab('thoughts'), 50); }
  if (view === 'sleep')         loadSleepView();
  if (view === 'body')          loadBodyView();
  if (view === 'todos')         loadTodos();
  if (view === 'progress')      loadProgress();
  if (view === 'family')        loadFamily();
  if (view === 'notifications') loadNotifications();
}

// ── Family sharing (Phase 3) ──────────────────────────────────────
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

const FAMILY_CATEGORIES = [
  ['share_sleep',     '🌙', 'Sleep'],
  ['share_vitals',    '❤️', 'Vitals'],
  ['share_medicines', '💊', 'Medicines'],
  ['share_food',      '🍽️', 'Food'],
  ['share_symptoms',  '🤒', 'Symptoms'],
  ['share_emergency', '🆘', 'Emergency card'],
];

async function loadFamily() {
  const box = document.getElementById('family-content');
  if (!box) return;
  const r = await fetch('/api/family', {credentials: 'same-origin'}).catch(() => null);
  const group = r && r.ok ? (await r.json()).group : null;
  box.innerHTML = group ? renderFamilyGroup(group) : renderFamilyEmpty();
  if (group) loadAlertContacts();
}

// ── Zero-install caregiver alert contacts (SMS/WhatsApp) ────────────────────
async function loadAlertContacts() {
  const list = document.getElementById('alert-contacts-list');
  if (!list) return;
  const r = await fetch('/api/family/alert-contacts', {credentials: 'same-origin'}).catch(() => null);
  const d = (r && r.ok) ? await r.json() : {contacts: [], sms_live: false, whatsapp_live: false};
  const contacts = d.contacts || [];
  if (!contacts.length) {
    list.innerHTML = `<div style="font-size:12px;color:var(--gray-400)">No alert contacts yet.</div>`;
    return;
  }
  list.innerHTML = contacts.map(c => {
    const live = c.channel === 'whatsapp' ? d.whatsapp_live : d.sms_live;
    const chan = c.channel === 'whatsapp' ? 'WhatsApp' : 'SMS';
    // Be honest: until a provider is wired, say alerts are simulated, don't imply delivery.
    const status = live ? '' :
      ` <span style="font-size:10px;color:var(--amber-600,#b45309)" title="No SMS provider is configured yet, so these are simulated">· not sending yet</span>`;
    return `
      <div style="display:flex;align-items:center;gap:10px;font-size:13px;padding:6px 0;border-bottom:1px solid var(--gray-50)">
        <div style="flex:1;min-width:120px">
          <b>${escapeHtml(c.name)}</b>
          <span style="color:var(--gray-400)">· ${escapeHtml(c.phone)} · ${chan}</span>${status}
        </div>
        <label style="display:flex;align-items:center;gap:5px;font-size:12px;cursor:pointer">
          <input type="checkbox" ${c.alerts_enabled ? 'checked' : ''}
                 data-ev-change="toggleAlertContact('${c.id}', this.checked)"> on
        </label>
        <button class="btn-outline" style="font-size:11px" data-ev-click="testAlertContact('${c.id}')">Test</button>
        <button class="btn-outline" style="font-size:11px;color:#DC2626" data-ev-click="deleteAlertContact('${c.id}')">Remove</button>
      </div>`;
  }).join('');
}

async function addAlertContact() {
  const name = (document.getElementById('ac-name')?.value || '').trim();
  const phone = (document.getElementById('ac-phone')?.value || '').trim();
  const channel = document.getElementById('ac-channel')?.value || 'sms';
  if (!name || !phone) { showToast('Enter a name and phone number', 'error'); return; }
  const r = await fetch('/api/family/alert-contacts', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({name, phone, channel}),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { showToast(d.error || 'Could not add contact', 'error'); return; }
  showToast('Added ' + name);
  loadAlertContacts();
}

async function toggleAlertContact(id, on) {
  await fetch('/api/family/alert-contacts/' + id, {
    method: 'PATCH', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({alerts_enabled: on}),
  }).catch(() => {});
}

async function deleteAlertContact(id) {
  await fetch('/api/family/alert-contacts/' + id, {method: 'DELETE', credentials: 'same-origin'}).catch(() => {});
  loadAlertContacts();
}

async function testAlertContact(id) {
  const r = await fetch('/api/family/alert-contacts/' + id + '/test', {
    method: 'POST', credentials: 'same-origin'});
  const d = await r.json().catch(() => ({}));
  if (d.delivered) showToast('✓ Test message sent');
  else if (d.dev_mode) showToast('Simulated — no SMS provider is set up yet', 'info');
  else showToast('Could not send test', 'error');
}

// The privacy explainer. Written to reassure someone deciding whether to let
// their family see any of this — and it used to render only *inside* an
// existing group, so the one person who most needed it could never reach it.
// It belongs wherever that decision is being made.
function familyExplainer() {
  return `
      <details class="family-explainer">
        <summary>How sharing works</summary>
        <ul>
          <li><b>Nothing is shared by default.</b> Each category is off until you turn it on — and you can switch any of them off again anytime.</li>
          <li><b>You choose per category.</b> Sharing medicines doesn't share your journal; sharing sleep doesn't share your vitals.</li>
          <li><b>Missed-dose alerts are opt-in.</b> Your family is only told about a missed dose if you turn that on — and you always get a heads-up first.</li>
          <li><b>Primary vs. viewer.</b> Anyone can see what's shared; only those who opt in to "Notify me…" get pinged about missed doses.</li>
        </ul>
      </details>`;
}

function renderFamilyEmpty() {
  return `
    <div class="panel" style="padding:32px;text-align:center;max-width:480px">
      <div style="font-size:34px;margin-bottom:10px">👨‍👩‍👧</div>
      <h2 style="font-size:17px;font-weight:700;margin-bottom:6px">Create your family group</h2>
      <p style="font-size:13px;color:var(--gray-400);margin-bottom:18px;line-height:1.6">
        Invite family members by email. Everyone chooses exactly which
        categories they share — nothing is visible unless they turn it on.
      </p>
      <div style="display:flex;gap:8px;justify-content:center">
        <input type="text" class="form-input" id="family-group-name" placeholder="Group name (e.g. The Guptas)"
               style="max-width:220px">
        <button class="btn-primary" data-ev-click="createFamilyGroup()">Create group</button>
      </div>
      <div style="margin-top:18px;text-align:left">${familyExplainer()}</div>
    </div>`;
}

function renderFamilyGroup(g) {
  const isOwner = g.my_role === 'owner';

  const memberCards = g.members.map(m => {
    const shared = FAMILY_CATEGORIES.filter(([f]) => m.shares[f]);
    let badges = shared.length
      ? shared.map(([, icon, label]) =>
          `<span style="font-size:11px;background:var(--gray-50);border-radius:6px;padding:2px 8px">${icon} ${label}</span>`).join(' ')
      : '<span style="font-size:11px;color:var(--gray-400)">Shares nothing yet</span>';
    const isMe = _currentUser && m.user_id === _currentUser.id;
    if (m.alerts_on)
      badges += ' <span style="font-size:11px;background:var(--amber-50);border-radius:6px;padding:2px 8px">🚨 dose alerts</span>';
    const actions = [];
    if (!isMe && shared.length)
      actions.push(`<button class="btn-outline" style="font-size:12px" data-ev-click="toggleFamilySummary('${m.user_id}')">View shared data</button>`);
    if (isOwner && !isMe)
      actions.push(`<button class="btn-outline" style="font-size:12px;color:#DC2626" data-ev-click="removeFamilyMember('${m.user_id}')">Remove</button>`);
    return `
      <div class="panel" style="padding:16px 18px;margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div style="flex:1;min-width:180px">
            <div style="font-size:14px;font-weight:600">${escapeHtml(m.name || m.email)}
              ${m.role === 'owner' ? '<span style="font-size:10px;color:var(--gray-400);margin-left:6px">OWNER</span>' : ''}
              ${isMe ? '<span style="font-size:10px;color:#3E7862;margin-left:6px">YOU</span>' : ''}
            </div>
            <div style="font-size:12px;color:var(--gray-400)">${escapeHtml(m.email)}</div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">${badges}</div>
          ${actions.join(' ')}
        </div>
        <div id="family-summary-${m.user_id}" style="display:none;margin-top:14px"></div>
      </div>`;
  }).join('');

  const consentToggles = FAMILY_CATEGORIES.map(([f, icon, label]) => `
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
      <input type="checkbox" ${g.my_consent[f] ? 'checked' : ''}
             data-ev-change="saveFamilyConsent('${f}', this.checked)">
      ${icon} ${label}
    </label>`).join('');

  // Caregiver alerts — only offered while medicines are shared
  const alertToggle = g.my_consent.share_medicines ? `
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;
                  margin-top:12px;padding:10px 12px;border:1px solid var(--amber-100);
                  border-radius:10px;background:var(--amber-50)">
      <input type="checkbox" ${g.my_alerts ? 'checked' : ''}
             data-ev-change="saveFamilyConsent('alert_missed_doses', this.checked)">
      🚨 Alert my family if I miss a dose by 2+ hours
    </label>` : '';

  // Caregiver role: primary (gets alerts) vs viewer (sees status, no pings)
  const receiveAlertsToggle = `
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;
                  margin-top:10px;padding:10px 12px;border:1px solid var(--gray-100);border-radius:10px">
      <input type="checkbox" ${g.my_receive_alerts ? 'checked' : ''}
             data-ev-change="saveFamilyConsent('receive_care_alerts', this.checked)">
      🔔 Notify me when a family member misses a dose
    </label>`;

  const inviteSection = isOwner ? `
    <div class="panel" style="padding:18px 20px;margin-bottom:16px">
      <h2 class="panel-title" style="margin-bottom:12px">Invite someone</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <input type="email" class="form-input" id="family-invite-email"
               placeholder="their-email@example.com" style="max-width:260px">
        <button class="btn-primary" data-ev-click="sendFamilyInvite()">Send invite</button>
      </div>
      ${(g.pending_invites || []).length ? `
        <div style="margin-top:14px">
          <div style="font-size:12px;color:var(--gray-400);margin-bottom:6px">Pending invites</div>
          ${g.pending_invites.map(i => `
            <div style="display:flex;align-items:center;gap:10px;font-size:13px;padding:4px 0">
              <span style="flex:1">${escapeHtml(i.email)}</span>
              <button class="btn-outline" style="font-size:11px" data-ev-click="revokeFamilyInvite('${i.id}')">Revoke</button>
            </div>`).join('')}
        </div>` : ''}
    </div>` : '';

  // Zero-install alert contacts — a phone that gets pinged if I miss a dose,
  // no app needed on their end. Filled in by loadAlertContacts().
  const alertContactsSection = `
    <div class="panel" style="padding:18px 20px;margin-bottom:16px">
      <h2 class="panel-title" style="margin-bottom:4px">📱 Text a loved one if I miss a dose</h2>
      <p style="font-size:12px;color:var(--gray-400);margin-bottom:12px">
        Add a phone number and they'll get an SMS or WhatsApp if one of my doses is 2+ hours
        overdue — no app or account needed on their end. This works once
        <b>🚨 Alert my family if I miss a dose</b> is on above. I can remove anyone anytime.</p>
      <div id="alert-contacts-list" style="margin-bottom:12px"></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <input type="text" class="form-input" id="ac-name" placeholder="Name (e.g. Mom)"
               aria-label="Contact name" style="max-width:150px">
        <input type="tel" class="form-input" id="ac-phone" placeholder="+9198XXXXXXXX"
               aria-label="Phone with country code" style="max-width:175px">
        <select class="form-input" id="ac-channel" aria-label="Channel" style="max-width:130px">
          <option value="sms">SMS</option>
          <option value="whatsapp">WhatsApp</option>
        </select>
        <button class="btn-primary" data-ev-click="addAlertContact()">Add</button>
      </div>
    </div>`;

  const dangerBtn = isOwner
    ? `<button class="btn-outline" style="color:#DC2626" data-ev-click="deleteFamilyGroup()">Delete group</button>`
    : `<button class="btn-outline" style="color:#DC2626" data-ev-click="leaveFamilyGroup()">Leave group</button>`;

  return `
    <div class="panel" style="padding:18px 20px;margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
        <h2 class="panel-title" style="flex:1">${escapeHtml(g.name)}</h2>
        ${dangerBtn}
      </div>
      <p style="font-size:12px;color:var(--gray-400)">You share only what you switch on below. Changes apply immediately.</p>
      ${familyExplainer()}
      <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:12px">${consentToggles}</div>
      ${alertToggle}
      ${receiveAlertsToggle}
    </div>
    ${inviteSection}
    ${alertContactsSection}
    <div>${memberCards}</div>`;
}

async function createFamilyGroup() {
  const name = document.getElementById('family-group-name')?.value || '';
  const r = await fetch('/api/family', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({name}),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { showToast(d.error || 'Could not create group', 'error'); return; }
  loadFamily();
}

async function saveFamilyConsent(field, on) {
  await fetch('/api/family/consent', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({[field]: on}),
  }).catch(() => {});
  loadFamily();
}

async function sendFamilyInvite() {
  const email = (document.getElementById('family-invite-email')?.value || '').trim();
  if (!email) { showToast('Enter an email address', 'error'); return; }
  const r = await fetch('/api/family/invite', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({email}),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { showToast(d.error || 'Could not send invite', 'error'); return; }
  showToast('Invite sent to ' + email);
  loadFamily();
}

async function revokeFamilyInvite(id) {
  await fetch('/api/family/invite/' + id, {method: 'DELETE', credentials: 'same-origin'}).catch(() => {});
  loadFamily();
}

function removeFamilyMember(uid) {
  undoable('Removing member…', async () => {
    const r = await fetch('/api/family/member/' + uid, {method: 'DELETE', credentials: 'same-origin'});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { showToast(d.error || 'Could not remove member', 'error'); return; }
    loadFamily();
  });
}

function leaveFamilyGroup() {
  undoable('Leaving family group…', async () => {
    const r = await fetch('/api/family/leave', {method: 'POST', credentials: 'same-origin'});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { showToast(d.error || 'Could not leave group', 'error'); return; }
    loadFamily();
  });
}

function deleteFamilyGroup() {
  undoable('Deleting family group…', async () => {
    const r = await fetch('/api/family', {method: 'DELETE', credentials: 'same-origin'});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { showToast(d.error || 'Could not delete group', 'error'); return; }
    loadFamily();
  });
}

async function toggleFamilySummary(uid) {
  const el = document.getElementById('family-summary-' + uid);
  if (!el) return;
  if (el.style.display !== 'none') { el.style.display = 'none'; return; }
  el.style.display = '';
  el.innerHTML = '<div style="font-size:12px;color:var(--gray-400)">Loading…</div>';
  const r = await fetch(`/api/family/member/${uid}/summary`, {credentials: 'same-origin'});
  const s = await r.json().catch(() => null);
  if (!r.ok || !s) {
    el.innerHTML = '<div style="font-size:12px;color:#DC2626">Could not load shared data</div>';
    return;
  }
  el.innerHTML = renderFamilySummary(s);
}

function renderFamilySummary(s) {
  const rows = [];
  if (s.sleep)
    rows.push(`🌙 <b>Sleep:</b> ${s.sleep.nights} night(s) logged this week` +
              (s.sleep.avg_hours != null ? `, avg ${s.sleep.avg_hours}h` : ''));
  if (s.vitals && Object.keys(s.vitals).length) {
    const parts = Object.entries(s.vitals).map(([t, v]) =>
      `${t.replace('_', ' ')}: ${v.value1}${v.value2 ? '/' + v.value2 : ''} ${v.unit || ''}`);
    rows.push(`❤️ <b>Vitals:</b> ${parts.join(' · ')}`);
  } else if (s.vitals) {
    rows.push('❤️ <b>Vitals:</b> nothing logged yet');
  }
  if (s.medicines)
    rows.push(`💊 <b>Medicines:</b> ${s.medicines.active.length} active — ` +
              `${s.medicines.today.taken}/${s.medicines.today.total} doses taken today`);
  if (s.food)
    rows.push(`🍽️ <b>Food:</b> ${s.food.today_calories} kcal across ${s.food.today_logs} log(s) today`);
  if (s.symptoms)
    rows.push(`🤒 <b>Symptoms (7d):</b> ` + (s.symptoms.length
      ? s.symptoms.slice(0, 5).map(x => `${escapeHtml(x.name)} (${x.severity}/10)`).join(', ')
      : 'none reported'));
  if (!rows.length && !s.emergency)
    rows.push('This member is not sharing any categories with the group.');

  // Emergency card — surfaced prominently for crisis fast-access
  let emergencyBlock = '';
  if (s.emergency) {
    const e = s.emergency;
    const line = (label, val) => val ? `<div><span style="color:var(--gray-400)">${label}:</span> ${escapeHtml(val)}</div>` : '';
    const contact = (n, p) => (n || p) ? `<div><span style="color:var(--gray-400)">Contact:</span> ${escapeHtml(n || '')}${p ? ` · <a href="tel:${escapeHtml(p)}" style="color:var(--red-500);font-weight:600">${escapeHtml(p)}</a>` : ''}</div>` : '';
    const inner = [
      line('Blood type', e.blood_type), line('Allergies', e.allergies),
      line('Conditions', e.conditions), line('Medications', e.medications),
      contact(e.contact1_name, e.contact1_phone), contact(e.contact2_name, e.contact2_phone),
    ].filter(Boolean).join('');
    emergencyBlock = `<div class="emergency-card-share">
        <div class="emergency-card-share-title">🆘 Emergency card</div>
        ${inner || '<div style="color:var(--gray-400)">No details filled in yet.</div>'}
      </div>`;
  }

  return `<div style="border-top:1px solid var(--gray-100);padding-top:12px;
               display:flex;flex-direction:column;gap:8px;font-size:13px">
            ${rows.map(x => `<div>${x}</div>`).join('')}
            ${emergencyBlock}
          </div>`;
}

// ── First-run "get started" checklist ─────────────────────────────
// Medication leads — it's Arogo's core loop, so onboarding starts there.
const FIRSTRUN_STEPS = [
  {key: 'medicines',      icon: '💊', label: 'Add your first medication', ev: 'openMedModal()', primary: true},
  {key: 'family',         icon: '👪', label: 'Connect a family member', ev: "switchView('family')"},
  {key: 'food_logs',      icon: '🍽️', label: 'Log your first meal',  ev: "quickAdd('food')"},
  {key: 'hydration_logs', icon: '💧', label: 'Log a glass of water', ev: 'quickWater(250)'},
  {key: 'habits',         icon: '⭐', label: 'Create a habit',       ev: "switchView('habits')"},
];

async function checkFirstRun() {
  const el = document.getElementById('firstrun-card');
  if (!el || !_currentUser) return;
  const dismissKey = 'me_firstrun_' + _currentUser.id;
  if (localStorage.getItem(dismissKey)) { el.style.display = 'none'; return; }

  const counts = await fetch('/api/export/counts', {credentials: 'same-origin'})
    .then(r => r.json()).catch(() => null);
  if (!counts) return;

  const remaining = FIRSTRUN_STEPS.filter(s => !(counts[s.key] > 0)).length;
  if (remaining === 0) {
    // Everything done — celebrate once, then never show again
    localStorage.setItem(dismissKey, '1');
    el.style.display = 'none';
    showToast('🎉 You’re all set up!');
    return;
  }

  el.style.display = '';
  el.innerHTML = `
    <div class="panel" style="padding:18px 20px;border-color:var(--teal-200);background:var(--teal-50)">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <div style="font-size:15px;font-weight:700;color:var(--gray-900);flex:1">
          👋 Welcome to Arogo — ${FIRSTRUN_STEPS.length - remaining}/${FIRSTRUN_STEPS.length} done
        </div>
        <a href="#" style="font-size:12px;color:var(--gray-400);text-decoration:none"
           data-ev-click="dismissFirstRun()">Dismiss</a>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        ${FIRSTRUN_STEPS.map(s => {
          const done = counts[s.key] > 0;
          return done
            ? `<div style="display:flex;align-items:center;gap:10px;font-size:13px;color:var(--gray-400)">
                 <span style="width:20px;height:20px;border-radius:50%;background:var(--teal-600);color:#fff;
                              display:inline-flex;align-items:center;justify-content:center;font-size:11px">✓</span>
                 <span style="text-decoration:line-through">${s.icon} ${s.label}</span>
               </div>`
            : `<button style="display:flex;align-items:center;gap:10px;font-size:13px;
                              color:${s.primary ? '#fff' : 'var(--gray-700)'};font-weight:${s.primary ? '600' : '400'};
                              background:${s.primary ? 'var(--teal-600)' : 'var(--gray-0)'};
                              border:1px solid ${s.primary ? 'var(--teal-600)' : 'var(--gray-100)'};border-radius:10px;
                              padding:10px 12px;cursor:pointer;text-align:left;font-family:inherit;min-height:42px"
                       data-ev-click="${s.ev}">
                 <span style="width:20px;height:20px;border-radius:50%;border:2px solid ${s.primary ? 'rgba(255,255,255,.6)' : 'var(--gray-200)'};flex-shrink:0"></span>
                 ${s.icon} ${s.label}
                 <span style="margin-left:auto;color:${s.primary ? '#fff' : 'var(--teal-600)'};font-weight:600">→</span>
               </button>`;
        }).join('')}
      </div>
    </div>`;
}

function dismissFirstRun() {
  if (_currentUser) localStorage.setItem('me_firstrun_' + _currentUser.id, '1');
  const el = document.getElementById('firstrun-card');
  if (el) el.style.display = 'none';
}

// ── Insight cards ─────────────────────────────────────────────────
async function loadInsightCards() {
  const box = document.getElementById('insight-cards');
  if (!box) return;
  const d = await fetch('/api/insights/cards', {credentials: 'same-origin'})
    .then(r => r.json()).catch(() => null);
  const cards = d?.cards || [];
  if (!cards.length) { box.style.display = 'none'; return; }
  const tones = {
    success: 'background:var(--green-50);border-color:#D1FAE5',
    warning: 'background:var(--amber-50);border-color:var(--amber-100)',
    info:    'background:var(--blue-50);border-color:#DBEAFE',
  };
  box.style.display = '';
  box.innerHTML = `<div style="display:flex;gap:12px;flex-wrap:wrap">` +
    cards.map(c => `
      <div style="flex:1;min-width:220px;display:flex;gap:10px;align-items:flex-start;
                  border:1px solid transparent;border-radius:12px;padding:12px 14px;
                  ${tones[c.tone] || tones.info}">
        <span style="font-size:20px">${c.icon}</span>
        <span style="font-size:13px;color:var(--gray-700);line-height:1.5">${escapeHtml(c.text)}</span>
      </div>`).join('') + '</div>';
}

// ── Dashboard ──
async function loadDashboard() {
  try { checkFirstRun(); }      catch (e) {}
  try { loadInsightCards(); }   catch (e) {}
  try { loadWellnessStrip(); }  catch (e) {}
  try { loadCarePanel(); }      catch (e) {}
  try { loadEncouragements(); } catch (e) {}
  try { loadLowStock(); }       catch (e) {}
  initDailyCheckin();

  const [doses, fitnessStats] = await Promise.all([
    fetch('/api/medicines/today').then(r => r.json()).catch(() => []),
    fetch('/api/fitness/stats').then(r => r.json()).catch(() => ({})),
  ]);

  // Active minutes (this week)
  setText('dash-active-min', fitnessStats.week?.duration || 0);

  // Calorie balance — calm inline stat (no coloured card)
  fetch('/api/calorie-balance').then(r => r.json()).then(cb => {
    const t = cb.today || {};
    // No target → no budget, so there is no "remaining". Show what they
    // actually ate, which needs no target to be true. `net ?? 0` used to turn
    // a missing budget into "2000 kcal remaining" — the most confident thing
    // on a new user's first screen, about a number nobody had computed.
    if (!cb.has_target) {
      setText('dash-cal-deficit', t.eaten || 0);
      setText('dash-cal-deficit-sub',
        t.eaten ? 'calories eaten' : 'no meals logged yet');
    } else {
      const net = t.net ?? 0;
      setText('dash-cal-deficit', Math.abs(net));
      setText('dash-cal-deficit-sub',
        t.burned > 0 ? `${t.burned} kcal burned` :
        net > 100 ? 'kcal remaining' : net < -100 ? 'kcal over budget' : 'calories today');
    }
    renderNextAction(doses, cb);   // refine the hero once calorie state is known
  }).catch(() => {});

  // ── Today's medicines — panel only appears if there are doses ──
  const remaining = doses.filter(d => !d.taken).length;
  const hasMeds   = doses.length > 0;

  // Medication adherence tile — the core loop, front and centre in the focal panel
  const takenToday = doses.filter(d => d.taken).length;
  const totalToday = doses.length;
  setText('dws-meds', totalToday ? `${takenToday} / ${totalToday}` : '—');
  const medsBar = document.getElementById('dws-meds-bar');
  if (medsBar) medsBar.style.width = totalToday ? Math.round(takenToday / totalToday * 100) + '%' : '0%';
  setText('dws-meds-sub', !totalToday ? 'no meds today'
    : takenToday === totalToday ? 'all doses taken ✓' : 'doses today');

  // Single "what do I do right now" hero — meds first, then a gentle fallback
  renderNextAction(doses, null);
  const medPanel  = document.getElementById('dash-medicines-panel');
  const medList   = document.getElementById('dash-medicine-list');
  if (medPanel) medPanel.style.display = hasMeds ? '' : 'none';
  if (hasMeds && medList) {
    medList.innerHTML = doses.slice(0, 5).map(d => `
      <div class="dash-dose-item ${d.taken ? 'taken' : ''}" data-ev-click="markDoseTaken('${d.med_id}','${d.time}',this)">
        <div class="dash-dose-icon">${d.icon}</div>
        <div class="dash-dose-info">
          <div class="dash-dose-name">${escHtml(d.med_name)}</div>
          <div class="dash-dose-detail">${d.dosage} ${d.unit}${d.with_food ? ' · with food' : ''}</div>
        </div>
        <div class="dash-dose-time">${d.time}</div>
        <div class="dash-dose-check ${d.taken ? 'done' : ''}">${d.taken ? '✓' : ''}</div>
      </div>`).join('');
  }

  // ── Pending tasks — panel only appears if there are any ──
  const pendingCount = await loadDashboardTodos();
  const taskPanel = document.getElementById('dash-tasks-panel');
  if (taskPanel) taskPanel.style.display = pendingCount > 0 ? '' : 'none';

  // Show the agenda grid only if at least one panel is visible
  const agenda = document.getElementById('dash-agenda-grid');
  if (agenda) agenda.style.display = (hasMeds || pendingCount > 0) ? '' : 'none';

  // ── Weekly activity — only when there is activity this week ──
  const weeklyDays = fitnessStats.weekly_days || {};
  const hasActivity = Object.values(weeklyDays).some(d => (d.duration || 0) > 0 || (d.calories || 0) > 0);
  const weeklyPanel = document.getElementById('dash-weekly-panel');
  if (weeklyPanel) weeklyPanel.style.display = hasActivity ? '' : 'none';
  if (hasActivity) renderWeeklyChart(weeklyDays);

  // Nav dose badge
  const badge = document.getElementById('nav-dose-badge');
  if (badge) {
    if (remaining > 0) { badge.textContent = remaining; badge.style.display = 'inline-block'; }
    else badge.style.display = 'none';
  }

  // Consistency streak badge
  fetch('/api/fitness/consistency').then(r => r.json()).then(con => {
    const sb = document.getElementById('dash-streak-badge');
    if (sb) {
      const streak = con.current_streak || 0;
      if (streak > 0) { sb.textContent = `🔥${streak}`; sb.style.display = 'inline-block'; }
      else sb.style.display = 'none';
    }
  }).catch(() => {});
}

// The dashboard hero: surface the single most important next action.
// Priority — an untaken dose (the app's core adherence loop) > "all caught up"
// affirmation > a gentle "log your first meal" nudge on an otherwise-empty day.
function renderNextAction(doses, calorieState) {
  const el = document.getElementById('dash-next-action');
  if (!el) return;
  const untaken = (doses || []).filter(d => !d.taken);

  // Current local time as HH:MM, to tell "due/overdue" from "coming up"
  const now  = new Date();
  const hhmm = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');

  if (untaken.length) {
    const sorted  = untaken.slice().sort((a, b) => (a.time || '').localeCompare(b.time || ''));
    const due     = sorted.filter(d => (d.time || '') <= hhmm);
    const next    = due.length ? due[due.length - 1] : sorted[0];  // most-overdue, else soonest
    const overdue = (next.time || '') <= hhmm;
    const more    = untaken.length - 1;
    el.className = 'next-action';
    el.innerHTML = `
      <div class="next-action-icon">${next.icon || '💊'}</div>
      <div class="next-action-body">
        <div class="next-action-eyebrow">${overdue ? 'Time for your dose' : 'Next dose'}</div>
        <div class="next-action-title">Take ${escHtml(next.med_name)}</div>
        <div class="next-action-sub">${escHtml(next.dosage || '')} ${escHtml(next.unit || '')} · ${next.time}${next.with_food ? ' · with food' : ''}${more > 0 ? ` · +${more} more today` : ''}</div>
      </div>
      <button class="next-action-btn" data-ev-click="markDoseTaken('${next.med_id}','${next.time}')">Mark taken</button>`;
    el.style.display = '';
    return;
  }

  if ((doses || []).length) {
    // Meds exist and every dose is done — a quiet affirmation, no action needed
    el.className = 'next-action is-calm';
    el.innerHTML = `
      <div class="next-action-icon">✓</div>
      <div class="next-action-body">
        <div class="next-action-eyebrow">All caught up</div>
        <div class="next-action-title">Every dose taken today</div>
        <div class="next-action-sub">Nice work staying on track.</div>
      </div>`;
    el.style.display = '';
    return;
  }

  // No medicines scheduled — nudge the next most useful log only if the day is empty
  const eaten = calorieState && calorieState.today ? (calorieState.today.eaten || 0) : 0;
  if (calorieState && eaten === 0) {
    el.className = 'next-action is-calm';
    el.innerHTML = `
      <div class="next-action-icon">🍽️</div>
      <div class="next-action-body">
        <div class="next-action-eyebrow">Start your day</div>
        <div class="next-action-title">Log your first meal</div>
        <div class="next-action-sub">A quick log keeps your nutrition picture accurate.</div>
      </div>
      <button class="next-action-btn" data-ev-click="quickAdd('food')">Log a meal</button>`;
    el.style.display = '';
    return;
  }

  el.style.display = 'none';
}

// Caregiver panel: today's medication status for family members who share
// their meds with you. Consent-gated server-side; only appears if ≥1 member.
async function loadCarePanel() {
  const el = document.getElementById('dash-care-panel');
  if (!el) return;
  const members = await fetch('/api/family/care-status').then(r => r.json()).catch(() => []);
  if (!Array.isArray(members) || !members.length) { el.style.display = 'none'; return; }
  // Reassurance: turn "no alerts" into explicit good news.
  const allGood = members.every(m => !m.overdue.length);
  const ago = (min) => min == null ? '' : min < 1 ? 'just now' : min < 60 ? `${min}m ago` : `${Math.round(min / 60)}h ago`;
  el.innerHTML = `
    <div class="care-panel-head">
      <span class="care-panel-title">People you're caring for${allGood ? ' · everyone’s on track today ✓' : ''}</span>
      <a href="#" class="panel-link" data-ev-click="switchView('family');return false">Family →</a>
    </div>
    <div class="care-list">${members.map(m => {
      const overdue = m.overdue.length;
      const done    = m.total > 0 && m.taken >= m.total;
      const status  = overdue ? `${overdue} dose${overdue > 1 ? 's' : ''} overdue`
                    : m.total === 0 ? 'No medicines scheduled today'
                    : done ? 'All doses taken ✓'
                    : `${m.taken} of ${m.total} doses taken`;
      const detail  = overdue ? m.overdue.map(o => `${escHtml(o.med_name || 'dose')} · ${o.time}`).join(', ')
                    : (m.last_ago_min != null ? `last dose ${ago(m.last_ago_min)}` : '');
      const low     = (m.low_stock && m.low_stock.length) ? m.low_stock[0] : null;
      const refill  = low
        ? `🔄 ${escHtml(low.name || 'A medicine')} running low${low.days_left != null ? ` (~${Math.max(0, Math.round(low.days_left))}d)` : ''}`
          + (m.low_stock.length > 1 ? ` +${m.low_stock.length - 1} more` : '')
        : '';
      const cls     = overdue ? 'is-alert' : done ? 'is-ok' : 'is-pending';
      const icon    = overdue ? '🚨' : done ? '✓' : '💊';
      // Coordination: on an overdue member, let one caregiver claim it so the
      // others don't all call at once.
      let right;
      if (overdue && m.checking_is_me)      right = `<span class="care-ack-chip is-me">You're on it ✓</span>`;
      else if (overdue && m.checking_by)    right = `<span class="care-ack-chip">${escHtml(m.checking_by)} is on it</span>`;
      else if (overdue)                     right = `<button class="care-ack-btn" data-ev-click="careAck('${m.user_id}')">I'll check</button>`;
      else                                  right = `<div class="care-item-actions">
        <button class="care-cheer-btn" data-ev-click="cheer('${m.user_id}','${escHtml(m.name)}')" title="Send encouragement">👏</button>
        <button class="care-cheer-btn" data-ev-click="pingMember('${m.user_id}','${escHtml(m.name)}')" title="Thinking of you">💛</button>
      </div>`;
      return `<div class="care-item ${cls}">
        <div class="care-item-avatar">${escHtml((m.name || '?').slice(0, 1).toUpperCase())}</div>
        <div class="care-item-body">
          <div class="care-item-name">${escHtml(m.name)}</div>
          <div class="care-item-status">${status}${detail ? ' · ' + detail : ''}</div>
          ${refill ? `<div class="care-item-refill">${refill}</div>` : ''}
        </div>
        ${right}
      </div>`;
    }).join('')}</div>`;
  el.style.display = '';
}

// Every action below tells one person something reassuring about another. If
// the write didn't land, claiming it did is worse than staying quiet: the
// member stops worrying because they believe their family knows they're okay,
// and the family is still sitting there waiting. So: check, then speak.
// Returns the parsed body on success, or null — never throws.
async function postJson(url, body) {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!r.ok) return null;
    const d = await r.json().catch(() => ({}));
    return (d && d.success === false) ? null : (d || {});
  } catch {
    return null;
  }
}

async function careAck(uid) {
  const ok = await postJson('/api/family/care-ack', { target_user_id: uid });
  if (!ok) { showToast("Couldn't let them know — check your connection", 'error'); return; }
  showToast("Thanks — your family will see you're on it", 'success');
  loadCarePanel();
}

// Caregiver → member encouragement (one tap; turns monitoring into connection)
async function cheer(uid, name) {
  const ok = await postJson('/api/family/encourage', { to_user_id: uid, emoji: '👏', message: '' });
  showToast(ok ? `👏 Sent encouragement to ${name || 'them'}`
               : "Couldn't send that — try again", ok ? 'success' : 'error');
}

async function pingMember(uid, name) {
  const ok = await postJson('/api/family/ping', { to_user_id: uid });
  showToast(ok ? `💛 Let ${name || 'them'} know you're thinking of them`
               : "Couldn't send that — try again", ok ? 'success' : 'error');
}

// Recipient side: warm cards for encouragements sent to me
async function loadEncouragements() {
  const el = document.getElementById('dash-encouragements');
  if (!el) return;
  const items = await fetch('/api/family/encouragements').then(r => r.json()).catch(() => []);
  if (!Array.isArray(items) || !items.length) { el.style.display = 'none'; return; }
  const verb = { ping: 'is thinking of you', reply: 'is okay 💛' };
  el.innerHTML = items.map(e => `
    <div class="cheer-card">
      <div class="cheer-emoji">${escHtml(e.emoji || '👏')}</div>
      <div class="cheer-body">
        <div class="cheer-from">${escHtml(e.from_name || 'Family')} ${verb[e.kind] || 'cheered you on'}</div>
        ${e.message ? `<div class="cheer-msg">${escHtml(e.message)}</div>` : ''}
      </div>
      ${e.kind === 'ping' ? `<button class="cheer-reply-btn" data-ev-click="replyOkay('${e.id}')">I'm okay 💛</button>` : ''}
    </div>`).join('') +
    `<button class="cheer-dismiss" data-ev-click="dismissEncouragements()">Thanks 💛</button>`;
  el.style.display = '';
}

async function replyOkay(eid) {
  const ok = await postJson(`/api/family/encouragements/${eid}/ok`);
  if (!ok) {
    // Leave the card up so they can retry — this is someone answering a
    // worried family member; a swallowed failure leaves both sides stranded.
    showToast("Couldn't send your reply — check your connection", 'error');
    return;
  }
  showToast("Sent — they'll know you're okay 💛", 'success');
  loadEncouragements();
}

async function dismissEncouragements() {
  await fetch('/api/family/encouragements/read', { method: 'POST' }).catch(() => {});
  const el = document.getElementById('dash-encouragements');
  if (el) el.style.display = 'none';
}

// Low-stock refill nudge — the other half of the pill-stock loop. Now that
// taking a dose decrements stock, surface medicines that are running low so
// the refill actually happens.
async function loadLowStock() {
  const el = document.getElementById('dash-lowstock');
  if (!el) return;
  const low = await fetch('/api/medicines/low-stock').then(r => r.json()).catch(() => []);
  if (!Array.isArray(low) || !low.length) { el.style.display = 'none'; return; }
  const title = low.length === 1
    ? `${escHtml(low[0].name)} is running low`
    : `${low.length} medicines are running low`;
  const detail = low.slice(0, 3).map(m => {
    const d = m.days_left;
    const left = (d != null && isFinite(d)) ? `~${Math.max(0, Math.round(d))}d left` : 'low';
    return `${escHtml(m.name)} · ${left}`;
  }).join('  ·  ');
  el.innerHTML = `
    <div class="lowstock-icon">🔔</div>
    <div class="lowstock-body">
      <div class="lowstock-title">${title} — time to refill</div>
      <div class="lowstock-sub">${detail}</div>
    </div>
    <button class="lowstock-btn" data-ev-click="switchView('medicines')">Review</button>`;
  el.style.display = 'flex';
}

// ── Doctor visit summary (printable one-pager) ──
async function openDoctorSummary() {
  const el = document.getElementById('doctor-summary-content');
  const modal = document.getElementById('doctor-summary-modal');
  if (!el || !modal) return;
  el.innerHTML = '<div style="padding:30px;text-align:center;color:var(--gray-400)">Compiling your summary…</div>';
  modal.style.display = 'flex';
  const d = await fetch('/api/doctor-summary').then(r => r.json()).catch(() => null);
  el.innerHTML = d ? renderDoctorSummary(d)
    : '<div style="padding:20px;color:#DC2626">Could not build the summary.</div>';
}
function closeDoctorSummary() { document.getElementById('doctor-summary-modal').style.display = 'none'; }
function printDoctorSummary() { window.print(); }

function renderDoctorSummary(d) {
  const esc = escapeHtml;
  const p = d.person || {};
  const fmt = iso => { try { return new Date(iso + 'T12:00:00').toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'}); } catch (e) { return iso || ''; } };

  const meds = (d.medications || []).length
    ? `<table class="ds-table"><thead><tr><th>Medicine</th><th>Dose</th><th>Schedule</th></tr></thead><tbody>`
      + d.medications.map(m => `<tr><td>${esc(m.name || '')}</td><td>${esc(((m.dosage || '') + ' ' + (m.unit || '')).trim())}</td><td>${esc((m.times || []).join(', '))}${m.with_food ? ' · with food' : ''}</td></tr>`).join('')
      + `</tbody></table>`
    : '<p class="ds-empty">No active medicines.</p>';

  const vrows = Object.entries(d.vitals || {}).map(([t, v]) =>
    `<tr><td>${esc(t.replace('_', ' '))}</td><td>${esc(String(v.value1))}${v.value2 ? '/' + esc(String(v.value2)) : ''} ${esc(v.unit || '')}</td><td>${fmt(v.date)}</td></tr>`).join('');
  const vitals = vrows
    ? `<table class="ds-table"><thead><tr><th>Vital</th><th>Latest</th><th>Measured</th></tr></thead><tbody>${vrows}</tbody></table>`
    : '<p class="ds-empty">No vitals recorded.</p>';

  const syms = (d.symptoms || []).length
    ? `<ul class="ds-list">` + d.symptoms.map(s => `<li>${esc(s.name)} <span class="ds-muted">(${s.severity}/10 · ${fmt(s.date)})</span></li>`).join('') + `</ul>`
    : '<p class="ds-empty">No symptoms logged in the last 30 days.</p>';

  const adh = d.adherence_30d || {};
  const adhLine = adh.total ? `${adh.pct}% (${adh.taken}/${adh.total} scheduled doses, last 30 days)` : 'No dose history yet';

  return `
    <div class="ds-sheet">
      <div class="ds-topline">
        <div class="ds-brand">🌱 Arogo — Health summary</div>
        <div class="ds-muted">Generated ${fmt(d.generated)}</div>
      </div>
      <div class="ds-name">${esc(p.name || '—')}</div>
      <div class="ds-meta">${[p.age ? 'Age ' + esc(String(p.age)) : '', p.gender ? esc(p.gender) : '', p.blood_type ? 'Blood type ' + esc(p.blood_type) : ''].filter(Boolean).join('  ·  ')}</div>
      ${(d.conditions || d.allergies) ? `<div class="ds-flags">
        ${d.conditions ? `<div><b>Conditions:</b> ${esc(d.conditions)}</div>` : ''}
        ${d.allergies ? `<div><b>Allergies:</b> ${esc(d.allergies)}</div>` : ''}
      </div>` : ''}
      <h2 class="ds-h2">Current medications</h2>${meds}
      <div class="ds-muted" style="margin-top:6px">Adherence: ${esc(adhLine)}</div>
      <h2 class="ds-h2">Latest vitals</h2>${vitals}
      <h2 class="ds-h2">Recent symptoms (30 days)</h2>${syms}
      <div class="ds-foot ds-muted">Generated by the patient from self-tracked data in Arogo. Not an official medical record.</div>
    </div>`;
}

async function openCalorieBreakdown() {
  const cb = await fetch('/api/calorie-balance').then(r => r.json()).catch(() => null);
  if (!cb) return;

  const t        = cb.today || {};
  const targets  = cb.targets || {};
  const profile  = cb.profile || {};
  const eaten    = t.eaten    || 0;
  const burned   = t.burned   || 0;
  // No profile → no target, and therefore no budget, no net and no percentage.
  // These used to fall back to 2000 and present the result as the user's own.
  const known    = cb.has_target && t.target;
  const target   = known ? t.target : null;
  const budget   = known ? (t.budget || target) : null;
  const net      = known ? (t.net || 0) : null;
  const pct      = known ? Math.min(Math.round((eaten / budget) * 100), 150) : 0;
  const today    = localToday();

  // Date label
  const d = new Date(today + 'T12:00:00');
  setText('cbd-date-label', d.toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' }));

  // Equation — show budget (target + burned) not raw target
  setText('cbd-target-val', known ? budget + ' kcal' : 'Not set');
  setText('cbd-eaten-val',  eaten  + ' kcal');
  setText('cbd-result-val', known ? Math.abs(net) + ' kcal' : '—');

  // Sub-label under target shows the breakdown when exercise exists
  const targetBlock = document.querySelector('.cbd-eq-block--target');
  if (targetBlock) {
    const sub = targetBlock.querySelector('.cbd-eq-label');
    if (sub) sub.textContent = burned > 0
      ? `Budget (${target} + ${burned} burned)`
      : 'Daily budget';
  }

  const resultBlock = document.getElementById('cbd-result-block');
  const resultLabel = document.getElementById('cbd-result-label');
  const resultIcon  = document.getElementById('cbd-result-icon');
  if (resultBlock) {
    resultBlock.className = 'cbd-eq-block cbd-eq-block--result ' +
      (net < -100 ? 'surplus' : net > 100 ? 'deficit' : 'balanced');
  }
  if (resultLabel) resultLabel.textContent = net < -100 ? 'Over budget' : net > 100 ? 'Remaining' : 'Balanced!';
  if (resultIcon)  resultIcon.textContent  = net < -100 ? '⚠️' : net > 100 ? '✅' : '⚖️';

  // Progress bar
  const fill = document.getElementById('cbd-progress-fill');
  if (fill) {
    fill.style.width = Math.min(pct, 100) + '%';
    fill.classList.toggle('over', pct > 105);
  }
  setText('cbd-progress-pct-label', `${pct}% of daily budget`);
  setText('cbd-target-label', budget + ' kcal');

  // Macro bars
  const foodDay = await fetch(`/api/food/log/${today}`).then(r => r.json()).catch(() => null);
  const totals  = foodDay?.summary?.totals || {};
  const macros  = [
    { id:'prot',  val: Math.round(totals.protein||0), target: targets.protein_g, unit:'g' },
    { id:'carb',  val: Math.round(totals.carbs||0),   target: targets.carbs_g,   unit:'g' },
    { id:'fat',   val: Math.round(totals.fat||0),     target: targets.fat_g,     unit:'g' },
    { id:'fiber', val: Math.round(totals.fiber||0),   target: targets.fiber_g,   unit:'g' },
  ];
  macros.forEach(m => {
    const bar = document.getElementById(`cbd-bar-${m.id}`);
    const val = document.getElementById(`cbd-${m.id}-val`);
    const has = hasTargets(targets) && m.target;
    if (bar) bar.style.width = has ? Math.min((m.val / m.target) * 100, 100).toFixed(0) + '%' : '0%';
    if (val) val.textContent = has ? `${m.val}${m.unit} / ${m.target}${m.unit}` : `${m.val}${m.unit}`;
  });

  // Workouts today
  const formulaEl = document.getElementById('cbd-formula-rows');
  if (formulaEl) {
    const goalLabels = {
      lose_fast: 'Lose fast (−500)', lose: 'Lose weight (−250)',
      maintain: 'Maintain (±0)', gain: 'Gain muscle (+250)', gain_fast: 'Bulk (+500)',
    };
    const workoutsHTML = t.workouts?.length
      ? t.workouts.map(w =>
          `<div class="cbd-formula-row">
            <span class="cbd-formula-key">🏃 ${escHtml(w.name || w.type)} (${w.duration} min)</span>
            <span class="cbd-formula-val" style="color:#22C55E">+${w.calories} kcal</span>
           </div>`).join('')
      : '';
    formulaEl.innerHTML = `
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">BMR (${profile.gender||'male'}, ${profile.age||25} yrs, ${profile.weight_kg||70}kg, ${profile.height_cm||170}cm)</span>
        <span class="cbd-formula-val">${targets.bmr||'—'} kcal</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">× Activity multiplier (${(profile.activity_level||'moderate').replace('_',' ')})</span>
        <span class="cbd-formula-val">${targets.tdee||'—'} kcal TDEE</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">Goal adjustment</span>
        <span class="cbd-formula-val">${goalLabels[profile.goal||'maintain']}</span>
      </div>
      ${workoutsHTML}
      <div class="cbd-formula-row" style="border-top:1px solid var(--gray-100);margin-top:6px;padding-top:6px">
        <span class="cbd-formula-key" style="font-weight:600">Daily budget</span>
        <span class="cbd-formula-val highlight">${budget} kcal</span>
      </div>
    `;
  }

  // 7-day trend chart
  renderCalorieTrendChart(cb.daily || []);

  // CTA text
  const ctaEl = document.getElementById('cbd-cta-text');
  if (ctaEl) {
    const logCount = foodDay?.summary?.log_count || 0;
    if (logCount === 0) {
      ctaEl.textContent = "No food logged today yet. Add your meals to see the full picture.";
    } else if (net > 300) {
      ctaEl.textContent = `${net} kcal remaining. ${burned > 0 ? 'Great job burning ' + burned + ' kcal!' : 'Log a workout to earn more calories.'}`;
    } else if (net < -100) {
      ctaEl.textContent = `${Math.abs(net)} kcal over budget. A ${Math.round(Math.abs(net)/8)}-min walk would balance it.`;
    } else {
      ctaEl.textContent = "Nice balance today! You're right on target.";
    }
  }

  document.getElementById('calorie-breakdown-overlay').style.display = 'flex';
}


function renderSuggestions(el, suggestions) {
  if (suggestions.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:8px 0">Log workouts to get personalized suggestions.</div>';
    return;
  }
  el.innerHTML = suggestions.map(s => `
    <div class="suggestion-item suggestion-item--${s.type}">
      <div class="sug-icon">${s.icon}</div>
      <div class="sug-text">${escHtml(s.text)}</div>
    </div>
  `).join('');
}

function renderWeeklyChart(days) {
  const el = document.getElementById('weekly-chart');
  if (!el) return;
  const entries = Object.entries(days);
  if (entries.length === 0) { el.innerHTML = '<div style="color:var(--gray-400);font-size:13px">No activity data yet</div>'; return; }
  const maxCal = Math.max(...entries.map(([,v]) => v.calories), 1);
  const maxMin = Math.max(...entries.map(([,v]) => v.duration), 1);
  const dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  el.innerHTML = entries.map(([date, data], i) => {
    const calH = Math.round((data.calories / maxCal) * 90);
    const minH = Math.round((data.duration / maxMin) * 90);
    const isToday = date === localToday();
    return `
      <div class="week-bar-col">
        <div class="week-bar-wrap">
          <div class="week-bar week-bar--cal" style="height:${calH}px;opacity:${isToday?1:.7}" title="${data.calories} cal"></div>
          <div class="week-bar week-bar--min" style="height:${minH}px;opacity:${isToday?1:.7}" title="${data.duration} min"></div>
        </div>
        <div class="week-bar-label" style="font-weight:${isToday?'600':'400'};color:${isToday?'var(--teal-600)':'var(--gray-400)'}">${dayNames[i]}</div>
        <div class="week-bar-count">${data.calories > 0 ? data.calories : ''}</div>
      </div>`;
  }).join('');
}

// ── Reports ──
function openUploadModal() {
  document.getElementById('upload-modal-overlay').style.display = 'flex';
}

async function loadReports() {
  const search = document.getElementById('search-input')?.value || '';
  const severity = document.getElementById('severity-filter')?.value || '';
  const tag = document.getElementById('tag-filter')?.value || '';
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (severity) params.set('severity', severity);
  if (tag) params.set('tag', tag);
  const reports = await fetch(`/api/reports?${params}`).then(r => r.json()).catch(() => []);
  const label = document.getElementById('reports-count-label');
  if (label) label.textContent = `${reports.length} report${reports.length !== 1 ? 's' : ''}`;
  const grid = document.getElementById('reports-grid');
  if (!grid) return;
  if (reports.length === 0) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No reports found</div><div class="empty-sub">Upload your first medical report</div><button class="btn-primary" data-ev-click="openUploadModal()">Upload Report</button></div>`;
    return;
  }
  grid.innerHTML = reports.map(r => `
    <div class="report-card" data-ev-click="openReportDetail(${JSON.stringify(r).replace(/"/g,'&quot;')})">
      <div class="report-card-header">
        <div class="report-card-file-icon">${fileIcon(r.file_ext)}</div>
        <div class="report-card-info">
          <div class="report-card-title" title="${escHtml(r.original_name)}">${escHtml(r.original_name)}</div>
          <div class="report-card-patient">${escHtml(r.patient_name)}${r.doctor ? ' · ' + escHtml(r.doctor) : ''}</div>
        </div>
        <span class="severity-badge sev-badge-${r.severity}">${r.severity}</span>
      </div>
      ${r.tags?.length ? `<div class="report-card-tags">${r.tags.slice(0,4).map(t=>`<span class="report-tag">${escHtml(t)}</span>`).join('')}${r.tags.length>4?`<span class="report-tag">+${r.tags.length-4}</span>`:''}</div>` : ''}
      ${r.analysis_notes ? `<div class="report-card-notes">${escHtml(r.analysis_notes)}</div>` : ''}
      <div class="report-card-footer">
        <span class="report-card-date">${r.report_date}</span>
        <div class="report-card-actions">
          <button class="btn-icon" title="Download" data-ev-click="event.stopPropagation();downloadFile('/uploads/${r.filename}',r.original_name)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </button>
          <button class="btn-icon" title="Delete" data-ev-click="event.stopPropagation();deleteReport('${r.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>
    </div>
  `).join('');
}

function openReportDetail(r) {
  document.getElementById('rdetail-title').textContent = r.original_name;
  document.getElementById('rdetail-body').innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">
      <div style="font-size:40px">${fileIcon(r.file_ext)}</div>
      <div>
        <div style="font-size:13px;color:var(--gray-400)">${escHtml(r.patient_name)}${r.doctor?' · Dr. '+escHtml(r.doctor):''}</div>
        <span class="severity-badge sev-badge-${r.severity}" style="margin-top:6px;display:inline-block">${r.severity}</span>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px">
      ${[['Type',r.report_type],['Date',r.report_date],['Uploaded',new Date(r.upload_date).toLocaleDateString()],['Format',(r.file_ext||'').toUpperCase()]].map(([l,v])=>`<div><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:3px">${l}</div><div style="font-size:13.5px;font-family:'JetBrains Mono',monospace;color:var(--gray-800)">${v}</div></div>`).join('')}
    </div>
    ${r.tags?.length?`<div style="margin-bottom:18px"><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:8px">Tags</div><div style="display:flex;flex-wrap:wrap;gap:6px">${r.tags.map(t=>`<span class="report-tag">${escHtml(t)}</span>`).join('')}</div></div>`:''}
    ${r.analysis_notes?`<div style="margin-bottom:18px"><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:8px">Analysis Notes</div><div style="font-size:13.5px;line-height:1.7;color:var(--gray-700);background:var(--gray-25);border:1px solid var(--gray-100);border-radius:var(--r-md);padding:12px">${escHtml(r.analysis_notes)}</div></div>`:''}
    <div id="rdetail-readings" style="margin-bottom:18px"></div>
    <div class="form-actions" style="margin-top:16px;padding-top:16px">
      <button class="btn-primary" data-ev-click="downloadFile('/uploads/${r.filename}','${r.original_name}')">Download</button>
      <button class="btn-danger" data-ev-click="deleteReport('${r.id}');closeModal('report-detail-overlay')">Delete</button>
    </div>
  `;
  document.getElementById('report-detail-overlay').style.display = 'flex';
  loadReportReadings(r.id);
}

// ── Readings found in a report ──
// An uploaded report used to be a filing cabinet: it went in and nothing came
// back. We read the numbers out of it and *offer* them — the user confirms
// every one. Wrong data in a health chart is worse than no data, so nothing
// here writes a vital until they say so.
let _reportReadings = [], _reportReadingsDate = '';

function _readingValue(v) {
  return v.value2 ? `${+v.value1}/${+v.value2}` : `${+v.value1}`;
}

async function loadReportReadings(rid) {
  const box = document.getElementById('rdetail-readings');
  if (!box) return;
  box.innerHTML = `<div style="font-size:12.5px;color:var(--gray-400)">Checking this report for readings…</div>`;
  let d;
  try {
    d = await (await fetch(`/api/reports/${rid}/readings`)).json();
  } catch { box.innerHTML = ''; return; }

  _reportReadings = d.readings || [];
  _reportReadingsDate = d.date_key || localToday();

  if (!_reportReadings.length) {
    // Say why, rather than showing nothing and letting them wonder.
    box.innerHTML = d.reason
      ? `<div style="font-size:12.5px;color:var(--gray-400);background:var(--gray-25);border:1px solid var(--gray-100);border-radius:var(--r-md);padding:10px 12px">${escHtml(d.reason)}</div>`
      : '';
    return;
  }

  box.innerHTML = `
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--gray-400);margin-bottom:8px">
      Readings in this report
    </div>
    <div style="font-size:12.5px;color:var(--gray-500);margin-bottom:10px">
      We read these off the report — check them against it, then add the ones you want.
      Nothing is saved to your vitals until you do.
    </div>
    <div style="display:flex;flex-direction:column;gap:8px">
      ${_reportReadings.map((v, i) => `
        <label style="display:flex;gap:10px;align-items:flex-start;background:var(--gray-25);border:1px solid var(--gray-100);border-radius:var(--r-md);padding:10px 12px;cursor:pointer">
          <input type="checkbox" class="rdetail-reading-cb" data-idx="${i}" checked style="margin-top:3px">
          <span style="flex:1;min-width:0">
            <span style="font-size:13.5px;color:var(--gray-800)">
              <b>${escHtml(v.label)}</b>
              <span style="font-family:'JetBrains Mono',monospace">${_readingValue(v)}</span>
              ${escHtml(v.unit || '')}
              ${v.note ? `<span style="color:var(--gray-400);font-size:11.5px"> · ${escHtml(v.note)}</span>` : ''}
            </span>
            <span style="display:block;font-size:11.5px;color:var(--gray-400);margin-top:3px;overflow-wrap:anywhere">
              from the report: “${escHtml(v.context || '')}”
            </span>
          </span>
        </label>`).join('')}
    </div>
    <button class="btn-secondary" style="margin-top:10px" data-ev-click="addReportReadings('${rid}')"
            id="rdetail-add-readings">Add checked to vitals</button>
  `;
}

async function addReportReadings() {
  const btn = document.getElementById('rdetail-add-readings');
  const picked = [..._reportReadings.keys()].filter(i =>
    document.querySelector(`.rdetail-reading-cb[data-idx="${i}"]`)?.checked);
  if (!picked.length) { showToast('Nothing checked to add', 'error'); return; }
  if (btn) { btn.disabled = true; btn.textContent = 'Adding…'; }

  let added = 0;
  for (const i of picked) {
    const v = _reportReadings[i];
    try {
      const r = await fetch('/api/vitals', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: v.type, value1: v.value1, value2: v.value2, unit: v.unit,
          // Date it to the day of the test, not the day it was uploaded.
          date_key: _reportReadingsDate,
          notes: 'From lab report',
        }),
      });
      if ((await r.json()).success) added++;
    } catch { /* counted as not added */ }
  }

  // Report honestly: if some failed the range check, don't claim they landed.
  showToast(added === picked.length
      ? `Added ${added} reading${added > 1 ? 's' : ''} to vitals`
      : `Added ${added} of ${picked.length} — check the rest by hand`,
    added ? 'success' : 'error');
  if (added) { closeModal('report-detail-overlay'); loadDashboard(); }
  else if (btn) { btn.disabled = false; btn.textContent = 'Add checked to vitals'; }
}

function deleteReport(id) {
  undoable('Deleting report…', async () => {
    await fetch(`/api/reports/${id}`, { method:'DELETE' });
    loadReports();
    loadDashboard();
  });
}

// ── Upload Form ──
function setupDropzone() {
  const dz = document.getElementById('dropzone');
  const fi = document.getElementById('file-input');
  if (!dz || !fi) return;
  dz.addEventListener('click', e => { if (e.target === dz || e.target.closest('.dropzone') === dz) fi.click(); });
  fi.addEventListener('change', () => { if (fi.files[0]) setFile(fi.files[0]); });
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('drag-over'); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });
}

function setFile(file) {
  selectedFile = file;
  const icons = { pdf:'📄', png:'🖼️', jpg:'🖼️', jpeg:'🖼️', txt:'📝', csv:'📊' };
  const ext = file.name.split('.').pop().toLowerCase();
  document.getElementById('file-preview-icon').textContent = icons[ext] || '📄';
  document.getElementById('file-preview-name').textContent = file.name;
  document.getElementById('file-preview-size').textContent = fmtBytes(file.size);
  document.getElementById('dropzone').style.display = 'none';
  document.getElementById('file-preview').style.display = 'flex';
}

function clearFile() {
  selectedFile = null;
  document.getElementById('file-input').value = '';
  document.getElementById('dropzone').style.display = 'flex';
  document.getElementById('file-preview').style.display = 'none';
}

function setupTagPicker() {
  document.querySelectorAll('.tag-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tag = btn.dataset.tag;
      if (btn.classList.contains('selected')) { selectedTags = selectedTags.filter(t=>t!==tag); btn.classList.remove('selected'); }
      else { selectedTags.push(tag); btn.classList.add('selected'); }
      renderSelectedTags();
    });
  });
}

function addCustomTag() {
  const input = document.getElementById('custom-tag-input');
  const val = input.value.trim();
  if (val && !selectedTags.includes(val)) { selectedTags.push(val); renderSelectedTags(); input.value = ''; }
}

document.getElementById('custom-tag-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addCustomTag(); } });

function renderSelectedTags() {
  const el = document.getElementById('selected-tags');
  if (!el) return;
  el.innerHTML = selectedTags.map(tag => `
    <span class="selected-tag">${escHtml(tag)}<span class="selected-tag-remove" data-ev-click="removeTag('${escHtml(tag)}')">×</span></span>
  `).join('');
}

function removeTag(tag) {
  selectedTags = selectedTags.filter(t => t !== tag);
  const btn = document.querySelector(`.tag-btn[data-tag="${tag}"]`);
  if (btn) btn.classList.remove('selected');
  renderSelectedTags();
}

function setupUploadForm() {
  document.getElementById('upload-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!selectedFile) { showToast('Please select a file', 'error'); return; }
    const form = e.target;
    const fd = new FormData();
    fd.append('file', selectedFile);
    ['patient_name','doctor','report_type','report_date','analysis_notes'].forEach(n => fd.append(n, form[n]?.value || ''));
    fd.append('severity', form.querySelector('input[name="severity"]:checked')?.value || 'normal');
    selectedTags.forEach(t => fd.append('tags', t));
    const btn = document.getElementById('submit-btn');
    btn.disabled = true; btn.textContent = 'Uploading…';
    try {
      const res = await fetch('/api/upload', { method:'POST', body:fd });
      const data = await res.json();
      if (data.success) {
        showToast('Report uploaded!', 'success');
        form.reset(); clearFile(); selectedTags = []; renderSelectedTags();
        document.querySelectorAll('.tag-btn.selected').forEach(b => b.classList.remove('selected'));
        setDates();
        closeModal('upload-modal-overlay');
        loadReports();
        // If the report has readings in it, this is the moment to offer them —
        // they just held the document; they'd never think to reopen it later.
        // Quiet when there's nothing to add: no modal, no interruption.
        try {
          const rd = await (await fetch(`/api/reports/${data.report.id}/readings`)).json();
          if (rd.readings?.length) openReportDetail(data.report);
        } catch { /* the report is saved either way */ }
      } else showToast(data.error || 'Upload failed', 'error');
    } catch { showToast('Network error', 'error'); }
    finally { btn.disabled = false; btn.textContent = 'Upload & Save'; }
  });
}

// ── Medicines ──
function openMedModal() {
  document.getElementById('med-modal-overlay').style.display = 'flex';
}

async function loadMedicines() {
  const [meds, doses] = await Promise.all([
    fetch('/api/medicines').then(r => r.json()).catch(() => []),
    fetch('/api/medicines/today').then(r => r.json()).catch(() => [])
  ]);
  renderTodayTimeline(doses);
  renderMedicinesGrid(meds);
  // cache active names so the add-medicine form can warn about duplicates
  window._activeMedNames = (Array.isArray(meds) ? meds : [])
    .filter(m => m.active).map(m => (m.name || '').trim().toLowerCase());
  const mc = document.getElementById('med-count');
  if (mc) mc.textContent = `${meds.filter(m=>m.active).length} active`;
  loadMedAdherence();
}

// ── Drug-name autocomplete on the add-medicine form ─────────────────────────
let _drugSuggestTimer = null, _drugSuggestIdx = -1;

function drugAutocomplete(value) {
  const box = document.getElementById('med-name-suggest');
  const input = document.getElementById('med-name-input');
  checkDupMedicine(value);
  const q = (value || '').trim();
  if (!box) return;
  if (q.length < 2) { _hideDrugSuggest(); return; }
  clearTimeout(_drugSuggestTimer);
  _drugSuggestTimer = setTimeout(async () => {
    const r = await fetch('/api/medicines/drugs?q=' + encodeURIComponent(q)).then(x => x.json()).catch(() => null);
    if (!r || !r.drugs || !r.drugs.length) { _hideDrugSuggest(); return; }
    // don't keep showing the list once it exactly matches what they typed
    if (r.drugs.length === 1 && r.drugs[0].name.toLowerCase() === q.toLowerCase()) { _hideDrugSuggest(); return; }
    _drugSuggestIdx = -1;
    box.innerHTML = r.drugs.map((d, i) =>
      `<div class="drug-suggest-item" role="option" data-idx="${i}" data-ev-click="pickDrug('${escHtml(d.name).replace(/'/g, "\\'")}')">
        <span>${escHtml(d.name)}</span><span class="dsi-hint">${escHtml(d.hint || '')}</span>
      </div>`).join('');
    box.style.display = 'block';
    if (input) input.setAttribute('aria-expanded', 'true');
  }, 150);
}

function _hideDrugSuggest() {
  const box = document.getElementById('med-name-suggest');
  const input = document.getElementById('med-name-input');
  if (box) { box.style.display = 'none'; box.innerHTML = ''; }
  if (input) input.setAttribute('aria-expanded', 'false');
  _drugSuggestIdx = -1;
}

function pickDrug(name) {
  const input = document.getElementById('med-name-input');
  if (input) { input.value = name; input.focus(); }
  _hideDrugSuggest();
  checkDupMedicine(name);
}

function drugAutocompleteKey(e) {
  const box = document.getElementById('med-name-suggest');
  if (!box || box.style.display === 'none') return;
  const items = [...box.querySelectorAll('.drug-suggest-item')];
  if (!items.length) return;
  if (e.key === 'ArrowDown') { _drugSuggestIdx = Math.min(_drugSuggestIdx + 1, items.length - 1); _highlightDrug(items); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { _drugSuggestIdx = Math.max(_drugSuggestIdx - 1, 0); _highlightDrug(items); e.preventDefault(); }
  else if (e.key === 'Enter' && _drugSuggestIdx >= 0) { items[_drugSuggestIdx].click(); e.preventDefault(); }
  else if (e.key === 'Escape') { _hideDrugSuggest(); }
}

function _highlightDrug(items) {
  items.forEach((it, i) => it.classList.toggle('active', i === _drugSuggestIdx));
  items[_drugSuggestIdx]?.scrollIntoView({ block: 'nearest' });
}

// Safe, data-free duplicate check — no interaction data, just "you already
// track this name", so the same medicine isn't added twice by accident.
function checkDupMedicine(value) {
  const warn = document.getElementById('med-name-dup');
  if (!warn) return;
  const name = (value || '').trim().toLowerCase();
  const names = window._activeMedNames || [];
  if (name && names.includes(name)) {
    warn.textContent = '⚠️ You already track a medicine called “' + value.trim() + '”.';
    warn.style.display = 'block';
  } else {
    warn.style.display = 'none';
  }
}

function fmt12(t) {
  if (!t || !t.includes(':')) return t || '';
  let [h, m] = t.split(':').map(Number);
  const ap = h >= 12 ? 'pm' : 'am';
  h = h % 12 || 12;
  return `${h}:${String(m).padStart(2, '0')} ${ap}`;
}

function renderTodayTimeline(doses) {
  const el = document.getElementById('today-dose-timeline');
  if (!el) return;
  const total = doses.length, taken = doses.filter(d => d.taken).length;
  // ── Focal panel: adherence ring + next dose ──
  const focal = document.getElementById('med-focal');
  if (focal) focal.style.display = total > 0 ? 'flex' : 'none';
  const ring = document.getElementById('med-ring');
  if (ring) ring.setAttribute('stroke-dasharray', `${total ? (taken / total * 194.8).toFixed(1) : 0} 194.8`);
  setText('med-ring-val', `${taken}/${total}`);
  setText('med-ring-label', (total && taken === total) ? 'all doses taken 🎉' : 'doses taken today');
  const nextIcon = document.getElementById('med-next-icon');
  const upcoming = [...doses].filter(d => !d.taken)
    .sort((a, b) => (a.time || '').localeCompare(b.time || ''))[0];
  if (upcoming) {
    setText('med-next-val', `${fmt12(upcoming.time)} · ${escHtml(upcoming.med_name)}`);
    setText('med-next-key', `${upcoming.dosage} ${upcoming.unit}${upcoming.with_food ? ' · with food' : ''}`);
    if (nextIcon) nextIcon.textContent = upcoming.icon || '💊';
  } else if (total) {
    setText('med-next-val', 'All done for today');
    setText('med-next-key', 'nothing left to take');
    if (nextIcon) nextIcon.textContent = '✅';
  }
  if (doses.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:16px 0;text-align:center">No doses scheduled. <a href="#" data-ev-click="openMedModal();return false" style="color:var(--teal-600)">Add a medicine →</a></div>';
    return;
  }
  // Group by time
  const byTime = {};
  doses.forEach(d => { if (!byTime[d.time]) byTime[d.time] = []; byTime[d.time].push(d); });
  const times = Object.keys(byTime).sort();
  const now = new Date().toTimeString().slice(0,5);
  el.innerHTML = times.map((time, idx) => {
    const group = byTime[time];
    const allTaken = group.every(d => d.taken);
    const isPast = time < now;
    const dotClass = allTaken ? 'taken' : (isPast ? 'missed' : '');
    return `
      <div class="dose-slot">
        <div class="dose-time-col"><span class="dose-time-label">${time}</span></div>
        <div class="dose-line-col">
          <div class="dose-dot ${dotClass}"></div>
          ${idx < times.length - 1 ? '<div class="dose-vline"></div>' : ''}
        </div>
        <div class="dose-cards-col">
          ${group.map(d => `
            <div class="dose-card ${d.taken ? 'taken' : ''}" data-ev-click="markDoseTaken('${d.med_id}','${d.time}',this)">
              <div class="dose-card-emoji">${d.icon}</div>
              <div class="dose-card-info">
                <div class="dose-card-name">${escHtml(d.med_name)}</div>
                <div class="dose-card-detail">${d.dosage} ${d.unit}${d.with_food ? ' · 🍽️ with food' : ''}</div>
              </div>
              <div class="dose-card-check">${d.taken ? '✓' : ''}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }).join('');
}

function renderMedicinesGrid(meds) {
  const grid = document.getElementById('medicines-grid');
  if (!grid) return;
  if (meds.length === 0) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">💊</div><div class="empty-text">No medicines added</div><div class="empty-sub">Add your first medicine to track doses</div><button class="btn-primary" data-ev-click="openMedModal()">Add Medicine</button></div>`;
    return;
  }
  grid.innerHTML = meds.map(m => {
    // Pill count / refill section
    const hasPills = m.pill_count != null;
    const freqDoses = {once_daily:1,twice_daily:2,thrice_daily:3,weekly:1/7}[m.frequency] || 1;
    const daysLeft = hasPills ? Math.floor(m.pill_count / Math.max(freqDoses * (m.pills_per_dose||1), 0.01)) : null;
    const maxDays  = m.refill_threshold ? m.refill_threshold * 4 : 28;
    const fillPct  = hasPills ? Math.min(100, Math.round((daysLeft / maxDays) * 100)) : 0;
    const isLow    = hasPills && daysLeft < (m.refill_threshold || 7);
    const stockColor = isLow ? '#EF4444' : daysLeft < (m.refill_threshold||7)*2 ? '#F59E0B' : '#22C55E';

    const pillSection = hasPills ? `
      <div class="med-pill-track">
        <div class="med-pill-track-row">
          <span class="med-pill-count-label" style="color:${stockColor}">
            ${isLow ? '⚠️' : '💊'} ${m.pill_count} pills · ${daysLeft}d left
          </span>
          <button class="med-restock-btn" data-ev-click="openRestockModal('${m.id}','${escHtml(m.name)}',${m.pill_count},${m.pills_per_dose||1},${m.refill_threshold||7})">Restock</button>
        </div>
        <div class="med-pill-bar-track">
          <div class="med-pill-bar-fill" style="width:${fillPct}%;background:${stockColor}"></div>
        </div>
      </div>` : `
      <div class="med-pill-track med-pill-track--empty">
        <button class="med-add-stock-btn" data-ev-click="openRestockModal('${m.id}','${escHtml(m.name)}',0,1,7)">+ Track pill count</button>
      </div>`;

    return `<div class="med-card med-card--${m.color}${isLow?' med-card--low-stock':''}">
      <div class="med-card-header">
        <div class="med-card-icon">${m.icon}</div>
        <div class="med-card-info">
          <div class="med-card-name">${escHtml(m.name)}</div>
          <div class="med-card-dose">${m.dosage} ${m.unit} · ${freqLabel(m.frequency)}</div>
        </div>
      </div>
      <div class="med-card-times">
        ${m.times?.map(t => `<span class="time-chip">⏰ ${t}</span>`).join('') || ''}
        ${m.with_food ? '<span class="med-food-badge">🍽️ With food</span>' : ''}
      </div>
      ${m.notes ? `<div style="font-size:12px;color:var(--gray-400);margin-bottom:8px">${escHtml(m.notes)}</div>` : ''}
      ${pillSection}
      <div class="med-card-footer">
        <span class="med-card-status ${m.active ? 'active' : ''}">● ${m.active ? 'Active' : 'Paused'}</span>
        <div class="med-card-actions">
          <button class="btn-icon" title="${m.active ? 'Pause' : 'Activate'}" data-ev-click="toggleMed('${m.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">${m.active ? '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>' : '<polygon points="5 3 19 12 5 21 5 3"/>'}</svg>
          </button>
          <button class="btn-icon" title="Delete" data-ev-click="deleteMed('${m.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function markDoseTaken(medId, time, el) {
  const date = localToday();
  // Never claim a dose landed without checking. This is the core adherence
  // loop: if the write failed and we say "taken ✓", the user stops thinking
  // about it, the dose stays unlogged, and their family gets escalated to
  // about a dose they actually took.
  const r = await fetch(`/api/medicines/${medId}/log`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ date, time, taken:true })
  }).then(r => r.json()).catch(() => null);
  if (!r?.success) {
    showToast("Couldn't log that dose — check your connection and try again", 'error');
    return;
  }
  showToast('Dose marked as taken ✓', 'success');
  loadMedicines();
  loadDashboard();
}

async function toggleMed(id) {
  await fetch(`/api/medicines/${id}/toggle`, { method:'POST' });
  loadMedicines();
}

function deleteMed(id) {
  undoable('Removing medicine…', async () => {
    await fetch(`/api/medicines/${id}`, { method:'DELETE' });
    loadMedicines();
  });
}

function setupMedForm() {
  document.getElementById('med-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const times = [...document.querySelectorAll('.time-input')].map(i => i.value).filter(Boolean);
    const body = {
      name: form.name.value,
      dosage: form.dosage.value,
      unit: form.unit.value,
      frequency: form.querySelector('input[name="frequency"]:checked')?.value || 'once_daily',
      times,
      with_food: document.getElementById('with-food-toggle')?.checked || false,
      notes: form.notes.value,
      start_date: form.start_date.value,
      end_date: form.end_date.value,
      icon: selectedIcon,
      color: selectedColor
    };
    const res = await fetch('/api/medicines', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    const data = await res.json();
    if (data.success) {
      // Save pill count if entered
      const pillCount = parseInt(document.getElementById('med-pill-count')?.value);
      if (pillCount > 0) {
        await fetch(`/api/medicines/${data.medicine.id}/stock`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            pill_count:  pillCount,
            pills_per_dose: parseInt(document.getElementById('med-pills-per-dose')?.value) || 1,
            refill_threshold: parseInt(document.getElementById('med-refill-threshold')?.value) || 7
          })
        });
      }
      showToast(`${body.name} added!`, 'success');
      form.reset(); setDates();
      resetTimeSlots();
      document.getElementById('med-pill-count').value = '';
      document.getElementById('med-pills-per-dose').value = '1';
      document.getElementById('med-refill-threshold').value = '7';
      document.getElementById('refill-fields').style.display = 'none';
      document.getElementById('refill-chevron').style.transform = 'rotate(-90deg)';
      closeModal('med-modal-overlay');
      loadMedicines();
    } else showToast('Failed to add medicine', 'error');
  });
}

function addTimeSlot() {
  const slots = document.getElementById('time-slots');
  const row = document.createElement('div');
  row.className = 'time-slot-row';
  row.innerHTML = `<input type="time" class="form-input time-input" value="12:00"><button type="button" class="btn-icon slot-remove" data-ev-click="removeTimeSlot(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>`;
  slots.appendChild(row);
}

function removeTimeSlot(btn) {
  const slots = document.getElementById('time-slots');
  if (slots.children.length > 1) btn.closest('.time-slot-row').remove();
}

function resetTimeSlots() {
  const slots = document.getElementById('time-slots');
  if (slots) slots.innerHTML = `<div class="time-slot-row"><input type="time" class="form-input time-input" value="08:00"><button type="button" class="btn-icon slot-remove" data-ev-click="removeTimeSlot(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>`;
}

function setupFreqPicker() {
  document.querySelectorAll('.freq-opt input').forEach(input => {
    input.addEventListener('change', () => {
      const counts = { once_daily:1, twice_daily:2, thrice_daily:3, weekly:1 };
      const count = counts[input.value] || 1;
      const slots = document.getElementById('time-slots');
      if (!slots) return;
      const defaultTimes = ['08:00','13:00','20:00'];
      while (slots.children.length < count) addTimeSlot();
      while (slots.children.length > count) slots.lastChild.remove();
      [...slots.querySelectorAll('.time-input')].forEach((inp, i) => { if (defaultTimes[i]) inp.value = defaultTimes[i]; });
    });
  });
}

function setupIconColorPicker() {
  document.querySelectorAll('.icon-opt').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.icon-opt').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedIcon = btn.dataset.icon;
    });
  });
  document.querySelectorAll('.color-opt').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.color-opt').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedColor = btn.dataset.color;
    });
  });
}

// ── Reminders / Notifications ──
function checkNotifPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    document.getElementById('notif-banner').style.display = 'flex';
  }
  notifPermission = Notification.permission;
}

function requestNotifPermission() {
  if (!('Notification' in window)) return;
  Notification.requestPermission().then(perm => {
    notifPermission = perm;
    document.getElementById('notif-banner').style.display = 'none';
    if (perm === 'granted') {
      showToast('Notifications enabled! 🔔', 'success');
      // Reminders come from the server (scheduler.py) so they arrive with the
      // tab closed and their action buttons actually work.
      setupPushSubscription();
    }
  });
}

// ── Fitness ──
function openActivityModal() {
  document.getElementById('activity-modal-overlay').style.display = 'flex';
  // Render fields for currently selected type (default: running)
  setTimeout(() => renderActivityFields(selectedActivityType || 'running'), 0);
}
function openConnectModal() { document.getElementById('connect-modal-overlay').style.display = 'flex'; }

async function loadFitness() {
  const today = localToday();
  const [stats, activities, consistency, foodDay, profile] = await Promise.all([
    fetch('/api/fitness/stats').then(r => r.json()).catch(() => ({})),
    fetch('/api/fitness/activities').then(r => r.json()).catch(() => []),
    fetch('/api/fitness/consistency').then(r => r.json()).catch(() => ({})),
    fetch(`/api/food/log/${today}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/profile').then(r => r.json()).catch(() => null)
  ]);

  setText('fit-week-acts', stats.week?.activities || 0);
  setText('fit-week-min', stats.week?.duration || 0);
  setText('fit-week-cal', (stats.week?.calories || 0).toLocaleString());
  setText('fit-week-km', `${stats.week?.distance || 0} km`);
  // Show today's burned calories as a sub-label under the weekly total
  const todayCal = stats.today?.calories || 0;
  const todaySubEl = document.getElementById('fit-today-cal-sub');
  if (todaySubEl) todaySubEl.textContent = todayCal > 0 ? `${todayCal} today` : '';

  const sugEl = document.getElementById('fitness-suggestions');
  if (sugEl) renderSuggestions(sugEl, stats.suggestions || []);
  renderTypeChart(stats.type_breakdown || {});
  renderActivityFeed(activities);
  const ac = document.getElementById('activity-count');
  if (ac) ac.textContent = `${activities.length} total`;

  // Streak badge
  const streakBadge = document.getElementById('fitness-streak-badge');
  if (streakBadge) {
    const streak = consistency.current_streak || 0;
    if (streak > 0) { streakBadge.textContent = `🔥${streak}`; streakBadge.style.display = 'inline-block'; }
    else streakBadge.style.display = 'none';
  }

  // ── Calorie deficit banner ──
  // Use TODAY's burned calories only (not the whole week)
  const burnedCal    = stats.today?.calories || 0;
  const eatenCal     = foodDay?.summary?.totals?.calories || 0;
  // null, not 2000: calc_tdee can't compute a target without weight/height/
  // age/gender, and inventing one meant a brand-new user got a red "over
  // budget" bar for exceeding a number the app made up about them.
  const targetCal    = profile?.targets?.target_calories || null;

  const netEl    = document.getElementById('cdb-net');
  const netLbl   = document.getElementById('cdb-net-label');
  const progress = document.getElementById('cdb-progress');
  const banner   = document.getElementById('calorie-deficit-banner');

  setText('cdb-burned', burnedCal.toLocaleString() + ' kcal');
  setText('cdb-eaten',  Math.round(eatenCal) + ' kcal');

  if (!targetCal) {
    // Eaten and burned are true without a target. Net, target and the progress
    // bar are not — so say they're missing and point at how to get them.
    setText('cdb-target', 'Not set');
    setText('cdb-progress-pct', '—');
    if (netEl)  netEl.textContent = '—';
    if (netLbl) netLbl.textContent = 'Add your details for a target';
    if (progress) { progress.style.width = '0%'; progress.classList.remove('over'); }
    if (banner) banner.classList.remove('cdb-deficit','cdb-surplus','cdb-balanced');
  } else {
    // Net = TDEE target - (eaten - burned): how many kcal you still have left today
    // A positive number means you still have room; negative means surplus over goal
    const net = Math.round((targetCal + burnedCal) - eatenCal);
    const pct = Math.min(Math.round((eatenCal / (targetCal + burnedCal)) * 100), 150);
    setText('cdb-target', targetCal + ' kcal/day');
    setText('cdb-progress-pct', pct + '%');
    if (netEl)  netEl.textContent = Math.abs(net) + ' kcal';
    if (netLbl) netLbl.textContent = net > 100 ? '✅ Remaining' : net < -100 ? '⚠️ Over budget' : '⚖️ Balanced';
    if (progress) {
      progress.style.width = Math.min(pct, 100) + '%';
      progress.classList.toggle('over', pct > 105);
    }
    if (banner) {
      banner.classList.remove('cdb-deficit','cdb-surplus','cdb-balanced');
      banner.classList.add(net > 100 ? 'cdb-deficit' : net < -100 ? 'cdb-surplus' : 'cdb-balanced');
    }
  }

  // ── Nutrition strip ──
  renderFitnessNutritionStrip(foodDay, profile?.targets);

  // ── Personal Records ──
  loadFitnessPRs();
}

function renderFitnessNutritionStrip(foodDay, targets) {
  if (!targets) return;
  // Same rule as the food page: without a real TDEE these "targets" are just
  // population averages presented as the user's own goals.
  const known = hasTargets(targets);
  const t    = foodDay?.summary?.totals || {};
  const defs = [
    { id:'cal',  val: Math.round(t.calories||0), target: targets.target_calories, unit:'kcal', label:'Calories', color:'#4F8D74' },
    { id:'prot', val: Math.round(t.protein||0),  target: targets.protein_g,       unit:'g',    label:'Protein',  color:'#5E8299' },
    { id:'carb', val: Math.round(t.carbs||0),    target: targets.carbs_g,         unit:'g',    label:'Carbs',    color:'#E0A34E' },
    { id:'fat',  val: Math.round(t.fat||0),      target: targets.fat_g,           unit:'g',    label:'Fat',      color:'#D07D4E' },
    { id:'fiber',val: Math.round(t.fiber||0),    target: targets.fiber_g,         unit:'g',    label:'Fiber',    color:'#5A9E70' },
  ];
  const R = 18, C = 2 * Math.PI * R; // circumference ~113

  defs.forEach(d => {
    const pct    = (known && d.target) ? Math.min(d.val / d.target, 1) : 0;
    const offset = C - pct * C;
    const ring   = document.getElementById(`fns-ring-${d.id}`);
    const valEl  = document.getElementById(`fns-${d.id}-val`);
    const subEl  = document.getElementById(`fns-${d.id}-sub`);
    if (ring)  ring.style.strokeDashoffset = offset.toFixed(1);
    if (valEl) valEl.textContent = d.id === 'cal' ? d.val : d.val + d.unit;
    // No denominator when we don't have one — an unfilled ring beats a ring
    // measured against an invented goal.
    if (subEl) subEl.textContent = (known && d.target)
      ? `/ ${d.target}${d.id !== 'cal' ? d.unit : ''}` : d.label;
  });

  // Nutrition suggestions in strip
  const sugEl = document.getElementById('fns-suggestions');
  if (sugEl) {
    const sugs = foodDay?.suggestions || [];
    if (sugs.length === 0) {
      sugEl.innerHTML = '<div style="color:var(--gray-400);font-size:12.5px">Log food to see nutrition insights integrated with your workouts.</div>';
    } else {
      sugEl.innerHTML = sugs.slice(0, 3).map(s => `
        <div class="fns-sug-row fns-sug-row--${s.type}">
          <span class="fns-sug-icon">${s.icon}</span>
          <span>${escHtml(s.text)}</span>
        </div>`).join('');
    }
  }
}

function renderTypeChart(types) {
  const el = document.getElementById('activity-type-chart');
  if (!el) return;
  const entries = Object.entries(types).sort((a,b) => b[1]-a[1]);
  if (entries.length === 0) { el.innerHTML = '<div style="color:var(--gray-400);font-size:13px">No activities logged yet</div>'; return; }
  const max = entries[0][1];
  const colors = { running:'#4F8D74', cycling:'#5E8299', walking:'#E0A34E', swimming:'#D07D4E', yoga:'#5A9E70', gym:'#DC2626', hiking:'#B9803A', stretching:'#059669', tennis:'#C15646', pickleball:'#C15646', basketball:'#EA580C', football:'#5A9E70', badminton:'#C15646', volleyball:'#EA580C', baseball:'#5E8299', cricket:'#5A9E70', golf:'#5A9E70', boxing:'#DC2626', martial_arts:'#DC2626', dancing:'#D07D4E', rowing:'#5E8299', climbing:'#B9803A', skiing:'#5E8299', snowboarding:'#5E8299', skating:'#5E8299', cycling_indoor:'#5E8299', pilates:'#D07D4E', crossfit:'#DC2626', other:'#9CA3AF' };
  const actIcons = { running:'🏃', cycling:'🚴', walking:'🚶', swimming:'🏊', yoga:'🧘', gym:'🏋️', hiking:'⛰️', stretching:'🤸', tennis:'🎾', pickleball:'🏓', basketball:'🏀', football:'⚽', badminton:'🏸', volleyball:'🏐', baseball:'⚾', cricket:'🏏', golf:'⛳', boxing:'🥊', martial_arts:'🥋', dancing:'💃', rowing:'🚣', climbing:'🧗', skiing:'⛷️', snowboarding:'🏂', skating:'⛸️', cycling_indoor:'🚲', pilates:'🤸', crossfit:'💪', other:'🏅' };
  el.innerHTML = entries.map(([type, count]) => `
    <div class="type-row">
      <div class="type-label">${actIcons[type]||'🏅'} ${type}</div>
      <div class="type-bar-track"><div class="type-bar-fill" style="width:${(count/max*100).toFixed(0)}%;background:${colors[type]||'var(--teal-500)'}"></div></div>
      <div class="type-count-label">${count}</div>
    </div>
  `).join('');
}

function renderActivityFeed(activities) {
  const el = document.getElementById('activity-feed');
  if (!el) return;
  if (activities.length === 0) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🏅</div><div class="empty-text">No activities yet</div><div class="empty-sub">Log a workout or connect a fitness app</div><button class="btn-primary" data-ev-click="openActivityModal()">Log Activity</button></div>`;
    return;
  }
  const actColors = { running:'#ECF3EF', cycling:'#EDF2F5', walking:'#FFFBEB', swimming:'#F9EBE0', yoga:'#F0FDF4', gym:'#FFF0EF', hiking:'#FEF3C7', stretching:'#ECFDF5', tennis:'#FFF0F0', pickleball:'#FFF0F0', basketball:'#FFF3E0', football:'#F0FDF4', badminton:'#FFF0F0', volleyball:'#FFF3E0', baseball:'#F0F4FF', cricket:'#F0FDF4', golf:'#F0FDF4', boxing:'#FFF0EF', martial_arts:'#FFF0EF', dancing:'#FDF0FF', rowing:'#EDF2F5', climbing:'#FEF3C7', skiing:'#EDF2F5', snowboarding:'#EDF2F5', skating:'#EDF2F5', cycling_indoor:'#EDF2F5', pilates:'#F9EBE0', crossfit:'#FFF0EF', other:'#F3F4F6' };
  const actIcons = { running:'🏃', cycling:'🚴', walking:'🚶', swimming:'🏊', yoga:'🧘', gym:'🏋️', hiking:'⛰️', stretching:'🤸', tennis:'🎾', pickleball:'🏓', basketball:'🏀', football:'⚽', badminton:'🏸', volleyball:'🏐', baseball:'⚾', cricket:'🏏', golf:'⛳', boxing:'🥊', martial_arts:'🥋', dancing:'💃', rowing:'🚣', climbing:'🧗', skiing:'⛷️', snowboarding:'🏂', skating:'⛸️', cycling_indoor:'🚲', pilates:'🤸', crossfit:'💪', other:'🏅' };
  el.innerHTML = activities.slice(0,20).map(a => `
    <div class="activity-item">
      <div class="act-type-icon" style="background:${actColors[a.type]||'var(--gray-50)'};">${actIcons[a.type]||'🏅'}</div>
      <div class="act-info">
        <div class="act-name">${escHtml(a.name || a.type)}</div>
        <div class="act-meta">
          <span>${a.date}</span>
          ${a.source !== 'manual' ? `<span class="act-source-badge">${a.source}</span>` : ''}
        </div>
      </div>
      <div class="act-stats">
        ${a.duration ? `<div class="act-stat"><div class="act-stat-val">${a.duration}m</div><div class="act-stat-label">duration</div></div>` : ''}
        ${a.calories ? `<div class="act-stat"><div class="act-stat-val">${a.calories}</div><div class="act-stat-label">kcal</div></div>` : ''}
        ${a.distance ? `<div class="act-stat"><div class="act-stat-val">${a.distance}km</div><div class="act-stat-label">distance</div></div>` : ''}
        ${a.heart_rate_avg ? `<div class="act-stat"><div class="act-stat-val">${a.heart_rate_avg}</div><div class="act-stat-label">bpm avg</div></div>` : ''}
      </div>
      <button class="btn-icon act-delete" data-ev-click="deleteActivity('${a.id}')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
      </button>
    </div>
  `).join('');
}

// ─────────────────────────────────────────────────────────────
// DYNAMIC ACTIVITY FORM
// ─────────────────────────────────────────────────────────────

let gymSubTypes  = new Set(['cardio']);   // multi-select — any combo allowed
let gymSets      = {};  // keyed by subId e.g. { upper_body:[...], lower_body:[...] }

// Field schema: maps activity type → which field groups to show
// Each group: { id, label, fields: [{name, label, placeholder, type, step?}] }
const ACTIVITY_FIELD_SCHEMA = {
  // ── Cardio / distance ──
  _distance: {
    label: 'Distance & Pace',
    fields: [
      { name:'duration',  label:'Duration (min)', placeholder:'30',   type:'number', min:'1' },
      { name:'distance',  label:'Distance (km)',  placeholder:'5.0',  type:'number', step:'0.1' },
    ]
  },
  _metrics: {
    label: 'Performance',
    fields: [
      { name:'calories',       label:'Calories',       placeholder:'300', type:'number' },
      { name:'heart_rate_avg', label:'Avg Heart Rate',  placeholder:'145', type:'number' },
    ]
  },
  _steps: {
    label: 'Steps & Elevation',
    fields: [
      { name:'steps',     label:'Steps',          placeholder:'8000', type:'number' },
      { name:'elevation', label:'Elevation (m)',   placeholder:'50',   type:'number' },
    ]
  },
  _duration_only: {
    label: 'Duration',
    fields: [
      { name:'duration',       label:'Duration (min)', placeholder:'45', type:'number', min:'1' },
      { name:'calories',       label:'Calories',       placeholder:'250', type:'number' },
    ]
  },
  _hr_only: {
    label: 'Performance',
    fields: [
      { name:'heart_rate_avg', label:'Avg Heart Rate', placeholder:'130', type:'number' },
    ]
  },
  _sport_sets: {
    label: 'Match Details',
    fields: [
      { name:'duration',  label:'Duration (min)', placeholder:'60', type:'number' },
      { name:'calories',  label:'Calories',       placeholder:'400', type:'number' },
      { name:'heart_rate_avg', label:'Avg Heart Rate', placeholder:'140', type:'number' },
    ]
  },
  _swim: {
    label: 'Swim Details',
    fields: [
      { name:'duration',  label:'Duration (min)', placeholder:'40', type:'number' },
      { name:'distance',  label:'Distance (km)',  placeholder:'1.5', type:'number', step:'0.1' },
      { name:'calories',  label:'Calories',       placeholder:'350', type:'number' },
    ]
  },
  _outdoor: {
    label: 'Outdoor Details',
    fields: [
      { name:'duration',  label:'Duration (min)', placeholder:'90',  type:'number' },
      { name:'distance',  label:'Distance (km)',  placeholder:'8.0', type:'number', step:'0.1' },
      { name:'elevation', label:'Elevation (m)',  placeholder:'200', type:'number' },
      { name:'calories',  label:'Calories',       placeholder:'600', type:'number' },
    ]
  },
  _mindful: {
    label: 'Session Details',
    fields: [
      { name:'duration', label:'Duration (min)', placeholder:'45', type:'number' },
      { name:'calories', label:'Calories (est)', placeholder:'150', type:'number' },
    ]
  },
  _cycling: {
    label: 'Ride Details',
    fields: [
      { name:'duration',       label:'Duration (min)', placeholder:'60',  type:'number' },
      { name:'distance',       label:'Distance (km)',  placeholder:'25.0', type:'number', step:'0.1' },
      { name:'elevation',      label:'Elevation (m)',  placeholder:'150', type:'number' },
      { name:'calories',       label:'Calories',       placeholder:'500', type:'number' },
      { name:'heart_rate_avg', label:'Avg Heart Rate', placeholder:'140', type:'number' },
    ]
  },
  _golf: {
    label: 'Golf Details',
    fields: [
      { name:'duration',  label:'Duration (min)', placeholder:'180', type:'number' },
      { name:'distance',  label:'Distance walked (km)', placeholder:'6.0', type:'number', step:'0.1' },
      { name:'calories',  label:'Calories',       placeholder:'350', type:'number' },
    ]
  },
};

// Map activity type → which schema groups to render
const TYPE_FIELDS = {
  running:       ['_distance', '_metrics', '_steps'],
  walking:       ['_distance', '_steps', '_hr_only'],
  cycling:       ['_cycling'],
  cycling_indoor:['_cycling'],
  swimming:      ['_swim'],
  rowing:        ['_duration_only', '_metrics'],
  crossfit:      ['_duration_only', '_metrics'],
  hiking:        ['_outdoor'],
  climbing:      ['_duration_only', '_metrics'],
  skiing:        ['_outdoor'],
  snowboarding:  ['_outdoor'],
  skating:       ['_duration_only', '_metrics'],
  tennis:        ['_sport_sets'],
  pickleball:    ['_sport_sets'],
  badminton:     ['_sport_sets'],
  football:      ['_sport_sets'],
  basketball:    ['_sport_sets'],
  volleyball:    ['_sport_sets'],
  baseball:      ['_sport_sets'],
  cricket:       ['_sport_sets'],
  golf:          ['_golf'],
  boxing:        ['_duration_only', '_metrics'],
  martial_arts:  ['_duration_only', '_metrics'],
  dancing:       ['_mindful'],
  yoga:          ['_mindful'],
  pilates:       ['_mindful'],
  stretching:    ['_mindful'],
  gym:           ['_gym'],   // special: uses gym sub-type renderer
  other:         ['_duration_only', '_metrics'],
};

function renderActivityFields(type) {
  const container = document.getElementById('activity-dynamic-fields');
  if (!container) return;

  // Gym gets its own special renderer
  if (type === 'gym') {
    renderGymFields(container);
    return;
  }

  const groups = TYPE_FIELDS[type] || ['_duration_only', '_metrics'];
  let html = '';

  groups.forEach(groupKey => {
    const schema = ACTIVITY_FIELD_SCHEMA[groupKey];
    if (!schema) return;
    // Pair fields into rows of 2
    const fields = schema.fields;
    const rows   = [];
    for (let i = 0; i < fields.length; i += 2) rows.push(fields.slice(i, i+2));
    html += `<div class="act-field-section">
      <div class="act-field-divider">
        <div class="act-field-divider-label">${schema.label}</div>
        <div class="act-field-divider-line"></div>
      </div>`;
    rows.forEach(row => {
      html += `<div class="form-row" style="margin-bottom:14px">`;
      row.forEach(f => {
        const extra = [
          f.min  ? `min="${f.min}"`   : '',
          f.step ? `step="${f.step}"` : ''
        ].filter(Boolean).join(' ');
        html += `<div class="form-group">
          <label class="form-label">${f.label}</label>
          <input type="${f.type}" class="form-input" name="${f.name}" placeholder="${f.placeholder}" ${extra}>
        </div>`;
      });
      // If odd field, pad with empty div
      if (row.length === 1) html += `<div class="form-group"></div>`;
      html += `</div>`;
    });
    html += `</div>`;
  });

  container.innerHTML = html;
}

// GYM SUB-TYPE CONFIG
const GYM_SUBS = [
  { id:'cardio',      label:'🫀 Cardio',      color:'#4F8D74' },
  { id:'hiit',        label:'⚡ HIIT',         color:'#EA580C' },
  { id:'upper_body',  label:'💪 Upper Body',   color:'#5E8299' },
  { id:'lower_body',  label:'🦵 Lower Body',   color:'#D07D4E' },
  { id:'full_body',   label:'🏋️ Full Body',   color:'#DC2626' },
  { id:'core',        label:'🔥 Core',         color:'#E0A34E' },
  { id:'flexibility', label:'🧘 Flexibility',  color:'#5A9E70' },
];

// Which sub-types need a strength sets/reps table
const STRENGTH_TYPES = new Set(['upper_body','lower_body','full_body','core']);

// Per sub-type metric fields (shown below the section header)
const GYM_SUB_FIELDS = {
  cardio:      [{ name:'cardio_duration', label:'Duration (min)', ph:'30', type:'number' },
                { name:'cardio_calories', label:'Calories',       ph:'250',type:'number' },
                { name:'cardio_hr',       label:'Avg Heart Rate', ph:'130',type:'number' }],
  hiit:        [{ name:'hiit_duration',   label:'Duration (min)', ph:'25', type:'number' },
                { name:'hiit_rounds',     label:'Rounds',         ph:'5',  type:'number' },
                { name:'hiit_calories',   label:'Calories',       ph:'350',type:'number' },
                { name:'hiit_hr',         label:'Avg Heart Rate', ph:'165',type:'number' }],
  upper_body:  null,   // → sets/reps table
  lower_body:  null,
  full_body:   null,
  core:        null,
  flexibility: [{ name:'flex_duration',  label:'Duration (min)', ph:'20', type:'number' }],
};

function renderGymFields(container) {
  if (!container) return;

  // ── Section 1: multi-select type badges ──
  const badgesHtml = GYM_SUBS.map(s => {
    const active = gymSubTypes.has(s.id);
    return `<button type="button"
      class="gym-sub-btn ${active ? 'selected' : ''}"
      data-sub="${s.id}"
      data-ev-click="toggleGymSub('${s.id}')"
      style="${active ? `background:${s.color};border-color:${s.color}` : ''}"
    >${s.label}</button>`;
  }).join('');

  // ── Section 2: one block per selected sub-type ──
  let sectionsHtml = '';
  let hasAnyStrength = false;

  // Sort selected to maintain consistent order
  const ordered = GYM_SUBS.filter(s => gymSubTypes.has(s.id));

  if (ordered.length === 0) {
    sectionsHtml = `<div class="gym-empty-hint">Select at least one workout type above</div>`;
  }

  // Shared duration/calories (always shown once at top of details)
  const showShared = ordered.length > 0;

  ordered.forEach(sub => {
    const fields = GYM_SUB_FIELDS[sub.id];
    const isStrength = STRENGTH_TYPES.has(sub.id);
    if (isStrength) hasAnyStrength = true;

    let innerHtml = '';
    if (isStrength) {
      innerHtml = renderSetsTable(sub.id);
    } else if (fields) {
      // Pair into rows of 2
      for (let i = 0; i < fields.length; i += 2) {
        const pair = fields.slice(i, i+2);
        innerHtml += `<div class="form-row" style="margin-bottom:12px">`;
        pair.forEach(f => {
          innerHtml += `<div class="form-group">
            <label class="form-label">${f.label}</label>
            <input type="${f.type}" class="form-input" name="${f.name}" placeholder="${f.ph}">
          </div>`;
        });
        if (pair.length === 1) innerHtml += `<div class="form-group"></div>`;
        innerHtml += `</div>`;
      }
    }

    sectionsHtml += `
      <div class="gym-section-block" data-sub="${sub.id}">
        <div class="gym-section-header" style="border-left-color:${sub.color}">
          <span>${sub.label}</span>
        </div>
        ${innerHtml}
      </div>`;
  });

  // ── Shared overall metrics (shown once regardless of combo) ──
  const sharedHtml = showShared ? `
    <div class="act-field-divider" style="margin-top:4px">
      <div class="act-field-divider-label">Overall Session</div>
      <div class="act-field-divider-line"></div>
    </div>
    <div class="form-row" style="margin-bottom:12px">
      <div class="form-group">
        <label class="form-label">Total Duration (min)</label>
        <input type="number" class="form-input" name="duration" placeholder="60">
      </div>
      <div class="form-group">
        <label class="form-label">Total Calories (est)</label>
        <input type="number" class="form-input" name="calories" placeholder="400">
      </div>
    </div>
    <div class="form-row" style="margin-bottom:12px">
      <div class="form-group">
        <label class="form-label">Avg Heart Rate</label>
        <input type="number" class="form-input" name="heart_rate_avg" placeholder="130">
      </div>
      <div class="form-group">
        <label class="form-label">Max Heart Rate</label>
        <input type="number" class="form-input" name="heart_rate_max" placeholder="165">
      </div>
    </div>` : '';

  container.innerHTML = `
    <div class="act-field-section">
      <div class="act-field-divider">
        <div class="act-field-divider-label">Workout Type <span style="font-size:9px;color:var(--gray-400);text-transform:none;letter-spacing:0;font-weight:400"> — select all that apply</span></div>
        <div class="act-field-divider-line"></div>
      </div>
      <div class="gym-subtype-picker" style="margin-bottom:14px">${badgesHtml}</div>
      ${sectionsHtml}
      ${sharedHtml}
    </div>`;
}

function toggleGymSub(sub) {
  if (gymSubTypes.has(sub)) {
    // Don't deselect last one
    if (gymSubTypes.size > 1) gymSubTypes.delete(sub);
  } else {
    gymSubTypes.add(sub);
  }
  // Re-render preserving existing input values
  const container = document.getElementById('activity-dynamic-fields');
  renderGymFields(container);
}

// gymSets is keyed by subId: { upper_body: [...], lower_body: [...], ... }
// Initialised lazily so any combo works
function getSubSets(subId) {
  if (!gymSets[subId]) gymSets[subId] = [{ exercise:'', sets:'', reps:'', weight:'' }];
  return gymSets[subId];
}

function renderSetsTable(subId) {
  const sets = getSubSets(subId);
  const rows = sets.map((s, i) => `
    <tr>
      <td><input type="text"   class="form-input" style="font-size:12px;padding:5px 8px"
                 placeholder="e.g. Bench Press"
                 data-ev-input="setGymField('${subId}',${i},'exercise',this.value)"
                 value="${escHtml(s.exercise)}"></td>
      <td><input type="number" class="form-input" style="font-size:12px;padding:5px 8px;width:54px"
                 placeholder="3"
                 data-ev-input="setGymField('${subId}',${i},'sets',this.value)"
                 value="${s.sets}"></td>
      <td><input type="number" class="form-input" style="font-size:12px;padding:5px 8px;width:54px"
                 placeholder="10"
                 data-ev-input="setGymField('${subId}',${i},'reps',this.value)"
                 value="${s.reps}"></td>
      <td><input type="number" class="form-input" style="font-size:12px;padding:5px 8px;width:68px"
                 placeholder="—" step="0.5"
                 data-ev-input="setGymField('${subId}',${i},'weight',this.value)"
                 value="${s.weight}"></td>
      <td><button type="button" class="btn-icon"
          data-ev-click="removeGymSet('${subId}',${i})"
          style="width:24px;height:24px;color:var(--gray-300)">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg></button></td>
    </tr>`).join('');

  return `<div style="margin-bottom:12px;overflow-x:auto">
    <table class="sets-table">
      <thead><tr>
        <th style="width:42%">Exercise</th>
        <th>Sets</th><th>Reps</th><th>Weight</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <button type="button" class="sets-add-btn" data-ev-click="addGymSet('${subId}')">+ Add exercise</button>
  </div>`;
}

function addGymSet(subId) {
  getSubSets(subId).push({ exercise:'', sets:'', reps:'', weight:'' });
  renderGymFields(document.getElementById('activity-dynamic-fields'));
}

function removeGymSet(subId, i) {
  const sets = getSubSets(subId);
  if (sets.length > 1) {
    sets.splice(i, 1);
    renderGymFields(document.getElementById('activity-dynamic-fields'));
  }
}

function setupActivityTypePicker() {
  document.querySelectorAll('.act-type-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.act-type-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedActivityType = btn.dataset.type;
      // Reset gym state when switching away from gym
      if (btn.dataset.type !== 'gym') gymSubType = 'cardio';
      // Reset gym sets when switching to gym fresh
      if (btn.dataset.type === 'gym') { gymSubTypes = new Set(['cardio']); gymSets = {}; }
      // Update name placeholder to match activity
      const nameInput = document.getElementById('act-name');
      if (nameInput) {
        const placeholders = {
          running:'Morning Run', cycling:'Evening Ride', walking:'Afternoon Walk',
          swimming:'Lap Swimming', hiking:'Trail Hike', gym:'Gym Session',
          yoga:'Yoga Flow', tennis:'Tennis Match', pickleball:'Pickleball Game',
          basketball:'Basketball Game', football:'Football Match', cycling_indoor:'Spin Class',
          crossfit:'CrossFit WOD', boxing:'Boxing Session', skiing:'Ski Run',
          golf:'Golf Round', other:'Workout'
        };
        nameInput.placeholder = placeholders[btn.dataset.type] || 'Activity';
      }
      renderActivityFields(btn.dataset.type);
    });
  });
}

function setupActivityForm() {
  document.getElementById('activity-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;

    // Collect gym sets as a JSON string stored in notes if applicable
    let gymSetsNote = '';
    if (selectedActivityType === 'gym') {
      // Serialise multi-type gym session
      const typeLabels = { upper_body:'Upper Body', lower_body:'Lower Body',
        full_body:'Full Body', core:'Core', cardio:'Cardio', hiit:'HIIT', flexibility:'Flexibility' };
      const parts = [];
      gymSubTypes.forEach(subId => {
        if (gymSets[subId] && gymSets[subId].some(s => s.exercise)) {
          const exParts = gymSets[subId].filter(s => s.exercise)
            .map(s => `${s.exercise}${s.sets?` ${s.sets}×${s.reps||'?'}`:''} ${s.weight?`@ ${s.weight}kg`:''}`.trim());
          parts.push(`[${typeLabels[subId]||subId}] ${exParts.join(', ')}`);
        } else {
          parts.push(`[${typeLabels[subId]||subId}]`);
        }
      });
      gymSetsNote = parts.join(' | ');
    }

    const body = {
      type: selectedActivityType,
      name: form.name?.value || selectedActivityType,
      date: form.date.value,
      duration:       parseInt(form.duration?.value)       || 0,
      distance:       parseFloat(form.distance?.value)     || 0,
      calories:       parseInt(form.calories?.value)       || 0,
      heart_rate_avg: parseInt(form.heart_rate_avg?.value) || 0,
      heart_rate_max: parseInt(form.heart_rate_max?.value) || 0,
      steps:          parseInt(form.steps?.value)          || 0,
      elevation:      parseFloat(form.elevation?.value)    || 0,
      notes:          gymSetsNote || form.notes?.value || '',
      source: 'manual',
      // Store gym sub-type in name if gym
      ...(selectedActivityType === 'gym' && !form.name?.value && {
        name: [...gymSubTypes].map(s=>s.replace('_',' ').replace(/\b\w/g,c=>c.toUpperCase())).join(' + ') + ' Workout'
      })
    };
    const res = await fetch('/api/fitness/activities', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    const data = await res.json();
    if (data.success) {
      showToast('Activity logged!', 'success');
      form.reset(); setDates();
      document.querySelectorAll('.act-type-btn').forEach(b => b.classList.remove('selected'));
      document.querySelector('.act-type-btn[data-type="running"]')?.classList.add('selected');
      selectedActivityType = 'running';
      gymSubTypes = new Set(['cardio']);
      gymSets = {};
      renderActivityFields('running');
      closeModal('activity-modal-overlay');
      loadFitness();
      loadDashboard();
      // Invalidate consistency cache
      calData = {};
      allHistoryActivities = [];
      // If consistency view is open, reload it fully; otherwise prefetch silently
      if (document.getElementById('view-consistency')?.classList.contains('active')) {
        loadConsistency();
      } else {
        // Prefetch in background so it's ready when user switches
        Promise.all([
          fetch('/api/fitness/calendar').then(r => r.json()),
          fetch('/api/fitness/activities').then(r => r.json())
        ]).then(([cal, acts]) => {
          calData = cal;
          allHistoryActivities = acts;
        }).catch(() => {});
      }
    } else showToast('Failed to log activity', 'error');
  });
}

async function connectService(service) {
  closeModal('connect-modal-overlay');
  showToast(`Connecting to ${service}…`);
  const res = await fetch('/api/fitness/connect', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ service }) });
  const data = await res.json();
  if (data.success) {
    showToast(`✓ Imported ${data.imported} activities from ${service}`, 'success');
    // Mark as connected
    const row = document.querySelector(`.app-connect-row[data-service="${service}"] .btn-connect`);
    if (row) { row.textContent = 'Connected ✓'; row.classList.add('connected'); }
    loadFitness();
    loadDashboard();
  } else showToast('Connection failed', 'error');
}

function deleteActivity(id) {
  undoable('Deleting activity…', async () => {
    await fetch(`/api/fitness/activities/${id}`, { method:'DELETE' });
    loadFitness();
    loadDashboard();
  });
}

// ── Filters ──
function setupFilters() {
  let timer;
  ['search-input','severity-filter','tag-filter'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(loadReports, 250); }); el.addEventListener('change', loadReports); }
  });
}

// ── Modals ──
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.style.display = 'none'; });
});

// ── Utils ──
function setText(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
function fileIcon(ext) { return { pdf:'📄', png:'🖼️', jpg:'🖼️', jpeg:'🖼️', txt:'📝', csv:'📊' }[(ext||'').toLowerCase()] || '📄'; }
function escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;'); }
function fmtBytes(b) { if (b<1024) return b+' B'; if (b<1048576) return (b/1024).toFixed(1)+' KB'; return (b/1048576).toFixed(1)+' MB'; }
function freqLabel(f) { return { once_daily:'Once daily', twice_daily:'Twice daily', thrice_daily:'3× daily', weekly:'Weekly' }[f] || f; }
function downloadFile(url, name) { const a = document.createElement('a'); a.href = url; a.download = name; a.click(); }
let toastTimer;
function showToast(msg, type='') { const el = document.getElementById('toast'); el.textContent = msg; el.className = `toast ${type}`; el.style.display = 'block'; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.style.display = 'none', 3200); }

// ── Real OAuth connect ──────────────────────────────────────────────────────

const OAUTH_URLS = {
  strava:     '/oauth/strava/start',
  garmin:     '/oauth/garmin/start',
  google_fit: '/oauth/google/start'
};

const SERVICE_LABELS = {
  strava: 'Strava', garmin: 'Garmin Connect',
  apple_health: 'Apple Health', google_fit: 'Google Fit'
};

async function loadConnectedServices() {
  const [status, tokens, syncLog] = await Promise.all([
    fetch('/api/fitness/service-status').then(r => r.json()).catch(() => ({})),
    fetch('/api/fitness/connected').then(r => r.json()).catch(() => []),
    fetch('/api/fitness/sync-log').then(r => r.json()).catch(() => [])
  ]);

  // Update sidebar connect rows
  document.querySelectorAll('.app-connect-row').forEach(row => {
    const svc = row.dataset.service;
    const btn = row.querySelector('.btn-connect');
    const info = row.querySelector('.app-desc');
    if (!btn) return;
    const svcStatus = status[svc] || {};
    if (svcStatus.connected) {
      btn.textContent = '✓ Connected';
      btn.classList.add('connected');
      btn.onclick = null;
      if (info && svcStatus.last_sync)
        info.textContent = `Last sync: ${new Date(svcStatus.last_sync).toLocaleDateString()}`;
    } else {
      btn.textContent = svcStatus.configured ? 'Connect' : 'Setup needed';
      btn.classList.remove('connected');
      btn.style.opacity = svcStatus.configured ? '1' : '0.6';
      btn.onclick = () => connectService(svc);
    }
  });

  // Update connect modal cards
  Object.entries(status).forEach(([svc, s]) => {
    const card = document.getElementById(`connect-card-${svc}`);
    if (!card) return;
    const cardBtn = card.querySelector('.connect-card-btn');
    if (s.connected) {
      card.classList.add('connected');
      if (cardBtn) {
        cardBtn.textContent = `✓ Connected${s.athlete_name ? ' — ' + s.athlete_name : ''}`;
        cardBtn.style.background = 'var(--green-600)';
      }
    } else if (!s.configured && svc !== 'apple_health') {
      if (cardBtn) {
        cardBtn.textContent = '⚙ Add credentials to .env first';
        cardBtn.style.background = 'var(--gray-400)';
        cardBtn.style.cursor = 'default';
      }
    }
  });

  renderConnectedPanel(tokens, syncLog);
}

function renderConnectedPanel(tokens, syncLog) {
  const el = document.getElementById('connected-services-panel');
  if (!el) return;

  if (tokens.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:8px 0">No apps connected yet. Click Connect to link a fitness app.</div>';
    return;
  }

  el.innerHTML = tokens.map(t => {
    const recentSync = syncLog.find(s => s.service === t.service);
    const statusColor = recentSync?.status === 'error' ? 'var(--red-500)' : 'var(--green-500)';
    const syncLabel = t.last_sync ? new Date(t.last_sync).toLocaleString() : 'Never';
    return `
      <div class="connected-service-row">
        <div class="cs-dot" style="background:${statusColor}"></div>
        <div class="cs-info">
          <div class="cs-name">${SERVICE_LABELS[t.service] || t.service}</div>
          <div class="cs-meta">${t.athlete_name ? escHtml(t.athlete_name) + ' · ' : ''}Last sync: ${syncLabel}</div>
        </div>
        <div class="cs-actions">
          <button class="btn-outline-sm" data-ev-click="triggerSync('${t.service}')">Sync now</button>
          <button class="btn-icon" data-ev-click="disconnectService('${t.service}')" title="Disconnect" style="color:var(--red-400)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

async function triggerSync(service) {
  showToast(`Syncing ${SERVICE_LABELS[service] || service}…`);
  try {
    const res = await fetch('/api/fitness/sync', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ service })
    });
    const data = await res.json();
    if (data.success) {
      const r = data.results[service];
      showToast(`✓ ${SERVICE_LABELS[service]}: ${r.count ?? 0} new activities`, 'success');
      loadFitness();
      loadDashboard();
      loadConnectedServices();
    } else {
      showToast(data.error || 'Sync failed', 'error');
    }
  } catch(e) {
    showToast('Sync error: ' + e.message, 'error');
  }
}

function disconnectService(service) {
  undoable(`Disconnecting ${SERVICE_LABELS[service] || service} (imported activities stay)…`, async () => {
    await fetch('/api/fitness/disconnect', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ service })
    });
    loadConnectedServices();
  });
}

// Real OAuth connect — redirects to backend OAuth start route
connectService = function(service) {
  closeModal('connect-modal-overlay');

  if (service === 'apple_health') {
    openAppleHealthModal();
    return;
  }

  const url = OAUTH_URLS[service];
  if (!url) { showToast('Service not supported yet', 'error'); return; }

  // Show connecting state on button
  const btn = document.querySelector(`.app-connect-row[data-service="${service}"] .btn-connect`);
  if (btn) { btn.textContent = 'Connecting…'; btn.disabled = true; }

  // Open OAuth in a popup window (keeps user in the app)
  const popup = window.open(
    url,
    `${service}_oauth`,
    'width=620,height=720,scrollbars=yes,resizable=yes,toolbar=no,menubar=no'
  );

  if (!popup) {
    // Popups blocked — redirect the whole page instead
    showToast('Redirecting to ' + (SERVICE_LABELS[service] || service) + '…');
    sessionStorage.setItem('oauth_return', 'fitness');
    window.location.href = url;
    return;
  }

  // Poll every 500ms until popup closes
  const pollTimer = setInterval(async () => {
    try {
      // Check if popup navigated back to our domain (means OAuth complete)
      if (popup.closed) {
        clearInterval(pollTimer);
        showToast('Checking connection…');
        await new Promise(r => setTimeout(r, 800));
        await loadConnectedServices();
        await loadFitness();
        await loadDashboard();
        // Check if actually connected
        const tokens = await fetch('/api/fitness/connected').then(r => r.json()).catch(() => []);
        const connected = tokens.find(t => t.service === service);
        if (connected) {
          showToast(`✓ ${SERVICE_LABELS[service]} connected!`, 'success');
        } else {
          showToast('Connection cancelled or failed', 'error');
          if (btn) { btn.textContent = 'Connect'; btn.disabled = false; }
        }
      }
    } catch(e) {
      // Cross-origin error means popup is on OAuth provider page — still in progress
    }
  }, 500);

  // Timeout after 5 minutes
  setTimeout(() => {
    clearInterval(pollTimer);
    if (!popup.closed) popup.close();
    if (btn) { btn.textContent = 'Connect'; btn.disabled = false; }
  }, 300000);
};

function openAppleHealthModal() {
  // Show Apple Health upload instructions
  const overlay = document.getElementById('apple-modal-overlay');
  if (overlay) overlay.style.display = 'flex';
}

// Apple Health XML upload
document.addEventListener('DOMContentLoaded', () => {
  const appleForm = document.getElementById('apple-health-form');
  if (appleForm) {
    appleForm.addEventListener('submit', async e => {
      e.preventDefault();
      const fileInput = document.getElementById('apple-health-file');
      if (!fileInput.files[0]) { showToast('Select a file first', 'error'); return; }
      const fd = new FormData();
      fd.append('file', fileInput.files[0]);
      const btn = appleForm.querySelector('button[type=submit]');
      btn.disabled = true; btn.textContent = 'Importing…';
      try {
        const res = await fetch('/api/fitness/apple/import', { method:'POST', body:fd });
        const data = await res.json();
        if (data.success) {
          showToast(`✓ Imported ${data.imported} of ${data.total} workouts`, 'success');
          closeModal('apple-modal-overlay');
          loadFitness(); loadDashboard();
        } else showToast(data.error || 'Import failed', 'error');
      } catch { showToast('Upload error', 'error'); }
      finally { btn.disabled = false; btn.textContent = 'Import'; }
    });
  }
  // Load connected services when fitness view loads
  const oldLoadFitness = loadFitness;
});

// Sync log display
async function showSyncLog() {
  const log = await fetch('/api/fitness/sync-log').then(r => r.json()).catch(() => []);
  const el = document.getElementById('sync-log-list');
  if (!el) return;
  if (log.length === 0) { el.innerHTML = '<div style="color:var(--gray-400);font-size:13px">No sync history yet</div>'; return; }
  el.innerHTML = log.slice(0,10).map(s => `
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--gray-100)">
      <div style="width:8px;height:8px;border-radius:50%;background:${s.status==='success'?'var(--green-500)':'var(--red-500)'};flex-shrink:0"></div>
      <div style="flex:1">
        <div style="font-size:13px;font-weight:500;color:var(--gray-700);text-transform:capitalize">${s.service.replace('_',' ')}</div>
        <div style="font-size:11.5px;color:var(--gray-400)">${new Date(s.synced_at).toLocaleString()} · ${s.count} activities · ${s.message}</div>
      </div>
    </div>
  `).join('');
}

// ════════════════════════════════════════════════════════════════
// CONSISTENCY VIEW
// ════════════════════════════════════════════════════════════════

let calYear  = new Date().getFullYear();  // reset on every loadConsistency
let calMonth = new Date().getMonth();     // 0-indexed, reset on every loadConsistency
let calData  = {};       // date -> activity info from API
let allHistoryActivities = [];
let historyPage = 0;
const HISTORY_PAGE_SIZE = 20;

const ACT_ICONS  = { running:'🏃', cycling:'🚴', walking:'🚶', swimming:'🏊', yoga:'🧘', gym:'🏋️', hiking:'⛰️', stretching:'🤸', tennis:'🎾', pickleball:'🏓', basketball:'🏀', football:'⚽', badminton:'🏸', volleyball:'🏐', baseball:'⚾', cricket:'🏏', golf:'⛳', boxing:'🥊', martial_arts:'🥋', dancing:'💃', rowing:'🚣', climbing:'🧗', skiing:'⛷️', snowboarding:'🏂', skating:'⛸️', cycling_indoor:'🚲', pilates:'🤸', crossfit:'💪', other:'🏅' };
const ACT_COLORS = { running:'#ECF3EF', cycling:'#EDF2F5', walking:'#FFFBEB', swimming:'#F9EBE0', yoga:'#F0FDF4', gym:'#FFF0EF', hiking:'#FEF3C7', stretching:'#ECFDF5', tennis:'#FFF0F0', pickleball:'#FFF0F0', basketball:'#FFF3E0', football:'#F0FDF4', badminton:'#FFF0F0', volleyball:'#FFF3E0', baseball:'#F0F4FF', cricket:'#F0FDF4', golf:'#F0FDF4', boxing:'#FFF0EF', martial_arts:'#FFF0EF', dancing:'#FDF0FF', rowing:'#EDF2F5', climbing:'#FEF3C7', skiing:'#EDF2F5', snowboarding:'#EDF2F5', skating:'#EDF2F5', cycling_indoor:'#EDF2F5', pilates:'#F9EBE0', crossfit:'#FFF0EF', other:'#F3F4F6' };

async function loadConsistency() {
  // ALWAYS reset to current month — do this synchronously before any async work
  calYear  = new Date().getFullYear();
  calMonth = new Date().getMonth();
  // Show current month label immediately while data loads
  const monthNames = ['January','February','March','April','May','June',
    'July','August','September','October','November','December'];
  setText('cal-month-label', `${monthNames[calMonth]} ${calYear}`);

  const [consistency, calendar, activities] = await Promise.all([
    fetch('/api/fitness/consistency').then(r => r.json()).catch(() => ({})),
    fetch('/api/fitness/calendar').then(r => r.json()).catch(() => ({})),
    fetch('/api/fitness/activities').then(r => r.json()).catch(() => [])
  ]);

  calData = calendar;
  allHistoryActivities = activities;
  historyPage = 0;

  // ── Streak + summary cards ──
  setText('con-current-streak', consistency.current_streak ?? 0);
  setText('con-longest-streak', consistency.longest_streak ?? 0);
  setText('con-active-month',   consistency.active_days_month ?? 0);
  setText('con-active-total',   consistency.active_days_total ?? 0);
  setText('con-total-acts',     consistency.total_activities ?? 0);

  if (consistency.best_month) {
    const [y, m] = consistency.best_month.split('-');
    const label = new Date(parseInt(y), parseInt(m)-1).toLocaleDateString('en-US', { month:'short', year:'numeric' });
    setText('con-best-month', label);
  } else {
    setText('con-best-month', '—');
  }

  // ── Calendar ──
  renderCalendar();

  // ── Monthly chart ──
  renderMonthlyChart(consistency.monthly || []);

  // ── History feed ──
  setupHistoryFilters();
  renderHistoryFeed();
}

// ── Calendar ──────────────────────────────────────────────────────────────

function renderCalendar() {
  const monthNames = ['January','February','March','April','May','June',
                      'July','August','September','October','November','December'];
  setText('cal-month-label', `${monthNames[calMonth]} ${calYear}`);

  const grid = document.getElementById('cal-grid');
  if (!grid) return;

  const today    = new Date();
  const todayStr = today.toISOString().split('T')[0];

  const firstDay   = new Date(calYear, calMonth, 1);
  const lastDay    = new Date(calYear, calMonth + 1, 0);
  const startDow   = (firstDay.getDay() + 6) % 7; // Monday = 0
  const daysInMon  = lastDay.getDate();
  const prevLastDay = new Date(calYear, calMonth, 0).getDate();

  let cells = [];

  // Prev month tail
  for (let i = startDow - 1; i >= 0; i--) {
    const d = prevLastDay - i;
    const pm = calMonth === 0 ? 11 : calMonth - 1;
    const py = calMonth === 0 ? calYear - 1 : calYear;
    cells.push({ day: d, dateStr: `${py}-${String(pm+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`, otherMonth: true });
  }

  // Current month
  for (let d = 1; d <= daysInMon; d++) {
    cells.push({
      day: d,
      dateStr: `${calYear}-${String(calMonth+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`,
      otherMonth: false
    });
  }

  // Next month fill
  const rem = (7 - (cells.length % 7)) % 7;
  for (let d = 1; d <= rem; d++) {
    const nm = calMonth === 11 ? 0 : calMonth + 1;
    const ny = calMonth === 11 ? calYear + 1 : calYear;
    cells.push({ day: d, dateStr: `${ny}-${String(nm+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`, otherMonth: true });
  }

  // Monthly stats for footer
  let monthActiveDays = 0, monthWorkouts = 0;

  grid.innerHTML = cells.map(({ day, dateStr, otherMonth }) => {
    const info     = calData[dateStr];
    const count    = info ? info.count : 0;
    const isToday  = dateStr === todayStr;
    const isFuture = dateStr > todayStr;

    if (!otherMonth && !isFuture && count > 0) {
      monthActiveDays++;
      monthWorkouts += count;
    }

    let intensity = 0;
    if (!otherMonth && !isFuture && count > 0) {
      intensity = count === 1 ? 1 : count === 2 ? 2 : count === 3 ? 3 : 4;
    }

    const classes = [
      'cal-cell',
      'cal-cell--circle',
      otherMonth ? 'cal-cell--other-month' : '',
      isFuture && !otherMonth ? 'cal-cell--future' : '',
      isToday ? 'cal-cell--today' : '',
      !otherMonth && !isFuture && count > 0 ? 'cal-cell--active' : '',
      `cal-cell--intensity-${intensity}`
    ].filter(Boolean).join(' ');

    const onclick = (!otherMonth && !isFuture && count > 0)
      ? `data-ev-click="showDayDetail('${dateStr}')"` : '';

    const tooltip = count > 0
      ? `${count} workout${count>1?'s':''} · ${dateStr}` : dateStr;

    return `<div class="${classes}" title="${tooltip}" ${onclick}>
      <span class="cal-day-num">${day}</span>
      ${count > 0 ? '<span class="cal-dot"></span>' : ''}
    </div>`;
  }).join('');

  // Update footer stats for visible month
  setText('cal-stat-days',     monthActiveDays);
  setText('cal-stat-workouts', monthWorkouts);
}

function showDayDetail(dateStr) {
  const info = calData[dateStr];
  if (!info) return;

  const detail = document.getElementById('cal-day-detail');
  const dateEl = document.getElementById('cal-detail-date');
  const bodyEl = document.getElementById('cal-detail-body');
  if (!detail || !dateEl || !bodyEl) return;

  const d = new Date(dateStr + 'T12:00:00');
  dateEl.textContent = d.toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric', year:'numeric' });

  bodyEl.innerHTML = info.activities.map(a => `
    <div class="cal-detail-activity">
      <div class="cal-detail-emoji">${ACT_ICONS[a.type] || '🏅'}</div>
      <div style="flex:1;min-width:0">
        <div class="cal-detail-name">${escHtml(a.name || a.type)}</div>
        <div class="cal-detail-meta">
          ${a.source !== 'manual' ? `<span style="font-size:10.5px;background:var(--gray-100);padding:1px 6px;border-radius:99px;margin-right:6px">${a.source}</span>` : ''}
          ${a.type}
        </div>
      </div>
      <div class="cal-detail-chips">
        ${a.duration  ? `<span class="cal-chip">⏱ ${a.duration}m</span>` : ''}
        ${a.calories  ? `<span class="cal-chip">🔥 ${a.calories}</span>` : ''}
        ${a.distance  ? `<span class="cal-chip">📍 ${a.distance}km</span>` : ''}
      </div>
    </div>
  `).join('');

  detail.style.display = 'block';
  detail.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

function calPrevMonth() {
  calMonth--;
  if (calMonth < 0) { calMonth = 11; calYear--; }
  renderCalendar();
  document.getElementById('cal-day-detail').style.display = 'none';
}

function calNextMonth() {
  const now = new Date();
  if (calYear === now.getFullYear() && calMonth === now.getMonth()) return; // don't go future
  calMonth++;
  if (calMonth > 11) { calMonth = 0; calYear++; }
  renderCalendar();
  document.getElementById('cal-day-detail').style.display = 'none';
}

// ── Monthly bar chart ──────────────────────────────────────────────────────

function renderMonthlyChart(monthly) {
  const el = document.getElementById('monthly-chart');
  if (!el) return;

  if (monthly.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:8px 0">No activity data yet</div>';
    return;
  }

  const maxDays = Math.max(...monthly.map(m => m.active_days), 1);

  el.innerHTML = monthly.map(m => {
    const [year, mon] = m.month.split('-');
    const label = new Date(parseInt(year), parseInt(mon)-1).toLocaleDateString('en-US', { month:'short', year:'2-digit' });
    const pct   = ((m.active_days / maxDays) * 100).toFixed(0);
    const isEmpty = m.active_days === 0;

    return `
      <div class="monthly-row">
        <div class="monthly-label">${label}</div>
        <div class="monthly-bar-track ${isEmpty ? 'monthly-bar-track--empty' : ''}">
          <div class="monthly-bar-fill" style="width:${isEmpty ? '100' : pct}%">
            ${!isEmpty ? `<span class="monthly-bar-text">${m.active_days}d · ${m.count} workouts</span>` : ''}
          </div>
        </div>
        <div class="monthly-count">${m.active_days}</div>
      </div>
    `;
  }).join('');
}

// ── History Feed ───────────────────────────────────────────────────────────

function setupHistoryFilters() {
  let timer;
  ['history-search','history-type-filter','history-source-filter'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input',  () => { clearTimeout(timer); timer = setTimeout(() => { historyPage=0; renderHistoryFeed(); }, 250); });
      el.addEventListener('change', () => { historyPage = 0; renderHistoryFeed(); });
    }
  });
}

function getFilteredHistory() {
  const search = (document.getElementById('history-search')?.value || '').toLowerCase();
  const type   = document.getElementById('history-type-filter')?.value || '';
  const source = document.getElementById('history-source-filter')?.value || '';

  return allHistoryActivities.filter(a => {
    if (type   && a.type   !== type)   return false;
    if (source && a.source !== source) return false;
    if (search && !`${a.name} ${a.type} ${a.date} ${a.notes}`.toLowerCase().includes(search)) return false;
    return true;
  });
}

function renderHistoryFeed() {
  const filtered = getFilteredHistory();
  const el = document.getElementById('history-feed');
  const statsBar = document.getElementById('history-stats-bar');
  const loadMore = document.getElementById('history-load-more');
  if (!el) return;

  // Aggregate stats for filtered set
  const totalCal  = filtered.reduce((s,a) => s + (a.calories||0), 0);
  const totalMin  = filtered.reduce((s,a) => s + (a.duration||0), 0);
  const totalKm   = filtered.reduce((s,a) => s + (a.distance||0), 0);
  const totalActs = filtered.length;

  const totalLabel = document.getElementById('history-total-label');
  if (totalLabel) totalLabel.textContent = `${filtered.length} of ${allHistoryActivities.length}`;
  if (statsBar) {
    statsBar.innerHTML = [
      { val: totalActs, label: 'Activities' },
      { val: `${totalMin}m`, label: 'Active time' },
      { val: totalCal.toLocaleString(), label: 'Calories' },
      { val: `${totalKm.toFixed(1)} km`, label: 'Distance' },
    ].map(s => `
      <div class="history-stat">
        <div class="history-stat-val">${s.val}</div>
        <div class="history-stat-label">${s.label}</div>
      </div>
    `).join('');
  }

  if (filtered.length === 0) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><div class="empty-text">No activities found</div><div class="empty-sub">Try changing your filters</div></div>`;
    if (loadMore) loadMore.style.display = 'none';
    return;
  }

  const page  = filtered.slice(0, (historyPage + 1) * HISTORY_PAGE_SIZE);
  const hasMore = filtered.length > page.length;

  el.innerHTML = page.map(a => `
    <div class="activity-item" style="border-left:3px solid ${actTypeColor(a.type)}">
      <div class="act-type-icon" style="background:${ACT_COLORS[a.type]||'var(--gray-50)'}">
        ${ACT_ICONS[a.type]||'🏅'}
      </div>
      <div class="act-info" style="flex:1">
        <div class="act-name">${escHtml(a.name || a.type)}</div>
        <div class="act-meta">
          <span>📅 ${formatDate(a.date)}</span>
          ${a.source !== 'manual' ? `<span class="act-source-badge">${a.source}</span>` : ''}
          ${a.notes ? `<span style="color:var(--gray-400);font-style:italic">${escHtml(a.notes.slice(0,40))}${a.notes.length>40?'…':''}</span>` : ''}
        </div>
      </div>
      <div class="act-stats">
        ${a.duration      ? `<div class="act-stat"><div class="act-stat-val">${a.duration}m</div><div class="act-stat-label">time</div></div>` : ''}
        ${a.distance      ? `<div class="act-stat"><div class="act-stat-val">${a.distance}km</div><div class="act-stat-label">dist</div></div>` : ''}
        ${a.calories      ? `<div class="act-stat"><div class="act-stat-val">${a.calories}</div><div class="act-stat-label">kcal</div></div>` : ''}
        ${a.heart_rate_avg? `<div class="act-stat"><div class="act-stat-val">${a.heart_rate_avg}</div><div class="act-stat-label">bpm</div></div>` : ''}
        ${a.steps         ? `<div class="act-stat"><div class="act-stat-val">${a.steps.toLocaleString()}</div><div class="act-stat-label">steps</div></div>` : ''}
      </div>
      <button class="btn-icon act-delete" data-ev-click="deleteActivityHistory('${a.id}')" title="Delete">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
      </button>
    </div>
  `).join('');

  if (loadMore) loadMore.style.display = hasMore ? 'block' : 'none';
}

function loadMoreHistory() {
  historyPage++;
  renderHistoryFeed();
}

function deleteActivityHistory(id) {
  undoable('Deleting activity…', async () => {
    await fetch(`/api/fitness/activities/${id}`, { method:'DELETE' });
    // Remove from local array so we don't need a full reload
    allHistoryActivities = allHistoryActivities.filter(a => a.id !== id);
    // Also remove from calData
    Object.keys(calData).forEach(date => {
      calData[date].activities = calData[date].activities.filter(a => a.id !== id);
      calData[date].count = calData[date].activities.length;
      if (calData[date].count === 0) delete calData[date];
    });
    renderHistoryFeed();
    renderCalendar();
    loadDashboard();
    // Refresh consistency hero stats
    fetch('/api/fitness/consistency').then(r => r.json()).then(con => {
      setText('con-current-streak',  con.current_streak ?? 0);
      setText('con-longest-streak',  con.longest_streak ?? 0);
      setText('con-active-month',    con.active_days_month ?? 0);
      setText('con-total-acts',      con.total_activities ?? 0);
    }).catch(() => {});
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────

function actTypeColor(type) {
  const c = { running:'#4F8D74', cycling:'#5E8299', walking:'#E0A34E', swimming:'#D07D4E', yoga:'#5A9E70', gym:'#DC2626', hiking:'#B9803A', stretching:'#059669', tennis:'#C15646', pickleball:'#C15646', basketball:'#EA580C', football:'#5A9E70', badminton:'#C15646', volleyball:'#EA580C', baseball:'#5E8299', cricket:'#5A9E70', golf:'#5A9E70', boxing:'#DC2626', martial_arts:'#DC2626', dancing:'#D07D4E', rowing:'#5E8299', climbing:'#B9803A', skiing:'#5E8299', snowboarding:'#5E8299', skating:'#5E8299', cycling_indoor:'#5E8299', pilates:'#D07D4E', crossfit:'#DC2626', other:'#9CA3AF' };
  return c[type] || '#9CA3AF';
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric', year:'numeric' });
}

// ════════════════════════════════════════════════════════════════
// FOOD TRACKER
// ════════════════════════════════════════════════════════════════

let foodDate    = localToday();
let foodTargets = {};
let selectedMealType = 'lunch';
let selectedFoodItem = null;
let foodSearchTimer  = null;
let activeFoodCat    = '';
let _dietPref        = '';   // '', 'veg', 'egg', 'vegan', 'jain' — filters the food picker

const MEAL_TYPES = [
  { id:'breakfast', label:'Breakfast', icon:'☀️' },
  { id:'lunch',     label:'Lunch',     icon:'🌤️' },
  { id:'snack',     label:'Snack',     icon:'🍎' },
  { id:'dinner',    label:'Dinner',    icon:'🌙' },
];

const MEAL_ORDER = ['breakfast','lunch','snack','dinner'];

// ── Main loader ──────────────────────────────────────────────────────────────
function toggleMicroPanel() {
  const panel = document.getElementById('micro-panel');
  const chevron = document.getElementById('micro-chevron');
  if (!panel) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : '';
  if (chevron) chevron.style.transform = open ? 'rotate(-90deg)' : 'rotate(0deg)';
}

async function loadFoodTracker() {
  const picker = document.getElementById('food-date-picker');
  if (picker && !picker.value) picker.value = foodDate;

  // Render empty meal sections immediately — no waiting for API
  renderMealSections({});

  const [dayData, weekData] = await Promise.all([
    fetch(`/api/food/log/${foodDate}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/weekly').then(r => r.json()).catch(() => [])
  ]);

  if (!dayData) return;

  foodTargets = dayData.targets || {};
  const totals = dayData.summary?.totals || {};
  const byMeal = dayData.summary?.by_meal || {};

  // Update header label
  const lbl = document.getElementById('food-date-label');
  if (lbl) {
    const d = new Date(foodDate + 'T12:00:00');
    const today = localToday();
    lbl.textContent = foodDate === today
      ? "Today's nutrition"
      : d.toLocaleDateString('en-US', { weekday:'long', month:'short', day:'numeric' });
  }

  // Macro rings
  updateRings(totals, foodTargets);

  // Meal sections
  renderMealSections(byMeal);

  // Micronutrients
  renderMicronutrients(totals, dayData.summary?.log_count || 0);

  // Suggestions
  const sugEl = document.getElementById('food-suggestions');
  if (sugEl) {
    const sugs = dayData.suggestions || [];
    if (sugs.length === 0) {
      sugEl.innerHTML = '<div style="color:var(--gray-400);font-size:13px">Log meals to see personalised suggestions.</div>';
    } else {
      renderSuggestions(sugEl, sugs);
    }
  }

  // Weekly trend
  renderFoodWeeklyChart(weekData, foodTargets);

  // Quick-add recent meals panel
  loadQuickMeals();
}

// True only once the profile has enough (weight/height/age/gender) for
// calc_tdee to compute real numbers. Without it, every "target" in the UI is a
// population average wearing the user's name — 2000 kcal, 56g protein, 250g
// carbs. The backend is careful to return null here; the frontend used to
// paper over it with `|| 2000` and then colour a progress bar red for going
// "over" a budget nobody ever set.
function hasTargets(targets) {
  return !!(targets && targets.target_calories);
}

// ── Macro rings ──────────────────────────────────────────────────────────────
function updateRings(totals, targets) {
  const known = hasTargets(targets);
  const macros = [
    { key:'calories', id:'cal',   target: targets?.target_calories, unit:'kcal', color:'#4F8D74' },
    { key:'protein',  id:'prot',  target: targets?.protein_g,       unit:'g',    color:'#5E8299' },
    { key:'carbs',    id:'carbs', target: targets?.carbs_g,         unit:'g',    color:'#E0A34E' },
    { key:'fat',      id:'fat',   target: targets?.fat_g,           unit:'g',    color:'#D07D4E' },
    { key:'fiber',    id:'fiber', target: targets?.fiber_g,         unit:'g',    color:'#5A9E70' },
  ];

  macros.forEach(m => {
    const val = Math.round(totals?.[m.key] || 0);
    // No target → no denominator, so no percentage and no filled bar. What the
    // user ate is still true and still shown.
    const pct = (known && m.target) ? Math.min((val / m.target) * 100, 100).toFixed(0) : 0;

    // Compact bar — value
    const valEl = document.getElementById(`fmc-${m.id}`);
    if (valEl) valEl.textContent = m.id === 'cal' ? val : val + 'g';

    // Compact bar — progress bar width
    const barEl = document.getElementById(`fmc-bar-${m.id}`);
    if (barEl) barEl.style.width = pct + '%';

    // Compact bar — target label
    const tgtEl = document.getElementById(`fmc-${m.id}-target`);
    if (tgtEl) tgtEl.textContent = (known && m.target)
      ? `/ ${m.target}${m.id !== 'cal' ? 'g' : ''}` : '';

    // Legacy ring SVG support (kept in case rings still exist somewhere)
    const ring = document.getElementById(`ring-${m.id}`);
    if (ring) ring.style.strokeDashoffset = (201 - (pct / 100) * 201).toFixed(1);
    setText(`ring-${m.id}-val`,    val);
    setText(`ring-${m.id}-target`, (known && m.target)
      ? `/ ${m.target}${m.unit !== 'kcal' ? m.unit : ''}` : '');
  });
}

// ── Meal sections ─────────────────────────────────────────────────────────────
function renderMealSections(byMeal) {
  const el = document.getElementById('meal-sections');
  if (!el) return;

  const today    = localToday();
  const isPast   = foodDate < today;
  const isFuture = foodDate > today;

  // Past date banner
  const pastBanner = isPast ? `
    <div style="background:var(--teal-50);border:1px solid var(--teal-100);border-radius:10px;
                padding:10px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px;
                font-size:13px;color:var(--teal-800)">
      <span>📅</span>
      <span>Viewing <strong>${new Date(foodDate+'T12:00:00').toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'})}</strong>
       — you can still add, edit, or delete items for this day.</span>
    </div>` : '';

  el.innerHTML = pastBanner + MEAL_ORDER.map(mtype => {
    const meal = byMeal[mtype] || { calories:0, protein:0, carbs:0, fat:0, items:[] };
    const meta = MEAL_TYPES.find(m => m.id === mtype);

    const itemsHtml = meal.items.map(item => `
      <div class="food-log-row" id="flr-${item.id}">
        <div class="food-log-emoji">${getFoodEmoji(item.food_id)}</div>
        <div style="flex:1;min-width:0">
          <div class="food-log-name">${escHtml(item.food_name)}</div>
          <div class="food-log-qty">
            <span id="flq-${item.id}">${item.quantity_g}g</span>
            <span style="color:var(--gray-300);margin:0 4px">·</span>
            <span style="color:var(--gray-400)">${Math.round(item.calories)} kcal</span>
          </div>
        </div>
        <div class="food-log-macros">
          <span class="food-macro-chip fmc-prot">${Math.round(item.protein)}g P</span>
          <span class="food-macro-chip fmc-carb">${Math.round(item.carbs)}g C</span>
          <span class="food-macro-chip fmc-fat">${Math.round(item.fat)}g F</span>
        </div>
        <div style="display:flex;gap:4px;flex-shrink:0">
          <button class="btn-icon" title="Edit quantity"
                  data-ev-click="editFoodQty('${item.id}',${item.quantity_g},'${escHtml(item.food_name)}')"
                  style="color:var(--gray-400);padding:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2.5" stroke-linecap="round">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button class="btn-icon" title="Remove"
                  data-ev-click="removeFoodLog('${item.id}')"
                  style="color:var(--gray-300);padding:4px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2.5" stroke-linecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </div>`).join('');

    const headerRight = meal.items.length > 0
      ? `<div class="meal-block-cal">${Math.round(meal.calories)} kcal · ${Math.round(meal.protein)}g protein</div>`
      : `<div class="meal-block-cal meal-block-cal--empty">Nothing logged</div>`;

    return `<div class="meal-block">
      <div class="meal-block-header">
        <div class="meal-block-title">${meta.icon} ${meta.label}</div>
        ${headerRight}
      </div>
      ${itemsHtml ? `<div class="meal-items">${itemsHtml}</div>` : ''}
      <button class="meal-add-btn" data-ev-click="openAddFoodModal('${mtype}')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        + Add to ${meta.label}
      </button>
    </div>`;
  }).join('');
}

// ── Micronutrients panel ──────────────────────────────────────────────────────
function renderMicronutrients(totals, logCount) {
  const el = document.getElementById('micro-panel');
  if (!el) return;

  const micros = [
    { key:'vit_a',  label:'Vit A',   rda:900,  unit:'µg' },
    { key:'vit_c',  label:'Vit C',   rda:90,   unit:'mg' },
    { key:'vit_d',  label:'Vit D',   rda:20,   unit:'µg' },
    { key:'vit_b12',label:'Vit B12', rda:2.4,  unit:'µg' },
    { key:'iron',   label:'Iron',    rda:12,   unit:'mg' },
    { key:'calcium',label:'Calcium', rda:1000, unit:'mg' },
    { key:'magnesium',label:'Magnesium',rda:400,unit:'mg'},
    { key:'zinc',   label:'Zinc',    rda:11,   unit:'mg' },
    { key:'folate', label:'Folate',  rda:400,  unit:'µg' },
  ];

  if (logCount === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:12.5px;text-align:center;padding:12px 0">Log food to see micronutrients</div>';
    return;
  }

  el.innerHTML = micros.map(m => {
    const val = totals[m.key] || 0;
    const pct = Math.min((val / m.rda) * 100, 120);
    const cls = pct < 30 ? 'micro-fill-deficit' : pct < 70 ? 'micro-fill-warn' : pct > 110 ? 'micro-fill-over' : 'micro-fill-ok';
    return `<div class="micro-row">
      <div class="micro-label">${m.label}</div>
      <div class="micro-bar-track"><div class="micro-bar-fill ${cls}" style="width:${Math.min(pct,100).toFixed(0)}%"></div></div>
      <div class="micro-val">${val < 10 ? val.toFixed(1) : Math.round(val)}${m.unit}</div>
    </div>`;
  }).join('');
}

// ── Weekly trend chart ────────────────────────────────────────────────────────
function renderFoodWeeklyChart(weekData, targets) {
  const el = document.getElementById('food-weekly-chart');
  if (!el || weekData.length === 0) return;
  // Without a real target there's nothing to be "over" or "low" against, so
  // the bars are scaled to the week's own range and left uncoloured.
  const tCal   = targets?.target_calories || null;
  const maxCal = Math.max(...weekData.map(d => d.calories), tCal || 0, 1);
  const days   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  el.innerHTML = weekData.map((d, i) => {
    const pct  = (d.calories / maxCal * 80).toFixed(0);
    const over = tCal ? d.calories > tCal * 1.1 : false;
    const low  = tCal ? d.calories < tCal * 0.4 : false;
    const cls  = !tCal ? 'fw-bar--ok' : over ? 'fw-bar--over' : low ? 'fw-bar--low' : 'fw-bar--ok';
    const isToday = d.date === foodDate;
    return `<div class="fw-bar-col">
      <div class="fw-bar ${cls}" style="height:${pct}px;opacity:${isToday?1:.7}"></div>
      <div class="fw-bar-label" style="font-weight:${isToday?'700':'400'};color:${isToday?'var(--teal-600)':'var(--gray-400)'}">${days[i]}</div>
      <div class="fw-bar-count">${d.calories > 0 ? Math.round(d.calories) : ''}</div>
    </div>`;
  }).join('');
}

// ── Date navigation ───────────────────────────────────────────────────────────
function foodDateShift(delta) {
  const d = new Date(foodDate + 'T12:00:00');
  d.setDate(d.getDate() + delta);
  const todayStr = localToday();
  const shiftedStr = d.getFullYear() + '-' +
    String(d.getMonth()+1).padStart(2,'0') + '-' +
    String(d.getDate()).padStart(2,'0');
  if (shiftedStr > todayStr) return;  // don't go into future
  foodDate = shiftedStr;
  const picker = document.getElementById('food-date-picker');
  if (picker) picker.value = foodDate;
  loadFoodTracker();
}

function loadFoodDay(dateStr) {
  foodDate = dateStr;
  loadFoodTracker();
}

// ── Add Food Modal ────────────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════
// CUSTOM FOOD — create, save, display, select
// ════════════════════════════════════════════════════════════


async function deleteCustomFood(id) {
  await fetch(`/api/food/custom/${id}`, {method: 'DELETE'});
  showToast('Custom food removed');
  searchFoodDB(document.getElementById('food-search-input')?.value || '');
}

function openCustomFoodForm() {
  const form = document.getElementById('custom-food-form');
  const btn  = document.getElementById('custom-food-toggle-btn');
  if (!form) return;
  const isOpen = form.style.display !== 'none';
  form.style.display = isOpen ? 'none' : 'block';
  if (btn) btn.textContent = isOpen ? '+ Custom food' : '− Cancel';
  if (!isOpen) {
    // Clear fields
    ['cf-name','cf-calories','cf-protein','cf-carbs','cf-fat','cf-serving'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    document.getElementById('cf-serving').placeholder = '100';
    document.getElementById('cf-name')?.focus();
  }
}

function closeCustomFoodForm() {
  const form = document.getElementById('custom-food-form');
  const btn  = document.getElementById('custom-food-toggle-btn');
  if (form) form.style.display = 'none';
  if (btn)  btn.textContent = '+ Custom food';
}

async function saveCustomFood() {
  const name     = document.getElementById('cf-name')?.value.trim();
  const calories = parseFloat(document.getElementById('cf-calories')?.value) || 0;
  const protein  = parseFloat(document.getElementById('cf-protein')?.value)  || 0;
  const carbs    = parseFloat(document.getElementById('cf-carbs')?.value)    || 0;
  const fat      = parseFloat(document.getElementById('cf-fat')?.value)      || 0;
  const serving  = parseFloat(document.getElementById('cf-serving')?.value)  || 100;

  if (!name)     { showToast('Enter a food name', 'error'); return; }
  if (!calories) { showToast('Enter calories', 'error'); return; }

  const btn = document.querySelector('#custom-food-form .btn-primary');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  const r = await fetch('/api/food/custom', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name, calories, protein, carbs, fat, fiber: 0, serving_g: serving })
  }).then(r => r.json()).catch(() => null);

  if (btn) { btn.disabled = false; btn.textContent = 'Save & Add to Meal'; }

  if (r?.success) {
    showToast(`"${name}" saved to My Foods ✓`, 'success');
    closeCustomFoodForm();
    // Immediately select this food so user can log it
    selectFoodItem({
      id: r.food.id || 'custom_' + Date.now(),
      name: r.food.name,
      calories: r.food.calories,
      protein:  r.food.protein  || 0,
      carbs:    r.food.carbs    || 0,
      fat:      r.food.fat      || 0,
      fiber:    0,
      serving_g: r.food.serving_g || 100,
      serving_unit: 'g',
      emoji: '⭐',
      is_custom: true,
    });
    // Refresh results so the new food appears with "My Foods" badge
    searchFoodDB(document.getElementById('food-search-input')?.value || '');
  } else {
    showToast('Failed to save custom food', 'error');
  }
}

function openAddFoodModal(mealType) {
  selectedMealType = mealType || 'lunch';
  document.getElementById('add-food-overlay').style.display = 'flex';
  // Init
  setTimeout(() => {
    loadFoodCategories();
    searchFoodDB('');
    document.getElementById('food-search-input')?.focus();
  }, 50);
}

// Category emoji map for the dropdown
const CAT_EMOJI = {
  'American':'🇺🇸','American Fast Food':'🍔','American Breakfast':'🥞','American Desserts':'🍰',
  'Indian Main':'🍛','Indian Bread':'🫓','Indian Snacks':'🟡','Indian Street Food':'🌆',
  'Indian Beverages':'☕','Indian Sides':'🫙','Indian Sweets':'🍬','South Indian':'🥞','Indo-Chinese':'🥡',
  'Pakistani':'🥘','Bangladeshi':'🐟','Sri Lankan':'🫓','Nepali':'🥟','Afghan':'🫙',
  'South Asian Sweets':'🍮','Street Food':'🌆',
  'Italian':'🍝','Mediterranean':'🫙','Thai':'🌶️','Japanese':'🍣',
  'Global Mains':'🌍','Global Breakfast':'🌅','Global Snacks':'🍿','Cafe':'☕',
  'Korean':'🇰🇷','Vietnamese':'🇻🇳','Mexican':'🌮','European':'🥐',
  'Filipino':'🇵🇭','Indonesian':'🇮🇩','Caribbean':'🏝️','African':'🍲','Alcohol':'🍺',
  'Condiments':'🧂','Cereals':'🥣','Jain':'🌿','Baby Food':'🍼',
  'Fruits':'🍎','Vegetables':'🥦','Protein':'🥩','Dairy':'🥛',
  'Nuts & Seeds':'🌰','Dry Fruits':'🍇','Trail Mix':'🥜','Chocolates':'🍫',
  'Packaged Snacks':'📦','Supplements':'💪','Beverages':'🥤',
  'Breakfast':'🌅','Salads':'🥗','Rice & Grains':'🍚',
  'Dips & Spreads':'🫙','Fats & Oils':'🫒',
};

const CAT_GROUPS = {
  '🇺🇸 American':    ['American','American Fast Food','American Breakfast','American Desserts'],
  '🇮🇳 Indian':      ['Indian Main','Indian Bread','Indian Snacks','Indian Street Food','Indian Beverages','Indian Sides','Indian Sweets','South Indian','Indo-Chinese','Jain'],
  '🌏 South Asian':  ['Pakistani','Bangladeshi','Sri Lankan','Nepali','Afghan','South Asian Sweets','Street Food'],
  '🌍 World Cuisine':['Italian','European','Mediterranean','Thai','Japanese','Korean','Vietnamese','Mexican','Filipino','Indonesian','Caribbean','African','Global Mains','Global Breakfast','Global Snacks','Cafe'],
  '🍺 Bar':          ['Alcohol'],
  '🥗 Healthy':      ['Protein','Dairy','Fruits','Vegetables','Salads','Rice & Grains','Breakfast','Cereals','Baby Food','Beverages'],
  '🍿 Snacks':       ['Nuts & Seeds','Dry Fruits','Trail Mix','Chocolates','Packaged Snacks','Dips & Spreads','Condiments'],
  '💪 Fitness':      ['Supplements','Fats & Oils'],
};

// How a food's quantity is entered. `count` is NOT listed here any more — a
// food is counted by pieces when its DB record carries a `piece` {unit,g}
// (e.g. one almond = 1.2 g), so the picker can offer a real "× N almonds"
// stepper instead of assuming the whole serving is one piece. This map now
// only holds the two modes that aren't per-item: `cup` (liquids, 240 ml) and
// `scoop` (supplements, one scoop = serving_g).
const FOOD_QTY_MODE = {
  "green_tea": "cup", "coconut_water": "cup", "masala_chai": "cup",
  "black_chai": "cup", "ginger_chai": "cup", "turmeric_milk": "cup",
  "rose_sharbat": "cup", "nimbu_pani": "cup", "aam_panna": "cup",
  "jaljeera": "cup", "badam_milk": "cup", "mango_lassi": "cup",
  "banana_smoothie": "cup", "coffee_black": "cup", "coffee_latte": "cup",
  "orange_juice": "cup", "cold_brew_black": "cup", "iced_coffee_creamer": "cup",
  "chocolate_milk": "cup", "green_smoothie": "cup", "berry_smoothie": "cup",
  "apple_cider": "cup", "kombucha": "cup", "protein_smoothie": "cup",
  "starbucks_latte_grande": "cup", "starbucks_frappuccino": "cup",
  "whole_milk": "cup", "skimmed_milk": "cup", "semi_milk": "cup",
  "oat_milk": "cup", "almond_milk": "cup", "soy_milk": "cup",
  "coconut_milk_drk": "cup", "buffalo_milk": "cup", "goat_milk": "cup",
  "whey_concentrate": "scoop", "whey_isolate": "scoop", "whey_hydrolysate": "scoop",
  "casein_protein": "scoop", "plant_protein": "scoop", "mass_gainer": "scoop",
  "creatine": "scoop", "bcaa_powder": "scoop", "protein_bar": "scoop",
  "collagen_peptides": "scoop", "ashwagandha": "scoop", "sattu_drink": "scoop",
};

// "almond" -> "almonds", "cherry" -> "cherries", "walnut half" -> "walnut halves"
function pluralUnit(u) {
  if (!u) return 'pieces';
  if (/half$/.test(u)) return u.replace(/half$/, 'halves');
  if (/[^aeiou]y$/.test(u)) return u.replace(/y$/, 'ies');
  if (/(s|sh|ch|x)$/.test(u)) return u + 'es';
  return u + 's';
}
// Grams label without a trailing ".0" (1.2 -> "1.2", 40 -> "40")
function trimG(g) { return Number(g).toFixed(1).replace(/\.0$/, ''); }

// {food_id: grams} — what this user habitually eats of each food, so the
// portion picker opens on THEIR serving instead of the DB's generic average.
let _usualPortions = {};

async function loadFoodCategories() {
  const r = await fetch('/api/food/db').then(res => res.json()).catch(err => {
    console.error('[Food] /api/food/db failed:', err);
    return {categories:[], foods:[]};
  });
  if (r.usual_portions) _usualPortions = r.usual_portions;
  if ('diet_pref' in r) { _dietPref = r.diet_pref || ''; highlightDietChips(); }
  const sel = document.getElementById('food-cat-select');
  if (!sel) return;
  const allCats = r.categories || [];
  if (allCats.length === 0) {
    console.warn('[Food] No categories returned. API response:', r);
  }

  sel.innerHTML = '<option value="">🌍 All Foods (' + allCats.length + ' categories)</option>';

  const grouped_flat = Object.values(CAT_GROUPS).flat();

  Object.entries(CAT_GROUPS).forEach(([groupLabel, catList]) => {
    const available = catList.filter(c => allCats.includes(c));
    if (!available.length) return;
    const grp = document.createElement('optgroup');
    grp.label = groupLabel;
    available.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = (CAT_EMOJI[c] || '🍽️') + ' ' + c;
      if (activeFoodCat === c) opt.selected = true;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  });

  const ungrouped = allCats.filter(c => !grouped_flat.includes(c));
  if (ungrouped.length) {
    const grp = document.createElement('optgroup');
    grp.label = '📂 Other';
    ungrouped.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = (CAT_EMOJI[c] || '🍽️') + ' ' + c;
      if (activeFoodCat === c) opt.selected = true;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }
}

function highlightDietChips() {
  document.querySelectorAll('#diet-pref-row .diet-chip').forEach(b =>
    b.classList.toggle('active', (b.dataset.diet || '') === (_dietPref || '')));
}

async function setDietPref(pref) {
  pref = pref || '';
  _dietPref = pref;
  highlightDietChips();
  // Persist so the choice sticks across sessions and applies everywhere the
  // picker is used. Send 'all' to clear (empty string is coerced to no-change).
  try {
    await fetch('/api/food/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ diet_pref: pref || 'all' })
    });
  } catch (err) { console.error('[Food] diet_pref save failed:', err); }
  searchFoodDB(document.getElementById('food-search-input')?.value || '');
}

function filterFoodCat(cat) {
  activeFoodCat = cat;
  const sel = document.getElementById('food-cat-select');
  if (sel) sel.value = cat;
  const badge = document.getElementById('food-cat-active-badge');
  const badgeText = document.getElementById('food-cat-active-text');
  if (badge && badgeText) {
    if (cat) {
      badgeText.textContent = (CAT_EMOJI[cat] || '🍽️') + ' ' + cat;
      badge.style.display = 'inline-flex';
    } else {
      badge.style.display = 'none';
    }
  }
  const si = document.getElementById('food-search-input');
  if (si && cat) { si.value = ''; toggleSearchClear(''); }
  searchFoodDB(si?.value || '');
}

function clearFoodSearch() {
  const el = document.getElementById('food-search-input');
  if (el) { el.value = ''; el.focus(); }
  toggleSearchClear('');
  searchFoodDB('');
}

function toggleSearchClear(val) {
  const btn = document.getElementById('food-search-clear');
  if (btn) btn.style.display = val.length > 0 ? 'flex' : 'none';
}

async function searchFoodDB(query) {
  clearTimeout(foodSearchTimer);
  toggleSearchClear(query);
  foodSearchTimer = setTimeout(async () => {
    const params = new URLSearchParams({ q: query, limit: 80 });
    if (activeFoodCat) params.set('category', activeFoodCat);
    if (_dietPref) params.set('diet', _dietPref);
    const r = await fetch(`/api/food/db?${params}`).then(res => res.json()).catch(err => {
      console.error('[Food] search failed:', err);
      return {foods:[], custom:[]};
    });
    if (r.usual_portions) _usualPortions = r.usual_portions;
    const all = [
      ...(r.foods || []),
      ...(r.custom || []).map(c => ({...c, cal:c.calories}))
    ];
    if (all.length === 0 && (r.categories || []).length === 0) {
      console.warn('[Food] Empty results AND no categories. Raw response:', r);
    }
    const el = document.getElementById('food-search-results');
    const countEl = document.getElementById('food-results-count');
    if (!el) return;
    const label = activeFoodCat || 'all foods';
    if (countEl) countEl.textContent = all.length === 0 ? 'No results' : `${all.length} item${all.length !== 1 ? 's' : ''} in ${label}`;
    if (all.length === 0) {
      el.innerHTML = `<div class="food-empty-state" style="padding:28px 0;text-align:center">
        <div style="font-size:28px;margin-bottom:8px">🔍</div>
        <div style="font-size:13px;font-weight:600;color:var(--gray-600);margin-bottom:4px">Nothing found</div>
        <div style="font-size:12px;color:var(--gray-400)">Try a different name or pick another category</div>
      </div>`;
      return;
    }
    el.innerHTML = all.map(f => {
      const json = JSON.stringify(f).replace(/"/g, '&quot;');
      return `<div class="food-result-row" data-ev-click="selectFoodItem(${json})">
        <div class="food-result-emoji">${f.emoji || '🍽️'}</div>
        <div class="food-result-info">
          <div class="food-result-name">
            ${escHtml(f.name)}
            ${f.is_custom ? '<span class="food-custom-badge">My food</span>' : ''}
          </div>
          <div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">
            <span class="food-result-category-tag">${f.is_custom ? '⭐ My Foods' : f.category}</span>
            <span class="food-result-meta">${f.serving_g}${f.serving_unit||'g'} serving</span>
          </div>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div class="food-result-cal">${Math.round(f.calories || f.cal || 0)} kcal</div>
          <div style="font-size:10.5px;color:var(--gray-400)">${f.protein}g P</div>
          ${f.is_custom ? `<button style="font-size:10px;color:var(--red-400);background:none;border:none;cursor:pointer;margin-top:2px" data-ev-click="event.stopPropagation();deleteCustomFood('${f.id}')">✕ remove</button>` : ''}
        </div>
      </div>`;
    }).join('');
  }, 150);
}

function selectFoodItem(food) {
  selectedFoodItem = food;
  const col = document.getElementById('food-add-col');
  if (!col) return;

  // Open on the portion THEY usually eat, if we've seen it before. serving_g is
  // a generic average; this is their plate. Falls back until they've logged it.
  const _servingG = food.serving_g || 100;
  const _usualG   = Number(_usualPortions[food.id]) || 0;
  const _startG   = _usualG || _servingG;

  const scale = _startG / 100;                    // preview matches the input
  const cal   = Math.round((food.calories || food.cal || 0) * scale);
  const prot  = Math.round(food.protein * scale * 10)/10;
  const carbs = Math.round(food.carbs * scale * 10)/10;
  const fat   = Math.round(food.fat  * scale * 10)/10;
  const fiber = Math.round((food.fiber||0) * scale * 10)/10;

  const macros = [
    { label:'Protein', val:prot,  max:40, color:'#5E8299' },
    { label:'Carbs',   val:carbs, max:80, color:'#E0A34E' },
    { label:'Fat',     val:fat,   max:40, color:'#D07D4E' },
    { label:'Fiber',   val:fiber, max:15, color:'#5A9E70' },
  ];

  // Smart quantity mode
  // A food is counted by pieces when the DB gives it a piece weight; otherwise
  // fall back to the cup/scoop map, else plain grams.
  const piece    = (food.piece && food.piece.g) ? food.piece : null;
  const qtyMode  = piece ? 'count' : (FOOD_QTY_MODE[food.id] || 'gram');
  const servingG = _servingG;      // the food's true serving — drives unit hints
  const usualG   = _usualG;        // their habitual portion (0 = never logged)
  const startG   = _startG;        // what the input opens on
  // Grams in one "primary" unit: one piece for count, one scoop = serving.
  const unitName = piece ? (piece.unit || 'piece') : 'piece';
  const unitG    = piece ? piece.g : servingG;
  window._foodCountUnit = unitName; // so switchQtyUnit can relabel the badge/hint
  window._foodUnitG     = unitG;

  // Unit toggle state — stored on window so toggle function can access it
  window._qtyActiveUnit = qtyMode === 'gram' ? 'gram' : 'primary';

  const buildQtyUI = () => {
    // For gram-only foods: simple single input
    if (qtyMode === 'gram') {
      return `<div class="form-group" style="margin-bottom:12px">
        <label class="form-label">Quantity</label>
        <div class="food-qty-single-row">
          <input type="number" class="form-input" id="food-qty-input"
                 value="${startG}" min="1" step="5"
                 data-ev-input="updateFoodPreview(this.value)">
          <span class="food-qty-unit-badge">g</span>
        </div>
        ${usualG ? `<div class="food-qty-usual">Your usual portion</div>` : ''}
      </div>`;
    }

    // For dual-unit foods: toggle on top, one input below
    let unit1, unit2, step1, step2, default1, hint;
    // Where we know their habitual grams, open on that — converted into the
    // unit they're actually shown (2 pcs, 1.5 cups…), not a flat "1".
    if (qtyMode === 'scoop') {
      const ul = food.serving_unit || 'scoop';
      unit1 = ul + 's'; unit2 = 'g';
      step1 = 0.5; step2 = 1;
      default1 = usualG ? Math.max(0.5, Math.round(usualG / servingG * 2) / 2) : 1;
      hint = `1 ${ul} = ${servingG}g`;
    } else if (qtyMode === 'cup') {
      unit1 = 'cups'; unit2 = 'ml';
      step1 = 0.25; step2 = 10;
      default1 = usualG ? Math.max(0.25, Math.round(usualG / 240 * 4) / 4)
                        : (Math.round(servingG / 240 * 4) / 4 || 1);
      hint = '1 cup = 240ml';
    } else { // count — by real pieces (almonds, dates, biscuits…)
      unit1 = pluralUnit(unitName); unit2 = 'g';
      step1 = 1; step2 = 1;
      default1 = Math.max(1, Math.round((usualG || servingG) / unitG));
      hint = '1 ' + unitName + ' ≈ ' + trimG(unitG) + 'g';
    }

    // The conversion basis handed to the toggle/preview handlers: one piece for
    // count, one scoop (=serving_g) for scoop; cup ignores it and uses 240 ml.
    const basisG = qtyMode === 'count' ? unitG : servingG;

    return '<div class="form-group" style="margin-bottom:12px">' +
      '<div class="food-qty-header">' +
        '<label class="form-label" style="margin:0">Quantity</label>' +
        '<div class="food-unit-toggle" id="food-unit-toggle">' +
          '<button class="fut-btn active" id="fut-btn-primary" data-ev-click="switchQtyUnit(\'primary\',' + basisG + ',\'' + qtyMode + '\')">' + unit1 + '</button>' +
          '<button class="fut-btn" id="fut-btn-secondary" data-ev-click="switchQtyUnit(\'secondary\',' + basisG + ',\'' + qtyMode + '\')">' + unit2 + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="food-qty-single-row">' +
        '<input type="number" class="form-input" id="food-qty-input"' +
               ' value="' + default1 + '" min="' + (qtyMode === 'count' ? '1' : '0.25') + '" step="' + step1 + '"' +
               ' data-ev-input="updateFoodPreviewSmart(this.value,\'primary\',' + basisG + ',\'' + qtyMode + '\')">' +
        '<span class="food-qty-unit-badge" id="food-qty-unit-badge">' + unit1 + '</span>' +
      '</div>' +
      '<div class="food-qty-hint" id="food-qty-hint">' + hint + '</div>' +
      (usualG ? '<div class="food-qty-usual">Your usual portion</div>' : '') +
    '</div>';
  };

  const mealBtns = MEAL_TYPES.map(m => `
    <button type="button" class="meal-type-btn ${selectedMealType===m.id?'selected':''}"
      data-ev-click="selectMealType('${m.id}')">${m.icon} ${m.label}</button>`).join('');

  col.innerHTML = `<div class="food-add-form">
    <div class="food-add-header">
      <div class="food-add-emoji">${food.emoji || '🍽️'}</div>
      <div>
        <div class="food-add-name">${escHtml(food.name)}</div>
        <div class="food-add-cat">${food.category}</div>
      </div>
    </div>
    <div class="nutrient-preview">
      <div style="font-size:20px;font-weight:700;font-family:'EB Garamond',serif;color:var(--gray-900);margin-bottom:10px" id="fp-cal-preview">${cal} kcal</div>
      ${macros.map(m => `
        <div class="nutprev-row">
          <div class="nutprev-label">${m.label}</div>
          <div class="nutprev-bar"><div class="nutprev-fill" id="fp-bar-${m.label.toLowerCase()}" style="width:${Math.min(m.val/m.max*100,100).toFixed(0)}%;background:${m.color}"></div></div>
          <div class="nutprev-val" id="fp-val-${m.label.toLowerCase()}">${m.val}g</div>
        </div>`).join('')}
    </div>
    ${buildQtyUI()}
    <div class="form-group" style="margin-bottom:14px">
      <label class="form-label">Meal</label>
      <div class="meal-type-picker">${mealBtns}</div>
    </div>
    <button class="btn-primary" style="width:100%" data-ev-click="logSelectedFood()">
      Add to ${MEAL_TYPES.find(m=>m.id===selectedMealType)?.label || 'Meal'}
    </button>
  </div>`;

  // Keep the macro preview honest: it must show the calories for the quantity
  // actually in the box. Count/cup modes round to whole pcs/quarter-cups, so a
  // preview derived from raw grams would understate or overstate what gets
  // logged. Syncing from the rendered input makes drift impossible.
  const qtyInput = document.getElementById('food-qty-input');
  if (qtyInput) {
    if (qtyMode === 'gram') updateFoodPreview(qtyInput.value);
    else                    updateFoodPreviewSmart(qtyInput.value, 'primary', unitG, qtyMode);
  }
}

// ── Smart quantity unit toggle ─────────────────────────────────────────────

// Convert input value to grams given current active unit
function _toGrams(val, activeUnit, mode, servingG) {
  const n = parseFloat(val) || 0;
  if (activeUnit === 'primary') {
    if (mode === 'scoop' || mode === 'count') return n * servingG;
    if (mode === 'cup')                       return n * 240;
  }
  return n; // secondary is always grams/ml
}

// Convert grams to the target unit
function _fromGrams(grams, targetUnit, mode, servingG) {
  if (targetUnit === 'primary') {
    if (mode === 'count') return Math.max(1, Math.round(grams / servingG)); // whole pieces
    if (mode === 'scoop') return Math.round(grams / servingG * 10) / 10;
    if (mode === 'cup')   return Math.round(grams / 240 * 4) / 4;
  }
  return Math.round(grams); // secondary = grams/ml
}

function updateFoodPreviewSmart(val, activeUnit, servingG, mode) {
  const grams = _toGrams(val, activeUnit, mode, servingG);
  updateFoodPreview(grams);
}

function switchQtyUnit(targetUnit, servingG, mode) {
  // Read current value and convert to grams first
  const inp = document.getElementById('food-qty-input');
  if (!inp) return;
  const currentActive = window._qtyActiveUnit || 'primary';
  const grams = _toGrams(parseFloat(inp.value) || 0, currentActive, mode, servingG);

  // Convert to new unit
  const newVal = _fromGrams(grams, targetUnit, mode, servingG);
  inp.value = newVal;
  inp.step  = targetUnit === 'primary'
    ? (mode === 'cup' ? '0.25' : mode === 'scoop' ? '0.5' : '1')
    : (mode === 'cup' ? '10' : '1');

  // Update badge text
  const badge = document.getElementById('food-qty-unit-badge');
  const hint  = document.getElementById('food-qty-hint');
  const cUnit = window._foodCountUnit || 'piece';
  if (badge) {
    if (targetUnit === 'primary') {
      badge.textContent = mode === 'scoop' ? (window._foodScoopUnit || 'scoops')
                        : mode === 'cup'   ? 'cups'
                        : pluralUnit(cUnit);
    } else {
      badge.textContent = mode === 'cup' ? 'ml' : 'g';
    }
  }
  if (hint) {
    if (targetUnit === 'primary') {
      hint.textContent = mode === 'scoop' ? '1 scoop = ' + servingG + 'g'
                       : mode === 'cup'   ? '1 cup = 240ml'
                       : '1 ' + cUnit + ' ≈ ' + trimG(servingG) + 'g';
    } else {
      hint.textContent = mode === 'cup' ? 'enter in ml' : 'enter in grams';
    }
  }

  // Update toggle buttons
  document.querySelectorAll('.fut-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('fut-btn-' + targetUnit)?.classList.add('active');

  // Store active unit and trigger preview
  window._qtyActiveUnit = targetUnit;
  inp.oninput = () => updateFoodPreviewSmart(inp.value, targetUnit, servingG, mode);
  updateFoodPreviewSmart(inp.value, targetUnit, servingG, mode);
}

function syncQtyFromUnit(val, mode, servingG) { /* legacy no-op */ }
function syncQtyFromGrams(val, servingG, mode) { /* legacy no-op */ }

function selectMealType(mt) {
  selectedMealType = mt;
  document.querySelectorAll('.meal-type-btn').forEach(b => {
    b.classList.toggle('selected', b.textContent.trim().includes(MEAL_TYPES.find(m=>m.id===mt)?.label||''));
  });
  const addBtn = document.querySelector('#food-add-col button.btn-primary');
  if (addBtn) addBtn.textContent = 'Add to ' + (MEAL_TYPES.find(m=>m.id===mt)?.label||'Meal');
}

function updateFoodPreview(qty) {
  if (!selectedFoodItem) return;
  const q = parseFloat(qty) || 100;
  const scale = q / 100;
  const cal   = Math.round((selectedFoodItem.calories || selectedFoodItem.cal || 0) * scale);
  const prot  = Math.round(selectedFoodItem.protein * scale * 10)/10;
  const carbs = Math.round(selectedFoodItem.carbs   * scale * 10)/10;
  const fat   = Math.round(selectedFoodItem.fat     * scale * 10)/10;
  const fiber = Math.round((selectedFoodItem.fiber||0) * scale * 10)/10;
  setText('fp-cal-preview', `${cal} kcal`);
  [['protein',prot,40,'#5E8299'],['carbs',carbs,80,'#E0A34E'],['fat',fat,40,'#D07D4E'],['fiber',fiber,15,'#5A9E70']].forEach(([name,val,max]) => {
    const bar = document.getElementById(`fp-bar-${name}`);
    const valEl = document.getElementById(`fp-val-${name}`);
    if (bar) bar.style.width = Math.min(val/max*100,100).toFixed(0)+'%';
    if (valEl) valEl.textContent = val+'g';
  });
}

async function logSelectedFood() {
  if (!selectedFoodItem) return;
  const unitEl    = document.getElementById('food-qty-input');
  const piece     = (selectedFoodItem?.piece && selectedFoodItem.piece.g) ? selectedFoodItem.piece : null;
  const mode      = piece ? 'count' : (FOOD_QTY_MODE[selectedFoodItem?.id] || 'gram');
  // Conversion basis: grams in one piece (count) or one scoop (=serving_g).
  const basisG    = piece ? piece.g : (selectedFoodItem?.serving_g || 100);
  const activeUnit= window._qtyActiveUnit || (mode === 'gram' ? 'gram' : 'primary');
  const qty       = _toGrams(parseFloat(unitEl?.value) || 1, activeUnit, mode, basisG);
  const scale     = qty / 100;
  const f     = selectedFoodItem;

  const r = await fetch('/api/food/log', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      food_id:    f.id,
      food_name:  f.name,
      meal_type:  selectedMealType,
      date_key:   foodDate,
      quantity_g: qty,
      // Always send pre-calculated macros so the route works for both
      // standard foods (looked up by id) and custom foods (not in FOOD_BY_ID)
      calories: Math.round((f.calories || f.cal || 0) * scale * 10) / 10,
      protein:  Math.round((f.protein  || 0) * scale * 10) / 10,
      carbs:    Math.round((f.carbs    || 0) * scale * 10) / 10,
      fat:      Math.round((f.fat      || 0) * scale * 10) / 10,
      fiber:    Math.round((f.fiber    || 0) * scale * 10) / 10,
    })
  });
  const d = await r.json();
  if (d.success) {
    showToast(`${selectedFoodItem.emoji||'🍽️'} ${selectedFoodItem.name} added!`, 'success');
    closeModal('add-food-overlay');
    selectedFoodItem = null;
    document.getElementById('food-add-col').innerHTML = `<div class="food-add-placeholder"><div style="font-size:36px">🔍</div><div style="font-size:13px;color:var(--gray-400);margin-top:8px">Select a food item to add</div></div>`;
    loadFoodTracker();
    loadDashboard();
  } else {
    showToast('Failed to log food', 'error');
  }
}

function removeFoodLog(id) {
  undoable('Removing item…', async () => {
    await fetch(`/api/food/log/${id}`, { method: 'DELETE' });
    loadFoodTracker();
    loadDashboard();
  });
}

async function editFoodQty(id, currentQty, foodName) {
  const newQty = prompt(`Edit quantity for "${foodName}" (grams):`, currentQty);
  if (newQty === null) return;  // cancelled
  const qty = parseFloat(newQty);
  if (!qty || qty <= 0 || qty > 5000) { showToast('Invalid quantity', 'error'); return; }

  const r = await fetch(`/api/food/log/${id}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ quantity_g: qty }),
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    showToast(`Updated to ${qty}g`, 'success');
    loadFoodTracker();
  } else {
    showToast('Failed to update', 'error');
  }
}

// ── User Profile Modal ────────────────────────────────────────────────────────
async function openProfileModal() {
  const r = await fetch('/api/food/profile').then(res => res.json()).catch(() => null);
  if (!r) return;
  const p = r.profile;
  const form = document.getElementById('profile-form');
  if (!form) return;
  ['name','age'].forEach(k => { if (form[k]) form[k].value = p[k] || ''; });
  if (form.gender)         form.gender.value         = p.gender         || 'male';
  if (form.activity_level) form.activity_level.value = p.activity_level || 'moderate';
  const goalRadio = form.querySelector(`input[name=goal][value="${p.goal||'maintain'}"]`);
  if (goalRadio) goalRadio.checked = true;

  // Populate unit-aware weight/height fields
  window._weightKg = parseFloat(p.weight_kg) || 70;
  window._heightCm = parseFloat(p.height_cm) || 170;
  setWeightUnit(window._weightUnit || 'kg', true);
  setHeightUnit(window._heightUnit || 'cm', true);

  updateTDEEPreview(r.targets);
  document.getElementById('profile-modal-overlay').style.display = 'flex';
}

function updateTDEEPreview(t) {
  const prev = document.getElementById('tdee-preview');
  if (!prev || !t) return;
  prev.style.display = 'block';
  // Profile may be incomplete (missing weight/height/age/gender) → values
  // come back null; show a clean placeholder instead of the literal "null".
  const fmt = v => (v == null || Number.isNaN(Number(v))) ? '—' : `${v} kcal/day`;
  setText('prev-bmr',    fmt(t.bmr));
  setText('prev-tdee',   fmt(t.tdee));
  setText('prev-target', fmt(t.target_calories));
}

document.addEventListener('DOMContentLoaded', () => {
  // ── Unit state for profile form ──
  window._weightUnit = 'kg';
  window._heightUnit = 'cm';
  window._weightKg   = 70;
  window._heightCm   = 170;

  document.getElementById('profile-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const data = {
      name:           form.name?.value,
      age:            parseInt(form.age?.value),
      weight_kg:      window._weightKg || parseFloat(form.weight_kg?.value) || 70,
      height_cm:      window._heightCm || parseFloat(form.height_cm?.value) || 170,
      gender:         form.gender?.value,
      activity_level: form.activity_level?.value,
      goal:           form.querySelector('input[name=goal]:checked')?.value || 'maintain'
    };
    const r = await fetch('/api/food/profile', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
    const d = await r.json();
    if (d.success) {
      showToast('Profile saved! Calorie targets updated.', 'success');
      updateTDEEPreview(d.targets);
      foodTargets = d.targets;
      closeModal('profile-modal-overlay');
      updateSidebarUser();
      // Refresh all pages that show calorie data
      loadDashboard();
      loadFoodTracker();
      if (document.getElementById('view-fitness')?.classList.contains('active')) loadFitness();
    }
  });

  // Profile form live TDEE update
  document.querySelectorAll('#profile-form input, #profile-form select').forEach(el => {
    el.addEventListener('change', async () => {
      const form = document.getElementById('profile-form');
      if (!form) return;
      const data = {
        name: form.name?.value || 'User',
        age: parseInt(form.age?.value) || 25,
        weight_kg: parseFloat(form.weight_kg?.value) || 70,
        height_cm: parseFloat(form.height_cm?.value) || 170,
        gender: form.gender?.value || 'male',
        activity_level: form.activity_level?.value || 'moderate',
        goal: form.querySelector('input[name=goal]:checked')?.value || 'maintain'
      };
      // Preview without saving
      const r = await fetch('/api/food/profile').then(res => res.json()).catch(() => null);
      if (r) {
        // Quick local estimate using the TDEE formula
        const w=data.weight_kg, h=data.height_cm, a=data.age;
        const bmr = data.gender==='male' ? 88.362+(13.397*w)+(4.799*h)-(5.677*a) : 447.593+(9.247*w)+(3.098*h)-(4.330*a);
        const mult = {sedentary:1.2,light:1.375,moderate:1.55,active:1.725,very_active:1.9}[data.activity_level]||1.55;
        const tdee = bmr*mult;
        const adj  = {lose_fast:-500,lose:-250,maintain:0,gain:250,gain_fast:500}[data.goal]||0;
        updateTDEEPreview({ bmr:Math.round(bmr), tdee:Math.round(tdee), target_calories:Math.round(tdee+adj) });
      }
    });
  });

  // Init food date picker
  const fp = document.getElementById('food-date-picker');
  if (fp) fp.value = localToday();
});

// ── Helpers ───────────────────────────────────────────────────────────────────
const FOOD_EMOJI_CACHE = {};
function getFoodEmoji(foodId) {
  if (FOOD_EMOJI_CACHE[foodId]) return FOOD_EMOJI_CACHE[foodId];
  return '🍽️';
}

// Pre-populate cache from food DB on load
fetch('/api/food/db?limit=100').then(r => r.json()).then(d => {
  (d.foods||[]).forEach(f => { FOOD_EMOJI_CACHE[f.id] = f.emoji || '🍽️'; });
}).catch(()=>{});

// ════════════════════════════════════════════════════════════
// PROFILE UNIT TOGGLES — kg/lbs, cm/ft-in
// ════════════════════════════════════════════════════════════

function setWeightUnit(unit, suppressLiveTDEE) {
  window._weightUnit = unit;
  // Toggle button states
  document.querySelectorAll('#weight-unit-toggle .unit-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.unit === unit);
  });
  const input = document.getElementById('weight-display-input');
  const hint  = document.getElementById('weight-unit-hint');
  if (!input) return;
  if (unit === 'kg') {
    input.step = '0.1';
    input.placeholder = '70';
    input.value = window._weightKg ? window._weightKg.toFixed(1) : '';
    if (hint) hint.textContent = `= ${window._weightKg ? (window._weightKg * 2.20462).toFixed(1) : '—'} lbs`;
  } else {
    const lbs = window._weightKg ? (window._weightKg * 2.20462) : 154;
    input.step = '0.5';
    input.placeholder = '154';
    input.value = lbs.toFixed(1);
    if (hint) hint.textContent = `= ${window._weightKg ? window._weightKg.toFixed(1) : '—'} kg`;
  }
  // Update hidden kg field
  const hidden = document.getElementById('weight-kg-hidden');
  if (hidden) hidden.value = window._weightKg || 70;
  if (!suppressLiveTDEE) triggerLiveTDEEUpdate();
}

function syncWeightInput(val) {
  const v = parseFloat(val);
  if (!v || isNaN(v)) return;
  if (window._weightUnit === 'kg') {
    window._weightKg = v;
    const hint = document.getElementById('weight-unit-hint');
    if (hint) hint.textContent = `= ${(v * 2.20462).toFixed(1)} lbs`;
  } else {
    window._weightKg = v / 2.20462;
    const hint = document.getElementById('weight-unit-hint');
    if (hint) hint.textContent = `= ${window._weightKg.toFixed(1)} kg`;
  }
  const hidden = document.getElementById('weight-kg-hidden');
  if (hidden) hidden.value = window._weightKg.toFixed(2);
  triggerLiveTDEEUpdate();
}

function setHeightUnit(unit, suppressLiveTDEE) {
  window._heightUnit = unit;
  document.querySelectorAll('#height-unit-toggle .unit-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.unit === unit);
  });
  const cmInput   = document.getElementById('height-cm-input');
  const ftinWrap  = document.getElementById('height-ftin-inputs');
  const ftInput   = document.getElementById('height-ft-input');
  const inInput   = document.getElementById('height-in-input');
  const hint      = document.getElementById('height-unit-hint');
  const cm        = window._heightCm || 170;

  if (unit === 'cm') {
    if (cmInput)  { cmInput.style.display = ''; cmInput.value = cm.toFixed(0); }
    if (ftinWrap) ftinWrap.style.display = 'none';
    if (hint)     hint.textContent = `= ${cmToFtIn(cm)}`;
  } else {
    if (cmInput)  cmInput.style.display = 'none';
    if (ftinWrap) ftinWrap.style.display = 'flex';
    const totalIn = cm / 2.54;
    const ft = Math.floor(totalIn / 12);
    const inches = Math.round(totalIn % 12);
    if (ftInput)  ftInput.value = ft;
    if (inInput)  inInput.value = inches;
    if (hint)     hint.textContent = `= ${cm.toFixed(0)} cm`;
  }
  const hidden = document.getElementById('height-cm-hidden');
  if (hidden) hidden.value = cm.toFixed(1);
  if (!suppressLiveTDEE) triggerLiveTDEEUpdate();
}

function syncHeightInput() {
  const unit = window._heightUnit || 'cm';
  if (unit === 'cm') {
    const v = parseFloat(document.getElementById('height-cm-input')?.value);
    if (v && !isNaN(v)) {
      window._heightCm = v;
      const hint = document.getElementById('height-unit-hint');
      if (hint) hint.textContent = `= ${cmToFtIn(v)}`;
    }
  } else {
    const ft = parseFloat(document.getElementById('height-ft-input')?.value) || 0;
    const inches = parseFloat(document.getElementById('height-in-input')?.value) || 0;
    window._heightCm = (ft * 12 + inches) * 2.54;
    const hint = document.getElementById('height-unit-hint');
    if (hint) hint.textContent = `= ${window._heightCm.toFixed(0)} cm`;
  }
  const hidden = document.getElementById('height-cm-hidden');
  if (hidden) hidden.value = (window._heightCm || 170).toFixed(1);
  triggerLiveTDEEUpdate();
}

function cmToFtIn(cm) {
  const totalIn = cm / 2.54;
  const ft = Math.floor(totalIn / 12);
  const inches = Math.round(totalIn % 12);
  return `${ft}′${inches}″`;
}

function triggerLiveTDEEUpdate() {
  const form = document.getElementById('profile-form');
  if (!form) return;
  const w = window._weightKg || 70;
  const h = window._heightCm || 170;
  const a = parseInt(form.age?.value) || 25;
  const g = form.gender?.value || 'male';
  const act = form.activity_level?.value || 'moderate';
  const goal = form.querySelector('input[name=goal]:checked')?.value || 'maintain';
  const bmr = g === 'male'
    ? 88.362 + (13.397*w) + (4.799*h) - (5.677*a)
    : 447.593 + (9.247*w) + (3.098*h) - (4.330*a);
  const mult = {sedentary:1.2,light:1.375,moderate:1.55,active:1.725,very_active:1.9}[act]||1.55;
  const tdee = bmr * mult;
  const adj  = {lose_fast:-500,lose:-250,maintain:0,gain:250,gain_fast:500}[goal]||0;
  updateTDEEPreview({ bmr:Math.round(bmr), tdee:Math.round(tdee), target_calories:Math.round(tdee+adj) });
}

// ════════════════════════════════════════════════════════════
// THOUGHTS — Daily Journal
// ════════════════════════════════════════════════════════════

// The app's mood vocabulary — one list, because there's one `mood` column.
//
// It grew two: the journal offered 8 categorical moods while the check-in, the
// quick-log sheet and the push actions used a 5-point scale whose lowest rung,
// `terrible`, existed nowhere in here. So a day logged as "Rough" rendered a
// literal "undefined" in the week dots, and read as plain 😐 Neutral
// everywhere that had a fallback — the app quietly downgrading someone's worst
// day to an average one. `terrible` is a real thing a user told us; it belongs
// in the vocabulary that displays them.
//
// Anything rendering a mood must go through here, and must tolerate a key it
// doesn't know rather than printing `undefined` at someone.
const MOOD_EMOJI = {
  terrible:'😩', sad:'😞', neutral:'😐', happy:'😊', excited:'🤩',
  calm:'😌', anxious:'😰', tired:'😴', angry:'😤'
};
const MOOD_COLOR = {
  terrible:'#DC2626', sad:'#3B82F6', neutral:'#4F8D74', happy:'#22C55E',
  excited:'#F59E0B', calm:'#06B6D4', anxious:'#8B5CF6', tired:'#9CA3AF',
  angry:'#EF4444'
};
function moodEmoji(mood) { return MOOD_EMOJI[mood] || '😐'; }
function moodColor(mood) { return MOOD_COLOR[mood] || '#4F8D74'; }

let currentThoughtsDate = localToday();
let selectedMood = 'neutral';
let editingThoughtId = null;

async function loadThoughts(dateStr) {
  if (dateStr) currentThoughtsDate = dateStr;
  const picker = document.getElementById('thoughts-date-picker');
  if (picker && !picker.value) picker.value = currentThoughtsDate;

  const r = await fetch(`/api/thoughts/${currentThoughtsDate}`).then(r => r.json()).catch(() => null);
  if (!r) return;

  // Update quota
  const quotaEl = document.getElementById('thoughts-quota');
  const usedEl  = document.getElementById('thoughts-used');
  if (quotaEl && usedEl) {
    usedEl.textContent = r.count;
    quotaEl.classList.toggle('full', r.remaining === 0);
  }

  // Update title
  const titleEl = document.getElementById('thoughts-feed-title');
  if (titleEl) {
    const d = new Date(currentThoughtsDate + 'T12:00:00');
    const today = localToday();
    titleEl.textContent = currentThoughtsDate === today
      ? "Today's thoughts"
      : d.toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' });
  }

  // Disable textarea if limit reached
  const ta  = document.getElementById('thought-textarea');
  const btn = document.getElementById('thought-submit-btn');
  if (ta)  ta.disabled = r.remaining === 0;
  if (ta && r.remaining === 0) ta.placeholder = "You've reached today's limit of 10 thoughts.";

  // Render thoughts
  renderThoughtsList(r.thoughts);

  // Week mood dots
  loadWeekMoods();
}

function renderThoughtsList(thoughts) {
  const el = document.getElementById('thoughts-list');
  if (!el) return;
  if (!thoughts || thoughts.length === 0) {
    el.innerHTML = `<div class="thoughts-empty">
      <div class="thoughts-empty-icon">💭</div>
      <div class="thoughts-empty-text">No thoughts yet</div>
      <div class="thoughts-empty-sub">Write your first one on the left</div>
    </div>`;
    return;
  }
  el.innerHTML = thoughts.map(t => {
    const time = new Date(t.created_at).toLocaleTimeString('en-US', { hour:'numeric', minute:'2-digit' });
    const mood = t.mood || 'neutral';
    return `<div class="thought-card" data-mood="${mood}" data-id="${t.id}">
      <div class="thought-card-header">
        <div class="thought-meta">
          <span class="thought-mood-badge">${moodEmoji(mood)}</span>
          <span class="thought-time">${time}</span>
        </div>
        <div class="thought-card-actions">
          <button class="thought-action-btn" data-ev-click="startEditThought('${t.id}')" title="Edit">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="thought-action-btn del" data-ev-click="deleteThought('${t.id}')" title="Delete">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>
      <div class="thought-content" id="tc-${t.id}">${escHtml(t.content)}</div>
      <div class="thought-edit-wrap" id="te-${t.id}" style="display:none">
        <textarea class="thought-edit-area" id="tea-${t.id}">${escHtml(t.content)}</textarea>
        <div class="thought-edit-actions">
          <button class="btn-outline" style="padding:5px 12px;font-size:12px" data-ev-click="cancelEditThought('${t.id}')">Cancel</button>
          <button class="btn-primary" style="padding:5px 12px;font-size:12px" data-ev-click="saveEditThought('${t.id}','${mood}')">Save</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function loadWeekMoods() {
  const r = await fetch('/api/thoughts/range/week').then(r => r.json()).catch(() => []);
  const el = document.getElementById('thoughts-week-moods');
  if (!el || !r.length) return;
  // Get one mood per day (most recent)
  const byDay = {};
  r.forEach(t => { if (!byDay[t.date_key]) byDay[t.date_key] = t.mood; });
  const days = ['M','T','W','T','F','S','S'];
  const today = new Date();
  el.innerHTML = Array.from({length:7}, (_,i) => {
    const d = new Date(today);
    d.setDate(d.getDate() - (6-i));
    const key = d.toISOString().split('T')[0];
    const mood = byDay[key];
    return mood
      ? `<div class="week-mood-dot" title="${key}"><div class="week-mood-emoji">${moodEmoji(mood)}</div><div class="week-mood-day">${days[i]}</div></div>`
      : `<div class="week-mood-dot"><div class="week-mood-emoji" style="opacity:.18">○</div><div class="week-mood-day" style="opacity:.3">${days[i]}</div></div>`;
  }).join('');
}

function selectMood(mood) {
  selectedMood = mood;
  document.querySelectorAll('.mood-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.mood === mood);
  });
}

function updateThoughtCounter(ta) {
  const len = ta.value.length;
  const el  = document.getElementById('thought-char-count');
  const btn = document.getElementById('thought-submit-btn');
  if (el) {
    el.textContent = `${len} / 1000`;
    el.classList.toggle('near', len > 800);
    el.classList.toggle('full', len >= 1000);
  }
  if (btn) btn.disabled = len === 0;
}

async function submitThought() {
  const ta = document.getElementById('thought-textarea');
  const content = ta?.value?.trim();
  if (!content) return;
  const btn = document.getElementById('thought-submit-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  const r = await fetch('/api/thoughts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ content, mood: selectedMood, date_key: currentThoughtsDate })
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    ta.value = '';
    updateThoughtCounter(ta);
    showToast(`Thought saved ${moodEmoji(selectedMood)}`, 'success');
    loadThoughts();
  } else {
    showToast(r?.error || 'Failed to save', 'error');
  }
  if (btn) { btn.textContent = 'Save thought'; }
}

function startEditThought(id) {
  document.getElementById(`tc-${id}`)?.classList.add('editing');
  const wrap = document.getElementById(`te-${id}`);
  if (wrap) wrap.style.display = 'block';
  document.getElementById(`tea-${id}`)?.focus();
}

function cancelEditThought(id) {
  document.getElementById(`tc-${id}`)?.classList.remove('editing');
  const wrap = document.getElementById(`te-${id}`);
  if (wrap) wrap.style.display = 'none';
}

async function saveEditThought(id, mood) {
  const ta = document.getElementById(`tea-${id}`);
  const content = ta?.value?.trim();
  if (!content) return;
  const r = await fetch(`/api/thoughts/${id}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ content, mood })
  }).then(r => r.json()).catch(() => null);
  if (r?.success) { showToast('Thought updated', 'success'); loadThoughts(); }
}

function deleteThought(id) {
  undoable('Deleting thought…', async () => {
    await fetch(`/api/thoughts/${id}`, { method: 'DELETE' });
    loadThoughts();
  });
}

function thoughtsDateShift(delta) {
  const d = new Date(currentThoughtsDate + 'T12:00:00');
  d.setDate(d.getDate() + delta);
  const today = new Date();
  if (d > today) return;
  currentThoughtsDate = d.toISOString().split('T')[0];
  const picker = document.getElementById('thoughts-date-picker');
  if (picker) picker.value = currentThoughtsDate;
  loadThoughts();
}

// ════════════════════════════════════════════════════════════
// TO-DO LIST
// ════════════════════════════════════════════════════════════

let allTodos = [];
let todoFilter = 'all';
let selectedTodoPriority = 'medium';
let editingTodoId = null;

async function loadTodos() {
  const r = await fetch('/api/todos').then(r => r.json()).catch(() => null);
  if (!r) return;
  allTodos = r.todos || [];

  // Stats
  const pending = allTodos.filter(t => t.status === 'pending');
  const done    = allTodos.filter(t => t.status === 'done');
  const today   = localToday();
  const overdue = pending.filter(t => t.due_date && t.due_date < today);
  const total   = allTodos.length;
  const donePct = total > 0 ? Math.round((done.length / total) * 100) : 0;

  setText('td-pending-count', pending.length);
  setText('td-done-count',    done.length);
  setText('td-overdue-count', overdue.length);
  setText('td-progress-label', `${donePct}% done`);
  const fill = document.getElementById('td-progress-fill');
  if (fill) fill.style.width = donePct + '%';

  // Nav badge
  const badge = document.getElementById('nav-todo-badge');
  if (badge) {
    if (pending.length > 0) { badge.textContent = pending.length; badge.style.display = 'inline-block'; }
    else badge.style.display = 'none';
  }

  renderTodos();
}

function renderTodos() {
  const today = localToday();
  const sort  = document.getElementById('todo-sort')?.value || 'priority';
  const PORD  = { high: 0, medium: 1, low: 2 };

  let items = [...allTodos];

  // Apply filter
  if (todoFilter !== 'all') items = items.filter(t => t.status === todoFilter);

  // Sort
  items.sort((a, b) => {
    if (sort === 'priority') return (PORD[a.priority]||1) - (PORD[b.priority]||1);
    if (sort === 'due_date') return (a.due_date||'9999') < (b.due_date||'9999') ? -1 : 1;
    return a.created_at < b.created_at ? 1 : -1;
  });

  const pending = items.filter(t => t.status === 'pending');
  const done    = items.filter(t => t.status === 'done');

  const pendSec = document.getElementById('todo-pending-section');
  const doneSec = document.getElementById('todo-done-section');
  const pendList= document.getElementById('todo-pending-list');
  const doneList= document.getElementById('todo-done-list');

  setText('td-pend-count-label', pending.length);
  setText('td-done-count-label', done.length);

  // Show/hide sections based on filter
  if (pendSec) pendSec.style.display = (todoFilter === 'done') ? 'none' : '';
  if (doneSec) doneSec.style.display = (todoFilter === 'pending') ? 'none' : '';

  if (pendList) {
    if (pending.length === 0) {
      pendList.innerHTML = `<div class="todo-empty">
        <div class="todo-empty-icon">🎉</div>
        <div class="todo-empty-text">All clear!</div>
        <div class="todo-empty-sub">No pending tasks. Great work!</div>
      </div>`;
    } else {
      pendList.innerHTML = pending.map(t => renderTodoCard(t, today)).join('');
    }
  }

  if (doneList) {
    if (done.length === 0) {
      doneList.innerHTML = `<div class="todo-empty"><div class="todo-empty-icon">📋</div><div class="todo-empty-text">Nothing completed yet</div></div>`;
    } else {
      doneList.innerHTML = done.map(t => renderTodoCard(t, today)).join('');
    }
  }
}

function renderTodoCard(t, today) {
  const isDone    = t.status === 'done';
  const isOverdue = !isDone && t.due_date && t.due_date < today;
  const PLABEL    = { high:'🔴 High', medium:'🟡 Medium', low:'🟢 Low' };

  let metaHtml = `<span class="todo-badge pri-${t.priority}">${PLABEL[t.priority]||'Medium'}</span>`;
  if (t.due_date) {
    const dueLbl = t.due_date === today ? 'Due today' : t.due_date < today ? `Overdue (${t.due_date})` : `Due ${t.due_date}`;
    metaHtml += `<span class="todo-badge ${isOverdue?'overdue':'due'}">📅 ${dueLbl}</span>`;
  }
  if (t.reminder_at) {
    const rt = new Date(t.reminder_at).toLocaleString('en-US', {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
    metaHtml += `<span class="todo-badge reminder">🔔 ${rt}</span>`;
  }

  return `<div class="todo-card pri-${t.priority} ${isDone?'done':''}" data-id="${t.id}">
    <div class="todo-checkbox ${isDone?'checked':''}" data-ev-click="toggleTodo('${t.id}')"></div>
    <div class="todo-content">
      <div class="todo-title">${escHtml(t.title)}</div>
      ${t.notes ? `<div class="todo-notes">${escHtml(t.notes)}</div>` : ''}
      <div class="todo-meta-row">${metaHtml}</div>
    </div>
    <div class="todo-card-actions">
      ${!isDone ? `<button class="todo-act-btn" data-ev-click="openEditTodo('${t.id}')" title="Edit">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      </button>` : ''}
      <button class="todo-act-btn del" data-ev-click="deleteTodo('${t.id}')" title="Delete">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
      </button>
    </div>
  </div>`;
}

function setTodoFilter(f) {
  todoFilter = f;
  document.querySelectorAll('.todo-filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === f);
  });
  renderTodos();
}

function openTodoModal(editId) {
  editingTodoId = editId || null;
  selectedTodoPriority = 'medium';

  const title = document.getElementById('todo-modal-title');
  const titleInput = document.getElementById('todo-title-input');
  const notesInput = document.getElementById('todo-notes-input');
  const dueInput   = document.getElementById('todo-due-input');
  const reminderToggle = document.getElementById('todo-reminder-toggle');
  const reminderInput  = document.getElementById('todo-reminder-input');
  const reminderPicker = document.getElementById('todo-reminder-picker');
  const editIdEl = document.getElementById('todo-edit-id');

  if (editId) {
    const todo = allTodos.find(t => t.id === editId);
    if (!todo) return;
    if (title) title.textContent = 'Edit Task';
    if (titleInput) titleInput.value = todo.title;
    if (notesInput) notesInput.value = todo.notes || '';
    if (dueInput)   dueInput.value   = todo.due_date || '';
    selectedTodoPriority = todo.priority || 'medium';
    if (editIdEl) editIdEl.value = editId;
    if (todo.reminder_at && reminderToggle && reminderInput && reminderPicker) {
      reminderToggle.checked = true;
      reminderPicker.style.display = 'block';
      reminderInput.value = todo.reminder_at.slice(0,16);
    }
  } else {
    if (title) title.textContent = 'Add Task';
    if (titleInput) titleInput.value = '';
    if (notesInput) notesInput.value = '';
    if (dueInput)   dueInput.value   = '';
    if (editIdEl)   editIdEl.value   = '';
    if (reminderToggle) reminderToggle.checked = false;
    if (reminderPicker) reminderPicker.style.display = 'none';
    if (reminderInput)  reminderInput.value = '';
  }

  // Reset priority picker
  document.querySelectorAll('.todo-pri-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.p === selectedTodoPriority);
  });

  document.getElementById('todo-modal-overlay').style.display = 'flex';
  titleInput?.focus();
}

function openEditTodo(id) { openTodoModal(id); }

function selectTodoPriority(p) {
  selectedTodoPriority = p;
  document.querySelectorAll('.todo-pri-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.p === p);
  });
}

function toggleReminderPicker(show) {
  const picker = document.getElementById('todo-reminder-picker');
  if (picker) picker.style.display = show ? 'block' : 'none';
  if (show) {
    const inp = document.getElementById('todo-reminder-input');
    if (inp && !inp.value) {
      // Default to 1 hour from now
      const d = new Date();
      d.setHours(d.getHours() + 1, 0, 0, 0);
      inp.value = d.toISOString().slice(0,16);
    }
  }
}

async function saveTodo() {
  const titleInput = document.getElementById('todo-title-input');
  const title = titleInput?.value?.trim();
  if (!title) { titleInput?.focus(); showToast('Please enter a title', 'error'); return; }

  const editId = document.getElementById('todo-edit-id')?.value;
  const reminderOn = document.getElementById('todo-reminder-toggle')?.checked;
  const data = {
    title,
    notes:       document.getElementById('todo-notes-input')?.value || '',
    priority:    selectedTodoPriority,
    due_date:    document.getElementById('todo-due-input')?.value || null,
    reminder_at: reminderOn ? (document.getElementById('todo-reminder-input')?.value || null) : null,
    tags: []
  };

  const url    = editId ? `/api/todos/${editId}` : '/api/todos';
  const method = editId ? 'PUT' : 'POST';
  const r = await fetch(url, {
    method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    showToast(editId ? 'Task updated!' : 'Task added!', 'success');
    closeModal('todo-modal-overlay');
    loadTodos();
    // Schedule browser notification if reminder set
    if (data.reminder_at && reminderOn) {
      scheduleTodoBrowserNotif(r.todo, data.reminder_at);
    }
  } else {
    showToast('Failed to save task', 'error');
  }
}

async function toggleTodo(id) {
  const r = await fetch(`/api/todos/${id}/toggle`, { method:'POST' }).then(r => r.json());
  if (r.success) {
    const todo = allTodos.find(t => t.id === id);
    if (todo) {
      const msg = r.todo.status === 'done' ? `✅ "${todo.title}" completed!` : `↩️ Moved back to pending`;
      showToast(msg, r.todo.status === 'done' ? 'success' : 'info');
    }
    loadTodos();
  }
}

function deleteTodo(id) {
  const todo = allTodos.find(t => t.id === id);
  undoable(`Deleting "${todo?.title || 'task'}"…`, async () => {
    await fetch(`/api/todos/${id}`, { method:'DELETE' });
    loadTodos();
  });
}

// ── Reminder notifications ──────────────────────────────────────────────────

function scheduleTodoBrowserNotif(todo, reminderAt) {
  if (Notification.permission !== 'granted') return;
  const ms = new Date(reminderAt) - Date.now();
  if (ms <= 0 || ms > 86400000) return; // only schedule within 24h
  setTimeout(() => {
    new Notification('📋 Arogo Reminder', {
      body: todo.title,
      icon: '/static/favicon.ico',
      tag:  `todo-${todo.id}`
    });
  }, ms);
}

function scheduleTodoReminderChecks() {
  // Poll the server every 60 seconds for due reminders
  setInterval(async () => {
    if (Notification.permission !== 'granted') return;
    const r = await fetch('/api/todos/reminders/due').then(r => r.json()).catch(() => null);
    if (!r?.reminders?.length) return;
    r.reminders.forEach(todo => {
      new Notification('📋 Arogo Reminder', {
        body: todo.title + (todo.notes ? `\n${todo.notes}` : ''),
        icon: '/static/favicon.ico',
        tag:  `todo-${todo.id}`
      });
    });
    // Refresh badge
    loadTodos();
  }, 60000);
}

// ════════════════════════════════════════════════════════════
// WELLNESS SYNC — updates dashboard strip from all sources
// ════════════════════════════════════════════════════════════

async function loadWellnessStrip() {
  const today = localToday();

  // Fetch hydration directly — separate call ensures freshest data
  const [hyd, r] = await Promise.all([
    fetch(`/api/hydration/${today}`, {cache: 'no-store'}).then(r => r.json()).catch(() => null),
    fetch('/api/wellness/today', {cache: 'no-store'}).then(r => r.json()).catch(() => null),
  ]);

  // Hydration — use direct fetch (most accurate)
  if (hyd) {
    const hydEl = document.getElementById('dws-hydration');
    if (hydEl) hydEl.textContent = `${hyd.total_ml || 0} ml`;
    const hBar = document.getElementById('dws-hydration-bar');
    if (hBar) hBar.style.width = (hyd.pct || 0) + '%';
    if (hyd.usual_ml) setUsualWaterMl(hyd.usual_ml);   // quick-log = their real glass
  }

  if (!r) return;

  // Sleep
  const s = r.sleep;
  const sleepEl = document.getElementById('dws-sleep');
  const sleepQ  = document.getElementById('dws-sleep-quality');
  if (sleepEl) sleepEl.textContent = s ? `${s.duration_h}h` : 'Not logged';
  if (sleepQ && s) {
    const qMap = { 1:'😩', 2:'😕', 3:'😐', 4:'😊', 5:'😴' };
    sleepQ.textContent = qMap[s.quality] || '';
  }

  // Habits
  const hb = r.habits;
  setText('dws-habits', hb.total > 0 ? `${hb.done} / ${hb.total}` : 'No habits');
  const hbBadge = document.getElementById('dws-habits-badge');
  if (hbBadge && hb.total > 0) {
    hbBadge.textContent = hb.done === hb.total ? '🎉 All done!' : `${hb.total - hb.done} left`;
    hbBadge.style.background = hb.done === hb.total ? '#DCFCE7' : 'var(--teal-50)';
    hbBadge.style.color = hb.done === hb.total ? '#468A5B' : 'var(--teal-700)';
  }

  // Symptoms
  const symEl = document.getElementById('dws-symptoms');
  if (symEl) symEl.textContent = r.symptoms > 0 ? `${r.symptoms} today` : 'None today';
}

// ════════════════════════════════════════════════════════════
// WELLNESS TABS (Thoughts page)
// ════════════════════════════════════════════════════════════

let sleepQuality = 3;
let selectedVitalType = 'blood_pressure';
let selectedHabitColor = '#4F8D74';

function switchWellnessTab(tab) {
  document.querySelectorAll('.wellness-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.wellness-tab-content').forEach(c => {
    const id = c.id?.replace('wellness-tab-', '');
    c.style.display = c.id === `wellness-tab-${tab}` ? '' : 'none';
  });
  if (tab === 'sleep') loadSleepData();
  if (tab === 'body')  loadBodyMetrics();
  if (tab === 'mood')  loadMoodAnalytics();
}

// ════════════════════════════════════════════════════════════
// SLEEP TRACKER
// ════════════════════════════════════════════════════════════

function selectSleepQ(q) {
  sleepQuality = q;
  document.querySelectorAll('.sleep-q-tile, .sleep-q-btn').forEach(b => b.classList.toggle('selected', +b.dataset.q === q));
}

function initSleepDefaults() {
  const now = new Date();
  const wake = new Date(); wake.setHours(7, 0, 0, 0);
  const bed  = new Date(); bed.setDate(bed.getDate() - 1); bed.setHours(23, 0, 0, 0);
  const fmt = d => d.toISOString().slice(0,16);
  const bi = document.getElementById('sleep-bedtime');
  const wi = document.getElementById('sleep-waketime');
  if (bi && !bi.value) bi.value = fmt(bed);
  if (wi && !wi.value) wi.value = fmt(wake);
}

function previewSleepDuration() {
  const bed  = document.getElementById('sleep-bedtime')?.value;
  const wake = document.getElementById('sleep-waketime')?.value;
  const prev = document.getElementById('sleep-duration-preview');
  const text = document.getElementById('sleep-duration-text');
  if (!bed || !wake || !prev || !text) return;
  try {
    let bedDt  = new Date(bed);
    let wakeDt = new Date(wake);
    if (wakeDt <= bedDt) wakeDt = new Date(wakeDt.getTime() + 24*3600*1000);
    const hrs = (wakeDt - bedDt) / 3600000;
    const h   = Math.floor(hrs);
    const m   = Math.round((hrs - h) * 60);
    text.textContent = `😴 ${h}h ${m}m of sleep`;
    prev.style.display = 'block';
  } catch(e) { prev.style.display = 'none'; }
}

async function saveSleepLog() {
  const bed  = document.getElementById('sleep-bedtime')?.value;
  const wake = document.getElementById('sleep-waketime')?.value;
  if (!bed || !wake) { showToast('Set both bedtime and wake time', 'error'); return; }
  const r = await fetch('/api/sleep', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ bedtime: bed, wake_time: wake, quality: sleepQuality,
                           notes: document.getElementById('sleep-notes')?.value || '' })
  }).then(r => r.json());
  if (r.success) {
    showToast(`Sleep logged — ${r.sleep.duration_h}h`, 'success');
    loadSleepData();
    loadWellnessStrip();
  } else showToast(r.error || 'Failed', 'error');
}

async function loadSleepData() {
  const r = await fetch('/api/sleep?days=14').then(r => r.json()).catch(() => []);
  const listEl  = document.getElementById('sleep-history-list');
  const statsEl = document.getElementById('sleep-stats-panel');
  if (!listEl) return;
  initSleepDefaults();
  if (!r.length) {
    listEl.innerHTML = '<div class="todo-empty"><div class="todo-empty-icon">🌙</div><div class="todo-empty-text">No sleep logged yet</div></div>';
    return;
  }
  const avg  = (r.reduce((s,l) => s+l.duration_h, 0) / r.length).toFixed(1);
  const best = Math.max(...r.map(l => l.duration_h)).toFixed(1);
  const QMAP = {1:'😩',2:'😕',3:'😐',4:'😊',5:'😴'};
  const QCLS = {1:'poor',2:'poor',3:'ok',4:'good',5:'great'};
  if (statsEl) {
    statsEl.innerHTML = `
      <div class="sleep-chip"><div class="sleep-chip-val">${avg}h</div><div class="sleep-chip-label">Avg sleep</div></div>
      <div class="sleep-chip-sep"></div>
      <div class="sleep-chip"><div class="sleep-chip-val">${best}h</div><div class="sleep-chip-label">Best night</div></div>
      <div class="sleep-chip-sep"></div>
      <div class="sleep-chip"><div class="sleep-chip-val">${r.length}</div><div class="sleep-chip-label">Entries</div></div>`;
  }
  listEl.innerHTML = r.map(s => {
    const pct = Math.min((s.duration_h / 9) * 100, 100).toFixed(0);
    return `<div class="sleep-log-row">
      <div class="sleep-log-date">${s.date_key.slice(5)}</div>
      <div class="sleep-log-dur">${s.duration_h}h</div>
      <div class="sleep-bar-col"><div class="sleep-bar-fill ${QCLS[s.quality]||'ok'}" style="width:${pct}%"></div></div>
      <div class="sleep-log-qual">${QMAP[s.quality]||'😐'}</div>
      <button class="todo-act-btn del" data-ev-click="delSleep('${s.id}')">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
      </button>
    </div>`;
  }).join('');
}

async function delSleep(id) {
  await fetch(`/api/sleep/${id}`, {method:'DELETE'});
  refreshSleep();   // recompute the average now that a night is gone
}

// ════════════════════════════════════════════════════════════
// BODY METRICS
// ════════════════════════════════════════════════════════════

async function saveBodyMetric() {
  const w = parseFloat(document.getElementById('body-weight')?.value);
  if (!w) { showToast('Weight is required', 'error'); return; }
  const r = await fetch('/api/body-metrics', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      weight_kg:    w,
      body_fat_pct: parseFloat(document.getElementById('body-fat')?.value) || null,
      waist_cm:     parseFloat(document.getElementById('body-waist')?.value) || null,
      notes:        document.getElementById('body-notes')?.value || '',
      date_key:     document.getElementById('body-date-input')?.value || localToday()
    })
  }).then(r => r.json());
  if (r.success) {
    showToast(`Metrics saved — BMI: ${r.metric.bmi || '—'}`, 'success');
    loadBodyMetrics();
    loadDashboard();
  }
}

async function loadBodyMetrics() {
  const r = await fetch('/api/body-metrics?days=30').then(r => r.json()).catch(() => []);
  const el = document.getElementById('body-metrics-chart');
  // Init date
  const di = document.getElementById('body-date-input');
  if (di && !di.value) di.value = localToday();
  if (!el) return;
  if (!r.length) {
    el.innerHTML = '<div class="todo-empty"><div class="todo-empty-icon">📊</div><div class="todo-empty-text">No metrics logged yet</div></div>';
    return;
  }
  el.innerHTML = r.slice().reverse().map(m => `
    <div class="body-metric-row">
      <div class="body-metric-date">${m.date_key.slice(5)}</div>
      <div class="body-metric-weight">${m.weight_kg ? m.weight_kg+'kg' : '—'}</div>
      <div class="body-metric-chips">
        ${m.bmi         ? `<span class="body-chip body-chip--bmi">BMI ${m.bmi}</span>` : ''}
        ${m.body_fat_pct? `<span class="body-chip body-chip--fat">${m.body_fat_pct}% fat</span>` : ''}
        ${m.waist_cm    ? `<span class="body-chip body-chip--waist">${m.waist_cm}cm</span>` : ''}
      </div>
    </div>`).join('');
}

// ════════════════════════════════════════════════════════════
// MOOD ANALYTICS
// ════════════════════════════════════════════════════════════

async function loadMoodAnalytics() {
  const r = await fetch('/api/thoughts/range/week').then(r => r.json()).catch(() => []);
  const el = document.getElementById('mood-analytics-content');
  if (!el) return;
  if (!r.length) {
    el.innerHTML = '<div class="todo-empty" style="padding:60px 0"><div class="todo-empty-icon">🎭</div><div class="todo-empty-text">Log thoughts to see mood analytics</div></div>';
    return;
  }
  // Count moods
  const counts = {};
  r.forEach(t => { counts[t.mood] = (counts[t.mood]||0) + 1; });
  const total = r.length;
  const sorted = Object.entries(counts).sort((a,b) => b[1]-a[1]);
  const maxCount = sorted[0]?.[1] || 1;

  const distHtml = sorted.map(([mood, count]) => {
    const pct = Math.round(count/maxCount*100);
    return `<div class="mood-dist-row">
      <div class="mood-dist-emoji">${moodEmoji(mood)}</div>
      <div class="mood-dist-bar-track"><div class="mood-dist-bar" style="width:${pct}%;background:${moodColor(mood)}"></div></div>
      <div class="mood-dist-count">${count}</div>
    </div>`;
  }).join('');

  el.innerHTML = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div class="panel">
      <div class="panel-header"><h2 class="panel-title">Mood Distribution (7 days)</h2></div>
      <div style="padding:16px"><div class="mood-dist-chart">${distHtml}</div></div>
    </div>
    <div class="panel">
      <div class="panel-header"><h2 class="panel-title">Insights</h2></div>
      <div style="padding:16px;display:flex;flex-direction:column;gap:10px">
        <div style="font-size:13px;color:var(--gray-600)">📝 <strong>${total}</strong> thoughts logged this week</div>
        <div style="font-size:13px;color:var(--gray-600)">🏆 Most common mood: ${sorted[0] ? `<strong>${moodEmoji(sorted[0][0])} ${sorted[0][0]}</strong>` : '—'}</div>
        <div style="font-size:13px;color:var(--gray-600)">🌟 Positive thoughts: <strong>${(counts['happy']||0)+(counts['excited']||0)+(counts['calm']||0)}</strong></div>
        <div style="font-size:13px;color:var(--gray-600)">💙 Challenging days: <strong>${(counts['sad']||0)+(counts['anxious']||0)+(counts['angry']||0)}</strong></div>
      </div>
    </div>
  </div>`;
}

// ════════════════════════════════════════════════════════════
// HABITS
// ════════════════════════════════════════════════════════════

function toggleRefillSection() {
  const el = document.getElementById('refill-fields');
  const ch = document.getElementById('refill-chevron');
  if (!el) return;
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  if (ch) ch.style.transform = open ? 'rotate(-90deg)' : 'rotate(0deg)';
}

function openHabitModal() {
  document.getElementById('habit-name-input').value = '';
  document.getElementById('habit-emoji-input').value = '⭐';
  selectedHabitColor = '#4F8D74';
  document.querySelectorAll('.habit-color-btn').forEach(b => b.classList.toggle('selected', b.dataset.color === selectedHabitColor));
  document.getElementById('habit-modal-overlay').style.display = 'flex';
  setTimeout(() => document.getElementById('habit-name-input')?.focus(), 50);
}

function fillHabitPreset(name, emoji, color) {
  document.getElementById('habit-name-input').value = name;
  document.getElementById('habit-emoji-input').value = emoji;
  selectHabitColor(color);
}

function selectHabitColor(color) {
  selectedHabitColor = color;
  document.querySelectorAll('.habit-color-btn').forEach(b => b.classList.toggle('selected', b.dataset.color === color));
}

async function saveHabit() {
  const name = document.getElementById('habit-name-input')?.value?.trim();
  if (!name) { showToast('Enter a habit name', 'error'); return; }
  const r = await fetch('/api/habits', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name, emoji: document.getElementById('habit-emoji-input')?.value || '⭐', color: selectedHabitColor })
  }).then(r => r.json());
  if (r.success) {
    showToast('Habit created!', 'success');
    closeModal('habit-modal-overlay');
    loadHabits();
    loadWellnessStrip();
  }
}

async function loadHabits() {
  const r = await fetch('/api/habits').then(r => r.json()).catch(() => ({habits:[]}));
  const today  = r.date || localToday();
  const habits = r.habits || [];

  // ── Update page subtitle with today's date ──
  const sub = document.getElementById('habits-date-label');
  if (sub) sub.textContent = new Date(today + 'T12:00:00').toLocaleDateString('en-US',
    {weekday:'long', month:'long', day:'numeric'});

  // ── TODAY CHECKLIST ──────────────────────────────────────────────────────
  const checklist = document.getElementById('habit-checklist');
  const scoreEl   = document.getElementById('habit-today-score');
  const panelEl   = document.getElementById('habit-today-panel');

  if (panelEl) panelEl.style.display = habits.length ? '' : 'none';

  if (checklist) {
    if (!habits.length) {
      checklist.innerHTML = '';
    } else {
      const done  = habits.filter(h => h.done_today).length;
      const total = habits.length;
      const pct   = Math.round(done / total * 100);

      // Score pill in header
      if (scoreEl) {
        const color = pct === 100 ? '#22C55E' : pct >= 60 ? '#F59E0B' : 'var(--gray-400)';
        scoreEl.innerHTML = `
          <span style="color:${color};font-weight:700;font-size:14px">${done}/${total}</span>
          <span style="color:var(--gray-400);font-size:12px;margin-left:4px">done</span>
          <div class="hts-progress-bar"><div class="hts-progress-fill" style="width:${pct}%;background:${color}"></div></div>`;
      }

      checklist.innerHTML = habits.map(h => `
        <div class="habit-check-row ${h.done_today ? 'is-done' : ''}" data-ev-click="toggleHabit('${h.id}','${today}')">
          <!-- Color accent -->
          <div class="hcr-accent" style="background:${h.color}"></div>

          <!-- Checkbox toggle -->
          <div class="hcr-toggle ${h.done_today ? 'checked' : ''}" style="--c:${h.color}">
            ${h.done_today ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>` : ''}
          </div>

          <!-- Emoji + name -->
          <div class="hcr-emoji">${h.emoji}</div>
          <div class="hcr-info">
            <div class="hcr-name">${escHtml(h.name)}</div>
            <div class="hcr-meta">${h.streak > 0 ? `🔥 ${h.streak} day streak` : 'Start your streak today'}</div>
          </div>

          <!-- Done label -->
          <div class="hcr-status">
            ${h.done_today
              ? `<span class="hcr-done-label">✓ Done</span>`
              : `<span class="hcr-todo-label">Tap to check off</span>`}
          </div>
        </div>`).join('');
    }
  }

  // ── HABITS GRID (cards with history) ─────────────────────────────────────
  const el = document.getElementById('habits-grid');
  if (!el) return;

  if (!habits.length) {
    el.innerHTML = `
      <!-- "+" add card only when no habits -->
      <div class="habit-add-card" data-ev-click="openHabitModal()">
        <div class="habit-add-icon">+</div>
        <div class="habit-add-label">Add first habit</div>
      </div>`;
    return;
  }

  el.innerHTML = habits.map(h => {
    // 7-day mini bars
    const bars = (h.week7 || []).map(d => `
      <div class="hc-bar-col">
        <div class="hc-bar-fill" style="height:${d.done ? '100' : '20'}%;background:${d.done ? h.color : 'var(--gray-100)'}"></div>
        <div class="hc-bar-lbl">${d.label.slice(0,1)}</div>
      </div>`).join('');

    // 28-day heatmap dots (4 rows × 7 cols)
    const heatmap = (h.cal28 || []).map(d =>
      `<div class="hc-heat-dot" style="background:${d.done ? h.color : 'var(--gray-100)'}" title="${d.date}"></div>`
    ).join('');

    return `
    <div class="habit-card2 ${h.done_today ? 'is-done' : ''}" data-id="${h.id}">

      <!-- Top row: emoji + name + streak + delete -->
      <div class="hc2-top">
        <div class="hc2-emoji">${h.emoji}</div>
        <div class="hc2-name">${escHtml(h.name)}</div>
        <div class="hc2-streak" title="Current streak">🔥 ${h.streak}</div>
        <button class="hc2-delete" data-ev-click="event.stopPropagation();deleteHabit('${h.id}')" title="Remove habit">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>

      <!-- Color bar -->
      <div class="hc2-color-bar" style="background:${h.color}"></div>

      <!-- 7-day bars -->
      <div class="hc2-section-label">Last 7 days</div>
      <div class="hc-bars">${bars}</div>

      <!-- 28-day heatmap -->
      <div class="hc2-section-label" style="margin-top:10px">Last 28 days</div>
      <div class="hc-heatmap">${heatmap}</div>

      <!-- Toggle button -->
      <button class="hc2-toggle-btn ${h.done_today ? 'done' : ''}"
              data-ev-click="toggleHabit('${h.id}','${today}')"
              style="--habit-color:${h.color}">
        ${h.done_today
          ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg> Done today — tap to undo`
          : `Mark done today`}
      </button>
    </div>`;
  }).join('') +
  // "+" add card at the end
  `<div class="habit-add-card" data-ev-click="openHabitModal()">
    <div class="habit-add-icon">+</div>
    <div class="habit-add-label">New habit</div>
  </div>`;
}

async function toggleHabit(id, date) {
  // Optimistic visual feedback — find the card and flip its state immediately
  const card  = document.querySelector(`.habit-card2[data-id="${id}"]`);
  const row   = document.querySelector(`.habit-check-row`);  // checklist row
  if (card) card.style.opacity = '0.6';

  const r = await fetch(`/api/habits/${id}/toggle`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({date_key: date})
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    loadHabits();
    loadWellnessStrip();
    if (r?.done) { try { checkHabitCelebrations(); } catch (e) {} }
  } else {
    if (card) card.style.opacity = '1';
    showToast('Could not update habit', 'error');
  }
}

function deleteHabit(id) {
  undoable('Removing habit and its history…', async () => {
    await fetch(`/api/habits/${id}`, {method: 'DELETE'});
    loadHabits();
    loadWellnessStrip();
  });
}

// ════════════════════════════════════════════════════════════
// SYMPTOMS
// ════════════════════════════════════════════════════════════

// ─── Multi-select symptoms ───────────────────────────────────────────────────
let selectedSymptoms = new Set();

function toggleSymptom(btn) {
  const name = btn.dataset.sym;
  if (selectedSymptoms.has(name)) {
    selectedSymptoms.delete(name);
    btn.classList.remove('selected');
  } else {
    selectedSymptoms.add(name);
    btn.classList.add('selected');
  }
  updateSymptomChips();
}

function addCustomSymptom() {
  const inp = document.getElementById('symptom-custom-input');
  const val = inp?.value?.trim();
  if (!val) return;
  selectedSymptoms.add(val);
  inp.value = '';
  updateSymptomChips();
}

function removeSymptomChip(name) {
  selectedSymptoms.delete(name);
  // Deselect grid button if present
  document.querySelectorAll('.sym-toggle-btn').forEach(b => {
    if (b.dataset.sym === name) b.classList.remove('selected');
  });
  updateSymptomChips();
}

function updateSymptomChips() {
  const wrap = document.getElementById('symptom-selected-chips');
  const list = document.getElementById('sym-chips-list');
  const btn  = document.getElementById('log-symptoms-btn');
  const hint = document.getElementById('sym-log-hint');
  const any  = selectedSymptoms.size > 0;

  if (wrap) wrap.style.display = any ? 'flex' : 'none';
  if (btn)  btn.disabled = !any;
  if (hint) hint.style.display = any ? 'none' : 'block';

  if (list) {
    list.innerHTML = [...selectedSymptoms].map(n =>
      `<span class="sym-chip">${escHtml(n)}<button class="sym-chip-del" data-ev-click="removeSymptomChip('${escHtml(n).replace(/'/g,'\'')}')">×</button></span>`
    ).join('');
  }
}

async function logSymptoms() {
  if (selectedSymptoms.size === 0) return;
  const severity  = +document.getElementById('symptom-severity').value;
  const timeOfDay = document.getElementById('symptom-time').value;
  const notes     = document.getElementById('symptom-notes')?.value || '';
  const dateKey   = localToday();
  const btn = document.getElementById('log-symptoms-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  // Log each selected symptom individually
  const promises = [...selectedSymptoms].map(name =>
    fetch('/api/symptoms', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, severity, time_of_day: timeOfDay, notes, date_key: dateKey })
    }).then(r => r.json())
  );
  const results = await Promise.all(promises);
  const ok = results.every(r => r.success);

  if (ok) {
    const count = selectedSymptoms.size;
    showToast(`${count} symptom${count>1?'s':''} logged`, 'success');
    // Reset
    selectedSymptoms.clear();
    document.querySelectorAll('.sym-toggle-btn').forEach(b => b.classList.remove('selected'));
    updateSymptomChips();
    document.getElementById('symptom-notes').value = '';
    document.getElementById('symptom-severity').value = 5;
    updateSeverityLabel(5);
    loadSymptoms(); loadSymptomPatterns();
    loadWellnessStrip();
  } else {
    showToast('Some symptoms failed to save', 'error');
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Log Symptoms'; }
}

function updateSeverityLabel(v) {
  const labels = ['','Minimal','Mild','Mild-Moderate','Moderate','Moderate','Noticeable','Significant','Severe','Very Severe','Extreme'];
  setText('severity-label', `${v} — ${labels[+v]||''}`);
}

function switchMedTab(tab) {
  document.querySelectorAll('.medical-tabs .wellness-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('#view-reports .wellness-tab-content').forEach(c => {
    c.style.display = c.id === `med-tab-${tab}` ? '' : 'none';
  });
  if (tab === 'symptoms') { loadSymptoms(); loadSymptomPatterns(); }
  if (tab === 'vitals')   { loadVitals(); renderVitalFields(); }
  if (tab === 'emergency') loadEmergencyCard();
}

async function logSymptom() {
  const name = document.getElementById('symptom-name')?.value?.trim();
  if (!name) { showToast('Enter a symptom', 'error'); return; }
  const r = await fetch('/api/symptoms', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      name, severity: +document.getElementById('symptom-severity').value,
      time_of_day: document.getElementById('symptom-time').value,
      notes: document.getElementById('symptom-notes')?.value || '',
      date_key: localToday()
    })
  }).then(r => r.json());
  if (r.success) {
    showToast(`${name} logged`, 'success');
    document.getElementById('symptom-name').value = '';
    loadSymptoms(); loadWellnessStrip();
  }
}

async function loadSymptoms() {
  const r = await fetch('/api/symptoms?days=14').then(r => r.json()).catch(() => []);
  const el = document.getElementById('symptoms-list');
  if (!el) return;

  if (!r.length) {
    el.innerHTML = `<div class="sym-history-empty">
      <span style="font-size:28px">🩺</span>
      <div>No symptoms logged in the last 14 days</div>
    </div>`;
    return;
  }

  const sevColor = s => s>=8?'#EF4444':s>=5?'#F59E0B':'#22C55E';
  const sevLabel = s => s>=8?'Severe':s>=7?'High':s>=5?'Moderate':s>=3?'Mild':'Minimal';
  const TMAP = { morning:'☀️ Morning', afternoon:'🌤️ Afternoon', evening:'🌆 Evening', night:'🌙 Night', all_day:'🔄 All day' };

  // Group by date for better readability
  const byDate = {};
  r.forEach(s => { (byDate[s.date_key] = byDate[s.date_key]||[]).push(s); });

  el.innerHTML = Object.entries(byDate).map(([date, syms]) => {
    const d = new Date(date+'T12:00:00');
    const today = localToday();
    const dateLabel = date === today ? 'Today' :
      d.toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric' });

    const rows = syms.map(s => `
      <div class="symptom-row">
        <div class="symptom-dot" style="background:${sevColor(s.severity)}"></div>
        <div class="symptom-info">
          <div class="symptom-name-text">${escHtml(s.name)}</div>
          <div class="symptom-meta">${TMAP[s.time_of_day]||s.time_of_day}${s.notes?' · '+escHtml(s.notes):''}</div>
        </div>
        <span class="symptom-severity-badge" style="background:${sevColor(s.severity)}1A;color:${sevColor(s.severity)}">
          ${s.severity}/10 · ${sevLabel(s.severity)}
        </span>
        <button class="todo-act-btn del" data-ev-click="delSymptom('${s.id}')" title="Remove">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
        </button>
      </div>`).join('');

    return `<div class="sym-date-group">
      <div class="sym-date-header">${dateLabel}</div>
      ${rows}
    </div>`;
  }).join('');
}

async function delSymptom(id) {
  await fetch(`/api/symptoms/${id}`, {method:'DELETE'});
  loadSymptoms(); loadSymptomPatterns(); loadWellnessStrip();
}

// ════════════════════════════════════════════════════════════
// VITALS
// ════════════════════════════════════════════════════════════

// Reading flags. Three rules, learned the hard way:
//
//   1. We never say "Normal". Vouching for a reading is a clinical call we're
//      not qualified to make, and the failure mode is the worst one there is:
//      a green badge telling someone their 85% SpO2 or 138/88 is fine. Silence
//      says "we're not judging this"; a badge only ever means "worth a look".
//   2. The thresholds ARE the `reference` string shown right below the input.
//      One source of truth — the two must never contradict each other.
//   3. When we can't know, we say nothing: an unrecognised type, a unit we
//      can't place, or a glucose whose fasting state we never asked about.
//
// A flag returns null (no badge) | 'low' | 'elevated' | 'high'.
const VITAL_CONFIG = {
  blood_pressure: {
    icon:'❤️', label:'Blood Pressure',
    fields:[{id:'vf1',label:'Systolic (mmHg)',ph:'120'},{id:'vf2',label:'Diastolic (mmHg)',ph:'80'}],
    unit:'mmHg',
    // v2 is guarded explicitly: `null >= 80` is false but `null < 60` is TRUE,
    // so a reading with no diastolic would otherwise be flagged "Low".
    flag: (v1, v2) => {
      const high = v1 >= 130 || (v2 != null && v2 >= 80);
      const low  = v1 <  90 || (v2 != null && v2 <  60);
      return high ? 'high' : low ? 'low' : v1 >= 120 ? 'elevated' : null;
    },
    reference: 'Normal: 90–120 / 60–80 mmHg · Elevated: 120–129 / <80 · High: >130 / >80 · Low: <90 / <60',
    categories: [{label:'Normal',range:'<120/<80',color:'#22C55E'},{label:'Elevated',range:'120-129/<80',color:'#F59E0B'},{label:'High',range:'>130/>80',color:'#EF4444'},{label:'Low',range:'<90/<60',color:'#3B82F6'}]
  },
  blood_sugar: {
    icon:'🩸', label:'Blood Sugar',
    fields:[{id:'vf1',label:'mg/dL',ph:'100'}],
    unit:'mg/dL',
    // We never ask whether the sample was fasting or post-meal, so 110 could be
    // textbook-normal or worth a conversation — we can't tell, so we don't say.
    // Only the readings that are notable either way get a flag.
    flag: (v1) => v1 > 125 ? 'high' : v1 < 70 ? 'low' : null,
    reference: 'Fasting: 70–100 mg/dL (Normal) · 100–125 (Pre-diabetic) · >126 (Diabetic) · <70 (Low)',
    categories: [{label:'Normal',range:'70–100',color:'#22C55E'},{label:'Pre-diabetic',range:'100–125',color:'#F59E0B'},{label:'High',range:'>126',color:'#EF4444'},{label:'Low',range:'<70',color:'#3B82F6'}]
  },
  heart_rate: {
    icon:'💓', label:'Heart Rate',
    fields:[{id:'vf1',label:'BPM',ph:'72'}],
    unit:'bpm',
    flag: (v1) => v1 > 100 ? 'high' : v1 < 60 ? 'low' : null,
    reference: 'Normal resting: 60–100 bpm · Athletes may have 40–60 bpm · >100 = Tachycardia · <60 = Bradycardia',
    categories: [{label:'Athlete',range:'40–60',color:'#06B6D4'},{label:'Normal',range:'60–100',color:'#22C55E'},{label:'High',range:'>100',color:'#EF4444'}]
  },
  temperature: {
    icon:'🌡️', label:'Temperature',
    fields:[{id:'vf1',label:'°F',ph:'98.6'}],
    unit:'°F',
    // Readings arrive in both scales (this form logs °F; the body-vitals chip
    // and lab import log °C), so the number means nothing without its unit.
    // An unrecognised unit gets no flag rather than a guess.
    flag: (v1, _v2, unit) => {
      const u = String(unit || '°F').toUpperCase();
      if (u.includes('C')) return v1 >= 38 ? 'high' : v1 < 36.1 ? 'low' : null;
      if (u.includes('F')) return v1 >= 100.4 ? 'high' : v1 < 97 ? 'low' : null;
      return null;
    },
    reference: 'Normal: 97–99°F (36.1–37.2°C) · Low-grade fever: 99–100.4°F · Fever: >100.4°F · Hypothermia: <97°F',
    categories: [{label:'Low',range:'<97°F',color:'#3B82F6'},{label:'Normal',range:'97–99°F',color:'#22C55E'},{label:'Fever',range:'>100.4°F',color:'#EF4444'}]
  },
  // Keyed 'spo2' — the same key the body-vitals chip, the trend chart, the
  // family view and lab import all use. It was 'oxygen_sat' here alone, so
  // every real reading missed this config and fell back to a hardcoded
  // "Normal" badge: an 85% (hypoxia) rendered green.
  spo2: {
    icon:'💨', label:'SpO2',
    fields:[{id:'vf1',label:'%',ph:'98'}],
    unit:'%',
    flag: (v1) => v1 < 95 ? 'low' : null,
    reference: 'Normal: 95–100% · Acceptable: 92–95% · Low (seek care): <92% · Critical: <88%',
    categories: [{label:'Normal',range:'95–100%',color:'#22C55E'},{label:'Acceptable',range:'92–95%',color:'#F59E0B'},{label:'Low',range:'<92%',color:'#EF4444'}]
  },
};

function selectVitalType(type) {
  selectedVitalType = type;
  document.querySelectorAll('.vital-type-btn').forEach(b => b.classList.toggle('selected', b.dataset.type === type));
  renderVitalFields();
}

function renderVitalFields() {
  const el = document.getElementById('vital-value-fields');
  if (!el) return;
  const cfg = VITAL_CONFIG[selectedVitalType];
  if (!cfg) return;
  const catHtml = cfg.categories ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px">` +
    cfg.categories.map(c => `<span style="font-size:10.5px;padding:2px 8px;border-radius:99px;background:${c.color}18;color:${c.color};font-weight:600">${c.label}: ${c.range}</span>`).join('') +
    `</div>` : '';
  el.innerHTML = `<div class="form-row" style="margin-bottom:8px">` +
    cfg.fields.map(f => `<div class="form-group"><label class="form-label">${f.label}</label>
      <input type="number" class="form-input" id="${f.id}" placeholder="${f.ph}" step="0.1"></div>`).join('') +
    `</div>` +
    (cfg.reference ? `<div class="vital-ref-range">📊 ${cfg.reference}${catHtml}</div>` : '');
}

async function logVital() {
  const cfg = VITAL_CONFIG[selectedVitalType];
  const v1 = parseFloat(document.getElementById('vf1')?.value);
  const v2 = parseFloat(document.getElementById('vf2')?.value);
  if (!v1) { showToast('Enter a reading', 'error'); return; }
  const r = await fetch('/api/vitals', {
    method:'POST', headers:{'Content-Type':'application/json'},
    // date_key: without it the server files the reading on ITS day, so a
    // late-night reading east of UTC lands yesterday — while the same reading
    // typed as "bp 120/80" in the command bar lands today. Every other vitals
    // path sends localToday(); this one didn't.
    body: JSON.stringify({ type:selectedVitalType, value1:v1, value2:v2||null,
      unit:cfg.unit, date_key: localToday(),
      notes:document.getElementById('vital-notes')?.value||'' })
  }).then(r => r.json());
  if (r.success) {
    showToast(`${cfg.label} saved`, 'success');
    document.getElementById('vf1').value = '';
    if (document.getElementById('vf2')) document.getElementById('vf2').value = '';
    loadVitals();
  } else {
    showToast(r.error || 'Could not save reading', 'error');
  }
}

// The one place a reading is judged. Returns null | 'low' | 'elevated' | 'high'
// — null meaning "we're not judging this", which is the honest answer for a
// type we don't recognise, a unit we can't place, or a reading whose context
// we never asked for. It must never return a "you're fine" verdict.
function vitalFlag(type, v1, v2, unit) {
  const cfg = VITAL_CONFIG[type];
  if (!cfg || typeof cfg.flag !== 'function') return null;
  const n1 = Number(v1);
  if (!isFinite(n1)) return null;
  const f = cfg.flag(n1, (v2 === null || v2 === undefined || v2 === '') ? null : Number(v2), unit);
  return f || null;
}

async function loadVitals() {
  const r = await fetch('/api/vitals?days=30').then(r => r.json()).catch(() => []);
  const el = document.getElementById('vitals-list');
  if (!el) return;
  if (!r.length) {
    el.innerHTML = '<div class="todo-empty"><div class="todo-empty-icon">❤️</div><div class="todo-empty-text">No readings logged</div></div>';
    return;
  }
  el.innerHTML = r.map(v => {
    const cfg = VITAL_CONFIG[v.type] || {icon:'📊', label:v.type};
    const flagStr = vitalFlag(v.type, v.value1, v.value2, v.unit);
    const display = v.value2 ? `${v.value1}/${v.value2}` : v.value1;
    return `<div class="vital-row">
      <div class="vital-type-icon">${cfg.icon}</div>
      <div class="vital-info">
        <div class="vital-reading">${display} <span style="font-size:12px;color:var(--gray-400)">${v.unit}</span></div>
        <div class="vital-meta">${v.date_key} ${v.notes ? '· '+escHtml(v.notes) : ''}</div>
      </div>
      ${flagStr ? `<span class="vital-flag ${flagStr}">${flagStr.charAt(0).toUpperCase()+flagStr.slice(1)}</span>` : ''}
      <button class="todo-act-btn del" data-ev-click="delVital('${v.id}')">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
      </button>
    </div>`;
  }).join('');
}

async function delVital(id) {
  await fetch(`/api/vitals/${id}`, {method:'DELETE'});
  // A reading feeds three places: the Medical list, and the Body & Vitals
  // history + trend chart. delVital is called from both views, but only
  // refreshed the Medical list — so deleting from Body & Vitals left its
  // history and trend stale. Refresh all three; each no-ops if not mounted.
  try { loadVitals(); }      catch (e) {}
  try { loadVitalsView(); }  catch (e) {}
  try { loadVitalTrends(); } catch (e) {}
}

// ════════════════════════════════════════════════════════════
// EMERGENCY HEALTH CARD
// ════════════════════════════════════════════════════════════

async function loadEmergencyCard() {
  const r = await fetch('/api/emergency').then(r => r.json()).catch(() => null);
  if (!r) return;
  const fields = ['blood_type','allergies','conditions','medications','contact1_name','contact1_phone','contact2_name','contact2_phone','insurance_provider','insurance_number'];
  const elMap  = {'blood_type':'em-blood-type','allergies':'em-allergies','conditions':'em-conditions','medications':'em-medications','contact1_name':'em-c1-name','contact1_phone':'em-c1-phone','contact2_name':'em-c2-name','contact2_phone':'em-c2-phone','insurance_provider':'em-insurance-provider','insurance_number':'em-insurance-number'};
  fields.forEach(k => {
    const el = document.getElementById(elMap[k]);
    if (el) { if (el.tagName === 'SELECT') el.value = r[k]||''; else el.value = r[k]||''; }
  });
  // Update card preview
  setText('ec-blood-type',  r.blood_type     || '—');
  setText('ec-allergies',   r.allergies      || '—');
  setText('ec-conditions',  r.conditions     || '—');
  setText('ec-medications', r.medications    || '—');
  const c1 = [r.contact1_name, r.contact1_phone].filter(Boolean).join(' · ');
  const c2 = [r.contact2_name, r.contact2_phone].filter(Boolean).join(' · ');
  setText('ec-c1', c1||'—');
  setText('ec-c2', c2||'—');
  setText('ec-insurance', [r.insurance_provider, r.insurance_number].filter(Boolean).join(' · ')||'—');
}

async function saveEmergencyInfo() {
  const data = {
    blood_type:          document.getElementById('em-blood-type')?.value,
    allergies:           document.getElementById('em-allergies')?.value,
    conditions:          document.getElementById('em-conditions')?.value,
    medications:         document.getElementById('em-medications')?.value,
    contact1_name:       document.getElementById('em-c1-name')?.value,
    contact1_phone:      document.getElementById('em-c1-phone')?.value,
    contact2_name:       document.getElementById('em-c2-name')?.value,
    contact2_phone:      document.getElementById('em-c2-phone')?.value,
    insurance_provider:  document.getElementById('em-insurance-provider')?.value,
    insurance_number:    document.getElementById('em-insurance-number')?.value,
  };
  const r = await fetch('/api/emergency', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)
  }).then(r => r.json());
  if (r.success) { showToast('Health card saved!', 'success'); loadEmergencyCard(); }
}

// ════════════════════════════════════════════════════════════
// HYDRATION (Food Tracker page)
// ════════════════════════════════════════════════════════════

async function loadHydration(dateStr) {
  const date = dateStr || localToday();
  const r = await fetch(`/api/hydration/${date}`, {cache: 'no-store'}).then(r => r.json()).catch(() => null);
  if (!r) return;

  const goalMl = r.goal_ml || 2450;
  const pct    = r.pct != null ? r.pct : Math.min(Math.round((r.total_ml || 0) / goalMl * 100), 100);

  // Update food page hydration panel
  const fill    = document.getElementById('hydration-fill');
  const pctEl   = document.getElementById('hydration-pct');
  const lvlEl   = document.getElementById('hydration-level-text');
  const badgeEl = document.getElementById('hydration-goal-badge');
  if (fill)    fill.style.height = pct + '%';
  if (pctEl)   pctEl.textContent = pct + '%';
  if (lvlEl)   lvlEl.textContent = (r.total_ml || 0) + 'ml';
  // Don't call a number "your goal" when we made it up. 2450ml is 35ml × an
  // assumed 70kg — specific enough that the user believes we know their body.
  // Say it's a default, and how to make it theirs.
  if (badgeEl) {
    badgeEl.textContent = r.goal_is_default ? `Goal: ${goalMl}ml (default)` : `Goal: ${goalMl}ml`;
    badgeEl.title = r.goal_is_default
      ? 'A general starting point — set a water goal, or add your weight, to personalise it'
      : '';
  }

  // Update dashboard wellness strip at the same time
  const stripEl  = document.getElementById('dws-hydration');
  const stripBar = document.getElementById('dws-hydration-bar');
  if (stripEl)  stripEl.textContent = `${r.total_ml || 0} ml`;
  if (stripBar) stripBar.style.width = pct + '%';

  // Render log list with delete buttons
  const wrap = document.getElementById('hydration-logs-wrap');
  if (!wrap) return;

  if (!r.logs || !r.logs.length) {
    wrap.innerHTML = '<div style="color:var(--gray-400);font-size:12px;text-align:center;padding:12px 0">No water logged yet — tap a button above</div>';
    return;
  }

  const DTYPE = { water:'💧', coffee:'☕', tea:'🍵', juice:'🥤', milk:'🥛', other:'🫙' };
  wrap.innerHTML = r.logs.map(l => `
    <div class="hydration-log-item">
      <span class="hli-icon">${DTYPE[l.drink_type] || '💧'}</span>
      <span class="hli-type">${l.drink_type || 'water'}</span>
      <span class="hli-amount">${l.amount_ml}ml</span>
      <button class="hli-delete" data-ev-click="delHydration('${l.id}')" title="Remove">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>`).join('');
}

// The user's real glass/bottle, learned from their own logs (server-computed).
// Nobody drinks "250ml" — they drink their bottle. 250 is only the cold start.
let _usualWaterMl = 250;

function setUsualWaterMl(ml) {
  _usualWaterMl = Math.max(50, Math.min(Number(ml) || 250, 2000));
  const hint = document.getElementById('ql-water-hint');
  if (hint) hint.textContent = `${_usualWaterMl}ml`;
}

async function quickAddWater(ml) {
  ml = Number(ml) || _usualWaterMl;      // no arg → their usual pour
  const today = localToday();
  const res = await fetch('/api/hydration', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({amount_ml: ml, drink_type: 'water', date_key: today})
  }).then(r => r.json()).catch(() => null);

  if (!res?.success) { showToast('Failed to log water', 'error'); return; }

  // Reload the full hydration panel (updates bottle + log list + strip)
  await loadHydration(today);
  showToast(`💧 +${ml}ml logged`, 'success');
}

async function delHydration(id) {
  const today = localToday();
  await fetch(`/api/hydration/${id}`, {method: 'DELETE'});
  await loadHydration(today);
  showToast('Entry removed', 'success');
}

// (monkey-patches removed — all wired directly in switchView)

// Patch loadReports to init medical tabs
const _origLoadReports = loadReports;
loadReports = async function() {
  await _origLoadReports.apply(this, arguments);
  loadSymptoms();
};

// Patch loadThoughts to init sleep defaults
const _origLoadThoughts = loadThoughts;
loadThoughts = async function() {
  await _origLoadThoughts.apply(this, arguments);
  initSleepDefaults();
};

// ════════════════════════════════════════════════════════════
// DASHBOARD IMPROVEMENTS
// ════════════════════════════════════════════════════════════

// Render pending todos on dashboard
async function loadDashboardTodos() {
  const r = await fetch('/api/todos?status=pending').then(r => r.json()).catch(() => null);
  const el = document.getElementById('dash-todos-list');
  if (!el) return 0;
  // Tasks live on the dashboard: the panel is always shown so the inline
  // quick-add is always available. The full Tasks screen ("Manage →") keeps
  // the depth — priorities, due dates, reminders, tags, completed history.
  const panel = document.getElementById('dash-tasks-panel');
  if (panel) panel.style.display = '';
  const agenda = document.getElementById('dash-agenda-grid');
  if (agenda) agenda.style.display = '';
  const allPending = r?.todos || [];
  const todos = allPending.slice(0, 5);
  if (todos.length === 0) {
    el.innerHTML = '<div class="dash-todo-empty">Nothing pending — add a task above.</div>';
    return 0;
  }
  const today = localToday();
  const PRI = { high:'🔴', medium:'🟡', low:'🟢' };
  el.innerHTML = todos.map(t => {
    const isOverdue = t.due_date && t.due_date < today;
    const dueStr = t.due_date === today ? 'Today' : t.due_date ? t.due_date.slice(5) : '';
    return `<div class="dash-todo-row" data-ev-click="switchView('todos')">
      <div class="dash-todo-check" data-ev-click="event.stopPropagation();dashToggleTodo('${t.id}')"></div>
      <div class="dash-todo-title">${escHtml(t.title)}</div>
      <span class="dash-todo-pri">${PRI[t.priority]||'🟡'}</span>
      ${dueStr ? `<span class="dash-todo-due ${isOverdue?'overdue':''}">${dueStr}</span>` : ''}
    </div>`;
  }).join('');
  if (allPending.length > 5) {
    el.innerHTML += `<div style="text-align:center;padding:6px 0">
      <a href="#" data-ev-click="switchView('todos');return false" style="font-size:12px;color:var(--teal-600)">+${allPending.length-5} more tasks →</a>
    </div>`;
  }
  return allPending.length;
}

async function dashToggleTodo(id) {
  await fetch(`/api/todos/${id}/toggle`, {method:'POST'});
  loadDashboardTodos();
  loadTodos();
}

// Add a task inline from the dashboard (the Tasks screen's most-common action,
// on home). Defaults to medium priority / no due date; use "Manage →" for those.
async function dashAddTodo() {
  const inp = document.getElementById('dash-todo-input');
  const title = (inp?.value || '').trim();
  if (!title) return;
  inp.value = '';
  await fetch('/api/todos', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, priority: 'medium' })
  }).catch(() => {});
  loadDashboardTodos();
  try { loadTodos(); } catch (e) {}
}
function dashAddTodoKey(e) { if (e.key === 'Enter') { e.preventDefault(); dashAddTodo(); } }

// Sidebar user info from profile
async function updateSidebarUser() {
  const r = await fetch('/api/food/profile').then(r => r.json()).catch(() => null);
  if (!r?.profile) return;
  const p = r.profile;
  const name  = p.name || 'User';
  const initials = name.split(' ').map(w=>w[0]?.toUpperCase()||'').join('').slice(0,2) || 'U';
  setText('sidebar-name',   name);
  setText('sidebar-avatar', initials);
  const goal = { lose_fast:'Losing weight', lose:'Losing weight', maintain:'Maintaining', gain:'Building muscle', gain_fast:'Building muscle' };
  setText('sidebar-role', goal[p.goal] || 'Health Profile');
}

// Patch loadDashboard to include new panels
const _dashBase = loadDashboard;
loadDashboard = async function() {
  await _dashBase.apply(this, arguments);
  loadDashboardTodos();
};

// ════════════════════════════════════════════════════════════
// MEDICINE ADHERENCE STREAKS
// ════════════════════════════════════════════════════════════

async function loadMedAdherence() {
  const section = document.getElementById('med-streaks-section');
  if (!section) return;

  const data = await fetch('/api/medicines/streaks?days=28', {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data || !data.medicines.length) {
    section.innerHTML = '';
    return;
  }

  const { medicines, overall_pct, overall_taken, overall_total } = data;

  // ── Overall score card ──────────────────────────────────────
  const scoreColor = overall_pct >= 90 ? '#22C55E'
                   : overall_pct >= 70 ? '#F59E0B' : '#EF4444';
  const scoreLabel = overall_pct >= 90 ? 'Excellent'
                   : overall_pct >= 70 ? 'Good'
                   : overall_pct >= 50 ? 'Needs work' : 'Low';

  // ── Per-medicine streak cards ───────────────────────────────
  const FREQ_LABEL = {
    once_daily: 'Once daily', twice_daily: 'Twice daily',
    thrice_daily: '3× daily', weekly: 'Weekly',
  };

  const medCards = medicines.map(m => {
    // 28-day dot heatmap — last 28 days
    const days28 = m.days.slice(-28);
    const dots = days28.map(d => {
      if (!d.total) return '<div class="adh-dot adh-dot--none"></div>';
      if (d.full)   return `<div class="adh-dot adh-dot--full" title="${d.date}: all doses taken"></div>`;
      if (d.taken)  return `<div class="adh-dot adh-dot--partial" title="${d.date}: ${d.taken}/${d.total} doses"></div>`;
      return `<div class="adh-dot adh-dot--missed" title="${d.date}: missed"></div>`;
    }).join('');

    const pctColor = m.adherence_pct >= 90 ? '#22C55E'
                   : m.adherence_pct >= 70 ? '#F59E0B' : '#EF4444';

    const streakEmoji = m.streak >= 14 ? '🔥'
                      : m.streak >= 7  ? '⚡'
                      : m.streak >= 3  ? '✅' : '';

    return `
      <div class="adh-med-card">
        <div class="adh-med-top">
          <span class="adh-med-icon">${m.icon}</span>
          <div class="adh-med-info">
            <div class="adh-med-name">${escHtml(m.name)}</div>
            <div class="adh-med-sub">${m.dosage} ${m.unit} · ${FREQ_LABEL[m.frequency] || m.frequency}</div>
          </div>
          <div class="adh-med-stats">
            <div class="adh-streak-badge" title="Current streak">
              ${streakEmoji} ${m.streak}<span style="font-size:10px;font-weight:400"> days</span>
            </div>
            <div class="adh-pct-badge" style="color:${pctColor}">${m.adherence_pct}%</div>
          </div>
        </div>
        <div class="adh-dot-grid">${dots}</div>
        <div class="adh-med-foot">
          <span>Best streak: ${m.best_streak} days${m.grace_used ? ` · 🛟 ${m.grace_used} rest day${m.grace_used > 1 ? 's' : ''} kept it going` : ''}</span>
          <span>${m.taken_total} of ${m.days.reduce((s,d)=>s+d.total,0)} doses taken</span>
        </div>
      </div>`;
  }).join('');

  section.innerHTML = `
    <div class="panel" style="padding:18px 20px 20px">

      <!-- Header + overall score -->
      <div class="adh-header">
        <div>
          <h2 class="panel-title">Adherence streaks</h2>
          <div style="font-size:12px;color:var(--gray-400);margin-top:3px">Last 28 days</div>
        </div>
        <div class="adh-overall-score">
          <div class="adh-overall-ring">
            <svg width="56" height="56" viewBox="0 0 56 56">
              <circle cx="28" cy="28" r="22" fill="none" stroke="var(--gray-100)" stroke-width="5"/>
              <circle cx="28" cy="28" r="22" fill="none"
                stroke="${scoreColor}" stroke-width="5"
                stroke-dasharray="${Math.round(overall_pct * 1.382)} 138.2"
                stroke-linecap="round"
                transform="rotate(-90 28 28)"/>
            </svg>
            <div class="adh-overall-num" style="color:${scoreColor}">${Math.round(overall_pct)}%</div>
          </div>
          <div style="text-align:center">
            <div class="adh-overall-label">${scoreLabel}</div>
            <div style="font-size:10.5px;color:var(--gray-400)">${overall_taken}/${overall_total} doses</div>
          </div>
        </div>
      </div>

      <!-- Legend -->
      <div class="adh-legend">
        <span class="adh-leg-item"><span class="adh-dot adh-dot--full" style="display:inline-block"></span>All taken</span>
        <span class="adh-leg-item"><span class="adh-dot adh-dot--partial" style="display:inline-block"></span>Partial</span>
        <span class="adh-leg-item"><span class="adh-dot adh-dot--missed" style="display:inline-block"></span>Missed</span>
        <span class="adh-leg-item"><span class="adh-dot adh-dot--none" style="display:inline-block"></span>No dose</span>
      </div>

      <!-- Per-medicine cards -->
      <div class="adh-med-list">${medCards}</div>

    </div>`;
}

// markDoseTaken also refreshes streaks

// Food weekly chart: update goal badge when loaded
const _origRenderFoodWeekly = renderFoodWeeklyChart;
renderFoodWeeklyChart = function(weekData, targets) {
  _origRenderFoodWeekly.apply(this, arguments);
  const badge = document.getElementById('food-weekly-target-badge');
  if (badge && targets?.target_calories) badge.textContent = `Goal: ${targets.target_calories} kcal`;
};

// ════════════════════════════════════════════════════════════
// GLOBAL SEARCH
// ════════════════════════════════════════════════════════════

let _gsTimer = null;

// ════════════════════════════════════════════════════════════
// GLOBAL SEARCH — full rebuild
// ════════════════════════════════════════════════════════════

const VIEW_MAP = {food:'food',fitness:'fitness',thought:'thoughts',symptom:'reports',
                  todo:'todos',activity:'fitness',report:'reports',medicine:'medicines'};
const TYPE_ICON= {food:'🍽️',thought:'💭',symptom:'🩺',todo:'✅',
                  activity:'🏃',report:'📋',medicine:'💊'};

let _gsSearchType = 'all';
let _gsSelectedIdx = -1;

function openGlobalSearch() {
  const wrap = document.getElementById('global-search-wrap');
  if (!wrap) return;
  wrap.style.display = 'flex';
  setTimeout(() => document.getElementById('global-search-input')?.focus(), 50);
  // Show hints on open
  document.getElementById('gs-hints').style.display = 'block';
  document.getElementById('global-search-results').innerHTML = '';
  // Reveal the mic only where the browser can actually transcribe speech.
  const mic = document.getElementById('gs-mic');
  if (mic) mic.style.display = _speechSupported() ? 'inline-block' : 'none';
}

// ── Voice input: speak a meal, feed it to the same NL parser ────────────────
function _speechSupported() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}
let _voiceRec = null;
function startVoiceSearch() {
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = document.getElementById('gs-mic');
  const inp = document.getElementById('global-search-input');
  if (!Rec || !inp) { showToast('Voice input isn’t available on this browser', 'error'); return; }
  if (_voiceRec) { try { _voiceRec.stop(); } catch {} _voiceRec = null; return; }  // toggle off
  const rec = new Rec();
  _voiceRec = rec;
  rec.lang = (navigator.language && /^en/i.test(navigator.language)) ? navigator.language : 'en-IN';
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  if (mic) mic.textContent = '🔴';
  rec.onresult = (e) => {
    const txt = Array.from(e.results).map(r => r[0].transcript).join('').trim();
    inp.value = txt;
    runGlobalSearch(txt);                     // live preview as they speak
  };
  const done = () => { _voiceRec = null; if (mic) mic.textContent = '🎤'; };
  rec.onerror = (e) => {
    done();
    if (e && e.error === 'not-allowed') showToast('Microphone permission denied', 'error');
  };
  rec.onend = done;
  try { rec.start(); } catch { done(); }
}

// Detect quick-log commands typed into global search
function parseQuickCommand(q) {
  let m = q.trim().toLowerCase().match(/^w(?:ater)?\s+(\d{2,4})\s*(?:ml)?$/);
  if (m) {
    const ml = parseInt(m[1], 10);
    if (ml >= 50 && ml <= 3000)
      return {icon: '💧', label: `Log ${ml}ml water`,
              ev: `closeGlobalSearch();quickWater(${ml})`};
  }
  m = q.trim().toLowerCase().match(/^weight\s+(\d{2,3}(?:\.\d+)?)\s*(?:kg)?$/);
  if (m) {
    const kg = parseFloat(m[1]);
    if (kg >= 20 && kg <= 400)
      return {icon: '⚖️', label: `Log weight ${kg}kg`,
              ev: `closeGlobalSearch();quickLogWeight(${kg})`};
  }
  // bp 120/80
  m = q.trim().toLowerCase().match(/^bp\s+(\d{2,3})\s*\/\s*(\d{2,3})$/);
  if (m) {
    const sys = parseInt(m[1], 10), dia = parseInt(m[2], 10);
    return {icon: '❤️', label: `Log BP ${sys}/${dia}`,
            ev: `closeGlobalSearch();quickLogVital('blood_pressure',${sys},${dia},'mmHg')`};
  }
  // sugar 110 / glucose 110
  m = q.trim().toLowerCase().match(/^(?:sugar|glucose)\s+(\d{2,3})$/);
  if (m) {
    const v = parseInt(m[1], 10);
    return {icon: '🩸', label: `Log blood sugar ${v} mg/dL`,
            ev: `closeGlobalSearch();quickLogVital('blood_sugar',${v},0,'mg/dL')`};
  }
  // hr 72 / pulse 72
  m = q.trim().toLowerCase().match(/^(?:hr|pulse)\s+(\d{2,3})$/);
  if (m) {
    const v = parseInt(m[1], 10);
    return {icon: '💓', label: `Log heart rate ${v} bpm`,
            ev: `closeGlobalSearch();quickLogVital('heart_rate',${v},0,'bpm')`};
  }
  return null;
}

async function quickLogWeight(kg) {
  const r = await fetch('/api/body-metrics', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({date_key: localToday(), weight_kg: kg}),
  }).then(r => r.json()).catch(() => null);
  if (!r || r.error) { showToast('Could not save weight', 'error'); return; }
  showToast(`⚖️ ${kg}kg saved`);
}

// One text box logs a vital: "bp 120/80", "sugar 110", "hr 72".
// value2 = 0 means "single value" (only BP is a pair).
async function quickLogVital(type, value1, value2, unit) {
  const r = await fetch('/api/vitals', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify({
      type, value1, value2: value2 || null, unit: unit || '', date_key: localToday(),
    }),
  }).then(r => r.json()).catch(() => null);
  // Surfaces the server's plausibility message ("that reading looks off")
  if (!r?.success) { showToast(r?.error || 'Could not log that reading', 'error'); return; }
  const shown = value2 ? `${value1}/${value2}` : value1;
  showToast(`✓ Logged ${shown} ${unit || ''}`.trim(), 'success');
  try { loadVitals(); } catch (e) {}
  try { loadVitalsView(); } catch (e) {}
}

function closeGlobalSearch() {
  const wrap = document.getElementById('global-search-wrap');
  if (wrap) wrap.style.display = 'none';
  const inp = document.getElementById('global-search-input');
  if (inp) inp.value = '';
  _gsSelectedIdx = -1;
}

function fillSearch(text) {
  const inp = document.getElementById('global-search-input');
  if (!inp) return;
  inp.value = text;
  inp.focus();
  document.getElementById('gs-hints').style.display = 'none';
  runGlobalSearch(text);
}

function setSearchType(type) {
  _gsSearchType = type;
  document.querySelectorAll('.gs-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.type === type));
  const q = document.getElementById('global-search-input')?.value;
  if (q?.length >= 2) runGlobalSearch(q);
}

function handleSearchKey(e) {
  const rows = document.querySelectorAll('.gs-result-row');
  if (e.key === 'Escape')  { closeGlobalSearch(); return; }
  if (e.key === 'ArrowDown') { _gsSelectedIdx = Math.min(_gsSelectedIdx+1, rows.length-1); highlightRow(rows); e.preventDefault(); }
  if (e.key === 'ArrowUp')   { _gsSelectedIdx = Math.max(_gsSelectedIdx-1, 0); highlightRow(rows); e.preventDefault(); }
  if (e.key === 'Enter' && _gsSelectedIdx >= 0) { rows[_gsSelectedIdx]?.click(); }
}

function highlightRow(rows) {
  rows.forEach((r,i) => r.classList.toggle('selected', i === _gsSelectedIdx));
  rows[_gsSelectedIdx]?.scrollIntoView({block:'nearest'});
}

// ── Natural-language food logging from the command bar ──────────────────────
let _pendingFoodLog = null;

// Only treat a phrase as a meal to log when it carries a clear signal, so we
// never hijack an ordinary history search for a single word like "chicken".
function _looksLikeFoodLog(q) {
  const s = (q || '').trim().toLowerCase();
  if (s.length < 3) return false;
  if (/^(log|ate|eat|had)\b/.test(s)) return true;               // "log 2 rotis"
  if (/\b(breakfast|lunch|dinner|snack|brunch)\b/.test(s)) return true;
  if (/^\d/.test(s) && /[a-z]/.test(s)) return true;             // "2 rotis"
  if (/\b(and|with)\b/.test(s) && /[a-z]/.test(s)) return true;  // "dal and rice"
  return false;
}

async function _fetchFoodPreview(q) {
  try {
    const r = await fetch('/api/food/parse', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ text: q, hour: new Date().getHours() }),
    });
    return await r.json();
  } catch { return null; }
}

function renderFoodLogPreview(res, p) {
  const mealLabel = (MEAL_TYPES.find(m => m.id === p.meal) || {}).label || p.meal;
  const total = p.items.reduce((s, i) => s + (i.calories || 0), 0);
  const lines = p.items.map(i =>
    `<div class="gsfl-item">${i.emoji || '🍽️'} <b>${escHtml(i.amount_label)}</b> ${escHtml(i.food_name)}` +
    ` · ${Math.round(i.calories || 0)} kcal` +
    (i.confident ? '' : ' <span style="color:var(--amber-600,#b45309)">· best guess</span>') +
    `</div>`).join('');
  const unmatched = (p.unmatched && p.unmatched.length)
    ? `<div class="gsfl-item" style="color:var(--gray-400)">Couldn’t find: ${p.unmatched.map(escHtml).join(', ')}</div>`
    : '';
  res.innerHTML = `<div class="gs-result-row gs-action-row" data-ev-click="confirmFoodLog()">
      <div class="gs-result-icon">🍽️</div>
      <div class="gs-result-main">
        <div class="gs-result-title">Log ${p.items.length} item${p.items.length > 1 ? 's' : ''} to ${escHtml(mealLabel)} · ~${Math.round(total)} kcal</div>
        <div class="gs-result-meta" style="display:flex;flex-direction:column;gap:2px;margin-top:4px">${lines}${unmatched}</div>
        <div class="gs-result-meta" style="margin-top:4px">Press Enter to log</div>
      </div>
      <span style="font-size:10px;font-weight:700;letter-spacing:.05em;color:var(--teal-600);
                   background:var(--teal-50);border-radius:6px;padding:3px 8px">LOG</span>
    </div>`;
  _gsSelectedIdx = 0;
  highlightRow([...res.querySelectorAll('.gs-result-row')]);
}

async function confirmFoodLog() {
  const p = _pendingFoodLog;
  if (!p || !p.items || !p.items.length) return;
  const date = localToday();
  let ok = 0;
  for (const it of p.items) {
    try {
      const r = await fetch('/api/food/log', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          food_id: it.food_id, food_name: it.food_name, meal_type: p.meal,
          date_key: date, quantity_g: it.grams,
          calories: it.calories, protein: it.protein, carbs: it.carbs,
          fat: it.fat, fiber: it.fiber,
        }),
      });
      if (r.ok) ok++;
    } catch { /* keep going; report the honest count below */ }
  }
  _pendingFoodLog = null;
  closeGlobalSearch();
  const mealLabel = (MEAL_TYPES.find(m => m.id === p.meal) || {}).label || p.meal;
  if (ok) showToast(`✓ Logged ${ok} item${ok > 1 ? 's' : ''} to ${mealLabel}`, 'success');
  else    showToast('Could not log that — try again', 'error');
  // refresh the food view if it's showing today
  if (ok && typeof loadFoodDay === 'function' && foodDate === date) loadFoodDay(date);
}

// Ctrl+K / Cmd+K
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); openGlobalSearch(); }
});

// Helper: highlight matched text
function hlText(text, query) {
  if (!query || !text) return escHtml(text||'');
  const clean = query.replace(/last\s+\w+|this\s+\w+|yesterday|today/g,'').trim();
  if (!clean || clean.length < 2) return escHtml(text);
  try {
    const re = new RegExp('(' + clean.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + ')', 'gi');
    return escHtml(text).replace(re, '<mark>$1</mark>');
  } catch { return escHtml(text); }
}

async function runGlobalSearch(q) {
  clearTimeout(_gsTimer);
  const res   = document.getElementById('global-search-results');
  const hints = document.getElementById('gs-hints');
  if (!res) return;
  if (q.length < 2) {
    res.innerHTML = '';
    if (hints) hints.style.display = 'block';
    return;
  }
  if (hints) hints.style.display = 'none';

  // ── Command actions: "water 500", "weight 71.5" log directly ──
  const action = parseQuickCommand(q);
  if (action) {
    res.innerHTML = `<div class="gs-result-row gs-action-row" data-ev-click="${action.ev}">
      <div class="gs-result-icon">${action.icon}</div>
      <div class="gs-result-main">
        <div class="gs-result-title">${action.label}</div>
        <div class="gs-result-meta">Press Enter to log it</div>
      </div>
      <span style="font-size:10px;font-weight:700;letter-spacing:.05em;color:var(--teal-600);
                   background:var(--teal-50);border-radius:6px;padding:3px 8px">ACTION</span>
    </div>`;
    _gsSelectedIdx = 0;
    highlightRow([...res.querySelectorAll('.gs-result-row')]);
    return;
  }

  // ── Natural-language food logging: "2 rotis and dal for lunch" ──
  if (_looksLikeFoodLog(q)) {
    res.innerHTML = '<div class="gs-empty" style="padding:20px;font-size:13px">Reading your meal…</div>';
    const preview = await _fetchFoodPreview(q);
    // user kept typing while we waited — drop this stale result
    if (((document.getElementById('global-search-input')?.value) || '').trim() !== q) return;
    if (preview && preview.items && preview.items.length) {
      _pendingFoodLog = preview;
      renderFoodLogPreview(res, preview);
      return;
    }
    // nothing matched → fall through to the normal history search
  }

  res.innerHTML = '<div class="gs-empty" style="padding:20px;font-size:13px">Searching…</div>';
  _gsTimer = setTimeout(async () => {
    const params = new URLSearchParams({q});
    if (_gsSearchType !== 'all') params.set('type', _gsSearchType);
    const r = await fetch(`/api/search?${params}`).then(r => r.json()).catch(() => null);
    if (!r) return;

    // Show date range tag if a date was parsed
    let dateTag = '';
    if (r.date_range) {
      const [from, to] = r.date_range;
      dateTag = `<div class="gs-date-tag">📅 Showing results for ${from === to ? from : from + ' → ' + to}</div>`;
    }

    if (r.total === 0) {
      res.innerHTML = dateTag + `<div class="gs-empty">
        <div class="gs-empty-icon">🔍</div>
        <div class="gs-empty-text">No results for "${escHtml(q)}"</div>
        <div class="gs-empty-sub">Try different keywords or a date range like "last week"</div>
      </div>`;
      return;
    }

    // Filter sections if type filter is active
    const sections = _gsSearchType === 'all' ? r.sections : r.sections.filter(s => s.type === _gsSearchType);

    res.innerHTML = dateTag + sections.map(s => {
      const rows = s.items.map(item => {
        let title='', meta='', badge='';

        if (s.type==='food')     { title=item.food_name; meta=`${item.date_key} · ${item.meal_type||''} · ${Math.round(item.calories||0)} kcal`; }
        if (s.type==='thought')  { title=item.content?.slice(0,90)+(item.content?.length>90?'…':''); meta=`${item.date_key} · ${item.mood ? moodEmoji(item.mood) : ''} ${item.mood||''}`; }
        if (s.type==='symptom')  { title=item.name; meta=`${item.date_key} · ${(item.time_of_day||'').replace('_',' ')} · ${item.severity}/10 severity${item.notes?' · '+item.notes:''}`; }
        if (s.type==='todo')     {
          title=item.title;
          meta=`${item.priority} priority${item.due_date?' · Due '+item.due_date:''}`;
          badge=`<span class="gs-result-badge ${item.status}">${item.status}</span>`;
        }
        if (s.type==='activity') { title=item.name||item.type; meta=`${item.date} · ${item.duration||0}min · ${item.calories||0} kcal${item.distance?' · '+item.distance+'km':''}`; }
        if (s.type==='report')   { title=item.filename||'Report'; meta=`${item.date||''} · ${item.severity||''}`; }
        if (s.type==='medicine') { title=item.name; meta=`${item.dosage} ${item.unit} · ${(item.frequency||'').replace('_',' ')}`; }

        return `<div class="gs-result-row" data-ev-click="closeGlobalSearch();switchView('${VIEW_MAP[s.type]||s.type}')">
          <div class="gs-result-icon">${TYPE_ICON[s.type]||'📄'}</div>
          <div class="gs-result-main">
            <div class="gs-result-title">${hlText(title, q)}</div>
            <div class="gs-result-meta">${escHtml(meta)}</div>
          </div>
          ${badge}
        </div>`;
      }).join('');
      return `<div class="gs-section-label">${s.icon} ${s.label}<span class="gs-section-count">${s.items.length}</span></div>${rows}`;
    }).join('');
    _gsSelectedIdx = -1;
  }, 200);
}

// ════════════════════════════════════════════════════════════
// NOTIFICATION CENTRE
// ════════════════════════════════════════════════════════════

const NOTIF_ICONS = {
  medicine:'💊', todo:'✅', hydration:'💧', sleep:'🌙', food:'🍽️',
  fitness:'🏃', symptom:'🩺', vital:'❤️', system:'🔔', refill:'⚠️'
};

let _notifFilter = 'all';
let _allNotifs   = [];

function setNotifFilter(f) {
  _notifFilter = f;
  document.querySelectorAll('.notif-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.f === f));
  renderNotifications();
}

async function loadNotifications() {
  // Preload reminder settings in background so panel is ready when opened
  loadReminderSettings().catch(() => {});
  const r = await fetch('/api/notifications?limit=100').then(r => r.json()).catch(() => null);
  if (!r) return;
  _allNotifs = r.notifications || [];
  updateNotifBadge(r.unread);
  const totalEl = document.getElementById('notif-unread-total');
  if (totalEl) totalEl.textContent = r.unread > 0 ? `${r.unread} unread` : '';
  renderNotifications();
}

function renderNotifications() {
  const el = document.getElementById('notif-list');
  if (!el) return;

  let items = _allNotifs;
  if (_notifFilter !== 'all') items = items.filter(n => n.type === _notifFilter);

  if (!items.length) {
    el.innerHTML = `<div class="notif-empty">
      <div class="notif-empty-icon">🔔</div>
      <div class="notif-empty-title">All clear!</div>
      <div class="notif-empty-sub">${_notifFilter === 'all' ? 'No notifications yet' : 'No ' + _notifFilter + ' notifications'}</div>
    </div>`;
    return;
  }

  // Group by date
  const byDate = {};
  items.forEach(n => {
    const d = n.created_at.slice(0,10);
    (byDate[d] = byDate[d]||[]).push(n);
  });

  const today = new Date().toISOString().slice(0,10);
  const yesterday = new Date(Date.now()-86400000).toISOString().slice(0,10);

  const NOTIF_STYLES = {
    medicine: {bg:'#EDF2F5', border:'#BFDBFE', icon:'💊'},
    refill:   {bg:'#FFFBEB', border:'#FDE68A', icon:'⚠️'},
    todo:     {bg:'#ECFDF5', border:'#A7F3D0', icon:'✅'},
    symptom:  {bg:'#FEF2F2', border:'#FECACA', icon:'🩺'},
    fitness:  {bg:'#F9EBE0', border:'#DDD6FE', icon:'🏃'},
    food:     {bg:'#FFF7ED', border:'#FED7AA', icon:'🍽️'},
    sleep:    {bg:'#EEF2FF', border:'#C7D2FE', icon:'🌙'},
    hydration:{bg:'#E0F2FE', border:'#BAE6FD', icon:'💧'},
    system:   {bg:'#F9FAFB', border:'#E5E7EB', icon:'🔔'},
  };

  el.innerHTML = Object.entries(byDate).map(([date, notifs]) => {
    const label = date === today ? 'Today' : date === yesterday ? 'Yesterday' : new Date(date+'T12:00:00').toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'});
    const rows = notifs.map(n => {
      const style = NOTIF_STYLES[n.type] || NOTIF_STYLES.system;
      const ago   = timeAgo(n.created_at);
      return `<div class="notif-row ${n.read?'':'unread'}" data-ev-click="markNotifRead('${n.id}')">
        <div class="notif-icon" style="background:${style.bg};border:1px solid ${style.border}">${NOTIF_ICONS[n.type]||style.icon}</div>
        <div class="notif-body">
          <div class="notif-title">${escHtml(n.title)}</div>
          ${n.body ? `<div class="notif-text">${escHtml(n.body)}</div>` : ''}
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0">
          <div class="notif-time">${ago}</div>
          ${!n.read ? '<div class="notif-unread-dot"></div>' : ''}
        </div>
      </div>`;
    }).join('');
    return `<div class="notif-date-group"><div class="notif-date-label">${label}</div>${rows}</div>`;
  }).join('');
}

function timeAgo(isoStr) {
  const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (diff < 60)   return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400)return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

async function markNotifRead(id) {
  const r = await fetch(`/api/notifications/${id}/read`, {method:'POST'}).then(r=>r.json()).catch(()=>null);
  if (r) updateNotifBadge(r.unread);
  loadNotifications();
}

async function markAllRead() {
  await fetch('/api/notifications/read-all', {method:'POST'});
  updateNotifBadge(0);
  loadNotifications();
}

function updateNotifBadge(count) {
  const badge = document.getElementById('nav-notif-badge');
  if (!badge) return;
  if (count > 0) { badge.textContent = count; badge.style.display = 'inline-block'; }
  else badge.style.display = 'none';
}

async function logNotification(type, title, body = '') {
  await fetch('/api/notifications', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({type, title, body})
  });
  // Refresh badge
  const r = await fetch('/api/notifications?unread=1').then(r=>r.json()).catch(()=>null);
  if (r) updateNotifBadge(r.unread);
}

// Check for low stock medicines and log notification
async function checkLowStock() {
  const r = await fetch('/api/medicines/low-stock').then(r=>r.json()).catch(()=>[]);
  const banner = document.getElementById('low-stock-banner');
  if (r.length > 0) {
    r.forEach(m => {
      logNotification('refill', `Refill needed: ${m.name}`,
        `Only ${m.days_left} days of supply remaining (${m.pill_count} pills left)`);
    });
    // Show banner on medicine page
    if (banner) {
      const names = r.map(m=>`<strong>${escHtml(m.name)}</strong> (${m.days_left}d left)`).join(', ');
      banner.innerHTML = `<div class="low-stock-banner-icon">⚠️</div><div class="low-stock-banner-text">Low stock: ${names}</div>`;
      banner.style.display = 'flex';
    }
  } else if (banner) banner.style.display = 'none';
}

// Poll unread count every 2 min
setInterval(async () => {
  const r = await fetch('/api/notifications?unread=1').then(r=>r.json()).catch(()=>null);
  if (r) updateNotifBadge(r.unread);
}, 120000);

// ════════════════════════════════════════════════════════════
// PROGRESS VIEW
// ════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════
// GOAL PROGRESS — Rich charts & per-metric analysis
// ════════════════════════════════════════════════════════════

let _progressData = null;
let _progressPeriod = 'month';

function setProgressPeriod(p) {
  _progressPeriod = p;
  document.querySelectorAll('.prog-period-btn').forEach(b => b.classList.toggle('active', b.dataset.period === p));
  if (_progressData) renderProgress(_progressData);
}

async function loadProgress() {
  const el = document.getElementById('progress-content');
  if (!el) return;
  el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--gray-400)"><div class="report-gen-spinner" style="margin:0 auto 12px"></div>Calculating your progress…</div>';
  const r = await fetch('/api/progress').then(r => r.json()).catch(() => null);
  if (!r) { el.innerHTML = '<div style="padding:40px;color:var(--gray-400)">Could not load progress data.</div>'; return; }
  _progressData = r;
  renderProgress(r);
  loadMoodSleepCorrelation();
  loadWeeklyDigest();
}

function renderProgress(r) {
  const el = document.getElementById('progress-content');
  if (!el) return;

  const p = _progressPeriod; // 'month' or 'week'
  const GOAL_LABELS = {lose_fast:'Lose weight fast 🔥',lose:'Lose weight 📉',maintain:'Maintain weight ⚖️',gain:'Gain muscle 📈',gain_fast:'Build mass 💪'};

  // ── Score calculations ──
  const workoutPct = p === 'month' ? (r.workouts?.frequency_pct||0) : Math.round((r.workouts?.daily?.slice(-7).filter(d=>d.cal>0).length||0)/7*100);
  const sleepAvg   = p === 'month' ? r.sleep?.avg_30 : r.sleep?.avg_7;
  const sleepPct   = sleepAvg ? Math.min(Math.round(sleepAvg/7.5*100),100) : 0;
  const habitPct   = r.habits?.completion_pct || 0;
  const calPct     = Math.min(r.nutrition?.adherence_pct||0, 100);
  const scores     = [workoutPct, sleepPct, habitPct, calPct].filter(s => s > 0);
  const hasData    = scores.length > 0;
  const overall    = hasData ? Math.round(scores.reduce((a,b)=>a+b)/scores.length) : 0;
  // No data yet → neutral, welcoming — never a red "Needs focus" on an empty week
  const overallColor = !hasData ? 'var(--gray-300)' : overall >= 75 ? '#22C55E' : overall >= 50 ? '#F59E0B' : '#EF4444';
  const overallLabel = !hasData ? 'Start logging to see your progress' : overall >= 75 ? 'On track! 🎯' : overall >= 50 ? 'Getting there 💪' : 'Needs focus 📋';

  // Update score strip
  const strip = document.getElementById('prog-score-strip');
  if (strip) {
    strip.style.display = 'flex';
    // Overall ring
    const ringEl = document.getElementById('psi-overall-ring');
    const r2 = 20, C = 2*Math.PI*r2;
    const offset = C - (overall/100)*C;
    if (ringEl) ringEl.innerHTML = `<svg width="56" height="56" viewBox="0 0 56 56">
      <circle cx="28" cy="28" r="${r2}" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="5"/>
      <circle cx="28" cy="28" r="${r2}" fill="none" stroke="${overallColor}" stroke-width="5"
        stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
        stroke-linecap="round" transform="rotate(-90 28 28)"/>
    </svg>
    <div class="prog-score-inner"><div class="prog-score-num">${overall}</div><div class="prog-score-sub">score</div></div>`;
    setText('psi-sleep',    sleepAvg ? sleepAvg+'h' : '—');
    setText('psi-workouts', r.workouts?.this_month + (p==='month'?' days':''));
    setText('psi-habits',   habitPct+'%');
    setText('psi-cals',     calPct+'%');
    const sub = document.getElementById('prog-subtitle');
    if (sub) sub.textContent = overallLabel;
  }

  // ── Build 30 or 7 days of data slices ──
  const daysSlice = d => p === 'week' ? (d||[]).slice(-7) : d;

  // Weight chart data
  const weights = r.weight_trend || [];
  const wMin = weights.length ? Math.min(...weights.map(w=>w.weight)) - 1 : 0;
  const wMax = weights.length ? Math.max(...weights.map(w=>w.weight)) + 1 : 100;

  // Build SVG weight chart
  let weightSVG = '';
  if (weights.length >= 2) {
    const W = 600, H = 80;
    const pts = weights.map((w, i) => {
      const x = i/(weights.length-1) * W;
      const y = H - ((w.weight - wMin)/(wMax - wMin||1)) * (H-12) - 6;
      return {x, y, w};
    });
    const path = pts.map((p,i) => (i===0?'M':'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
    const area = `M${pts[0].x},${H} ` + pts.map(p=>`L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ` L${pts[pts.length-1].x},${H} Z`;
    const dots = pts.map(p => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="var(--teal-500)" stroke="#fff" stroke-width="2" class="weight-dot"><title>${p.w.weight}kg · ${p.w.date}</title></circle>`).join('');
    const firstDate = weights[0]?.date?.slice(5) || '';
    const lastDate  = weights[weights.length-1]?.date?.slice(5) || '';
    weightSVG = `<div style="position:relative">
      <svg viewBox="0 0 ${W} ${H+20}" class="prog-weight-chart" preserveAspectRatio="none" style="width:100%;height:90px">
        <defs><linearGradient id="wGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--teal-400)" stop-opacity=".25"/><stop offset="100%" stop-color="var(--teal-400)" stop-opacity="0"/></linearGradient></defs>
        <path d="${area}" fill="url(#wGrad)"/>
        <path d="${path}" fill="none" stroke="var(--teal-500)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        ${dots}
        <text x="0" y="${H+14}" font-size="10" fill="#9CA3AF">${firstDate}</text>
        <text x="${W}" y="${H+14}" font-size="10" fill="#9CA3AF" text-anchor="end">${lastDate}</text>
        <text x="0" y="10" font-size="10" fill="#9CA3AF">${wMax.toFixed(1)}</text>
        <text x="0" y="${H-4}" font-size="10" fill="#9CA3AF">${wMin.toFixed(1)}</text>
      </svg>
    </div>`;
  } else {
    weightSVG = `<div style="padding:24px 0;text-align:center;color:var(--gray-300);font-size:13px">Log body metrics to see trend</div>`;
  }

  // Workout mini bars (30 days)
  const workoutDays  = daysSlice(r.workouts?.daily) || [];
  const maxCal = Math.max(...workoutDays.map(d=>d.cal), 1);
  const workoutBars  = workoutDays.map((d, i) => {
    const pct   = d.cal > 0 ? Math.max(Math.round((d.cal/maxCal)*100), 12) : 0;
    const color = d.cal > 0 ? 'var(--teal-500)' : 'var(--gray-100)';
    const label = i === 0 || i === workoutDays.length-1 ? d.date.slice(5) : '';
    return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;gap:2px">
      <div class="prog-mini-bar" style="height:${pct}%;background:${color};width:100%" title="${d.date}: ${d.cal} kcal"></div>
      <div style="font-size:8px;color:var(--gray-300);white-space:nowrap">${label}</div>
    </div>`;
  }).join('');

  // Sleep dots
  const sleepDays = daysSlice(r.sleep?.daily) || [];
  const SLEEP_COLORS = {1:'#EF4444',2:'#F59E0B',3:'#D1D5DB',4:'#34D399',5:'#4F8D74'};
  const sleepDots = sleepDays.map(s => {
    const h = Math.min(s.h/9, 1) * 100;
    return `<div class="prog-sleep-dot" style="height:${Math.max(h,8)}%;background:${SLEEP_COLORS[s.q]||'#D1D5DB'}" title="${s.date}: ${s.h}h · Quality ${s.q}/5"></div>`;
  }).join('');
  const noSleepMsg = sleepDays.length === 0 ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">No sleep data — log from Thoughts page</div>` : '';

  // Calorie adherence bars
  const calDays = daysSlice(r.nutrition?.daily) || [];
  // Null until the profile can produce a TDEE. Without it there's no "% of
  // goal" to colour a bar against, so scale to the week's own range instead.
  const targetCal = r.nutrition?.target_daily || null;
  const calMax    = Math.max(...calDays.map(d => d.cal || 0), 1);
  const calBars = calDays.map((d,i) => {
    const pct = targetCal
      ? (d.cal > 0 ? Math.min(Math.round((d.cal/targetCal)*100), 150) : 0)
      : Math.round((d.cal || 0) / calMax * 100);
    const color = !targetCal ? 'var(--gray-200)'
      : pct > 115 ? '#EF4444' : pct > 95 ? '#22C55E' : pct > 70 ? '#F59E0B' : 'var(--gray-200)';
    const label = targetCal ? `${d.date}: ${d.cal} kcal (${pct}% of goal)` : `${d.date}: ${d.cal} kcal`;
    return `<div class="prog-cal-bar ${targetCal && pct>115?'over':''}" style="height:${Math.max(pct,4)}%;background:${color}" title="${label}"></div>`;
  }).join('');
  const noCalMsg = calDays.every(d=>d.cal===0) ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">Log meals to see calorie data</div>` : '';

  // Habit breakdown
  const habits = r.habits?.detail || [];
  const habitRows = habits.map(h => `
    <div class="prog-habit-row">
      <div class="prog-habit-emoji">${h.emoji}</div>
      <div class="prog-habit-name">${escHtml(h.name)}</div>
      <div class="prog-habit-bar-wrap">
        <div class="prog-habit-bar" style="width:${h.pct}%;background:${h.color}"></div>
      </div>
      <div class="prog-habit-pct">${h.pct}%</div>
      <div class="prog-habit-streak">🔥${h.streak}</div>
    </div>`).join('');
  const noHabitMsg = habits.length === 0 ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">No habits tracked — add habits on the Consistency page</div>` : '';

  // Status badge helper.
  //
  // `has` is not optional in spirit: with no data every pct is 0, so an empty
  // account used to get four red "📋 Needs work" badges — while the header one
  // line above correctly said "Start logging to see your progress". The page
  // scolded a user for not having used an app they'd just installed, and
  // contradicted itself doing it. No data, no verdict; the sections already
  // carry their own "start logging" empty states.
  const badge = (pct, good=70, warn=40, has=true) => {
    if (!has) return '';
    const cls = pct >= good ? 'good' : pct >= warn ? 'warn' : 'bad';
    const txt = pct >= good ? '✅ On target' : pct >= warn ? '⚠️ Almost there' : '📋 Needs work';
    return `<span class="prog-status-badge ${cls}">${txt}</span>`;
  };

  const latest = weights[weights.length-1];

  el.innerHTML = `
  <div class="prog-sections">

    <!-- Goal header -->
    <div class="prog-section">
      <div class="prog-section-head">
        <div class="prog-section-title">🎯 Current Goal</div>
        <!-- Was "— kcal/day · —g protein" under a heading called "Current
             Goal": a section that states nothing and offers no way to set one.
             Show the targets only when they exist; otherwise the body below
             becomes a way in. -->
        ${r.targets?.target_calories
          ? `<div class="prog-section-meta">${r.targets.target_calories} kcal/day · ${r.targets.protein_g||'—'}g protein</div>`
          : ''}
      </div>
      <div class="prog-section-body" style="display:flex;align-items:center;gap:20px">
        ${r.profile?.goal
          ? `<div style="font-size:22px;font-weight:700;color:var(--gray-900)">${GOAL_LABELS[r.profile.goal]||''}</div>`
          : `<a href="#" data-ev-click="switchView('food');return false"
                style="font-size:14px;font-weight:600;color:var(--teal-600)">Set your goal →</a>`}
        ${latest ? `<div style="font-size:13px;color:var(--gray-500)">Current weight: <strong>${latest.weight}kg</strong> · BMI: <strong>${latest.bmi||'—'}</strong></div>` : ''}
        <div style="margin-left:auto;font-size:13px;color:${overallColor};font-weight:700">${overallLabel}</div>
      </div>
    </div>

    <!-- Weight + Workouts row -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">⚖️ Weight Trend</div>
          ${latest ? badge(r.profile?.goal==='lose'||r.profile?.goal==='lose_fast' ? (weights.length>=2 && weights[0].weight > latest.weight ? 100 : 20) : 70) : ''}
        </div>
        <div class="prog-section-body">${weightSVG}</div>
      </div>

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🏃 Workout Frequency</div>
          ${badge(workoutPct, 70, 40, !!(r.workouts?.this_month || r.workouts?.total))}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'EB Garamond',serif;color:var(--gray-900)">${p==='month'?r.workouts?.this_month:workoutDays.filter(d=>d.cal>0).length}</span>
            <span style="font-size:14px;color:var(--gray-400)">active days · target 4/week</span>
          </div>
          <div style="display:flex;align-items:flex-end;gap:2px;height:50px">${workoutBars}</div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:2px">
            <span>${workoutDays[0]?.date?.slice(5)||''}</span><span>${workoutDays[workoutDays.length-1]?.date?.slice(5)||''}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Sleep + Calories row -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🌙 Sleep Consistency</div>
          ${badge(sleepPct, 90, 70, sleepDays.length > 0)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'EB Garamond',serif;color:var(--gray-900)">${sleepAvg||'—'}</span>
            <span style="font-size:14px;color:var(--gray-400)">h avg · target 7.5h</span>
          </div>
          ${noSleepMsg}
          ${sleepDays.length ? `<div style="display:flex;align-items:flex-end;gap:3px;height:60px">${sleepDots}</div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:4px">
            <span>😩 Poor</span>
            <span style="display:flex;gap:8px">
              <span style="width:10px;height:10px;border-radius:2px;background:#EF4444;display:inline-block"></span>Poor
              <span style="width:10px;height:10px;border-radius:2px;background:#34D399;display:inline-block"></span>Good
              <span style="width:10px;height:10px;border-radius:2px;background:#4F8D74;display:inline-block"></span>Great
            </span>
          </div>` : ''}
        </div>
      </div>

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🍽️ Calorie Adherence</div>
          ${badge(calPct, 70, 40, !!targetCal && !noCalMsg)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'EB Garamond',serif;color:var(--gray-900)">${calPct}%</span>
            <span style="font-size:14px;color:var(--gray-400)">of daily goal (${targetCal} kcal)</span>
          </div>
          ${noCalMsg}
          ${!noCalMsg ? `<div style="position:relative">
            <div style="display:flex;align-items:flex-end;gap:2px;height:60px">${calBars}</div>
            <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:2px">
              <span>${calDays[0]?.date?.slice(5)||''}</span>
              <span style="display:flex;gap:8px"><span style="color:#22C55E">■ On target</span><span style="color:#EF4444">■ Over</span><span style="color:var(--gray-300)">■ Not logged</span></span>
              <span>${calDays[calDays.length-1]?.date?.slice(5)||''}</span>
            </div>
          </div>` : ''}
        </div>
      </div>
    </div>

    <!-- Habit breakdown -->
    <div class="prog-section">
      <div class="prog-section-head">
        <div class="prog-section-title">⭐ Habit Completion</div>
        ${badge(habitPct, 70, 40, habits.length > 0)}
      </div>
      <div class="prog-section-body">
        ${noHabitMsg}
        ${habits.length ? `<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:16px">
          <span style="font-size:32px;font-weight:800;font-family:'EB Garamond',serif;color:var(--gray-900)">${habitPct}%</span>
          <span style="font-size:14px;color:var(--gray-400)">overall · ${r.habits?.total||0} habits · ${r.habits?.done_count||0} total check-ins</span>
        </div>
        <div class="prog-habit-rows">${habitRows}</div>` : ''}
      </div>
    </div>

    ${r.refill_alerts?.length ? `
    <div class="prog-section" style="border-color:#F59E0B">
      <div class="prog-section-head">
        <div class="prog-section-title">💊 Medicine Refill Alerts</div>
        <span class="prog-status-badge bad">⚠️ Action needed</span>
      </div>
      <div class="prog-section-body">
        ${r.refill_alerts.map(m=>`
          <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--gray-50)">
            <span style="font-size:20px">${m.icon||'💊'}</span>
            <div style="flex:1"><div style="font-size:14px;font-weight:600">${escHtml(m.name)}</div><div style="font-size:12px;color:var(--red-500)">${m.pill_count} pills · ${m.days_left} days remaining</div></div>
            <button class="btn-outline" style="font-size:12px;padding:5px 12px" data-ev-click="openRestockModal('${m.id}','${escHtml(m.name)}',${m.pill_count},${m.pills_per_dose||1},${m.refill_threshold||7})">Restock →</button>
          </div>`).join('')}
      </div>
    </div>` : ''}

  </div>`;
}


// ════════════════════════════════════════════════════════════
// WEEKLY HEALTH REPORT
// ════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════
// WEEKLY HEALTH REPORT — Rich in-app display + PDF export
// ════════════════════════════════════════════════════════════

async function loadReport() {
  const el = document.getElementById('report-content');
  if (!el) return;
  el.innerHTML = `<div class="report-generating">
    <div class="report-gen-spinner"></div>
    <div class="report-gen-text">Analysing your last 7 days…</div>
  </div>`;

  const r = await fetch('/api/report/weekly').then(r=>r.json()).catch(()=>null);
  if (!r) { el.innerHTML = '<div style="padding:40px;color:var(--gray-400)">Could not load report data.</div>'; return; }

  const Q_LABEL = {1:'Very Poor',2:'Poor',3:'Fair',4:'Good',5:'Excellent'};
  const Q_EMOJI = {1:'😩',2:'😕',3:'😐',4:'😊',5:'😴'};
  const GOAL_LABELS = {lose_fast:'Lose weight fast',lose:'Lose weight',maintain:'Maintain weight',gain:'Gain muscle',gain_fast:'Build mass'};

  // There is deliberately no "health score" here.
  //
  // This page is footed "For your doctor:" and has a Download PDF button, so
  // whatever sits on it gets read as an assessment. A single number averaging
  // sleep, workouts, calories and habits — with no vitals, no medication
  // adherence, no symptoms, nothing clinical in it at all — is not an
  // assessment of anyone's health, and printing it next to that footer invited
  // a doctor to read it as one. It also scored *not tracking* as failing: the
  // fitness term counted 0 workouts as 0/100, so a user who logs 8h of sleep
  // and doesn't use fitness tracking scored 50 and was labelled "Fair".
  //
  // The raw metrics below say more, and each carries its own denominator, so a
  // doctor can see what the numbers rest on.

  // Build the period label
  const d1 = new Date(r.period?.start + 'T12:00:00');
  const d2 = new Date(r.period?.end + 'T12:00:00');
  const periodStr = d1.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' – ' +
                    d2.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
  const generatedStr = new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'});

  // Metric bar helper
  const metricBar = (val, max, color) => {
    const pct = Math.min(Math.round((val/max)*100),100);
    return `<div class="rpt-bar-wrap"><div class="rpt-bar-fill" style="width:${pct}%;background:${color}"></div></div>`;
  };

  el.innerHTML = `
  <!-- Action bar -->
  <div class="report-action-bar">
    <div class="report-action-bar-left">
      <div class="report-period-chip">📅 ${periodStr}</div>
    </div>
    <button class="btn-primary" data-ev-click="printReport()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
      Download PDF
    </button>
  </div>

  <!-- Printable report starts here -->
  <div id="printable-report" class="rpt-doc">

    <!-- Header -->
    <div class="rpt-header">
      <div class="rpt-header-left">
        <div class="rpt-patient-name">${escHtml(r.profile?.name||'Health Report')}</div>
        <div class="rpt-period">Weekly Summary · ${periodStr}</div>
        <div class="rpt-generated">Generated ${generatedStr}</div>
        <div class="rpt-goal-chip">${GOAL_LABELS[r.profile?.goal]||'—'}</div>
      </div>
      <div class="rpt-header-right"></div>
    </div>

    <!-- 6-metric grid -->
    <div class="rpt-grid">

      <!-- Sleep -->
      <div class="rpt-section">
        <div class="rpt-section-head">🌙 Sleep</div>
        <div class="rpt-big">${r.sleep?.avg_hours ?? '—'}<span class="rpt-unit">h avg</span></div>
        <div class="rpt-sub">${r.sleep?.nights||0} nights logged</div>
        ${r.sleep?.avg_hours ? metricBar(r.sleep.avg_hours, 9, '#818CF8') : ''}
        <div class="rpt-detail-rows">
          ${r.sleep?.avg_quality ? `<div class="rpt-detail-row"><span>Quality</span><span>${Q_EMOJI[Math.round(r.sleep.avg_quality)]} ${Q_LABEL[Math.round(r.sleep.avg_quality)]}</span></div>` : ''}
          <!-- "Guideline", not "Target": the user never set 7.5h, so calling it
               theirs — and then marking them "Below target" against it — is
               putting words in their mouth on a page their doctor reads. -->
          <div class="rpt-detail-row"><span>Common guideline</span><span>7–9h / night</span></div>
        </div>
      </div>

      <!-- Fitness -->
      <div class="rpt-section">
        <div class="rpt-section-head">🏃 Fitness</div>
        <div class="rpt-big">${r.fitness?.workout_days??0}<span class="rpt-unit">active days</span></div>
        <div class="rpt-sub">${r.fitness?.activities||0} workouts completed</div>
        ${metricBar(r.fitness?.workout_days||0, 7, '#34D399')}
        <div class="rpt-detail-rows">
          <div class="rpt-detail-row"><span>Calories burned</span><span>${(r.fitness?.calories_burned||0).toLocaleString()} kcal</span></div>
          <!-- The old status row fired whenever workout_days was non-null,
               which is always: it's 0, not null. So someone who simply doesn't
               use fitness tracking got stamped "Below target" against a goal
               they never set. Only speak when something was actually logged. -->
          ${r.fitness?.activities ? `<div class="rpt-detail-row"><span>Common guideline</span><span>150 min / week</span></div>` : ''}
        </div>
      </div>

      <!-- Nutrition -->
      <div class="rpt-section">
        <div class="rpt-section-head">🍽️ Nutrition</div>
        <div class="rpt-big">${r.nutrition?.adherence_pct != null ? Math.round(r.nutrition.adherence_pct)+'%' : '—'}<span class="rpt-unit">adherence</span></div>
        <div class="rpt-sub">${(r.nutrition?.calories_eaten||0).toLocaleString()} kcal consumed</div>
        ${r.nutrition?.adherence_pct != null ? metricBar(r.nutrition.adherence_pct, 100, '#FB923C') : ''}
        <div class="rpt-detail-rows">
          <!-- target_calories is null until the user gives us weight/height/
               age/gender. It used to render "0 kcal/day", which reads like a
               measurement rather than a blank. Say it's not set. -->
          ${r.nutrition?.target ? `
          <div class="rpt-detail-row"><span>Weekly target</span><span>${(r.nutrition.weekly_target||0).toLocaleString()} kcal</span></div>
          <div class="rpt-detail-row"><span>Daily target</span><span>${r.nutrition.target.toLocaleString()} kcal/day</span></div>`
          : `<div class="rpt-detail-row"><span>Daily target</span><span>Not set</span></div>`}
          ${r.nutrition?.avg_hydration_ml ? `<div class="rpt-detail-row"><span>Avg hydration</span><span>${r.nutrition.avg_hydration_ml} ml/day</span></div>` : ''}
        </div>
      </div>

      <!-- Habits -->
      <div class="rpt-section">
        <div class="rpt-section-head">⭐ Habits</div>
        <div class="rpt-big">${r.habits?.completion_pct != null ? r.habits.completion_pct+'%' : '—'}<span class="rpt-unit">completion</span></div>
        <div class="rpt-sub">${r.habits?.total||0} habits tracked</div>
        ${r.habits?.completion_pct != null ? metricBar(r.habits.completion_pct, 100, '#A78BFA') : ''}
        <div class="rpt-detail-rows">
          <div class="rpt-detail-row"><span>Done</span><span>${r.habits?.done_count||0} of ${(r.habits?.total||0)*7} check-ins</span></div>
          ${r.habits?.completion_pct != null ? `<div class="rpt-detail-row ${r.habits.completion_pct>=70?'rpt-row--good':'rpt-row--warn'}"><span>Status</span><span>${r.habits.completion_pct>=70?'✅ Great':'⚠️ Keep going'}</span></div>` : ''}
        </div>
      </div>

      <!-- Symptoms -->
      <div class="rpt-section">
        <div class="rpt-section-head">🩺 Symptoms</div>
        <div class="rpt-big">${r.symptoms?.length??0}<span class="rpt-unit">unique</span></div>
        <div class="rpt-sub">this week</div>
        <div class="rpt-symptom-list">
          ${r.symptoms?.length ? r.symptoms.map(s => `
            <div class="rpt-symptom-row">
              <span class="rpt-symptom-name">${escHtml(s.name)}</span>
              <span class="rpt-symptom-count">×${s.count}</span>
            </div>`).join('') : '<div style="color:var(--gray-400);font-size:13px;margin-top:8px">No symptoms logged ✅</div>'}
        </div>
      </div>

      <!-- Body & Vitals -->
      <div class="rpt-section">
        <div class="rpt-section-head">⚖️ Body & Vitals</div>
        ${r.body?.weight_kg ? `
          <div class="rpt-big">${r.body.weight_kg}<span class="rpt-unit">kg</span></div>
          <div class="rpt-sub">BMI: ${r.body.bmi ?? '—'}</div>` :
          '<div class="rpt-sub" style="margin-top:8px">No body metrics logged</div>'}
        <div class="rpt-detail-rows" style="margin-top:10px">
          ${r.vitals?.blood_pressure ? `<div class="rpt-detail-row"><span>Blood Pressure</span><span>${r.vitals.blood_pressure.value1}/${r.vitals.blood_pressure.value2} mmHg</span></div>` : ''}
          ${r.vitals?.blood_sugar ? `<div class="rpt-detail-row"><span>Blood Sugar</span><span>${r.vitals.blood_sugar.value1} mg/dL</span></div>` : ''}
          ${r.vitals?.heart_rate ? `<div class="rpt-detail-row"><span>Heart Rate</span><span>${r.vitals.heart_rate.value1} bpm</span></div>` : ''}
          ${!r.vitals?.blood_pressure && !r.vitals?.blood_sugar && !r.vitals?.heart_rate ? '<div style="color:var(--gray-400);font-size:13px">No vitals recorded</div>' : ''}
        </div>
      </div>

    </div>

    <!-- Doctor note footer -->
    <div class="rpt-footer">
      <div class="rpt-footer-note">
        <strong>For your doctor:</strong> This is a personal health summary generated by Arogo.
        Data is self-reported and should be reviewed alongside clinical assessments.
      </div>
      <div class="rpt-footer-brand">Arogo · ${generatedStr}</div>
    </div>

  </div><!-- /printable-report -->
  `;
}

function printReport() {
  const el = document.getElementById('printable-report');
  if (!el) { showToast('Click "Generate Report" first', 'error'); return; }

  // Build a full-CSS print window
  const win = window.open('', '_blank', 'width=900,height=700');
  win.document.write(`<!DOCTYPE html><html><head>
<title>Weekly Health Report</title>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Manrope:wght@400;500;600;700&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Manrope',sans-serif;background:#fff;color:#1a1a1a;padding:28px}
  .rpt-doc{max-width:820px;margin:0 auto}

  /* Header */
  .rpt-header{display:flex;align-items:flex-start;justify-content:space-between;
    background:linear-gradient(135deg,#20362D,#25443A);border-radius:12px;
    padding:28px 32px;margin-bottom:24px;color:#fff}
  .rpt-patient-name{font-size:24px;font-weight:700;margin-bottom:6px}
  .rpt-period{font-size:14px;color:rgba(255,255,255,.6);margin-bottom:3px}
  .rpt-generated{font-size:12px;color:rgba(255,255,255,.4);margin-bottom:10px}
  .rpt-goal-chip{display:inline-block;padding:3px 12px;border-radius:99px;
    background:rgba(255,255,255,.1);font-size:12px;color:rgba(255,255,255,.7)}

  /* Grid */
  .rpt-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px}
  .rpt-section{border:1px solid #e5e7eb;border-radius:10px;padding:18px;break-inside:avoid}
  .rpt-section-head{font-size:11px;font-weight:700;text-transform:uppercase;
    letter-spacing:.07em;color:#6b7280;margin-bottom:10px}
  .rpt-big{font-size:30px;font-weight:800;color:#111;line-height:1}
  .rpt-unit{font-size:14px;font-weight:500;color:#6b7280;margin-left:4px}
  .rpt-sub{font-size:12px;color:#9ca3af;margin-top:3px;margin-bottom:8px}
  .rpt-bar-wrap{height:6px;background:#f3f4f6;border-radius:99px;overflow:hidden;margin:8px 0}
  .rpt-bar-fill{height:100%;border-radius:99px}
  .rpt-detail-rows{display:flex;flex-direction:column;gap:5px;margin-top:8px}
  .rpt-detail-row{display:flex;justify-content:space-between;font-size:12px;color:#374151}
  .rpt-detail-row span:first-child{color:#6b7280}
  .rpt-row--good span:last-child{color:#5A9E70;font-weight:600}
  .rpt-row--warn span:last-child{color:#E0A34E;font-weight:600}
  .rpt-symptom-list{display:flex;flex-direction:column;gap:4px;margin-top:8px}
  .rpt-symptom-row{display:flex;justify-content:space-between;font-size:12.5px}
  .rpt-symptom-name{color:#374151}
  .rpt-symptom-count{color:#ef4444;font-weight:600}

  /* Footer */
  .rpt-footer{border-top:1px solid #e5e7eb;padding-top:14px;
    display:flex;justify-content:space-between;align-items:flex-start;gap:20px}
  .rpt-footer-note{font-size:11.5px;color:#6b7280;flex:1;line-height:1.6}
  .rpt-footer-brand{font-size:11px;color:#9ca3af;white-space:nowrap;padding-top:2px}

  @media print{
    body{padding:0}
    @page{size:A4;margin:16mm}
    .rpt-doc{max-width:100%}
  }
</style>
</head><body>
<div class="rpt-doc">${el.innerHTML}</div>
</body></html>`);
  win.document.close();
  setTimeout(() => { win.print(); }, 600);
}

// ════════════════════════════════════════════════════════════
// MEDICINE STOCK — Check on app load
// ════════════════════════════════════════════════════════════
// Patch loadMedicines to check low stock after loading
const __loadMeds = loadMedicines;
loadMedicines = async function() {
  await __loadMeds.apply(this, arguments);
  checkLowStock();
};

// ════════════════════════════════════════════════════════════
// MEDICINE STOCK — Restock modal + low stock banner
// ════════════════════════════════════════════════════════════

function openRestockModal(id, name, pillCount, pillsPerDose, threshold) {
  document.getElementById('restock-med-id').value  = id;
  document.getElementById('restock-med-name').textContent = name;
  document.getElementById('restock-pill-count').value    = pillCount;
  document.getElementById('restock-pills-per-dose').value = pillsPerDose;
  document.getElementById('restock-threshold').value      = threshold;
  updateRestockPreview();
  document.getElementById('restock-modal-overlay').style.display = 'flex';
}

function stepRestock(delta) {
  const el = document.getElementById('restock-pill-count');
  if (!el) return;
  el.value = Math.max(0, (parseInt(el.value) || 0) + delta);
  updateRestockPreview();
}

function updateRestockPreview() {
  const pills  = parseInt(document.getElementById('restock-pill-count')?.value) || 0;
  const ppd    = parseInt(document.getElementById('restock-pills-per-dose')?.value) || 1;
  const prev   = document.getElementById('restock-days-preview');
  if (!prev) return;
  if (pills === 0) { prev.style.display = 'none'; return; }
  const days = Math.floor(pills / ppd);
  prev.style.display = 'block';
  prev.textContent = `💊 ${pills} pills = ${days} day${days!==1?'s':''} of supply`;
}

async function saveRestock() {
  const id        = document.getElementById('restock-med-id')?.value;
  const pillCount = parseInt(document.getElementById('restock-pill-count')?.value) || 0;
  const ppd       = parseInt(document.getElementById('restock-pills-per-dose')?.value) || 1;
  const threshold = parseInt(document.getElementById('restock-threshold')?.value) || 7;
  if (!id) return;
  const r = await fetch(`/api/medicines/${id}/stock`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ pill_count: pillCount, pills_per_dose: ppd, refill_threshold: threshold })
  }).then(r => r.json()).catch(() => null);
  if (r?.success) {
    showToast(`Stock updated — ${Math.floor(pillCount/ppd)} days of supply`, 'success');
    closeModal('restock-modal-overlay');
    loadMedicines();
  } else {
    showToast('Failed to save stock', 'error');
  }
}

async function checkLowStock() {
  const r = await fetch('/api/medicines/low-stock').then(r => r.json()).catch(() => []);
  const banner   = document.getElementById('med-low-stock-banner');
  const itemsEl  = document.getElementById('lsab-items');
  if (!banner || !itemsEl) return;
  if (!r.length) { banner.style.display = 'none'; return; }
  banner.style.display = 'flex';
  itemsEl.innerHTML = r.map(m =>
    `<span class="lsab-item">${m.icon||'💊'} ${escHtml(m.name)} — ${m.days_left}d left</span>`
  ).join('');
  // Log one notification per low-stock medicine (only if not already logged today)
  r.forEach(m => {
    logNotification('refill', `Refill needed: ${m.name}`,
      `Only ${m.days_left} day${m.days_left!==1?'s':''} of supply remaining`);
  });
}

// ════════════════════════════════════════════════════════════
// SCHEDULED DAILY NUDGES
// These fire once per session at specified times and log to
// the notification centre so they appear in the unified feed.
// ════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════
// REMINDER SETTINGS
// The reminders themselves are fired server-side by scheduler.py — this is
// only the settings UI. The client used to run its own reminder loop beside
// the server's, which meant two notifications for one dose whenever the tab
// happened to be open. See the notes on setupPushSubscription.
// ════════════════════════════════════════════════════════════

let _remSettings = null;  // cached settings

async function loadReminderSettings() {
  const s = await fetch('/api/reminders/settings').then(r => r.json()).catch(() => null);
  if (s) _remSettings = s;
  return s;
}

// ── Reminder settings UI ──────────────────────────────────────
function toggleReminderSettings() {
  const panel = document.getElementById('reminder-settings-panel');
  if (!panel) return;
  const showing = panel.style.display !== 'none';
  panel.style.display = showing ? 'none' : 'block';
  if (!showing) loadReminderSettingsUI();
}

async function loadReminderSettingsUI() {
  const s = await loadReminderSettings();
  if (!s) return;

  // Permission badge
  const badge = document.getElementById('notif-permission-badge');
  if (badge) {
    if (!('Notification' in window)) {
      badge.textContent = 'Not supported';
      badge.style.background = '#FEE2E2'; badge.style.color = '#DC2626';
    } else if (Notification.permission === 'granted') {
      badge.textContent = '🔔 Notifications on';
      badge.style.background = '#DCFCE7'; badge.style.color = '#468A5B';
    } else {
      badge.innerHTML = '<a href="#" data-ev-click="requestNotifPermission();return false" style="color:inherit">Enable notifications →</a>';
      badge.style.background = '#FEF3C7'; badge.style.color = '#92400E';
    }
  }

  // Populate toggles and inputs
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') el.checked = Boolean(val);
    else el.value = val;
  };

  set('rs-water-enabled',   s.water_enabled);
  set('rs-water-interval',  s.water_interval_h);
  set('rs-water-start',     s.water_start);
  set('rs-water-end',       s.water_end);
  set('rs-habit-enabled',   s.habit_reminder_enabled);
  set('rs-habit-time',      s.habit_reminder_time);
  set('rs-sleep-enabled',   s.sleep_reminder_enabled);
  set('rs-sleep-time',      s.sleep_reminder_time);
  set('rs-mood-enabled',    s.mood_reminder_enabled);
  set('rs-mood-time',       s.mood_reminder_time);
  set('rs-digest-enabled',  s.weekly_digest_enabled ?? 1);
  set('rs-caregiver-digest-enabled', s.caregiver_digest_enabled ?? 1);

  // Show/hide section bodies based on toggle state
  ['water','habit','sleep','mood'].forEach(key => {
    const enabled = document.getElementById(`rs-${key}-enabled`)?.checked;
    const body    = document.getElementById(`rs-${key}-body`);
    if (body) body.style.display = enabled ? 'block' : 'none';
  });
}

async function saveReminderSettings() {
  const get = id => {
    const el = document.getElementById(id);
    if (!el) return null;
    return el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
  };

  const settings = {
    water_enabled:           get('rs-water-enabled'),
    water_interval_h:        parseFloat(get('rs-water-interval') || 2),
    water_start:             get('rs-water-start'),
    water_end:               get('rs-water-end'),
    habit_reminder_enabled:  get('rs-habit-enabled'),
    habit_reminder_time:     get('rs-habit-time'),
    sleep_reminder_enabled:  get('rs-sleep-enabled'),
    sleep_reminder_time:     get('rs-sleep-time'),
    mood_reminder_enabled:   get('rs-mood-enabled'),
    mood_reminder_time:      get('rs-mood-time'),
    weekly_digest_enabled:   get('rs-digest-enabled'),
    caregiver_digest_enabled: get('rs-caregiver-digest-enabled'),
  };

  const r = await fetch('/api/reminders/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(settings),
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    _remSettings = r.settings;
    showToast('Reminder settings saved', 'success');
    // Show/hide section bodies
    ['water','habit','sleep','mood'].forEach(key => {
      const enabled = document.getElementById(`rs-${key}-enabled`)?.checked;
      const body    = document.getElementById(`rs-${key}-body`);
      if (body) body.style.display = enabled ? 'block' : 'none';
    });
  }
}





// ════════════════════════════════════════════════════════════
// SLEEP VIEW — standalone page
// ════════════════════════════════════════════════════════════
async function loadSleepView() {
  const el = document.getElementById('sleep-view-content');
  if (!el) return;

  el.innerHTML = `
    <div class="today-panel" id="sleep-focal" style="display:none"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:20px">

      <!-- Log form -->
      <div class="panel">
        <div class="panel-header">
          <h2 class="panel-title">Log sleep</h2>
        </div>
        <div style="padding:16px 20px 20px">

          <!-- Duration-first: lead with how long you slept -->
          <div id="sleep-dur-wrap" class="sleep-dur--good">
            <div class="sleep-dur-head">
              <div class="stp-section-label" style="margin-bottom:6px">How long did you sleep?</div>
              <div class="sleep-dur-readout" id="sleep-dur-readout">7h 30m</div>
              <div class="sleep-dur-caption" id="sleep-dur-caption"></div>
            </div>
            <div class="sleep-dur-control">
              <button type="button" class="sleep-dur-step" id="sleep-dur-minus" aria-label="15 minutes less (hold for 30-minute jumps)">−</button>
              <input type="range" class="sleep-dur-range" id="sleep-dur-range"
                     min="180" max="720" step="15" value="450"
                     data-ev-input="sleepDurDrag(this.value)" aria-label="Sleep duration">
              <button type="button" class="sleep-dur-step" id="sleep-dur-plus" aria-label="15 minutes more (hold for 30-minute jumps)">+</button>
            </div>
            <div class="sleep-dur-ticks"><span>3h</span><span>5h</span><span>7h</span><span>9h</span><span>12h</span></div>

            <!-- Exact times, on demand -->
            <button type="button" class="sleep-exact-toggle" id="sleep-exact-toggle"
                    aria-expanded="false" data-ev-click="toggleSleepExact()">
              <span class="chev">›</span> Set exact times
            </button>
            <div class="sleep-exact-row" id="sleep-exact-row" style="display:none">
              <div class="sleep-exact-field">
                <label>🌙 Bedtime</label>
                <input type="time" id="sleep-bed-time" data-ev-input="sleepExactChanged('bed')">
              </div>
              <div class="sleep-exact-field">
                <label>☀️ Wake time</label>
                <input type="time" id="sleep-wake-time" data-ev-input="sleepExactChanged('wake')">
              </div>
            </div>
          </div>

          <!-- Quality -->
          <div style="margin:16px 0 10px">
            <div class="stp-section-label">Sleep quality</div>
            <div class="sdial-quality-row" id="sleep-q-sv">
              ${[
                {q:1,emoji:'😩',label:'Terrible'},
                {q:2,emoji:'😕',label:'Poor'},
                {q:3,emoji:'😐',label:'Okay'},
                {q:4,emoji:'😊',label:'Good'},
                {q:5,emoji:'😴',label:'Great'},
              ].map(({q,emoji,label}) => `
                <button class="sdial-q-btn${q===4?' active':''}" data-q="${q}"
                        data-ev-click="selectSleepQ(${q},'sv')">
                  <span class="sdial-q-emoji">${emoji}</span>
                  <span class="sdial-q-label">${label}</span>
                </button>`).join('')}
            </div>
          </div>

          <!-- Notes -->
          <div style="margin-bottom:14px">
            <div class="stp-section-label">Notes <span style="font-weight:400;text-transform:none;letter-spacing:0;color:var(--gray-400)">(optional)</span></div>
            <input type="text" class="form-input" id="sleep-notes-sv"
                   placeholder="e.g. woke up once, vivid dreams"
                   style="font-size:13px">
          </div>

          <button class="btn-primary" style="width:100%;font-size:14px;font-weight:600"
                  data-ev-click="saveSleepLogFromView()">
            Save sleep log
          </button>
        </div>
      </div>

      <!-- Stats + history -->
      <div class="panel" id="sleep-stats-card">
        <div class="panel-header">
          <h2 class="panel-title">Last 30 nights</h2>
        </div>
        <div id="sleep-summary-strip" style="padding:14px 20px 4px">
          <div style="color:var(--gray-400);font-size:13px;text-align:center;padding:20px 0">No data yet</div>
        </div>
        <div id="sleep-history-sv" style="padding:0 20px 16px"></div>
      </div>
    </div>

    <!-- Trend chart -->
    <div class="panel" id="sleep-trend-card" style="padding:18px 20px 20px;display:none">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:4px">
        <h2 class="panel-title">Duration trend</h2>
        <div id="sleep-trend-badge"></div>
      </div>
      <div style="font-size:12px;color:var(--gray-400);margin-bottom:14px" id="sleep-trend-sub"></div>
      <div style="position:relative;height:180px"><canvas id="sleep-chart"></canvas></div>
      <div style="display:flex;gap:16px;margin-top:12px;flex-wrap:wrap" id="sleep-week-strip"></div>
    </div>`;

  window._svQuality = 4;
  initSleepEntry();          // sets duration + wake anchor from the user's usual
  loadSleepTrend();
  renderSleepFocal();
}

async function renderSleepFocal() {
  const el = document.getElementById('sleep-focal');
  if (!el) return;
  const logs = await fetch('/api/sleep?days=7', {cache: 'no-store'}).then(r => r.json()).catch(() => []);
  if (!Array.isArray(logs) || logs.length === 0) { el.style.display = 'none'; return; }
  el.style.display = 'flex';
  const sorted = [...logs].sort((a, b) => (b.date_key || '').localeCompare(a.date_key || ''));
  const last = sorted[0];
  // Average over the nights actually logged in the window — not the window
  // length. logs holds only real entries, so dividing by logs.length is right.
  const avg = logs.reduce((s, l) => s + (l.duration_h || 0), 0) / logs.length;
  const fmtDur = h => `${Math.floor(h)}h ${Math.round((h % 1) * 60)}m`;
  const qEmoji = { 1: '😩', 2: '😕', 3: '😐', 4: '😊', 5: '😴' }[last.quality] || '';
  // "last night" only when the newest log really is last night — otherwise it
  // claimed a days-old entry was last night's. Fall back to its date.
  const _y = new Date(Date.now() - 86400000).toLocaleDateString('en-CA');
  const lastLabel = (last.date_key === localToday() || last.date_key === _y)
    ? 'last night'
    : new Date(last.date_key + 'T12:00:00').toLocaleDateString('en-US', {month:'short', day:'numeric'});
  const byDate = {}; logs.forEach(l => { byDate[l.date_key] = l.duration_h; });
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    days.push({ h: byDate[k] || 0, lbl: ['S', 'M', 'T', 'W', 'T', 'F', 'S'][d.getDay()] });
  }
  const maxH = Math.max(9, ...days.map(d => d.h));
  const bars = days.map(d => `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:3px">
      <div style="width:100%;background:${d.h ? 'var(--teal-200)' : 'var(--gray-100)'};height:${Math.max(6, d.h / maxH * 44)}px;border-radius:3px 3px 0 0"></div>
      <span style="font-size:8px;color:var(--gray-400)">${d.lbl}</span></div>`).join('');
  el.innerHTML = `
    <div style="min-width:150px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:4px 8px">
      <div class="today-score-num" style="font-size:32px">${fmtDur(last.duration_h || 0)}</div>
      <div style="font-size:12.5px;color:var(--gray-500);margin-top:4px">${lastLabel} ${qEmoji}</div>
    </div>
    <div style="flex:1;display:flex;flex-direction:column;justify-content:center">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding:0 4px">
        <span style="font-size:12px;color:var(--gray-500)">7-day average</span>
        <span style="font-size:16px;font-weight:700;color:var(--gray-800)">${fmtDur(avg)}</span>
      </div>
      <div style="display:flex;align-items:flex-end;gap:5px;height:52px;padding:0 4px">${bars}</div>
    </div>`;
}

// Re-render every sleep number from fresh data. Call this after any add or
// delete so the 7-day average, the 30-night stats and the dashboard strip all
// move together — the focal card used to be left stale because save/delete
// refreshed the trend and strip but not it.
function refreshSleep() {
  try { renderSleepFocal(); } catch (e) {}
  try { loadSleepTrend(); }  catch (e) {}
  try { loadWellnessStrip(); } catch (e) {}
}

// ── Duration-first sleep entry ─────────────────────────────────
// The state is a duration plus a wake-time anchor; bedtime is derived
// (wake − duration). The "Set exact times" row just exposes those two
// anchors as native time inputs, kept in sync both ways. Sleep tracking
// cares about how long and how well — so we lead with duration and let
// exact clock times be optional.
const _SLEEP_DUR_MIN = 180, _SLEEP_DUR_MAX = 720;   // 3h … 12h

const _fmtDurMin = m => { const h = Math.floor(m/60), mm = m%60; return h + 'h' + (mm ? ' ' + mm + 'm' : ''); };
const _minToHHMM = m => { m = ((m%1440)+1440)%1440; return String(Math.floor(m/60)).padStart(2,'0') + ':' + String(m%60).padStart(2,'0'); };
const _min12 = m => { m = ((m%1440)+1440)%1440; let h = Math.floor(m/60); const ap = h < 12 ? 'AM' : 'PM'; h = h%12 || 12; return h + ':' + String(m%60).padStart(2,'0') + ' ' + ap; };
const _clampDur = m => Math.max(_SLEEP_DUR_MIN, Math.min(_SLEEP_DUR_MAX, m));

async function initSleepEntry() {
  const usual = await usualSleep();
  window._sleepEntry = { durMin: usual.durMin, wakeMin: usual.wakeMin };
  window._sleepExactOpen = false;
  // Tap = 15 min; press-and-hold accelerates to 30-min jumps. Wired here (not
  // via the click-dispatcher) because that only handles click, and hold needs
  // pointer events. The buttons are freshly rendered each loadSleepView, so
  // these listeners don't accumulate.
  attachSleepHold(document.getElementById('sleep-dur-minus'), -1);
  attachSleepHold(document.getElementById('sleep-dur-plus'),  +1);
  sleepDurRender();
}

// Press-and-hold stepper. A quick tap steps once by 15 minutes; holding past a
// short threshold starts repeating in 30-minute chunks until release. Keyboard
// activation (Enter/Space fires click, not pointerdown) still gets one 15-min
// step, and we swallow the click that follows a pointer press so a mouse tap
// doesn't count twice.
function attachSleepHold(btn, dir) {
  if (!btn || btn._holdWired) return;
  btn._holdWired = true;
  let holdTimer = null, repeatTimer = null;
  const stop = () => { clearTimeout(holdTimer); clearInterval(repeatTimer); holdTimer = repeatTimer = null; };
  btn.addEventListener('pointerdown', e => {
    if (e.button != null && e.button !== 0) return;   // left button / touch only
    e.preventDefault();
    sleepDurStep(dir * 15);                            // immediate feedback
    holdTimer = setTimeout(() => {
      repeatTimer = setInterval(() => sleepDurStep(dir * 30), 150);
    }, 450);
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(ev => btn.addEventListener(ev, stop));
  // Keyboard activation (Enter/Space) fires a click with detail 0; a mouse or
  // touch click reports detail ≥ 1 and was already handled by pointerdown, so
  // we only act on the keyboard case — no flag to get stuck.
  btn.addEventListener('click', e => { if (e.detail === 0) sleepDurStep(dir * 15); });
}

// The user's usual duration + wake, learned from their own recent logs — the
// same "default to what you actually do" idea as food portions and water pours.
// A brand-new user falls back to 7h30m waking at 07:00.
async function usualSleep() {
  try {
    const logs = await fetch('/api/sleep?days=30', {cache:'no-store'}).then(r => r.json());
    if (Array.isArray(logs) && logs.length) {
      const durs = logs.map(l => Math.round((l.duration_h||0)*60)).filter(x => x > 0).sort((a,b)=>a-b);
      let durMin = durs.length ? durs[Math.floor(durs.length/2)] : 450;   // median
      durMin = _clampDur(Math.round(durMin/15)*15);
      const wakeCount = {};
      logs.forEach(l => {
        const t = (l.wake_time||'').slice(11,16); if (!/^\d\d:\d\d$/.test(t)) return;
        const [h,m] = t.split(':').map(Number); const wm = Math.round((h*60+m)/15)*15;
        wakeCount[wm] = (wakeCount[wm]||0) + 1;
      });
      let wakeMin = 420, best = 0;   // 07:00
      Object.entries(wakeCount).forEach(([wm,c]) => { if (c > best) { best = c; wakeMin = +wm; } });
      return { durMin, wakeMin };
    }
  } catch (e) {}
  return { durMin: 450, wakeMin: 420 };
}

function sleepDurStep(delta) {
  const s = window._sleepEntry; if (!s) return;
  s.durMin = _clampDur(s.durMin + delta);
  sleepDurRender();
}
function sleepDurDrag(val) {
  const s = window._sleepEntry; if (!s) return;
  s.durMin = _clampDur(parseInt(val) || 450);
  sleepDurRender();
}
function toggleSleepExact() {
  window._sleepExactOpen = !window._sleepExactOpen;
  const row = document.getElementById('sleep-exact-row');
  const btn = document.getElementById('sleep-exact-toggle');
  if (row) row.style.display = window._sleepExactOpen ? 'grid' : 'none';
  if (btn) btn.setAttribute('aria-expanded', window._sleepExactOpen ? 'true' : 'false');
  sleepDurRender();   // populate the inputs with the current implied times
}
// Editing an exact time drives the duration back the other way: change the wake
// anchor and the duration holds; type a bedtime and the duration recomputes.
function sleepExactChanged(which) {
  const s = window._sleepEntry; if (!s) return;
  const parse = id => { const v = document.getElementById(id)?.value || '';
    if (!/^\d\d:\d\d$/.test(v)) return null; const [h,m] = v.split(':').map(Number); return h*60 + m; };
  const wm = parse('sleep-wake-time'), bm = parse('sleep-bed-time');
  if (which === 'wake' && wm != null) {
    s.wakeMin = wm;                                   // duration unchanged
  } else if (which === 'bed' && bm != null) {
    const wake = wm != null ? wm : s.wakeMin;
    let d = ((wake - bm) % 1440 + 1440) % 1440;
    s.durMin = _clampDur(d === 0 ? _SLEEP_DUR_MAX : d);
    if (wm != null) s.wakeMin = wm;
  }
  sleepDurRender(true);   // true → don't overwrite the field being edited
}

function sleepDurRender(fromExact) {
  const s = window._sleepEntry; if (!s) return;
  const bedMin = ((s.wakeMin - s.durMin) % 1440 + 1440) % 1440;
  const h = Math.floor(s.durMin/60);

  const wrap    = document.getElementById('sleep-dur-wrap');
  const readout = document.getElementById('sleep-dur-readout');
  const cap     = document.getElementById('sleep-dur-caption');
  const range   = document.getElementById('sleep-dur-range');
  if (readout) readout.textContent = _fmtDurMin(s.durMin);
  if (wrap)    wrap.className = h >= 7 ? 'sleep-dur--good' : h >= 5 ? 'sleep-dur--ok' : 'sleep-dur--low';
  // Show the clock times this duration implies — keeps duration-first honest
  // about exactly what it will save.
  if (cap)     cap.textContent = `${_min12(bedMin)} → ${_min12(s.wakeMin)}`;
  if (range) {
    if (+range.value !== s.durMin) range.value = s.durMin;
    range.style.setProperty('--fill', (s.durMin - _SLEEP_DUR_MIN) / (_SLEEP_DUR_MAX - _SLEEP_DUR_MIN) * 100 + '%');
  }
  if (!fromExact) {
    const bedEl = document.getElementById('sleep-bed-time'), wakeEl = document.getElementById('sleep-wake-time');
    if (bedEl)  bedEl.value  = _minToHHMM(bedMin);
    if (wakeEl) wakeEl.value = _minToHHMM(s.wakeMin);
  }

  // Absolute datetimes for save — bedtime falls on the previous day whenever
  // the duration crosses midnight, which the old yesterday-string hack got
  // wrong for early/short entries. Anchor to this morning's wake and subtract.
  const now = new Date();
  const wakeDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), Math.floor(s.wakeMin/60), s.wakeMin%60);
  const bedDate  = new Date(wakeDate.getTime() - s.durMin*60000);
  const fmtDT = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` +
                     `T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  window._svBed  = fmtDT(bedDate);
  window._svWake = fmtDT(wakeDate);
}

function selectSleepQ(q, suffix) {
  const grid = document.getElementById('sleep-q-' + (suffix || ''));
  // The quality buttons carry class .sdial-q-btn — the old selector looked for
  // .sleep-q-btn and so never moved the highlight.
  if (grid) grid.querySelectorAll('.sdial-q-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.q) === q);
  });
  if (suffix === 'sv') window._svQuality = q;
  else window._sleepQ = q;
}

async function saveSleepLogFromView() {
  // Full local datetimes computed by sleepDurRender (bed may be the prior day).
  const bed = window._svBed, wake = window._svWake;
  if (!bed || !wake) { showToast('Set how long you slept', 'error'); return; }

  const r = await fetch('/api/sleep', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      bedtime:   bed,
      wake_time: wake,
      // The night is keyed to the morning you woke, so re-logging the same
      // night replaces it regardless of whether bedtime was before midnight.
      date_key:  wake.slice(0, 10),
      quality:   window._svQuality || 4,
      notes:     document.getElementById('sleep-notes-sv')?.value || '',
    })
  }).then(r => r.json()).catch(() => null);

  if (r?.success) {
    showToast('Sleep logged ✓', 'success');
    refreshSleep();   // focal 7-day average included — not just the trend/strip
  } else {
    showToast(r?.error || 'Failed to save', 'error');
  }
}

// ════════════════════════════════════════════════════════════
// BODY & VITALS VIEW — standalone page
// ════════════════════════════════════════════════════════════
async function loadBodyView() {
  const el = document.getElementById('body-view-content');
  if (!el) return;

  el.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:20px">

      <!-- Log Body Metrics -->
      <div class="panel">
        <div class="panel-header"><h2 class="panel-title">Log body metrics</h2></div>
        <div style="padding:16px 20px">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div class="form-group">
              <label class="form-label">Weight (kg)</label>
              <input type="number" class="form-input" id="bv-weight" placeholder="72.5" step="0.1">
            </div>
            <div class="form-group">
              <label class="form-label">Body fat %</label>
              <input type="number" class="form-input" id="bv-bodyfat" placeholder="18.0" step="0.1">
            </div>
            <div class="form-group">
              <label class="form-label">Waist (cm)</label>
              <input type="number" class="form-input" id="bv-waist" placeholder="82" step="0.5">
            </div>
            <div class="form-group">
              <label class="form-label">Date</label>
              <input type="date" class="form-input" id="bv-date" value="${localToday()}">
            </div>
          </div>
          <button class="btn-primary" style="width:100%;margin-top:4px" data-ev-click="saveBodyMetricFromView()">Save</button>
        </div>
        <div id="bv-metric-history" style="padding:0 20px 16px"></div>
      </div>

      <!-- Log Vitals -->
      <div class="panel">
        <div class="panel-header"><h2 class="panel-title">Log a vital</h2></div>
        <div style="padding:16px 20px">
          <div class="form-group">
            <label class="form-label">Type</label>
            <div class="vital-type-chips" id="bv-vital-chips">
              ${[
                {id:'blood_pressure', label:'Blood pressure', unit:'mmHg'},
                {id:'heart_rate',     label:'Heart rate',     unit:'bpm'},
                {id:'blood_sugar',    label:'Blood sugar',    unit:'mg/dL'},
                {id:'temperature',    label:'Temperature',    unit:'°C'},
                {id:'spo2',           label:'SpO₂',      unit:'%'},
              ].map(v =>
                '<button class="vital-chip" data-type="'+v.id+'" data-unit="'+v.unit+'" data-ev-click="selectVitalTypeView(this)">'+v.label+'</button>'
              ).join('')}
            </div>
          </div>
          <div id="bv-vital-fields" style="display:none">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
              <div class="form-group">
                <label class="form-label" id="bv-v1-label">Value</label>
                <input type="number" class="form-input" id="bv-v1" step="0.1">
              </div>
              <div class="form-group" id="bv-v2-wrap" style="display:none">
                <label class="form-label" id="bv-v2-label">Value 2</label>
                <input type="number" class="form-input" id="bv-v2" step="0.1">
              </div>
            </div>
            <button class="btn-primary" style="width:100%;margin-top:4px" data-ev-click="saveVitalFromView()">Log vital</button>
          </div>
        </div>
        <div id="bv-vital-history" style="padding:0 20px 16px"></div>
      </div>
    </div>

    <!-- Weight progress chart — full width -->
    <div id="bv-weight-chart-section" style="margin-bottom:20px"></div>

    <!-- Vital trend charts -->
    <div id="bv-trend-section"></div>
  `;

  loadBodyMetricsView();
  loadVitalsView();
  loadWeightProgressChart();
  loadVitalTrends();
}

function selectVitalTypeView(btn) {
  document.querySelectorAll('.vital-chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  window._bvVitalType = btn.dataset.type;
  window._bvVitalUnit = btn.dataset.unit;
  const fields = document.getElementById('bv-vital-fields');
  if (fields) fields.style.display = 'block';
  // Show/hide second value for BP
  const v2 = document.getElementById('bv-v2-wrap');
  const v1l = document.getElementById('bv-v1-label');
  const v2l = document.getElementById('bv-v2-label');
  if (btn.dataset.type === 'blood_pressure') {
    if (v2) v2.style.display = 'block';
    if (v1l) v1l.textContent = 'Systolic';
    if (v2l) v2l.textContent = 'Diastolic';
  } else {
    if (v2) v2.style.display = 'none';
    if (v1l) v1l.textContent = 'Value (' + btn.dataset.unit + ')';
  }
}

async function saveBodyMetricFromView() {
  const data = {
    weight_kg:    parseFloat(document.getElementById('bv-weight')?.value) || null,
    body_fat_pct: parseFloat(document.getElementById('bv-bodyfat')?.value) || null,
    waist_cm:     parseFloat(document.getElementById('bv-waist')?.value) || null,
    date_key:     document.getElementById('bv-date')?.value || localToday(),
  };
  if (!data.weight_kg && !data.body_fat_pct && !data.waist_cm) {
    showToast('Enter at least one measurement', 'error'); return;
  }
  const r = await fetch('/api/body-metrics', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(data)
  }).then(r => r.json()).catch(() => null);
  if (r?.success) { showToast('Saved ✓', 'success'); loadBodyMetricsView(); loadWeightProgressChart(); }
  else showToast('Failed to save', 'error');
}

async function saveVitalFromView() {
  if (!window._bvVitalType) { showToast('Select a vital type', 'error'); return; }
  const v1 = parseFloat(document.getElementById('bv-v1')?.value);
  const v2 = parseFloat(document.getElementById('bv-v2')?.value) || null;
  if (!v1) { showToast('Enter a value', 'error'); return; }
  const r = await fetch('/api/vitals', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ type: window._bvVitalType, value1: v1, value2: v2,
                           unit: window._bvVitalUnit, date_key: localToday() })
  }).then(r => r.json()).catch(() => null);
  if (r?.success) { showToast('Logged ✓', 'success'); loadVitalsView(); }
  else showToast(r?.error || 'Failed to save', 'error');
}

async function loadBodyMetricsView() {
  const el = document.getElementById('bv-metric-history');
  if (!el) return;
  const r = await fetch('/api/body-metrics').then(r => r.json()).catch(() => []);
  const rows = (Array.isArray(r) ? r : []).slice(0,5);
  if (!rows.length) { el.innerHTML = '<p style="color:var(--gray-400);font-size:13px;text-align:center;padding:12px 0">No entries yet</p>'; return; }
  el.innerHTML = rows.map(m => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--gray-50)">
      <div style="font-size:12px;color:var(--gray-400)">${m.date_key}</div>
      <div style="font-size:13px;font-weight:600;color:var(--gray-800)">
        ${m.weight_kg ? m.weight_kg + ' kg' : ''}
        ${m.bmi ? ' · BMI ' + m.bmi : ''}
        ${m.body_fat_pct ? ' · ' + m.body_fat_pct + '% fat' : ''}
      </div>
    </div>`).join('');
}

async function loadVitalsView() {
  const el = document.getElementById('bv-vital-history');
  if (!el) return;
  const r = await fetch('/api/vitals').then(r => r.json()).catch(() => []);
  const rows = (Array.isArray(r) ? r : []).slice(0,5);
  if (!rows.length) { el.innerHTML = '<p style="color:var(--gray-400);font-size:13px;text-align:center;padding:12px 0">No vitals logged yet</p>'; return; }
  el.innerHTML = rows.map(v => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--gray-50)">
      <div>
        <div style="font-size:13px;font-weight:600;color:var(--gray-800)">${v.type.replace('_',' ')}</div>
        <div style="font-size:11.5px;color:var(--gray-400)">${v.date_key}</div>
      </div>
      <div style="font-size:14px;font-weight:700;color:var(--teal-700)">
        ${v.value1}${v.value2 ? '/' + v.value2 : ''} <span style="font-size:11px;font-weight:400">${v.unit}</span>
      </div>
    </div>`).join('');
}

// loadJournal = alias for the existing loadWellness but only shows thoughts tab
function loadJournal() {
  loadWellness();
  // Switch to journal/thoughts tab
  setTimeout(() => switchWellnessTab('thoughts'), 50);
}

// ════════════════════════════════════════════════════════════
// DATA EXPORT VIEW
// ════════════════════════════════════════════════════════════

const EXPORT_SECTIONS = [
  { key:'food_logs',          icon:'🍽️', name:'Food Logs',         desc:'Meals, calories, macros' },
  { key:'fitness_activities', icon:'🏃', name:'Workouts',           desc:'Activities, duration, calories' },
  { key:'sleep_logs',         icon:'🌙', name:'Sleep Logs',         desc:'Bedtime, duration, quality' },
  { key:'symptoms',           icon:'🩺', name:'Symptoms',           desc:'Logged symptoms & severity' },
  { key:'vitals',             icon:'❤️', name:'Vitals',             desc:'BP, blood sugar, heart rate' },
  { key:'thoughts',           icon:'💭', name:'Thoughts',           desc:'Daily journal entries' },
  { key:'todos',              icon:'✅', name:'Tasks',              desc:'To-do list items' },
  { key:'body_metrics',       icon:'⚖️', name:'Body Metrics',       desc:'Weight, BMI, body fat' },
  { key:'hydration_logs',     icon:'💧', name:'Hydration',          desc:'Daily water intake logs' },
  { key:'habits',             icon:'⭐', name:'Habits & Logs',      desc:'Habits + completion history' },
  { key:'medicines',          icon:'💊', name:'Medicines',          desc:'Medication list' },
];

let _exportFmt      = 'json';
let _exportSelected = new Set(EXPORT_SECTIONS.map(s => s.key));
let _exportCounts   = {};

async function initExportView() {
  // Set default dates
  const today = new Date().toISOString().slice(0,10);
  const yearAgo = new Date(Date.now() - 365*86400000).toISOString().slice(0,10);
  const fromEl = document.getElementById('export-from-date');
  const toEl   = document.getElementById('export-to-date');
  if (fromEl && !fromEl.value) fromEl.value = yearAgo;
  if (toEl && !toEl.value)     toEl.value   = today;

  renderExportSections();
  await loadExportCounts();
}

async function loadExportCounts() {
  const from = document.getElementById('export-from-date')?.value || '2000-01-01';
  const to   = document.getElementById('export-to-date')?.value   || new Date().toISOString().slice(0,10);
  const r = await fetch(`/api/export/counts?from=${from}&to=${to}`).then(r=>r.json()).catch(()=>({}));
  _exportCounts = r;
  renderExportSections();
  updateExportEstimate();
}

function renderExportSections() {
  const el = document.getElementById('export-sections-grid');
  if (!el) return;
  el.innerHTML = EXPORT_SECTIONS.map(s => {
    const selected = _exportSelected.has(s.key);
    const count = _exportCounts[s.key];
    const countStr = count != null ? `${count} record${count!==1?'s':''}` : '—';
    return `<div class="export-section-card ${selected?'selected':''}" data-ev-click="toggleExportSection('${s.key}')">
      <div class="export-section-check"></div>
      <div class="export-section-icon">${s.icon}</div>
      <div class="export-section-info">
        <div class="export-section-name">${s.name}</div>
        <div class="export-section-count">${countStr}</div>
      </div>
    </div>`;
  }).join('');
}

function toggleExportSection(key) {
  if (_exportSelected.has(key)) _exportSelected.delete(key);
  else _exportSelected.add(key);
  renderExportSections();
  updateExportEstimate();
}

function setAllExportSections(val) {
  if (val) EXPORT_SECTIONS.forEach(s => _exportSelected.add(s.key));
  else _exportSelected.clear();
  renderExportSections();
  updateExportEstimate();
}

function updateExportEstimate() {
  const el = document.getElementById('export-size-estimate');
  if (!el) return;
  const total = [..._exportSelected].reduce((sum, k) => sum + (_exportCounts[k]||0), 0);
  el.textContent = total > 0 ? `~${total} records selected` : 'Nothing selected';
  // Update button text
  const btn = document.getElementById('export-download-btn');
  const fmtLabel = _exportFmt.toUpperCase();
  if (btn) btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Download ${fmtLabel} (${total} records)`;
}

function setExportFmt(fmt) {
  _exportFmt = fmt;
  document.querySelectorAll('.export-fmt-btn').forEach(b => b.classList.toggle('active', b.dataset.fmt === fmt));
  updateExportEstimate();
}

function setExportPreset(days) {
  const today = new Date().toISOString().slice(0,10);
  const fromEl = document.getElementById('export-from-date');
  const toEl   = document.getElementById('export-to-date');
  if (!fromEl || !toEl) return;
  toEl.value = today;
  if (days === 0) {
    fromEl.value = '2000-01-01';
  } else {
    fromEl.value = new Date(Date.now() - days*86400000).toISOString().slice(0,10);
  }
  loadExportCounts();
}

async function doExport() {
  if (_exportSelected.size === 0) { showToast('Select at least one section', 'error'); return; }
  const from = document.getElementById('export-from-date')?.value || '2000-01-01';
  const to   = document.getElementById('export-to-date')?.value   || new Date().toISOString().slice(0,10);
  const sections = [..._exportSelected].join(',');
  const url = `/api/export?format=${_exportFmt}&sections=${sections}&from=${from}&to=${to}`;

  // Trigger download
  const a = document.createElement('a');
  a.href = url; a.download = '';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  showToast(`Downloading ${_exportFmt.toUpperCase()} export…`, 'success');
}

// ── Complete data export + account deletion (DPDP/GDPR) ─────────────────────
async function downloadAllData() {
  showToast('Preparing your data…', 'info');
  try {
    const r = await fetch('/api/account/export', {credentials: 'same-origin'});
    if (!r.ok) throw new Error('export failed');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'arogo-my-data.json';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('✓ Downloaded all your data', 'success');
  } catch { showToast('Could not prepare your data — try again', 'error'); }
}

function openDeleteAccount() {
  const panel = document.getElementById('delete-account-panel');
  if (!panel) return;
  // Reveal a password confirm inline — deletion is irreversible, so require the
  // password and an explicit second click.
  panel.innerHTML = `
    <h2 class="panel-title" style="margin-bottom:6px;color:#B91C1C">Delete my account</h2>
    <p style="font-size:13px;color:var(--gray-400);margin-bottom:12px">
      This permanently erases your account and every record. Enter your password to confirm.</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <input type="password" class="form-input" id="delete-account-pw" placeholder="Your password"
             aria-label="Confirm password" style="max-width:220px" autocomplete="current-password">
      <button class="btn-outline" data-ev-click="resetDeleteAccount()">Cancel</button>
      <button class="btn-outline" style="color:#fff;background:#B91C1C;border-color:#B91C1C"
              data-ev-click="confirmDeleteAccount()">Permanently delete</button>
    </div>`;
}

function resetDeleteAccount() {
  const panel = document.getElementById('delete-account-panel');
  if (!panel) return;
  panel.innerHTML = `
    <h2 class="panel-title" style="margin-bottom:4px;color:#B91C1C">Delete my account</h2>
    <p style="font-size:13px;color:var(--gray-400);margin-bottom:12px">
      Permanently deletes your account and <b>all</b> your data — medicines, logs,
      family links, everything. This cannot be undone. Consider downloading your data first.</p>
    <button class="btn-outline" style="color:#B91C1C;border-color:#e7a3a3"
            data-ev-click="openDeleteAccount()">Delete account…</button>`;
}

async function confirmDeleteAccount() {
  const pw = document.getElementById('delete-account-pw')?.value || '';
  if (!pw) { showToast('Enter your password to confirm', 'error'); return; }
  const r = await fetch('/api/account', {
    method: 'DELETE', headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin', body: JSON.stringify({password: pw}),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { showToast(d.error || 'Could not delete account', 'error'); return; }
  // Account and session are gone — send them back to the sign-in screen.
  showToast('Your account and data have been deleted', 'success');
  setTimeout(() => { window.location.href = '/'; }, 1200);
}

// ════════════════════════════════════════════════════════════════
// DAILY CHECK-IN
// Shown once per day on first dashboard open.
// Writes to: /api/thoughts (mood), /api/sleep, /api/symptoms,
//            /api/hydration  — all existing endpoints.
// Completion stored in localStorage so it shows once per day.
// ════════════════════════════════════════════════════════════════

const CI_STEPS  = ['mood', 'sleep', 'symptoms', 'water'];
let   ciStep    = 0;
const ciSel     = { mood: null, sleep: null, symptoms: [], water: null };

// Emoji come from MOOD_EMOJI, not a second hardcoded copy — the two drifted
// (the check-in showed 😕 for `sad` where the journal showed 😞, for the same
// stored value).
const CI_MOODS = [
  { label: 'Rough', mood: 'terrible' },
  { label: 'Low',   mood: 'sad'      },
  { label: 'Okay',  mood: 'neutral'  },
  { label: 'Good',  mood: 'happy'    },
  { label: 'Great', mood: 'excited'  },
].map(m => ({ ...m, emoji: MOOD_EMOJI[m.mood] }));
const CI_SLEEP = [
  { label: 'Under 5h', sub: 'Very short',    dur: 4,   quality: 1 },
  { label: '5 – 6h',   sub: 'A bit short',   dur: 5.5, quality: 2 },
  { label: '6 – 7h',   sub: 'Nearly enough', dur: 6.5, quality: 3 },
  { label: '7 – 9h',   sub: 'Just right',    dur: 8,   quality: 5 },
  { label: '9h+',      sub: 'Long sleep',    dur: 9.5, quality: 3 },
  { label: 'No sleep', sub: '—',             dur: 0,   quality: 1 },
];
const CI_SYMPTOMS = [
  'Headache', 'Fatigue', 'Nausea', 'Back pain',
  'Anxiety',  'Sore throat', 'Stomach ache', 'Dizziness',
  'Fever', 'Cold / runny nose',
];
const CI_WATER = [
  { label: '250ml', ml: 250  },
  { label: '500ml', ml: 500  },
  { label: '750ml', ml: 750  },
  { label: '1L+',   ml: 1000 },
];

// ── Trigger: call from loadDashboard ─────────────────────────────
async function initDailyCheckin() {
  const today     = localToday();
  const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
  const key       = `medeasy_checkin_${today}`;
  if (localStorage.getItem(key)) return;  // already done today

  // Check what's already been logged so we don't ask twice
  const [sleepLogs, thoughts, hydration] = await Promise.all([
    fetch('/api/sleep?days=2').then(r => r.json()).catch(() => []),
    fetch(`/api/thoughts/${today}`).then(r => r.json()).catch(() => []),
    fetch(`/api/hydration/${today}`, {cache: 'no-store'}).then(r => r.json()).catch(() => null),
  ]);

  // Sleep: skip if logged for today or yesterday
  const hasSleep = Array.isArray(sleepLogs) &&
    sleepLogs.some(s => s.date_key === today || s.date_key === yesterday);

  // Mood: skip if thought/mood logged today
  const hasMood = Array.isArray(thoughts) && thoughts.length > 0;

  // Hydration: skip if already has meaningful water logged
  const hasHydration = hydration && (hydration.total_ml || 0) >= 250;

  // Build the steps to show — skip already-logged ones
  const stepsToShow = [];
  if (!hasMood)      stepsToShow.push('mood');
  if (!hasSleep)     stepsToShow.push('sleep');
                     stepsToShow.push('symptoms');  // always ask about symptoms
  if (!hasHydration) stepsToShow.push('water');

  // If everything is already logged, just mark done and skip
  if (stepsToShow.length <= 1 && stepsToShow[0] === 'symptoms') {
    localStorage.setItem(key, '1');
    return;
  }

  // Respect a "not now" snooze for today
  if (localStorage.getItem(`medeasy_checkin_snooze_${today}`)) return;

  // Show only the relevant steps
  window._ciStepsToShow = stepsToShow;

  // Surface an inline, dismissible nudge instead of interrupting with a modal
  // over the dashboard's next-action hero — the user chooses when to start.
  const prompt = document.getElementById('dash-checkin-prompt');
  if (!prompt) return;
  const labels = { mood:'mood', sleep:'sleep', symptoms:'symptoms', water:'water' };
  const parts  = stepsToShow.map(s => labels[s]).filter(Boolean);
  prompt.innerHTML = `
    <div class="checkin-prompt-icon">☀️</div>
    <div class="checkin-prompt-body">
      <div class="checkin-prompt-title">Daily check-in</div>
      <div class="checkin-prompt-sub">A quick 30 seconds — ${parts.join(', ')}.</div>
    </div>
    <button class="checkin-prompt-start" data-ev-click="startDailyCheckin()">Start</button>
    <button class="checkin-prompt-dismiss" data-ev-click="dismissCheckinPrompt()" title="Not now" aria-label="Dismiss">✕</button>`;
  prompt.style.display = 'flex';
}

function startDailyCheckin() {
  const prompt = document.getElementById('dash-checkin-prompt');
  if (prompt) prompt.style.display = 'none';
  ciStep = 0;
  ciSel.mood = null; ciSel.sleep = null; ciSel.symptoms = []; ciSel.water = null; ciSel.note = '';
  renderCheckin();
  document.getElementById('checkin-overlay').style.display = 'flex';
}

function dismissCheckinPrompt() {
  const prompt = document.getElementById('dash-checkin-prompt');
  if (prompt) prompt.style.display = 'none';
  // Snooze for the rest of today only — it returns tomorrow
  localStorage.setItem(`medeasy_checkin_snooze_${localToday()}`, '1');
}

function closeCheckin() {
  document.getElementById('checkin-overlay').style.display = 'none';
}

// ── Renderer ──────────────────────────────────────────────────────
function renderCheckin() {
  // Use only the steps that haven't been logged yet
  const steps = window._ciStepsToShow || CI_STEPS;
  const currentStepName = steps[ciStep];
  const totalSteps = steps.length;

  // Dots
  const dotsEl = document.getElementById('checkin-dots');
  if (dotsEl) {
    dotsEl.innerHTML = steps.map((_, i) => {
      let cls = 'ci-dot';
      if (i < ciStep)        cls += ' done';
      else if (i === ciStep) cls += ' active';
      return `<div class="${cls}"></div>`;
    }).join('');
  }

  // Progress bar
  const prog = document.getElementById('checkin-progress');
  if (prog) prog.style.width = ((ciStep + 1) / totalSteps * 100) + '%';

  const body   = document.getElementById('checkin-body');
  const footer = document.getElementById('checkin-footer');
  if (!body || !footer) return;

  const stepNum = ciStep + 1;

  // ── Step: Mood ──────────────────────────────────────────────
  if (currentStepName === 'mood') {
    body.innerHTML = `
      <div class="ci-step-label">Step ${stepNum} of ${totalSteps} · How you feel</div>
      <div class="ci-question">Good morning! How are you feeling?</div>
      <div class="ci-mood-grid">
        ${CI_MOODS.map((m, i) => `
          <button class="ci-mood-btn${ciSel.mood === i ? ' active' : ''}"
                  data-ev-click="ciPickMood(${i})">
            <span class="ci-mood-emoji">${m.emoji}</span>
            <span class="ci-mood-label">${m.label}</span>
          </button>`).join('')}
      </div>
      ${ciSel.mood !== null ? `
        <textarea class="ci-note" rows="2" maxlength="500"
                  placeholder="Anything on your mind? Adds a note to your journal (optional)…"
                  data-ev-input="ciSetNote(this.value)">${escHtml(ciSel.note || '')}</textarea>` : ''}`;
    footer.innerHTML = `
      <button class="ci-btn-primary" data-ev-click="ciNext()"
              ${ciSel.mood === null ? 'disabled' : ''}>Continue</button>`;
  }

  // ── Step: Sleep ─────────────────────────────────────────────
  else if (currentStepName === 'sleep') {
    body.innerHTML = `
      <div class="ci-step-label">Step ${stepNum} of ${totalSteps} · Sleep</div>
      <div class="ci-question">How much did you sleep last night?</div>
      <div class="ci-sleep-grid">
        ${CI_SLEEP.map((s, i) => `
          <button class="ci-sleep-btn${ciSel.sleep === i ? ' active' : ''}"
                  data-ev-click="ciPickSleep(${i})">
            <div class="ci-sleep-dur">${s.label}</div>
            <div class="ci-sleep-qual">${s.sub}</div>
          </button>`).join('')}
      </div>`;
    footer.innerHTML = `
      <button class="ci-btn-secondary" data-ev-click="ciBack()">Back</button>
      <button class="ci-btn-primary" data-ev-click="ciNext()"
              ${ciSel.sleep === null ? 'disabled' : ''}>Continue</button>`;
  }

  // ── Step: Symptoms ──────────────────────────────────────────
  else if (currentStepName === 'symptoms') {
    body.innerHTML = `
      <div class="ci-step-label">Step ${stepNum} of ${totalSteps} · Symptoms</div>
      <div class="ci-question">Any symptoms today?</div>
      <div class="ci-sym-list">
        <button class="ci-none-btn${ciSel.symptoms.length === 0 ? ' active' : ''}"
                data-ev-click="ciClearSymptoms()">None, feeling fine</button>
        ${CI_SYMPTOMS.map(s => `
          <button class="ci-sym-btn${ciSel.symptoms.includes(s) ? ' active' : ''}"
                  data-ev-click="ciToggleSymptom('${s}')">${s}</button>`).join('')}
      </div>`;
    const isFirst = ciStep === 0;
    footer.innerHTML = `
      ${!isFirst ? '<button class="ci-btn-secondary" data-ev-click="ciBack()">Back</button>' : ''}
      <button class="ci-btn-primary" data-ev-click="ciNext()">Continue</button>`;
  }

  // ── Step: Hydration ─────────────────────────────────────────
  else if (currentStepName === 'water') {
    body.innerHTML = `
      <div class="ci-step-label">Step ${stepNum} of ${totalSteps} · Hydration</div>
      <div class="ci-question">How much have you had to drink so far?</div>
      <div class="ci-water-grid">
        ${CI_WATER.map((w, i) => `
          <button class="ci-water-btn${ciSel.water === i ? ' active' : ''}"
                  data-ev-click="ciPickWater(${i})">
            <div>${w.label}</div>
          </button>`).join('')}
      </div>`;
    footer.innerHTML = `
      <button class="ci-btn-secondary" data-ev-click="ciBack()">Back</button>
      <button class="ci-btn-primary" data-ev-click="ciSubmit()">Done</button>`;
  }
}

// ── Interaction handlers ──────────────────────────────────────────
function ciPickMood(i) {
  ciSel.mood = i;
  renderCheckin();
}
function ciSetNote(v) {
  // Store only — no re-render, so the textarea keeps focus while typing
  ciSel.note = v;
}
function ciPickSleep(i) {
  ciSel.sleep = i;
  renderCheckin();
}
function ciToggleSymptom(s) {
  const idx = ciSel.symptoms.indexOf(s);
  if (idx >= 0) ciSel.symptoms.splice(idx, 1);
  else          ciSel.symptoms.push(s);
  renderCheckin();
}
function ciClearSymptoms() {
  ciSel.symptoms = [];
  renderCheckin();
}
function ciPickWater(i) {
  ciSel.water = i;
  renderCheckin();
}
function ciNext() {
  const steps = window._ciStepsToShow || CI_STEPS;
  ciStep++;
  // If we've gone past the last step, submit
  if (ciStep >= steps.length) {
    ciSubmit();
  } else {
    renderCheckin();
  }
}
function ciBack() {
  if (ciStep > 0) { ciStep--; renderCheckin(); }
}

// ── Submit: save to all relevant APIs ────────────────────────────
async function ciSubmit() {
  const today     = localToday();
  const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
  const saves     = [];

  // 1. Mood → save as a journal thought. If the user wrote a reflection note,
  //    that becomes the journal entry (the check-in doubles as the journal).
  if (ciSel.mood !== null) {
    const m    = CI_MOODS[ciSel.mood];
    const note = (ciSel.note || '').trim();
    const content = note
      ? `${note}\n\n(Check-in: feeling ${m.label.toLowerCase()})`
      : `Daily check-in: feeling ${m.label.toLowerCase()}.`;
    saves.push(fetch('/api/thoughts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, mood: m.mood, date_key: today })
    }).catch(() => {}));
  }

  // 2. Sleep → derive bedtime/wake from duration
  if (ciSel.sleep !== null) {
    const s   = CI_SLEEP[ciSel.sleep];
    const dur = s.dur;
    if (dur > 0) {
      // Assume woke up now, went to bed dur hours ago
      const now      = new Date();
      const wake     = now.toISOString().slice(0, 16);
      const bedDate  = new Date(now - dur * 3600000);
      const bedtime  = bedDate.toISOString().slice(0, 16);
      saves.push(fetch('/api/sleep', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bedtime, wake_time: wake,
          quality:  s.quality,
          notes:    'Logged via daily check-in',
          date_key: yesterday,   // sleep was last night
        })
      }).catch(() => {}));
    }
  }

  // 3. Symptoms
  ciSel.symptoms.forEach(sym => {
    saves.push(fetch('/api/symptoms', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name:        sym,
        severity:    5,
        date_key:    today,
        time_of_day: 'morning',
        notes:       'Logged via daily check-in',
      })
    }).catch(() => {}));
  });

  // 4. Hydration
  if (ciSel.water !== null) {
    const w = CI_WATER[ciSel.water];
    saves.push(fetch('/api/hydration', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount_ml: w.ml, drink_type: 'water', date_key: today })
    }).catch(() => {}));
  }

  await Promise.all(saves);

  // Mark today's check-in done
  localStorage.setItem(`medeasy_checkin_${today}`, '1');

  // Show thank-you summary, then auto-close after 2.5s
  ciShowSummary();

  // Refresh dashboard strip so hydration shows updated
  loadWellnessStrip();
}

// ── Summary screen ────────────────────────────────────────────────
function ciShowSummary() {
  const body   = document.getElementById('checkin-body');
  const footer = document.getElementById('checkin-footer');
  const prog   = document.getElementById('checkin-progress');
  const dots   = document.getElementById('checkin-dots');
  if (prog) prog.style.width = '100%';
  if (dots) dots.innerHTML = CI_STEPS.map(() => '<div class="ci-dot done"></div>').join('');

  const moodObj  = ciSel.mood  !== null ? CI_MOODS[ciSel.mood]  : null;
  const sleepObj = ciSel.sleep !== null ? CI_SLEEP[ciSel.sleep] : null;
  const waterObj = ciSel.water !== null ? CI_WATER[ciSel.water] : null;
  const symText  = ciSel.symptoms.length
    ? ciSel.symptoms.slice(0, 2).join(', ') + (ciSel.symptoms.length > 2 ? ` +${ciSel.symptoms.length - 2}` : '')
    : 'None';

  body.innerHTML = `
    <div class="ci-step-label" style="color:var(--teal-600)">All done</div>
    <div class="ci-question" style="font-size:17px;margin-bottom:18px">Good start to the day!</div>
    <div class="ci-summary-grid">
      <div class="ci-sum-card">
        <div class="ci-sum-val">${moodObj ? moodObj.emoji + ' ' + moodObj.label : '—'}</div>
        <div class="ci-sum-lab">Mood</div>
      </div>
      <div class="ci-sum-card">
        <div class="ci-sum-val">${sleepObj ? sleepObj.label : '—'}</div>
        <div class="ci-sum-lab">Sleep</div>
      </div>
      <div class="ci-sum-card">
        <div class="ci-sum-val" style="font-size:13px">${symText}</div>
        <div class="ci-sum-lab">Symptoms</div>
      </div>
      <div class="ci-sum-card">
        <div class="ci-sum-val">${waterObj ? waterObj.label : '—'}</div>
        <div class="ci-sum-lab">Hydration</div>
      </div>
    </div>`;

  footer.innerHTML = `
    <button class="ci-btn-primary" data-ev-click="closeCheckin()">Go to dashboard</button>`;

  setTimeout(closeCheckin, 3000);
}


// ════════════════════════════════════════════════════════════════
// VITAL TRENDS — 30-day charts using Chart.js
// ════════════════════════════════════════════════════════════════

const VITAL_META = {
  blood_pressure: {
    label: 'Blood pressure',
    unit:  'mmHg',
    color: { sys: '#4F8D74', dia: '#5DCAA5' },
    refLines: [
      { value: 120, label: 'Sys goal', color: '#4F8D74', dash: [4,3] },
      { value: 80,  label: 'Dia goal', color: '#5DCAA5', dash: [4,3] },
      { value: 140, label: 'Sys high', color: '#EF4444', dash: [6,3] },
    ],
    yMin: 40, yMax: 180,
    twoValues: true,
  },
  heart_rate: {
    label: 'Heart rate',
    unit:  'bpm',
    color: { main: '#E85D24' },
    refLines: [
      { value: 60,  label: 'Low',    color: '#3B82F6', dash: [4,3] },
      { value: 100, label: 'High',   color: '#EF4444', dash: [4,3] },
    ],
    yMin: 40, yMax: 160,
    twoValues: false,
  },
  blood_sugar: {
    label: 'Blood sugar',
    unit:  'mg/dL',
    color: { main: '#BA7517' },
    refLines: [
      { value: 70,  label: 'Low',    color: '#3B82F6', dash: [4,3] },
      { value: 99,  label: 'Normal', color: '#22C55E', dash: [4,3] },
      { value: 125, label: 'Pre-diabetic', color: '#F59E0B', dash: [4,3] },
    ],
    yMin: 50, yMax: 200,
    twoValues: false,
  },
  spo2: {
    label: 'SpO\u2082',
    unit:  '%',
    color: { main: '#5E8299' },
    refLines: [
      { value: 95, label: 'Min normal', color: '#EF4444', dash: [4,3] },
    ],
    yMin: 85, yMax: 102,
    twoValues: false,
  },
  temperature: {
    label: 'Temperature',
    unit:  '\u00b0C',
    color: { main: '#D85A30' },
    refLines: [
      { value: 37.2, label: 'Fever threshold', color: '#EF4444', dash: [4,3] },
    ],
    yMin: 35, yMax: 40,
    twoValues: false,
  },
};

// Chart.js instance cache so we can destroy before re-render
const _vitalCharts = {};

let _vitalTrendDays = 30;

async function loadVitalTrends(days) {
  if (days) _vitalTrendDays = days;
  const d = _vitalTrendDays;

  const section = document.getElementById('bv-trend-section');
  if (!section) return;

  section.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:20px 0;text-align:center">Loading trend charts…</div>';

  if (!window.Chart) {
    await new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  const data = await fetch(`/api/vitals/trend?days=${d}`, { cache: 'no-store' })
    .then(r => r.json()).catch(() => null);

  if (!data) {
    section.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:20px 0;text-align:center">Could not load trend data</div>';
    return;
  }

  const groups  = data.groups || {};
  const hasData = Object.keys(groups).some(k => groups[k].length > 0);

  const toggleHTML = `
    <div class="trend-toggle">
      <button class="trend-toggle-btn${d===7?' active':''}"  data-ev-click="loadVitalTrends(7)">Weekly</button>
      <button class="trend-toggle-btn${d===30?' active':''}" data-ev-click="loadVitalTrends(30)">Monthly</button>
      <button class="trend-toggle-btn${d===90?' active':''}" data-ev-click="loadVitalTrends(90)">3 months</button>
    </div>`;

  if (!hasData) {
    section.innerHTML = `
      <div class="panel" style="padding:20px 22px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
          <span style="font-size:14px;font-weight:600;color:var(--gray-700)">Vital trends</span>
          ${toggleHTML}
        </div>
        <div style="text-align:center;padding:20px 0">
          <div style="font-size:14px;font-weight:600;color:var(--gray-700);margin-bottom:6px">No vitals logged yet</div>
          <div style="font-size:13px;color:var(--gray-400)">Log your first vital above — charts appear once you have data.</div>
        </div>
      </div>`;
    return;
  }

  const CHART_ORDER = ['blood_pressure','heart_rate','blood_sugar','spo2','temperature'];
  const chartsHTML  = CHART_ORDER
    .filter(t => groups[t] && groups[t].length >= 1)
    .map(t => {
      const meta    = VITAL_META[t];
      const entries = groups[t];
      const latest  = entries[entries.length - 1];
      const latestVal = latest.value2
        ? `${latest.value1}/${latest.value2}`
        : latest.value1;
      const periodLabel = d === 7 ? 'this week' : d === 30 ? 'this month' : 'last 3 months';
      return `
        <div class="panel" style="padding:16px 20px 20px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">
            <h2 class="panel-title">${meta.label}</h2>
            <span class="panel-badge">${latestVal} ${meta.unit}</span>
          </div>
          <div style="font-size:11.5px;color:var(--gray-400);margin-bottom:12px">
            ${entries.length} reading${entries.length !== 1 ? 's' : ''} ${periodLabel}
          </div>
          <div style="position:relative;height:160px">
            <canvas id="vchart-${t}"></canvas>
          </div>
          <div id="vref-${t}" style="display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;font-size:11px;color:var(--gray-500)"></div>
        </div>`;
    }).join('');

  section.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:12px">
      <span style="font-size:13px;font-weight:600;color:var(--gray-700)">Vital trends</span>
      ${toggleHTML}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px">${chartsHTML}</div>`;

  requestAnimationFrame(() => {
    CHART_ORDER.filter(t => groups[t] && groups[t].length >= 1).forEach(t => {
      renderVitalChart(t, groups[t], VITAL_META[t]);
    });
  });
}

function renderVitalChart(type, entries, meta) {
  const canvas = document.getElementById('vchart-' + type);
  if (!canvas) return;

  // Destroy previous instance if exists
  if (_vitalCharts[type]) {
    _vitalCharts[type].destroy();
    delete _vitalCharts[type];
  }

  const labels = entries.map(e => {
    const d = new Date(e.date);
    return (d.getMonth() + 1) + '/' + d.getDate();
  });

  const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const gridColor  = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const tickColor  = isDark ? '#888780'                : '#888780';

  // Build datasets
  const datasets = [];
  if (meta.twoValues) {
    // Blood pressure: two lines
    datasets.push({
      label:           'Systolic',
      data:            entries.map(e => e.value1),
      borderColor:     meta.color.sys,
      backgroundColor: meta.color.sys + '20',
      borderWidth:     2,
      pointRadius:     entries.length > 15 ? 2 : 3.5,
      pointHoverRadius:5,
      tension:         0.35,
      fill:            false,
    });
    datasets.push({
      label:           'Diastolic',
      data:            entries.map(e => e.value2),
      borderColor:     meta.color.dia,
      backgroundColor: meta.color.dia + '20',
      borderWidth:     2,
      pointRadius:     entries.length > 15 ? 2 : 3.5,
      pointHoverRadius:5,
      tension:         0.35,
      fill:            false,
    });
  } else {
    datasets.push({
      label:           meta.label,
      data:            entries.map(e => e.value1),
      borderColor:     meta.color.main,
      backgroundColor: meta.color.main + '18',
      borderWidth:     2,
      pointRadius:     entries.length > 15 ? 2 : 3.5,
      pointHoverRadius:5,
      tension:         0.35,
      fill:            true,
    });
  }

  // Reference line annotations as extra datasets (dashed)
  meta.refLines.forEach(ref => {
    datasets.push({
      label:       ref.label,
      data:        entries.map(() => ref.value),
      borderColor: ref.color,
      borderWidth: 1,
      borderDash:  ref.dash,
      pointRadius: 0,
      pointHoverRadius: 0,
      fill:        false,
    });
  });

  _vitalCharts[type] = new window.Chart(canvas, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction:         { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display:  meta.twoValues || meta.refLines.length > 0,
          position: 'bottom',
          labels:   { boxWidth: 10, boxHeight: 2, font: { size: 11 }, color: tickColor, padding: 10 },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.dataset.pointRadius === 0) return null; // skip ref lines in tooltip
              if (ctx.parsed.y == null) return 'Not logged';
              return ' ' + ctx.dataset.label + ': ' + ctx.parsed.y + ' ' + meta.unit;
            },
          },
        },
      },
      scales: {
        x: {
          grid:   { color: gridColor },
          ticks:  { color: tickColor, font: { size: 10 }, maxTicksLimit: 8 },
          border: { display: false },
        },
        y: {
          min:    meta.yMin,
          max:    meta.yMax,
          grid:   { color: gridColor },
          ticks:  { color: tickColor, font: { size: 10 }, maxTicksLimit: 5 },
          border: { display: false },
        },
      },
    },
  });

  // Render ref line legend
  const refLegend = document.getElementById('vref-' + type);
  if (refLegend && meta.refLines.length) {
    refLegend.innerHTML = meta.refLines.map(r =>
      `<span style="display:flex;align-items:center;gap:4px">
         <span style="width:18px;height:2px;background:${r.color};display:inline-block;border-radius:1px"></span>
         ${r.label}
       </span>`
    ).join('');
  }
}

// After saving a vital, reload both the list AND the trend chart
const _origSaveVitalFromView = saveVitalFromView;
saveVitalFromView = async function() {
  await _origSaveVitalFromView.apply(this, arguments);
  setTimeout(loadVitalTrends, 400);  // preserves _vitalTrendDays
};


// ════════════════════════════════════════════════════════════════
// SYMPTOM PATTERN DETECTOR
// ════════════════════════════════════════════════════════════════

async function loadSymptomPatterns() {
  const panel = document.getElementById('symptom-patterns-panel');
  if (!panel) return;

  const data = await fetch('/api/symptoms/patterns?days=30', {cache:'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data || data.total_logs === 0) {
    panel.innerHTML = '';
    return;
  }

  const { symptoms, alerts, co_occur, heatmap } = data;
  if (!symptoms.length) { panel.innerHTML = ''; return; }

  // 'insufficient' (too few loggings to judge) shows no arrow at all — a blank
  // reads as "no trend yet", never a false ↑ worsening on a symptom.
  const TREND_ICON  = { worsening:'↑', improving:'↓', stable:'→', insufficient:'' };
  const TREND_COLOR = { worsening:'#EF4444', improving:'#22C55E', stable:'#888780', insufficient:'#888780' };
  const TIME_LABEL  = { morning:'morning', afternoon:'afternoon', evening:'evening',
                        night:'night', all_day:'all day' };
  const SEV_COLOR   = s => s >= 8 ? '#EF4444' : s >= 5 ? '#F59E0B' : '#22C55E';

  // ── Alerts banner ─────────────────────────────────────────────
  const alertsHTML = alerts.length ? `
    <div class="spp-alerts">
      <div class="spp-alerts-head">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Recurring this week
      </div>
      <div class="spp-alerts-list">
        ${alerts.map(a => `
          <div class="spp-alert-chip">
            <span class="spp-alert-name">${escHtml(a.name)}</span>
            <span class="spp-alert-count">${a.count}× · mostly ${TIME_LABEL[a.peak_time]}</span>
          </div>`).join('')}
      </div>
    </div>` : '';

  // ── Symptom frequency bars ────────────────────────────────────
  const maxCount = symptoms[0]?.count || 1;
  const freqRows = symptoms.slice(0, 8).map(s => `
    <div class="spp-freq-row">
      <div class="spp-freq-name">${escHtml(s.name)}</div>
      <div class="spp-freq-bar-wrap">
        <div class="spp-freq-bar" style="width:${Math.round(s.count/maxCount*100)}%;background:${SEV_COLOR(s.avg_severity)}"></div>
      </div>
      <div class="spp-freq-meta">
        <span>${s.count}×</span>
        <span style="color:${TREND_COLOR[s.trend] || '#888780'};font-weight:600">${TREND_ICON[s.trend] || ''}</span>
        <span style="color:var(--gray-400);font-size:11px">${TIME_LABEL[s.peak_time]}</span>
      </div>
    </div>`).join('');

  // ── Heatmap ───────────────────────────────────────────────────
  const heatDates    = heatmap.dates;
  const heatNames    = heatmap.names;
  const SHORT_DATES  = heatDates.map(d => {
    const dt = new Date(d + 'T12:00:00');
    return (dt.getMonth()+1) + '/' + dt.getDate();
  });

  const heatRows = heatNames.map(name => {
    const vals = heatmap.data[name] || [];
    const cells = vals.map((v, i) => {
      if (!v) return `<div class="spp-heat-cell spp-heat-0" title="${heatDates[i]}: none"></div>`;
      const bg = v >= 8 ? '#FCA5A5' : v >= 5 ? '#FCD34D' : '#86EFAC';
      return `<div class="spp-heat-cell" style="background:${bg}" title="${heatDates[i]}: severity ${v}"></div>`;
    }).join('');
    return `
      <div class="spp-heat-row">
        <div class="spp-heat-name">${escHtml(name)}</div>
        <div class="spp-heat-cells">${cells}</div>
      </div>`;
  }).join('');

  const heatLegend = `
    <div class="spp-heat-legend">
      <span class="spp-heat-leg-item"><span class="spp-heat-cell spp-heat-0" style="display:inline-block"></span> None</span>
      <span class="spp-heat-leg-item"><span class="spp-heat-cell" style="background:#86EFAC;display:inline-block"></span> Mild</span>
      <span class="spp-heat-leg-item"><span class="spp-heat-cell" style="background:#FCD34D;display:inline-block"></span> Moderate</span>
      <span class="spp-heat-leg-item"><span class="spp-heat-cell" style="background:#FCA5A5;display:inline-block"></span> Severe</span>
    </div>`;

  // ── Co-occurrence ─────────────────────────────────────────────
  const coHTML = co_occur.length ? `
    <div class="panel" style="padding:16px 20px">
      <div class="panel-header" style="margin-bottom:12px">
        <h2 class="panel-title">Often appear together</h2>
        <span class="panel-badge">30 days</span>
      </div>
      ${co_occur.map(pair => `
        <div class="spp-co-row">
          <span class="spp-co-name">${escHtml(pair.a)}</span>
          <span class="spp-co-plus">+</span>
          <span class="spp-co-name">${escHtml(pair.b)}</span>
          <span class="spp-co-count">${pair.count} days</span>
        </div>`).join('')}
    </div>` : '';

  panel.innerHTML = `
    ${alertsHTML}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px">

      <!-- Frequency + trend -->
      <div class="panel" style="padding:16px 20px">
        <div class="panel-header" style="margin-bottom:14px">
          <h2 class="panel-title">Frequency (30 days)</h2>
        </div>
        <div class="spp-freq-legend" style="margin-bottom:10px">
          <span style="color:#22C55E">● mild</span>
          <span style="color:#F59E0B">● moderate</span>
          <span style="color:#EF4444">● severe</span>
          <span style="margin-left:8px;color:var(--gray-400);font-size:11px">↑ worsening  ↓ improving  → stable</span>
        </div>
        ${freqRows}
      </div>

      <!-- Heatmap + co-occurrence -->
      <div style="display:flex;flex-direction:column;gap:18px">
        <div class="panel" style="padding:16px 20px">
          <div class="panel-header" style="margin-bottom:12px">
            <h2 class="panel-title">14-day calendar</h2>
          </div>
          <div class="spp-heat-date-row">
            <div style="width:90px;flex-shrink:0"></div>
            ${SHORT_DATES.map(d => `<div class="spp-heat-date">${d}</div>`).join('')}
          </div>
          ${heatRows}
          ${heatLegend}
        </div>
        ${coHTML}
      </div>
    </div>`;
}


// ════════════════════════════════════════════════════════════════
// SLEEP TREND CHART
// ════════════════════════════════════════════════════════════════

let _sleepChart = null;

// Active sleep trend window — 7, 14, or 30
let _sleepTrendDays = 7;

async function loadSleepTrend(days) {
  if (days) _sleepTrendDays = days;
  const d = _sleepTrendDays;

  const data = await fetch(`/api/sleep/trend?days=30`, {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data) return;

  // ── Stats strip ───────────────────────────────────────────────
  const strip = document.getElementById('sleep-summary-strip');
  const histEl = document.getElementById('sleep-history-sv');
  const s = data.stats;

  if (!data.total || !s.avg_duration) {
    if (strip) strip.innerHTML = '<div style="color:var(--gray-400);font-size:13px;text-align:center;padding:20px 0">No sleep logged yet</div>';
  } else {
    // 'insufficient' → a calm dash, not a red verdict. A trend needs a week of
    // nights (see the API); until then we say so plainly instead of alarming
    // the user off one short night.
    const TREND_ICON  = {improving: '↑ improving', worsening: '↓ worsening', stable: '→ stable', insufficient: '—'};
    const TREND_COLOR = {improving: '#22C55E',      worsening: '#EF4444',      stable: '#888780',  insufficient: '#888780'};
    const trendInsufficient = s.dur_trend === 'insufficient' || !TREND_ICON[s.dur_trend];
    if (strip) {
      strip.innerHTML = `
        <div class="sleep-stat-grid">
          <div class="sleep-stat-card">
            <div class="sleep-stat-val">${s.avg_duration}h</div>
            <div class="sleep-stat-lab">Avg duration</div>
          </div>
          <div class="sleep-stat-card">
            <div class="sleep-stat-val">${s.best_night}h</div>
            <div class="sleep-stat-lab">Best night</div>
          </div>
          <div class="sleep-stat-card">
            <div class="sleep-stat-val">${s.good_pct}%</div>
            <div class="sleep-stat-lab">Nights ≥ 7h</div>
          </div>
          <div class="sleep-stat-card">
            <div class="sleep-stat-val" style="color:${TREND_COLOR[s.dur_trend] || '#888780'}">${TREND_ICON[s.dur_trend] || '—'}</div>
            <div class="sleep-stat-lab">${trendInsufficient ? 'Trend · need a week' : 'Trend'}</div>
          </div>
        </div>`;
    }
  }

  // ── Recent history list ──────────────────────────────────────
  const QMAP = {1:'😩',2:'😕',3:'😐',4:'😊',5:'😴'};
  if (histEl) {
    const recent = (data.logs || []).slice().reverse().slice(0, 7);
    const QCLS   = {1:'poor',2:'poor',3:'ok',4:'good',5:'great'};
    histEl.innerHTML = recent.length ? recent.map(r => {
      const pct = Math.min((r.duration_h / 9) * 100, 100).toFixed(0);
      return `
        <div class="sleep-log-row">
          <div class="sleep-log-date">${r.date_key.slice(5)}</div>
          <div class="sleep-log-dur">${r.duration_h}h</div>
          <div class="sleep-bar-col">
            <div class="sleep-bar-fill ${QCLS[r.quality]||'ok'}" style="width:${pct}%"></div>
          </div>
          <div class="sleep-log-qual">${QMAP[r.quality]||'😐'}</div>
          <button class="todo-act-btn del" data-ev-click="delSleep('${r.id}')" title="Delete">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </div>`;
    }).join('') : '';
  }

  // ── Trend chart ───────────────────────────────────────────────
  const trendCard = document.getElementById('sleep-trend-card');
  if (!trendCard) return;
  trendCard.style.display = '';

  // Render toggle buttons
  const badge = document.getElementById('sleep-trend-badge');
  if (badge) {
    badge.innerHTML = `
      <div class="trend-toggle">
        <button class="trend-toggle-btn${d===7?' active':''}"  data-ev-click="loadSleepTrend(7)">Weekly</button>
        <button class="trend-toggle-btn${d===14?' active':''}" data-ev-click="loadSleepTrend(14)">Bi-weekly</button>
        <button class="trend-toggle-btn${d===30?' active':''}" data-ev-click="loadSleepTrend(30)">Monthly</button>
      </div>`;
  }

  // Build date range for selected window
  const today = new Date();
  const dateRange = Array.from({length: d}, (_, i) => {
    const dt = new Date(today);
    dt.setDate(dt.getDate() - (d - 1 - i));
    return dt.toISOString().split('T')[0];
  });

  // Index logs by date
  const logByDate = {};
  (data.logs || []).forEach(l => { logByDate[l.date_key] = l; });

  // Build labels — for 7d use day names, for 14/30 use M/D
  const labels = dateRange.map(date => {
    const dt = new Date(date + 'T12:00:00');
    if (d === 7) return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dt.getDay()];
    return (dt.getMonth()+1) + '/' + dt.getDate();
  });

  const durations  = dateRange.map(date => logByDate[date]?.duration_h ?? null);
  const qualities  = dateRange.map(date => logByDate[date]?.quality    ?? null);
  const hasAnyData = durations.some(v => v !== null);
  const logged     = durations.filter(v => v !== null).length;

  const sub = document.getElementById('sleep-trend-sub');
  if (sub) {
    sub.textContent = hasAnyData
      ? `${logged} of ${d} nights logged · avg ${s?.avg_duration ?? '—'}h`
      : 'No nights logged yet — start tracking to see your trend';
  }

  // Load Chart.js if needed
  if (!window.Chart) {
    await new Promise((res, rej) => {
      const sc = document.createElement('script');
      sc.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
      sc.onload = res; sc.onerror = rej;
      document.head.appendChild(sc);
    });
  }

  const canvas = document.getElementById('sleep-chart');
  if (!canvas) return;
  if (_sleepChart) { _sleepChart.destroy(); _sleepChart = null; }

  const barColors  = durations.map(v =>
    v === null ? 'rgba(0,0,0,0.04)' : v >= 7 ? '#22C55E55' : v >= 6 ? '#F59E0B55' : '#EF444455'
  );
  const barBorders = durations.map(v =>
    v === null ? 'rgba(0,0,0,0.08)' : v >= 7 ? '#5A9E70' : v >= 6 ? '#E0A34E' : '#DC2626'
  );

  const isDark  = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const grid    = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)';
  const tickCol = '#9CA3AF';

  // Quality emoji color for tooltip
  const QUALITY_LABEL = {1:'😩 Terrible',2:'😕 Poor',3:'😐 Okay',4:'😊 Good',5:'😴 Great'};

  // Custom plugin: draw quality emoji below x-axis labels
  const qualityEmojiPlugin = {
    id: 'qualityEmoji',
    afterDraw(chart) {
      const ctx2  = chart.ctx;
      const xAxis = chart.scales.x;
      const QEMOJI = {1:'😩',2:'😕',3:'😐',4:'😊',5:'😴'};
      ctx2.save();
      ctx2.font = d <= 14 ? '16px serif' : '13px serif';
      ctx2.textAlign = 'center';
      xAxis.ticks.forEach((tick, i) => {
        const q = qualities[i];
        if (q == null) return;
        const x = xAxis.getPixelForTick(i);
        const y = chart.chartArea.bottom + (d <= 14 ? 38 : 34);
        ctx2.fillText(QEMOJI[q] || '', x, y);
      });
      ctx2.restore();
    },
  };

  _sleepChart = new window.Chart(canvas, {
    plugins: [qualityEmojiPlugin],
    data: {
      labels,
      datasets: [
        {
          type:            'bar',
          label:           'Duration (h)',
          data:            durations,
          backgroundColor: barColors,
          borderColor:     barBorders,
          borderWidth:     1.5,
          borderRadius:    5,
          yAxisID:         'y',
        },
        {
          type:        'line',
          label:       '7h target',
          data:        Array(d).fill(7),
          borderColor: '#22C55E',
          borderWidth: 1,
          borderDash:  [4, 4],
          pointRadius: 0,
          yAxisID:     'y',
        },
      ],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      layout: { padding: { bottom: d <= 14 ? 28 : 22 } },  // room for emoji row
      interaction:         {mode: 'index', intersect: false},
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            boxWidth: 10, boxHeight: 3,
            font: {size: 11}, color: tickCol, padding: 14,
            filter: item => item.text !== '7h target',
          },
        },
        tooltip: {
          backgroundColor: 'rgba(17,24,39,0.88)',
          padding: 10,
          titleFont: {size: 12, weight: '600'},
          bodyFont:  {size: 12},
          callbacks: {
            label: ctx => {
              if (ctx.dataset.label === '7h target') return null;
              if (ctx.parsed.y === null || ctx.parsed.y === undefined) return null;
              return '  Duration: ' + ctx.parsed.y + 'h';
            },
            afterLabel: ctx => {
              if (ctx.dataset.label === '7h target') return null;
              const q = qualities[ctx.dataIndex];
              if (q == null) return null;
              return '  Quality: ' + (QUALITY_LABEL[q] || '');
            },
            afterBody: items => {
              const real = items.filter(i => i.dataset.label !== '7h target');
              if (real.every(i => i.parsed.y === null || i.parsed.y === undefined)) {
                return ['  Not logged'];
              }
              return [];
            },
          },
          filter: item => item.dataset.label !== '7h target',
        },
      },
      scales: {
        x: {
          grid:  {color: grid},
          ticks: {
            color: tickCol, font: {size: 10},
            maxTicksLimit: d === 30 ? 10 : d,
          },
          border: {display: false},
        },
        y: {
          min: 0, max: 11,
          grid: {color: grid},
          ticks: {
            color: tickCol, font: {size: 10},
            callback: v => v + 'h',
            stepSize: 2,
          },
          border: {display: false},
        },
      },
    },
  });

  // ── Week strip ────────────────────────────────────────────────
  const weekStrip = document.getElementById('sleep-week-strip');
  if (weekStrip && data.weekly?.length) {
    weekStrip.innerHTML = data.weekly.map(w => `
      <div class="sleep-week-card">
        <div class="sleep-week-label">${w.label}</div>
        <div class="sleep-week-dur">${w.avg_dur}h</div>
        <div class="sleep-week-nights">${w.good}/${w.nights} good nights</div>
      </div>`).join('');
  }
}


// ════════════════════════════════════════════════════════════════
// CALORIE BALANCE — 7-day trend chart
// ════════════════════════════════════════════════════════════════

let _calChart = null;

async function renderCalorieTrendChart(daily) {
  const section = document.getElementById('cbd-trend-section');
  const canvas  = document.getElementById('cbd-trend-chart');
  if (!section || !canvas || !daily.length) return;

  // Only show when at least 2 days have food logged
  const logged = daily.filter(d => d.logged);
  if (logged.length < 2) return;
  section.style.display = '';

  if (!window.Chart) {
    await new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  if (_calChart) { _calChart.destroy(); _calChart = null; }

  const isDark   = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const gridCol  = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const tickCol  = '#888780';

  const labels = daily.map(d => {
    const dt = new Date(d.date + 'T12:00:00');
    return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dt.getDay()];
  });

  // Bar colour: green if under budget, red if over
  const barColors = daily.map(d =>
    !d.logged ? 'transparent' :
    d.net >= 0 ? '#22C55E66' : '#EF444466'
  );
  const barBorders = daily.map(d =>
    !d.logged ? 'transparent' :
    d.net >= 0 ? '#5A9E70' : '#DC2626'
  );

  _calChart = new window.Chart(canvas, {
    data: {
      labels,
      datasets: [
        {
          type:            'bar',
          label:           'Eaten',
          data:            daily.map(d => d.eaten || 0),
          backgroundColor: barColors,
          borderColor:     barBorders,
          borderWidth:     1,
          borderRadius:    3,
          yAxisID:         'y',
        },
        {
          type:            'line',
          label:           'Budget',
          data:            daily.map(d => d.budget),
          borderColor:     '#4F8D74',
          backgroundColor: 'transparent',
          borderWidth:     1.5,
          borderDash:      [4, 3],
          pointRadius:     0,
          yAxisID:         'y',
        },
      ],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction:         {mode: 'index', intersect: false},
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            boxWidth: 10, boxHeight: 2,
            font: {size: 10}, color: tickCol, padding: 10,
          },
        },
        tooltip: {
          callbacks: {
            afterBody: items => {
              const idx = items[0]?.dataIndex;
              if (idx == null) return '';
              const d = daily[idx];
              if (!d.logged) return 'Not logged';
              const diff = d.net;
              return diff >= 0
                ? `${diff} kcal under budget`
                : `${Math.abs(diff)} kcal over budget`;
            },
          },
        },
      },
      scales: {
        x: {
          grid:   {display: false},
          ticks:  {color: tickCol, font: {size: 10}},
          border: {display: false},
        },
        y: {
          min:    0,
          grid:   {color: gridCol},
          ticks:  {
            color: tickCol, font: {size: 10},
            callback: v => v >= 1000 ? (v/1000).toFixed(1) + 'k' : v,
            maxTicksLimit: 4,
          },
          border: {display: false},
        },
      },
    },
  });
}


// ════════════════════════════════════════════════════════════════
// FITNESS PERSONAL RECORDS (PRs)
// ════════════════════════════════════════════════════════════════

async function loadFitnessPRs() {
  const section = document.getElementById('fitness-pr-section');
  if (!section) return;

  const data = await fetch('/api/fitness/prs', {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data?.has_data || !data.prs.length) {
    section.innerHTML = '';
    return;
  }

  const { prs, total_activities, recent_prs } = data;

  // Group PRs by category for display
  const grouped = {};
  prs.forEach(pr => {
    const cat = pr.category;
    if (!grouped[cat]) grouped[cat] = { icon: pr.icon, metrics: [] };
    grouped[cat].metrics.push(pr);
  });

  const PRCards = Object.entries(grouped).map(([cat, group]) => {
    const metricsHTML = group.metrics.map(pr => {
      const val    = pr.value_display || (pr.unit === 'km' ? pr.value + ' km' : pr.value + ' ' + pr.unit);
      const date   = new Date(pr.date + 'T12:00:00').toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
      const newTag = pr.is_recent
        ? '<span class="pr-new-tag">🏆 New!</span>'
        : '';
      return `
        <div class="pr-metric-row">
          <div class="pr-metric-info">
            <div class="pr-metric-name">${escHtml(pr.metric)}</div>
            <div class="pr-metric-date">${escHtml(pr.name)} · ${date}</div>
          </div>
          <div class="pr-metric-right">
            ${newTag}
            <div class="pr-metric-val">${escHtml(String(val))}</div>
          </div>
        </div>`;
    }).join('');

    return `
      <div class="pr-card">
        <div class="pr-card-header">
          <span class="pr-card-icon">${group.icon}</span>
          <span class="pr-card-cat">${escHtml(cat)}</span>
        </div>
        ${metricsHTML}
      </div>`;
  }).join('');

  section.innerHTML = `
    <div class="panel" style="padding:18px 20px 20px">
      <div class="panel-header" style="margin-bottom:14px">
        <h2 class="panel-title">Personal Records</h2>
        <div style="display:flex;align-items:center;gap:8px">
          ${recent_prs > 0 ? `<span class="panel-badge" style="background:#DCFCE7;color:#468A5B">🏆 ${recent_prs} new this month</span>` : ''}
          <span class="panel-badge">${total_activities} workouts all-time</span>
        </div>
      </div>
      <div class="pr-grid">${PRCards}</div>
    </div>`;
}


// ════════════════════════════════════════════════════════════════
// MOOD × SLEEP CORRELATION
// ════════════════════════════════════════════════════════════════

let _moodSleepChart = null;
let _moodSleepDays  = 30;   // default Monthly

async function loadMoodSleepCorrelation(days) {
  if (days) _moodSleepDays = days;
  const d = _moodSleepDays;

  const section = document.getElementById('mood-sleep-section');
  if (!section) return;

  const data = await fetch(`/api/mood-sleep/correlation?days=${d}`, {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data) return;

  const mscToggle = `
    <div class="trend-toggle">
      <button class="trend-toggle-btn${d===30?' active':''}"  data-ev-click="loadMoodSleepCorrelation(30)">Monthly</button>
      <button class="trend-toggle-btn${d===90?' active':''}"  data-ev-click="loadMoodSleepCorrelation(90)">3 months</button>
    </div>`;

  // Not enough data yet
  if (!data.has_data || data.need_more) {
    const needed = data.need_count || 5;
    section.innerHTML = `
      <div class="panel" style="padding:20px 24px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <h2 class="panel-title">Mood × Sleep correlation</h2>
          ${mscToggle}
        </div>
        <div style="text-align:center;padding:24px 0">
          <div style="font-size:28px;margin-bottom:10px">🌙😊</div>
          <div style="font-size:14px;font-weight:600;color:var(--gray-700);margin-bottom:6px">Not enough data yet</div>
          <div style="font-size:13px;color:var(--gray-400)">
            Log both mood (in Journal) and sleep on the same day ${needed} more time${needed !== 1 ? 's' : ''} to unlock this insight.
          </div>
        </div>
      </div>`;
    return;
  }

  const { paired, correlation, per_mood, threshold, insight, matched_days } = data;
  const r_val   = correlation?.r ?? 0;
  const strength = correlation?.strength || 'none';

  // Strength indicator color
  const STRENGTH_COLOR = { strong:'#22C55E', moderate:'#F59E0B', weak:'#9CA3AF', none:'#9CA3AF' };
  const strengthColor  = STRENGTH_COLOR[strength];

  // ── Per-mood sleep average bars ──────────────────────────────
  const MOOD_ORDER = ['excited','happy','calm','neutral','tired','anxious','sad','terrible'];
  const moodRows = MOOD_ORDER
    .filter(m => per_mood[m])
    .map(m => {
      const pm  = per_mood[m];
      const pct = Math.min(Math.round(pm.avg_duration / 10 * 100), 100);
      return `
        <div class="msc-mood-row">
          <div class="msc-mood-emoji">${moodEmoji(m)}</div>
          <div class="msc-mood-bar-wrap">
            <div class="msc-mood-bar" style="width:${pct}%;background:${moodColor(m)}"></div>
          </div>
          <div class="msc-mood-val">${pm.avg_duration}h</div>
          <div class="msc-mood-count">${pm.count}d</div>
        </div>`;
    }).join('');

  // ── 7h threshold split ────────────────────────────────────────
  const above = threshold?.above_7h || {};
  const below = threshold?.below_7h || {};
  const SCORE_LABELS = {1:'Rough',2:'Low',3:'Okay',4:'Neutral',5:'Calm',6:'Good',7:'Great'};
  const aboveLabel = above.avg_mood_score ? SCORE_LABELS[Math.round(above.avg_mood_score)] || '' : '—';
  const belowLabel = below.avg_mood_score ? SCORE_LABELS[Math.round(below.avg_mood_score)] || '' : '—';

  section.innerHTML = `
    <div class="panel" style="padding:18px 20px 20px">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:14px">
        <div>
          <h2 class="panel-title">Mood × Sleep correlation</h2>
          <div style="font-size:12px;margin-top:3px;display:flex;gap:8px;align-items:center">
            <span style="background:${strengthColor}22;color:${strengthColor};padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600">${strength} correlation</span>
            <span style="color:var(--gray-400)">${matched_days} matched days</span>
          </div>
        </div>
        ${mscToggle}
      </div>

      <!-- Insight banner -->
      <div class="msc-insight-banner">
        <span class="msc-insight-icon">💡</span>
        <span class="msc-insight-text">${escHtml(insight)}</span>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:16px">

        <!-- Left: per-mood sleep averages -->
        <div>
          <div style="font-size:12px;font-weight:600;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px">
            Avg sleep per mood
          </div>
          ${moodRows || '<div style="color:var(--gray-400);font-size:13px">Not enough data</div>'}
        </div>

        <!-- Right: 7h split + correlation badge -->
        <div style="display:flex;flex-direction:column;gap:12px">

          <!-- Correlation coefficient -->
          <div class="msc-r-card">
            <div class="msc-r-val" style="color:${strengthColor}">${r_val > 0 ? '+' : ''}${r_val.toFixed(2)}</div>
            <div class="msc-r-label">Pearson r</div>
            <div class="msc-r-sub">
              ${Math.abs(r_val) >= 0.3 ? 'Statistically meaningful' : 'More data needed'}
            </div>
          </div>

          <!-- 7h threshold split -->
          <div class="msc-split-card">
            <div style="font-size:12px;font-weight:600;color:var(--gray-500);margin-bottom:10px">Sleep ≥ 7h vs < 7h</div>
            <div class="msc-split-row">
              <div class="msc-split-block msc-split-block--good">
                <div class="msc-split-val">🌙 ${aboveLabel}</div>
                <div class="msc-split-sub">After ≥7h (${above.count || 0} nights)</div>
              </div>
              <div class="msc-split-block msc-split-block--low">
                <div class="msc-split-val">😪 ${belowLabel}</div>
                <div class="msc-split-sub">After &lt;7h (${below.count || 0} nights)</div>
              </div>
            </div>
          </div>

        </div>
      </div>

      <!-- Scatter plot -->
      <div id="msc-chart-section" style="margin-top:18px;display:none">
        <div style="font-size:12px;font-weight:600;color:var(--gray-500);text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px">
          Sleep duration vs mood — scatter
        </div>
        <div style="position:relative;height:200px">
          <canvas id="msc-scatter"></canvas>
        </div>
        <div style="font-size:11px;color:var(--gray-400);margin-top:6px;text-align:center">
          Each dot = one day · horizontal = sleep hours · vertical = mood score
        </div>
      </div>

    </div>`;

  // Render scatter chart if 5+ points
  if (paired.length >= 5) {
    renderMoodSleepScatter(paired);
  }
}

async function renderMoodSleepScatter(paired) {
  const section = document.getElementById('msc-chart-section');
  const canvas  = document.getElementById('msc-scatter');
  if (!section || !canvas) return;
  section.style.display = '';

  if (!window.Chart) {
    await new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  if (_moodSleepChart) { _moodSleepChart.destroy(); _moodSleepChart = null; }

  const isDark  = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const gridCol = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const tickCol = '#888780';

  const SCORE_LABELS = ['','Rough','Low','Okay','Neutral','Calm','Good','Great'];

  const points = paired.map(p => ({
    x: p.duration,
    y: p.score,
    mood: p.mood,
    date: p.date,
  }));

  // Colour each point by mood
  const pointColors = points.map(pt =>
    moodColor(pt.mood) + 'CC'
  );

  _moodSleepChart = new window.Chart(canvas, {
    type: 'scatter',
    data: {
      datasets: [{
        label:           'Days',
        data:            points,
        backgroundColor: pointColors,
        borderColor:     pointColors.map(c => c.slice(0,7)),
        borderWidth:     1,
        pointRadius:     6,
        pointHoverRadius:8,
      }],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const pt = ctx.raw;
              return ` ${moodEmoji(pt.mood)} ${pt.mood} after ${pt.x}h sleep (${pt.date})`;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: 'Sleep (hours)', color: tickCol, font: {size: 11} },
          min: 3, max: 11,
          grid:  { color: gridCol },
          ticks: { color: tickCol, font: {size: 10} },
          border:{ display: false },
        },
        y: {
          title: { display: true, text: 'Mood', color: tickCol, font: {size: 11} },
          min: 0.5, max: 7.5,
          grid:  { color: gridCol },
          ticks: {
            color: tickCol, font: {size: 10},
            callback: v => SCORE_LABELS[Math.round(v)] || '',
            stepSize: 1,
          },
          border:{ display: false },
        },
      },
    },
  });
}


// ════════════════════════════════════════════════════════════════
// WEEKLY DIGEST
// ════════════════════════════════════════════════════════════════

async function loadWeeklyDigest() {
  const section = document.getElementById('weekly-digest-section');
  if (!section) return;

  section.innerHTML = '<div style="height:4px"></div>'; // placeholder while loading

  const d = await fetch('/api/weekly-digest', {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!d) { section.innerHTML = ''; return; }

  const { headline, overall_score, scores, highlights, wins, concerns,
          period_label, tracked_areas } = d;

  // overall_score is null when there's nothing to score. It must not become 0:
  // a red 0 ring under "Nothing logged yet — start tracking" read as sarcasm,
  // and it said "you failed" where the truth was "you didn't track anything".
  const hasScore = overall_score != null;
  const scoreColor = overall_score >= 80 ? '#22C55E'
                   : overall_score >= 60 ? '#4F8D74'
                   : overall_score >= 40 ? '#F59E0B' : '#EF4444';

  // Mini score bars
  const SCORE_LABELS = {
    sleep: '🌙 Sleep', workouts: '🏃 Workouts',
    habits: '⭐ Habits', hydration: '💧 Hydration', nutrition: '🍽️ Nutrition',
  };
  // Only bar the areas they actually track. A null score means "not tracked",
  // and drawing it as an empty red 0% bar next to the real ones turns an
  // absence into a failure.
  const scoreBars = Object.entries(scores)
    .filter(([, val]) => val != null)
    .map(([key, val]) => `
    <div class="wd-score-row">
      <span class="wd-score-label">${SCORE_LABELS[key] || key}</span>
      <div class="wd-score-bar-wrap">
        <div class="wd-score-bar" style="width:${val}%;background:${
          val >= 80 ? '#22C55E' : val >= 60 ? '#4F8D74' : val >= 40 ? '#F59E0B' : '#EF4444'
        }"></div>
      </div>
      <span class="wd-score-pct">${val}%</span>
    </div>`).join('');

  // Highlights strip
  const highlightStrip = highlights.map(h => `
    <div class="wd-highlight">
      <div class="wd-highlight-icon">${h.icon}</div>
      <div class="wd-highlight-val">${escHtml(h.value)}</div>
      <div class="wd-highlight-label">${escHtml(h.label)}</div>
    </div>`).join('');

  // Wins and concerns
  const winsHTML = wins.length
    ? wins.map(w => `
        <div class="wd-item wd-item--win">
          <span class="wd-item-icon">${w.icon}</span>
          <span class="wd-item-text">${escHtml(w.text)}</span>
        </div>`).join('')
    : '<div style="font-size:13px;color:var(--gray-400);padding:8px 0">No highlights yet — keep logging!</div>';

  const concernsHTML = concerns.length
    ? concerns.map(c => `
        <div class="wd-item wd-item--concern">
          <span class="wd-item-icon">${c.icon}</span>
          <span class="wd-item-text">${escHtml(c.text)}</span>
        </div>`).join('')
    : '<div style="font-size:13px;color:var(--gray-400);padding:8px 0">Nothing to flag — great week!</div>';

  section.innerHTML = `
    <div class="wd-card" style="margin-bottom:20px">

      <!-- Header row -->
      <div class="wd-header">
        <div class="wd-header-left">
          <div class="wd-period">${escHtml(period_label)}</div>
          <div class="wd-headline">${escHtml(headline)}</div>
        </div>
        ${hasScore ? `
        <div class="wd-ring-wrap" title="Averaged across the ${tracked_areas} area${tracked_areas === 1 ? '' : 's'} you track">
          <svg width="64" height="64" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="26" fill="none" stroke="var(--gray-100)" stroke-width="6"/>
            <circle cx="32" cy="32" r="26" fill="none"
              stroke="${scoreColor}" stroke-width="6"
              stroke-dasharray="${Math.round(overall_score * 1.634)} 163.4"
              stroke-linecap="round"
              transform="rotate(-90 32 32)"/>
          </svg>
          <div class="wd-ring-num" style="color:${scoreColor}">${overall_score}</div>
        </div>` : ''}
      </div>

      <!-- Highlights strip -->
      ${highlights.length ? `<div class="wd-highlights">${highlightStrip}</div>` : ''}

      <!-- Scores + wins/concerns -->
      <div class="wd-body">
        <!-- Score bars (only the areas they track; hidden entirely if none) -->
        ${scoreBars ? `
        <div class="wd-scores">
          <div class="wd-section-title">Area scores</div>
          ${scoreBars}
        </div>` : ''}

        <!-- Wins and concerns -->
        <div class="wd-narrative">
          <div style="margin-bottom:14px">
            <div class="wd-section-title">✅ What went well</div>
            ${winsHTML}
          </div>
          <div>
            <div class="wd-section-title">📌 Worth watching</div>
            ${concernsHTML}
          </div>
        </div>
      </div>

    </div>`;
}


// ════════════════════════════════════════════════════════════════
// WEIGHT PROGRESS CHART
// ════════════════════════════════════════════════════════════════

let _weightChart = null;
let _weightTrendDays = 90;  // default 3 months

async function loadWeightProgressChart(days) {
  if (days) _weightTrendDays = days;
  const d = _weightTrendDays;

  const section = document.getElementById('bv-weight-chart-section');
  if (!section) return;

  const data = await fetch(`/api/body-metrics/trend?days=${d}`, {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data) return;

  const { logs, projection, stats } = data;

  // Not enough data
  if (!logs.length) {
    section.innerHTML = `
      <div class="panel" style="padding:20px 24px">
        <div class="panel-header" style="margin-bottom:10px">
          <h2 class="panel-title">Weight progress</h2>
        </div>
        <div style="text-align:center;padding:20px 0">
          <div style="font-size:24px;margin-bottom:10px">⚖️</div>
          <div style="font-size:14px;font-weight:600;color:var(--gray-700);margin-bottom:6px">No weight logged yet</div>
          <div style="font-size:13px;color:var(--gray-400)">Log your first weight entry above to start tracking progress.</div>
        </div>
      </div>`;
    return;
  }

  const s      = stats;
  const goal   = s.goal || 'maintain';
  const GOAL_LABELS = {
    lose_fast:'Lose weight fast', lose:'Lose weight',
    maintain:'Maintain', gain:'Gain muscle', gain_fast:'Build mass',
  };

  // Progress toward goal
  const hasGoal     = s.target_weight != null && goal !== 'maintain';
  const change      = s.total_change;
  const changeDir   = change < 0 ? '↓' : change > 0 ? '↑' : '→';
  const changeColor = (goal.startsWith('lose') && change <= 0) || (goal.startsWith('gain') && change >= 0)
    ? '#22C55E' : change === 0 ? '#888780' : '#F59E0B';

  // ETA text
  let etaText = '';
  if (s.eta_date) {
    const eta = new Date(s.eta_date + 'T12:00:00');
    const daysLeft = Math.round((eta - new Date()) / 86400000);
    etaText = daysLeft <= 0
      ? '🎉 Goal reached!'
      : `~${daysLeft} days to go (${eta.toLocaleDateString('en-US',{month:'short',day:'numeric'})})`;
  }

  // Stat cards
  const statCards = [
    {label: 'Current',   val: `${s.latest_weight} kg`,                 show: true},
    {label: 'Starting',  val: `${s.start_weight} kg`,                  show: !!s.start_weight},
    {label: 'Change',    val: `${changeDir} ${Math.abs(change)} kg`,   show: change !== 0, color: changeColor},
    {label: 'Target',    val: `${s.target_weight} kg`,                  show: hasGoal},
    {label: 'Progress',  val: `${s.pct_to_goal}%`,                      show: hasGoal && s.pct_to_goal != null},
    {label: 'Pace',      val: `${Math.abs(s.rate_per_week)}kg/wk`,      show: s.rate_per_week !== 0},
  ].filter(c => c.show);

  const statsHTML = statCards.map(c => `
    <div class="wpc-stat">
      <div class="wpc-stat-val" ${c.color ? `style="color:${c.color}"` : ''}>${escHtml(c.val)}</div>
      <div class="wpc-stat-label">${c.label}</div>
    </div>`).join('');

  const toggleHTML = `
    <div class="trend-toggle">
      <button class="trend-toggle-btn${d===30?' active':''}"  data-ev-click="loadWeightProgressChart(30)">Monthly</button>
      <button class="trend-toggle-btn${d===90?' active':''}"  data-ev-click="loadWeightProgressChart(90)">3 months</button>
      <button class="trend-toggle-btn${d===180?' active':''}" data-ev-click="loadWeightProgressChart(180)">6 months</button>
    </div>`;

  section.innerHTML = `
    <div class="panel" style="padding:18px 20px 20px">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:12px">
        <div>
          <h2 class="panel-title">Weight progress</h2>
          ${etaText ? `<div style="font-size:12px;color:#468A5B;margin-top:3px">${escHtml(etaText)}</div>` : ''}
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="panel-badge">${GOAL_LABELS[goal] || goal}</span>
          ${toggleHTML}
        </div>
      </div>

      <!-- Goal weight input -->
      <div class="wpc-goal-row">
        <label style="font-size:12.5px;color:var(--gray-600);flex-shrink:0">Target weight</label>
        <input type="number" class="form-input wpc-goal-input" id="wpc-target-weight"
               placeholder="e.g. 68.0" step="0.5"
               value="${s.target_weight || ''}"
               data-ev-change="saveTargetWeight(this.value)">
        <span style="font-size:12.5px;color:var(--gray-500);flex-shrink:0">kg</span>
        ${hasGoal && s.pct_to_goal != null ? `
          <div class="wpc-progress-pill">
            <div class="wpc-progress-fill" style="width:${s.pct_to_goal}%"></div>
          </div>
          <span style="font-size:11.5px;color:var(--gray-500);flex-shrink:0">${s.pct_to_goal}%</span>
        ` : ''}
      </div>

      <!-- Stat strip -->
      <div class="wpc-stats">${statsHTML}</div>

      <!-- Chart -->
      <div style="position:relative;height:220px;margin-top:16px">
        <canvas id="wpc-chart"></canvas>
      </div>

      <!-- Legend -->
      <div style="display:flex;gap:16px;margin-top:8px;font-size:11.5px;color:var(--gray-500);flex-wrap:wrap">
        <span style="display:flex;align-items:center;gap:5px">
          <span style="width:18px;height:3px;background:#4F8D74;display:inline-block;border-radius:1px"></span>
          Actual weight
        </span>
        ${hasGoal && projection.length ? `
          <span style="display:flex;align-items:center;gap:5px">
            <span style="width:18px;height:2px;background:#F59E0B;display:inline-block;border-radius:1px;border-top:2px dashed #F59E0B;height:0"></span>
            Projected at ${Math.abs(s.rate_per_week)} kg/week
          </span>
          <span style="display:flex;align-items:center;gap:5px">
            <span style="width:18px;height:2px;background:#22C55E;display:inline-block;border-radius:1px;border-top:2px dashed #22C55E;height:0"></span>
            Goal: ${s.target_weight} kg
          </span>` : ''}
      </div>
    </div>`;

  renderWeightChart(logs, projection, stats);
}

async function renderWeightChart(logs, projection, stats) {
  const canvas = document.getElementById('wpc-chart');
  if (!canvas) return;

  if (!window.Chart) {
    await new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  if (_weightChart) { _weightChart.destroy(); _weightChart = null; }

  const isDark   = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const gridCol  = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const tickCol  = '#888780';

  // Actual weight dataset — all log dates
  const actualLabels = logs.map(l => {
    const d = new Date(l.date_key + 'T12:00:00');
    return (d.getMonth()+1) + '/' + d.getDate();
  });
  const actualData = logs.map(l => l.weight_kg);

  // Combined date range for projection overlay
  const hasProjection = projection && projection.length > 0 && stats.target_weight;

  // Y-axis range
  const allWeights = actualData.slice();
  if (hasProjection) projection.forEach(p => allWeights.push(p.weight));
  if (stats.target_weight) allWeights.push(stats.target_weight);
  const minW = Math.floor(Math.min(...allWeights) - 2);
  const maxW = Math.ceil(Math.max(...allWeights) + 2);

  // Projection labels (only dates beyond last actual entry)
  const lastActualDate = logs[logs.length - 1].date_key;
  const projFuture     = (projection || []).filter(p => p.date > lastActualDate);

  // Build unified label set for combined chart
  const projLabels = projFuture.map(p => {
    const d = new Date(p.date + 'T12:00:00');
    return (d.getMonth()+1) + '/' + d.getDate();
  });

  const allLabels = [...actualLabels, ...projLabels];

  // Actual data padded with nulls for future dates
  const actualPadded = [
    ...actualData,
    ...projLabels.map(() => null),
  ];

  // Projection data padded with nulls for past dates
  // Overlap one point at the last actual to connect the lines
  const lastActualIdx = actualLabels.length - 1;
  const projPadded = [
    ...actualLabels.map((_, i) => i === lastActualIdx ? actualData[lastActualIdx] : null),
    ...projFuture.map(p => p.weight),
  ];

  // Goal line
  const goalLine = stats.target_weight
    ? allLabels.map(() => stats.target_weight)
    : null;

  const datasets = [
    {
      label:           'Weight',
      data:            actualPadded,
      borderColor:     '#4F8D74',
      backgroundColor: '#4F8D7418',
      borderWidth:     2.5,
      pointRadius:     logs.length > 30 ? 2 : 4,
      pointHoverRadius:6,
      tension:         0.35,
      fill:            true,
      spanGaps:        false,
    },
  ];

  if (hasProjection && projFuture.length) {
    datasets.push({
      label:           'Projected',
      data:            projPadded,
      borderColor:     '#F59E0B',
      backgroundColor: 'transparent',
      borderWidth:     2,
      borderDash:      [5, 4],
      pointRadius:     0,
      pointHoverRadius:4,
      tension:         0.2,
      fill:            false,
      spanGaps:        false,
    });
  }

  if (goalLine) {
    datasets.push({
      label:       'Goal',
      data:        goalLine,
      borderColor: '#22C55E',
      borderWidth: 1.5,
      borderDash:  [6, 4],
      pointRadius: 0,
      fill:        false,
    });
  }

  _weightChart = new window.Chart(canvas, {
    type: 'line',
    data: { labels: allLabels, datasets },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction:         { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.parsed.y == null) return 'Not logged';
              return ` ${ctx.dataset.label}: ${ctx.parsed.y} kg`;
            },
          },
        },
      },
      scales: {
        x: {
          grid:   { color: gridCol },
          ticks:  { color: tickCol, font: {size: 10}, maxTicksLimit: 10 },
          border: { display: false },
        },
        y: {
          min:    minW, max: maxW,
          grid:   { color: gridCol },
          ticks:  {
            color: tickCol, font: {size: 10},
            callback: v => v + ' kg',
            maxTicksLimit: 6,
          },
          border: { display: false },
        },
      },
    },
  });
}

async function saveTargetWeight(val) {
  const kg = parseFloat(val);
  if (!kg || kg < 20 || kg > 300) return;
  const r = await fetch('/api/food/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ target_weight_kg: kg }),
  }).then(r => r.json()).catch(() => null);
  if (r?.success) {
    showToast(`Target weight set: ${kg} kg`, 'success');
    loadWeightProgressChart();
  }
}


// ════════════════════════════════════════════════════════════════
// QUICK-ADD RECENT MEALS
// ════════════════════════════════════════════════════════════════

async function loadQuickMeals() {
  const el    = document.getElementById('quick-meals-content');
  const badge = document.getElementById('quick-meals-badge');
  if (!el) return;

  const data = await fetch('/api/food/recent-meals', {cache: 'no-store'})
    .then(r => r.json()).catch(() => null);

  if (!data) return;

  const { combos, yesterday, yesterday_total_cal, yesterday_date } = data;

  if (!combos.length && !Object.keys(yesterday).length) {
    el.innerHTML = `<div style="color:var(--gray-400);font-size:12.5px;text-align:center;padding:16px 0">
      Log meals for a few days to unlock quick-add shortcuts
    </div>`;
    return;
  }

  const MEAL_ICONS = {breakfast:'🌅',lunch:'☀️',snack:'🍎',dinner:'🌙'};

  // ── Yesterday shortcut (if has data and we're viewing today) ──
  const today = localToday();
  const isToday = foodDate === today;
  const ystdHtml = isToday && Object.keys(yesterday).length
    ? `<div class="qm-yesterday-banner">
        <div class="qm-yday-info">
          <div class="qm-yday-title">📋 Same as yesterday</div>
          <div class="qm-yday-sub">${Math.round(yesterday_total_cal)} kcal total</div>
        </div>
        <button class="qm-yday-btn" data-ev-click="copyYesterdayMeals()">Copy all</button>
       </div>`
    : '';

  // ── Combo chips ───────────────────────────────────────────────
  const comboHtml = combos.map((combo, idx) => {
    const icon     = MEAL_ICONS[combo.meal_type] || '🍽️';
    const repeated = combo.count > 1 ? `<span class="qm-freq">${combo.count}×</span>` : '';
    const macros   = `${Math.round(combo.total_cal)} kcal · ${combo.total_prot}g P`;

    return `
      <div class="qm-combo" data-ev-click="repeatMealCombo(${idx})">
        <div class="qm-combo-top">
          <span class="qm-combo-icon">${icon}</span>
          <span class="qm-combo-meal">${combo.meal_type}</span>
          ${repeated}
        </div>
        <div class="qm-combo-label">${escHtml(combo.label)}</div>
        <div class="qm-combo-macros">${macros}</div>
      </div>`;
  }).join('');

  el.innerHTML = ystdHtml + `<div class="qm-grid">${comboHtml}</div>`;
  if (badge) badge.textContent = `${combos.length} recent`;

  // Store for repeatMealCombo to access
  window._recentCombos    = combos;
  window._yesterdayMeals  = yesterday;
}

// Log a full combo to current foodDate
async function repeatMealCombo(idx) {
  const combo = (window._recentCombos || [])[idx];
  if (!combo) return;

  const promises = combo.items.map(item =>
    fetch('/api/food/log', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        food_id:    item.food_id,
        food_name:  item.food_name,
        meal_type:  combo.meal_type,
        date_key:   foodDate,
        quantity_g: item.quantity_g,
        calories:   item.calories,
        protein:    item.protein,
        carbs:      item.carbs,
        fat:        item.fat,
        fiber:      item.fiber,
      })
    }).then(r => r.json()).catch(() => null)
  );

  const results = await Promise.all(promises);
  const ok = results.every(r => r?.success);

  if (ok) {
    const MEAL_LABELS = {breakfast:'Breakfast',lunch:'Lunch',snack:'Snack',dinner:'Dinner'};
    showToast(`✓ ${MEAL_LABELS[combo.meal_type] || combo.meal_type} added (${Math.round(combo.total_cal)} kcal)`, 'success');
    loadFoodTracker();
  } else {
    showToast('Some items failed to log', 'error');
  }
}

// Copy all meals from yesterday to today
async function copyYesterdayMeals() {
  const yesterday = window._yesterdayMeals || {};
  const allItems  = Object.values(yesterday).flat();
  if (!allItems.length) return;

  const promises = allItems.map(item =>
    fetch('/api/food/log', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        food_id:    item.food_id,
        food_name:  item.food_name,
        meal_type:  item.meal_type,
        date_key:   foodDate,
        quantity_g: item.quantity_g,
        calories:   item.calories,
        protein:    item.protein,
        carbs:      item.carbs,
        fat:        item.fat,
        fiber:      item.fiber,
      })
    }).then(r => r.json()).catch(() => null)
  );

  const results = await Promise.all(promises);
  const ok = results.filter(r => r?.success).length;
  showToast(`✓ Copied ${ok} item${ok !== 1 ? 's' : ''} from yesterday`, 'success');
  loadFoodTracker();
}


// ════════════════════════════════════════════════════════════════
// HEALTH SCORE
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
// ONBOARDING — profile setup after new account creation
// ════════════════════════════════════════════════════════════════

let _obActivity = null;
let _obGoal     = null;

function showOnboarding() {
  document.getElementById('onboarding-overlay').style.display = '';
  // Carry over the name from the create-account form so it isn't asked twice
  const obName = document.getElementById('ob-name');
  if (obName && !obName.value && _currentUser?.name) obName.value = _currentUser.name;
}

function hideOnboarding() {
  document.getElementById('onboarding-overlay').style.display = 'none';
}

function obShowError(msg) {
  const el = document.getElementById('ob-error');
  if (el) { el.textContent = msg; el.style.display = ''; }
}
function obHideError() {
  const el = document.getElementById('ob-error');
  if (el) el.style.display = 'none';
}

function obSelectActivity(btn) {
  document.querySelectorAll('#ob-activity-grid .ob-option-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _obActivity = btn.dataset.val;
  obHideError();
}

function obSelectGoal(btn) {
  document.querySelectorAll('#ob-goal-grid .ob-option-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _obGoal = btn.dataset.val;
  obHideError();
}

function obNext() {
  obHideError();
  const name   = (document.getElementById('ob-name')?.value || '').trim();
  const age    = document.getElementById('ob-age')?.value;
  const gender = document.getElementById('ob-gender')?.value;

  if (!name)   { obShowError('Please enter your name'); return; }
  if (!age || parseInt(age) < 1 || parseInt(age) > 120) {
    obShowError('Please enter a valid age'); return;
  }
  if (!gender) { obShowError('Please select your biological sex'); return; }

  // Advance to step 2
  document.getElementById('ob-step-1').style.display = 'none';
  document.getElementById('ob-step-2').style.display = '';
  document.getElementById('ob-progress').style.background = '#4F8D74';

  // Populate timezone dropdown with detected value
  const detected = browserTimezone();
  const tzSel = document.getElementById('ob-timezone');
  const tzDetected = document.getElementById('ob-tz-detected');
  if (tzSel && detected) {
    const COMMON_TZ = [
      'Pacific/Honolulu','America/Anchorage','America/Los_Angeles','America/Denver',
      'America/Chicago','America/New_York','America/Sao_Paulo','Europe/London',
      'Europe/Paris','Europe/Berlin','Europe/Moscow','Asia/Dubai','Asia/Kolkata',
      'Asia/Bangkok','Asia/Singapore','Asia/Shanghai','Asia/Tokyo','Australia/Sydney',
    ];
    const allTz = COMMON_TZ.includes(detected) ? COMMON_TZ : [detected, ...COMMON_TZ];
    tzSel.innerHTML = allTz.map(tz =>
      `<option value="${tz}" ${tz === detected ? 'selected' : ''}>${tz.replace('_',' ')}</option>`
    ).join('');
    if (tzDetected) tzDetected.textContent = `Detected: ${detected.replace('_',' ')}`;
  }
}

function obBack() {
  document.getElementById('ob-step-2').style.display = 'none';
  document.getElementById('ob-step-1').style.display = '';
  document.getElementById('ob-progress').style.background = 'var(--gray-150)';
  obHideError();
}

async function obSubmit() {
  obHideError();

  if (!_obActivity) { obShowError('Please select your activity level'); return; }
  if (!_obGoal)     { obShowError('Please select your health goal');    return; }

  const name   = (document.getElementById('ob-name')?.value || '').trim();
  const age    = parseInt(document.getElementById('ob-age')?.value);
  const gender = document.getElementById('ob-gender')?.value;
  const weight = parseFloat(document.getElementById('ob-weight')?.value) || null;
  const height = parseFloat(document.getElementById('ob-height')?.value) || null;

  const btn = document.getElementById('ob-submit-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  const tz = document.getElementById('ob-timezone')?.value || browserTimezone();
  const payload = {
    name,
    age,
    gender,
    activity_level: _obActivity,
    goal:           _obGoal,
    timezone:       tz,
  };
  // Only include weight/height if provided
  if (weight) payload.weight_kg  = weight;
  if (height) payload.height_cm  = height;

  const r = await fetch('/api/food/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    credentials: 'same-origin',
    body: JSON.stringify(payload),
  }).catch(() => null);

  if (btn) { btn.disabled = false; btn.textContent = 'Start using Arogo'; }

  if (!r || !r.ok) {
    obShowError('Failed to save profile. Please try again.');
    return;
  }

  hideOnboarding();
  showApp();

  // First-run offer: 60+ users get a one-tap Simple View prompt.
  if (Number.isFinite(age) && age >= 60) {
    let decided = null;
    try { decided = localStorage.getItem('me_ui_mode'); } catch (e) {}
    if (!decided) setTimeout(offerSimpleMode, 400);
  }
}


// ════════════════════════════════════════════════════════════════
// SLEEP TIME DIAL — iOS-style scroll wheel picker
// ════════════════════════════════════════════════════════════════

const _dialState = {
  'bed-h': 11, 'bed-m': 0, 'bed-p': 1,   // 11:00 PM
  'wake-h': 7, 'wake-m': 0, 'wake-p': 0, // 7:00 AM
};

function initSleepDials() {
  renderDial('sdial-bed-h',  _hourItems(),    _dialState['bed-h'],  'bed-h');
  renderDial('sdial-bed-m',  _minuteItems(),  _dialState['bed-m'],  'bed-m');
  renderDial('sdial-bed-p',  _ampmItems(),    _dialState['bed-p'],  'bed-p');
  renderDial('sdial-wake-h', _hourItems(),    _dialState['wake-h'], 'wake-h');
  renderDial('sdial-wake-m', _minuteItems(),  _dialState['wake-m'], 'wake-m');
  renderDial('sdial-wake-p', _ampmItems(),    _dialState['wake-p'], 'wake-p');
  svUpdate();
}

function _hourItems()   { return Array.from({length:12}, (_,i) => String(i+1).padStart(2,'0')); }
function _minuteItems() { return Array.from({length:12}, (_,i) => String(i*5).padStart(2,'0')); }
function _ampmItems()   { return ['AM','PM']; }

const ITEM_H = 32;  // px per item

function renderDial(elId, items, selectedIdx, dialId) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = '';
  el.dataset.items  = JSON.stringify(items);
  el.dataset.sel    = selectedIdx;
  el.dataset.dialId = dialId;

  // Build infinite-feeling list with padding items
  const PAD = 2;
  for (let i = -PAD; i < items.length + PAD; i++) {
    const div = document.createElement('div');
    div.className = 'sdial-item';
    const idx = ((i % items.length) + items.length) % items.length;
    div.textContent = items[idx];
    div.dataset.idx = idx;
    el.appendChild(div);
  }

  // Scroll to selected
  el.style.transform = `translateY(${-(selectedIdx + PAD) * ITEM_H + ITEM_H}px)`;
  _bindDialEvents(el, items, dialId);
  _highlightDial(el, selectedIdx);
}

function _highlightDial(el, selIdx) {
  el.querySelectorAll('.sdial-item').forEach(item => {
    item.classList.toggle('sdial-item--sel', parseInt(item.dataset.idx) === selIdx);
  });
}

function _bindDialEvents(el, items, dialId) {
  const PAD = 2;
  let startY = 0, currentY = 0, startTrans = 0, isDragging = false;

  function getTransY() {
    const m = new DOMMatrix(getComputedStyle(el).transform);
    return m.m42;
  }

  function setIndex(idx) {
    const clamped = ((idx % items.length) + items.length) % items.length;
    _dialState[dialId] = clamped;
    el.dataset.sel = clamped;
    el.style.transition = 'transform .2s cubic-bezier(.25,.8,.25,1)';
    el.style.transform = `translateY(${-(clamped + PAD) * ITEM_H + ITEM_H}px)`;
    _highlightDial(el, clamped);
    svUpdate();
  }

  function snapFromOffset(offset) {
    // offset from top of drum — which item is centred?
    const raw = -offset / ITEM_H + 1 - PAD;
    const rounded = Math.round(raw);
    setIndex(rounded);
  }

  // Mouse / touch drag
  el.addEventListener('mousedown', e => {
    isDragging = true; startY = e.clientY; startTrans = getTransY();
    el.style.transition = 'none';
    el.style.cursor = 'grabbing';
  });
  window.addEventListener('mousemove', e => {
    if (!isDragging) return;
    currentY = e.clientY;
    el.style.transform = `translateY(${startTrans + currentY - startY}px)`;
  });
  window.addEventListener('mouseup', () => {
    if (!isDragging) return;
    isDragging = false;
    el.style.cursor = '';
    snapFromOffset(getTransY());
  });

  el.addEventListener('touchstart', e => {
    startY = e.touches[0].clientY; startTrans = getTransY();
    el.style.transition = 'none';
  }, {passive:true});
  el.addEventListener('touchmove', e => {
    currentY = e.touches[0].clientY;
    el.style.transform = `translateY(${startTrans + currentY - startY}px)`;
  }, {passive:true});
  el.addEventListener('touchend', () => {
    snapFromOffset(getTransY());
  });

  // Scroll wheel
  el.addEventListener('wheel', e => {
    e.preventDefault();
    const cur = parseInt(el.dataset.sel || 0);
    setIndex(cur + (e.deltaY > 0 ? 1 : -1));
  }, {passive:false});
}

function svUpdate() {
  // Read dial state and compute times
  const bh  = _dialState['bed-h'];   // 0–11 (index in _hourItems)
  const bm  = _dialState['bed-m'];   // 0–11 (index → 0,5,10...55)
  const bp  = _dialState['bed-p'];   // 0=AM, 1=PM
  const wh  = _dialState['wake-h'];
  const wm  = _dialState['wake-m'];
  const wp  = _dialState['wake-p'];

  // Convert to 24h
  function to24(hIdx, mIdx, ampm) {
    let h = hIdx + 1;  // 1–12
    if (ampm === 0 && h === 12) h = 0;
    if (ampm === 1 && h !== 12) h += 12;
    return h * 60 + mIdx * 5;
  }

  let bedMins  = to24(bh, bm, bp);
  let wakeMins = to24(wh, wm, wp);
  if (wakeMins <= bedMins) wakeMins += 24 * 60;  // next day

  const totalMins = wakeMins - bedMins;
  const h = Math.floor(totalMins / 60);
  const m = totalMins % 60;

  // Store hidden values for saveSleepLogFromView
  const bedH24  = Math.floor(bedMins  / 60);
  const bedM24  = bedMins  % 60;
  const wakeH24 = Math.floor(wakeMins / 60) % 24;
  const wakeM24 = wakeMins % 60;

  window._svBedTime  = String(bedH24).padStart(2,'0')  + ':' + String(bedM24).padStart(2,'0');
  window._svWakeTime = String(wakeH24).padStart(2,'0') + ':' + String(wakeM24).padStart(2,'0');

  // Duration chip
  const chip = document.getElementById('sv-duration-chip');
  if (chip) {
    chip.textContent = `${h}h ${m > 0 ? m + 'm' : ''}`;
    chip.className = 'sdial-duration ' +
      (h >= 7 ? 'sdial-dur--good' : h >= 5 ? 'sdial-dur--ok' : 'sdial-dur--low');
  }
}