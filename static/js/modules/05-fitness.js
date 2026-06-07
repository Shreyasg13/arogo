// Auto-generated module — see static/js/app.js for full app
// Part of MediScan Health OS

// Fitness: activity log, gym form, stats, energy balance

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