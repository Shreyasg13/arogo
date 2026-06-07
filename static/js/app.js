// ── State ──
let selectedTags = [], selectedFile = null, selectedIcon = '💊', selectedColor = 'teal', selectedActivityType = 'running';
let notifPermission = 'default';
let reminderIntervals = [];

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
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
  scheduleReminderChecks();
  scheduleTodoReminderChecks();
  // Init date pickers
  const tdp = document.getElementById('thoughts-date-picker');
  if (tdp) tdp.value = new Date().toISOString().split('T')[0];
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
  const today = new Date().toISOString().split('T')[0];
  ['report-date','med-start-date','activity-date'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = today;
  });
}

// ── Navigation ──
function setupNavigation() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => {
      e.preventDefault();
      switchView(item.dataset.view);
    });
  });
}

function switchView(view) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const viewEl = document.getElementById(`view-${view}`);
  const navEl = document.querySelector(`[data-view="${view}"]`);
  if (viewEl) viewEl.classList.add('active');
  if (navEl) navEl.classList.add('active');
  if (view === 'dashboard')   loadDashboard();
  if (view === 'reports')     loadReports();
  if (view === 'medicines')   loadMedicines();
  if (view === 'fitness')     { loadFitness(); loadConnectedServices(); }
  if (view === 'consistency') loadConsistency();
  if (view === 'food')      loadFoodTracker();
  if (view === 'thoughts')  loadThoughts();
  if (view === 'todos')         loadTodos();
  if (view === 'progress')      loadProgress();
  if (view === 'report')        loadReport();
  if (view === 'notifications') loadNotifications();
  if (view === 'export')        initExportView();
  if (view === 'habits')        loadHabits();
}

// ── Dashboard ──
async function loadDashboard() {
  const today = new Date().toISOString().split('T')[0];
  const [doses, fitnessStats, reportStats, foodDay, profile] = await Promise.all([
    fetch('/api/medicines/today').then(r => r.json()).catch(() => []),
    fetch('/api/fitness/stats').then(r => r.json()).catch(() => ({})),
    fetch('/api/stats').then(r => r.json()).catch(() => ({})),
    fetch(`/api/food/log/${today}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/profile').then(r => r.json()).catch(() => null)
  ]);

  // Hero cards — show medicines card only if user has medicines
  const remaining = doses.filter(d => !d.taken).length;
  const dosesCard   = document.getElementById('dash-doses-card');
  const reportsCard = document.getElementById('dash-reports-card');
  if (doses.length > 0 && dosesCard) {
    dosesCard.style.display = '';
    setText('dash-doses-today', doses.length);
    setText('dash-doses-sub', `${remaining} remaining today`);
  }
  setText('dash-active-min', fitnessStats.week?.duration || 0);
  // Show reports card only if user has at least one report
  const totalReports = reportStats.total || 0;
  if (totalReports > 0 && reportsCard) {
    reportsCard.style.display = '';
    setText('dash-reports', totalReports);
  }

  // Calorie balance hero card
  const todayCalBurned  = fitnessStats.week?.calories || 0;  // weekly, approximate
  const todayCalEaten   = foodDay?.summary?.totals?.calories || 0;
  const targetCal       = profile?.targets?.target_calories || 2000;
  const netBalance      = Math.round(targetCal - todayCalEaten); // deficit = target - eaten
  const deficitCard     = document.getElementById('dash-caldeficit-card');
  const deficitEl       = document.getElementById('dash-cal-deficit');
  const deficitSubEl    = document.getElementById('dash-cal-deficit-sub');
  if (deficitEl) deficitEl.textContent = (netBalance >= 0 ? '' : '+') + Math.abs(netBalance);
  if (deficitSubEl) deficitSubEl.textContent = netBalance >= 0 ? 'kcal remaining' : 'kcal over goal';
  if (deficitCard) {
    deficitCard.classList.remove('hero-card--amber','hero-card--green','hero-card--red');
    deficitCard.classList.add(netBalance >= 0 ? 'hero-card--amber' : 'hero-card--red');
  }

  // Dashboard nutrition bar
  if (foodDay && foodDay.summary?.log_count > 0) {
    const t = foodDay.summary.totals;
    const nb = document.getElementById('dash-nutrition-bar');
    if (nb) nb.style.display = 'flex';
    setText('dnb-cal',   Math.round(t.calories));
    setText('dnb-prot',  Math.round(t.protein) + 'g');
    setText('dnb-carb',  Math.round(t.carbs) + 'g');
    setText('dnb-fat',   Math.round(t.fat) + 'g');
    setText('dnb-fiber', Math.round(t.fiber) + 'g');
  }

  // Medicine list
  const medList = document.getElementById('dash-medicine-list');
  if (medList) {
    if (doses.length === 0) {
      medList.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:16px 0;text-align:center">No medicines scheduled today.<br><a href="#" onclick="switchView(\'medicines\');return false" style="color:var(--teal-600)">Add medicine →</a></div>';
    } else {
      medList.innerHTML = doses.slice(0,5).map(d => `
        <div class="dash-dose-item ${d.taken ? 'taken' : ''}" onclick="markDoseTaken('${d.med_id}','${d.time}',this)">
          <div class="dash-dose-icon">${d.icon}</div>
          <div class="dash-dose-info">
            <div class="dash-dose-name">${escHtml(d.med_name)}</div>
            <div class="dash-dose-detail">${d.dosage} ${d.unit}${d.with_food ? ' · with food' : ''}</div>
          </div>
          <div class="dash-dose-time">${d.time}</div>
          <div class="dash-dose-check ${d.taken ? 'done' : ''}">${d.taken ? '✓' : ''}</div>
        </div>
      `).join('');
    }
  }

  // Suggestions
  const sugs = document.getElementById('dash-suggestions');
  if (sugs) renderSuggestions(sugs, fitnessStats.suggestions || []);

  // Weekly chart
  renderWeeklyChart(fitnessStats.weekly_days || {});

  // Nav badge
  const badge = document.getElementById('nav-dose-badge');
  if (badge) {
    if (remaining > 0) { badge.textContent = remaining; badge.style.display = 'inline-block'; }
    else badge.style.display = 'none';
  }

  // Consistency streak badge in dashboard header
  fetch('/api/fitness/consistency').then(r => r.json()).then(con => {
    const sb = document.getElementById('dash-streak-badge');
    if (sb) {
      const streak = con.current_streak || 0;
      if (streak > 0) { sb.textContent = `🔥${streak}`; sb.style.display = 'inline-block'; }
      else sb.style.display = 'none';
    }
  }).catch(() => {});
}

async function openCalorieBreakdown() {
  const today = new Date().toISOString().split('T')[0];
  const [foodDay, profile] = await Promise.all([
    fetch(`/api/food/log/${today}`).then(r => r.json()).catch(() => null),
    fetch('/api/food/profile').then(r => r.json()).catch(() => null)
  ]);

  const targets  = profile?.targets || {};
  const totals   = foodDay?.summary?.totals || {};
  const logCount = foodDay?.summary?.log_count || 0;

  const targetCal = targets.target_calories || 2000;
  const eaten     = Math.round(totals.calories || 0);
  const net       = Math.round(targetCal - eaten);      // positive = still has room
  const pct       = Math.min(Math.round((eaten / targetCal) * 100), 150);

  // Date label
  const d = new Date(today + 'T12:00:00');
  setText('cbd-date-label', d.toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' }));

  // Equation values
  setText('cbd-target-val', targetCal + ' kcal');
  setText('cbd-eaten-val',  eaten + ' kcal');
  setText('cbd-result-val', Math.abs(net) + ' kcal');

  const resultBlock = document.getElementById('cbd-result-block');
  const resultLabel = document.getElementById('cbd-result-label');
  const resultIcon  = document.getElementById('cbd-result-icon');
  if (resultBlock) {
    resultBlock.className = 'cbd-eq-block cbd-eq-block--result ' +
      (net < -100 ? 'surplus' : net > 100 ? 'deficit' : 'balanced');
  }
  if (resultLabel) resultLabel.textContent = net < -100 ? 'Over goal' : net > 100 ? 'Remaining' : 'Balanced!';
  if (resultIcon)  resultIcon.textContent  = net < -100 ? '⚠️' : net > 100 ? '✅' : '⚖️';

  // Progress bar
  const fill = document.getElementById('cbd-progress-fill');
  if (fill) {
    fill.style.width = Math.min(pct, 100) + '%';
    fill.classList.toggle('over', pct > 105);
  }
  setText('cbd-progress-pct-label', `${pct}% of daily goal`);
  setText('cbd-target-label', targetCal + ' kcal');

  // Macro bars
  const macros = [
    { id:'prot', val: Math.round(totals.protein||0), target: targets.protein_g||56, unit:'g' },
    { id:'carb', val: Math.round(totals.carbs||0),   target: targets.carbs_g||250,  unit:'g' },
    { id:'fat',  val: Math.round(totals.fat||0),     target: targets.fat_g||65,     unit:'g' },
    { id:'fiber',val: Math.round(totals.fiber||0),   target: targets.fiber_g||30,   unit:'g' },
  ];
  macros.forEach(m => {
    const bar = document.getElementById(`cbd-bar-${m.id}`);
    const val = document.getElementById(`cbd-${m.id}-val`);
    if (bar) bar.style.width = Math.min((m.val/m.target)*100, 100).toFixed(0) + '%';
    if (val) val.textContent = `${m.val}${m.unit} / ${m.target}${m.unit}`;
  });

  // Formula explanation
  const formulaEl = document.getElementById('cbd-formula-rows');
  if (formulaEl) {
    const p = profile?.profile || {};
    const goalLabels = { lose_fast:'Lose fast (−500)', lose:'Lose weight (−250)',
      maintain:'Maintain (±0)', gain:'Gain muscle (+250)', gain_fast:'Bulk (+500)' };
    formulaEl.innerHTML = `
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">BMR (${p.gender||'male'}, ${p.age||25} yrs, ${p.weight_kg||70}kg, ${p.height_cm||170}cm)</span>
        <span class="cbd-formula-val">${targets.bmr||'—'} kcal</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">× Activity multiplier (${(p.activity_level||'moderate').replace('_',' ')})</span>
        <span class="cbd-formula-val">${targets.tdee||'—'} kcal (TDEE)</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">Goal adjustment</span>
        <span class="cbd-formula-val">${goalLabels[p.goal||'maintain']}</span>
      </div>
      <div class="cbd-formula-row">
        <span class="cbd-formula-key">Daily calorie target</span>
        <span class="cbd-formula-val highlight">${targetCal} kcal</span>
      </div>
    `;
  }

  // CTA text
  const ctaEl = document.getElementById('cbd-cta-text');
  if (ctaEl) {
    if (logCount === 0) {
      ctaEl.textContent = "You haven't logged any food today. Add your meals to see the full picture.";
    } else if (net > 300) {
      ctaEl.textContent = `You still have ${net} kcal left. Log your next meal to stay on track.`;
    } else if (net < -100) {
      ctaEl.textContent = `You're ${Math.abs(net)} kcal over your goal. Consider a lighter dinner.`;
    } else {
      ctaEl.textContent = "Great balance today! Keep logging to maintain accuracy.";
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
    const isToday = date === new Date().toISOString().split('T')[0];
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
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">No reports found</div><div class="empty-sub">Upload your first medical report</div><button class="btn-primary" onclick="openUploadModal()">Upload Report</button></div>`;
    return;
  }
  grid.innerHTML = reports.map(r => `
    <div class="report-card" onclick="openReportDetail(${JSON.stringify(r).replace(/"/g,'&quot;')})">
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
          <button class="btn-icon" title="Download" onclick="event.stopPropagation();downloadFile('/uploads/${r.filename}',r.original_name)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </button>
          <button class="btn-icon" title="Delete" onclick="event.stopPropagation();deleteReport('${r.id}')">
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
    <div class="form-actions" style="margin-top:16px;padding-top:16px">
      <button class="btn-primary" onclick="downloadFile('/uploads/${r.filename}','${r.original_name}')">Download</button>
      <button class="btn-danger" onclick="deleteReport('${r.id}');closeModal('report-detail-overlay')">Delete</button>
    </div>
  `;
  document.getElementById('report-detail-overlay').style.display = 'flex';
}

async function deleteReport(id) {
  if (!confirm('Delete this report?')) return;
  await fetch(`/api/reports/${id}`, { method:'DELETE' });
  showToast('Report deleted', 'success');
  loadReports();
  loadDashboard();
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
    <span class="selected-tag">${escHtml(tag)}<span class="selected-tag-remove" onclick="removeTag('${escHtml(tag)}')">×</span></span>
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
  const mc = document.getElementById('med-count');
  if (mc) mc.textContent = `${meds.filter(m=>m.active).length} active`;
}

function renderTodayTimeline(doses) {
  const el = document.getElementById('today-dose-timeline');
  if (!el) return;
  const total = doses.length, taken = doses.filter(d => d.taken).length;
  const fill = document.getElementById('med-progress-fill');
  const label = document.getElementById('med-progress-label');
  if (fill) fill.style.width = total ? `${(taken/total*100).toFixed(0)}%` : '0%';
  if (label) label.textContent = `${taken} of ${total} taken`;
  if (doses.length === 0) {
    el.innerHTML = '<div style="color:var(--gray-400);font-size:13px;padding:16px 0;text-align:center">No doses scheduled. <a href="#" onclick="openMedModal();return false" style="color:var(--teal-600)">Add a medicine →</a></div>';
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
            <div class="dose-card ${d.taken ? 'taken' : ''}" onclick="markDoseTaken('${d.med_id}','${d.time}',this)">
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
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">💊</div><div class="empty-text">No medicines added</div><div class="empty-sub">Add your first medicine to track doses</div><button class="btn-primary" onclick="openMedModal()">Add Medicine</button></div>`;
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
          <button class="med-restock-btn" onclick="openRestockModal('${m.id}','${escHtml(m.name)}',${m.pill_count},${m.pills_per_dose||1},${m.refill_threshold||7})">Restock</button>
        </div>
        <div class="med-pill-bar-track">
          <div class="med-pill-bar-fill" style="width:${fillPct}%;background:${stockColor}"></div>
        </div>
      </div>` : `
      <div class="med-pill-track med-pill-track--empty">
        <button class="med-add-stock-btn" onclick="openRestockModal('${m.id}','${escHtml(m.name)}',0,1,7)">+ Track pill count</button>
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
          <button class="btn-icon" title="${m.active ? 'Pause' : 'Activate'}" onclick="toggleMed('${m.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">${m.active ? '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>' : '<polygon points="5 3 19 12 5 21 5 3"/>'}</svg>
          </button>
          <button class="btn-icon" title="Delete" onclick="deleteMed('${m.id}')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function markDoseTaken(medId, time, el) {
  const date = new Date().toISOString().split('T')[0];
  await fetch(`/api/medicines/${medId}/log`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ date, time, taken:true }) });
  showToast('Dose marked as taken ✓', 'success');
  loadMedicines();
  loadDashboard();
}

async function toggleMed(id) {
  await fetch(`/api/medicines/${id}/toggle`, { method:'POST' });
  loadMedicines();
}

async function deleteMed(id) {
  if (!confirm('Remove this medicine?')) return;
  await fetch(`/api/medicines/${id}`, { method:'DELETE' });
  showToast('Medicine removed', 'success');
  loadMedicines();
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
      scheduleReminderChecks();
    } else showToast('Failed to add medicine', 'error');
  });
}

function addTimeSlot() {
  const slots = document.getElementById('time-slots');
  const row = document.createElement('div');
  row.className = 'time-slot-row';
  row.innerHTML = `<input type="time" class="form-input time-input" value="12:00"><button type="button" class="btn-icon slot-remove" onclick="removeTimeSlot(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>`;
  slots.appendChild(row);
}

function removeTimeSlot(btn) {
  const slots = document.getElementById('time-slots');
  if (slots.children.length > 1) btn.closest('.time-slot-row').remove();
}

function resetTimeSlots() {
  const slots = document.getElementById('time-slots');
  if (slots) slots.innerHTML = `<div class="time-slot-row"><input type="time" class="form-input time-input" value="08:00"><button type="button" class="btn-icon slot-remove" onclick="removeTimeSlot(this)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>`;
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
    if (perm === 'granted') { showToast('Notifications enabled! 🔔', 'success'); scheduleReminderChecks(); }
  });
}

function scheduleReminderChecks() {
  reminderIntervals.forEach(clearInterval);
  reminderIntervals = [];
  if (notifPermission !== 'granted') return;
  registerNotifServiceWorker();
  const interval = setInterval(async () => {
    const doses = await fetch('/api/medicines/today').then(r => r.json()).catch(() => []);
    const now = new Date().toTimeString().slice(0,5);
    doses.forEach(d => { if (d.time === now && !d.taken) fireReminderNotification(d); });
  }, 60000);
  reminderIntervals.push(interval);
  setTimeout(async () => {
    const doses = await fetch('/api/medicines/today').then(r => r.json()).catch(() => []);
    const now = new Date().toTimeString().slice(0,5);
    doses.forEach(d => { if (d.time === now && !d.taken) fireReminderNotification(d); });
  }, 2000);
}

function fireReminderNotification(dose) {
  if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
    navigator.serviceWorker.ready.then(reg => {
      reg.showNotification('💊 Medicine Reminder', {
        body: `Time to take ${dose.med_name} — ${dose.dosage} ${dose.unit}${dose.with_food ? ' (with food)' : ''}`,
        tag: `dose-${dose.med_id}-${dose.time}`,
        requireInteraction: true,
        data: { med_id: dose.med_id, time: dose.time, med_name: dose.med_name },
        actions: [
          { action: 'taken', title: '✓ Mark as Taken' },
          { action: 'snooze', title: '⏰ Snooze 10 min' }
        ]
      });
    });
  } else {
    const n = new Notification('💊 Medicine Reminder', {
      body: `Time to take ${dose.med_name} — ${dose.dosage} ${dose.unit}${dose.with_food ? ' (with food)' : ''}`,
      tag: `dose-${dose.med_id}-${dose.time}`,
      requireInteraction: true
    });
    n.onclick = () => { window.focus(); markDoseTaken(dose.med_id, dose.time, null); n.close(); };
  }
}

function registerNotifServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  const swCode = `
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const { med_id, time, med_name } = e.notification.data || {};
  if (e.action === 'taken') {
    e.waitUntil(
      fetch('/api/medicines/' + med_id + '/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: new Date().toISOString().split('T')[0], time, taken: true })
      }).then(() =>
        self.registration.showNotification('Dose Logged', {
          body: med_name + ' marked as taken',
          tag: 'dose-confirm',
          requireInteraction: false
        })
      )
    );
    e.waitUntil(clients.matchAll({ type: 'window' }).then(list => {
      if (list.length) return list[0].focus();
      return clients.openWindow('/');
    }));
  } else if (e.action === 'snooze') {
    e.waitUntil(new Promise(resolve => {
      setTimeout(() => {
        self.registration.showNotification('Medicine Reminder (Snoozed)', {
          body: 'Still need to take ' + med_name,
          tag: 'dose-' + med_id + '-snooze',
          requireInteraction: true,
          data: { med_id, time, med_name },
          actions: [
            { action: 'taken', title: 'Mark as Taken' },
            { action: 'snooze', title: 'Snooze 10 min' }
          ]
        });
        resolve();
      }, 600000);
    }));
  } else {
    e.waitUntil(clients.matchAll({ type: 'window' }).then(list => {
      if (list.length) return list[0].focus();
      return clients.openWindow('/');
    }));
  }
});
`;
  const blob = new Blob([swCode], { type: 'application/javascript' });
  const swUrl = URL.createObjectURL(blob);
  navigator.serviceWorker.register(swUrl, { scope: '/' })
    .then(() => console.log('[SW] Registered'))
    .catch(err => console.warn('[SW] Failed:', err));
}

// ── Fitness ──
function openActivityModal() {
  document.getElementById('activity-modal-overlay').style.display = 'flex';
  // Render fields for currently selected type (default: running)
  setTimeout(() => renderActivityFields(selectedActivityType || 'running'), 0);
}
function openConnectModal() { document.getElementById('connect-modal-overlay').style.display = 'flex'; }

async function loadFitness() {
  const today = new Date().toISOString().split('T')[0];
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
  const targetCal    = profile?.targets?.target_calories || 2000;
  // Net = TDEE target - (eaten - burned): how many kcal you still have left today
  // A positive number means you still have room; negative means surplus over goal
  const net          = Math.round((targetCal + burnedCal) - eatenCal);  // surplus capacity
  const pct          = targetCal > 0 ? Math.min(Math.round((eatenCal / (targetCal + burnedCal)) * 100), 150) : 0;

  setText('cdb-burned', burnedCal.toLocaleString() + ' kcal');
  setText('cdb-eaten',  Math.round(eatenCal) + ' kcal');
  setText('cdb-target', targetCal + ' kcal/day');
  setText('cdb-progress-pct', pct + '%');

  const netEl    = document.getElementById('cdb-net');
  const netLbl   = document.getElementById('cdb-net-label');
  const progress = document.getElementById('cdb-progress');
  const banner   = document.getElementById('calorie-deficit-banner');

  if (netEl) {
    // net > 0 = room left to eat; net < 0 = exceeded budget
    netEl.textContent = (net >= 0 ? '' : '') + Math.abs(net) + ' kcal';
  }
  if (netLbl) netLbl.textContent = net > 100 ? '✅ Remaining' : net < -100 ? '⚠️ Over budget' : '⚖️ Balanced';
  if (progress) {
    progress.style.width = Math.min(pct, 100) + '%';
    progress.classList.toggle('over', pct > 105);
  }
  if (banner) {
    banner.classList.remove('cdb-deficit','cdb-surplus','cdb-balanced');
    banner.classList.add(net > 100 ? 'cdb-deficit' : net < -100 ? 'cdb-surplus' : 'cdb-balanced');
  }

  // ── Nutrition strip ──
  renderFitnessNutritionStrip(foodDay, profile?.targets);
}

function renderFitnessNutritionStrip(foodDay, targets) {
  if (!targets) return;
  const t    = foodDay?.summary?.totals || {};
  const defs = [
    { id:'cal',  val: Math.round(t.calories||0), target: targets.target_calories||2000, unit:'kcal', label:'Calories', color:'#0E8F7E' },
    { id:'prot', val: Math.round(t.protein||0),  target: targets.protein_g||56,         unit:'g',    label:'Protein',  color:'#2563EB' },
    { id:'carb', val: Math.round(t.carbs||0),    target: targets.carbs_g||250,          unit:'g',    label:'Carbs',    color:'#D97706' },
    { id:'fat',  val: Math.round(t.fat||0),      target: targets.fat_g||65,             unit:'g',    label:'Fat',      color:'#7C3AED' },
    { id:'fiber',val: Math.round(t.fiber||0),    target: targets.fiber_g||30,           unit:'g',    label:'Fiber',    color:'#16A34A' },
  ];
  const R = 18, C = 2 * Math.PI * R; // circumference ~113

  defs.forEach(d => {
    const pct    = Math.min(d.val / d.target, 1);
    const offset = C - pct * C;
    const ring   = document.getElementById(`fns-ring-${d.id}`);
    const valEl  = document.getElementById(`fns-${d.id}-val`);
    const subEl  = document.getElementById(`fns-${d.id}-sub`);
    if (ring)  ring.style.strokeDashoffset = offset.toFixed(1);
    if (valEl) valEl.textContent = d.id === 'cal' ? d.val : d.val + d.unit;
    if (subEl) subEl.textContent = `/ ${d.target}${d.id !== 'cal' ? d.unit : ''}`;
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
  const colors = { running:'#0E8F7E', cycling:'#2563EB', walking:'#D97706', swimming:'#7C3AED', yoga:'#16A34A', gym:'#DC2626', hiking:'#B45309', stretching:'#059669', tennis:'#E53E3E', pickleball:'#E53E3E', basketball:'#EA580C', football:'#16A34A', badminton:'#E53E3E', volleyball:'#EA580C', baseball:'#2563EB', cricket:'#16A34A', golf:'#16A34A', boxing:'#DC2626', martial_arts:'#DC2626', dancing:'#7C3AED', rowing:'#2563EB', climbing:'#B45309', skiing:'#2563EB', snowboarding:'#2563EB', skating:'#2563EB', cycling_indoor:'#2563EB', pilates:'#7C3AED', crossfit:'#DC2626', other:'#9CA3AF' };
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
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🏅</div><div class="empty-text">No activities yet</div><div class="empty-sub">Log a workout or connect a fitness app</div><button class="btn-primary" onclick="openActivityModal()">Log Activity</button></div>`;
    return;
  }
  const actColors = { running:'#E4F5F2', cycling:'#EFF6FF', walking:'#FFFBEB', swimming:'#F5F3FF', yoga:'#F0FDF4', gym:'#FFF0EF', hiking:'#FEF3C7', stretching:'#ECFDF5', tennis:'#FFF0F0', pickleball:'#FFF0F0', basketball:'#FFF3E0', football:'#F0FDF4', badminton:'#FFF0F0', volleyball:'#FFF3E0', baseball:'#F0F4FF', cricket:'#F0FDF4', golf:'#F0FDF4', boxing:'#FFF0EF', martial_arts:'#FFF0EF', dancing:'#FDF0FF', rowing:'#EFF6FF', climbing:'#FEF3C7', skiing:'#EFF6FF', snowboarding:'#EFF6FF', skating:'#EFF6FF', cycling_indoor:'#EFF6FF', pilates:'#F5F3FF', crossfit:'#FFF0EF', other:'#F3F4F6' };
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
      <button class="btn-icon act-delete" onclick="deleteActivity('${a.id}')">
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
  { id:'cardio',      label:'🫀 Cardio',      color:'#0E8F7E' },
  { id:'hiit',        label:'⚡ HIIT',         color:'#EA580C' },
  { id:'upper_body',  label:'💪 Upper Body',   color:'#2563EB' },
  { id:'lower_body',  label:'🦵 Lower Body',   color:'#7C3AED' },
  { id:'full_body',   label:'🏋️ Full Body',   color:'#DC2626' },
  { id:'core',        label:'🔥 Core',         color:'#D97706' },
  { id:'flexibility', label:'🧘 Flexibility',  color:'#16A34A' },
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
      onclick="toggleGymSub('${s.id}')"
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
                 oninput="gymSets['${subId}'][${i}].exercise=this.value"
                 value="${escHtml(s.exercise)}"></td>
      <td><input type="number" class="form-input" style="font-size:12px;padding:5px 8px;width:54px"
                 placeholder="3"
                 oninput="gymSets['${subId}'][${i}].sets=this.value"
                 value="${s.sets}"></td>
      <td><input type="number" class="form-input" style="font-size:12px;padding:5px 8px;width:54px"
                 placeholder="10"
                 oninput="gymSets['${subId}'][${i}].reps=this.value"
                 value="${s.reps}"></td>
      <td><input type="number" class="form-input" style="font-size:12px;padding:5px 8px;width:68px"
                 placeholder="—" step="0.5"
                 oninput="gymSets['${subId}'][${i}].weight=this.value"
                 value="${s.weight}"></td>
      <td><button type="button" class="btn-icon"
          onclick="removeGymSet('${subId}',${i})"
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
    <button type="button" class="sets-add-btn" onclick="addGymSet('${subId}')">+ Add exercise</button>
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

async function deleteActivity(id) {
  if (!confirm('Delete this activity?')) return;
  await fetch(`/api/fitness/activities/${id}`, { method:'DELETE' });
  showToast('Activity deleted');
  loadFitness();
  loadDashboard();
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
          <button class="btn-outline-sm" onclick="triggerSync('${t.service}')">Sync now</button>
          <button class="btn-icon" onclick="disconnectService('${t.service}')" title="Disconnect" style="color:var(--red-400)">
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

async function disconnectService(service) {
  if (!confirm(`Disconnect ${SERVICE_LABELS[service] || service}? Imported activities will remain.`)) return;
  await fetch('/api/fitness/disconnect', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ service })
  });
  showToast(`${SERVICE_LABELS[service]} disconnected`);
  loadConnectedServices();
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
const ACT_COLORS = { running:'#E4F5F2', cycling:'#EFF6FF', walking:'#FFFBEB', swimming:'#F5F3FF', yoga:'#F0FDF4', gym:'#FFF0EF', hiking:'#FEF3C7', stretching:'#ECFDF5', tennis:'#FFF0F0', pickleball:'#FFF0F0', basketball:'#FFF3E0', football:'#F0FDF4', badminton:'#FFF0F0', volleyball:'#FFF3E0', baseball:'#F0F4FF', cricket:'#F0FDF4', golf:'#F0FDF4', boxing:'#FFF0EF', martial_arts:'#FFF0EF', dancing:'#FDF0FF', rowing:'#EFF6FF', climbing:'#FEF3C7', skiing:'#EFF6FF', snowboarding:'#EFF6FF', skating:'#EFF6FF', cycling_indoor:'#EFF6FF', pilates:'#F5F3FF', crossfit:'#FFF0EF', other:'#F3F4F6' };

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
    const today = new Date().toISOString().split('T')[0];
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
}

// ── Macro rings ──────────────────────────────────────────────────────────────
function updateRings(totals, targets) {
  const rings = [
    { key:'calories', id:'cal',   target: targets.target_calories || 2000, unit:'kcal', fmt: v => Math.round(v) },
    { key:'protein',  id:'prot',  target: targets.protein_g || 56,         unit:'g',    fmt: v => Math.round(v) },
    { key:'carbs',    id:'carbs', target: targets.carbs_g || 250,           unit:'g',    fmt: v => Math.round(v) },
    { key:'fat',      id:'fat',   target: targets.fat_g || 65,              unit:'g',    fmt: v => Math.round(v) },
    { key:'fiber',    id:'fiber', target: targets.fiber_g || 30,            unit:'g',    fmt: v => Math.round(v) },
  ];

  const C = 201; // stroke-dasharray = 2 * π * r(32) ≈ 201

  rings.forEach(r => {
    const val  = totals[r.key] || 0;
    const pct  = Math.min(val / r.target, 1);
    const offset = C - pct * C;
    const ring = document.getElementById(`ring-${r.id}`);
    if (ring) ring.style.strokeDashoffset = offset.toFixed(1);
    setText(`ring-${r.id}-val`,    r.fmt(val));
    setText(`ring-${r.id}-target`, `/ ${r.fmt(r.target)}${r.unit !== 'kcal' ? r.unit : ''}`);
  });
}

// ── Meal sections ─────────────────────────────────────────────────────────────
function renderMealSections(byMeal) {
  const el = document.getElementById('meal-sections');
  if (!el) return;

  // Always render all 4 meal sections in fixed order,
  // whether or not anything has been logged for the day.
  el.innerHTML = MEAL_ORDER.map(mtype => {
    const meal = byMeal[mtype] || { calories:0, protein:0, carbs:0, fat:0, items:[] };
    const meta = MEAL_TYPES.find(m => m.id === mtype);

    const itemsHtml = meal.items.map(item => `
      <div class="food-log-row">
        <div class="food-log-emoji">${getFoodEmoji(item.food_id)}</div>
        <div style="flex:1;min-width:0">
          <div class="food-log-name">${escHtml(item.food_name)}</div>
          <div class="food-log-qty">${item.quantity_g}g</div>
        </div>
        <div class="food-log-macros">
          <span class="food-macro-chip fmc-cal">${Math.round(item.calories)} kcal</span>
          <span class="food-macro-chip fmc-prot">${Math.round(item.protein)}g P</span>
          <span class="food-macro-chip fmc-carb">${Math.round(item.carbs)}g C</span>
          <span class="food-macro-chip fmc-fat">${Math.round(item.fat)}g F</span>
        </div>
        <button class="btn-icon" onclick="removeFoodLog('${item.id}')" title="Remove"
                style="color:var(--gray-300);flex-shrink:0">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
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
      <button class="meal-add-btn" onclick="openAddFoodModal('${mtype}')">
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
  const tCal  = targets.target_calories || 2000;
  const maxCal = Math.max(...weekData.map(d => d.calories), tCal, 1);
  const days   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  el.innerHTML = weekData.map((d, i) => {
    const pct  = (d.calories / maxCal * 80).toFixed(0);
    const over = d.calories > tCal * 1.1;
    const low  = d.calories < tCal * 0.4;
    const cls  = over ? 'fw-bar--over' : low ? 'fw-bar--low' : 'fw-bar--ok';
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
  const today = new Date();
  if (d > today) return;
  foodDate = d.toISOString().split('T')[0];
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
  'Indian Beverages':'☕','Indian Sides':'🫙','Indian Sweets':'🍬','South Indian':'🥞',
  'Pakistani':'🥘','Bangladeshi':'🐟','Sri Lankan':'🫓','Nepali':'🥟','Afghan':'🫙',
  'South Asian Sweets':'🍮','Street Food':'🌆',
  'Italian':'🍝','Mediterranean':'🫙','Thai':'🌶️','Japanese':'🍣',
  'Global Mains':'🌍','Global Breakfast':'🌅','Global Snacks':'🍿',
  'Fruits':'🍎','Vegetables':'🥦','Protein':'🥩','Dairy':'🥛',
  'Nuts & Seeds':'🌰','Dry Fruits':'🍇','Trail Mix':'🥜','Chocolates':'🍫',
  'Packaged Snacks':'📦','Supplements':'💪','Beverages':'🥤',
  'Breakfast':'🌅','Salads':'🥗','Rice & Grains':'🍚',
  'Dips & Spreads':'🫙','Fats & Oils':'🫒',
};

const CAT_GROUPS = {
  '🇺🇸 American':    ['American','American Fast Food','American Breakfast','American Desserts'],
  '🇮🇳 Indian':      ['Indian Main','Indian Bread','Indian Snacks','Indian Street Food','Indian Beverages','Indian Sides','Indian Sweets','South Indian'],
  '🌏 South Asian':  ['Pakistani','Bangladeshi','Sri Lankan','Nepali','Afghan','South Asian Sweets','Street Food'],
  '🌍 World Cuisine':['Italian','Mediterranean','Thai','Japanese','Global Mains','Global Breakfast','Global Snacks'],
  '🥗 Healthy':      ['Protein','Dairy','Fruits','Vegetables','Salads','Rice & Grains','Breakfast','Beverages'],
  '🍿 Snacks':       ['Nuts & Seeds','Dry Fruits','Trail Mix','Chocolates','Packaged Snacks','Dips & Spreads'],
  '💪 Fitness':      ['Supplements','Fats & Oils'],
};

const FOOD_QTY_MODE = {
  "roti": "count",
  "paratha": "count",
  "puri": "count",
  "idli": "count",
  "dosa": "count",
  "samosa": "count",
  "vada_pav": "count",
  "egg_boiled": "count",
  "banana": "count",
  "mango": "count",
  "apple": "count",
  "papaya": "count",
  "guava": "count",
  "pomegranate": "count",
  "brown_bread": "count",
  "green_tea": "cup",
  "coconut_water": "cup",
  "masala_chai": "cup",
  "black_chai": "cup",
  "ginger_chai": "cup",
  "turmeric_milk": "cup",
  "rose_sharbat": "cup",
  "nimbu_pani": "cup",
  "aam_panna": "cup",
  "jaljeera": "cup",
  "badam_milk": "cup",
  "mango_lassi": "cup",
  "pani_puri": "count",
  "aloo_paratha": "count",
  "methi_paratha": "count",
  "tandoori_roti": "count",
  "uttapam": "count",
  "banana_smoothie": "cup",
  "omelette": "count",
  "hummus": "count",
  "coffee_black": "cup",
  "coffee_latte": "cup",
  "orange_juice": "cup",
  "apple_pie": "count",
  "hummus_pita": "count",
  "pita_bread": "count",
  "egg_hopper": "count",
  "kottu_roti": "count",
  "bolani": "count",
  "golgappa_pani_puri": "count",
  "kati_roll": "count",
  "bhel_puri": "count",
  "dark_choc_70": "count",
  "milk_chocolate_bar": "count",
  "kitkat": "count",
  "snickers": "count",
  "ferrero_rocher": "count",
  "bounty": "count",
  "twix": "count",
  "dairy_milk": "count",
  "white_chocolate": "count",
  "m_and_m": "count",
  "lindt_excellence": "count",
  "kinder_bueno": "count",
  "raisins": "count",
  "medjool_dates": "count",
  "dried_apricots": "count",
  "dried_figs": "count",
  "prunes": "count",
  "dried_cranberries": "count",
  "dried_mango": "count",
  "dried_blueberries": "count",
  "dried_cherries": "count",
  "dried_pineapple": "count",
  "dried_goji": "count",
  "makhana": "count",
  "trail_mix_tropical": "count",
  "strawberries": "count",
  "watermelon": "count",
  "grapes": "count",
  "kiwi": "count",
  "pear": "count",
  "peach": "count",
  "pineapple": "count",
  "lychee": "count",
  "blueberries": "count",
  "orange": "count",
  "cherry": "count",
  "oreo": "count",
  "digestive_biscuit": "count",
  "starbucks_latte_grande": "cup",
  "starbucks_frappuccino": "cup",
  "egg_salad_sandwich": "count",
  "eggs_benedict": "count",
  "breakfast_burrito": "count",
  "avocado_toast_egg": "count",
  "chocolate_chip_cookie": "count",
  "banana_pudding": "count",
  "peach_cobbler": "count",
  "cold_brew_black": "cup",
  "iced_coffee_creamer": "cup",
  "chocolate_milk": "cup",
  "green_smoothie": "cup",
  "berry_smoothie": "cup",
  "apple_cider": "cup",
  "kombucha": "cup",
  "protein_smoothie": "cup",
  "cornbread": "count",
  "deviled_eggs": "count",
  "hard_boiled_egg_2": "count",
  "bread_sourdough": "count",
  "whole_milk": "cup",
  "skimmed_milk": "cup",
  "semi_milk": "cup",
  "oat_milk": "cup",
  "almond_milk": "cup",
  "soy_milk": "cup",
  "coconut_milk_drk": "cup",
  "buffalo_milk": "cup",
  "goat_milk": "cup",
  "whey_concentrate": "scoop",
  "whey_isolate": "scoop",
  "whey_hydrolysate": "scoop",
  "casein_protein": "scoop",
  "plant_protein": "scoop",
  "mass_gainer": "scoop",
  "creatine": "scoop",
  "bcaa_powder": "scoop",
  "protein_bar": "scoop",
  "collagen_peptides": "scoop",
  "ashwagandha": "scoop",
  "sattu_drink": "scoop"
};

async function loadFoodCategories() {
  const r = await fetch('/api/food/db').then(res => res.json()).catch(err => {
    console.error('[Food] /api/food/db failed:', err);
    return {categories:[], foods:[]};
  });
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
    const r = await fetch(`/api/food/db?${params}`).then(res => res.json()).catch(err => {
      console.error('[Food] search failed:', err);
      return {foods:[], custom:[]};
    });
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
      return `<div class="food-result-row" onclick="selectFoodItem(${json})">
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
          ${f.is_custom ? `<button style="font-size:10px;color:var(--red-400);background:none;border:none;cursor:pointer;margin-top:2px" onclick="event.stopPropagation();deleteCustomFood('${f.id}')">✕ remove</button>` : ''}
        </div>
      </div>`;
    }).join('');
  }, 150);
}

function selectFoodItem(food) {
  selectedFoodItem = food;
  const col = document.getElementById('food-add-col');
  if (!col) return;

  const scale = (food.serving_g || 100) / 100;
  const cal   = Math.round((food.calories || food.cal || 0) * scale);
  const prot  = Math.round(food.protein * scale * 10)/10;
  const carbs = Math.round(food.carbs * scale * 10)/10;
  const fat   = Math.round(food.fat  * scale * 10)/10;
  const fiber = Math.round((food.fiber||0) * scale * 10)/10;

  const macros = [
    { label:'Protein', val:prot,  max:40, color:'#2563EB' },
    { label:'Carbs',   val:carbs, max:80, color:'#D97706' },
    { label:'Fat',     val:fat,   max:40, color:'#7C3AED' },
    { label:'Fiber',   val:fiber, max:15, color:'#16A34A' },
  ];

  // Smart quantity mode
  const qtyMode  = FOOD_QTY_MODE[food.id] || 'gram';
  const servingG = food.serving_g || 100;

  // Unit toggle state — stored on window so toggle function can access it
  window._qtyActiveUnit = qtyMode === 'gram' ? 'gram' : 'primary';

  const buildQtyUI = () => {
    // For gram-only foods: simple single input
    if (qtyMode === 'gram') {
      return `<div class="form-group" style="margin-bottom:12px">
        <label class="form-label">Quantity</label>
        <div class="food-qty-single-row">
          <input type="number" class="form-input" id="food-qty-input"
                 value="${servingG}" min="1" step="5"
                 oninput="updateFoodPreview(this.value)">
          <span class="food-qty-unit-badge">g</span>
        </div>
      </div>`;
    }

    // For dual-unit foods: toggle on top, one input below
    let unit1, unit2, step1, step2, default1, hint;
    if (qtyMode === 'scoop') {
      const ul = food.serving_unit || 'scoop';
      unit1 = ul + 's'; unit2 = 'g';
      step1 = 0.5; step2 = 1; default1 = 1;
      hint = `1 ${ul} = ${servingG}g`;
    } else if (qtyMode === 'cup') {
      unit1 = 'cups'; unit2 = 'ml';
      step1 = 0.25; step2 = 10;
      default1 = Math.round(servingG / 240 * 4) / 4 || 1;
      hint = '1 cup = 240ml';
    } else { // count
      unit1 = 'pcs'; unit2 = 'g';
      step1 = 1; step2 = 1; default1 = 1;
      hint = '1 pc ≈ ' + servingG + 'g';
    }

    return '<div class="form-group" style="margin-bottom:12px">' +
      '<div class="food-qty-header">' +
        '<label class="form-label" style="margin:0">Quantity</label>' +
        '<div class="food-unit-toggle" id="food-unit-toggle">' +
          '<button class="fut-btn active" id="fut-btn-primary" onclick="switchQtyUnit(\'primary\',' + servingG + ',\'' + qtyMode + '\')">' + unit1 + '</button>' +
          '<button class="fut-btn" id="fut-btn-secondary" onclick="switchQtyUnit(\'secondary\',' + servingG + ',\'' + qtyMode + '\')">' + unit2 + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="food-qty-single-row">' +
        '<input type="number" class="form-input" id="food-qty-input"' +
               ' value="' + default1 + '" min="0.25" step="' + step1 + '"' +
               ' oninput="updateFoodPreviewSmart(this.value,\'primary\',' + servingG + ',\'' + qtyMode + '\')">' +
        '<span class="food-qty-unit-badge" id="food-qty-unit-badge">' + unit1 + '</span>' +
      '</div>' +
      '<div class="food-qty-hint" id="food-qty-hint">' + hint + '</div>' +
    '</div>';
  };

  const mealBtns = MEAL_TYPES.map(m => `
    <button type="button" class="meal-type-btn ${selectedMealType===m.id?'selected':''}"
      onclick="selectMealType('${m.id}')">${m.icon} ${m.label}</button>`).join('');

  col.innerHTML = `<div class="food-add-form">
    <div class="food-add-header">
      <div class="food-add-emoji">${food.emoji || '🍽️'}</div>
      <div>
        <div class="food-add-name">${escHtml(food.name)}</div>
        <div class="food-add-cat">${food.category}</div>
      </div>
    </div>
    <div class="nutrient-preview">
      <div style="font-size:20px;font-weight:700;font-family:'DM Serif Display',serif;color:var(--gray-900);margin-bottom:10px" id="fp-cal-preview">${cal} kcal</div>
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
    <button class="btn-primary" style="width:100%" onclick="logSelectedFood()">
      Add to ${MEAL_TYPES.find(m=>m.id===selectedMealType)?.label || 'Meal'}
    </button>
  </div>`;
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
    if (mode === 'scoop' || mode === 'count') return Math.round(grams / servingG * 10) / 10;
    if (mode === 'cup')                       return Math.round(grams / 240 * 4) / 4;
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
  if (badge) {
    if (targetUnit === 'primary') {
      badge.textContent = mode === 'scoop' ? (window._foodScoopUnit || 'scoops')
                        : mode === 'cup'   ? 'cups' : 'pcs';
    } else {
      badge.textContent = mode === 'cup' ? 'ml' : 'g';
    }
  }
  if (hint) {
    if (targetUnit === 'primary') {
      hint.textContent = mode === 'scoop' ? '1 scoop = ' + servingG + 'g'
                       : mode === 'cup'   ? '1 cup = 240ml'
                       : '1 pc ≈ ' + servingG + 'g';
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
  [['protein',prot,40,'#2563EB'],['carbs',carbs,80,'#D97706'],['fat',fat,40,'#7C3AED'],['fiber',fiber,15,'#16A34A']].forEach(([name,val,max]) => {
    const bar = document.getElementById(`fp-bar-${name}`);
    const valEl = document.getElementById(`fp-val-${name}`);
    if (bar) bar.style.width = Math.min(val/max*100,100).toFixed(0)+'%';
    if (valEl) valEl.textContent = val+'g';
  });
}

async function logSelectedFood() {
  if (!selectedFoodItem) return;
  const unitEl    = document.getElementById('food-qty-input');
  const mode      = FOOD_QTY_MODE[selectedFoodItem?.id] || 'gram';
  const servG     = selectedFoodItem?.serving_g || 100;
  const activeUnit= window._qtyActiveUnit || (mode === 'gram' ? 'gram' : 'primary');
  const qty       = _toGrams(parseFloat(unitEl?.value) || 1, activeUnit, mode, servG);
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

async function removeFoodLog(id) {
  await fetch(`/api/food/log/${id}`, { method: 'DELETE' });
  showToast('Removed from log');
  loadFoodTracker();
  loadDashboard();
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
  if (prev && t) {
    prev.style.display = 'block';
    setText('prev-bmr',    `${t.bmr} kcal/day`);
    setText('prev-tdee',   `${t.tdee} kcal/day`);
    setText('prev-target', `${t.target_calories} kcal/day`);
  }
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
  if (fp) fp.value = new Date().toISOString().split('T')[0];
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

const MOOD_EMOJI = {
  neutral:'😐', happy:'😊', excited:'🤩', calm:'😌',
  anxious:'😰', tired:'😴', sad:'😞', angry:'😤'
};
const MOOD_COLOR = {
  neutral:'#0E8F7E', happy:'#22C55E', excited:'#F59E0B', calm:'#06B6D4',
  anxious:'#8B5CF6', tired:'#9CA3AF', sad:'#3B82F6', angry:'#EF4444'
};

let currentThoughtsDate = new Date().toISOString().split('T')[0];
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
    const today = new Date().toISOString().split('T')[0];
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
          <span class="thought-mood-badge">${MOOD_EMOJI[mood] || '😐'}</span>
          <span class="thought-time">${time}</span>
        </div>
        <div class="thought-card-actions">
          <button class="thought-action-btn" onclick="startEditThought('${t.id}')" title="Edit">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="thought-action-btn del" onclick="deleteThought('${t.id}')" title="Delete">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>
      <div class="thought-content" id="tc-${t.id}">${escHtml(t.content)}</div>
      <div class="thought-edit-wrap" id="te-${t.id}" style="display:none">
        <textarea class="thought-edit-area" id="tea-${t.id}">${escHtml(t.content)}</textarea>
        <div class="thought-edit-actions">
          <button class="btn-outline" style="padding:5px 12px;font-size:12px" onclick="cancelEditThought('${t.id}')">Cancel</button>
          <button class="btn-primary" style="padding:5px 12px;font-size:12px" onclick="saveEditThought('${t.id}','${mood}')">Save</button>
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
      ? `<div class="week-mood-dot" title="${key}"><div class="week-mood-emoji">${MOOD_EMOJI[mood]}</div><div class="week-mood-day">${days[i]}</div></div>`
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
    showToast(`Thought saved ${MOOD_EMOJI[selectedMood]}`, 'success');
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

async function deleteThought(id) {
  if (!confirm('Delete this thought?')) return;
  await fetch(`/api/thoughts/${id}`, { method: 'DELETE' });
  showToast('Thought deleted');
  loadThoughts();
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
  const today   = new Date().toISOString().split('T')[0];
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
  const today = new Date().toISOString().split('T')[0];
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
    <div class="todo-checkbox ${isDone?'checked':''}" onclick="toggleTodo('${t.id}')"></div>
    <div class="todo-content">
      <div class="todo-title">${escHtml(t.title)}</div>
      ${t.notes ? `<div class="todo-notes">${escHtml(t.notes)}</div>` : ''}
      <div class="todo-meta-row">${metaHtml}</div>
    </div>
    <div class="todo-card-actions">
      ${!isDone ? `<button class="todo-act-btn" onclick="openEditTodo('${t.id}')" title="Edit">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      </button>` : ''}
      <button class="todo-act-btn del" onclick="deleteTodo('${t.id}')" title="Delete">
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

async function deleteTodo(id) {
  const todo = allTodos.find(t => t.id === id);
  if (!confirm(`Delete "${todo?.title || 'this task'}"?`)) return;
  await fetch(`/api/todos/${id}`, { method:'DELETE' });
  showToast('Task deleted');
  loadTodos();
}

// ── Reminder notifications ──────────────────────────────────────────────────

function scheduleTodoBrowserNotif(todo, reminderAt) {
  if (Notification.permission !== 'granted') return;
  const ms = new Date(reminderAt) - Date.now();
  if (ms <= 0 || ms > 86400000) return; // only schedule within 24h
  setTimeout(() => {
    new Notification('📋 MediScan Reminder', {
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
      new Notification('📋 MediScan Reminder', {
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
  const r = await fetch('/api/wellness/today').then(r => r.json()).catch(() => null);
  if (!r) return;

  // Hydration
  const h = r.hydration;
  const hGoal = h.goal_ml || 2450;
  const hPct  = h.pct != null ? h.pct : Math.min(Math.round((h.total_ml || 0) / hGoal * 100), 100);
  setText('dws-hydration', `${h.total_ml || 0} ml`);
  const hBar = document.getElementById('dws-hydration-bar');
  if (hBar) hBar.style.width = hPct + '%';

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
  const today  = r.date || new Date().toISOString().split('T')[0];
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
        <div class="habit-check-row ${h.done_today ? 'is-done' : ''}" onclick="toggleHabit('${h.id}','${today}')">
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
      <div class="habit-add-card" onclick="openHabitModal()">
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
        <button class="hc2-delete" onclick="event.stopPropagation();deleteHabit('${h.id}')" title="Remove habit">
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
              onclick="toggleHabit('${h.id}','${today}')"
              style="--habit-color:${h.color}">
        ${h.done_today
          ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg> Done today — tap to undo`
          : `Mark done today`}
      </button>
    </div>`;
  }).join('') +
  // "+" add card at the end
  `<div class="habit-add-card" onclick="openHabitModal()">
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
  } else {
    if (card) card.style.opacity = '1';
    showToast('Could not update habit', 'error');
  }
}

async function deleteHabit(id) {
  if (!confirm('Remove this habit and all its history?')) return;
  await fetch(`/api/habits/${id}`, {method: 'DELETE'});
  showToast('Habit removed');
  loadHabits();
  loadWellnessStrip();
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
  // Calculate pct client-side as fallback if server doesn't send it
  const goalMl = r.goal_ml || Math.round(2450);   // 35ml/kg × 70kg default
  const pct    = r.pct != null ? r.pct : Math.min(Math.round(r.total_ml / goalMl * 100), 100);
  if (fill)    fill.style.height = pct + '%';
  if (pctEl)   pctEl.textContent = pct + '%';
  if (lvlEl)   lvlEl.textContent = (r.total_ml || 0) + 'ml';
  if (badgeEl) badgeEl.textContent = `Goal: ${goalMl}ml`;

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

function openGlobalSearch() {
  const wrap = document.getElementById('global-search-wrap');
  if (!wrap) return;
  wrap.style.display = 'flex';
  setTimeout(() => document.getElementById('global-search-input')?.focus(), 50);
  // Show hints on open
  document.getElementById('gs-hints').style.display = 'block';
  document.getElementById('global-search-results').innerHTML = '';
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
        if (s.type==='thought')  { title=item.content?.slice(0,90)+(item.content?.length>90?'…':''); meta=`${item.date_key} · ${MOOD_EMOJI[item.mood]||''} ${item.mood||''}`; }
        if (s.type==='symptom')  { title=item.name; meta=`${item.date_key} · ${(item.time_of_day||'').replace('_',' ')} · ${item.severity}/10 severity${item.notes?' · '+item.notes:''}`; }
        if (s.type==='todo')     {
          title=item.title;
          meta=`${item.priority} priority${item.due_date?' · Due '+item.due_date:''}`;
          badge=`<span class="gs-result-badge ${item.status}">${item.status}</span>`;
        }
        if (s.type==='activity') { title=item.name||item.type; meta=`${item.date} · ${item.duration||0}min · ${item.calories||0} kcal${item.distance?' · '+item.distance+'km':''}`; }
        if (s.type==='report')   { title=item.filename||'Report'; meta=`${item.date||''} · ${item.severity||''}`; }
        if (s.type==='medicine') { title=item.name; meta=`${item.dosage} ${item.unit} · ${(item.frequency||'').replace('_',' ')}`; }

        return `<div class="gs-result-row" onclick="closeGlobalSearch();switchView('${VIEW_MAP[s.type]||s.type}')">
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
    medicine: {bg:'#EFF6FF', border:'#BFDBFE', icon:'💊'},
    refill:   {bg:'#FFFBEB', border:'#FDE68A', icon:'⚠️'},
    todo:     {bg:'#ECFDF5', border:'#A7F3D0', icon:'✅'},
    symptom:  {bg:'#FEF2F2', border:'#FECACA', icon:'🩺'},
    fitness:  {bg:'#F5F3FF', border:'#DDD6FE', icon:'🏃'},
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
      return `<div class="notif-row ${n.read?'':'unread'}" onclick="markNotifRead('${n.id}')">
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
      const names = r.map(m=>`<strong>${m.name}</strong> (${m.days_left}d left)`).join(', ');
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
  const overall    = scores.length ? Math.round(scores.reduce((a,b)=>a+b)/scores.length) : 0;
  const overallColor = overall >= 75 ? '#22C55E' : overall >= 50 ? '#F59E0B' : '#EF4444';
  const overallLabel = overall >= 75 ? 'On track! 🎯' : overall >= 50 ? 'Getting there 💪' : 'Needs focus 📋';

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
  const SLEEP_COLORS = {1:'#EF4444',2:'#F59E0B',3:'#D1D5DB',4:'#34D399',5:'#0E8F7E'};
  const sleepDots = sleepDays.map(s => {
    const h = Math.min(s.h/9, 1) * 100;
    return `<div class="prog-sleep-dot" style="height:${Math.max(h,8)}%;background:${SLEEP_COLORS[s.q]||'#D1D5DB'}" title="${s.date}: ${s.h}h · Quality ${s.q}/5"></div>`;
  }).join('');
  const noSleepMsg = sleepDays.length === 0 ? `<div style="padding:20px 0;text-align:center;color:var(--gray-300);font-size:13px">No sleep data — log from Thoughts page</div>` : '';

  // Calorie adherence bars
  const calDays = daysSlice(r.nutrition?.daily) || [];
  const targetCal = r.nutrition?.target_daily || 2000;
  const calBars = calDays.map((d,i) => {
    const pct = d.cal > 0 ? Math.min(Math.round((d.cal/targetCal)*100), 150) : 0;
    const color = pct > 115 ? '#EF4444' : pct > 95 ? '#22C55E' : pct > 70 ? '#F59E0B' : 'var(--gray-200)';
    return `<div class="prog-cal-bar ${pct>115?'over':''}" style="height:${Math.max(pct,4)}%;background:${color}" title="${d.date}: ${d.cal} kcal (${pct}% of goal)"></div>`;
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

  // Status badge helper
  const badge = (pct, good=70, warn=40) => {
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
        <div class="prog-section-meta">${r.targets?.target_calories||'—'} kcal/day · ${r.targets?.protein_g||'—'}g protein</div>
      </div>
      <div class="prog-section-body" style="display:flex;align-items:center;gap:20px">
        <div style="font-size:22px;font-weight:700;color:var(--gray-900)">${GOAL_LABELS[r.profile?.goal]||'—'}</div>
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
          ${badge(workoutPct)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${p==='month'?r.workouts?.this_month:workoutDays.filter(d=>d.cal>0).length}</span>
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
          ${badge(sleepPct, 90, 70)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${sleepAvg||'—'}</span>
            <span style="font-size:14px;color:var(--gray-400)">h avg · target 7.5h</span>
          </div>
          ${noSleepMsg}
          ${sleepDays.length ? `<div style="display:flex;align-items:flex-end;gap:3px;height:60px">${sleepDots}</div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--gray-300);margin-top:4px">
            <span>😩 Poor</span>
            <span style="display:flex;gap:8px">
              <span style="width:10px;height:10px;border-radius:2px;background:#EF4444;display:inline-block"></span>Poor
              <span style="width:10px;height:10px;border-radius:2px;background:#34D399;display:inline-block"></span>Good
              <span style="width:10px;height:10px;border-radius:2px;background:#0E8F7E;display:inline-block"></span>Great
            </span>
          </div>` : ''}
        </div>
      </div>

      <div class="prog-section">
        <div class="prog-section-head">
          <div class="prog-section-title">🍽️ Calorie Adherence</div>
          ${badge(calPct)}
        </div>
        <div class="prog-section-body">
          <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:12px">
            <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${calPct}%</span>
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
        ${badge(habitPct)}
      </div>
      <div class="prog-section-body">
        ${noHabitMsg}
        ${habits.length ? `<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:16px">
          <span style="font-size:32px;font-weight:800;font-family:'DM Serif Display',serif;color:var(--gray-900)">${habitPct}%</span>
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
            <button class="btn-outline" style="font-size:12px;padding:5px 12px" onclick="openRestockModal('${m.id}','${escHtml(m.name)}',${m.pill_count},${m.pills_per_dose||1},${m.refill_threshold||7})">Restock →</button>
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

  // Compute overall health score (0–100) from available data
  let scoreComponents = [], scoreTotal = 0;
  if (r.sleep?.avg_hours) {
    const s = Math.min(r.sleep.avg_hours / 7.5, 1) * 100;
    scoreComponents.push(s); scoreTotal += s;
  }
  if (r.fitness?.workout_days != null) {
    const s = Math.min(r.fitness.workout_days / 4, 1) * 100;
    scoreComponents.push(s); scoreTotal += s;
  }
  if (r.nutrition?.adherence_pct != null) {
    const s = Math.min(r.nutrition.adherence_pct, 100);
    scoreComponents.push(s); scoreTotal += s;
  }
  if (r.habits?.completion_pct != null) {
    scoreComponents.push(r.habits.completion_pct); scoreTotal += r.habits.completion_pct;
  }
  const healthScore = scoreComponents.length ? Math.round(scoreTotal / scoreComponents.length) : null;
  const scoreColor = healthScore >= 80 ? '#22C55E' : healthScore >= 60 ? '#F59E0B' : '#EF4444';
  const scoreLabel = healthScore >= 80 ? 'Excellent' : healthScore >= 60 ? 'Good' : healthScore >= 40 ? 'Fair' : 'Needs attention';

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
      ${healthScore!=null ? `<div class="report-score-chip" style="background:${scoreColor}18;color:${scoreColor};border-color:${scoreColor}40">
        <span style="font-weight:800">${healthScore}</span>/100 · ${scoreLabel}
      </div>` : ''}
    </div>
    <button class="btn-primary" onclick="printReport()">
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
      <div class="rpt-header-right">
        ${healthScore != null ? `
        <div class="rpt-score-circle" style="--score-color:${scoreColor}">
          <svg viewBox="0 0 80 80" class="rpt-score-ring">
            <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="7"/>
            <circle cx="40" cy="40" r="34" fill="none" stroke="${scoreColor}" stroke-width="7"
              stroke-dasharray="${2*Math.PI*34}" stroke-dashoffset="${2*Math.PI*34*(1-healthScore/100)}"
              stroke-linecap="round" transform="rotate(-90 40 40)"/>
          </svg>
          <div class="rpt-score-inner">
            <div class="rpt-score-num">${healthScore}</div>
            <div class="rpt-score-sub">Health score</div>
          </div>
        </div>` : ''}
      </div>
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
          <div class="rpt-detail-row"><span>Target</span><span>7.5h / night</span></div>
          ${r.sleep?.avg_hours ? `<div class="rpt-detail-row ${r.sleep.avg_hours>=7?'rpt-row--good':'rpt-row--warn'}"><span>Status</span><span>${r.sleep.avg_hours>=7?'✅ On target':'⚠️ Below target'}</span></div>` : ''}
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
          <div class="rpt-detail-row"><span>Target</span><span>4 days / week</span></div>
          ${r.fitness?.workout_days!=null ? `<div class="rpt-detail-row ${r.fitness.workout_days>=4?'rpt-row--good':'rpt-row--warn'}"><span>Status</span><span>${r.fitness.workout_days>=4?'✅ On target':'⚠️ Below target'}</span></div>` : ''}
        </div>
      </div>

      <!-- Nutrition -->
      <div class="rpt-section">
        <div class="rpt-section-head">🍽️ Nutrition</div>
        <div class="rpt-big">${r.nutrition?.adherence_pct != null ? Math.round(r.nutrition.adherence_pct)+'%' : '—'}<span class="rpt-unit">adherence</span></div>
        <div class="rpt-sub">${(r.nutrition?.calories_eaten||0).toLocaleString()} kcal consumed</div>
        ${r.nutrition?.adherence_pct != null ? metricBar(r.nutrition.adherence_pct, 100, '#FB923C') : ''}
        <div class="rpt-detail-rows">
          <div class="rpt-detail-row"><span>Weekly target</span><span>${(r.nutrition?.weekly_target||0).toLocaleString()} kcal</span></div>
          <div class="rpt-detail-row"><span>Daily target</span><span>${(r.nutrition?.target||0).toLocaleString()} kcal/day</span></div>
          <div class="rpt-detail-row"><span>Avg hydration</span><span>${r.nutrition?.avg_hydration_ml||0} ml/day</span></div>
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
        <strong>For your doctor:</strong> This is a personal health summary generated by MediScan Health OS.
        Data is self-reported and should be reviewed alongside clinical assessments.
      </div>
      <div class="rpt-footer-brand">MediScan Health OS · ${generatedStr}</div>
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
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#fff;color:#1a1a1a;padding:28px}
  .rpt-doc{max-width:820px;margin:0 auto}

  /* Header */
  .rpt-header{display:flex;align-items:flex-start;justify-content:space-between;
    background:linear-gradient(135deg,#0D1117,#0A2E28);border-radius:12px;
    padding:28px 32px;margin-bottom:24px;color:#fff}
  .rpt-patient-name{font-size:24px;font-weight:700;margin-bottom:6px}
  .rpt-period{font-size:14px;color:rgba(255,255,255,.6);margin-bottom:3px}
  .rpt-generated{font-size:12px;color:rgba(255,255,255,.4);margin-bottom:10px}
  .rpt-goal-chip{display:inline-block;padding:3px 12px;border-radius:99px;
    background:rgba(255,255,255,.1);font-size:12px;color:rgba(255,255,255,.7)}
  .rpt-score-circle{position:relative;width:80px;height:80px}
  .rpt-score-ring{position:absolute;inset:0;width:80px;height:80px}
  .rpt-score-inner{position:absolute;inset:0;display:flex;flex-direction:column;
    align-items:center;justify-content:center}
  .rpt-score-num{font-size:22px;font-weight:800;color:#fff}
  .rpt-score-sub{font-size:9px;color:rgba(255,255,255,.5);text-transform:uppercase;letter-spacing:.05em}

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
  .rpt-row--good span:last-child{color:#16a34a;font-weight:600}
  .rpt-row--warn span:last-child{color:#d97706;font-weight:600}
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