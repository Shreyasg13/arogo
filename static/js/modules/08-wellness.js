// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Wellness: strip sync, sleep tracker, body metrics, habit tracker,
// symptoms multi-select, vitals with reference ranges, hydration

async function loadWellnessStrip() {
  const r = await fetch('/api/wellness/today').then(r => r.json()).catch(() => null);
  if (!r) return;

  // Hydration
  const h = r.hydration;
  setText('dws-hydration', `${h.total_ml} ml`);
  const hBar = document.getElementById('dws-hydration-bar');
  if (hBar) hBar.style.width = h.pct + '%';

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
    hbBadge.style.color = hb.done === hb.total ? '#15803D' : 'var(--teal-700)';
  }

  // Symptoms
  const symEl = document.getElementById('dws-symptoms');
  if (symEl) {
    if (!r.symptoms.length) {
      symEl.textContent = 'None today';
    } else {
      symEl.textContent = r.symptoms.slice(0,2).map(s => s.name).join(', ');
      if (r.symptoms.length > 2) symEl.textContent += ` +${r.symptoms.length-2}`;
    }
  }
}

// ════════════════════════════════════════════════════════════
// WELLNESS TABS (Thoughts page)
// ════════════════════════════════════════════════════════════

let sleepQuality = 3;
let selectedVitalType = 'blood_pressure';
let selectedHabitColor = '#0E8F7E';

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
      <button class="todo-act-btn del" onclick="delSleep('${s.id}')">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
      </button>
    </div>`;
  }).join('');
}

async function delSleep(id) {
  await fetch(`/api/sleep/${id}`, {method:'DELETE'});
  loadSleepData(); loadWellnessStrip();
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
      date_key:     document.getElementById('body-date-input')?.value || new Date().toISOString().split('T')[0]
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
  if (di && !di.value) di.value = new Date().toISOString().split('T')[0];
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
      <div class="mood-dist-emoji">${MOOD_EMOJI[mood]||'😐'}</div>
      <div class="mood-dist-bar-track"><div class="mood-dist-bar" style="width:${pct}%;background:${MOOD_COLOR[mood]||'#0E8F7E'}"></div></div>
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
        <div style="font-size:13px;color:var(--gray-600)">🏆 Most common mood: ${sorted[0] ? `<strong>${MOOD_EMOJI[sorted[0][0]]} ${sorted[0][0]}</strong>` : '—'}</div>
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
  selectedHabitColor = '#0E8F7E';
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
  const el = document.getElementById('habits-grid');
  if (!el) return;
  const today = new Date().toISOString().split('T')[0];
  if (!r.habits.length) {
    el.innerHTML = `<div class="habits-empty">
      <div class="habits-empty-icon">⭐</div>
      <div class="habits-empty-text">No habits yet</div>
      <div class="habits-empty-sub">Click "Add Habit" to create your first one</div>
    </div>`;
    return;
  }
  el.innerHTML = r.habits.map(h => `
    <div class="habit-card" data-id="${h.id}">
      <div class="habit-color-stripe" style="background:${h.color}"></div>
      <button class="habit-delete-btn" onclick="deleteHabit('${h.id}')">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
      <div class="habit-card-top">
        <div class="habit-emoji">${h.emoji}</div>
        <div class="habit-streak">🔥${h.streak}</div>
      </div>
      <div class="habit-name">${escHtml(h.name)}</div>
      <button class="habit-check-btn ${h.done_today?'done':''}" onclick="toggleHabit('${h.id}','${today}')">
        ${h.done_today ? '✓ Done today' : 'Mark done today'}
      </button>
    </div>`).join('');
}

async function toggleHabit(id, date) {
  const r = await fetch(`/api/habits/${id}/toggle`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({date_key:date})
  }).then(r => r.json());
  if (r.success) { loadHabits(); loadWellnessStrip(); }
}

async function deleteHabit(id) {
  if (!confirm('Remove this habit?')) return;
  await fetch(`/api/habits/${id}`, {method:'DELETE'});
  showToast('Habit removed'); loadHabits(); loadWellnessStrip();
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
      `<span class="sym-chip">${escHtml(n)}<button class="sym-chip-del" onclick="removeSymptomChip('${escHtml(n).replace(/'/g,'\'')}')">×</button></span>`
    ).join('');
  }
}

async function logSymptoms() {
  if (selectedSymptoms.size === 0) return;
  const severity  = +document.getElementById('symptom-severity').value;
  const timeOfDay = document.getElementById('symptom-time').value;
  const notes     = document.getElementById('symptom-notes')?.value || '';
  const dateKey   = new Date().toISOString().split('T')[0];
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
    loadSymptoms();
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
  if (tab === 'symptoms') loadSymptoms();
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
      date_key: new Date().toISOString().split('T')[0]
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
    const today = new Date().toISOString().split('T')[0];
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
        <button class="todo-act-btn del" onclick="delSymptom('${s.id}')" title="Remove">
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
  loadSymptoms(); loadWellnessStrip();
}

// ════════════════════════════════════════════════════════════
// VITALS
// ════════════════════════════════════════════════════════════

const VITAL_CONFIG = {
  blood_pressure: {
    icon:'❤️', label:'Blood Pressure',
    fields:[{id:'vf1',label:'Systolic (mmHg)',ph:'120'},{id:'vf2',label:'Diastolic (mmHg)',ph:'80'}],
    unit:'mmHg',
    flag: (v1,v2) => (v1>140||v2>90) ? 'high' : (v1<90||v2<60) ? 'low' : 'normal',
    reference: 'Normal: 90–120 / 60–80 mmHg · Elevated: 120–129 / <80 · High: >130 / >80 · Low: <90 / <60',
    categories: [{label:'Normal',range:'<120/<80',color:'#22C55E'},{label:'Elevated',range:'120-129/<80',color:'#F59E0B'},{label:'High',range:'>130/>80',color:'#EF4444'},{label:'Low',range:'<90/<60',color:'#3B82F6'}]
  },
  blood_sugar: {
    icon:'🩸', label:'Blood Sugar',
    fields:[{id:'vf1',label:'mg/dL',ph:'100'}],
    unit:'mg/dL',
    flag: (v1) => v1>126 ? 'high' : v1<70 ? 'low' : 'normal',
    reference: 'Fasting: 70–100 mg/dL (Normal) · 100–125 (Pre-diabetic) · >126 (Diabetic) · <70 (Low)',
    categories: [{label:'Normal',range:'70–100',color:'#22C55E'},{label:'Pre-diabetic',range:'100–125',color:'#F59E0B'},{label:'High',range:'>126',color:'#EF4444'},{label:'Low',range:'<70',color:'#3B82F6'}]
  },
  heart_rate: {
    icon:'💓', label:'Heart Rate',
    fields:[{id:'vf1',label:'BPM',ph:'72'}],
    unit:'bpm',
    flag: (v1) => v1>100 ? 'high' : v1<60 ? 'low' : 'normal',
    reference: 'Normal resting: 60–100 bpm · Athletes may have 40–60 bpm · >100 = Tachycardia · <60 = Bradycardia',
    categories: [{label:'Athlete',range:'40–60',color:'#06B6D4'},{label:'Normal',range:'60–100',color:'#22C55E'},{label:'High',range:'>100',color:'#EF4444'}]
  },
  temperature: {
    icon:'🌡️', label:'Temperature',
    fields:[{id:'vf1',label:'°F',ph:'98.6'}],
    unit:'°F',
    flag: (v1) => v1>=100.4 ? 'high' : v1<97 ? 'low' : 'normal',
    reference: 'Normal: 97–99°F (36.1–37.2°C) · Low-grade fever: 99–100.4°F · Fever: >100.4°F · Hypothermia: <97°F',
    categories: [{label:'Low',range:'<97°F',color:'#3B82F6'},{label:'Normal',range:'97–99°F',color:'#22C55E'},{label:'Fever',range:'>100.4°F',color:'#EF4444'}]
  },
  oxygen_sat: {
    icon:'💨', label:'SpO2',
    fields:[{id:'vf1',label:'%',ph:'98'}],
    unit:'%',
    flag: (v1) => v1<95 ? 'low' : v1<98 ? 'normal' : 'normal',
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
    body: JSON.stringify({ type:selectedVitalType, value1:v1, value2:v2||null,
      unit:cfg.unit, notes:document.getElementById('vital-notes')?.value||'' })
  }).then(r => r.json());
  if (r.success) {
    showToast(`${cfg.label} saved`, 'success');
    document.getElementById('vf1').value = '';
    if (document.getElementById('vf2')) document.getElementById('vf2').value = '';
    loadVitals();
  }
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
    const cfg = VITAL_CONFIG[v.type] || {icon:'📊',label:v.type,flag:()=>'normal'};
    const flagStr = v.value2 ? cfg.flag(v.value1,v.value2) : cfg.flag(v.value1);
    const display = v.value2 ? `${v.value1}/${v.value2}` : v.value1;
    return `<div class="vital-row">
      <div class="vital-type-icon">${cfg.icon}</div>
      <div class="vital-info">
        <div class="vital-reading">${display} <span style="font-size:12px;color:var(--gray-400)">${v.unit}</span></div>
        <div class="vital-meta">${v.date_key} ${v.notes ? '· '+escHtml(v.notes) : ''}</div>
      </div>
      <span class="vital-flag ${flagStr}">${flagStr.charAt(0).toUpperCase()+flagStr.slice(1)}</span>
      <button class="todo-act-btn del" onclick="delVital('${v.id}')">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
      </button>
    </div>`;
  }).join('');
}

async function delVital(id) {
  await fetch(`/api/vitals/${id}`, {method:'DELETE'});
  loadVitals();
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
  const date = dateStr || (typeof foodDate !== 'undefined' ? foodDate : new Date().toISOString().split('T')[0]);
  const r = await fetch(`/api/hydration/${date}`).then(r => r.json()).catch(() => null);
  if (!r) return;

  // Update bottle fill
  const fill = document.getElementById('hydration-fill');
  const pctEl = document.getElementById('hydration-pct');
  const lvlEl = document.getElementById('hydration-level-text');
  const badgeEl = document.getElementById('hydration-goal-badge');
  if (fill)   fill.style.height = r.pct + '%';
  if (pctEl)  pctEl.textContent = r.pct + '%';
  if (lvlEl)  lvlEl.textContent = r.total_ml + 'ml';
  if (badgeEl) badgeEl.textContent = `Goal: ${r.goal_ml}ml`;

  // Logs
  const wrap = document.getElementById('hydration-logs-wrap');
  if (wrap) {
    if (!r.logs.length) {
      wrap.innerHTML = '<div style="color:var(--gray-400);font-size:12px;text-align:center;padding:8px 0">No water logged today</div>';
    } else {
      const DTYPE = { water:'💧', coffee:'☕', tea:'🍵', juice:'🥤', milk:'🥛', other:'🫙' };
      wrap.innerHTML = r.logs.map(l => `
        <div class="hydration-log-item">
          <span>${DTYPE[l.drink_type]||'💧'} ${l.drink_type}</span>
          <span style="font-weight:600;font-family:'JetBrains Mono',monospace">${l.amount_ml}ml</span>
          <button class="food-search-clear" onclick="delHydration('${l.id}')" style="width:20px;height:20px">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>`).join('');
    }
  }
  loadWellnessStrip();
}

async function quickAddWater(ml) {
  const date = typeof foodDate !== 'undefined' ? foodDate : new Date().toISOString().split('T')[0];
  await fetch('/api/hydration', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({amount_ml: ml, drink_type:'water', date_key: date})
  });
  loadHydration(date);
  showToast(`💧 +${ml}ml logged`, 'success');
}

async function delHydration(id) {
  await fetch(`/api/hydration/${id}`, {method:'DELETE'});
  const date = typeof foodDate !== 'undefined' ? foodDate : new Date().toISOString().split('T')[0];
  loadHydration(date);
}

// Patch loadFoodTracker to also load hydration
const _origLoadFoodTracker = loadFoodTracker;
loadFoodTracker = async function() {
  await _origLoadFoodTracker.apply(this, arguments);
  loadHydration(foodDate);
};

// Patch loadDashboard to also load wellness strip
const _origLoadDashboard = loadDashboard;
loadDashboard = async function() {
  await _origLoadDashboard.apply(this, arguments);
  loadWellnessStrip();
};

// Patch loadConsistency to also load habits
const _origLoadConsistency = loadConsistency;
loadConsistency = async function() {
  await _origLoadConsistency.apply(this, arguments);
  loadHabits();
};

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
  if (!el) return;
  const todos = (r?.todos || []).slice(0, 5);
  if (todos.length === 0) {
    el.innerHTML = `<div style="color:var(--gray-400);font-size:13px;padding:12px 14px;text-align:center">
      🎉 No pending tasks! <a href="#" onclick="switchView('todos');return false" style="color:var(--teal-600)">Add one →</a>
    </div>`;
    return;
  }
  const today = new Date().toISOString().split('T')[0];
  const PRI = { high:'🔴', medium:'🟡', low:'🟢' };
  el.innerHTML = todos.map(t => {
    const isOverdue = t.due_date && t.due_date < today;
    const dueStr = t.due_date === today ? 'Today' : t.due_date ? t.due_date.slice(5) : '';
    return `<div class="dash-todo-row" onclick="switchView('todos')">
      <div class="dash-todo-check" onclick="event.stopPropagation();dashToggleTodo('${t.id}')"></div>
      <div class="dash-todo-title">${escHtml(t.title)}</div>
      <span class="dash-todo-pri">${PRI[t.priority]||'🟡'}</span>
      ${dueStr ? `<span class="dash-todo-due ${isOverdue?'overdue':''}">${dueStr}</span>` : ''}
    </div>`;
  }).join('');
  if (r.todos.length > 5) {
    el.innerHTML += `<div style="text-align:center;padding:6px 0">
      <a href="#" onclick="switchView('todos');return false" style="font-size:12px;color:var(--teal-600)">+${r.todos.length-5} more tasks →</a>
    </div>`;
  }
}

async function dashToggleTodo(id) {
  await fetch(`/api/todos/${id}/toggle`, {method:'POST'});
  loadDashboardTodos();
  loadTodos();
}

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
// MEDICINE: Adherence history chart (weekly heatmap)
// ════════════════════════════════════════════════════════════
async function loadMedAdherence() {
  const el = document.getElementById('med-adherence-chart');
  if (!el) return;
  const r = await fetch('/api/medicines/adherence').then(r => r.json()).catch(() => null);
  if (!r) return;

  const medicines = r.medicines || [];
  if (!medicines.length) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;text-align:center;padding:16px 0">No medicines tracked yet.</div>';
    return;
  }

  // Build 7-day date labels
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    days.push({ iso: d.toISOString().split('T')[0], label: d.toLocaleDateString('en-US',{weekday:'short'}) });
  }

  el.innerHTML = medicines.slice(0, 8).map(m => {
    const dots = days.map(d => {
      const logged = (m.dose_log || []).some(l => l.date === d.iso && l.taken);
      const expected = (m.dose_log || []).some(l => l.date === d.iso);
      const color = logged ? 'var(--teal-500)' : expected ? 'var(--red-300)' : 'var(--gray-100)';
      return `<div style="width:22px;height:22px;border-radius:50%;background:${color};flex-shrink:0" title="${d.iso}"></div>`;
    }).join('');
    const rate = m.adherence_rate != null ? Math.round(m.adherence_rate) + '%' : '—';
    return `<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--gray-50)">
      <span style="font-size:18px;flex-shrink:0">${m.icon||'💊'}</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:13px;font-weight:600;color:var(--gray-800);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(m.name)}</div>
        <div style="font-size:11px;color:var(--gray-400)">${m.dosage||''} ${m.unit||''}</div>
      </div>
      <div style="display:flex;gap:4px;align-items:center">${dots}</div>
      <div style="font-size:12px;font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--teal-600);width:32px;text-align:right;flex-shrink:0">${rate}</div>
    </div>`;
  }).join('') +
  `<div style="display:flex;gap:4px;align-items:center;margin-top:10px;padding-top:8px;border-top:1px solid var(--gray-100)">
    <span style="font-size:11px;color:var(--gray-400);margin-right:6px">Legend:</span>
    <div style="width:14px;height:14px;border-radius:50%;background:var(--teal-500)"></div><span style="font-size:11px;color:var(--gray-500)">Taken</span>
    <div style="width:14px;height:14px;border-radius:50%;background:var(--red-300);margin-left:8px"></div><span style="font-size:11px;color:var(--gray-500)">Missed</span>
    <div style="width:14px;height:14px;border-radius:50%;background:var(--gray-100);margin-left:8px"></div><span style="font-size:11px;color:var(--gray-500)">No dose</span>
  </div>`;
}

// Patch loadMedicines to also render adherence
const _origLoadMedicines = loadMedicines;
loadMedicines = async function() {
  await _origLoadMedicines.apply(this, arguments);
  loadMedAdherence();
};

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