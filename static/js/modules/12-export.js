// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Data export: section selector, date range, JSON/CSV download
// Medicine restock modal + daily nudge scheduler

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

const _nudgeFired = {};

async function checkDailyNudges() {
  if (Notification.permission !== 'granted') return;

  const now  = new Date();
  const hour = now.getHours();
  const min  = now.getMinutes();
  const timeStr = String(hour).padStart(2,'0') + ':' + String(min).padStart(2,'0');
  const today = now.toISOString().slice(0,10);

  // ── 2:00 PM — Hydration check ──
  if (hour === 14 && min < 10 && !_nudgeFired['hydration_'+today]) {
    _nudgeFired['hydration_'+today] = true;
    const h = await fetch(`/api/hydration/${today}`).then(r=>r.json()).catch(()=>null);
    if (h && h.pct < 50) {
      const msg = `You've had ${h.total_ml}ml so far. Goal is ${h.goal_ml}ml.`;
      new Notification('💧 Hydration check', { body: msg, tag: 'hydration-'+today });
      logNotification('hydration', '💧 Hydration Reminder', msg);
    }
  }

  // ── 10:00 PM — Sleep reminder ──
  if (hour === 22 && min < 10 && !_nudgeFired['sleep_'+today]) {
    _nudgeFired['sleep_'+today] = true;
    const s = await fetch('/api/sleep?days=1').then(r=>r.json()).catch(()=>[]);
    const loggedToday = s.some && s.some(l => l.date_key === today);
    if (!loggedToday) {
      const msg = "Don't forget to log tonight's sleep when you wake up.";
      new Notification('🌙 Sleep reminder', { body: msg, tag: 'sleep-'+today });
      logNotification('sleep', '🌙 Sleep Reminder', msg);
    }
  }

  // ── 6:00 PM — Mood / thought check ──
  if (hour === 18 && min < 10 && !_nudgeFired['thought_'+today]) {
    _nudgeFired['thought_'+today] = true;
    const t = await fetch(`/api/thoughts/${today}`).then(r=>r.json()).catch(()=>null);
    if (t && t.count === 0) {
      const msg = 'Take a moment to capture your thoughts for today.';
      new Notification('💭 Daily check-in', { body: msg, tag: 'thought-'+today });
      logNotification('system', '💭 Daily Check-in', msg);
    }
  }
}

// Run nudge check every 5 minutes
setInterval(checkDailyNudges, 5 * 60 * 1000);
// Also run once on load (in case user opens app at 2pm)
setTimeout(checkDailyNudges, 3000);

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
    return `<div class="export-section-card ${selected?'selected':''}" onclick="toggleExportSection('${s.key}')">
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