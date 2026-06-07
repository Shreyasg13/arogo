// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Consistency: calendar, streaks, activity history, habits

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
      ? `onclick="showDayDetail('${dateStr}')"` : '';

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
      <button class="btn-icon act-delete" onclick="deleteActivityHistory('${a.id}')" title="Delete">
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

async function deleteActivityHistory(id) {
  if (!confirm('Delete this activity? This cannot be undone.')) return;
  await fetch(`/api/fitness/activities/${id}`, { method:'DELETE' });
  showToast('Activity deleted');
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
}

// ── Helpers ───────────────────────────────────────────────────────────────

function actTypeColor(type) {
  const c = { running:'#0E8F7E', cycling:'#2563EB', walking:'#D97706', swimming:'#7C3AED', yoga:'#16A34A', gym:'#DC2626', hiking:'#B45309', stretching:'#059669', tennis:'#E53E3E', pickleball:'#E53E3E', basketball:'#EA580C', football:'#16A34A', badminton:'#E53E3E', volleyball:'#EA580C', baseball:'#2563EB', cricket:'#16A34A', golf:'#16A34A', boxing:'#DC2626', martial_arts:'#DC2626', dancing:'#7C3AED', rowing:'#2563EB', climbing:'#B45309', skiing:'#2563EB', snowboarding:'#2563EB', skating:'#2563EB', cycling_indoor:'#2563EB', pilates:'#7C3AED', crossfit:'#DC2626', other:'#9CA3AF' };
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

let foodDate    = new Date().toISOString().split('T')[0];
let foodTargets = {};
let selectedMealType = 'lunch';
let selectedFoodItem = null;
let foodSearchTimer  = null;
let activeFoodCat    = '';

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